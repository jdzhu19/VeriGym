"""Private broker for the canonical repository-tool surface."""

from __future__ import annotations

import json
import math
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.agents.external import ExternalAgentBridge
from verigym.core.agent_feedback import AGENT_FEEDBACK_INFRASTRUCTURE_SUBCATEGORIES
from verigym.core.errors import PathPolicyError
from verigym.core.repository_observation import bounded_text_with_marker
from verigym.protocols.repository_action import (
    RepositoryActionProtocolViolation,
    canonical_action_json,
    canonical_tool_observation,
    repository_action_state_failure,
    repository_tool_definitions,
)
from verigym.schemas.agent_feedback import AgentFeedbackContract
from verigym.schemas.options import JsonValue

_MAX_MESSAGE_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_TRAINING_CAPTURE_BYTES = 32 * 1024 * 1024
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TOOL_NAMES = frozenset(
    definition["name"] for definition in repository_tool_definitions(dialect="mcp")
)
_RECOVERABLE_PATCH_ERRORS = (
    ("invalid Codex patch hunk body", "patch_body"),
    ("invalid Codex patch:", "patch_format"),
    ("invalid unified patch hunk header", "patch_header"),
    ("invalid unified patch hunk body", "patch_body"),
    ("invalid unified patch: expected hunk header", "patch_header"),
    ("invalid unified patch: missing '+++' header", "patch_header"),
    ("invalid unified patch:", "patch_format"),
    ("patch context does not match the workspace", "patch_context"),
    ("patch hunk is out of range or overlaps a prior hunk", "patch_range"),
    ("patch hunk line counts do not match its header", "patch_count"),
    ("patch cannot have both paths set to /dev/null", "patch_format"),
    ("renames are not supported by file.apply_patch", "patch_rename"),
    ("renames are not supported by file.apply_codex_patch", "patch_rename"),
    ("patch file has no hunks", "patch_empty"),
    ("patch is empty", "patch_empty"),
)
_PATH_VIOLATION_CATEGORIES = frozenset(
    {
        "absolute",
        "traversal",
        "outside_editable",
        "readonly",
        "symlink",
        "hardlink",
        "hidden_or_protected",
        "unspecified",
    }
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
    policy_failure_subcategory: str | None = None
    infrastructure_failure_subcategory: str | None = None
    diff_inspections: int = 0
    finish_calls: int = 0
    rejected_calls: int = 0
    finished: bool = False
    limit_failure: str | None = None
    consecutive_rejected_calls: int = 0
    maximum_consecutive_rejected_calls: int = 0
    max_tool_calls: int | None = None
    max_patch_calls: int | None = None
    max_consecutive_rejected_calls: int | None = None
    wall_time_s: int | None = None
    elapsed_wall_time_s: int | None = None
    remaining_wall_time_s: int | None = None
    finalization_reserve_s: int | None = None
    max_exploratory_calls: int | None = None
    exploratory_calls: int = 0
    exploration_guard_calls: int = 0
    finalization_required: bool = False
    finalization_reason: str | None = None
    terminal_tool_name: str | None = None
    terminal_path_category: str | None = None
    tool_call_sequence: tuple[str, ...] = ()
    accepted_finish_call_index: int | None = None
    public_validation_calls: int = 0
    public_validation_passes: int = 0
    public_validation_failures: int = 0
    first_public_validation_passed: bool | None = None
    repair_patches_after_public_validation_failure: int = 0
    public_validation_rechecks_after_repair_patch: int = 0
    public_validation_failed_then_passed: bool = False
    patch_format_profile: str = "strict_unified_v1"


@dataclass(frozen=True)
class RepositoryToolBrokerLimits:
    """Provider-neutral episode limits enforced at the canonical tool boundary."""

    max_tool_calls: int
    max_patch_calls: int
    max_consecutive_rejected_calls: int

    def __post_init__(self) -> None:
        for label, value in (
            ("max_tool_calls", self.max_tool_calls),
            ("max_patch_calls", self.max_patch_calls),
            ("max_consecutive_rejected_calls", self.max_consecutive_rejected_calls),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4096:
                raise ValueError(f"repository broker {label} must be in [1, 4096]")
        if self.max_patch_calls > self.max_tool_calls:
            raise ValueError("repository broker patch limit cannot exceed its tool-call limit")


@dataclass(frozen=True)
class RepositoryToolBrokerTurn:
    """One canonical public action/observation pair captured only for training."""

    tool_name: str
    arguments_json: str
    observation_json: str


class RepositoryToolBroker:
    """Route six typed actions into an already isolated runtime bridge."""

    def __init__(
        self,
        *,
        bridge: ExternalAgentBridge,
        socket_path: Path,
        public_test_ids: tuple[str, ...],
        capture_training_transcript: bool = False,
        campaign_role: str | None = None,
        limits: RepositoryToolBrokerLimits | None = None,
        agent_feedback_contract: AgentFeedbackContract | None = None,
        wall_time_s: float | None = None,
        finalization_reserve_s: float | None = None,
        max_exploratory_calls: int | None = None,
        codex_patch_compatibility: bool = False,
    ) -> None:
        if capture_training_transcript and campaign_role != "training":
            raise ValueError("repository broker transcript capture is training-only")
        if wall_time_s is not None and (
            isinstance(wall_time_s, bool)
            or not isinstance(wall_time_s, (int, float))
            or not math.isfinite(wall_time_s)
            or wall_time_s <= 0
        ):
            raise ValueError("repository broker wall time must be a positive finite number")
        if finalization_reserve_s is not None and (
            wall_time_s is None
            or isinstance(finalization_reserve_s, bool)
            or not isinstance(finalization_reserve_s, (int, float))
            or not math.isfinite(finalization_reserve_s)
            or finalization_reserve_s <= 0
            or finalization_reserve_s >= wall_time_s
        ):
            raise ValueError(
                "repository broker finalization reserve must be positive and below wall time"
            )
        if max_exploratory_calls is not None and (
            isinstance(max_exploratory_calls, bool)
            or not isinstance(max_exploratory_calls, int)
            or not 1 <= max_exploratory_calls <= 4096
        ):
            raise ValueError("repository broker exploratory-call limit must be in [1, 4096]")
        self._bridge = bridge
        self.socket_path = socket_path
        self._public_test_ids = frozenset(public_test_ids)
        self._feedback_contract = agent_feedback_contract
        self._state_machine_id = (
            agent_feedback_contract.state_machine_id
            if agent_feedback_contract is not None
            else "repository_action_state_machine_v2"
        )
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.RLock()
        self._tool_calls = 0
        self._tool_call_sequence: list[str] = []
        self._public_test_calls = 0
        self._public_validation_calls = 0
        self._public_validation_passes = 0
        self._public_validation_failures = 0
        self._first_public_validation_passed: bool | None = None
        self._current_revision_public_validation_failed = False
        self._repair_patch_pending_public_validation = False
        self._repair_patches_after_public_validation_failure = 0
        self._public_validation_rechecks_after_repair_patch = 0
        self._public_validation_failed_then_passed = False
        self._file_reads = 0
        self._exploratory_calls = 0
        self._exploration_guard_calls = 0
        self._patches = 0
        self._diff_inspections = 0
        self._finish_calls = 0
        self._accepted_finish_call_index: int | None = None
        self._rejected_calls = 0
        self._consecutive_rejected_calls = 0
        self._maximum_consecutive_rejected_calls = 0
        self._current_call_rejected = False
        self._patch_applied = False
        self._public_observed = False
        self._compile_passed = False
        self._diff_observed = False
        self._finished = False
        self._policy_failure: str | None = None
        self._infrastructure_failure: str | None = None
        self._policy_failure_subcategory: str | None = None
        self._infrastructure_failure_subcategory: str | None = None
        self._limit_failure: str | None = None
        self._limits = limits
        self._wall_time_s = float(wall_time_s) if wall_time_s is not None else None
        self._finalization_reserve_s = (
            float(finalization_reserve_s) if finalization_reserve_s is not None else None
        )
        self._max_exploratory_calls = max_exploratory_calls
        self._codex_patch_compatibility = codex_patch_compatibility
        self._started_monotonic_s = time.monotonic()
        self._terminal_tool_name: str | None = None
        self._terminal_path_category: str | None = None
        self._cancellation = threading.Event()
        self._capture_training_transcript = capture_training_transcript
        self._training_turns: list[RepositoryToolBrokerTurn] = []
        self._training_capture_bytes = 0

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
            elapsed_wall_time_s, remaining_wall_time_s = self._wall_time_state_locked()
            finalization_reason = self._finalization_reason_locked()
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
                policy_failure_subcategory=self._policy_failure_subcategory,
                infrastructure_failure_subcategory=self._infrastructure_failure_subcategory,
                limit_failure=self._limit_failure,
                consecutive_rejected_calls=self._consecutive_rejected_calls,
                maximum_consecutive_rejected_calls=(self._maximum_consecutive_rejected_calls),
                max_tool_calls=self._limits.max_tool_calls if self._limits else None,
                max_patch_calls=self._limits.max_patch_calls if self._limits else None,
                max_consecutive_rejected_calls=(
                    self._limits.max_consecutive_rejected_calls if self._limits else None
                ),
                wall_time_s=(
                    int(round(self._wall_time_s)) if self._wall_time_s is not None else None
                ),
                elapsed_wall_time_s=elapsed_wall_time_s,
                remaining_wall_time_s=remaining_wall_time_s,
                finalization_reserve_s=(
                    int(round(self._finalization_reserve_s))
                    if self._finalization_reserve_s is not None
                    else None
                ),
                max_exploratory_calls=self._max_exploratory_calls,
                exploratory_calls=self._exploratory_calls,
                exploration_guard_calls=self._exploration_guard_calls,
                finalization_required=finalization_reason is not None,
                finalization_reason=finalization_reason,
                terminal_tool_name=self._terminal_tool_name,
                terminal_path_category=self._terminal_path_category,
                tool_call_sequence=tuple(self._tool_call_sequence),
                accepted_finish_call_index=self._accepted_finish_call_index,
                public_validation_calls=self._public_validation_calls,
                public_validation_passes=self._public_validation_passes,
                public_validation_failures=self._public_validation_failures,
                first_public_validation_passed=self._first_public_validation_passed,
                repair_patches_after_public_validation_failure=(
                    self._repair_patches_after_public_validation_failure
                ),
                public_validation_rechecks_after_repair_patch=(
                    self._public_validation_rechecks_after_repair_patch
                ),
                public_validation_failed_then_passed=(self._public_validation_failed_then_passed),
                patch_format_profile=(
                    "strict_unified_and_codex_native_v1"
                    if self._codex_patch_compatibility
                    else "strict_unified_v1"
                ),
            )

    @property
    def cancellation_event(self) -> threading.Event:
        """Signal the owning process runner when a broker-owned limit becomes terminal."""

        return self._cancellation

    def training_turns(self) -> tuple[RepositoryToolBrokerTurn, ...]:
        """Return canonical turns only when the broker was explicitly training-bound."""

        if not self._capture_training_transcript:
            raise RuntimeError("repository broker transcript capture was not enabled")
        with self._lock:
            return tuple(self._training_turns)

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
            if (
                self._policy_failure is not None
                or self._infrastructure_failure is not None
                or self._limit_failure is not None
            ):
                return self._error_result(
                    name, "tool broker stopped after a terminal safety failure"
                )
            self._tool_calls += 1
            self._tool_call_sequence.append(name)
            self._current_call_rejected = False
            if (
                name == "apply_patch"
                and self._limits is not None
                and self._patches >= self._limits.max_patch_calls
            ):
                self._record_rejection_locked()
                self._trip_limit_locked("repository_patch_call_limit")
                self._finalize_call_locked()
                return self._error_result(name, "repository patch-call limit reached")
            try:
                canonical_action = json.loads(canonical_action_json(name, arguments))
            except RepositoryActionProtocolViolation as exc:
                self._record_rejection_locked()
                self._finalize_call_locked()
                return self._error_result(name, exc.subcategory)
            canonical_arguments = json.dumps(
                canonical_action["arguments"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            guard_reason = (
                self._finalization_reason_locked() if name in {"list_files", "read_file"} else None
            )
            if guard_reason is not None:
                self._exploration_guard_calls += 1
                state_response = self._error_result(
                    name,
                    guard_reason,
                    error_subcategory=guard_reason,
                )
            else:
                if name in {"list_files", "read_file"}:
                    self._exploratory_calls += 1
                state_failure = repository_action_state_failure(
                    name,
                    state_machine_id=self._state_machine_id,
                    public_test_required=bool(self._public_test_ids),
                    patch_applied=self._patch_applied,
                    public_observed=self._public_observed,
                    diff_observed=self._diff_observed,
                    finished=self._finished,
                    public_test_id=(
                        arguments.get("test_id") if name == "run_public_test" else None
                    ),
                    compile_test_id=(
                        self._feedback_contract.compile_test_id
                        if self._feedback_contract is not None
                        else None
                    ),
                    compile_passed=self._compile_passed,
                    compile_required_for_finish=(
                        self._feedback_contract.compile_required_for_finish
                        if self._feedback_contract is not None
                        else False
                    ),
                )
                if state_failure is not None:
                    self._record_rejection_locked()
                    state_response = self._error_result(name, state_failure)
                else:
                    state_response = None
        if state_response is not None:
            return self._capture_response(name, canonical_arguments, state_response)
        try:
            if name == "list_files":
                response = self._workspace_result(name, "file.list", arguments)
                return self._capture_response(name, canonical_arguments, response)
            if name == "read_file":
                with self._lock:
                    self._file_reads += 1
                response = self._workspace_result(name, "file.read", arguments)
                return self._capture_response(name, canonical_arguments, response)
            if name == "apply_patch":
                with self._lock:
                    self._patches += 1
                response, _success = self._workspace_result_with_success(
                    name,
                    (
                        "file.apply_codex_patch"
                        if self._codex_patch_compatibility
                        else "file.apply_patch"
                    ),
                    arguments,
                )
                return self._capture_response(name, canonical_arguments, response)
            if name == "run_public_test":
                response = self._run_public_test(arguments)
                return self._capture_response(name, canonical_arguments, response)
            if name == "inspect_diff":
                with self._lock:
                    self._diff_inspections += 1
                response, _success = self._workspace_result_with_success(
                    name, "file.diff", arguments
                )
                return self._capture_response(name, canonical_arguments, response)
            if name == "finish":
                if set(arguments) != {"message"} or not isinstance(arguments["message"], str):
                    return self._error_result(name, "finish requires one string message")
                with self._lock:
                    self._finish_calls += 1
                    self._finished = True
                    self._accepted_finish_call_index = len(self._tool_call_sequence) - 1
                response = self._payload_result(
                    name, {"accepted": True, "terminal": True}, is_error=False
                )
                return self._capture_response(name, canonical_arguments, response)
        except PathPolicyError as exc:
            path_category = _path_violation_category(str(exc))
            with self._lock:
                self._set_policy_failure_locked(
                    "repository workspace path policy violation",
                    "workspace_path_policy",
                    terminal_tool_name=name,
                    terminal_path_category=path_category,
                )
            response = self._error_result(
                name,
                "repository workspace path policy violation",
                error_subcategory="workspace_path_policy",
                terminal_tool_name=name,
                path_violation_category=path_category,
            )
            return self._capture_response(name, canonical_arguments, response)
        except Exception:
            with self._lock:
                self._set_infrastructure_failure_locked(
                    "repository broker dispatch failed",
                    "broker_dispatch_internal_error",
                    terminal_tool_name=name,
                )
            response = self._error_result(name, "repository broker internal error")
            return self._capture_response(name, canonical_arguments, response)
        response = self._error_result(name, "unknown tool request")
        return self._capture_response(name, canonical_arguments, response)

    def _capture_response(
        self, name: str, arguments_json: str, response: dict[str, Any]
    ) -> dict[str, Any]:
        if self._capture_training_transcript:
            content = response.get("content")
            observation = (
                content[0].get("text")
                if isinstance(content, list)
                and len(content) == 1
                and isinstance(content[0], dict)
                and content[0].get("type") == "text"
                else None
            )
            if not isinstance(observation, str):
                with self._lock:
                    self._set_infrastructure_failure_locked(
                        "canonical training observation was unavailable",
                        "training_observation_internal_error",
                        terminal_tool_name=name,
                    )
                    self._finalize_call_locked()
                return response
            capture_bytes = len(arguments_json.encode("utf-8")) + len(observation.encode("utf-8"))
            with self._lock:
                if self._training_capture_bytes + capture_bytes > _MAX_TRAINING_CAPTURE_BYTES:
                    self._set_infrastructure_failure_locked(
                        "canonical training capture exceeded its bound",
                        "training_capture_limit",
                        terminal_tool_name=name,
                    )
                    self._finalize_call_locked()
                    return response
                self._training_turns.append(
                    RepositoryToolBrokerTurn(
                        tool_name=name,
                        arguments_json=arguments_json,
                        observation_json=observation,
                    )
                )
                self._training_capture_bytes += capture_bytes
        with self._lock:
            self._finalize_call_locked()
        return response

    def _record_rejection_locked(self) -> None:
        self._rejected_calls += 1
        self._current_call_rejected = True

    def _finalize_call_locked(self) -> None:
        if self._current_call_rejected:
            self._consecutive_rejected_calls += 1
            self._maximum_consecutive_rejected_calls = max(
                self._maximum_consecutive_rejected_calls,
                self._consecutive_rejected_calls,
            )
        else:
            self._consecutive_rejected_calls = 0
        self._current_call_rejected = False
        if self._limits is None or self._finished:
            return
        if self._consecutive_rejected_calls >= self._limits.max_consecutive_rejected_calls:
            self._trip_limit_locked("repository_consecutive_rejection_limit")
        elif self._tool_calls >= self._limits.max_tool_calls:
            self._trip_limit_locked("repository_tool_call_limit")

    def _trip_limit_locked(self, reason: str) -> None:
        if self._limit_failure is None:
            self._limit_failure = reason
            self._cancellation.set()

    def _set_policy_failure_locked(
        self,
        message: str,
        subcategory: str,
        *,
        terminal_tool_name: str | None = None,
        terminal_path_category: str | None = None,
    ) -> None:
        self._policy_failure = message
        self._policy_failure_subcategory = subcategory
        self._set_terminal_metadata_locked(terminal_tool_name, terminal_path_category)
        self._cancellation.set()

    def _set_infrastructure_failure_locked(
        self,
        message: str,
        subcategory: str,
        *,
        terminal_tool_name: str | None = None,
    ) -> None:
        self._infrastructure_failure = message
        self._infrastructure_failure_subcategory = subcategory
        self._set_terminal_metadata_locked(terminal_tool_name, None)
        self._cancellation.set()

    def _set_terminal_metadata_locked(
        self,
        terminal_tool_name: str | None,
        terminal_path_category: str | None,
    ) -> None:
        if self._terminal_tool_name is None and terminal_tool_name in _TOOL_NAMES:
            self._terminal_tool_name = terminal_tool_name
        if (
            self._terminal_path_category is None
            and terminal_path_category in _PATH_VIOLATION_CATEGORIES
        ):
            self._terminal_path_category = terminal_path_category

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
        failure_message = result.message or result.stderr or result.category.value
        error_subcategory: str | None = None
        path_violation_category: str | None = None
        if not result.success and result.category.value in {
            "permission_denied",
            "policy_denied",
            "sandbox_error",
        }:
            with self._lock:
                patch_category = (
                    _recoverable_patch_category(failure_message) if name == "apply_patch" else None
                )
                if patch_category is not None:
                    self._record_rejection_locked()
                    error_subcategory = patch_category
                else:
                    error_subcategory = _workspace_policy_subcategory(
                        name,
                        result.category.value,
                        failure_message,
                    )
                    path_violation_category = (
                        _path_violation_category(failure_message)
                        if error_subcategory == "workspace_path_policy"
                        else None
                    )
                    self._set_policy_failure_locked(
                        "repository workspace policy violation",
                        error_subcategory,
                        terminal_tool_name=name,
                        terminal_path_category=path_violation_category,
                    )
        elif not result.success and result.category.value == "internal_error":
            with self._lock:
                self._set_infrastructure_failure_locked(
                    "workspace tool internal error",
                    "workspace_tool_internal_error",
                    terminal_tool_name=name,
                )
        elif not result.success and result.category.value == "invalid_request":
            error_subcategory = _safe_error_subcategory(failure_message)
            with self._lock:
                self._record_rejection_locked()
        elif result.success:
            with self._lock:
                if name == "apply_patch":
                    if self._current_revision_public_validation_failed:
                        self._repair_patches_after_public_validation_failure += 1
                        self._repair_patch_pending_public_validation = True
                        self._current_revision_public_validation_failed = False
                    self._patch_applied = True
                    if self._feedback_contract is not None:
                        self._public_observed = False
                        self._compile_passed = False
                        self._diff_observed = False
                elif name == "inspect_diff":
                    self._diff_observed = True
        if not result.success:
            return (
                self._error_result(
                    name,
                    failure_message,
                    error_subcategory=error_subcategory,
                    terminal_tool_name=(name if path_violation_category is not None else None),
                    path_violation_category=path_violation_category,
                ),
                False,
            )
        return self._payload_result(name, payload, is_error=not result.success), result.success

    def _run_public_test(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = "run_public_test"
        if set(arguments) != {"test_id"} or not isinstance(arguments.get("test_id"), str):
            with self._lock:
                self._record_rejection_locked()
            return self._error_result(name, "run_public_test requires one string test_id")
        test_id = arguments["test_id"]
        if test_id not in self._public_test_ids:
            with self._lock:
                self._record_rejection_locked()
            return self._error_result(name, "public-test ID is not declared for this task")
        with self._lock:
            self._public_test_calls += 1
        completed = self._bridge.execute_public_test(test_id)
        if completed.failure_origin == "control_plane":
            subcategory = (
                completed.failure_reason
                if completed.failure_reason in AGENT_FEEDBACK_INFRASTRUCTURE_SUBCATEGORIES
                else "public_test_control_plane"
            )
            with self._lock:
                self._set_infrastructure_failure_locked(
                    "public-test control-plane failure",
                    subcategory,
                    terminal_tool_name=name,
                )
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
        policy = getattr(self._bridge, "observation_policy", None)
        if policy is not None:
            stdout, stdout_truncated = bounded_text_with_marker(
                payload["stdout"], policy.public_test_max_bytes, description="public-test stdout"
            )
            stderr, stderr_truncated = bounded_text_with_marker(
                payload["stderr"],
                min(policy.public_test_max_bytes, 2 * 1024),
                description="public-test stderr",
            )
            payload["stdout"] = stdout
            payload["stderr"] = stderr
            payload["output_truncated"] = bool(
                payload["output_truncated"] or stdout_truncated or stderr_truncated
            )
            payload["observation_policy_id"] = policy.policy_id
            payload["observation_omission_marker"] = "[verigym omission:"
        is_error = completed.exit_code not in {0}
        with self._lock:
            self._public_observed = True
            if (
                self._feedback_contract is not None
                and test_id == self._feedback_contract.compile_test_id
            ):
                passed = completed.exit_code == 0
                infrastructure = completed.failure_origin == "control_plane"
                self._compile_passed = passed
                self._public_validation_calls += 1
                if self._first_public_validation_passed is None:
                    self._first_public_validation_passed = passed
                if passed:
                    self._public_validation_passes += 1
                elif not infrastructure:
                    self._public_validation_failures += 1
                    self._current_revision_public_validation_failed = True
                if self._repair_patch_pending_public_validation:
                    self._public_validation_rechecks_after_repair_patch += 1
                    if passed:
                        self._public_validation_failed_then_passed = True
                    self._repair_patch_pending_public_validation = False
        return self._payload_result(name, payload, is_error=is_error)

    def _payload_result(
        self, name: str, payload: dict[str, Any], *, is_error: bool
    ) -> dict[str, Any]:
        with self._lock:
            enriched = {
                **payload,
                "state": self._state_summary_locked(),
                "next_allowed_actions": self._next_allowed_actions_locked(),
            }
        text = canonical_tool_observation(name, enriched, is_error=is_error)
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    def _error_result(
        self,
        name: str,
        message: str,
        *,
        error_subcategory: str | None = None,
        terminal_tool_name: str | None = None,
        path_violation_category: str | None = None,
    ) -> dict[str, Any]:
        tool_name = name if name in _TOOL_NAMES else "list_files"
        payload: dict[str, Any] = {
            "error_subcategory": error_subcategory or _safe_error_subcategory(message)
        }
        if terminal_tool_name in _TOOL_NAMES:
            payload["terminal_tool_name"] = terminal_tool_name
        if path_violation_category in _PATH_VIOLATION_CATEGORIES:
            payload["path_violation_category"] = path_violation_category
        return self._payload_result(
            tool_name,
            payload,
            is_error=True,
        )

    def _state_summary_locked(self) -> dict[str, Any]:
        terminal = (
            any(
                value is not None
                for value in (
                    self._policy_failure,
                    self._infrastructure_failure,
                    self._limit_failure,
                )
            )
            or self._pending_limit_locked()
        )
        finalization_reason = self._finalization_reason_locked()
        if terminal:
            phase = "terminal_failure"
        elif self._finished:
            phase = "finished"
        elif finalization_reason is not None:
            phase = "finalization_required"
        elif self._patch_applied and not self._compile_passed:
            phase = "current_revision_needs_compile"
        elif self._patch_applied and not self._diff_observed:
            phase = "current_revision_needs_diff"
        else:
            phase = "working"
        state: dict[str, Any] = {
            "phase": phase,
            "patch_applied": self._patch_applied,
            "compile_passed": self._compile_passed,
            "public_feedback_observed": self._public_observed,
            "latest_diff_observed": self._diff_observed,
            "finished": self._finished,
        }
        if self._finalization_reserve_s is not None or self._max_exploratory_calls is not None:
            state.update(
                {
                    "finalization_required": finalization_reason is not None,
                    "finalization_reason": finalization_reason,
                }
            )
        if self._limits is not None:
            state.update(
                {
                    "max_tool_calls": self._limits.max_tool_calls,
                    "max_patch_calls": self._limits.max_patch_calls,
                    "max_consecutive_rejected_calls": (self._limits.max_consecutive_rejected_calls),
                }
            )
        elapsed_wall_time_s, remaining_wall_time_s = self._wall_time_state_locked()
        if elapsed_wall_time_s is not None and remaining_wall_time_s is not None:
            state.update(
                {
                    "elapsed_wall_time_s": elapsed_wall_time_s,
                    "remaining_wall_time_s": remaining_wall_time_s,
                }
            )
        if self._finalization_reserve_s is not None:
            state["finalization_reserve_s"] = int(round(self._finalization_reserve_s))
        if self._max_exploratory_calls is not None:
            state.update(
                {
                    "max_exploratory_calls": self._max_exploratory_calls,
                    "exploratory_calls": self._exploratory_calls,
                }
            )
        return state

    def _wall_time_state_locked(self) -> tuple[int | None, int | None]:
        if self._wall_time_s is None:
            return None, None
        elapsed = max(0.0, time.monotonic() - self._started_monotonic_s)
        remaining = max(0.0, self._wall_time_s - elapsed)
        return int(round(elapsed)), int(round(remaining))

    def _finalization_reason_locked(self) -> str | None:
        if self._finished:
            return None
        if self._finalization_reserve_s is None and self._max_exploratory_calls is None:
            return None
        _elapsed, remaining = self._wall_time_state_locked()
        if (
            remaining is not None
            and self._finalization_reserve_s is not None
            and remaining <= int(round(self._finalization_reserve_s))
        ):
            return "finalization_reserve"
        if (
            self._max_exploratory_calls is not None
            and self._exploratory_calls >= self._max_exploratory_calls
        ):
            return "exploration_call_limit"
        return None

    def _next_allowed_actions_locked(self) -> list[str]:
        if (
            self._policy_failure is not None
            or self._infrastructure_failure is not None
            or self._limit_failure is not None
            or self._pending_limit_locked()
            or self._finished
        ):
            return []
        actions = (
            [] if self._finalization_reason_locked() is not None else ["list_files", "read_file"]
        )
        if self._limits is None or self._patches < self._limits.max_patch_calls:
            actions.append("apply_patch")
        if self._public_test_ids:
            actions.append("run_public_test")
        if self._patch_applied:
            actions.append("inspect_diff")
        finish_failure = repository_action_state_failure(
            "finish",
            state_machine_id=self._state_machine_id,
            public_test_required=bool(self._public_test_ids),
            patch_applied=self._patch_applied,
            public_observed=self._public_observed,
            diff_observed=self._diff_observed,
            finished=self._finished,
            public_test_id=None,
            compile_test_id=(
                self._feedback_contract.compile_test_id
                if self._feedback_contract is not None
                else None
            ),
            compile_passed=self._compile_passed,
            compile_required_for_finish=(
                self._feedback_contract.compile_required_for_finish
                if self._feedback_contract is not None
                else False
            ),
        )
        if finish_failure is None:
            actions.append("finish")
        return actions

    def _pending_limit_locked(self) -> bool:
        if self._limits is None or self._finished:
            return False
        consecutive = self._consecutive_rejected_calls + int(self._current_call_rejected)
        return (
            consecutive >= self._limits.max_consecutive_rejected_calls
            or self._tool_calls >= self._limits.max_tool_calls
        )


def _json_arguments(arguments: dict[str, Any]) -> dict[str, JsonValue]:
    encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    decoded = json.loads(encoded)
    assert isinstance(decoded, dict)
    return decoded


def _safe_error(text: str) -> str:
    clean = text.replace(str(Path.home()), "<redacted-root>")
    return _CONTROL.sub(" ", clean)


def _safe_error_subcategory(message: str) -> str:
    """Map caller-controlled diagnostics to a bounded, path-free category."""

    normalized = re.sub(r"[^a-z0-9]+", "_", message.lower()).strip("_")
    patch_category = _recoverable_patch_category(message)
    if patch_category is not None:
        return patch_category
    if any(
        marker in normalized
        for marker in (
            "absolute_path",
            "absolute_paths",
            "outside_workspace",
            "outside_editable_globs",
            "path_policy",
            "parent_path",
            "read_only",
            "not_editable",
            "not_available",
            "symlink",
            "hardlink",
            "hidden_asset",
            "credential",
        )
    ):
        return "workspace_path_policy"
    if "limit" in normalized:
        return "broker_resource_limit"
    if "public_test" in normalized or "test_id" in normalized:
        return "invalid_public_test"
    if normalized.startswith(("agent_", "repository_")) and len(normalized) <= 96:
        return normalized
    if "state" in normalized or "finish" in normalized:
        return "invalid_state_transition"
    if "internal" in normalized or "broker_error" in normalized:
        return "broker_internal_error"
    return "invalid_request"


def _workspace_policy_subcategory(name: str, category: str, message: str) -> str:
    safe = _safe_error_subcategory(message)
    if safe == "workspace_path_policy":
        return safe
    if category == "sandbox_error":
        return "workspace_sandbox_policy"
    if name == "apply_patch":
        return "workspace_patch_policy"
    return "workspace_access_policy"


def _recoverable_patch_category(message: str) -> str | None:
    for prefix, category in _RECOVERABLE_PATCH_ERRORS:
        if message.startswith(prefix):
            return category
    return None


def _path_violation_category(message: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", message.lower()).strip("_")
    if "absolute" in normalized:
        return "absolute"
    if "traversal" in normalized or "parent_path" in normalized:
        return "traversal"
    if "hardlink" in normalized or "hard_link" in normalized:
        return "hardlink"
    if "symlink" in normalized or "symbolic_link" in normalized:
        return "symlink"
    if "read_only" in normalized or "readonly" in normalized:
        return "readonly"
    if any(
        marker in normalized
        for marker in (
            "hidden",
            "protected",
            "credential",
            "not_available",
            "excluded",
            "internal",
        )
    ):
        return "hidden_or_protected"
    if "outside_editable" in normalized or "not_editable" in normalized:
        return "outside_editable"
    return "unspecified"


__all__ = [
    "RepositoryToolBroker",
    "RepositoryToolBrokerLimits",
    "RepositoryToolBrokerStats",
    "RepositoryToolBrokerTurn",
]
