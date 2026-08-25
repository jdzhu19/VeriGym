from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from verigym.hwe.codex_collector import HweExecProtocolCollector
from verigym.hwe.observation import HweObservationCompactor
from verigym.hwe.private_audit import HweRawArtifactWriter
from verigym.runtimes.docker.errors import DockerContainerError
from verigym.runtimes.docker.stdio_broker import LoopbackWebSocketStdioBroker


class _CharacterCounter:
    tokenizer_id = "tiktoken-0.7.0/o200k_base"
    tokenizer_hash = "test-tokenizer-hash"

    def count(self, text: str) -> int:
        return len(text)


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


def _delayed_response_process() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            (
                "import json,sys,time\n"
                "for line in sys.stdin.buffer:\n"
                " request=json.loads(line)\n"
                " time.sleep(0.2)\n"
                " response={'jsonrpc':'2.0','id':request['id'],'result':{}}\n"
                " sys.stdout.write(json.dumps(response)+'\\n')\n"
                " sys.stdout.flush()\n"
            ),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def _exec_server_process() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            (
                "import json,sys\n"
                "for line in sys.stdin.buffer:\n"
                " request=json.loads(line)\n"
                " method=request.get('method')\n"
                " if method=='initialized': continue\n"
                " if method=='initialize':\n"
                "  messages=[{'id':request['id'],'result':{'sessionId':'session'}}]\n"
                " elif method=='process/start':\n"
                "  pid=request['params']['processId']\n"
                "  messages=[\n"
                "   {'id':request['id'],'result':{'processId':pid}},\n"
                "   {'method':'process/output','params':{'processId':pid,'seq':1,"
                "'stream':'stdout','chunk':'cHJvdG9jb2wtb2s='}},\n"
                "   {'method':'process/exited','params':{'processId':pid,'seq':2,"
                "'exitCode':0,'sandboxDenied':False}},\n"
                "   {'method':'process/closed','params':{'processId':pid,'seq':3}},\n"
                "  ]\n"
                " else: messages=[{'id':request['id'],'result':{}}]\n"
                " for message in messages:\n"
                "  sys.stdout.write(json.dumps(message)+'\\n')\n"
                "  sys.stdout.flush()\n"
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


def test_loopback_broker_drains_pending_hwe_response_before_shutdown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "run")
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(_CharacterCounter()),
        raw_writer=writer,
    )
    broker = LoopbackWebSocketStdioBroker(
        _delayed_response_process(),
        max_output_bytes=64 * 1024,
        protocol_collector=collector,
    )
    broker.start()
    client = _connect(broker.url)
    _send_masked(
        client,
        b'{"jsonrpc":"2.0","id":1,"method":"environment/status","params":{}}',
    )
    deadline = time.monotonic() + 1
    while True:
        try:
            collector.records()
        except RuntimeError as exc:
            if "unresolved requests" in str(exc):
                break
            raise
        if time.monotonic() >= deadline:
            pytest.fail("broker did not forward the HWE request")
        time.sleep(0.01)
    result = broker.stop()
    assert result.stopped
    assert result.protocol_records[0]["method"] == "environment/status"
    assert writer.finalize()["records"] == 1
    client.close()


def test_loopback_broker_preserves_hwe_protocol_subreason_and_cleanup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(_CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    broker = LoopbackWebSocketStdioBroker(
        _echo_process(),
        max_output_bytes=64 * 1024,
        protocol_collector=collector,
    )
    broker.start()
    client = _connect(broker.url)
    _send_masked(
        client,
        b'{"jsonrpc":"2.0","id":1,"method":"fs/unknownRead","params":{}}',
    )
    deadline = time.monotonic() + 2
    while broker._error is None:  # noqa: SLF001 - assert asynchronous broker evidence
        if time.monotonic() >= deadline:
            pytest.fail("broker did not retain the HWE protocol failure")
        time.sleep(0.01)
    with pytest.raises(DockerContainerError) as captured:
        broker.stop()
    error = captured.value
    assert error.subreason == "hwe_protocol_unknown_output_bearing_method:fs/unknownRead"
    assert error.details["broker_stopped"] is True
    assert error.details["process_group_cleaned"] is True
    assert error.details["protocol_records"] == ()
    client.close()


def test_loopback_broker_replaces_exec_stream_with_one_compact_frame(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "run")
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(_CharacterCounter()),
        raw_writer=writer,
    )
    broker = LoopbackWebSocketStdioBroker(
        _exec_server_process(),
        max_output_bytes=64 * 1024,
        protocol_collector=collector,
    )
    broker.start()
    client = _connect(broker.url)
    _send_masked(
        client,
        b'{"id":1,"method":"initialize","params":{"clientName":"test"}}',
    )
    assert b"sessionId" in _receive(client)[1]
    _send_masked(client, b'{"method":"initialized","params":{}}')
    _send_masked(
        client,
        (
            b'{"id":2,"method":"process/start","params":{"processId":"p1",'
            b'"argv":["/bin/bash","-lc","printf protocol-ok"],'
            b'"cwd":"file:///workspace/repository","env":{},"tty":false,'
            b'"pipeStdin":false,"arg0":null}}'
        ),
    )
    assert b'"id":2' in _receive(client)[1]
    compact = json.loads(_receive(client)[1])
    exited = json.loads(_receive(client)[1])
    closed = json.loads(_receive(client)[1])
    assert compact["method"] == "process/output"
    assert base64.b64decode(compact["params"]["chunk"]) == b"protocol-ok"
    assert exited["method"] == "process/exited"
    assert closed["method"] == "process/closed"
    result = broker.stop()
    assert result.stopped
    assert result.process_group_cleaned
    assert [record["method"] for record in result.protocol_records] == [
        "initialize",
        "process/start",
    ]
    assert writer.finalize()["records"] == 5
    client.close()
