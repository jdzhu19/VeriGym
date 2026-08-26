"""Verifier-gated, exact-context OpenHands trajectory collection for SFT."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.repository_tool_broker import RepositoryToolBrokerTurn
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl, atomic_write_text
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID, canonical_hwe_action_json
from verigym.hwe.qwen_action_tokenizer import (
    QwenDecisionExampleTokenizer,
    exact_decision_token_receipt,
)
from verigym.hwe.trajectory import HweNormalizedEvent
from verigym.protocols.repository_action import canonical_action_json

from ._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_MESSAGE,
    OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
    OPENHANDS_FORMAT_RECOVERY_REASON_SHA256,
)

OPENHANDS_TRAJECTORY_FORMAT = "verigym_openhands_exact_tool_trajectory_v1"
OPENHANDS_RECOVERY_TRAJECTORY_FORMAT = "verigym_openhands_exact_tool_trajectory_v2"
OPENHANDS_DECISION_FORMAT = "verigym_openhands_decision_sft_64k_v1"
OPENHANDS_RECOVERY_DECISION_FORMAT = "verigym_openhands_decision_sft_64k_v2"
OPENHANDS_DATASET_FORMAT = "verigym_openhands_decision_sft_dataset_64k_v1"
OPENHANDS_RECOVERY_DATASET_FORMAT = "verigym_openhands_decision_sft_dataset_64k_v2"
OPENHANDS_SDK_VERSION = "1.42.1"
OPENHANDS_MAX_LENGTH = 65_536

_MAX_MESSAGE_BYTES = 2 * 1024 * 1024
_MAX_TRAJECTORY_BYTES = 32 * 1024 * 1024
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HOST_PATH = re.compile(r"/(?:home|data|tmp|hpc)/|[A-Za-z]:\\", re.IGNORECASE)
_SENSITIVE = re.compile(
    r"(?:\b(?:authorization|password|api[_ -]?key|access[_ -]?token)\s*[:=]|"
    r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}|\b(?:sk|ds)-[A-Za-z0-9_-]{12,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)",
    re.IGNORECASE,
)
_CONTRACT_TOOLS = {
    "repository_action.v2": frozenset(
        {
            "apply_patch",
            "finish",
            "inspect_diff",
            "list_files",
            "read_file",
            "run_public_test",
        }
    ),
    "hwe_native_shell_v2": frozenset(
        {"apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell"}
    ),
}


class OpenHandsTrajectoryError(ValueError):
    """The model-visible episode is policy-ineligible for trajectory export."""


class OpenHandsTrajectoryInfrastructureError(RuntimeError):
    """OpenHands and broker evidence cannot be causally reconciled."""


class OpenHandsEvent(Protocol):
    """Runtime subset used to snapshot OpenHands without importing the optional SDK."""

    id: str
    parent_id: str | None
    source: str

    def to_llm_message(self) -> Any: ...


@dataclass(frozen=True)
class BrokerTurnReceipt:
    """One broker-owned semantic action and public observation binding."""

    call_id: str | None
    tool_name: str
    arguments_json: str
    observation_sha256: str


def snapshot_openhands_events(events: Sequence[object]) -> list[dict[str, Any]]:
    """Capture only model-visible messages plus content-free causal metadata."""

    snapshots: list[dict[str, Any]] = []
    for event in events:
        event_type = type(event).__name__
        base: dict[str, Any] = {
            "event_type": event_type,
            "event_id": getattr(event, "id", None),
            "parent_id": getattr(event, "parent_id", None),
            "source": getattr(event, "source", None),
        }
        if event_type == "SystemPromptEvent":
            base.update(
                {
                    "message": _dump_llm_message(event),
                    "dynamic_context_present": getattr(event, "dynamic_context", None) is not None,
                }
            )
        elif event_type == "MessageEvent":
            base.update(
                {
                    "message": _dump_llm_message(event),
                    "activated_skills": list(getattr(event, "activated_skills", [])),
                    "extended_content_present": bool(getattr(event, "extended_content", [])),
                    "critic_present": getattr(event, "critic_result", None) is not None,
                }
            )
        elif event_type == "ActionEvent":
            tool_call = getattr(event, "tool_call", None)
            base.update(
                {
                    "message": _dump_llm_message(event),
                    "tool_name": getattr(event, "tool_name", None),
                    "tool_call_id": getattr(event, "tool_call_id", None),
                    "tool_call": _plain(tool_call),
                    "llm_response_id": getattr(event, "llm_response_id", None),
                    "reasoning_content_present": bool(getattr(event, "reasoning_content", None)),
                    "thinking_blocks_present": bool(getattr(event, "thinking_blocks", [])),
                    "responses_reasoning_present": (
                        getattr(event, "responses_reasoning_item", None) is not None
                    ),
                    "critic_present": getattr(event, "critic_result", None) is not None,
                }
            )
        elif event_type == "ObservationEvent":
            base.update(
                {
                    "message": _dump_llm_message(event),
                    "tool_name": getattr(event, "tool_name", None),
                    "tool_call_id": getattr(event, "tool_call_id", None),
                    "action_id": getattr(event, "action_id", None),
                    "extended_content_present": bool(getattr(event, "extended_content", [])),
                }
            )
        elif event_type == "HookExecutionEvent":
            reason = getattr(event, "reason", None)
            base.update(
                {
                    "hook_event_type": getattr(event, "hook_event_type", None),
                    "success": getattr(event, "success", None),
                    "blocked": getattr(event, "blocked", None),
                    "exit_code": getattr(event, "exit_code", None),
                    "reason_sha256": (
                        hashlib.sha256(reason.encode()).hexdigest()
                        if isinstance(reason, str)
                        else None
                    ),
                    "stdout_present": bool(getattr(event, "stdout", "")),
                    "stderr_present": bool(getattr(event, "stderr", "")),
                    "additional_context_present": bool(getattr(event, "additional_context", None)),
                    "error_present": bool(getattr(event, "error", None)),
                }
            )
        snapshots.append(base)
    return snapshots


def snapshot_openhands_tools(tools: Sequence[object]) -> list[dict[str, Any]]:
    """Freeze the exact OpenAI tool schemas produced by OpenHands 1.42.1."""

    result: list[dict[str, Any]] = []
    for tool in tools:
        converter = getattr(tool, "to_openai_tool", None)
        if not callable(converter):
            raise OpenHandsTrajectoryInfrastructureError(
                "OpenHands tool cannot expose its effective OpenAI schema"
            )
        # Agent 1.42.1 enables its model-visible security-risk field when
        # serializing MCP tools. The MCP adapter strips this metadata before
        # broker validation, but exact-context SFT must retain the request schema.
        value = _plain(converter(add_security_risk_prediction=True))
        if not isinstance(value, dict):
            raise OpenHandsTrajectoryInfrastructureError(
                "OpenHands effective tool schema is not an object"
            )
        result.append(value)
    return result


def repository_broker_receipts(
    turns: Sequence[RepositoryToolBrokerTurn],
) -> tuple[BrokerTurnReceipt, ...]:
    """Bind OpenHands events to compact observations owned by the repository broker."""

    return tuple(
        BrokerTurnReceipt(
            call_id=None,
            tool_name=turn.tool_name,
            arguments_json=turn.arguments_json,
            observation_sha256=hashlib.sha256(turn.observation_json.encode()).hexdigest(),
        )
        for turn in turns
    )


def hwe_broker_receipts(
    events: Sequence[HweNormalizedEvent], call_ids: Sequence[str]
) -> tuple[BrokerTurnReceipt, ...]:
    """Bind OpenHands HWE events to the DeepSeek broker's public compact layer."""

    if len(events) != len(call_ids):
        raise OpenHandsTrajectoryInfrastructureError("HWE broker event and call-ID counts differ")
    if any(not call_id for call_id in call_ids) or len(set(call_ids)) != len(call_ids):
        raise OpenHandsTrajectoryInfrastructureError("HWE broker call IDs are empty or duplicate")
    receipts: list[BrokerTurnReceipt] = []
    for event, _call_id in zip(events, call_ids, strict=True):
        if event.compact_observation_sha256 is None:
            raise OpenHandsTrajectoryInfrastructureError(
                "HWE broker event omits its compact observation hash"
            )
        arguments_json = json.dumps(
            event.arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        receipts.append(
            BrokerTurnReceipt(
                # MCP JSON-RPC request IDs and model tool-call IDs are distinct
                # transports. The broker validates its IDs; the collector binds
                # the model IDs by strict ordered name/arguments/observation evidence.
                call_id=None,
                tool_name=event.action,
                arguments_json=arguments_json,
                observation_sha256=event.compact_observation_sha256,
            )
        )
    return tuple(receipts)


def build_openhands_training_trajectory(
    *,
    task_id: str,
    provider: str,
    model_id: str,
    configuration_fingerprint: str,
    event_snapshots: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    broker_turns: Sequence[BrokerTurnReceipt],
    tool_contract: Literal["repository_action.v2", "hwe_native_shell_v2"],
    recovery_policy_id: str | None = None,
) -> dict[str, Any]:
    """Reconcile the OpenHands event stream with one broker-owned successful episode."""

    if not task_id or not model_id or not provider:
        raise OpenHandsTrajectoryError("OpenHands trajectory identity is incomplete")
    _require_hash(configuration_fingerprint, "configuration fingerprint")
    exact_tools = [copy.deepcopy(dict(item)) for item in tools]
    tool_names = _validate_tools(exact_tools, tool_contract=tool_contract)
    if recovery_policy_id not in {None, OPENHANDS_FORMAT_RECOVERY_POLICY}:
        raise OpenHandsTrajectoryError("OpenHands format recovery policy is unknown")
    messages, decisions, recoveries, terminal_hook_allow_count = _normalize_events(
        event_snapshots,
        broker_turns=broker_turns,
        tool_contract=tool_contract,
        recovery_policy_id=recovery_policy_id,
    )
    recovery_enabled = recovery_policy_id is not None
    base = {
        "schema_version": "2.0" if recovery_enabled else "1.0",
        "format_id": (
            OPENHANDS_RECOVERY_TRAJECTORY_FORMAT
            if recovery_enabled
            else OPENHANDS_TRAJECTORY_FORMAT
        ),
        "campaign_role": "training",
        "task_id": task_id,
        "provider": provider,
        "model_id": model_id,
        "client_kind": "sdk",
        "client_name": "openhands-sdk",
        "client_version": OPENHANDS_SDK_VERSION,
        "harness_id": (
            "openhands-sdk-1.42.1-verigym-broker-v2"
            if recovery_enabled
            else "openhands-sdk-1.42.1-verigym-broker-v1"
        ),
        "configuration_fingerprint": configuration_fingerprint,
        "tool_contract": tool_contract,
        "tool_names": tool_names,
        "tools": exact_tools,
        "tool_schema_hash": content_hash(exact_tools),
        "messages": messages,
        "assistant_decisions": decisions,
        "assistant_decision_count": len(decisions),
        "broker_turn_count": len(broker_turns),
        "typed_finish_observed": True,
        "causal_validation": "passed",
        "exact_model_visible_context": True,
        "openhands_text_content_normalization": "ordered_text_block_concatenation",
        "model_visible_text_bytes_preserved": True,
        "openhands_tool_metadata_preserved": True,
        "broker_semantics_hash_bound": True,
        "verifier_resolved": False,
        "infrastructure_valid": True,
        "sft_eligible": False,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    if recovery_enabled:
        base.update(
            {
                "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
                "format_recovery_count": len(recoveries),
                "format_recoveries": recoveries,
                "same_session_recovery": True,
                "whole_episode_retries": 0,
                "termination_authority": "broker_typed_finish",
                "openhands_stop_hook_enabled": True,
                "terminal_hook_allow_count": terminal_hook_allow_count,
            }
        )
    result = {**base, "transcript_hash": content_hash(base)}
    validate_openhands_training_trajectory(result)
    return result


def set_openhands_verifier_result(
    trajectory: Mapping[str, Any], *, verifier_resolved: bool
) -> dict[str, Any]:
    """Seal the ordinary verifier result without rerunning or altering the episode."""

    validated = validate_openhands_training_trajectory(trajectory)
    validated.pop("transcript_hash")
    validated["verifier_resolved"] = verifier_resolved
    validated["sft_eligible"] = verifier_resolved
    result = {**validated, "transcript_hash": content_hash(validated)}
    validate_openhands_training_trajectory(result)
    return result


def validate_openhands_training_trajectory(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on schema, tool, causal, safety, or hash drift."""

    candidate = copy.deepcopy(dict(value))
    expected_hash = candidate.pop("transcript_hash", None)
    if not isinstance(expected_hash, str) or content_hash(candidate) != expected_hash:
        raise OpenHandsTrajectoryError("OpenHands trajectory identity changed")
    format_id = value.get("format_id")
    if format_id == OPENHANDS_TRAJECTORY_FORMAT:
        versioned_required: dict[str, Any] = {
            "schema_version": "1.0",
            "harness_id": "openhands-sdk-1.42.1-verigym-broker-v1",
        }
        recoveries: list[Any] = []
    elif format_id == OPENHANDS_RECOVERY_TRAJECTORY_FORMAT:
        versioned_required = {
            "schema_version": "2.0",
            "harness_id": "openhands-sdk-1.42.1-verigym-broker-v2",
            "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
            "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
            "same_session_recovery": True,
            "whole_episode_retries": 0,
            "termination_authority": "broker_typed_finish",
            "openhands_stop_hook_enabled": True,
        }
        raw_recoveries = value.get("format_recoveries")
        if not isinstance(raw_recoveries, list):
            raise OpenHandsTrajectoryError("OpenHands format recovery receipts are malformed")
        recoveries = raw_recoveries
        terminal_hook_allow_count = value.get("terminal_hook_allow_count")
        if (
            value.get("format_recovery_count") != len(recoveries)
            or len(recoveries) > OPENHANDS_FORMAT_RECOVERY_BUDGET
            or not isinstance(terminal_hook_allow_count, int)
            or isinstance(terminal_hook_allow_count, bool)
            or not 0 <= terminal_hook_allow_count <= 1
        ):
            raise OpenHandsTrajectoryError("OpenHands format recovery accounting changed")
    else:
        raise OpenHandsTrajectoryError("OpenHands trajectory format changed")
    required = {
        **versioned_required,
        "campaign_role": "training",
        "client_kind": "sdk",
        "client_name": "openhands-sdk",
        "client_version": OPENHANDS_SDK_VERSION,
        "typed_finish_observed": True,
        "causal_validation": "passed",
        "exact_model_visible_context": True,
        "openhands_text_content_normalization": "ordered_text_block_concatenation",
        "model_visible_text_bytes_preserved": True,
        "openhands_tool_metadata_preserved": True,
        "broker_semantics_hash_bound": True,
        "infrastructure_valid": True,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    if any(value.get(key) != expected for key, expected in required.items()):
        raise OpenHandsTrajectoryError("OpenHands trajectory contract changed")
    if value.get("sft_eligible") is not (value.get("verifier_resolved") is True):
        raise OpenHandsTrajectoryError("OpenHands verifier and SFT gates differ")
    tool_contract = value.get("tool_contract")
    if tool_contract not in _CONTRACT_TOOLS:
        raise OpenHandsTrajectoryError("OpenHands trajectory tool contract is unknown")
    assert isinstance(tool_contract, str)
    tools = value.get("tools")
    if not isinstance(tools, list):
        raise OpenHandsTrajectoryError("OpenHands trajectory omits exact tools")
    tool_names = _validate_tools(tools, tool_contract=tool_contract)
    if value.get("tool_names") != tool_names or value.get("tool_schema_hash") != content_hash(
        tools
    ):
        raise OpenHandsTrajectoryError("OpenHands exact tool identity changed")
    messages = value.get("messages")
    decisions = value.get("assistant_decisions")
    if not isinstance(messages, list) or not isinstance(decisions, list):
        raise OpenHandsTrajectoryError("OpenHands trajectory messages are malformed")
    _validate_normalized_messages(
        messages,
        decisions,
        tool_contract=tool_contract,
        recovery_receipts=recoveries,
    )
    broker_turn_count = sum(
        int(item.get("tool_action_count", -1)) if isinstance(item, dict) else -1
        for item in decisions
    )
    if (
        value.get("assistant_decision_count") != len(decisions)
        or value.get("broker_turn_count") != broker_turn_count
    ):
        raise OpenHandsTrajectoryError("OpenHands trajectory decision counts changed")
    _require_hash(str(value.get("configuration_fingerprint", "")), "configuration fingerprint")
    return copy.deepcopy(dict(value))


def materialize_openhands_decisions(
    trajectory: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    tokenizer: QwenDecisionExampleTokenizer,
    max_length: int = OPENHANDS_MAX_LENGTH,
) -> list[dict[str, Any]]:
    """Create exact final-decision-only rows; overlength context is never truncated."""

    validated = validate_openhands_training_trajectory(trajectory)
    if validated["verifier_resolved"] is not True or validated["sft_eligible"] is not True:
        raise OpenHandsTrajectoryError("only verifier-passed OpenHands trajectories may enter SFT")
    if max_length != OPENHANDS_MAX_LENGTH:
        raise OpenHandsTrajectoryError("OpenHands decision SFT freezes max_length=65536")
    required_binding = ("sample_id", "task_hash", "source_hash", "candidate_hash", "verifier_hash")
    if any(key not in binding for key in required_binding):
        raise OpenHandsTrajectoryError("OpenHands SFT binding is incomplete")
    for key in required_binding:
        _require_hash(str(binding[key]), f"binding {key}")
    tools = validated["tools"]
    messages = validated["messages"]
    decisions = validated["assistant_decisions"]
    recovery_enabled = validated["format_id"] == OPENHANDS_RECOVERY_TRAJECTORY_FORMAT
    records: list[dict[str, Any]] = []
    for decision_index, decision in enumerate(decisions):
        message_index = decision["message_index"]
        target = copy.deepcopy(messages[message_index])
        input_messages = copy.deepcopy(messages[:message_index])
        receipt = exact_decision_token_receipt(
            tokenizer=tokenizer,
            tools=tools,
            input_messages=input_messages,
            target_message=target,
        )
        if receipt["token_count"] > max_length:
            raise OpenHandsTrajectoryError(
                f"OpenHands decision {decision_index} exceeds 65536 tokens; truncation forbidden"
            )
        visible_recoveries = (
            [
                copy.deepcopy(item)
                for item in validated.get("format_recoveries", [])
                if int(item["feedback_message_index"]) < message_index
            ]
            if recovery_enabled
            else []
        )
        base = {
            "schema_version": "2.0" if recovery_enabled else "1.0",
            "format_id": (
                OPENHANDS_RECOVERY_DECISION_FORMAT
                if recovery_enabled
                else OPENHANDS_DECISION_FORMAT
            ),
            "sample_id": binding["sample_id"],
            "task_id": validated["task_id"],
            "task_hash": binding["task_hash"],
            "source_hash": binding["source_hash"],
            "candidate_hash": binding["candidate_hash"],
            "verifier_hash": binding["verifier_hash"],
            "transcript_hash": validated["transcript_hash"],
            "decision_index": decision_index,
            "target_message_index": message_index,
            "call_ids": copy.deepcopy(decision["call_ids"]),
            "action_names": copy.deepcopy(decision["action_names"]),
            "tool_action_count": decision["tool_action_count"],
            "trajectory_assistant_decision_count": len(decisions),
            "tools": copy.deepcopy(tools),
            "tool_schema_hash": validated["tool_schema_hash"],
            "input_messages": input_messages,
            "target_message": target,
            **receipt,
            "max_length": max_length,
            "truncation": "error",
            "eligible": True,
            "supervised_target_kind": "complete_assistant_decision",
            "supervised_roles": ["assistant"],
            "input_loss_masked": True,
            "exact_model_visible_context": True,
            "context_transformed_after_collection": False,
            "nap_required": False,
            "verifier_resolved": True,
            "infrastructure_valid": True,
            "raw_provider_events_exported": False,
            "raw_observations_exported": False,
            "private_reasoning_exported": False,
            "hidden_assets_exported": False,
            "reference_solutions_exported": False,
            "credential_values_exported": False,
            "raw_host_paths_exported": False,
        }
        if recovery_enabled:
            base.update(
                {
                    "source_trajectory_format": OPENHANDS_RECOVERY_TRAJECTORY_FORMAT,
                    "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                    "trajectory_format_recovery_count": validated["format_recovery_count"],
                    "format_recovery_count": len(visible_recoveries),
                    "format_recoveries": visible_recoveries,
                    "same_session_recovery": True,
                    "whole_episode_retries": 0,
                    "termination_authority": "broker_typed_finish",
                }
            )
        record = {**base, "record_hash": content_hash(base)}
        validate_openhands_decision_record(record, tokenizer=tokenizer)
        records.append(record)
    return records


def validate_openhands_decision_record(
    value: Mapping[str, Any], *, tokenizer: QwenDecisionExampleTokenizer
) -> dict[str, Any]:
    """Re-tokenize one row and reject tool, message, token, mask, or template drift."""

    candidate = copy.deepcopy(dict(value))
    expected_hash = candidate.pop("record_hash", None)
    if not isinstance(expected_hash, str) or content_hash(candidate) != expected_hash:
        raise OpenHandsTrajectoryError("OpenHands decision record identity changed")
    format_id = value.get("format_id")
    if format_id not in {OPENHANDS_DECISION_FORMAT, OPENHANDS_RECOVERY_DECISION_FORMAT}:
        raise OpenHandsTrajectoryError("OpenHands decision format changed")
    tools = value.get("tools")
    inputs = value.get("input_messages")
    target = value.get("target_message")
    if not isinstance(tools, list) or not isinstance(inputs, list) or not isinstance(target, dict):
        raise OpenHandsTrajectoryError("OpenHands decision messages are malformed")
    receipt = exact_decision_token_receipt(
        tokenizer=tokenizer,
        tools=tools,
        input_messages=inputs,
        target_message=target,
    )
    if any(value.get(key) != expected for key, expected in receipt.items()):
        raise OpenHandsTrajectoryError("OpenHands decision exact-token receipt changed")
    required = {
        "tool_schema_hash": content_hash(tools),
        "target_message_index": len(inputs),
        "max_length": OPENHANDS_MAX_LENGTH,
        "truncation": "error",
        "eligible": True,
        "supervised_target_kind": "complete_assistant_decision",
        "supervised_roles": ["assistant"],
        "input_loss_masked": True,
        "exact_model_visible_context": True,
        "context_transformed_after_collection": False,
        "nap_required": False,
        "verifier_resolved": True,
        "infrastructure_valid": True,
    }
    if any(value.get(key) != expected for key, expected in required.items()):
        raise OpenHandsTrajectoryError("OpenHands decision eligibility receipt changed")
    if format_id == OPENHANDS_RECOVERY_DECISION_FORMAT:
        recoveries = value.get("format_recoveries")
        trajectory_recovery_count = value.get("trajectory_format_recovery_count")
        recovery_required = {
            "source_trajectory_format": OPENHANDS_RECOVERY_TRAJECTORY_FORMAT,
            "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
            "same_session_recovery": True,
            "whole_episode_retries": 0,
            "termination_authority": "broker_typed_finish",
        }
        if (
            any(value.get(key) != expected for key, expected in recovery_required.items())
            or not isinstance(recoveries, list)
            or value.get("format_recovery_count") != len(recoveries)
            or len(recoveries) > OPENHANDS_FORMAT_RECOVERY_BUDGET
            or not isinstance(trajectory_recovery_count, int)
            or isinstance(trajectory_recovery_count, bool)
            or trajectory_recovery_count not in {0, 1}
            or len(recoveries) > trajectory_recovery_count
        ):
            raise OpenHandsTrajectoryError("OpenHands decision recovery receipt changed")
        _validate_recovery_receipts(inputs, recoveries)
    if target.get("role") != "assistant" or not target.get("tool_calls"):
        raise OpenHandsTrajectoryError("OpenHands decision target is not a complete tool decision")
    target_calls = target["tool_calls"]
    if (
        not isinstance(target_calls, list)
        or value.get("tool_action_count") != len(target_calls)
        or value.get("call_ids") != [item.get("id") for item in target_calls]
        or value.get("action_names")
        != [item.get("function", {}).get("name") for item in target_calls]
    ):
        raise OpenHandsTrajectoryError("OpenHands decision sibling tool identity changed")
    return copy.deepcopy(dict(value))


def write_openhands_decision_dataset(
    records: Sequence[Mapping[str, Any]],
    *,
    tokenizer: QwenDecisionExampleTokenizer,
    output: Path,
) -> dict[str, Any]:
    """Atomically write a new hash-bound dataset directory without overwriting data."""

    if not records:
        raise OpenHandsTrajectoryError("OpenHands decision dataset cannot be empty")
    rows = [validate_openhands_decision_record(item, tokenizer=tokenizer) for item in records]
    hashes = [str(item.get("record_hash", "")) for item in rows]
    if any(not _HASH.fullmatch(item) for item in hashes) or len(set(hashes)) != len(hashes):
        raise OpenHandsTrajectoryError("OpenHands decision record hashes are invalid or duplicate")
    destination = _new_directory(output)
    atomic_dump_jsonl(destination / "train.jsonl", rows)
    records_sha256 = hash_bytes((destination / "train.jsonl").read_bytes())
    task_ids = sorted({str(item["task_id"]) for item in rows})
    transcript_hashes = sorted({str(item["transcript_hash"]) for item in rows})
    max_tokens = max(int(item["token_count"]) for item in rows)
    record_formats = {str(item["format_id"]) for item in rows}
    if not record_formats <= {OPENHANDS_DECISION_FORMAT, OPENHANDS_RECOVERY_DECISION_FORMAT}:
        raise OpenHandsTrajectoryError("OpenHands decision dataset contains an unknown row format")
    recovery_dataset = OPENHANDS_RECOVERY_DECISION_FORMAT in record_formats
    base = {
        "schema_version": "2.0" if recovery_dataset else "1.0",
        "format_id": (
            OPENHANDS_RECOVERY_DATASET_FORMAT if recovery_dataset else OPENHANDS_DATASET_FORMAT
        ),
        "record_count": len(rows),
        "record_hashes": hashes,
        "records_sha256": records_sha256,
        "task_ids": task_ids,
        "trajectory_count": len(transcript_hashes),
        "trajectory_hashes": transcript_hashes,
        "supervised_decision_count": len(rows),
        "max_observed_token_count": max_tokens,
        "max_length": OPENHANDS_MAX_LENGTH,
        "truncation": "error",
        "overlength_records": [],
        "exact_token_receipts": True,
        "only_verifier_resolved": True,
        "infrastructure_invalid_excluded": True,
        "loader_ready": True,
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "adapter_written": False,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    if recovery_dataset:
        recovery_by_trajectory: dict[str, int] = {}
        for row in rows:
            if row["format_id"] != OPENHANDS_RECOVERY_DECISION_FORMAT:
                continue
            transcript_hash = str(row["transcript_hash"])
            count = row.get("trajectory_format_recovery_count")
            if not isinstance(count, int) or isinstance(count, bool) or count not in {0, 1}:
                raise OpenHandsTrajectoryError(
                    "OpenHands decision dataset recovery count is malformed"
                )
            previous = recovery_by_trajectory.setdefault(transcript_hash, count)
            if previous != count:
                raise OpenHandsTrajectoryError(
                    "OpenHands decision dataset recovery count changed within a trajectory"
                )
        base.update(
            {
                "record_formats": sorted(record_formats),
                "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                "format_recovery_trajectory_count": sum(
                    count > 0 for count in recovery_by_trajectory.values()
                ),
                "format_recovery_count": sum(recovery_by_trajectory.values()),
                "same_session_recovery_hash_bound": True,
                "whole_episode_retries": 0,
                "termination_authority": "broker_typed_finish",
            }
        )
    manifest = {**base, "dataset_hash": content_hash(base)}
    atomic_dump_json(destination / "dataset-manifest.json", manifest)
    artifacts = {
        name: hash_bytes((destination / name).read_bytes())
        for name in ("dataset-manifest.json", "train.jsonl")
    }
    atomic_write_text(
        destination / "SHA256SUMS",
        "".join(f"{digest}  {name}\n" for name, digest in sorted(artifacts.items())),
    )
    return manifest


def _normalize_events(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    broker_turns: Sequence[BrokerTurnReceipt],
    tool_contract: str,
    recovery_policy_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    if not snapshots or not broker_turns:
        raise OpenHandsTrajectoryError("OpenHands training trajectory is empty")
    messages: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    receipt_index = 0
    pending: list[dict[str, Any]] = []
    pending_response_id: str | None = None
    saw_system = False
    saw_user = False
    saw_finish = False
    terminal_text_seen = False
    recovery_assistant_index: int | None = None
    pending_recovery_hook_index: int | None = None
    recoveries: list[dict[str, Any]] = []
    terminal_hook_allow_count = 0
    seen_calls: set[str] = set()
    for event_index, raw in enumerate(snapshots):
        event = dict(raw)
        event_type = event.get("event_type")
        if event_type == "SystemPromptEvent":
            if saw_system or messages or event.get("dynamic_context_present") is not False:
                raise OpenHandsTrajectoryError("OpenHands system prompt event is not isolated")
            message = _normalized_message(event.get("message"), expected_role="system")
            messages.append(message)
            saw_system = True
        elif event_type == "MessageEvent":
            if (
                event.get("activated_skills") != []
                or event.get("extended_content_present") is not False
                or event.get("critic_present") is not False
            ):
                raise OpenHandsTrajectoryError("OpenHands injected skills, context, or a critic")
            source = event.get("source")
            if source == "user":
                if not saw_system or saw_user or pending or decisions:
                    raise OpenHandsTrajectoryError("OpenHands user message is out of sequence")
                message = _normalized_message(event.get("message"), expected_role="user")
                saw_user = True
            elif source == "agent":
                message = _normalized_message(event.get("message"), expected_role="assistant")
                if message.get("tool_calls") or not message.get("content"):
                    raise OpenHandsTrajectoryError(
                        "OpenHands final assistant message is not plain public text"
                    )
                if saw_finish and not pending and not terminal_text_seen:
                    terminal_text_seen = True
                elif (
                    recovery_policy_id == OPENHANDS_FORMAT_RECOVERY_POLICY
                    and saw_user
                    and not pending
                    and not saw_finish
                    and recovery_assistant_index is None
                    and pending_recovery_hook_index is None
                    and len(recoveries) < OPENHANDS_FORMAT_RECOVERY_BUDGET
                ):
                    recovery_assistant_index = len(messages)
                else:
                    raise OpenHandsTrajectoryError(
                        "OpenHands assistant text is outside a recovery or terminal boundary"
                    )
            elif source == "environment":
                if (
                    recovery_policy_id != OPENHANDS_FORMAT_RECOVERY_POLICY
                    or recovery_assistant_index is None
                    or pending_recovery_hook_index is None
                    or pending
                    or saw_finish
                ):
                    raise OpenHandsTrajectoryError("OpenHands recovery feedback is out of sequence")
                message = _normalized_message(event.get("message"), expected_role="user")
                if message.get("content") != OPENHANDS_FORMAT_RECOVERY_MESSAGE:
                    raise OpenHandsTrajectoryError("OpenHands recovery feedback text changed")
                feedback_message_index = len(messages)
                assistant_message = messages[recovery_assistant_index]
                recoveries.append(
                    {
                        "recovery_index": len(recoveries),
                        "reason": "assistant_content_without_typed_tool",
                        "assistant_message_index": recovery_assistant_index,
                        "assistant_message_sha256": content_hash(assistant_message),
                        "hook_event_index": pending_recovery_hook_index,
                        "feedback_message_index": feedback_message_index,
                        "feedback_message_sha256": content_hash(message),
                        "feedback_text_sha256": OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
                        "same_session": True,
                        "whole_episode_retries": 0,
                        "broker_typed_finish_before": False,
                    }
                )
                recovery_assistant_index = None
                pending_recovery_hook_index = None
            else:
                raise OpenHandsTrajectoryError("OpenHands message source is unsupported")
            messages.append(message)
        elif event_type == "ActionEvent":
            response_id = event.get("llm_response_id")
            if not isinstance(response_id, str) or not response_id or len(response_id) > 1024:
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands action omits its bounded LLM response identity"
                )
            if (
                not saw_user
                or saw_finish
                or terminal_text_seen
                or recovery_assistant_index is not None
                or pending_recovery_hook_index is not None
                or (pending_response_id is not None and response_id != pending_response_id)
                or any(item["tool_name"] == "finish" for item in pending)
            ):
                state = (
                    f"saw_user={str(saw_user).lower()},"
                    f"pending={str(bool(pending)).lower()},"
                    f"saw_finish={str(saw_finish).lower()},"
                    f"terminal_text_seen={str(terminal_text_seen).lower()}"
                )
                raise OpenHandsTrajectoryError(
                    f"OpenHands action event {event_index} is out of sequence ({state})"
                )
            if any(
                event.get(field) is not False
                for field in (
                    "reasoning_content_present",
                    "thinking_blocks_present",
                    "responses_reasoning_present",
                    "critic_present",
                )
            ):
                raise OpenHandsTrajectoryError(
                    "OpenHands action contains private reasoning or critic content"
                )
            broker_index = receipt_index + len(pending)
            if broker_index >= len(broker_turns):
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands action has no broker-owned turn"
                )
            message = _normalized_message(event.get("message"), expected_role="assistant")
            calls = message.get("tool_calls")
            if not isinstance(calls, list) or len(calls) != 1:
                raise OpenHandsTrajectoryError(
                    "OpenHands action must contain exactly one tool call"
                )
            call = calls[0]
            call_id = call["id"]
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            if (
                event.get("tool_name") != name
                or event.get("tool_call_id") != call_id
                or call_id in seen_calls
            ):
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands action identity differs from its LLM message"
                )
            seen_calls.add(call_id)
            receipt = broker_turns[broker_index]
            if receipt.call_id is not None and receipt.call_id != call_id:
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands call ID differs from the broker turn"
                )
            canonical = _canonical_arguments(name, arguments, tool_contract=tool_contract)
            if receipt.tool_name != name or receipt.arguments_json != canonical:
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands tool arguments differ from broker semantics"
                )
            if name == "finish" and (pending or broker_index != len(broker_turns) - 1):
                raise OpenHandsTrajectoryError(
                    "OpenHands finish must be the only action in the terminal decision"
                )
            decision: dict[str, Any]
            if not pending:
                message_index = len(messages)
                messages.append(message)
                decision = {
                    "decision_index": len(decisions),
                    "message_index": message_index,
                    "call_ids": [],
                    "action_names": [],
                    "tool_action_count": 0,
                    "sibling_tool_calls": False,
                    "actions": [],
                }
                decisions.append(decision)
                pending_response_id = response_id
            else:
                decision = decisions[-1]
                message_index = int(decision["message_index"])
                # OpenHands 1.42.1 attaches the shared assistant text only to
                # the first ActionEvent in one parallel tool-call response.
                if message.get("content") is not None:
                    raise OpenHandsTrajectoryInfrastructureError(
                        "OpenHands sibling action repeats shared assistant content"
                    )
                messages[message_index]["tool_calls"].append(call)
            action_receipt = {
                "action_index": len(decision["actions"]),
                "call_id": call_id,
                "tool_name": name,
                "raw_arguments_sha256": hashlib.sha256(arguments.encode()).hexdigest(),
                "canonical_arguments_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                "observation_message_index": None,
                "observation_sha256": None,
                "broker_observation_sha256": receipt.observation_sha256,
            }
            decision["call_ids"].append(call_id)
            decision["action_names"].append(name)
            decision["actions"].append(action_receipt)
            decision["tool_action_count"] = len(decision["actions"])
            decision["sibling_tool_calls"] = len(decision["actions"]) > 1
            pending.append(
                {
                    "call_id": call_id,
                    "tool_name": name,
                    "observation_sha256": receipt.observation_sha256,
                    "message_index": message_index,
                    "action_receipt": action_receipt,
                }
            )
        elif event_type == "ObservationEvent":
            if not pending:
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands observation has no pending action"
                )
            expected = pending[0]
            call_id = expected["call_id"]
            name = expected["tool_name"]
            expected_observation_hash = expected["observation_sha256"]
            if event.get("extended_content_present") is not False:
                raise OpenHandsTrajectoryError("OpenHands observation injected dynamic context")
            if event.get("tool_name") != name or event.get("tool_call_id") != call_id:
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands observation identity differs from its action"
                )
            message = _normalized_message(event.get("message"), expected_role="tool")
            if message.get("name") != name or message.get("tool_call_id") != call_id:
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands tool LLM message differs from its action"
                )
            observation = message.get("content")
            broker_observation = _broker_observation_text(observation, tool_name=name)
            if hashlib.sha256(broker_observation.encode()).hexdigest() != (
                expected_observation_hash
            ):
                raise OpenHandsTrajectoryInfrastructureError(
                    "OpenHands observation differs from the broker-owned compact result"
                )
            messages.append(message)
            action_receipt = expected["action_receipt"]
            action_receipt["observation_message_index"] = len(messages) - 1
            action_receipt["observation_sha256"] = content_hash(observation)
            receipt_index += 1
            pending.pop(0)
            if not pending:
                pending_response_id = None
                saw_finish = name == "finish"
        elif event_type == "HookExecutionEvent":
            if recovery_policy_id != OPENHANDS_FORMAT_RECOVERY_POLICY:
                raise OpenHandsTrajectoryError("OpenHands trajectory contains an undeclared hook")
            common_valid = (
                event.get("source") == "hook"
                and event.get("hook_event_type") == "Stop"
                and event.get("stdout_present") is True
                and event.get("stderr_present") is False
                and event.get("additional_context_present") is False
                and event.get("error_present") is False
                and not pending
            )
            if event.get("blocked") is True:
                if (
                    not common_valid
                    or event.get("success") is not False
                    or event.get("exit_code") != 2
                    or event.get("reason_sha256") != OPENHANDS_FORMAT_RECOVERY_REASON_SHA256
                    or recovery_assistant_index is None
                    or pending_recovery_hook_index is not None
                    or saw_finish
                    or len(recoveries) >= OPENHANDS_FORMAT_RECOVERY_BUDGET
                ):
                    raise OpenHandsTrajectoryError("OpenHands recovery Stop hook changed")
                pending_recovery_hook_index = event_index
            elif event.get("blocked") is False:
                typed_finish_reason = hashlib.sha256(b"broker typed finish observed").hexdigest()
                if (
                    not common_valid
                    or event.get("success") is not True
                    or event.get("exit_code") != 0
                    or event.get("reason_sha256") != typed_finish_reason
                    or not saw_finish
                    or recovery_assistant_index is not None
                    or pending_recovery_hook_index is not None
                    or terminal_hook_allow_count != 0
                ):
                    raise OpenHandsTrajectoryError("OpenHands terminal Stop hook changed")
                terminal_hook_allow_count = 1
            else:
                raise OpenHandsTrajectoryError("OpenHands Stop hook result is malformed")
        else:
            raise OpenHandsTrajectoryError(
                f"OpenHands training stream contains unsupported {event_type!r}"
            )
    total_bytes = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode())
    if total_bytes > _MAX_TRAJECTORY_BYTES:
        raise OpenHandsTrajectoryError("OpenHands training trajectory exceeds its bound")
    if (
        pending
        or pending_response_id is not None
        or recovery_assistant_index is not None
        or pending_recovery_hook_index is not None
        or receipt_index != len(broker_turns)
    ):
        raise OpenHandsTrajectoryInfrastructureError("OpenHands and broker turn counts differ")
    if not saw_system or not saw_user or not saw_finish:
        raise OpenHandsTrajectoryError("OpenHands trajectory lacks system, user, or typed finish")
    return messages, decisions, recoveries, terminal_hook_allow_count


def _validate_normalized_messages(
    messages: list[Any],
    decisions: list[Any],
    *,
    tool_contract: str,
    recovery_receipts: list[Any],
) -> None:
    if len(messages) < 4 or [item.get("role") for item in messages[:2]] != ["system", "user"]:
        raise OpenHandsTrajectoryError("OpenHands normalized messages have no prompt prefix")
    decision_by_message: dict[int, dict[str, Any]] = {}
    validated_recoveries = _validate_recovery_receipts(messages, recovery_receipts)
    recovery_by_assistant = {item["assistant_message_index"]: item for item in validated_recoveries}
    recovery_by_feedback = {item["feedback_message_index"]: item for item in validated_recoveries}
    for raw in decisions:
        if not isinstance(raw, dict) or not isinstance(raw.get("message_index"), int):
            raise OpenHandsTrajectoryError("OpenHands decision receipt is malformed")
        message_index = raw["message_index"]
        if message_index in decision_by_message:
            raise OpenHandsTrajectoryError("OpenHands decision message identity is duplicated")
        decision_by_message[message_index] = raw
    pending: list[dict[str, Any]] = []
    saw_finish = False
    observed_decisions = 0
    observed_actions = 0
    seen_calls: set[str] = set()
    awaiting_recovery: dict[str, Any] | None = None
    for index, raw in enumerate(messages):
        message = _normalized_message(raw, expected_role=None)
        role = message["role"]
        if index < 2:
            continue
        if role == "assistant" and message.get("tool_calls"):
            if pending or saw_finish or awaiting_recovery is not None:
                raise OpenHandsTrajectoryError("OpenHands decision order changed")
            receipt = decision_by_message.get(index)
            if receipt is None or receipt.get("decision_index") != observed_decisions:
                raise OpenHandsTrajectoryError("OpenHands decision receipt changed")
            calls = message["tool_calls"]
            actions = receipt.get("actions")
            call_ids = [call["id"] for call in calls]
            action_names = [call["function"]["name"] for call in calls]
            if (
                not isinstance(actions, list)
                or len(actions) != len(calls)
                or receipt.get("call_ids") != call_ids
                or receipt.get("action_names") != action_names
                or receipt.get("tool_action_count") != len(calls)
                or receipt.get("sibling_tool_calls") is not (len(calls) > 1)
                or any(call_id in seen_calls for call_id in call_ids)
                or ("finish" in action_names and len(calls) != 1)
            ):
                raise OpenHandsTrajectoryError("OpenHands sibling decision receipt changed")
            seen_calls.update(call_ids)
            for action_index, (call, action) in enumerate(zip(calls, actions, strict=True)):
                if not isinstance(action, dict):
                    raise OpenHandsTrajectoryError("OpenHands action receipt is malformed")
                call_id = call["id"]
                name = call["function"]["name"]
                arguments = call["function"]["arguments"]
                canonical = _canonical_arguments(name, arguments, tool_contract=tool_contract)
                if (
                    action.get("action_index") != action_index
                    or action.get("call_id") != call_id
                    or action.get("tool_name") != name
                    or action.get("raw_arguments_sha256")
                    != hashlib.sha256(arguments.encode()).hexdigest()
                    or action.get("canonical_arguments_sha256")
                    != hashlib.sha256(canonical.encode()).hexdigest()
                    or not isinstance(action.get("observation_message_index"), int)
                    or not isinstance(action.get("observation_sha256"), str)
                ):
                    raise OpenHandsTrajectoryError("OpenHands action receipt changed")
                pending.append(action)
                observed_actions += 1
            observed_decisions += 1
        elif role == "tool":
            if not pending or awaiting_recovery is not None:
                raise OpenHandsTrajectoryError("OpenHands tool message has no decision")
            action = pending.pop(0)
            call_id = action["call_id"]
            name = action["tool_name"]
            broker_observation_hash = str(action.get("broker_observation_sha256"))
            content = message.get("content")
            broker_observation = _broker_observation_text(content, tool_name=name)
            if (
                message.get("tool_call_id") != call_id
                or message.get("name") != name
                or hashlib.sha256(broker_observation.encode()).hexdigest()
                != broker_observation_hash
                or action.get("observation_message_index") != index
                or action.get("observation_sha256") != content_hash(content)
            ):
                raise OpenHandsTrajectoryError("OpenHands observation receipt changed")
            if not pending:
                saw_finish = name == "finish"
        elif role == "assistant" and message.get("content") and index in recovery_by_assistant:
            if pending or saw_finish or awaiting_recovery is not None:
                raise OpenHandsTrajectoryError("OpenHands recovery assistant order changed")
            awaiting_recovery = recovery_by_assistant[index]
        elif role == "user" and index in recovery_by_feedback:
            if (
                pending
                or saw_finish
                or awaiting_recovery is None
                or awaiting_recovery != recovery_by_feedback[index]
            ):
                raise OpenHandsTrajectoryError("OpenHands recovery feedback order changed")
            awaiting_recovery = None
        elif (
            role == "assistant"
            and message.get("content")
            and saw_finish
            and index == len(messages) - 1
        ):
            continue
        else:
            raise OpenHandsTrajectoryError("OpenHands normalized message sequence changed")
    expected_actions = sum(
        int(item.get("tool_action_count", -1)) if isinstance(item, dict) else -1
        for item in decisions
    )
    if (
        pending
        or awaiting_recovery is not None
        or not saw_finish
        or observed_decisions != len(decisions)
        or observed_actions != expected_actions
    ):
        raise OpenHandsTrajectoryError("OpenHands normalized trajectory is incomplete")


def _validate_recovery_receipts(
    messages: Sequence[Any], receipts: Sequence[Any]
) -> list[dict[str, Any]]:
    if len(receipts) > OPENHANDS_FORMAT_RECOVERY_BUDGET:
        raise OpenHandsTrajectoryError("OpenHands format recovery budget changed")
    result: list[dict[str, Any]] = []
    expected_fields = {
        "recovery_index",
        "reason",
        "assistant_message_index",
        "assistant_message_sha256",
        "hook_event_index",
        "feedback_message_index",
        "feedback_message_sha256",
        "feedback_text_sha256",
        "same_session",
        "whole_episode_retries",
        "broker_typed_finish_before",
    }
    for recovery_index, raw in enumerate(receipts):
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise OpenHandsTrajectoryError("OpenHands format recovery receipt is malformed")
        assistant_index = raw.get("assistant_message_index")
        feedback_index = raw.get("feedback_message_index")
        hook_index = raw.get("hook_event_index")
        if (
            raw.get("recovery_index") != recovery_index
            or raw.get("reason") != "assistant_content_without_typed_tool"
            or not isinstance(assistant_index, int)
            or isinstance(assistant_index, bool)
            or not isinstance(feedback_index, int)
            or isinstance(feedback_index, bool)
            or not isinstance(hook_index, int)
            or isinstance(hook_index, bool)
            or not 2 <= assistant_index < feedback_index < len(messages)
            or hook_index < 0
            or raw.get("same_session") is not True
            or raw.get("whole_episode_retries") != 0
            or raw.get("broker_typed_finish_before") is not False
            or raw.get("feedback_text_sha256") != OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256
        ):
            raise OpenHandsTrajectoryError("OpenHands format recovery receipt changed")
        assistant = _normalized_message(messages[assistant_index], expected_role="assistant")
        feedback = _normalized_message(messages[feedback_index], expected_role="user")
        if (
            assistant.get("tool_calls")
            or not assistant.get("content")
            or feedback.get("content") != OPENHANDS_FORMAT_RECOVERY_MESSAGE
            or raw.get("assistant_message_sha256") != content_hash(assistant)
            or raw.get("feedback_message_sha256") != content_hash(feedback)
        ):
            raise OpenHandsTrajectoryError("OpenHands recovery message binding changed")
        result.append(copy.deepcopy(raw))
    return result


def _normalized_message(value: Any, *, expected_role: str | None) -> dict[str, Any]:
    raw = _plain(value)
    if not isinstance(raw, dict):
        raise OpenHandsTrajectoryError("OpenHands LLM message is not an object")
    role = raw.get("role")
    if role not in {"system", "user", "assistant", "tool"} or (
        expected_role is not None and role != expected_role
    ):
        raise OpenHandsTrajectoryError("OpenHands LLM message role changed")
    for field in ("reasoning_content", "responses_reasoning_item"):
        field_value = raw.get(field)
        if field_value is not None and field_value != "":
            raise OpenHandsTrajectoryError("OpenHands LLM message contains private reasoning")
    thinking_blocks = raw.get("thinking_blocks")
    if thinking_blocks is not None and thinking_blocks != () and thinking_blocks != []:
        raise OpenHandsTrajectoryError("OpenHands LLM message contains thinking blocks")
    content = _message_content(raw.get("content"))
    if role != "tool" and isinstance(content, list):
        content = "".join(block["text"] for block in content) or None
    result: dict[str, Any] = {"role": role, "content": content}
    calls = raw.get("tool_calls")
    if calls:
        if role != "assistant" or not isinstance(calls, list) or not 1 <= len(calls) <= 64:
            raise OpenHandsTrajectoryError("OpenHands tool call message is malformed")
        normalized_calls = [_normalized_tool_call(call) for call in calls]
        call_ids = [call["id"] for call in normalized_calls]
        if len(call_ids) != len(set(call_ids)):
            raise OpenHandsTrajectoryError("OpenHands sibling tool call IDs are duplicated")
        result["tool_calls"] = normalized_calls
    tool_call_id = raw.get("tool_call_id")
    name = raw.get("name")
    if role == "tool":
        if not isinstance(tool_call_id, str) or not tool_call_id or not isinstance(name, str):
            raise OpenHandsTrajectoryError("OpenHands tool observation identity is malformed")
        result["tool_call_id"] = tool_call_id
        result["name"] = name
    elif tool_call_id is not None or name is not None:
        raise OpenHandsTrajectoryError("OpenHands non-tool message has tool observation fields")
    if role in {"system", "user"} and (not content or calls):
        raise OpenHandsTrajectoryError("OpenHands prompt message is empty or contains a tool call")
    if role == "assistant" and not content and not calls:
        raise OpenHandsTrajectoryError("OpenHands assistant message is empty")
    if role == "tool" and not content:
        raise OpenHandsTrajectoryError("OpenHands tool observation is empty")
    return result


def _normalized_tool_call(value: Any) -> dict[str, Any]:
    raw = _plain(value)
    if not isinstance(raw, dict):
        raise OpenHandsTrajectoryError("OpenHands tool call is not an object")
    call_id = raw.get("id")
    if not isinstance(call_id, str) or not call_id or len(call_id.encode()) > 512:
        raise OpenHandsTrajectoryError("OpenHands tool call ID is malformed")
    if "function" in raw:
        function = raw.get("function")
        if not isinstance(function, dict):
            raise OpenHandsTrajectoryError("OpenHands tool function is malformed")
        name = function.get("name")
        arguments = function.get("arguments")
    else:
        name = raw.get("name")
        arguments = raw.get("arguments")
    if not isinstance(name, str) or not isinstance(arguments, str):
        raise OpenHandsTrajectoryError("OpenHands tool name or arguments are malformed")
    _strict_json_object(arguments)
    _validate_public_text(arguments, allow_host_paths=False)
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _canonical_arguments(name: str, arguments: str, *, tool_contract: str) -> str:
    raw = _strict_json_object(arguments)
    sanitized = dict(raw)
    sanitized.pop("security_risk", None)
    if not (tool_contract == "hwe_native_shell_v2" and name == "finish"):
        sanitized.pop("summary", None)
    try:
        if tool_contract == "hwe_native_shell_v2":
            envelope = json.loads(
                canonical_hwe_action_json(
                    name,
                    sanitized,
                    profile_id=HWE_COLLECTION_PROFILE_V2_ID,
                )
            )
        else:
            envelope = json.loads(canonical_action_json(name, sanitized))
    except (TypeError, ValueError) as exc:
        raise OpenHandsTrajectoryError(
            "OpenHands action is outside the canonical broker contract"
        ) from exc
    return json.dumps(
        envelope["arguments"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _validate_tools(tools: Sequence[Any], *, tool_contract: str) -> list[str]:
    expected = _CONTRACT_TOOLS.get(tool_contract)
    if expected is None or len(tools) != len(expected):
        raise OpenHandsTrajectoryError("OpenHands must preserve exactly six tool schemas")
    names: list[str] = []
    for raw in tools:
        if not isinstance(raw, Mapping) or raw.get("type") != "function":
            raise OpenHandsTrajectoryError("OpenHands effective tool is not an OpenAI function")
        function = raw.get("function")
        if not isinstance(function, Mapping):
            raise OpenHandsTrajectoryError("OpenHands effective function schema is malformed")
        name = function.get("name")
        parameters = function.get("parameters")
        if not isinstance(name, str) or not isinstance(parameters, Mapping):
            raise OpenHandsTrajectoryError("OpenHands effective tool identity is malformed")
        names.append(name)
    if frozenset(names) != expected or len(set(names)) != len(names):
        raise OpenHandsTrajectoryError("OpenHands exposed tools outside the selected contract")
    return names


def _message_content(value: Any) -> str | list[dict[str, str]] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        _validate_public_text(value)
        return value or None
    if not isinstance(value, list):
        raise OpenHandsTrajectoryError("OpenHands message content is not text")
    blocks: list[dict[str, str]] = []
    for block in value:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            raise OpenHandsTrajectoryError("OpenHands message contains a non-text block")
        text = block.get("text")
        if not isinstance(text, str):
            raise OpenHandsTrajectoryError("OpenHands text block is malformed")
        _validate_public_text(text)
        blocks.append({"type": "text", "text": text})
    return blocks or None


def _broker_observation_text(value: Any, *, tool_name: str) -> str:
    prefix = f"[Tool '{tool_name}' executed.]"
    if (
        not isinstance(value, list)
        or len(value) != 2
        or value[0] != {"type": "text", "text": prefix}
        or not isinstance(value[1], dict)
        or value[1].get("type") != "text"
        or not isinstance(value[1].get("text"), str)
    ):
        raise OpenHandsTrajectoryInfrastructureError("OpenHands tool observation wrapper changed")
    return str(value[1]["text"])


def _validate_public_text(value: str, *, allow_host_paths: bool = True) -> None:
    encoded = value.encode("utf-8")
    if len(encoded) > _MAX_MESSAGE_BYTES or _CONTROL.search(value) or _SENSITIVE.search(value):
        raise OpenHandsTrajectoryError("OpenHands public message failed the content boundary")
    if not allow_host_paths and _HOST_PATH.search(value):
        raise OpenHandsTrajectoryError("OpenHands tool arguments contain a raw host path")


def _strict_json_object(value: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OpenHandsTrajectoryError("OpenHands tool arguments are not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise OpenHandsTrajectoryError("OpenHands tool arguments must decode to an object")
    return decoded


def _dump_llm_message(event: object) -> dict[str, Any]:
    converter = getattr(event, "to_llm_message", None)
    if not callable(converter):
        raise OpenHandsTrajectoryInfrastructureError(
            "OpenHands event cannot expose its exact LLM message"
        )
    value = _plain(converter())
    if not isinstance(value, dict):
        raise OpenHandsTrajectoryInfrastructureError("OpenHands LLM message is not serializable")
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _plain(dump(mode="json"))
    return value


def _require_hash(value: str, label: str) -> str:
    if not _HASH.fullmatch(value):
        raise OpenHandsTrajectoryError(f"OpenHands {label} must be lowercase SHA-256")
    return value


def _new_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise OpenHandsTrajectoryError("OpenHands dataset output already exists")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise OpenHandsTrajectoryError("OpenHands dataset parent is not a directory")
    path.mkdir(mode=0o750)
    metadata = os.lstat(path)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise OpenHandsTrajectoryError("OpenHands dataset output is not a real directory")
    return path.resolve(strict=True)


__all__ = [
    "BrokerTurnReceipt",
    "OPENHANDS_DATASET_FORMAT",
    "OPENHANDS_DECISION_FORMAT",
    "OPENHANDS_MAX_LENGTH",
    "OPENHANDS_RECOVERY_DATASET_FORMAT",
    "OPENHANDS_RECOVERY_DECISION_FORMAT",
    "OPENHANDS_RECOVERY_TRAJECTORY_FORMAT",
    "OPENHANDS_TRAJECTORY_FORMAT",
    "OpenHandsTrajectoryError",
    "OpenHandsTrajectoryInfrastructureError",
    "build_openhands_training_trajectory",
    "hwe_broker_receipts",
    "materialize_openhands_decisions",
    "repository_broker_receipts",
    "set_openhands_verifier_result",
    "snapshot_openhands_events",
    "snapshot_openhands_tools",
    "validate_openhands_decision_record",
    "validate_openhands_training_trajectory",
    "write_openhands_decision_dataset",
]
