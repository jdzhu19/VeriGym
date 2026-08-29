"""Canonical provider-neutral ``repository_action.v2`` parsing and validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

from pydantic import ConfigDict, Field, ValidationError, model_validator

from verigym.core.agent_feedback import public_feedback_test_ids
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.repository_observation import (
    BOUNDED_REPOSITORY_OBSERVATION_POLICY,
    REPOSITORY_OBSERVATION_POLICY_ID,
    resolve_repository_observation_policy,
)
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

# This is the pre-bounded v1 OpenAI tool-contract identity.  Keep it as a literal so a
# historical transcript can be checked after the live registry grows optional bounded-view
# arguments and descriptions.
LEGACY_REPOSITORY_TOOL_CONTRACT_HASH = (
    "2234b7de9631d2916ac24c3f6b42653c7c203c9528ee3436935bd77439722b8d"
)
LEGACY_REPOSITORY_ACTION_REGISTRY_HASH = (
    "c60164616d37a85b33d6aa3df39ba3ac422ac4650b32265f7da5ae2aaf69f03b"
)


class _StrictArguments(StrictModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, strict=True)


class ListFilesArguments(_StrictArguments):
    path: str = "."
    recursive: bool = True
    # Optional fields keep historical action serialization stable when omitted.
    max_depth: int | None = Field(default=None, ge=0, le=64)
    max_entries: int | None = Field(default=None, ge=1, le=4096)


class ReadFileArguments(_StrictArguments):
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    concise: bool | None = None

    @model_validator(mode="after")
    def validate_line_range(self) -> ReadFileArguments:
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.start_line > self.end_line
        ):
            raise ValueError("read_file start_line must not be after end_line")
        return self


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

_ACTION_DESCRIPTIONS = {
    "list_files": (
        "List visible task-workspace files using safe relative paths. Start with the default "
        "shallow view and use read_file for a local slice."
    ),
    "read_file": (
        "Read one visible UTF-8 task-workspace file by relative path. Prefer a bounded line "
        "range or concise view before requesting a whole large file."
    ),
    "apply_patch": (
        "Apply one unified diff to editable repository paths. The patch must use exact "
        "--- a/path and +++ b/path file headers plus numbered "
        "@@ -old,count +new,count @@ hunk headers; do not use *** Update File syntax."
    ),
    "run_public_test": "Run one exact task-declared public test.",
    "inspect_diff": "Inspect the current canonical candidate diff.",
    "finish": "Finish after applying a patch and inspecting the candidate diff.",
}


def repository_tool_definitions(*, dialect: str = "openai") -> list[dict[str, Any]]:
    """Derive provider tool definitions from the canonical action registry.

    The returned schemas are intentionally copies of the registry schemas. Providers may
    rename their surrounding fields, but they do not get a second independently maintained
    argument contract.
    """

    registry = action_registry()["actions"]
    if not isinstance(registry, dict):  # pragma: no cover - action_registry is local and typed
        raise RuntimeError("repository action registry is malformed")
    definitions: list[dict[str, Any]] = []
    for name in sorted(registry):
        entry = registry[name]
        if not isinstance(entry, dict) or not isinstance(entry.get("arguments_schema"), dict):
            raise RuntimeError("repository action registry entry is malformed")
        schema = json.loads(json.dumps(entry["arguments_schema"]))
        if dialect == "openai":
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": _ACTION_DESCRIPTIONS[name],
                        "parameters": schema,
                    },
                }
            )
        elif dialect == "mcp":
            definitions.append(
                {
                    "name": name,
                    "description": _ACTION_DESCRIPTIONS[name],
                    "inputSchema": schema,
                }
            )
        else:
            raise ValueError("repository tool dialect must be 'openai' or 'mcp'")
    return definitions


def legacy_repository_tool_contract_hash() -> str:
    """Return the frozen v1 tool-contract hash without exposing a second live registry."""

    return LEGACY_REPOSITORY_TOOL_CONTRACT_HASH


def legacy_repository_action_registry_hash() -> str:
    """Return the frozen v1 registry identity used by historical replay manifests."""

    return LEGACY_REPOSITORY_ACTION_REGISTRY_HASH


def _legacy_action_registry() -> dict[str, Any]:
    """Project the current registry back to the exact pre-bounded v1 schema."""

    registry = deepcopy(action_registry())
    list_properties = registry["actions"]["list_files"]["arguments_schema"]["properties"]
    list_properties.pop("max_depth", None)
    list_properties.pop("max_entries", None)
    read_properties = registry["actions"]["read_file"]["arguments_schema"]["properties"]
    read_properties.pop("start_line", None)
    read_properties.pop("end_line", None)
    read_properties.pop("concise", None)
    if content_hash(registry) != LEGACY_REPOSITORY_ACTION_REGISTRY_HASH:  # pragma: no cover
        raise RuntimeError("the historical repository action registry projection changed")
    return registry


def canonical_action_json(name: str, arguments: Mapping[str, Any]) -> str:
    """Serialize one provider-native call as a ``repository_action.v2`` envelope."""

    if name not in _ARGUMENT_MODELS:
        raise RepositoryActionProtocolViolation(
            "agent_unknown_action", "provider requested an unregistered repository action"
        )
    try:
        parsed = _ARGUMENT_MODELS[name].model_validate(dict(arguments))
    except ValidationError as exc:
        raise RepositoryActionProtocolViolation(
            "agent_invalid_arguments", "repository action arguments do not match the registry"
        ) from exc
    value = {
        "protocol": "repository_action.v2",
        "action": name,
        # Keep omitted optional bounded-view controls out of historical call identities.
        "arguments": parsed.model_dump(mode="json", exclude_none=True),
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_tool_observation(
    name: str,
    payload: Mapping[str, Any],
    *,
    is_error: bool,
    observation_policy_id: str | None = None,
) -> str:
    """Serialize a bounded public tool result identically for every harness."""

    if name not in _ARGUMENT_MODELS:
        raise ValueError("cannot serialize an observation for an unknown repository tool")
    value = {
        "schema_version": "1.0",
        "protocol": "repository_action.v2",
        "tool": name,
        "is_error": is_error,
        "result": dict(payload),
    }
    if observation_policy_id is None:
        candidate = payload.get("observation_policy_id")
        if isinstance(candidate, str):
            observation_policy_id = candidate
    if observation_policy_id is None:
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            candidate = metadata.get("observation_policy_id")
            if isinstance(candidate, str):
                observation_policy_id = candidate
    if observation_policy_id is not None:
        if observation_policy_id != REPOSITORY_OBSERVATION_POLICY_ID:
            raise ValueError("unsupported repository observation policy identity")
        value["observation_policy_id"] = observation_policy_id
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def prompt_contract(
    state_machine_id: RepositoryActionStateMachine = "repository_action_state_machine_v2",
    *,
    prompt_contract_id: str | None = None,
) -> dict[str, Any]:
    """Return the deterministic action prompt contract derived from the registry."""

    registry = (
        _legacy_action_registry()
        if state_machine_id == "repository_action_state_machine_v1"
        else action_registry()
    )
    registry_hash = (
        LEGACY_REPOSITORY_ACTION_REGISTRY_HASH
        if state_machine_id == "repository_action_state_machine_v1"
        else content_hash(registry)
    )
    default_prompt_contract_id = {
        "repository_action_state_machine_v1": "repository_action_v2_prompt_v1",
        "repository_action_state_machine_v2": "repository_action_v2_prompt_v2",
        "repository_action_state_machine_v3": "repository_action_v2_prompt_v3",
    }[state_machine_id]
    selected_prompt_contract_id = prompt_contract_id or default_prompt_contract_id
    compatible_prompt_contracts = {default_prompt_contract_id}
    if state_machine_id == "repository_action_state_machine_v3":
        compatible_prompt_contracts.update(
            {
                "repository_action_v2_prompt_v4",
                "repository_action_v2_prompt_v5",
                "repository_action_v2_prompt_v6",
            }
        )
    if selected_prompt_contract_id not in compatible_prompt_contracts:
        raise ValueError("repository action prompt is incompatible with its state machine")
    contract: dict[str, Any] = {
        "schema_version": "1.0",
        "prompt_contract_id": selected_prompt_contract_id,
        "protocol": "repository_action.v2",
        "required_response": {
            "protocol": "repository_action.v2",
            "action": "one registered action name",
            "arguments": "an object matching that action's strict schema",
        },
        "registry_hash": registry_hash,
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
    if state_machine_id in {
        "repository_action_state_machine_v2",
        "repository_action_state_machine_v3",
    }:
        contract["state_machine_id"] = state_machine_id
        contract["observation_policy"] = BOUNDED_REPOSITORY_OBSERVATION_POLICY.identity()
        contract["rules"].extend(
            [
                "Begin with the bounded shallow list_files view; do not recursively enumerate "
                "large trees.",
                "Use read_file start_line/end_line or concise=true for large files.",
                "Every bounded omission is explicit; never infer that an omitted region is empty.",
            ]
        )
    if state_machine_id == "repository_action_state_machine_v3":
        contract["rules"].extend(
            [
                "Every successful patch invalidates compile, PPA, and diff evidence.",
                "PPA requires compile to pass for the exact current candidate revision.",
                "Finish requires a current compile pass when compile is exposed and a current "
                "diff.",
            ]
        )
    if selected_prompt_contract_id in {
        "repository_action_v2_prompt_v4",
        "repository_action_v2_prompt_v5",
    }:
        contract["rules"].extend(
            [
                "Use repository-relative editable paths exactly as supplied by the task.",
                "Track the broker-reported elapsed and remaining wall time and reserve the "
                "final minute for validation and typed finish.",
                "Treat tool-call and patch-call limits as hard episode budgets.",
            ]
        )
    if selected_prompt_contract_id in {
        "repository_action_v2_prompt_v5",
    }:
        contract["rules"].extend(
            [
                "When remaining wall time is at most one minute, stop optional reading and "
                "finalize immediately.",
                "Do not end with assistant text before the typed finish action.",
            ]
        )
    if selected_prompt_contract_id == "repository_action_v2_prompt_v6":
        contract["rules"].extend(
            [
                "Use repository-relative editable paths exactly as supplied by the task.",
                "Track broker-reported elapsed and remaining wall time without relying on an "
                "absolute deadline.",
                "Treat tool-call, patch-call, and exploratory-call limits as hard episode budgets.",
                "The broker stops optional exploration after twelve file calls or when the "
                "final ninety-second reserve begins.",
                "Do not end with assistant text before the typed finish action.",
                "When finalization is required, use only broker-advertised next actions.",
            ]
        )
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
    raw_observation_policy = agent_options.get(
        "observation_policy_id", agent_options.get("observation_policy")
    )
    feedback = task.metadata.get("agent_feedback_contract")
    effective_state_machine: RepositoryActionStateMachine = (
        "repository_action_state_machine_v3"
        if isinstance(feedback, dict)
        else protocol_spec.state_machine_id
    )
    default_prompt_contract_id = {
        "repository_action_state_machine_v1": "repository_action_v2_prompt_v1",
        "repository_action_state_machine_v2": "repository_action_v2_prompt_v2",
        "repository_action_state_machine_v3": "repository_action_v2_prompt_v3",
    }[effective_state_machine]
    effective_prompt_contract_id = (
        protocol_spec.prompt_contract_id
        if effective_state_machine == "repository_action_state_machine_v3"
        and protocol_spec.prompt_contract_id
        in {
            "repository_action_v2_prompt_v4",
            "repository_action_v2_prompt_v5",
            "repository_action_v2_prompt_v6",
        }
        else default_prompt_contract_id
    )
    if raw_observation_policy is None and effective_state_machine in {
        "repository_action_state_machine_v2",
        "repository_action_state_machine_v3",
    }:
        raw_observation_policy = "repository_observation_v1"
    observation_policy = resolve_repository_observation_policy(raw_observation_policy)
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
    registry_hash = (
        legacy_repository_action_registry_hash()
        if effective_state_machine == "repository_action_state_machine_v1"
        else content_hash(action_registry())
    )
    contract_hash = content_hash(
        prompt_contract(
            effective_state_machine,
            prompt_contract_id=effective_prompt_contract_id,
        )
    )
    public_ids = _public_test_ids(task)
    task_tool_contract: dict[str, Any] = {
        "allowed_tools": sorted(task.interaction.allowed_tools),
        "denied_tools": sorted(task.interaction.denied_tools),
        "network_policy": task.interaction.network_policy,
        "editable_globs": sorted(task.workspace.editable_globs),
        "readonly_globs": sorted(task.workspace.readonly_globs),
        "public_test_ids": public_ids,
    }
    if observation_policy is not None:
        task_tool_contract["observation_policy"] = observation_policy.identity()
    if isinstance(feedback, dict):
        task_tool_contract["agent_feedback_contract_hash"] = content_hash(feedback)
    payload: dict[str, Any] = {
        "resolver_id": "repository_action_protocol_resolver_v1",
        "protocol_id": protocol_spec.protocol_id,
        "protocol_version": protocol_spec.protocol_version,
        "action_transport": transport,
        "one_action_per_turn": True,
        "action_registry_hash": registry_hash,
        "prompt_contract_id": effective_prompt_contract_id,
        "prompt_contract_hash": contract_hash,
        "normalizer_id": protocol_spec.normalizer_id,
        "state_machine_id": effective_state_machine,
        "max_completion_calls": max_calls,
        "max_response_bytes": max_bytes,
        "agent_descriptor_hash": content_hash(agent_descriptor),
        "task_tool_contract_hash": content_hash(task_tool_contract),
    }
    return RepositoryActionProtocolDescriptor.model_validate(
        {**payload, "configuration_fingerprint": content_hash(payload)}
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
    public_test_id: str | None = None,
    compile_test_id: str | None = None,
    compile_passed: bool = False,
    compile_required_for_finish: bool = False,
) -> RepositoryProtocolError | None:
    """Validate one state transition without depending on an execution provider."""

    if finished:
        return "agent_invalid_state_transition"
    if action in {"run_public_test", "inspect_diff"} and not patch_applied:
        return "agent_invalid_state_transition"
    if (
        state_machine_id == "repository_action_state_machine_v3"
        and action == "run_public_test"
        and public_test_id == "ppa"
        and not compile_passed
    ):
        return "agent_invalid_state_transition"
    required_public_observation = (
        True if state_machine_id == "repository_action_state_machine_v1" else public_test_required
    )
    if action == "finish":
        if state_machine_id == "repository_action_state_machine_v3":
            if not (
                patch_applied
                and diff_observed
                and (compile_passed or not compile_required_for_finish)
            ):
                return "agent_finish_invalid"
        elif not (
            patch_applied and diff_observed and (public_observed or not required_public_observation)
        ):
            return "agent_finish_invalid"
    return None


def task_requires_public_test(task: VeriTask) -> bool:
    """Return whether the public action state machine requires a test observation."""

    feedback = task.metadata.get("agent_feedback_contract")
    if isinstance(feedback, dict):
        return bool(feedback.get("compile_required_for_finish"))
    return bool(_public_test_ids(task))


def canonical_repository_action_to_agent_action(
    action: str,
    arguments: _StrictArguments,
) -> AgentAction:
    """Map one validated canonical action to the ordinary VeriGym environment action."""

    if isinstance(arguments, ListFilesArguments):
        return ToolCallAction(
            tool="file.list", arguments=arguments.model_dump(mode="json", exclude_none=True)
        )
    if isinstance(arguments, ReadFileArguments):
        return ToolCallAction(
            tool="file.read", arguments=arguments.model_dump(mode="json", exclude_none=True)
        )
    if isinstance(arguments, ApplyPatchArguments):
        return ApplyPatchAction(patch=arguments.patch)
    if isinstance(arguments, RunPublicTestArguments):
        return ToolCallAction(
            tool="repository.public_test",
            arguments=arguments.model_dump(mode="json", exclude_none=True),
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
    return public_feedback_test_ids(task)


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
    "canonical_action_json",
    "canonical_repository_action_to_agent_action",
    "canonical_tool_observation",
    "extract_json_content",
    "extract_transport_action",
    "LEGACY_REPOSITORY_ACTION_REGISTRY_HASH",
    "LEGACY_REPOSITORY_TOOL_CONTRACT_HASH",
    "prompt_contract",
    "repository_tool_definitions",
    "legacy_repository_action_registry_hash",
    "legacy_repository_tool_contract_hash",
    "repository_action_state_failure",
    "resolve_repository_action_protocol",
    "task_requires_public_test",
    "validate_canonical_action",
    "validate_repository_action_protocol_binding",
]
