"""Private broker for the canonical repository-tool surface."""

from __future__ import annotations

import json
import os
import re
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.agents.external import ExternalAgentBridge
from verigym.core.errors import PathPolicyError
from verigym.protocols.repository_action import (
    RepositoryActionProtocolViolation,
    canonical_action_json,
    canonical_tool_observation,
    repository_action_state_failure,
    repository_tool_definitions,
)
from verigym.schemas.options import JsonValue

_MAX_MESSAGE_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 512 * 1024
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TOOL_NAMES = frozenset(
    definition["name"] for definition in repository_tool_definitions(dialect="mcp")
)


@dataclass(frozen=True)
class RepositoryToolBrokerStats:
    """Content-free accounting for one broker lifetime."""

    tool_calls: int
    command_calls: int
    public_test_calls: int
    file_reads: int
    file_writes: int
    patches: int
    policy_failure: str | None
    infrastructure_failure: str | None
    diff_inspections: int = 0
    finish_calls: int = 0
    rejected_calls: int = 0
    finished: bool = False


class RepositoryToolBroker:
    """Route six typed actions into an already isolated runtime bridge."""

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
        self._public_test_calls = 0
        self._file_reads = 0
        self._patches = 0
        self._diff_inspections = 0
        self._finish_calls = 0
        self._rejected_calls = 0
        self._patch_applied = False
        self._public_observed = False
        self._diff_observed = False
        self._finished = False
        self._policy_failure: str | None = None
        self._infrastructure_failure: str | None = None

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("repository tool broker is already running")
        if len(os.fsencode(self.socket_path)) > 100:
            raise ValueError("repository broker socket path is too long")
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.socket_path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(4)
        server.settimeout(0.2)
        self._server = server
        self._thread = threading.Thread(target=self._serve, name="verigym-repository-broker")
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

    def stats(self) -> RepositoryToolBrokerStats:
        with self._lock:
            return RepositoryToolBrokerStats(
                tool_calls=self._tool_calls,
                command_calls=0,
                public_test_calls=self._public_test_calls,
                file_reads=self._file_reads,
                file_writes=0,
                patches=self._patches,
                diff_inspections=self._diff_inspections,
                finish_calls=self._finish_calls,
                rejected_calls=self._rejected_calls,
                finished=self._finished,
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
                    response = self._dispatch(json.loads(raw))
                except Exception as exc:
                    response = self._error_result("unknown", f"broker error: {type(exc).__name__}")
                encoded = (
                    json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
                )
                if len(encoded) > _MAX_RESPONSE_BYTES:
                    encoded = (
                        json.dumps(
                            self._error_result("unknown", "tool response exceeded the bound"),
                            separators=(",", ":"),
                        ).encode()
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
            return self._error_result("unknown", "tool request must be an object")
        name = request.get("name")
        arguments = request.get("arguments", {})
        if not isinstance(name, str) or name not in _TOOL_NAMES or not isinstance(arguments, dict):
            return self._error_result("unknown", "unknown or malformed tool request")
        with self._lock:
            if self._policy_failure is not None or self._infrastructure_failure is not None:
                return self._error_result(
                    name, "tool broker stopped after a terminal safety failure"
                )
            self._tool_calls += 1
            try:
                canonical_action_json(name, arguments)
            except RepositoryActionProtocolViolation as exc:
                self._rejected_calls += 1
                return self._error_result(name, exc.subcategory)
            state_failure = repository_action_state_failure(
                name,
                state_machine_id="repository_action_state_machine_v2",
                public_test_required=bool(self._public_test_ids),
                patch_applied=self._patch_applied,
                public_observed=self._public_observed,
                diff_observed=self._diff_observed,
                finished=self._finished,
            )
            if state_failure is not None:
                self._rejected_calls += 1
                return self._error_result(name, state_failure)
        try:
            if name == "list_files":
                return self._workspace_result(name, "file.list", arguments)
            if name == "read_file":
                with self._lock:
                    self._file_reads += 1
                return self._workspace_result(name, "file.read", arguments)
            if name == "apply_patch":
                with self._lock:
                    self._patches += 1
                response, success = self._workspace_result_with_success(
                    name, "file.apply_patch", arguments
                )
                if success:
                    with self._lock:
                        self._patch_applied = True
                return response
            if name == "run_public_test":
                return self._run_public_test(arguments)
            if name == "inspect_diff":
                with self._lock:
                    self._diff_inspections += 1
                response, success = self._workspace_result_with_success(
                    name, "file.diff", arguments
                )
                if success:
                    with self._lock:
                        self._diff_observed = True
                return response
            if name == "finish":
                if set(arguments) != {"message"} or not isinstance(arguments["message"], str):
                    return self._error_result(name, "finish requires one string message")
                with self._lock:
                    self._finish_calls += 1
                    self._finished = True
                return self._payload_result(
                    name, {"accepted": True, "terminal": True}, is_error=False
                )
        except PathPolicyError as exc:
            message = _safe_error(str(exc)) or type(exc).__name__
            with self._lock:
                self._policy_failure = message
            return self._error_result(name, message)
        except Exception as exc:
            message = _safe_error(str(exc)) or type(exc).__name__
            with self._lock:
                self._infrastructure_failure = message
            return self._error_result(name, message)
        return self._error_result(name, "unknown tool request")

    def _workspace_result(
        self, name: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        response, _success = self._workspace_result_with_success(name, tool_name, arguments)
        return response

    def _workspace_result_with_success(
        self, name: str, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        result = self._bridge.invoke_workspace_tool(tool_name, _json_arguments(arguments))
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
        return self._payload_result(name, payload, is_error=not result.success), result.success

    def _run_public_test(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = "run_public_test"
        if set(arguments) != {"test_id"} or not isinstance(arguments.get("test_id"), str):
            return self._error_result(name, "run_public_test requires one string test_id")
        test_id = arguments["test_id"]
        if test_id not in self._public_test_ids:
            return self._error_result(name, "public-test ID is not declared for this task")
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
        is_error = completed.exit_code not in {0}
        with self._lock:
            self._public_observed = True
        return self._payload_result(name, payload, is_error=is_error)

    @staticmethod
    def _payload_result(name: str, payload: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
        text = canonical_tool_observation(name, payload, is_error=is_error)
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    @classmethod
    def _error_result(cls, name: str, message: str) -> dict[str, Any]:
        tool_name = name if name in _TOOL_NAMES else "list_files"
        return cls._payload_result(tool_name, {"message": message}, is_error=True)


def _json_arguments(arguments: dict[str, Any]) -> dict[str, JsonValue]:
    encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    decoded = json.loads(encoded)
    assert isinstance(decoded, dict)
    return decoded


def _safe_error(text: str) -> str:
    clean = text.replace(str(Path.home()), "<redacted-root>")
    return _CONTROL.sub(" ", clean)


__all__ = ["RepositoryToolBroker", "RepositoryToolBrokerStats"]
