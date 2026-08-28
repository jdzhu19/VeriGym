"""Strict six-tool Unix-socket broker for DeepSeek Harness HWE collection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import stat
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from verigym.hwe.observation import HweObservationCompactor, ObservationKind
from verigym.hwe.private_audit import HweRawArtifactWriter
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    canonical_hwe_action_json,
    resolve_hwe_collection_profile,
    validate_hwe_action,
)
from verigym.hwe.trajectory import (
    HweEpisodeBudget,
    HweLimitExceeded,
    HweNormalizedEvent,
    command_classification,
)
from verigym.plugin_api import ExternalAgentBridge
from verigym.schemas.common import ErrorCategory
from verigym.schemas.options import JsonValue
from verigym.schemas.tool import CommandSpec, ToolResult

_MAX_REQUEST_BYTES = 5 * 1024 * 1024
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TOOLS = frozenset({"list_files", "read_file", "apply_patch", "shell", "inspect_diff", "finish"})
_TERMINAL_STATUS_OPERATION = "verigym_hwe_terminal_status_v1"
_RAW_HOST_PATH = re.compile(
    r"(?<![A-Za-z0-9._-])/(?:home|data|hpc)(?:/|(?![A-Za-z0-9._-]))|[A-Za-z]:\\\\",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeepSeekHarnessBrokerStats:
    tool_calls: int
    command_calls: int
    file_reads: int
    patches: int
    diff_inspections: int
    finish_calls: int
    rejected_calls: int
    rejection_codes: tuple[str, ...]
    finished: bool
    policy_failure: str | None
    infrastructure_failure: str | None
    workspace_epoch: int
    decision_steps: int
    mutation_actions: int
    raw_audit_manifest: dict[str, Any] | None


class DeepSeekHarnessHweBroker:
    """Route exact HWE actions while recording one causal public event per call."""

    def __init__(
        self,
        *,
        bridge: ExternalAgentBridge,
        socket_path: Path,
        private_audit_root: Path,
    ) -> None:
        self._bridge = bridge
        self.socket_path = socket_path
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._compactor = HweObservationCompactor(profile_id=HWE_COLLECTION_PROFILE_V2_ID)
        self._budget = HweEpisodeBudget(profile_id=HWE_COLLECTION_PROFILE_V2_ID)
        self._raw_writer = HweRawArtifactWriter(
            private_audit_root,
            filename="deepseek-harness-tool-observations.ndjson",
            profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        )
        self._raw_manifest: dict[str, Any] | None = None
        self._events: list[HweNormalizedEvent] = []
        self._call_ids: list[str] = []
        self._workspace_epoch = 0
        self._tool_calls = 0
        self._command_calls = 0
        self._file_reads = 0
        self._patches = 0
        self._diff_inspections = 0
        self._finish_calls = 0
        self._rejected_calls = 0
        self._rejection_codes: list[str] = []
        self._finished = False
        self._policy_failure: str | None = None
        self._infrastructure_failure: str | None = None

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("DeepSeek Harness broker is already running")
        if len(os.fsencode(self.socket_path)) > 100:
            raise ValueError("DeepSeek Harness broker socket path is too long")
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(1)
        server.settimeout(0.2)
        self._server = server
        self._thread = threading.Thread(
            target=self._serve,
            name="verigym-deepseek-harness-broker",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._server is not None:
            self._server.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                self._infrastructure_failure = "broker_thread_did_not_stop"
        self.socket_path.unlink(missing_ok=True)
        try:
            self.socket_path.parent.rmdir()
        except OSError:
            pass
        self._server = None
        self._thread = None
        if self._raw_manifest is None:
            self._raw_manifest = self._raw_writer.finalize()

    def events(self) -> tuple[HweNormalizedEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def call_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._call_ids)

    def stats(self) -> DeepSeekHarnessBrokerStats:
        with self._lock:
            return DeepSeekHarnessBrokerStats(
                tool_calls=self._tool_calls,
                command_calls=self._command_calls,
                file_reads=self._file_reads,
                patches=self._patches,
                diff_inspections=self._diff_inspections,
                finish_calls=self._finish_calls,
                rejected_calls=self._rejected_calls,
                rejection_codes=tuple(self._rejection_codes),
                finished=self._finished,
                policy_failure=self._policy_failure,
                infrastructure_failure=self._infrastructure_failure,
                workspace_epoch=self._workspace_epoch,
                decision_steps=self._budget.decision_steps,
                mutation_actions=self._budget.mutation_actions,
                raw_audit_manifest=(
                    dict(self._raw_manifest) if self._raw_manifest is not None else None
                ),
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
                    response = {
                        "ok": False,
                        "error": "broker_error",
                        "text": f"broker error: {type(exc).__name__}",
                    }
                encoded = (
                    json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
                )
                if len(encoded) > _MAX_RESPONSE_BYTES:
                    encoded = (
                        b'{"ok":false,"error":"response_too_large",'
                        b'"text":"tool response exceeded the broker bound"}\n'
                    )
                try:
                    connection.sendall(encoded)
                except OSError:
                    pass

    @staticmethod
    def _receive_line(connection: socket.socket) -> bytes:
        data = bytearray()
        while len(data) <= _MAX_REQUEST_BYTES:
            block = connection.recv(min(65_536, _MAX_REQUEST_BYTES + 1 - len(data)))
            if not block:
                break
            data.extend(block)
            if data.endswith(b"\n"):
                break
        if len(data) > _MAX_REQUEST_BYTES or not data.endswith(b"\n"):
            raise ValueError("invalid DeepSeek Harness broker framing")
        return bytes(data)

    def _dispatch(self, request: object) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self._reject("invalid_request", "tool request must be an object")
        if request == {"operation": _TERMINAL_STATUS_OPERATION}:
            with self._lock:
                return {
                    "ok": True,
                    "finished": self._finished,
                    "policy_failed": self._policy_failure is not None,
                    "infrastructure_failed": self._infrastructure_failure is not None,
                }
        call_id = request.get("id")
        name = request.get("name")
        arguments = request.get("arguments")
        if (
            not isinstance(call_id, str)
            or not call_id
            or len(call_id.encode("utf-8")) > 512
            or not isinstance(name, str)
            or name not in _TOOLS
            or not isinstance(arguments, dict)
        ):
            return self._reject("invalid_request", "tool request identity is malformed")
        with self._lock:
            finished = self._finished
            duplicate = call_id in self._call_ids
        if finished:
            return self._reject("episode_finished", "no tool calls are accepted after finish")
        if duplicate:
            return self._reject("duplicate_call_id", "tool call id was already used")
        serialized_arguments = json.dumps(
            arguments,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if _RAW_HOST_PATH.search(serialized_arguments):
            return self._reject(
                "raw_host_path",
                "tool arguments must use workspace-relative paths",
            )
        try:
            validated = validate_hwe_action(
                name,
                arguments,
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
            canonical_hwe_action_json(
                name,
                validated,
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
        except ValueError as exc:
            with self._lock:
                self._policy_failure = type(exc).__name__
            return self._reject("invalid_arguments", str(exc))

        before = self._workspace_state()
        epoch_before = self._workspace_epoch
        try:
            raw_stdout, raw_stderr, exit_code, duration_ms, result = self._execute(
                name,
                validated,
            )
            after = self._workspace_state()
            changed_paths = tuple(
                sorted(
                    path
                    for path in before.keys() | after.keys()
                    if before.get(path) != after.get(path)
                )
            )
            if changed_paths:
                self._workspace_epoch += 1
            self._budget.observe(name, changed_paths=changed_paths)
        except HweLimitExceeded as exc:
            with self._lock:
                self._policy_failure = str(exc)
            return self._reject("episode_limit", str(exc))
        except Exception as exc:
            with self._lock:
                self._infrastructure_failure = type(exc).__name__
            return self._reject(
                "infrastructure_failure",
                f"tool execution failed: {type(exc).__name__}",
            )

        observation_kinds: dict[str, ObservationKind] = {
            "list_files": "list",
            "read_file": "read",
            "apply_patch": "diff",
            "shell": "shell",
            "inspect_diff": "diff",
            "finish": "diff",
        }
        kind = observation_kinds[name]
        command = validated.get("command") if name == "shell" else None
        compact = self._compactor.compact(
            kind,
            raw_stdout,
            path=validated.get("path") if isinstance(validated.get("path"), str) else None,
            stderr=raw_stderr,
            command=command if isinstance(command, str) else None,
            cwd=validated.get("cwd") if isinstance(validated.get("cwd"), str) else ".",
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        raw_stdout_bytes = len(raw_stdout.encode("utf-8"))
        raw_stderr_bytes = len(raw_stderr.encode("utf-8"))
        self._raw_writer.append(
            {
                "schema_version": "1.0",
                "sequence": len(self._events),
                "call_id": call_id,
                "action": name,
                "arguments_sha256": hashlib.sha256(
                    json.dumps(validated, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "stdout": raw_stdout,
                "stderr": raw_stderr,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "changed_paths": list(changed_paths),
            },
            command_raw_bytes=raw_stdout_bytes + raw_stderr_bytes,
            secret_scan_text=raw_stdout + "\n" + raw_stderr,
        )
        compile_observed, simulation_observed = (
            command_classification(command) if isinstance(command, str) else (False, False)
        )
        event = HweNormalizedEvent(
            sequence=len(self._events),
            action=name,  # type: ignore[arg-type]
            arguments=validated,
            workspace_epoch_before=epoch_before,
            workspace_epoch_after=self._workspace_epoch,
            changed_paths=changed_paths,
            raw_observation_sha256=compact.raw_sha256,
            raw_observation_bytes=compact.raw_bytes,
            compact_observation_sha256=hashlib.sha256(compact.text.encode()).hexdigest(),
            compact_observation_tokens=compact.compact_tokens,
            observation_rule_id=compact.rule_id,
            observation_omitted=compact.omitted,
            exit_code=exit_code,
            duration_ms=duration_ms,
            raw_stdout_bytes=raw_stdout_bytes,
            raw_stderr_bytes=raw_stderr_bytes,
            raw_stdout_sha256=hashlib.sha256(raw_stdout.encode()).hexdigest(),
            raw_stderr_sha256=hashlib.sha256(raw_stderr.encode()).hexdigest(),
            compile_observed=compile_observed,
            simulation_observed=simulation_observed,
            event_mapping="deepseek_harness_native_tool",
        )
        with self._lock:
            self._events.append(event)
            self._call_ids.append(call_id)
            self._tool_calls += 1
            self._command_calls += int(name == "shell")
            self._file_reads += int(name == "read_file")
            self._patches += int(name == "apply_patch")
            self._diff_inspections += int(name == "inspect_diff")
            self._finish_calls += int(name == "finish")
            self._finished = self._finished or name == "finish"
        return {
            "ok": True,
            "text": compact.text,
            "sequence": event.sequence,
            "workspace_epoch_before": epoch_before,
            "workspace_epoch_after": self._workspace_epoch,
            "changed_paths": list(changed_paths),
            "result_success": result.success,
        }

    def _execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[str, str, int | None, int | None, ToolResult]:
        if name == "list_files":
            result = self._bridge.invoke_workspace_tool(
                "file.list",
                {
                    "path": arguments["path"],
                    "recursive": True,
                    "max_depth": 2,
                    "max_entries": 200,
                },
            )
        elif name == "read_file":
            request: dict[str, JsonValue] = {
                key: cast(JsonValue, arguments[key])
                for key in ("path", "start_line", "end_line")
                if key in arguments
            }
            result = self._bridge.invoke_workspace_tool("file.read", request)
        elif name == "apply_patch":
            result = self._bridge.invoke_workspace_tool("file.apply_patch", arguments)
        elif name == "inspect_diff" or name == "finish":
            result = self._bridge.invoke_workspace_tool("file.diff", {})
            if name == "finish":
                result = result.model_copy(
                    update={
                        "message": arguments["summary"],
                        "stdout": result.stdout or "No candidate diff.",
                    }
                )
        elif name == "shell":
            command = arguments["command"]
            compile_observed, simulation_observed = command_classification(command)
            profile = resolve_hwe_collection_profile(HWE_COLLECTION_PROFILE_V2_ID)
            timeout_s = (
                profile.simulation_command_timeout_s
                if simulation_observed
                else profile.compile_command_timeout_s
                if compile_observed
                else profile.ordinary_command_timeout_s
            )
            completed = self._bridge.execute_external_agent_command(
                CommandSpec(
                    argv=["/bin/bash", "-lc", command],
                    cwd=arguments.get("cwd", "."),
                    timeout_s=timeout_s,
                )
            )
            success = completed.failure_reason is None and completed.error is None
            result = ToolResult(
                tool="shell",
                success=success,
                category=ErrorCategory.SUCCESS if success else ErrorCategory.TOOL_FAILED,
                exit_code=completed.exit_code,
                stdout=completed.stdout,
                stderr=completed.stderr or completed.error or "",
                duration_s=completed.duration_s,
                output_truncated=completed.output_truncated,
                message=completed.failure_reason or "",
                metadata=dict(completed.metadata),
            )
            return (
                result.stdout,
                result.stderr,
                result.exit_code,
                round(result.duration_s * 1000),
                result,
            )
        else:
            raise AssertionError("unreachable HWE tool")
        return result.stdout or result.message, result.stderr, result.exit_code, None, result

    def _workspace_state(self) -> dict[str, str]:
        root = self._bridge.workspace_root.resolve(strict=True)
        state: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if ".verigym_internal" in relative.parts:
                continue
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("workspace contains a forbidden symlink")
            if stat.S_ISREG(metadata.st_mode):
                state[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            elif not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("workspace contains a forbidden special file")
        return state

    def _reject(self, code: str, text: str) -> dict[str, Any]:
        with self._lock:
            self._rejected_calls += 1
            self._rejection_codes.append(code)
        return {"ok": False, "error": code, "text": text}


def broker_stats_dict(stats: DeepSeekHarnessBrokerStats) -> dict[str, Any]:
    return asdict(stats)


__all__ = [
    "DeepSeekHarnessBrokerStats",
    "DeepSeekHarnessHweBroker",
    "broker_stats_dict",
]
