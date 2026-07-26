from __future__ import annotations

import base64
import os
import socket
import struct
import subprocess
import sys
import time
from urllib.parse import urlsplit

import pytest

from verigym.runtimes.docker.errors import DockerContainerError
from verigym.runtimes.docker.stdio_broker import LoopbackWebSocketStdioBroker


def _echo_process() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            (
                "import sys\n"
                "for line in sys.stdin.buffer:\n"
                " sys.stdout.buffer.write(line)\n"
                " sys.stdout.buffer.flush()\n"
            ),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def _connect(url: str) -> socket.socket:
    parsed = urlsplit(url)
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port is not None
    client = socket.create_connection((parsed.hostname, parsed.port), timeout=2)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    client.sendall(
        (
            f"GET {parsed.path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
    )
    response = bytearray()
    while b"\r\n\r\n" not in response:
        response.extend(client.recv(4096))
    assert response.startswith(b"HTTP/1.1 101 ")
    return client


def _send_masked(client: socket.socket, payload: bytes, *, opcode: int = 0x1) -> None:
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, 0x80 | length))
    elif length <= 0xFFFF:
        header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    client.sendall(header + mask + masked)


def _recv_exact(client: socket.socket, size: int) -> bytes:
    output = bytearray()
    while len(output) < size:
        output.extend(client.recv(size - len(output)))
    return bytes(output)


def _receive(client: socket.socket) -> tuple[int, bytes]:
    first, second = _recv_exact(client, 2)
    assert second & 0x80 == 0
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(client, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(client, 8))[0]
    return first & 0x0F, _recv_exact(client, length)


def test_loopback_broker_translates_one_masked_websocket_client_to_stdio() -> None:
    broker = LoopbackWebSocketStdioBroker(_echo_process(), max_output_bytes=64 * 1024)
    broker.start()
    client = _connect(broker.url)
    payload = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
    _send_masked(client, payload)
    opcode, observed = _receive(client)
    assert opcode == 0x1
    assert observed == payload
    result = broker.stop()
    assert result.stopped
    assert result.process_group_cleaned
    assert not result.stderr
    client.close()


def test_loopback_broker_rejects_unmasked_client_frames() -> None:
    broker = LoopbackWebSocketStdioBroker(_echo_process(), max_output_bytes=64 * 1024)
    broker.start()
    client = _connect(broker.url)
    client.sendall(bytes((0x81, 2)) + b"{}")
    deadline = time.monotonic() + 2
    while True:
        try:
            broker.assert_healthy()
        except DockerContainerError:
            break
        if time.monotonic() >= deadline:
            pytest.fail("broker did not reject the unmasked frame")
        time.sleep(0.01)
    with pytest.raises(DockerContainerError, match="stdio broker failed"):
        broker.stop()
    client.close()
