"""Protocol-aware observer/compactor for Codex 0.147.0 exec-server JSON-RPC."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import stat
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from urllib.parse import unquote, urlsplit

from verigym.hwe.observation import HweObservationCompactor, ObservationKind
from verigym.hwe.private_audit import HweRawArtifactWriter
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_ID,
    HWE_COLLECTION_PROFILE_V2_ID,
    HweShellCommandPolicyError,
    resolve_hwe_collection_profile,
    validate_shell_command,
    validate_workspace_relative_path,
)
from verigym.hwe.trajectory import HweEpisodeBudget, command_classification

_MUTATION_METHODS = frozenset({"fs/writeFile", "fs/createDirectory", "fs/remove", "fs/copy"})
_SHELL_METHODS = frozenset({"process/start"})
_SHELL_WRAPPERS = frozenset({"bash", "/bin/bash", "/usr/bin/bash"})
_NULL_PARAMS_METHODS = frozenset({"environment/info", "environment/status"})
_PROCESS_CONTROL_METHODS = frozenset(
    {"process/read", "process/write", "process/signal", "process/terminate"}
)
_FS_PATH_METHODS = frozenset(
    {
        "fs/readFile",
        "fs/open",
        "fs/writeFile",
        "fs/createDirectory",
        "fs/getMetadata",
        "fs/canonicalize",
        "fs/readDirectory",
        "fs/walk",
        "fs/remove",
    }
)
_RAW_COMMAND_BYTES = 32 * 1024 * 1024
_LOGICAL_WORKSPACE_ROOT = "/workspace/repository"
_LOGICAL_WORKSPACE_URI = "file:///workspace/repository"
_FIXED_EXEC_ENV_POLICY = {
    "inherit": "core",
    "ignoreDefaultExcludes": False,
    "exclude": [],
    "set": {},
    "includeOnly": [],
}
_FIXED_V2_EXEC_ENV = {"VERILATOR_ROOT": "/tools/verilator"}
_HOST_ANCESTOR_METADATA_PROBES = {
    (".git",): "git_ancestor",
    (".agents", "skills"): "agents_skills_ancestor",
    (".codex", "skills"): "codex_skills_ancestor",
    ("AGENTS.md",): "agents_instructions_ancestor",
}


@dataclass(frozen=True)
class HweProtocolRecord:
    sequence: int
    request_id: str
    method: str
    action: str | None
    arguments: dict[str, Any]
    workspace_epoch_before: int
    workspace_epoch_after: int | None = None
    changed_paths: tuple[str, ...] = ()
    raw_bytes: int = 0
    raw_sha256: str | None = None
    compact_tokens: int = 0
    compact_sha256: str | None = None
    compact_text: str | None = None
    observation_rule_id: str | None = None
    observation_omitted: bool = False
    exit_code: int | None = None
    duration_ms: int | None = None
    raw_stdout_bytes: int = 0
    raw_stderr_bytes: int = 0
    raw_stdout_sha256: str | None = None
    raw_stderr_sha256: str | None = None
    compile_observed: bool = False
    simulation_observed: bool = False
    interrupted_by_agent: bool = False
    completed: bool = False


@dataclass
class _ActiveProcess:
    record: HweProtocolRecord
    before: dict[str, tuple[int, int, int]]
    output_chunks: dict[int, tuple[str, bytes]] = field(default_factory=dict)
    raw_output_bytes: int = 0
    last_sequence: int = 0
    started_ns: int = 0
    exit_code: int | None = None
    exit_sequence: int | None = None
    exit_event: dict[str, Any] | None = None


class HweExecProtocolError(RuntimeError):
    """Fail-closed exec protocol error with a stable machine-readable reason."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class HweExecProtocolCollector:
    """Correlate and compact exec-server traffic while preserving the original audit layer."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        compactor: HweObservationCompactor,
        raw_writer: HweRawArtifactWriter,
        sft_mode: bool = True,
        profile_id: str = HWE_COLLECTION_PROFILE_ID,
    ) -> None:
        self.workspace_root = workspace_root.resolve(strict=True)
        self.compactor = compactor
        self.raw_writer = raw_writer
        self.sft_mode = sft_mode
        self.profile = resolve_hwe_collection_profile(profile_id)
        if self.compactor.profile.profile_id != self.profile.profile_id:
            raise ValueError("HWE collector and observation profiles differ")
        if self.raw_writer.profile.profile_id != self.profile.profile_id:
            raise ValueError("HWE collector and private-audit profiles differ")
        self._pending: dict[str, tuple[HweProtocolRecord, dict[str, tuple[int, int, int]]]] = {}
        self._process_ids_by_request: dict[str, str] = {}
        self._prestart_process_events: dict[str, list[dict[str, Any]]] = {}
        self._prestart_process_event_bytes: dict[str, int] = {}
        self._early_process_closures: dict[str, dict[str, Any]] = {}
        self._active_processes: dict[str, _ActiveProcess] = {}
        self._exited_processes: set[str] = set()
        self._closed_processes: set[str] = set()
        self._interrupted_processes: set[str] = set()
        self._process_records: dict[str, HweProtocolRecord] = {}
        self._file_handles: dict[str, str] = {}
        self._records: list[HweProtocolRecord] = []
        self._request_started_ns: dict[str, int] = {}
        self._next_sequence = 0
        self._epoch = 0
        self._failed: str | None = None
        self._budget = HweEpisodeBudget(profile_id=profile_id)
        self._condition = threading.Condition(threading.RLock())
        self._accepting_requests = True
        self._current_request_method: str | None = None

    @property
    def failed(self) -> str | None:
        with self._condition:
            return self._failed

    def records(self) -> tuple[HweProtocolRecord, ...]:
        with self._condition:
            return self._settled_records()

    def wait_for_settled(self, *, timeout_s: float) -> tuple[HweProtocolRecord, ...]:
        """Wait briefly for already-issued requests before transport shutdown."""

        if timeout_s < 0:
            raise ValueError("HWE protocol settle timeout cannot be negative")
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while (self._pending or self._active_processes) and self._failed is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            self._accepting_requests = False
            return self._settled_records()

    def _settled_records(self) -> tuple[HweProtocolRecord, ...]:
        if self._failed is not None:
            raise HweExecProtocolError(
                self._failed,
                f"HWE exec protocol failed closed: {self._failed}",
            )
        if self._pending or self._active_processes:
            methods: dict[str, int] = {}
            for record, _snapshot in self._pending.values():
                methods[record.method] = methods.get(record.method, 0) + 1
            if self._active_processes:
                methods["process/start(active)"] = len(self._active_processes)
            summary = ",".join(f"{method}:{methods[method]}" for method in sorted(methods))
            raise HweExecProtocolError(
                "unresolved_requests",
                f"HWE exec protocol has unresolved requests ({summary})",
            )
        return tuple(sorted(self._records, key=lambda record: record.sequence))

    def completed_records(self) -> tuple[HweProtocolRecord, ...]:
        """Return completed records even after a fail-closed protocol decision."""

        with self._condition:
            return tuple(sorted(self._records, key=lambda record: record.sequence))

    def client_message(self, payload: bytes) -> bytes:
        """Validate/freeze a client request before it reaches the agent container."""

        with self._condition:
            return self._client_message(payload)

    def _client_message(self, payload: bytes) -> bytes:
        if not self._accepting_requests:
            self._fail("request_after_protocol_settle")
        value = self._parse(payload, direction="client")
        method = value.get("method")
        request_id = value.get("id")
        if not isinstance(method, str):
            return payload
        self._current_request_method = method
        if request_id is None:
            if method != "initialized" or value.get("params") not in (None, {}):
                self._fail("unexpected_client_notification")
            value["params"] = {}
            return (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        try:
            key = _request_key(request_id)
        except RuntimeError:
            self._fail("request_id_invalid")
        params = value.get("params")
        if params is None and method in _NULL_PARAMS_METHODS:
            params = {}
            value["params"] = params
        if not isinstance(params, dict):
            self._fail(f"request_params_not_object:{method}")
        if key in self._pending:
            self._fail("duplicate_request_id")
        before = _workspace_snapshot(self.workspace_root)
        action: str | None = None
        arguments: dict[str, Any] = {}
        compile_observed = False
        simulation_observed = False
        if method == "initialize":
            client_name = params.get("clientName")
            if (
                not isinstance(client_name, str)
                or not client_name
                or len(client_name) > 128
                or params.get("resumeSessionId") is not None
            ):
                self._fail("initialize_params_invalid")
            arguments = {}
        elif method == "process/start":
            if self._active_processes or any(
                pending_record.method == "process/start"
                for pending_record, _snapshot in self._pending.values()
            ):
                self._fail("concurrent_process_start_forbidden")
            arguments, inner, process_id = self._freeze_process_start(params)
            action = "shell"
            compile_observed, simulation_observed = command_classification(inner)
            self._process_ids_by_request[key] = process_id
        elif method == "fs/readFile":
            path, masked = self._freeze_read_only_path(params, "path")
            arguments = {"path": path}
            if masked:
                arguments["control_plane_probe"] = "container_external_read_mask_v2"
            params["sandbox"] = None
            action = None if masked else "read_file"
        elif method == "fs/readDirectory":
            path, masked = self._freeze_read_only_path(params, "path", allow_root=True)
            arguments = {"path": path}
            if masked:
                arguments["control_plane_probe"] = "container_external_read_mask_v2"
            params["sandbox"] = None
            action = None if masked else "list_files"
        elif method == "fs/walk":
            path, masked = self._freeze_read_only_path(params, "path", allow_root=True)
            arguments = {"path": path}
            if masked:
                arguments["control_plane_probe"] = "container_external_read_mask_v2"
            params["sandbox"] = None
            params["options"] = {
                "maxDepth": 2,
                "maxDirectories": 200,
                "maxEntries": 200,
                "followDirectorySymlinks": False,
                "pruneHiddenDirectories": True,
            }
            action = None if masked else "list_files"
        elif method == "fs/open":
            handle = self._process_handle(params.get("handleId"), field="handleId")
            path, masked = self._freeze_read_only_path(params, "path")
            arguments = {
                "path": path,
                "handle_id": handle,
            }
            if masked:
                arguments["control_plane_probe"] = "container_external_read_mask_v2"
            params["sandbox"] = None
        elif method == "fs/readBlock":
            handle = self._process_handle(params.get("handleId"), field="handleId")
            open_path = self._file_handles.get(handle)
            if open_path is None:
                self._fail("filesystem_read_without_open_handle")
            length = params.get("len")
            if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
                self._fail("filesystem_read_length_invalid")
            params["len"] = min(length, 1024 * 1024)
            arguments = {"path": open_path}
            action = "read_file"
        elif method == "fs/close":
            handle = self._process_handle(params.get("handleId"), field="handleId")
            if handle not in self._file_handles:
                self._fail("filesystem_close_without_open_handle")
            arguments = {"path": self._file_handles[handle], "handle_id": handle}
        elif method in _MUTATION_METHODS:
            arguments = self._validate_fs_mutation(method, params)
            params["sandbox"] = None
        elif method == "fs/getMetadata":
            probe_kind = self._workspace_ancestor_metadata_probe(params.get("path"))
            if (
                probe_kind is None
                and self.profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
                and self._v2_external_metadata_probe(params.get("path"))
            ):
                probe_kind = "container_external_metadata_mask_v2"
            if probe_kind:
                probe = ".verigym-hwe-nonexistent-control-plane-probe"
                params["path"] = f"file:///workspace/repository/{probe}"
                arguments = {"path": probe, "control_plane_probe": probe_kind}
            else:
                arguments = {"path": self._freeze_file_path(params, "path", allow_root=True)}
            params["sandbox"] = None
        elif method == "fs/canonicalize":
            path, masked = self._freeze_read_only_path(params, "path", allow_root=True)
            arguments = {"path": path}
            if masked:
                arguments["control_plane_probe"] = "container_external_read_mask_v2"
            params["sandbox"] = None
        elif method in _PROCESS_CONTROL_METHODS:
            process_id = self._process_handle(params.get("processId"), field="processId")
            active = process_id in self._active_processes
            exited = process_id in self._exited_processes
            closed = process_id in self._closed_processes
            running = active and not exited
            if not active and not exited and not closed:
                self._fail("process_control_without_known_process")
            if method == "process/write" and running:
                self._fail(f"interactive_process_control_forbidden:{method}")
            if method == "process/signal":
                if set(params) != {"processId", "signal"} or params.get("signal") != "interrupt":
                    self._fail("process_signal_invalid")
                if running:
                    if process_id in self._interrupted_processes:
                        self._fail("duplicate_active_process_interrupt")
                    self._interrupted_processes.add(process_id)
            if method == "process/read":
                params["maxBytes"] = _RAW_COMMAND_BYTES
                wait_ms = params.get("waitMs")
                if wait_ms is not None and (
                    isinstance(wait_ms, bool) or not isinstance(wait_ms, int) or wait_ms < 0
                ):
                    self._fail("process_read_wait_invalid")
                if isinstance(wait_ms, int):
                    params["waitMs"] = min(wait_ms, 1000)
            arguments = {"process_id": process_id}
            if method == "process/signal":
                arguments.update(
                    {
                        "signal": "interrupt",
                        "lifecycle_state": (
                            "active" if running else "closed" if closed else "exited"
                        ),
                    }
                )
            elif method == "process/write":
                arguments["lifecycle_state"] = "closed" if closed else "exited"
        elif method in {"environment/info", "environment/status"}:
            arguments = {}
        elif method.startswith(("command/", "process/", "fs/", "http/", "capabilityRoots/")):
            self._fail(f"unknown_output_bearing_method:{method}")
        else:
            self._fail(f"unknown_exec_server_method:{method}")
        record = HweProtocolRecord(
            sequence=self._next_sequence,
            request_id=key,
            method=method,
            action=action,
            arguments=arguments,
            workspace_epoch_before=self._epoch,
            compile_observed=compile_observed,
            simulation_observed=simulation_observed,
        )
        self._next_sequence += 1
        self._pending[key] = (record, before)
        self._request_started_ns[key] = time.monotonic_ns()
        self._current_request_method = None
        return (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()

    def server_message(self, payload: bytes) -> bytes | tuple[bytes, ...] | None:
        """Audit a response, compact output fields, and correlate observed workspace changes."""

        with self._condition:
            return self._server_message(payload)

    def _server_message(self, payload: bytes) -> bytes | tuple[bytes, ...] | None:
        value = self._parse(payload, direction="server")
        method = value.get("method")
        if isinstance(method, str):
            if method == "process/output":
                return self._buffer_process_output(value)
            if method == "process/exited":
                return self._complete_process(value)
            if method == "process/closed":
                return self._close_process(value)
            self._fail(f"unknown_exec_server_notification:{method}")
        response_id = value.get("id")
        if response_id is None:
            return payload
        try:
            key = _request_key(response_id)
        except RuntimeError:
            self._fail("response_id_invalid")
        pending = self._pending.get(key)
        if pending is None:
            self._fail("response_without_request")
        record, before = pending
        if record.method == "process/start" and "error" not in value:
            self._record_raw_response(record, key, value, command_raw_bytes=None)
            process_id = self._process_ids_by_request.pop(key, None)
            if process_id is None:
                self._fail("process_start_id_missing")
            if process_id in self._active_processes:
                self._fail("duplicate_active_process_id")
            self._active_processes[process_id] = _ActiveProcess(
                record=record,
                before=before,
                started_ns=self._request_started_ns.pop(key),
            )
            self._process_records[process_id] = record
            del self._pending[key]
            self._condition.notify_all()
            frames: list[bytes] = [
                (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
            ]
            queued = self._prestart_process_events.pop(process_id, [])
            self._prestart_process_event_bytes.pop(process_id, None)
            for event in queued:
                event_method = event.get("method")
                transformed: bytes | tuple[bytes, ...] | None
                if event_method == "process/output":
                    transformed = self._buffer_process_output(event)
                elif event_method == "process/exited":
                    transformed = self._complete_process(event)
                elif event_method == "process/closed":
                    transformed = self._close_process(event)
                else:
                    self._fail("prestart_process_event_invalid")
                if transformed is None:
                    continue
                if isinstance(transformed, tuple):
                    frames.extend(transformed)
                else:
                    frames.append(transformed)
            return tuple(frames) if len(frames) > 1 else frames[0]
        failed_process_id = self._process_ids_by_request.pop(key, None)
        if failed_process_id is not None and failed_process_id in self._prestart_process_events:
            self._fail("process_events_before_failed_start")
        raw_result = value.get("result")
        raw_serialized = json.dumps(
            raw_result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        raw_bytes = len(raw_serialized.encode("utf-8"))
        raw_sha256 = hashlib.sha256(raw_serialized.encode("utf-8")).hexdigest()
        self._record_raw_response(
            record,
            key,
            value,
            command_raw_bytes=raw_bytes if record.method in _SHELL_METHODS else None,
        )
        compact_tokens = 0
        compact_hash: str | None = None
        compact_text: str | None = None
        observation_rule_id: str | None = None
        observation_omitted = False
        exit_code: int | None = None
        if "error" not in value and isinstance(raw_result, dict):
            if record.method == "fs/open":
                handle = self._process_handle(raw_result.get("handleId"), field="handleId")
                self._file_handles[handle] = str(record.arguments["path"])
            elif record.method == "fs/close":
                handle = self._process_handle(record.arguments.get("handle_id"), field="handleId")
                self._file_handles.pop(handle, None)
            elif record.method == "fs/canonicalize":
                self._relative_path(raw_result.get("path"), allow_root=True)
            (
                compact_tokens,
                compact_hash,
                compact_text,
                exit_code,
                observation_rule_id,
                observation_omitted,
            ) = self._compact_result(record, raw_result)
        after = _workspace_snapshot(self.workspace_root)
        started_ns = self._request_started_ns.pop(key, None)
        if started_ns is None:
            self._fail("request_timing_missing")
        duration_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
        changed_paths = tuple(sorted(_changed_paths(before, after)))
        if changed_paths:
            self._epoch += 1
        completed = HweProtocolRecord(
            **{
                **asdict(record),
                "workspace_epoch_after": self._epoch,
                "changed_paths": changed_paths,
                "raw_bytes": raw_bytes,
                "raw_sha256": raw_sha256,
                "compact_tokens": compact_tokens,
                "compact_sha256": compact_hash,
                "compact_text": compact_text,
                "observation_rule_id": observation_rule_id,
                "observation_omitted": observation_omitted,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "completed": True,
            }
        )
        if record.action is not None:
            self._budget.observe(record.action, changed_paths=changed_paths)
        elif record.method in _MUTATION_METHODS:
            mutation_paths = changed_paths or tuple(
                value
                for name, value in record.arguments.items()
                if name != "method" and isinstance(value, str)
            )
            self._budget.observe("apply_patch", changed_paths=mutation_paths)
        self._records.append(completed)
        del self._pending[key]
        self._condition.notify_all()
        return (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()

    def _buffer_process_output(self, value: dict[str, Any]) -> bytes | None:
        params = value.get("params")
        if not isinstance(params, dict):
            self._fail("process_output_params_not_object")
        process_id = self._process_handle(params.get("processId"), field="processId")
        active = self._active_processes.get(process_id)
        if active is None:
            if self._queue_prestart_process_event(process_id, value):
                return None
            self._fail("process_output_without_active_start")
        sequence = params.get("seq")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            self._fail("process_output_sequence_invalid")
        if sequence in active.output_chunks:
            self._fail("process_output_sequence_duplicate")
        stream = params.get("stream")
        if stream not in {"stdout", "stderr", "pty"}:
            self._fail("process_output_stream_invalid")
        encoded = params.get("chunk")
        if not isinstance(encoded, str):
            self._fail("process_output_chunk_invalid")
        try:
            chunk = base64.b64decode(encoded, validate=True)
        except ValueError:
            self._fail("process_output_chunk_invalid")
        active.raw_output_bytes += len(chunk)
        if active.raw_output_bytes > _RAW_COMMAND_BYTES:
            self._fail("process_output_raw_cap_exceeded")
        active.last_sequence = max(active.last_sequence, sequence)
        active.output_chunks[sequence] = (stream, chunk)
        self.raw_writer.append(
            {
                "schema_version": "1.0",
                "format_id": "verigym_hwe_raw_exec_event_v1",
                "sequence": active.record.sequence,
                "request_id": active.record.request_id,
                "method": "process/output",
                "arguments": active.record.arguments,
                "response": value,
            },
            command_raw_bytes=active.raw_output_bytes,
            secret_scan_text=chunk.decode("utf-8", errors="replace"),
        )
        if self.sft_mode:
            return None
        return (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()

    def _complete_process(self, value: dict[str, Any]) -> tuple[bytes, ...]:
        params = value.get("params")
        if not isinstance(params, dict):
            self._fail("process_exit_params_not_object")
        process_id = self._process_handle(params.get("processId"), field="processId")
        active = self._active_processes.get(process_id)
        if active is None:
            if self._queue_prestart_process_event(process_id, value):
                return ()
            self._fail("process_exit_without_active_start")
        sequence = params.get("seq")
        exit_code = params.get("exitCode")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            self._fail("process_exit_sequence_invalid")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            self._fail("process_exit_code_invalid")
        if active.exit_event is not None or process_id in self._exited_processes:
            self._fail("duplicate_process_exit")
        self.raw_writer.append(
            {
                "schema_version": "1.0",
                "format_id": "verigym_hwe_raw_exec_event_v1",
                "sequence": active.record.sequence,
                "request_id": active.record.request_id,
                "method": "process/exited",
                "arguments": active.record.arguments,
                "response": value,
            },
            command_raw_bytes=active.raw_output_bytes,
        )
        active.last_sequence = max(active.last_sequence, sequence)
        active.exit_code = exit_code
        active.exit_sequence = sequence
        active.exit_event = value
        self._exited_processes.add(process_id)
        self._condition.notify_all()
        early_close = self._early_process_closures.pop(process_id, None)
        if early_close is not None:
            close_params = early_close.get("params")
            close_sequence = close_params.get("seq") if isinstance(close_params, dict) else None
            if (
                isinstance(close_sequence, bool)
                or not isinstance(close_sequence, int)
                or close_sequence <= sequence
            ):
                self._fail("process_close_sequence_precedes_exit")
            return self._finish_closed_process(process_id, early_close)
        return ()

    def _finalize_exited_process(self, process_id: str) -> tuple[bytes, ...]:
        active = self._active_processes.get(process_id)
        if (
            active is None
            or active.exit_code is None
            or active.exit_sequence is None
            or active.exit_event is None
        ):
            self._fail("process_finalize_without_exit")
        exit_code = active.exit_code
        exit_event = active.exit_event
        stdout_bytes = b"".join(
            chunk
            for _sequence, (stream, chunk) in sorted(active.output_chunks.items())
            if stream != "stderr"
        )
        stderr_bytes = b"".join(
            chunk
            for _sequence, (stream, chunk) in sorted(active.output_chunks.items())
            if stream == "stderr"
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if "\ufffd" in stdout or "\ufffd" in stderr:
            marker = "[verigym-hwe invalid UTF-8 replaced in model-visible output]"
            stderr = f"{stderr}\n{marker}" if stderr else marker
        if self.profile.profile_id == HWE_COLLECTION_PROFILE_ID:
            stdout = _workspace_relative_observation(stdout)
            stderr = _workspace_relative_observation(stderr)
        interrupted = process_id in self._interrupted_processes
        if interrupted:
            marker = "[verigym-hwe process interrupted by agent]"
            stderr = f"{stderr}\n{marker}" if stderr else marker
        command = str(active.record.arguments.get("command", ""))
        kind, path = _command_observation(command)
        if stderr:
            kind = "shell"
        duration_ms = max(0, (time.monotonic_ns() - active.started_ns) // 1_000_000)
        compact = self.compactor.compact(
            kind,
            stdout,
            stderr=stderr,
            path=path,
            command=command,
            cwd=str(active.record.arguments.get("cwd", ".")),
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        raw_material = stdout_bytes + b"\n[stderr]\n" + stderr_bytes
        after = _workspace_snapshot(self.workspace_root)
        changed_paths = tuple(sorted(_changed_paths(active.before, after)))
        if changed_paths:
            self._epoch += 1
        completed = HweProtocolRecord(
            **{
                **asdict(active.record),
                "workspace_epoch_after": self._epoch,
                "changed_paths": changed_paths,
                "raw_bytes": active.raw_output_bytes,
                "raw_sha256": hashlib.sha256(raw_material).hexdigest(),
                "compact_tokens": compact.compact_tokens,
                "compact_sha256": hashlib.sha256(compact.text.encode()).hexdigest(),
                "compact_text": compact.text,
                "observation_rule_id": compact.rule_id,
                "observation_omitted": compact.omitted,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "raw_stdout_bytes": len(stdout_bytes),
                "raw_stderr_bytes": len(stderr_bytes),
                "raw_stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
                "raw_stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
                "interrupted_by_agent": interrupted,
                "completed": True,
            }
        )
        self._budget.observe("shell", changed_paths=changed_paths)
        self._records.append(completed)
        del self._active_processes[process_id]
        self._interrupted_processes.discard(process_id)
        self._condition.notify_all()
        frames: list[bytes] = []
        if self.sft_mode and compact.text:
            output_sequence = max(1, active.exit_sequence - 1)
            output: dict[str, Any] = {
                "method": "process/output",
                "params": {
                    "processId": process_id,
                    "seq": output_sequence,
                    "stream": "stdout",
                    "chunk": base64.b64encode(compact.text.encode()).decode("ascii"),
                },
            }
            if exit_event.get("jsonrpc") == "2.0":
                output["jsonrpc"] = "2.0"
            frames.append(
                (json.dumps(output, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
            )
        frames.append(
            (json.dumps(exit_event, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        )
        return tuple(frames)

    def _close_process(self, value: dict[str, Any]) -> bytes | tuple[bytes, ...] | None:
        params = value.get("params")
        if not isinstance(params, dict):
            self._fail("process_closed_params_not_object")
        process_id = self._process_handle(params.get("processId"), field="processId")
        if process_id not in self._exited_processes and self._queue_prestart_process_event(
            process_id, value
        ):
            return None
        active = self._active_processes.get(process_id)
        if active is None:
            self._fail("process_closed_without_active_start")
        sequence = params.get("seq")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            self._fail("process_close_sequence_invalid")
        if process_id in self._early_process_closures:
            self._fail("duplicate_early_process_close")
        if process_id in self._exited_processes:
            if active.exit_sequence is None or sequence <= active.exit_sequence:
                self._fail("process_close_sequence_precedes_exit")
        elif sequence <= active.last_sequence:
            self._fail("process_close_sequence_not_monotonic")
        self.raw_writer.append(
            {
                "schema_version": "1.0",
                "format_id": "verigym_hwe_raw_exec_event_v1",
                "method": "process/closed",
                "arguments": {"process_id": process_id},
                "response": value,
            }
        )
        if process_id not in self._exited_processes:
            active.last_sequence = max(active.last_sequence, sequence)
            self._early_process_closures[process_id] = value
            self._condition.notify_all()
            return None
        return self._finish_closed_process(process_id, value)

    def _finish_closed_process(self, process_id: str, value: dict[str, Any]) -> tuple[bytes, ...]:
        finalized = self._finalize_exited_process(process_id)
        self._exited_processes.remove(process_id)
        self._closed_processes.add(process_id)
        closed = (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        return (*finalized, closed)

    def _record_raw_response(
        self,
        record: HweProtocolRecord,
        key: str,
        value: dict[str, Any],
        *,
        command_raw_bytes: int | None,
    ) -> None:
        self.raw_writer.append(
            {
                "schema_version": "1.0",
                "format_id": "verigym_hwe_raw_exec_event_v1",
                "sequence": record.sequence,
                "request_id": key,
                "method": record.method,
                "arguments": record.arguments,
                "response": value,
            },
            command_raw_bytes=command_raw_bytes,
            secret_scan_text=_decoded_observation_text(record.method, value),
        )

    def _queue_prestart_process_event(
        self,
        process_id: str,
        value: dict[str, Any],
    ) -> bool:
        """Bound events that race ahead of their correlated process/start response."""

        if process_id not in self._process_ids_by_request.values():
            return False
        encoded_bytes = len(
            json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        observed = self._prestart_process_event_bytes.get(process_id, 0) + encoded_bytes
        events = self._prestart_process_events.setdefault(process_id, [])
        if observed > 2 * _RAW_COMMAND_BYTES or len(events) >= 4096:
            self._fail("prestart_process_event_cap_exceeded")
        events.append(value)
        self._prestart_process_event_bytes[process_id] = observed
        return True

    def _freeze_process_start(self, params: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        command = params.get("argv")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(value, str) for value in command)
        ):
            self._fail("process_start_argv_invalid")
        original_command = command
        original_inner = _unwrap_shell(original_command)
        if self.profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID:
            normalized_command = list(command)
            inner = original_inner
        else:
            normalized_command = [_normalize_logical_workspace_paths(value) for value in command]
            inner = _unwrap_shell(normalized_command)
        if inner != original_inner:
            self.raw_writer.append(
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_raw_command_path_normalization_v1",
                    "rule_id": "logical_workspace_root_to_relative_v1",
                    "original_command": original_inner,
                    "normalized_command": inner,
                    "original_command_sha256": hashlib.sha256(original_inner.encode()).hexdigest(),
                    "normalized_command_sha256": hashlib.sha256(inner.encode()).hexdigest(),
                },
                secret_scan_text=f"{original_inner}\n{inner}",
            )
        try:
            validate_shell_command(inner, profile_id=self.profile.profile_id)
        except HweShellCommandPolicyError as exc:
            request_sha256 = hashlib.sha256(
                json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
            self._fail(
                f"shell_command_policy_violation:{exc.reason}",
                diagnostics={
                    "policy_subreason": exc.reason,
                    "rejected_command": inner,
                    "rejected_request_sha256": request_sha256,
                },
            )
        params["argv"] = normalized_command
        if (
            self.profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
            and self._v2_direct_workspace_parent(params.get("cwd"))
        ):
            original_cwd = str(params["cwd"])
            params["cwd"] = _LOGICAL_WORKSPACE_URI
            cwd = "."
            self.raw_writer.append(
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_raw_process_cwd_normalization_v1",
                    "rule_id": "direct_workspace_parent_to_repository_root_v1",
                    "original_cwd_sha256": hashlib.sha256(original_cwd.encode()).hexdigest(),
                    "normalized_cwd": _LOGICAL_WORKSPACE_URI,
                }
            )
        else:
            cwd = self._freeze_file_path(params, "cwd", allow_root=True)
        process_id = self._process_handle(params.get("processId"), field="processId")
        if (
            process_id in self._active_processes
            or process_id in self._exited_processes
            or process_id in self._closed_processes
            or process_id in self._process_ids_by_request.values()
        ):
            self._fail("duplicate_process_id")
        # The model-facing shell contract has no environment, sandbox, proxy, or stdin fields.
        # Replace app-server transport details with one frozen executor-local policy.
        params["envPolicy"] = dict(_FIXED_EXEC_ENV_POLICY)
        params["env"] = (
            dict(_FIXED_V2_EXEC_ENV)
            if self.profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
            else {}
        )
        params["pipeStdin"] = False
        params["tty"] = False
        params["arg0"] = None
        params["sandbox"] = None
        params["enforceManagedNetwork"] = False
        params["managedNetwork"] = None
        params["networkProxy"] = None
        return (
            {"command": inner, **({"cwd": cwd} if cwd != "." else {})},
            inner,
            process_id,
        )

    def _compact_result(
        self, record: HweProtocolRecord, result: dict[str, Any]
    ) -> tuple[int, str | None, str | None, int | None, str | None, bool]:
        if record.method in _SHELL_METHODS:
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            if not isinstance(stdout, str) or not isinstance(stderr, str):
                self._fail("command_response_output_invalid")
            if self.profile.profile_id == HWE_COLLECTION_PROFILE_ID:
                stdout = _workspace_relative_observation(stdout)
                stderr = _workspace_relative_observation(stderr)
            command = str(record.arguments.get("command", ""))
            kind, path = _command_observation(command)
            if stderr:
                kind = "shell"
            capped_streams = [
                stream
                for stream, key in (("stdout", "stdoutCapReached"), ("stderr", "stderrCapReached"))
                if result.get(key) is True
            ]
            if capped_streams:
                marker = "[verigym-hwe raw output cap reached: " + ",".join(capped_streams) + "]"
                stderr = f"{stderr}\n{marker}" if stderr else marker
            exit_code = result.get("exitCode")
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                self._fail("command_response_exit_invalid")
            compact = self.compactor.compact(
                kind,
                stdout,
                stderr=stderr,
                path=path,
                command=command,
                cwd=str(record.arguments.get("cwd", ".")),
                exit_code=exit_code,
            )
            result["stdout"] = compact.text
            result["stderr"] = ""
            result["verigymHweObservation"] = _observation_metadata(compact)
            return (
                compact.compact_tokens,
                hashlib.sha256(compact.text.encode()).hexdigest(),
                compact.text,
                exit_code,
                compact.rule_id,
                compact.omitted,
            )
        if record.method == "process/read":
            process_id = str(record.arguments.get("process_id", ""))
            process_record = self._process_records.get(process_id)
            chunks = result.get("chunks")
            if process_record is None or not isinstance(chunks, list):
                self._fail("process_read_response_invalid")
            stdout = bytearray()
            stderr = bytearray()
            last_sequence = 0
            for item in chunks:
                if not isinstance(item, dict):
                    self._fail("process_read_chunk_invalid")
                sequence = item.get("seq")
                stream = item.get("stream")
                encoded = item.get("chunk")
                if (
                    isinstance(sequence, bool)
                    or not isinstance(sequence, int)
                    or sequence < last_sequence
                    or stream not in {"stdout", "stderr", "pty"}
                    or not isinstance(encoded, str)
                ):
                    self._fail("process_read_chunk_invalid")
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                except ValueError:
                    self._fail("process_read_chunk_invalid")
                last_sequence = sequence
                if stream == "stderr":
                    stderr.extend(decoded)
                else:
                    stdout.extend(decoded)
            if len(stdout) + len(stderr) > _RAW_COMMAND_BYTES:
                self._fail("process_read_raw_cap_exceeded")
            command = str(process_record.arguments.get("command", ""))
            kind, path = _command_observation(command)
            stderr_text = bytes(stderr).decode("utf-8", errors="replace")
            if stderr_text:
                kind = "shell"
            compact = self.compactor.compact(
                kind,
                bytes(stdout).decode("utf-8", errors="replace"),
                stderr=stderr_text,
                path=path,
                command=command,
                cwd=str(process_record.arguments.get("cwd", ".")),
                exit_code=(
                    result.get("exitCode") if isinstance(result.get("exitCode"), int) else None
                ),
            )
            result["chunks"] = (
                [
                    {
                        "seq": last_sequence,
                        "stream": "stdout",
                        "chunk": base64.b64encode(compact.text.encode()).decode("ascii"),
                    }
                ]
                if compact.text
                else []
            )
            return (
                compact.compact_tokens,
                hashlib.sha256(compact.text.encode()).hexdigest(),
                compact.text,
                result.get("exitCode") if isinstance(result.get("exitCode"), int) else None,
                compact.rule_id,
                compact.omitted,
            )
        if record.method == "fs/readFile":
            encoded = result.get("dataBase64")
            if not isinstance(encoded, str):
                self._fail("read_file_response_invalid")
            try:
                raw = base64.b64decode(encoded, validate=True)
                text = raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise RuntimeError("HWE read_file response is not strict UTF-8 base64") from exc
            compact = self.compactor.compact(
                "read",
                text,
                path=str(record.arguments.get("path", "")),
                command=f"read_file {record.arguments.get('path', '')}",
                cwd=".",
            )
            result["dataBase64"] = base64.b64encode(compact.text.encode()).decode("ascii")
            result["verigymHweObservation"] = _observation_metadata(compact)
            return (
                compact.compact_tokens,
                hashlib.sha256(compact.text.encode()).hexdigest(),
                compact.text,
                None,
                compact.rule_id,
                compact.omitted,
            )
        if record.method == "fs/readBlock":
            encoded = result.get("chunk")
            if not isinstance(encoded, str):
                self._fail("read_block_response_invalid")
            try:
                raw = base64.b64decode(encoded, validate=True)
                text = raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                self._fail("read_block_response_invalid")
            compact = self.compactor.compact(
                "read",
                text,
                path=str(record.arguments.get("path", "")),
                command=f"read_file {record.arguments.get('path', '')}",
                cwd=".",
            )
            result["chunk"] = base64.b64encode(compact.text.encode()).decode("ascii")
            return (
                compact.compact_tokens,
                hashlib.sha256(compact.text.encode()).hexdigest(),
                compact.text,
                None,
                compact.rule_id,
                compact.omitted,
            )
        if record.method == "fs/readDirectory":
            entries = result.get("entries")
            if not isinstance(entries, list):
                self._fail("read_directory_response_invalid")
            rendered = "\n".join(
                str(entry.get("fileName", "")) if isinstance(entry, dict) else str(entry)
                for entry in entries
            )
            compact = self.compactor.compact(
                "list",
                rendered,
                command=f"list_files {record.arguments.get('path', '.')}",
                cwd=".",
            )
            allowed = set(compact.text.splitlines())
            result["entries"] = [
                entry
                for entry in entries
                if isinstance(entry, dict) and str(entry.get("fileName", "")) in allowed
            ][:200]
            return (
                compact.compact_tokens,
                hashlib.sha256(compact.text.encode()).hexdigest(),
                compact.text,
                None,
                compact.rule_id,
                compact.omitted,
            )
        if record.method == "fs/walk":
            entries = result.get("entries")
            if not isinstance(entries, list):
                self._fail("walk_response_invalid")
            walk_rendered: list[str] = []
            entry_paths: list[tuple[dict[str, Any], str]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    self._fail("walk_response_invalid")
                relative = self._relative_path(entry.get("path"), allow_root=True)
                walk_rendered.append(relative)
                entry_paths.append((entry, relative))
            compact = self.compactor.compact(
                "list",
                "\n".join(walk_rendered),
                command=f"list_files {record.arguments.get('path', '.')}",
                cwd=".",
            )
            allowed = set(compact.text.splitlines())
            result["entries"] = [entry for entry, path in entry_paths if path in allowed][:200]
            if compact.omitted:
                result["truncated"] = True
            return (
                compact.compact_tokens,
                hashlib.sha256(compact.text.encode()).hexdigest(),
                compact.text,
                None,
                compact.rule_id,
                compact.omitted,
            )
        return 0, None, None, None, None, False

    def _relative_path(self, value: object, *, allow_root: bool = False) -> str:
        if not isinstance(value, str):
            self._fail("filesystem_path_invalid")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "file"
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or any(marker in parsed.path.casefold() for marker in ("%2f", "%5c", "%00"))
        ):
            self._fail("filesystem_path_uri_invalid")
        native_path = unquote(parsed.path)
        logical_root = "/workspace/repository"
        host_root = self.workspace_root.as_posix()
        if native_path in {logical_root, host_root}:
            relative = "."
        elif native_path.startswith(f"{logical_root}/"):
            relative = native_path.removeprefix(f"{logical_root}/")
        elif native_path.startswith(f"{host_root}/"):
            relative = native_path.removeprefix(f"{host_root}/")
        else:
            self._fail(
                "filesystem_path_outside_workspace",
                diagnostics={"rejected_path": value},
            )
        try:
            return validate_workspace_relative_path(relative, allow_dot=allow_root)
        except ValueError:
            self._fail("filesystem_path_invalid")

    def _freeze_file_path(
        self,
        params: dict[str, Any],
        key: str,
        *,
        allow_root: bool = False,
    ) -> str:
        """Map an exact host-workspace URI onto the single visible container mount."""

        relative = self._relative_path(params.get(key), allow_root=allow_root)
        logical = PurePosixPath("/workspace/repository")
        if relative != ".":
            logical /= relative
        params[key] = logical.as_uri()
        return relative

    def _freeze_read_only_path(
        self,
        params: dict[str, Any],
        key: str,
        *,
        allow_root: bool = False,
    ) -> tuple[str, bool]:
        """Keep direct reads bounded while making external discovery look absent in v2."""

        if (
            self.profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
            and self._v2_external_metadata_probe(params.get(key))
        ):
            probe = ".verigym-hwe-nonexistent-control-plane-probe"
            params[key] = f"{_LOGICAL_WORKSPACE_URI}/{probe}"
            return probe, True
        return self._freeze_file_path(params, key, allow_root=allow_root), False

    def _workspace_ancestor_metadata_probe(self, value: object) -> str | None:
        """Recognize bounded Codex discovery probes above the visible mount."""

        if not isinstance(value, str):
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "file"
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or any(marker in parsed.path.casefold() for marker in ("%2f", "%5c", "%00"))
        ):
            return None
        candidate = PurePosixPath(unquote(parsed.path))
        if ".." in candidate.parts:
            return None
        workspace_roots = (
            PurePosixPath(self.workspace_root.as_posix()),
            PurePosixPath("/workspace/repository"),
        )
        for suffix, probe_kind in _HOST_ANCESTOR_METADATA_PROBES.items():
            if tuple(candidate.parts[-len(suffix) :]) != suffix:
                continue
            discovery_root = candidate
            for _part in suffix:
                discovery_root = discovery_root.parent
            for workspace_root in workspace_roots:
                if discovery_root != workspace_root and workspace_root.is_relative_to(
                    discovery_root
                ):
                    return probe_kind
        return None

    def _v2_external_metadata_probe(self, value: object) -> bool:
        """Mask non-workspace metadata discovery without exposing container contents."""

        if not isinstance(value, str):
            return False
        parsed = urlsplit(value)
        if (
            parsed.scheme != "file"
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or any(marker in parsed.path.casefold() for marker in ("%2f", "%5c", "%00"))
        ):
            return False
        native_path = PurePosixPath(unquote(parsed.path))
        if ".." in native_path.parts:
            return False
        for root in (
            PurePosixPath(self.workspace_root.as_posix()),
            PurePosixPath("/workspace/repository"),
        ):
            if native_path == root or native_path.is_relative_to(root):
                return False
        return True

    def _v2_direct_workspace_parent(self, value: object) -> bool:
        """Recognize only the transport's direct parent of either workspace identity."""

        if not isinstance(value, str):
            return False
        parsed = urlsplit(value)
        if (
            parsed.scheme != "file"
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or any(marker in parsed.path.casefold() for marker in ("%2f", "%5c", "%00"))
        ):
            return False
        candidate = PurePosixPath(unquote(parsed.path))
        if ".." in candidate.parts:
            return False
        return any(
            candidate == root.parent
            for root in (
                PurePosixPath(self.workspace_root.as_posix()),
                PurePosixPath(_LOGICAL_WORKSPACE_ROOT),
            )
        )

    def _validate_fs_mutation(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        result = {"method": method}
        for key in (
            "path",
            "from",
            "to",
            "source",
            "destination",
            "sourcePath",
            "destinationPath",
        ):
            if key in params:
                result[key] = self._freeze_file_path(params, key)
        if not any(
            key in result
            for key in (
                "path",
                "from",
                "to",
                "source",
                "destination",
                "sourcePath",
                "destinationPath",
            )
        ):
            self._fail("filesystem_mutation_path_missing")
        return result

    def _process_handle(self, value: object, *, field: str = "processHandle") -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 128
            or any(ord(character) < 33 or ord(character) > 126 for character in value)
        ):
            self._fail(f"{field}_invalid")
        return value

    def _parse(self, payload: bytes, *, direction: str) -> dict[str, Any]:
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._fail(f"{direction}_json_malformed")
        if not isinstance(value, dict) or value.get("jsonrpc") not in {None, "2.0"}:
            self._fail(f"{direction}_json_not_rpc_object")
        return value

    def _fail(self, reason: str, *, diagnostics: dict[str, str] | None = None) -> NoReturn:
        if self._failed is None:
            self._failed = reason
            safe_diagnostics = dict(diagnostics or {})
            if self._current_request_method is not None:
                safe_diagnostics.setdefault("request_method", self._current_request_method)
            if any(
                key
                not in {
                    "policy_subreason",
                    "rejected_command",
                    "rejected_path",
                    "rejected_request_sha256",
                    "request_method",
                }
                or not isinstance(value, str)
                for key, value in safe_diagnostics.items()
            ):
                raise ValueError("HWE protocol failure diagnostics are not allowlisted")
            self.raw_writer.append(
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_raw_protocol_failure_v1",
                    "reason": reason,
                    "completed_records": len(self._records),
                    "pending_methods": sorted(
                        record.method for record, _snapshot in self._pending.values()
                    ),
                    "active_process_count": len(self._active_processes),
                    **safe_diagnostics,
                }
            )
        else:
            reason = self._failed
        self._condition.notify_all()
        raise HweExecProtocolError(reason, f"HWE exec protocol failed closed: {reason}")


def _unwrap_shell(command: list[str]) -> str:
    if len(command) == 3 and command[0] in _SHELL_WRAPPERS and command[1] in {"-c", "-lc"}:
        return command[2]
    # Codex may use an argv-native command. Preserve shell semantics deterministically.
    return " ".join(_shell_quote(value) for value in command)


def _normalize_logical_workspace_paths(value: str) -> str:
    normalized = value.replace(f"{_LOGICAL_WORKSPACE_ROOT}/", "")
    return re.sub(
        rf"{re.escape(_LOGICAL_WORKSPACE_ROOT)}(?=$|[\s'\";&|<>,:)\]])",
        ".",
        normalized,
    )


def _workspace_relative_observation(value: str) -> str:
    normalized = value.replace(f"{_LOGICAL_WORKSPACE_URI}/", "")
    normalized = re.sub(
        rf"{re.escape(_LOGICAL_WORKSPACE_URI)}(?=$|[\s'\";&|<>,:)\]])",
        ".",
        normalized,
    )
    return _normalize_logical_workspace_paths(normalized)


def _shell_quote(value: str) -> str:
    if value and all(character.isalnum() or character in "_./:+,@%=-" for character in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _command_observation(command: str) -> tuple[ObservationKind, str | None]:
    """Choose only a compaction rule; the normalized action remains ``shell``."""

    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return "shell", None
    if not words:
        return "shell", None
    if any(operator in words for operator in ("&&", "||", ";", "&")):
        return "shell", None
    executable = PurePosixPath(words[0]).name
    if "|" in words:
        pipeline_heads = [executable]
        pipeline_heads.extend(
            PurePosixPath(words[index + 1]).name
            for index, word in enumerate(words[:-1])
            if word == "|"
        )
        if executable not in {"find", "ls", "tree"} or any(
            value not in {"find", "ls", "tree", "sort", "head", "tail"} for value in pipeline_heads
        ):
            return "shell", None
    if executable in {"rg", "grep", "egrep", "fgrep"}:
        if executable == "rg" and "--files" in words:
            return "list", None
        return "search", None
    if executable == "git" and len(words) > 1:
        if words[1] in {"diff", "show"}:
            return "diff", None
        if words[1] == "grep":
            return "search", None
    if executable in {"find", "ls", "tree"}:
        return "list", None
    if executable in {"cat", "head", "tail", "sed"}:
        candidates = [word for word in words[1:] if not word.startswith("-")]
        path = candidates[-1] if candidates else None
        return "read", path
    return "shell", None


def _request_key(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise RuntimeError("HWE JSON-RPC request ID is invalid")
    return str(value)


def _workspace_snapshot(root: Path) -> dict[str, tuple[int, int, int]]:
    result: dict[str, tuple[int, int, int]] = {}
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name != ".git")
        entries = [*names, *sorted(files)]
        for name in entries:
            path = Path(directory) / name
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if stat.S_ISLNK(metadata.st_mode):
                if not path.resolve(strict=False).is_relative_to(root):
                    raise RuntimeError("HWE workspace symlink escapes the visible repository")
                if name in names:
                    names.remove(name)
            elif not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("HWE workspace contains a special file")
            relative = path.relative_to(root).as_posix()
            result[relative] = (metadata.st_size, metadata.st_mtime_ns, metadata.st_mode & 0o777)
    return result


def _changed_paths(
    before: dict[str, tuple[int, int, int]], after: dict[str, tuple[int, int, int]]
) -> set[str]:
    return {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}


def _observation_metadata(value: Any) -> dict[str, Any]:
    return {
        "policyId": "hwe_repository_observation_v1",
        "ruleId": value.rule_id,
        "rawBytes": value.raw_bytes,
        "rawSha256": value.raw_sha256,
        "compactTokens": value.compact_tokens,
        "omitted": value.omitted,
    }


def _decoded_observation_text(method: str, value: dict[str, Any]) -> str | None:
    """Return decoded output solely for the private writer's secret scan."""

    result = value.get("result")
    if not isinstance(result, dict):
        return None
    encoded_values: list[str] = []
    if method == "fs/readFile" and isinstance(result.get("dataBase64"), str):
        encoded_values.append(result["dataBase64"])
    elif method == "fs/readBlock" and isinstance(result.get("chunk"), str):
        encoded_values.append(result["chunk"])
    elif method == "process/read" and isinstance(result.get("chunks"), list):
        encoded_values.extend(
            item["chunk"]
            for item in result["chunks"]
            if isinstance(item, dict) and isinstance(item.get("chunk"), str)
        )
    decoded: list[str] = []
    for encoded in encoded_values:
        try:
            decoded.append(base64.b64decode(encoded, validate=True).decode(errors="replace"))
        except ValueError:
            continue
    return "\n".join(decoded) if decoded else None


__all__ = ["HweExecProtocolCollector", "HweExecProtocolError", "HweProtocolRecord"]
