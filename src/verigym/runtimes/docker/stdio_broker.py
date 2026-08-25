"""Loopback-only WebSocket bridge to a container's stdio exec-server."""

from __future__ import annotations

import base64
import hashlib
import os
import selectors
import signal
import socket
import struct
import subprocess
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, cast

from verigym.runtimes.docker.errors import DockerContainerError

if TYPE_CHECKING:
    from verigym.hwe.codex_collector import HweExecProtocolCollector

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_HANDSHAKE_BYTES = 16 * 1024
_MAX_FRAME_BYTES = 1024 * 1024
_PROTOCOL_SETTLE_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class BrokerResult:
    stderr: bytes
    stderr_truncated: bool
    process_group_cleaned: bool
    stopped: bool
    protocol_records: tuple[dict[str, object], ...] = ()


class LoopbackWebSocketStdioBroker:
    """Expose one stdio JSON-RPC process to one loopback WebSocket client."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        max_output_bytes: int,
        protocol_collector: HweExecProtocolCollector | None = None,
    ) -> None:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise ValueError("stdio broker requires a process with all three pipes")
        self._process = process
        self._max_output_bytes = max_output_bytes
        self._protocol_collector = protocol_collector
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(1.0)
        self._path = f"/verigym-{os.urandom(16).hex()}"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._client: socket.socket | None = None
        self._error: BaseException | None = None
        self._stderr = bytearray()
        self._stderr_truncated = False
        self._send_lock = threading.Lock()

    @property
    def url(self) -> str:
        port = self._listener.getsockname()[1]
        return f"ws://127.0.0.1:{port}{self._path}"

    def start(self) -> None:
        self._thread.start()

    def assert_healthy(self) -> None:
        if self._error is not None:
            reason = getattr(self._error, "reason", None)
            raise DockerContainerError(
                f"external-agent stdio broker failed: {type(self._error).__name__}",
                subreason=(f"hwe_protocol_{reason}" if reason else "stdio_broker_failed"),
            ) from self._error

    def stop(self) -> BrokerResult:
        protocol_records: tuple[dict[str, object], ...] = ()
        protocol_error: RuntimeError | None = None
        if self._protocol_collector is not None:
            try:
                settled = self._protocol_collector.wait_for_settled(
                    timeout_s=_PROTOCOL_SETTLE_TIMEOUT_S
                )
                protocol_records = tuple(
                    {field: getattr(record, field) for field in record.__dataclass_fields__}
                    for record in settled
                )
            except RuntimeError as exc:
                protocol_error = exc
        self._stop.set()
        client = self._client
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
        try:
            self._listener.close()
        except OSError:
            pass
        self._close_process_stdin()
        self._terminate_process_group()
        self._thread.join(timeout=5)
        stopped = not self._thread.is_alive()
        if protocol_error is not None:
            reason = getattr(protocol_error, "reason", "failed_closed")
            completed = (
                self._protocol_collector.completed_records()
                if self._protocol_collector is not None
                else ()
            )
            raise DockerContainerError(
                f"external-agent HWE protocol failed: {protocol_error}",
                subreason=f"hwe_protocol_{reason}",
                details={
                    "broker_stopped": stopped,
                    "process_group_cleaned": self._process_group_absent(),
                    "protocol_records": tuple(
                        {field: getattr(record, field) for field in record.__dataclass_fields__}
                        for record in completed
                    ),
                },
            ) from protocol_error
        self.assert_healthy()
        return BrokerResult(
            stderr=bytes(self._stderr),
            stderr_truncated=self._stderr_truncated,
            process_group_cleaned=self._process_group_absent(),
            stopped=stopped,
            protocol_records=protocol_records,
        )

    def _serve(self) -> None:
        stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        stderr_thread.start()
        try:
            while not self._stop.is_set():
                try:
                    client, _address = self._listener.accept()
                    break
                except TimeoutError as exc:
                    if self._process.poll() is not None:
                        raise RuntimeError(
                            "container exec-server exited before broker connection"
                        ) from exc
            else:
                return
            self._client = client
            client.settimeout(5.0)
            self._handshake(client)
            client.settimeout(None)
            self._ready.set()
            inbound = threading.Thread(target=self._client_to_process, args=(client,), daemon=True)
            inbound.start()
            self._process_to_client(client)
            self._stop.set()
            inbound.join(timeout=2)
        except BaseException as exc:
            if not self._stop.is_set():
                self._error = exc
            self._stop.set()
        finally:
            self._close_process_stdin()
            stderr_thread.join(timeout=2)

    def _handshake(self, client: socket.socket) -> None:
        request = bytearray()
        while b"\r\n\r\n" not in request:
            chunk = client.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket client closed during handshake")
            request.extend(chunk)
            if len(request) > _MAX_HANDSHAKE_BYTES:
                raise RuntimeError("WebSocket handshake exceeded its size bound")
        header = bytes(request).decode("ascii", errors="strict")
        lines = header.split("\r\n")
        request_line = lines[0].split()
        if len(request_line) != 3 or request_line[:2] != ["GET", self._path]:
            raise RuntimeError("WebSocket broker path mismatch")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                continue
            name, separator, value = line.partition(":")
            if not separator:
                raise RuntimeError("malformed WebSocket request header")
            lowered = name.strip().lower()
            if lowered in headers:
                raise RuntimeError("duplicate WebSocket request header")
            headers[lowered] = value.strip()
        if headers.get("upgrade", "").lower() != "websocket":
            raise RuntimeError("WebSocket Upgrade header is missing")
        if "upgrade" not in headers.get("connection", "").lower():
            raise RuntimeError("WebSocket Connection header is missing")
        key = headers.get("sec-websocket-key")
        if key is None:
            raise RuntimeError("WebSocket key is missing")
        accept = base64.b64encode(
            hashlib.sha1((key + _WEBSOCKET_GUID).encode("ascii")).digest()
        ).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        client.sendall(response.encode("ascii"))

    def _client_to_process(self, client: socket.socket) -> None:
        assert self._process.stdin is not None
        try:
            while not self._stop.is_set():
                opcode, payload = self._read_frame(client)
                if opcode == 0x8:
                    return
                if opcode == 0x9:
                    self._send_frame(client, payload, opcode=0xA)
                    continue
                if opcode == 0xA:
                    continue
                if opcode not in {0x1, 0x2}:
                    raise RuntimeError("unsupported WebSocket opcode")
                if not payload.endswith(b"\n"):
                    payload += b"\n"
                if self._protocol_collector is not None:
                    payload = self._protocol_collector.client_message(payload)
                self._process.stdin.write(payload)
                self._process.stdin.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            if not self._stop.is_set():
                self._stop.set()
        except BaseException as exc:
            if not self._stop.is_set():
                self._error = exc
                self._stop.set()

    def _process_to_client(self, client: socket.socket) -> None:
        assert self._process.stdout is not None
        selector = selectors.DefaultSelector()
        descriptor = self._process.stdout.fileno()
        selector.register(descriptor, selectors.EVENT_READ)
        retained = 0
        buffered = bytearray()
        try:
            while not self._stop.is_set():
                ready = selector.select(timeout=0.25)
                if not ready:
                    if self._process.poll() is not None and not buffered:
                        return
                    continue
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    if buffered:
                        raise RuntimeError("exec-server emitted a partial JSON-RPC frame")
                    return
                buffered.extend(chunk)
                while True:
                    newline = buffered.find(b"\n")
                    if newline < 0:
                        if len(buffered) > _MAX_FRAME_BYTES:
                            raise RuntimeError("exec-server JSON-RPC frame exceeded its size bound")
                        break
                    line = bytes(buffered[: newline + 1])
                    del buffered[: newline + 1]
                    if len(line) > _MAX_FRAME_BYTES:
                        raise RuntimeError("exec-server JSON-RPC frame exceeded its size bound")
                    retained += len(line)
                    if retained > self._max_output_bytes:
                        raise RuntimeError("exec-server output exceeded its aggregate bound")
                    transformed: bytes | tuple[bytes, ...] | None = line
                    if self._protocol_collector is not None:
                        transformed = self._protocol_collector.server_message(line)
                    if transformed is None:
                        continue
                    frames = transformed if isinstance(transformed, tuple) else (transformed,)
                    for frame in frames:
                        self._send_frame(client, frame.rstrip(b"\r\n"), opcode=0x1)
        finally:
            selector.close()

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        while True:
            chunk = self._process.stderr.read(8192)
            if not chunk:
                return
            remaining = self._max_output_bytes - len(self._stderr)
            if remaining > 0:
                self._stderr.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self._stderr_truncated = True

    @staticmethod
    def _read_frame(client: socket.socket) -> tuple[int, bytes]:
        header = _recv_exact(client, 2)
        first, second = header
        if first & 0x80 == 0:
            raise RuntimeError("fragmented WebSocket frames are forbidden")
        opcode = first & 0x0F
        if second & 0x80 == 0:
            raise RuntimeError("client WebSocket frames must be masked")
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _recv_exact(client, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _recv_exact(client, 8))[0]
        if length > _MAX_FRAME_BYTES:
            raise RuntimeError("WebSocket frame exceeded its size bound")
        mask = _recv_exact(client, 4)
        payload = bytearray(_recv_exact(client, length))
        for index in range(length):
            payload[index] ^= mask[index % 4]
        return opcode, bytes(payload)

    def _send_frame(self, client: socket.socket, payload: bytes, *, opcode: int) -> None:
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = bytes((first, length))
        elif length <= 0xFFFF:
            header = bytes((first, 126)) + struct.pack("!H", length)
        else:
            header = bytes((first, 127)) + struct.pack("!Q", length)
        with self._send_lock:
            client.sendall(header + payload)

    def _close_process_stdin(self) -> None:
        stream = cast(BinaryIO | None, self._process.stdin)
        if stream is not None and not stream.closed:
            try:
                stream.close()
            except OSError:
                pass

    def _terminate_process_group(self) -> None:
        if self._process.poll() is not None:
            return
        try:
            os.killpg(self._process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self._process.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(self._process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return

    def _process_group_absent(self) -> bool:
        try:
            os.killpg(self._process.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False


def _recv_exact(client: socket.socket, size: int) -> bytes:
    value = bytearray()
    while len(value) < size:
        chunk = client.recv(size - len(value))
        if not chunk:
            raise ConnectionError("WebSocket connection closed")
        value.extend(chunk)
    return bytes(value)


__all__ = ["BrokerResult", "LoopbackWebSocketStdioBroker"]
