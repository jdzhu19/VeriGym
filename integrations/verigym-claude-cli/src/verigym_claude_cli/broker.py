"""Private Unix-socket broker from Claude MCP calls to the runtime bridge."""

from __future__ import annotations

import json
import os
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.plugin_api import CommandSpec, ExternalAgentBridge, JsonValue, PathPolicyError

from .mcp_tools import TOOL_NAMES
from .util import redact_text

_MAX_MESSAGE_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 512 * 1024


@dataclass(frozen=True)
class BrokerStats:
    tool_calls: int
    command_calls: int
    public_test_calls: int
    file_reads: int
    file_writes: int
    patches: int
    policy_failure: str | None
    infrastructure_failure: str | None


class ClaudeToolBroker:
    def __init__(
        self,
        *,
        bridge: ExternalAgentBridge,
        socket_path: Path,
        public_test_ids: tuple[str, ...],
    ) -> None:
        self._bridge = bridge
        self.socket_path = socket_path
        self._public_test_ids = frozenset(public_test_ids)
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._tool_calls = 0
        self._command_calls = 0
        self._public_test_calls = 0
        self._file_reads = 0
        self._file_writes = 0
        self._patches = 0
        self._policy_failure: str | None = None
        self._infrastructure_failure: str | None = None

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("Claude tool broker is already running")
        if len(os.fsencode(self.socket_path)) > 100:
            raise ValueError("Claude broker socket path is too long")
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.socket_path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(4)
        server.settimeout(0.2)
        self._server = server
        self._thread = threading.Thread(target=self._serve, name="verigym-claude-broker")
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        server = self._server
        if server is not None:
            server.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self.socket_path.unlink(missing_ok=True)
        try:
            self.socket_path.parent.rmdir()
        except OSError:
            pass
        self._server = None
        self._thread = None

    def stats(self) -> BrokerStats:
        with self._lock:
            return BrokerStats(
                tool_calls=self._tool_calls,
                command_calls=self._command_calls,
                public_test_calls=self._public_test_calls,
                file_reads=self._file_reads,
                file_writes=self._file_writes,
                patches=self._patches,
                policy_failure=self._policy_failure,
                infrastructure_failure=self._infrastructure_failure,
            )

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stopping.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                try:
                    raw = self._receive_line(connection)
                    request = json.loads(raw)
                    response = self._dispatch(request)
                except Exception as exc:
                    response = self._error_result(f"broker error: {type(exc).__name__}")
                encoded = (
                    json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                    + b"\n"
                )
                if len(encoded) > _MAX_RESPONSE_BYTES:
                    encoded = (
                        json.dumps(
                            self._error_result("tool response exceeded the broker bound"),
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n"
                    )
                try:
                    connection.sendall(encoded)
                except OSError:
                    pass

    @staticmethod
    def _receive_line(connection: socket.socket) -> bytes:
        data = bytearray()
        while len(data) <= _MAX_MESSAGE_BYTES:
            block = connection.recv(min(65536, _MAX_MESSAGE_BYTES + 1 - len(data)))
            if not block:
                break
            data.extend(block)
            if data.endswith(b"\n"):
                break
        if len(data) > _MAX_MESSAGE_BYTES or not data.endswith(b"\n"):
            raise ValueError("invalid broker request framing")
        return bytes(data)

    def _dispatch(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self._error_result("tool request must be an object")
        name = request.get("name")
        arguments = request.get("arguments", {})
        if not isinstance(name, str) or name not in TOOL_NAMES or not isinstance(arguments, dict):
            return self._error_result("unknown or malformed tool request")
        with self._lock:
            if self._policy_failure is not None or self._infrastructure_failure is not None:
                return self._error_result("tool broker stopped after a terminal safety failure")
            self._tool_calls += 1
        try:
            if name == "list_files":
                return self._workspace_result("file.list", arguments)
            if name == "read_file":
                with self._lock:
                    self._file_reads += 1
                return self._workspace_result("file.read", arguments)
            if name == "search_files":
                with self._lock:
                    self._file_reads += 1
                return self._workspace_result("file.search", arguments)
            if name == "apply_patch":
                with self._lock:
                    self._patches += 1
                return self._workspace_result("file.apply_patch", arguments)
            if name == "write_file":
                with self._lock:
                    self._file_writes += 1
                return self._workspace_result("file.write", arguments)
            if name == "inspect_diff":
                return self._workspace_result("file.diff", arguments)
            if name == "run_command":
                return self._run_command(arguments)
            if name == "run_public_test":
                return self._run_public_test(arguments)
        except PathPolicyError as exc:
            message = redact_text(str(exc)) or type(exc).__name__
            with self._lock:
                self._policy_failure = message
            return self._error_result(message)
        except Exception as exc:
            message = redact_text(str(exc)) or type(exc).__name__
            with self._lock:
                self._infrastructure_failure = message
            return self._error_result(message)
        return self._error_result("unknown tool request")

    def _workspace_result(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._bridge.invoke_workspace_tool(
            tool_name,
            _json_arguments(arguments),
        )
        payload = result.model_dump(mode="json")
        if not result.success and result.category.value in {
            "permission_denied",
            "policy_denied",
            "sandbox_error",
        }:
            with self._lock:
                self._policy_failure = result.message or result.stderr or result.category.value
        elif not result.success and result.category.value == "internal_error":
            with self._lock:
                self._infrastructure_failure = result.message or "workspace tool internal error"
        return self._payload_result(payload, is_error=not result.success)

    def _run_command(self, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = {"argv", "cwd", "timeout_s", "stdin"}
        if set(arguments) - allowed:
            return self._error_result("run_command received unknown arguments")
        argv = arguments.get("argv")
        cwd = arguments.get("cwd", ".")
        timeout_s = arguments.get("timeout_s", 60)
        stdin = arguments.get("stdin")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(value, str) for value in argv)
            or not isinstance(cwd, str)
            or isinstance(timeout_s, bool)
            or not isinstance(timeout_s, int)
            or timeout_s < 1
            or timeout_s > 1800
            or (stdin is not None and not isinstance(stdin, str))
        ):
            return self._error_result("run_command arguments are invalid")
        with self._lock:
            self._command_calls += 1
        completed = self._bridge.execute_command(
            CommandSpec(argv=argv, cwd=cwd, timeout_s=timeout_s, stdin=stdin)
        )
        if completed.failure_origin == "control_plane":
            with self._lock:
                self._infrastructure_failure = completed.failure_reason or "runtime command failure"
        payload = {
            "argv": completed.argv,
            "cwd": completed.cwd,
            "exit_code": completed.exit_code,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_s": completed.duration_s,
            "timed_out": completed.timed_out,
            "oom_killed": completed.oom_killed,
            "output_truncated": completed.output_truncated,
            "failure_reason": completed.failure_reason,
            "failure_origin": completed.failure_origin,
        }
        return self._payload_result(payload, is_error=completed.exit_code not in {0})

    def _run_public_test(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) != {"test_id"} or not isinstance(arguments.get("test_id"), str):
            return self._error_result("run_public_test requires one string test_id")
        test_id = arguments["test_id"]
        if test_id not in self._public_test_ids:
            return self._error_result("public-test ID is not declared for this task")
        with self._lock:
            self._public_test_calls += 1
        completed = self._bridge.execute_public_test(test_id)
        if completed.failure_origin == "control_plane":
            with self._lock:
                self._infrastructure_failure = completed.failure_reason or "public-test failure"
        payload = {
            "test_id": test_id,
            "exit_code": completed.exit_code,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_s": completed.duration_s,
            "timed_out": completed.timed_out,
            "oom_killed": completed.oom_killed,
            "output_truncated": completed.output_truncated,
            "failure_reason": completed.failure_reason,
            "failure_origin": completed.failure_origin,
        }
        return self._payload_result(payload, is_error=completed.exit_code not in {0})

    @staticmethod
    def _payload_result(payload: Any, *, is_error: bool) -> dict[str, Any]:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    @staticmethod
    def _error_result(message: str) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": message}], "isError": True}


def _json_arguments(arguments: dict[str, Any]) -> dict[str, JsonValue]:
    encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    decoded = json.loads(encoded)
    assert isinstance(decoded, dict)
    return decoded


__all__ = ["BrokerStats", "ClaudeToolBroker"]
