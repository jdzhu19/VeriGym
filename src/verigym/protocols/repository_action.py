"""Canonical provider-neutral ``repository_action.v2`` parsing and validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from verigym.core.hashing import content_hash, hash_bytes
from verigym.schemas.action_protocol import (
    CanonicalRepositoryAction,
    ProviderNativeToolCall,
    RepositoryActionNormalization,
    RepositoryActionProtocolDescriptor,
    RepositoryActionProtocolSpec,
    RepositoryActionStateMachine,
    RepositoryActionTransport,
    RepositoryProtocolError,
)
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    FinalSubmissionAction,
    ToolCallAction,
)
from verigym.schemas.base import StrictModel
from verigym.schemas.options import JsonValue
from verigym.schemas.task import VeriTask
from verigym.schemas.tool import ToolResult

_FENCE = re.compile(r"\A```(?P<label>json)?[ \t]*\n(?P<body>[\s\S]*?)\n```\Z")
_SAFE_ACTION = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_TEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PATCH_HEADER = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?(?P<path>[^\t\n]+)", re.MULTILINE)


class _StrictArguments(StrictModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, strict=True)


class ListFilesArguments(_StrictArguments):
    path: str = "."
    recursive: bool = True


class ReadFileArguments(_StrictArguments):
    path: str


class ApplyPatchArguments(_StrictArguments):
    patch: str = Field(min_length=1, max_length=1024 * 1024)


class RunPublicTestArguments(_StrictArguments):
    test_id: str


class InspectDiffArguments(_StrictArguments):
    pass


class FinishArguments(_StrictArguments):
    message: str = Field(min_length=1, max_length=2048)


_ARGUMENT_MODELS: dict[str, type[_StrictArguments]] = {
    "list_files": ListFilesArguments,
    "read_file": ReadFileArguments,
    "apply_patch": ApplyPatchArguments,
    "run_public_test": RunPublicTestArguments,
    "inspect_diff": InspectDiffArguments,
    "finish": FinishArguments,
}


class RepositoryActionProtocolViolation(ValueError):
    """Expected fail-closed protocol rejection with a stable public subcategory."""

    def __init__(self, subcategory: RepositoryProtocolError, message: str) -> None:
        super().__init__(message)
        self.subcategory = subcategory


def action_registry() -> dict[str, Any]:
    """Generate the canonical registry from the strict registered argument schemas."""

    return {
        "schema_version": "2.0",
        "protocol": "repository_action.v2",
        "one_action_per_turn": True,
        "actions": {
            name: {
                "arguments_schema": model.model_json_schema(mode="validation"),
                "verigym_mapping": _ACTION_MAPPINGS[name],
            }
            for name, model in sorted(_ARGUMENT_MODELS.items())
        },
    }


_ACTION_MAPPINGS = {
    "list_files": "file.list",
    "read_file": "file.read",
    "apply_patch": "file.apply_patch",
    "run_public_test": "repository.public_test",
    "inspect_diff": "file.diff",
    "finish": "final_submission",
}


def prompt_contract(
    state_machine_id: RepositoryActionStateMachine = "repository_action_state_machine_v2",
) -> dict[str, Any]:
    """Return the deterministic action prompt contract derived from the registry."""

    registry = action_registry()
    prompt_contract_id = {
        "repository_action_state_machine_v1": "repository_action_v2_prompt_v1",
        "repository_action_state_machine_v2": "repository_action_v2_prompt_v2",
    }[state_machine_id]
    contract = {
        "schema_version": "1.0",
        "prompt_contract_id": prompt_contract_id,
        "protocol": "repository_action.v2",
        "required_response": {
            "protocol": "repository_action.v2",
            "action": "one registered action name",
            "arguments": "an object matching that action's strict schema",
        },
        "registry_hash": content_hash(registry),
        "registry": registry,
        "rules": [
            "Return exactly one action object and no prose.",
            "Use only registered actions; unrestricted shell is unavailable.",
            "Read visible files before editing.",
            (
                "Use registered public tests for bounded feedback."
                if state_machine_id == "repository_action_state_machine_v1"
                else "Use a registered public test when the task exposes one."
            ),
            "Inspect the candidate diff before finish.",
            "Never request credentials, network, hidden assets, or reference patches.",
        ],
    }
    if state_machine_id == "repository_action_state_machine_v2":
        contract["state_machine_id"] = state_machine_id
    return contract


def resolve_repository_action_protocol(
    *,
    agent_descriptor: object,
    protocol_spec: RepositoryActionProtocolSpec | None,
    agent_options: Mapping[str, JsonValue],
    task: VeriTask,
) -> RepositoryActionProtocolDescriptor | None:
    """Purely resolve the effective action protocol from actual agent configuration."""

    if protocol_spec is None:
        return None
    requested_protocol = agent_options.get("action_protocol")
    if requested_protocol not in {None, protocol_spec.protocol_id}:
        raise ValueError("agent action protocol differs from its plugin declaration")
    raw_transport = agent_options.get("action_transport", protocol_spec.default_transport)
    if raw_transport not in protocol_spec.supported_transports:
        raise ValueError("agent action transport is unsupported")
    transport: RepositoryActionTransport = raw_transport
    max_calls = _bounded_int(
        agent_options.get("max_completion_calls", protocol_spec.default_max_completion_calls),
        "max_completion_calls",
        1,
        128,
    )
    max_bytes = _bounded_int(
        agent_options.get("max_response_bytes", protocol_spec.default_max_response_bytes),
        "max_response_bytes",
        1024,
        4 * 1024 * 1024,
    )
    if task.budget.max_model_calls is not None and max_calls > task.budget.max_model_calls:
        raise ValueError("repository action completion-call limit exceeds the task model budget")
    registry_hash = content_hash(action_registry())
    contract_hash = content_hash(prompt_contract(protocol_spec.state_machine_id))
    public_ids = _public_test_ids(task)
    task_tool_contract = {
        "allowed_tools": sorted(task.interaction.allowed_tools),
        "denied_tools": sorted(task.interaction.denied_tools),
        "network_policy": task.interaction.network_policy,
        "editable_globs": sorted(task.workspace.editable_globs),
        "readonly_globs": sorted(task.workspace.readonly_globs),
        "public_test_ids": public_ids,
    }
    payload = {
        "resolver_id": "repository_action_protocol_resolver_v1",
        "protocol_id": protocol_spec.protocol_id,
        "protocol_version": protocol_spec.protocol_version,
        "action_transport": transport,
        "one_action_per_turn": True,
        "action_registry_hash": registry_hash,
        "prompt_contract_id": protocol_spec.prompt_contract_id,
        "prompt_contract_hash": contract_hash,
        "normalizer_id": protocol_spec.normalizer_id,
        "state_machine_id": protocol_spec.state_machine_id,
        "max_completion_calls": max_calls,
        "max_response_bytes": max_bytes,
        "agent_descriptor_hash": content_hash(agent_descriptor),
        "task_tool_contract_hash": content_hash(task_tool_contract),
    }
    return RepositoryActionProtocolDescriptor(
        resolver_id="repository_action_protocol_resolver_v1",
        protocol_id=protocol_spec.protocol_id,
        protocol_version=protocol_spec.protocol_version,
        action_transport=transport,
        one_action_per_turn=True,
        action_registry_hash=registry_hash,
        prompt_contract_id=protocol_spec.prompt_contract_id,
        prompt_contract_hash=contract_hash,
        normalizer_id=protocol_spec.normalizer_id,
        state_machine_id=protocol_spec.state_machine_id,
        max_completion_calls=max_calls,
        max_response_bytes=max_bytes,
        agent_descriptor_hash=content_hash(agent_descriptor),
        task_tool_contract_hash=content_hash(task_tool_contract),
        configuration_fingerprint=content_hash(payload),
    )


def validate_repository_action_protocol_binding(
    *,
    expected: RepositoryActionProtocolDescriptor | None,
    resolved: RepositoryActionProtocolDescriptor | None,
) -> None:
    if expected == resolved:
        return
    mismatches: list[str] = []
    expected_payload = expected.model_dump(mode="json") if expected is not None else {}
    resolved_payload = resolved.model_dump(mode="json") if resolved is not None else {}
    for field in sorted(set(expected_payload) | set(resolved_payload)):
        if expected_payload.get(field) != resolved_payload.get(field):
            mismatches.append(field)
    raise ValueError(
        "repository action protocol mismatch: " + ", ".join(mismatches or ["descriptor"])
    )


def repository_action_state_failure(
    action: str,
    *,
    state_machine_id: RepositoryActionStateMachine,
    public_test_required: bool,
    patch_applied: bool,
    public_observed: bool,
    diff_observed: bool,
    finished: bool,
) -> RepositoryProtocolError | None:
    """Validate one state transition without depending on an execution provider."""

    if finished:
        return "agent_invalid_state_transition"
    if action in {"run_public_test", "inspect_diff"} and not patch_applied:
        return "agent_invalid_state_transition"
    required_public_observation = (
        True if state_machine_id == "repository_action_state_machine_v1" else public_test_required
    )
    if action == "finish" and not (
        patch_applied and diff_observed and (public_observed or not required_public_observation)
    ):
        return "agent_finish_invalid"
    return None


def task_requires_public_test(task: VeriTask) -> bool:
    """Return whether the public action state machine requires a test observation."""

    return bool(_public_test_ids(task))


def canonical_repository_action_to_agent_action(
    action: str,
    arguments: _StrictArguments,
) -> AgentAction:
    """Map one validated canonical action to the ordinary VeriGym environment action."""

    if isinstance(arguments, ListFilesArguments):
        return ToolCallAction(tool="file.list", arguments=arguments.model_dump(mode="json"))
    if isinstance(arguments, ReadFileArguments):
        return ToolCallAction(tool="file.read", arguments=arguments.model_dump(mode="json"))
    if isinstance(arguments, ApplyPatchArguments):
        return ApplyPatchAction(patch=arguments.patch)
    if isinstance(arguments, RunPublicTestArguments):
        return ToolCallAction(
            tool="repository.public_test", arguments=arguments.model_dump(mode="json")
        )
    if isinstance(arguments, InspectDiffArguments):
        return ToolCallAction(tool="file.diff", arguments={})
    if isinstance(arguments, FinishArguments):
        return FinalSubmissionAction(message=arguments.message)
    raise RepositoryActionProtocolViolation(
        "agent_unknown_action", f"unmapped canonical repository action: {action}"
    )


def extract_json_content(
    raw: str | bytes,
    *,
    max_response_bytes: int,
) -> tuple[object, RepositoryActionNormalization]:
    """Perform only the explicitly allowed representation normalization."""

    raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
    raw_hash = hash_bytes(raw_bytes)
    if len(raw_bytes) > max_response_bytes:
        raise RepositoryActionProtocolViolation(
            "agent_response_oversized", "provider action response exceeds its frozen byte bound"
        )
    if not raw_bytes:
        raise RepositoryActionProtocolViolation("agent_empty_output", "provider action is empty")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositoryActionProtocolViolation(
            "agent_malformed_json", "provider action is not valid UTF-8"
        ) from exc
    decisions: list[str] = ["utf8_decoded"]
    if text.startswith("\ufeff"):
        text = text[1:]
        decisions.append("leading_bom_removed")
    normalized_lines = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized_lines != text:
        decisions.append("line_endings_normalized")
    text = normalized_lines
    stripped = text.strip()
    if stripped != text:
        decisions.append("outer_whitespace_stripped")
    text = stripped
    if not text:
        raise RepositoryActionProtocolViolation("agent_empty_output", "provider action is empty")
    fence = _FENCE.fullmatch(text)
    if fence is not None:
        text = fence.group("body").strip()
        decisions.append(
            "response_wide_json_fence_unwrapped"
            if fence.group("label") == "json"
            else "response_wide_unlabeled_fence_unwrapped"
        )
    elif text.startswith("```") or text.endswith("```"):
        raise RepositoryActionProtocolViolation(
            "agent_extra_prose", "response is not exactly one supported response-wide fence"
        )
    try:
        parsed = json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        if _looks_like_json_with_extra_prose(text):
            raise RepositoryActionProtocolViolation(
                "agent_extra_prose", "provider response contains prose outside the JSON object"
            ) from exc
        raise RepositoryActionProtocolViolation(
            "agent_malformed_json", "provider response is not strict JSON"
        ) from exc
    except ValueError as exc:
        raise RepositoryActionProtocolViolation(
            "agent_malformed_json", "provider response contains duplicate JSON object keys"
        ) from exc
    normalized_bytes = text.encode("utf-8")
    return parsed, RepositoryActionNormalization(
        raw_sha256=raw_hash,
        raw_bytes=len(raw_bytes),
        normalized_sha256=hash_bytes(normalized_bytes),
        normalized_bytes=len(normalized_bytes),
        decisions=decisions,  # type: ignore[arg-type]
    )


def extract_transport_action(
    *,
    transport: RepositoryActionTransport,
    text: str,
    native_tool_calls: Sequence[ProviderNativeToolCall],
    max_response_bytes: int,
) -> tuple[object, RepositoryActionNormalization | None]:
    """Extract one transport value without performing canonical validation."""

    if transport == "json_content":
        if native_tool_calls:
            raise RepositoryActionProtocolViolation(
                "agent_unsupported_transport", "json_content response included native tool calls"
            )
        return extract_json_content(text, max_response_bytes=max_response_bytes)
    if text.strip() or len(native_tool_calls) != 1:
        subcategory: RepositoryProtocolError = (
            "agent_multiple_actions"
            if len(native_tool_calls) > 1
            else "agent_unsupported_transport"
        )
        raise RepositoryActionProtocolViolation(
            subcategory, "native_tool_call transport requires exactly one call and no content"
        )
    call = native_tool_calls[0]
    if len(call.arguments_json.encode("utf-8")) > max_response_bytes:
        raise RepositoryActionProtocolViolation(
            "agent_response_oversized", "native tool arguments exceed the frozen byte bound"
        )
    try:
        arguments = json.loads(call.arguments_json, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RepositoryActionProtocolViolation(
            "agent_malformed_json", "native tool arguments are not strict JSON"
        ) from exc
    return {
        "protocol": "repository_action.v2",
        "action": call.name,
        "arguments": arguments,
    }, None


def validate_canonical_action(
    value: object,
    *,
    task: VeriTask,
) -> tuple[CanonicalRepositoryAction, _StrictArguments]:
    """Validate one extracted value against the canonical action registry and task."""

    if isinstance(value, list):
        if len(value) > 1:
            raise RepositoryActionProtocolViolation(
                "agent_multiple_actions", "provider returned multiple canonical actions"
            )
        raise RepositoryActionProtocolViolation(
            "agent_non_object_json", "canonical repository action must be a JSON object"
        )
    if not isinstance(value, dict):
        raise RepositoryActionProtocolViolation(
            "agent_non_object_json", "canonical repository action must be a JSON object"
        )
    legacy = value.get("actions")
    if isinstance(legacy, list) and len(legacy) > 1:
        raise RepositoryActionProtocolViolation(
            "agent_multiple_actions", "provider returned a legacy multi-action plan"
        )
    try:
        envelope = CanonicalRepositoryAction.model_validate(value)
    except ValidationError as exc:
        raise RepositoryActionProtocolViolation(
            "agent_invalid_arguments", "canonical repository action envelope is invalid"
        ) from exc
    _validate_no_forbidden_controls(envelope.model_dump(mode="json"))
    if not _SAFE_ACTION.fullmatch(envelope.action) or envelope.action not in _ARGUMENT_MODELS:
        raise RepositoryActionProtocolViolation(
            "agent_unknown_action", "provider requested an unregistered repository action"
        )
    try:
        arguments = _ARGUMENT_MODELS[envelope.action].model_validate(envelope.arguments)
    except ValidationError as exc:
        raise RepositoryActionProtocolViolation(
            "agent_invalid_arguments", "repository action arguments do not match the registry"
        ) from exc
    _validate_task_arguments(envelope.action, arguments, task)
    return envelope, arguments


def _validate_task_arguments(action: str, arguments: _StrictArguments, task: VeriTask) -> None:
    if isinstance(arguments, ListFilesArguments | ReadFileArguments):
        _validate_visible_path(arguments.path)
    elif isinstance(arguments, ApplyPatchArguments):
        headers = [match.group("path") for match in _PATCH_HEADER.finditer(arguments.patch)]
        if not headers or len(headers) % 2:
            raise RepositoryActionProtocolViolation(
                "agent_invalid_arguments", "patch lacks balanced strict file headers"
            )
        for path in headers:
            if path == "/dev/null":
                continue
            _validate_visible_path(path)
            if not path.startswith("repository/"):
                raise RepositoryActionProtocolViolation(
                    "agent_invalid_arguments", "patch target is outside the visible repository"
                )
    elif isinstance(arguments, RunPublicTestArguments):
        if not _SAFE_TEST_ID.fullmatch(arguments.test_id):
            raise RepositoryActionProtocolViolation(
                "agent_invalid_arguments", "public-test identity is malformed"
            )
        if arguments.test_id not in _public_test_ids(task):
            raise RepositoryActionProtocolViolation(
                "agent_invalid_arguments", "public-test identity is not task-declared"
            )


def _validate_visible_path(value: str) -> None:
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or any(ord(character) < 32 for character in value)
    ):
        raise RepositoryActionProtocolViolation(
            "agent_invalid_arguments", "repository action path is not a safe relative path"
        )
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts if value != "."):
        raise RepositoryActionProtocolViolation(
            "agent_invalid_arguments", "repository action path contains traversal"
        )
    forbidden = {"hidden", "reference", ".git", ".codex"}
    if any(part.lower() in forbidden for part in path.parts):
        raise RepositoryActionProtocolViolation(
            "agent_invalid_arguments", "repository action path names a forbidden asset class"
        )


def _validate_no_forbidden_controls(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_no_forbidden_controls(key)
            _validate_no_forbidden_controls(child)
    elif isinstance(value, list):
        for child in value:
            _validate_no_forbidden_controls(child)
    elif isinstance(value, str) and any(
        ord(character) < 32 and character not in {"\n", "\r", "\t"} for character in value
    ):
        raise RepositoryActionProtocolViolation(
            "agent_invalid_arguments", "repository action contains forbidden control characters"
        )


def _public_test_ids(task: VeriTask) -> list[str]:
    repository = task.metadata.get("repository_repair")
    raw = repository.get("public_test_ids") if isinstance(repository, dict) else None
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        return []
    return sorted(raw)


def bounded_tool_result_identity(result: ToolResult) -> dict[str, Any]:
    """Return the bounded observable result identity shared by execution and replay."""

    return {
        "tool": result.tool,
        "success": result.success,
        "category": result.category.value,
        "message": result.message[:2048],
        "stdout": result.stdout[:65_536],
        "stderr": result.stderr[:8192],
        "output_truncated": result.output_truncated,
        "metadata": result.metadata,
    }


def _bounded_int(value: JsonValue, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in [{minimum}, {maximum}]")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _looks_like_json_with_extra_prose(value: str) -> bool:
    first = value.find("{")
    last = value.rfind("}")
    return bool(
        first >= 0 and last > first and (value[:first].strip() or value[last + 1 :].strip())
    )


__all__ = [
    "ApplyPatchArguments",
    "FinishArguments",
    "InspectDiffArguments",
    "ListFilesArguments",
    "ReadFileArguments",
    "RepositoryActionProtocolViolation",
    "RunPublicTestArguments",
    "action_registry",
    "bounded_tool_result_identity",
    "canonical_repository_action_to_agent_action",
    "extract_json_content",
    "extract_transport_action",
    "prompt_contract",
    "repository_action_state_failure",
    "resolve_repository_action_protocol",
    "task_requires_public_test",
    "validate_canonical_action",
    "validate_repository_action_protocol_binding",
]
