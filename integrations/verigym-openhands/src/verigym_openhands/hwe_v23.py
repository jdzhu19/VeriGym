"""Receipts and six-plane admission for the OpenHands v23 behavior protocol."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from verigym.core.hashing import content_hash
from verigym_deepseek_harness.broker import openhands_v23_progress_gate_state

from .hwe_v22 import benchmark_verifier_passed
from .hwe_v23_protocol import (
    OPENHANDS_V23_CONTENT_RECOVERY_BUDGET,
    OPENHANDS_V23_MAX_CONTEXT_TOKENS,
    OPENHANDS_V23_MAX_OUTPUT_TOKENS,
    OPENHANDS_V23_MAX_PROVIDER_CALLS,
    OPENHANDS_V23_MAX_PROVIDER_TOKENS,
    OPENHANDS_V23_TOOL_CHOICE_POLICY,
)
from .trajectory import validate_openhands_training_trajectory

OPENHANDS_V23_PROTOCOL_RECEIPT_FORMAT = "verigym_openhands_hwe_v23_protocol_receipt_v1"
OPENHANDS_V23_PROGRESS_RECEIPT_FORMAT = "verigym_openhands_v23_progress_observation_receipt_v1"
OPENHANDS_V23_RESULT_FORMAT = "verigym_openhands_hwe_v23_campaign_result_v1"
OPENHANDS_V23_TRAJECTORY_RECEIPT_FORMAT = "verigym_openhands_hwe_v23_trajectory_receipt_v1"
OPENHANDS_V23_DECISION_RECEIPT_FORMAT = "verigym_openhands_hwe_v23_decision_receipt_v1"

_HASH = re.compile(r"^[0-9a-f]{64}$")
_RESULT_PLANES = (
    "benchmark_verifier_pass",
    "agent_protocol_valid",
    "trajectory_eligible",
    "infrastructure_valid",
    "security_valid",
    "sft_admitted",
)


def build_v23_protocol_receipt(
    *,
    provider: Mapping[str, Any],
    protocol: Mapping[str, Any],
    broker: Mapping[str, Any],
    progress: Mapping[str, Any],
    stuck_status: str,
) -> dict[str, Any]:
    """Seal auto/recovery choice, sibling, progress, and observation accounting."""

    input_tokens = _integer(provider.get("input_tokens"), "provider input tokens")
    output_tokens = _integer(provider.get("output_tokens"), "provider output tokens")
    decision_counts = _integer_list(
        protocol.get("decision_tool_call_counts"), "decision tool-call counts", positive=True
    )
    progress_value = _validate_progress(progress)
    observation_compaction = progress_value["observation_compaction"]
    canonical_decisions = _integer(
        protocol.get("canonical_tool_decision_count"), "canonical tool decisions"
    )
    canonical_calls = _integer(protocol.get("canonical_tool_call_count"), "canonical tool calls")
    public_decisions = _integer(protocol.get("public_text_decision_count"), "public-text decisions")
    required_requests = _integer(
        protocol.get("required_tool_request_count"), "recovery required requests"
    )
    ordinary_requests = _integer(
        protocol.get("ordinary_auto_request_count"), "ordinary auto requests"
    )
    broker_calls = _integer(broker.get("tool_calls"), "broker tool calls")
    broker_finished = _boolean(broker.get("finished"), "broker finished")
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V23_PROTOCOL_RECEIPT_FORMAT,
        "tool_choice_policy": OPENHANDS_V23_TOOL_CHOICE_POLICY,
        "ordinary_tool_choice": "auto",
        "ordinary_tool_choice_serialization": "provider_default_omitted",
        "recovery_tool_choice": "required",
        "provider_call_budget": OPENHANDS_V23_MAX_PROVIDER_CALLS,
        "provider_token_budget": OPENHANDS_V23_MAX_PROVIDER_TOKENS,
        "max_context_tokens": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
        "max_output_tokens": OPENHANDS_V23_MAX_OUTPUT_TOKENS,
        "content_recovery_budget": OPENHANDS_V23_CONTENT_RECOVERY_BUDGET,
        "provider_call_count": _integer(provider.get("provider_call_count"), "provider calls"),
        "successful_provider_response_count": _integer(
            provider.get("successful_provider_response_count"), "successful provider responses"
        ),
        "provider_usage_record_count": _integer(
            provider.get("provider_usage_record_count"), "provider usage records"
        ),
        "ordinary_auto_request_count": ordinary_requests,
        "recovery_required_request_count": required_requests,
        "canonical_tool_decision_count": canonical_decisions,
        "canonical_tool_call_count": canonical_calls,
        "content_free_tool_decision_count": canonical_decisions - public_decisions,
        "public_text_decision_count": public_decisions,
        "content_only_response_count": _integer(
            protocol.get("content_only_response_count"), "content-only responses"
        ),
        "format_recovery_count": _integer(
            protocol.get("format_recovery_count"), "format recoveries"
        ),
        "recovery_validated_tool_count": _integer(
            protocol.get("recovery_validated_tool_count"), "recovery validated tools"
        ),
        "over_budget_response_count": _integer(
            protocol.get("over_budget_response_count"), "over-budget responses"
        ),
        "decision_tool_call_counts": decision_counts,
        "sibling_tool_decision_count": _integer(
            protocol.get("sibling_tool_decision_count"), "sibling decisions"
        ),
        "sibling_tool_call_count": _integer(
            protocol.get("sibling_tool_call_count"), "sibling tool calls"
        ),
        "maximum_sibling_tool_calls": max(decision_counts, default=0),
        "broker_tool_calls": broker_calls,
        "broker_action_steps": _integer(broker.get("decision_steps"), "broker action steps"),
        "broker_finished": broker_finished,
        "provider_input_tokens": input_tokens,
        "provider_output_tokens": output_tokens,
        "provider_total_tokens": input_tokens + output_tokens,
        "sibling_prevalidation": "all_before_dispatch",
        "sibling_execution": "openhands_decision_order_serial",
        "tool_concurrency_limit": 1,
        "invalid_sibling_dispatch_count": 0,
        "public_tool_thought_allowed": True,
        "public_tool_thought_supervised": True,
        "private_reasoning_allowed": False,
        "private_reasoning_persisted": False,
        "content_only_recovery_supervised": False,
        "failed_tool_decisions_supervised": False,
        "provider_hidden_thinking": "disabled",
        "stuck_detection_enabled": True,
        "stuck_status": stuck_status,
        "progress_observation_receipt_hash": content_hash(progress_value),
        "first_effective_modification_action": progress_value[
            "first_effective_modification_action"
        ],
        "progress_checkpoint_action": progress_value["progress_checkpoint_action"],
        "progress_checkpoint_injected": progress_value["progress_checkpoint_injected"],
        "progress_checkpoint_sha256": progress_value["progress_checkpoint_sha256"],
        "no_progress_action": progress_value["no_progress_action"],
        "no_progress_terminated": progress_value["no_progress_terminated"],
        "progress_gate_state": progress_value["progress_gate_state"],
        "observation_compaction_hashes": [
            item["compact_sha256"] for item in observation_compaction
        ],
        "observation_raw_hashes": [item["raw_sha256"] for item in observation_compaction],
        "observation_omission_count": sum(
            item["omitted"] is True for item in observation_compaction
        ),
    }
    return validate_v23_protocol_receipt({**base, "receipt_hash": content_hash(base)})


def seal_v23_progress_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal the broker-owned content-free progress/observation projection receipt."""

    if "receipt_hash" in value:
        raise ValueError("OpenHands v23 progress receipt was already sealed")
    base = _validate_progress(value)
    return {**base, "receipt_hash": content_hash(base)}


def validate_v23_progress_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("receipt_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v23 progress receipt identity changed")
    _validate_progress(result)
    return copy.deepcopy(dict(value))


def validate_v23_protocol_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on v23 request, sibling, progress, or token drift."""

    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("receipt_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v23 protocol receipt identity changed")
    required = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V23_PROTOCOL_RECEIPT_FORMAT,
        "tool_choice_policy": OPENHANDS_V23_TOOL_CHOICE_POLICY,
        "ordinary_tool_choice": "auto",
        "ordinary_tool_choice_serialization": "provider_default_omitted",
        "recovery_tool_choice": "required",
        "provider_call_budget": OPENHANDS_V23_MAX_PROVIDER_CALLS,
        "provider_token_budget": OPENHANDS_V23_MAX_PROVIDER_TOKENS,
        "max_context_tokens": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
        "max_output_tokens": OPENHANDS_V23_MAX_OUTPUT_TOKENS,
        "content_recovery_budget": 1,
        "sibling_prevalidation": "all_before_dispatch",
        "sibling_execution": "openhands_decision_order_serial",
        "tool_concurrency_limit": 1,
        "invalid_sibling_dispatch_count": 0,
        "public_tool_thought_allowed": True,
        "public_tool_thought_supervised": True,
        "private_reasoning_allowed": False,
        "private_reasoning_persisted": False,
        "content_only_recovery_supervised": False,
        "failed_tool_decisions_supervised": False,
        "provider_hidden_thinking": "disabled",
        "stuck_detection_enabled": True,
    }
    if any(result.get(key) != item for key, item in required.items()):
        raise ValueError("OpenHands v23 protocol policy changed")
    numeric_names = (
        "provider_call_count",
        "successful_provider_response_count",
        "provider_usage_record_count",
        "ordinary_auto_request_count",
        "recovery_required_request_count",
        "canonical_tool_decision_count",
        "canonical_tool_call_count",
        "content_free_tool_decision_count",
        "public_text_decision_count",
        "content_only_response_count",
        "format_recovery_count",
        "recovery_validated_tool_count",
        "over_budget_response_count",
        "sibling_tool_decision_count",
        "sibling_tool_call_count",
        "maximum_sibling_tool_calls",
        "broker_tool_calls",
        "broker_action_steps",
        "provider_input_tokens",
        "provider_output_tokens",
        "provider_total_tokens",
        "observation_omission_count",
    )
    numeric = {name: _integer(result.get(name), name) for name in numeric_names}
    counts = _integer_list(
        result.get("decision_tool_call_counts"), "decision tool-call counts", positive=True
    )
    calls = numeric["provider_call_count"]
    content_only = numeric["content_only_response_count"]
    sibling_counts = [count for count in counts if count > 1]
    hashes = result.get("observation_compaction_hashes")
    raw_hashes = result.get("observation_raw_hashes")
    if (
        not 0 < calls <= OPENHANDS_V23_MAX_PROVIDER_CALLS
        or numeric["successful_provider_response_count"] != calls
        or numeric["provider_usage_record_count"] != calls
        or numeric["ordinary_auto_request_count"] + numeric["recovery_required_request_count"]
        != calls
        or content_only not in {0, 1}
        or numeric["recovery_required_request_count"] != content_only
        or numeric["format_recovery_count"] != content_only
        or numeric["recovery_validated_tool_count"] != content_only
        or numeric["canonical_tool_decision_count"] + content_only != calls
        or len(counts) != numeric["canonical_tool_decision_count"]
        or sum(counts) != numeric["canonical_tool_call_count"]
        or numeric["content_free_tool_decision_count"] + numeric["public_text_decision_count"]
        != numeric["canonical_tool_decision_count"]
        or len(sibling_counts) != numeric["sibling_tool_decision_count"]
        or sum(sibling_counts) != numeric["sibling_tool_call_count"]
        or max(counts, default=0) != numeric["maximum_sibling_tool_calls"]
        or numeric["broker_tool_calls"] != numeric["canonical_tool_call_count"]
        or numeric["broker_action_steps"]
        != numeric["broker_tool_calls"] - int(result.get("broker_finished") is True)
        or numeric["over_budget_response_count"] != 0
        or numeric["provider_total_tokens"]
        != numeric["provider_input_tokens"] + numeric["provider_output_tokens"]
        or numeric["provider_total_tokens"] > OPENHANDS_V23_MAX_PROVIDER_TOKENS
        or not isinstance(hashes, list)
        or not isinstance(raw_hashes, list)
        or len(hashes) != numeric["broker_tool_calls"]
        or len(raw_hashes) != numeric["broker_tool_calls"]
        or any(not isinstance(item, str) or not _HASH.fullmatch(item) for item in hashes)
        or any(not isinstance(item, str) or not _HASH.fullmatch(item) for item in raw_hashes)
        or result.get("stuck_status") not in {"not_stuck", "stuck"}
        or not isinstance(result.get("broker_finished"), bool)
        or not _HASH.fullmatch(str(result.get("progress_observation_receipt_hash", "")))
    ):
        raise ValueError("OpenHands v23 protocol accounting changed")
    _validate_progress_projection(result, action_count=numeric["broker_tool_calls"])
    return copy.deepcopy(dict(value))


def classify_v23_campaign_result(
    scorecard: Mapping[str, Any],
    *,
    agent_protocol_valid: bool,
    trajectory_eligible: bool,
    infrastructure_valid: bool,
    security_valid: bool,
    admit_to_sft: bool,
) -> dict[str, Any]:
    """Record the six independent admission planes for one fresh v23 episode."""

    flags = {
        "benchmark_verifier_pass": benchmark_verifier_passed(scorecard),
        "agent_protocol_valid": _boolean(agent_protocol_valid, "agent protocol valid"),
        "trajectory_eligible": _boolean(trajectory_eligible, "trajectory eligible"),
        "infrastructure_valid": _boolean(infrastructure_valid, "infrastructure valid"),
        "security_valid": _boolean(security_valid, "security valid"),
    }
    admitted = all(flags.values()) and _boolean(admit_to_sft, "SFT admission")
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V23_RESULT_FORMAT,
        "task_id": scorecard.get("task_id"),
        "run_id": scorecard.get("run_id"),
        "scorecard_content_hash": content_hash(scorecard),
        "scorecard_resolved_compatibility_value": scorecard.get("resolved"),
        **flags,
        "sft_admitted": admitted,
        "all_sft_admission_planes_satisfied": admitted,
        "evidence_origin": "fresh_v23_episode",
        "historical_trajectory_imported": False,
        "historical_trajectory_reconstructed": False,
        "historical_evidence_relabelled": False,
    }
    return validate_v23_campaign_result({**base, "result_hash": content_hash(base)})


def validate_v23_campaign_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("result_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v23 campaign result identity changed")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V23_RESULT_FORMAT
        or not _HASH.fullmatch(str(result.get("scorecard_content_hash", "")))
        or any(not isinstance(result.get(key), bool) for key in _RESULT_PLANES)
        or not isinstance(result.get("scorecard_resolved_compatibility_value"), bool)
        or result.get("evidence_origin") != "fresh_v23_episode"
        or result.get("historical_trajectory_imported") is not False
        or result.get("historical_trajectory_reconstructed") is not False
        or result.get("historical_evidence_relabelled") is not False
        or (
            result["sft_admitted"] is True
            and not all(result[key] is True for key in _RESULT_PLANES[:-1])
        )
        or result.get("all_sft_admission_planes_satisfied") is not result["sft_admitted"]
    ):
        raise ValueError("OpenHands v23 campaign result is malformed")
    return copy.deepcopy(dict(value))


def seal_v23_trajectory_receipt(
    *,
    trajectory: Mapping[str, Any],
    protocol_receipt: Mapping[str, Any],
    campaign_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one exact trajectory to v23 decision, sibling, and mask semantics."""

    transcript = validate_openhands_training_trajectory(trajectory)
    protocol = validate_v23_protocol_receipt(protocol_receipt)
    result = validate_v23_campaign_result(campaign_result)
    if any(result[key] is not True for key in _RESULT_PLANES):
        raise ValueError("OpenHands v23 trajectory receipt requires SFT-admitted evidence")
    decisions = transcript.get("assistant_decisions")
    messages = transcript.get("messages")
    if not isinstance(decisions, list) or not isinstance(messages, list):
        raise ValueError("OpenHands v23 trajectory decisions are malformed")
    tool_counts = [
        _integer(item.get("tool_action_count"), "trajectory tool calls") for item in decisions
    ]
    public_count = sum(
        bool(messages[_integer(item.get("message_index"), "decision message index")].get("content"))
        for item in decisions
    )
    failed_count = sum(item.get("supervised_target") is False for item in decisions)
    if (
        transcript.get("format_recovery_count", 0) != protocol["format_recovery_count"]
        or len(decisions) != protocol["canonical_tool_decision_count"]
        or tool_counts != protocol["decision_tool_call_counts"]
        or public_count != protocol["public_text_decision_count"]
    ):
        raise ValueError("OpenHands v23 trajectory and protocol accounting differ")
    transcript_hash = str(transcript.get("transcript_hash", ""))
    _require_hash(transcript_hash, "transcript hash")
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V23_TRAJECTORY_RECEIPT_FORMAT,
        "transcript_hash": transcript_hash,
        "protocol_receipt_hash": protocol["receipt_hash"],
        "campaign_result_hash": result["result_hash"],
        "decision_only_loss_mask": True,
        "content_only_recovery_loss_mask": 0,
        "recovery_feedback_loss_mask": 0,
        "failed_tool_decision_loss_mask": 0,
        "public_rationale_loss_mask": 1,
        "complete_sibling_decision_loss_mask": 1,
        "assistant_decision_count": len(decisions),
        "supervised_decision_count": len(decisions) - failed_count,
        "failed_tool_decision_count": failed_count,
        "public_text_decision_count": public_count,
        "sibling_tool_decision_count": sum(count > 1 for count in tool_counts),
        "sibling_tool_call_count": sum(count for count in tool_counts if count > 1),
        "first_effective_modification_action": protocol["first_effective_modification_action"],
        "progress_checkpoint_injected": protocol["progress_checkpoint_injected"],
        "no_progress_terminated": protocol["no_progress_terminated"],
        "stuck_status": protocol["stuck_status"],
        "observation_compaction_hashes": protocol["observation_compaction_hashes"],
        "max_length": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
        "truncation": "error",
    }
    return {**base, "receipt_hash": content_hash(base)}


def seal_v23_decision_receipt(
    *,
    records: Sequence[Mapping[str, Any]],
    trajectory_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind exact-64K v23 rows without splitting sibling targets."""

    trajectory = validate_v23_trajectory_receipt(trajectory_receipt)
    if not records:
        raise ValueError("OpenHands v23 decision receipt cannot be empty")
    hashes: list[str] = []
    token_counts: list[int] = []
    sibling_counts: list[int] = []
    for raw in records:
        record_hash = str(raw.get("record_hash", ""))
        token_count = _integer(raw.get("token_count"), "decision token count")
        tool_count = _integer(raw.get("tool_action_count"), "decision tool count")
        target = raw.get("target_message")
        if (
            not _HASH.fullmatch(record_hash)
            or raw.get("transcript_hash") != trajectory["transcript_hash"]
            or raw.get("eligible") is not True
            or raw.get("truncation") != "error"
            or raw.get("input_loss_masked") is not True
            or token_count > OPENHANDS_V23_MAX_CONTEXT_TOKENS
            or not isinstance(target, Mapping)
            or not isinstance(target.get("tool_calls"), list)
            or len(target["tool_calls"]) != tool_count
        ):
            raise ValueError("OpenHands v23 decision row is not exact-64K eligible")
        hashes.append(record_hash)
        token_counts.append(token_count)
        sibling_counts.append(tool_count)
    if len(hashes) != len(set(hashes)) or len(records) != trajectory["supervised_decision_count"]:
        raise ValueError("OpenHands v23 decision rows are duplicated or incomplete")
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V23_DECISION_RECEIPT_FORMAT,
        "trajectory_receipt_hash": trajectory["receipt_hash"],
        "transcript_hash": trajectory["transcript_hash"],
        "record_count": len(records),
        "record_hashes": hashes,
        "token_counts": token_counts,
        "maximum_token_count": max(token_counts),
        "sibling_target_tool_counts": sibling_counts,
        "sibling_targets_split": False,
        "max_length": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
        "truncation": "error",
        "decision_only_loss_mask": True,
        "public_rationale_supervised": True,
        "content_only_recovery_supervised": False,
        "failed_tool_decisions_supervised": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def validate_v23_trajectory_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("receipt_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v23 trajectory receipt identity changed")
    required = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V23_TRAJECTORY_RECEIPT_FORMAT,
        "decision_only_loss_mask": True,
        "content_only_recovery_loss_mask": 0,
        "recovery_feedback_loss_mask": 0,
        "failed_tool_decision_loss_mask": 0,
        "public_rationale_loss_mask": 1,
        "complete_sibling_decision_loss_mask": 1,
        "max_length": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
        "truncation": "error",
    }
    if any(result.get(key) != item for key, item in required.items()):
        raise ValueError("OpenHands v23 trajectory receipt policy changed")
    for key in ("transcript_hash", "protocol_receipt_hash", "campaign_result_hash"):
        _require_hash(str(result.get(key, "")), key)
    for key in (
        "assistant_decision_count",
        "supervised_decision_count",
        "failed_tool_decision_count",
        "public_text_decision_count",
        "sibling_tool_decision_count",
        "sibling_tool_call_count",
    ):
        _integer(result.get(key), key)
    if (
        result["supervised_decision_count"] + result["failed_tool_decision_count"]
        != result["assistant_decision_count"]
        or result.get("stuck_status") != "not_stuck"
        or result.get("no_progress_terminated") is not False
        or not isinstance(result.get("progress_checkpoint_injected"), bool)
        or not isinstance(result.get("observation_compaction_hashes"), list)
    ):
        raise ValueError("OpenHands v23 trajectory receipt is not admissible")
    return copy.deepcopy(dict(value))


def validate_v23_decision_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("receipt_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v23 decision receipt identity changed")
    required = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V23_DECISION_RECEIPT_FORMAT,
        "sibling_targets_split": False,
        "max_length": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
        "truncation": "error",
        "decision_only_loss_mask": True,
        "public_rationale_supervised": True,
        "content_only_recovery_supervised": False,
        "failed_tool_decisions_supervised": False,
    }
    if any(result.get(key) != item for key, item in required.items()):
        raise ValueError("OpenHands v23 decision receipt policy changed")
    count = _integer(result.get("record_count"), "decision record count")
    hashes = result.get("record_hashes")
    tokens = _integer_list(result.get("token_counts"), "decision tokens")
    siblings = _integer_list(
        result.get("sibling_target_tool_counts"), "sibling target counts", positive=True
    )
    if (
        count == 0
        or not isinstance(hashes, list)
        or len(hashes) != count
        or len(tokens) != count
        or len(siblings) != count
        or len(set(str(item) for item in hashes)) != count
        or any(not isinstance(item, str) or not _HASH.fullmatch(item) for item in hashes)
        or any(item > OPENHANDS_V23_MAX_CONTEXT_TOKENS for item in tokens)
        or result.get("maximum_token_count") != max(tokens)
    ):
        raise ValueError("OpenHands v23 decision receipt rows changed")
    for key in ("trajectory_receipt_hash", "transcript_hash"):
        _require_hash(str(result.get(key, "")), key)
    return copy.deepcopy(dict(value))


def _validate_progress(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    required_fields = {
        "schema_version",
        "format_id",
        "first_effective_modification_action",
        "progress_checkpoint_action",
        "progress_checkpoint_injected",
        "progress_checkpoint_sha256",
        "no_progress_action",
        "no_progress_terminated",
        "progress_gate_state",
        "observation_compaction",
    }
    if (
        set(result) != required_fields
        or result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V23_PROGRESS_RECEIPT_FORMAT
        or not isinstance(result.get("progress_checkpoint_injected"), bool)
        or not isinstance(result.get("no_progress_terminated"), bool)
        or not _HASH.fullmatch(str(result.get("progress_checkpoint_sha256", "")))
        or not isinstance(result.get("observation_compaction"), list)
    ):
        raise ValueError("OpenHands v23 progress receipt is malformed")
    for sequence, raw in enumerate(result["observation_compaction"]):
        if (
            not isinstance(raw, Mapping)
            or set(raw)
            != {
                "sequence",
                "raw_sha256",
                "raw_bytes",
                "compact_sha256",
                "compact_tokens",
                "rule_id",
                "omitted",
            }
            or raw.get("sequence") != sequence
            or not _HASH.fullmatch(str(raw.get("raw_sha256", "")))
            or not _HASH.fullmatch(str(raw.get("compact_sha256", "")))
            or not isinstance(raw.get("rule_id"), str)
            or not str(raw["rule_id"]).endswith("_v23")
            or not isinstance(raw.get("omitted"), bool)
        ):
            raise ValueError("OpenHands v23 observation compaction receipt is malformed")
        _integer(raw.get("raw_bytes"), "observation raw bytes")
        _integer(raw.get("compact_tokens"), "observation compact tokens")
    _validate_progress_projection(result, action_count=len(result["observation_compaction"]))
    return result


def _validate_progress_projection(value: Mapping[str, Any], *, action_count: int) -> None:
    first = value.get("first_effective_modification_action")
    try:
        expected = openhands_v23_progress_gate_state(
            action_count=action_count,
            first_effective_modification_action=first,
        )
    except ValueError as exc:
        raise ValueError("OpenHands v23 first modification action is invalid") from exc
    if any(value.get(name) != item for name, item in expected.items()):
        raise ValueError("OpenHands v23 progress gate state changed")


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"OpenHands v23 {label} must be a non-negative integer")
    return value


def _integer_list(value: Any, label: str, *, positive: bool = False) -> list[int]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"OpenHands v23 {label} must be a sequence")
    result = [_integer(item, label) for item in value]
    if positive and any(item == 0 for item in result):
        raise ValueError(f"OpenHands v23 {label} must be positive")
    return result


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"OpenHands v23 {label} is invalid")
    return value


def _require_hash(value: str, label: str) -> None:
    if not _HASH.fullmatch(value):
        raise ValueError(f"OpenHands v23 {label} is invalid")


__all__ = [
    "OPENHANDS_V23_DECISION_RECEIPT_FORMAT",
    "OPENHANDS_V23_PROGRESS_RECEIPT_FORMAT",
    "OPENHANDS_V23_PROTOCOL_RECEIPT_FORMAT",
    "OPENHANDS_V23_RESULT_FORMAT",
    "OPENHANDS_V23_TRAJECTORY_RECEIPT_FORMAT",
    "build_v23_protocol_receipt",
    "classify_v23_campaign_result",
    "seal_v23_decision_receipt",
    "seal_v23_progress_receipt",
    "seal_v23_trajectory_receipt",
    "validate_v23_campaign_result",
    "validate_v23_decision_receipt",
    "validate_v23_protocol_receipt",
    "validate_v23_progress_receipt",
    "validate_v23_trajectory_receipt",
]
