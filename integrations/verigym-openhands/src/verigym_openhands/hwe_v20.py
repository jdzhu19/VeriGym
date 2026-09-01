"""V20 protocol receipts for public thought plus one canonical HWE tool call."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from verigym.core.hashing import content_hash

from .hwe_v20_protocol import (
    OPENHANDS_V20_CONTENT_RECOVERY_BUDGET,
    OPENHANDS_V20_MAX_CONTEXT_TOKENS,
    OPENHANDS_V20_MAX_OUTPUT_TOKENS,
    OPENHANDS_V20_MAX_PROVIDER_CALLS,
    OPENHANDS_V20_MAX_PROVIDER_TOKENS,
    OPENHANDS_V20_TOOL_CHOICE_POLICY,
)

OPENHANDS_V20_PROTOCOL_RECEIPT_FORMAT = "verigym_openhands_hwe_v20_protocol_receipt_v1"
OPENHANDS_V20_RESULT_FORMAT = "verigym_openhands_hwe_v20_campaign_result_v1"
OPENHANDS_V20_TRAJECTORY_RECEIPT_FORMAT = "verigym_openhands_hwe_v20_trajectory_receipt_v1"
OPENHANDS_V20_DECISION_RECEIPT_FORMAT = "verigym_openhands_hwe_v20_decision_receipt_v1"

_HASH = re.compile(r"^[0-9a-f]{64}$")
_RESULT_PLANES = (
    "benchmark_verifier_pass",
    "agent_protocol_valid",
    "trajectory_eligible",
    "infrastructure_valid",
    "security_valid",
    "sft_admitted",
)


def build_v20_protocol_receipt(
    *,
    provider: Mapping[str, Any],
    protocol: Mapping[str, Any],
    broker_decision_steps: int,
) -> dict[str, Any]:
    """Seal v20 provider, mixed-content, recovery, and broker accounting."""

    input_tokens = _integer(provider.get("input_tokens"), "provider input tokens")
    output_tokens = _integer(provider.get("output_tokens"), "provider output tokens")
    canonical = _integer(
        protocol.get("canonical_tool_response_count"), "canonical-tool response count"
    )
    mixed = _integer(
        protocol.get("mixed_content_tool_response_count"),
        "mixed-content tool response count",
    )
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V20_PROTOCOL_RECEIPT_FORMAT,
        "tool_choice_policy": OPENHANDS_V20_TOOL_CHOICE_POLICY,
        "ordinary_tool_choice": "required",
        "provider_call_budget": OPENHANDS_V20_MAX_PROVIDER_CALLS,
        "provider_token_budget": OPENHANDS_V20_MAX_PROVIDER_TOKENS,
        "max_context_tokens": OPENHANDS_V20_MAX_CONTEXT_TOKENS,
        "max_output_tokens": OPENHANDS_V20_MAX_OUTPUT_TOKENS,
        "content_recovery_budget": OPENHANDS_V20_CONTENT_RECOVERY_BUDGET,
        "provider_call_count": _integer(provider.get("provider_call_count"), "provider call count"),
        "successful_provider_response_count": _integer(
            provider.get("successful_provider_response_count"),
            "successful provider response count",
        ),
        "provider_usage_record_count": _integer(
            provider.get("provider_usage_record_count"), "provider usage record count"
        ),
        "required_tool_request_count": _integer(
            protocol.get("required_tool_request_count"), "required-tool request count"
        ),
        "canonical_tool_response_count": canonical,
        "content_free_tool_response_count": canonical - mixed,
        "mixed_content_tool_response_count": mixed,
        "content_only_response_count": _integer(
            protocol.get("content_only_response_count"), "content-only response count"
        ),
        "format_recovery_count": _integer(
            protocol.get("format_recovery_count"), "format recovery count"
        ),
        "recovery_forced_request_count": _integer(
            protocol.get("recovery_forced_request_count"), "recovery request count"
        ),
        "recovery_validated_tool_count": _integer(
            protocol.get("recovery_validated_tool_count"), "recovery validation count"
        ),
        "over_budget_response_count": _integer(
            protocol.get("over_budget_response_count"), "over-budget response count"
        ),
        "provider_input_tokens": input_tokens,
        "provider_output_tokens": output_tokens,
        "provider_total_tokens": input_tokens + output_tokens,
        "broker_decision_steps": _integer(broker_decision_steps, "broker decision steps"),
        "maximum_tool_calls_per_response": 1,
        "public_tool_thought_allowed": True,
        "public_tool_thought_retained_in_decision": True,
        "public_tool_thought_supervised": True,
        "over_budget_response_accounted_before_rejection": True,
        "over_budget_response_entered_agent_or_broker": False,
        "same_session_recovery": True,
        "recovery_feedback_source": "environment",
        "abnormal_assistant_text_retained_as_input": True,
        "abnormal_assistant_text_supervised": False,
        "recovery_feedback_retained_as_input": True,
        "recovery_feedback_supervised": False,
        "canonical_tool_decisions_supervised": True,
    }
    return validate_v20_protocol_receipt({**base, "receipt_hash": content_hash(base)})


def validate_v20_protocol_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on any v20 request, response, recovery, or budget drift."""

    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("receipt_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v20 protocol receipt identity changed")
    required = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V20_PROTOCOL_RECEIPT_FORMAT,
        "tool_choice_policy": OPENHANDS_V20_TOOL_CHOICE_POLICY,
        "ordinary_tool_choice": "required",
        "provider_call_budget": OPENHANDS_V20_MAX_PROVIDER_CALLS,
        "provider_token_budget": OPENHANDS_V20_MAX_PROVIDER_TOKENS,
        "max_context_tokens": OPENHANDS_V20_MAX_CONTEXT_TOKENS,
        "max_output_tokens": OPENHANDS_V20_MAX_OUTPUT_TOKENS,
        "content_recovery_budget": OPENHANDS_V20_CONTENT_RECOVERY_BUDGET,
        "maximum_tool_calls_per_response": 1,
        "public_tool_thought_allowed": True,
        "public_tool_thought_retained_in_decision": True,
        "public_tool_thought_supervised": True,
        "over_budget_response_accounted_before_rejection": True,
        "over_budget_response_entered_agent_or_broker": False,
        "same_session_recovery": True,
        "recovery_feedback_source": "environment",
        "abnormal_assistant_text_retained_as_input": True,
        "abnormal_assistant_text_supervised": False,
        "recovery_feedback_retained_as_input": True,
        "recovery_feedback_supervised": False,
        "canonical_tool_decisions_supervised": True,
    }
    if any(result.get(key) != item for key, item in required.items()):
        raise ValueError("OpenHands v20 protocol policy changed")
    numeric = {
        key: _integer(result.get(key), key)
        for key in (
            "provider_call_count",
            "successful_provider_response_count",
            "provider_usage_record_count",
            "required_tool_request_count",
            "canonical_tool_response_count",
            "content_free_tool_response_count",
            "mixed_content_tool_response_count",
            "content_only_response_count",
            "format_recovery_count",
            "recovery_forced_request_count",
            "recovery_validated_tool_count",
            "over_budget_response_count",
            "provider_input_tokens",
            "provider_output_tokens",
            "provider_total_tokens",
            "broker_decision_steps",
        )
    }
    calls = numeric["provider_call_count"]
    successful = numeric["successful_provider_response_count"]
    canonical = numeric["canonical_tool_response_count"]
    content_only = numeric["content_only_response_count"]
    recovery_counts = {
        content_only,
        numeric["format_recovery_count"],
        numeric["recovery_forced_request_count"],
        numeric["recovery_validated_tool_count"],
    }
    if (
        not 0 < calls <= OPENHANDS_V20_MAX_PROVIDER_CALLS
        or numeric["required_tool_request_count"] != calls
        or successful != calls
        or numeric["provider_usage_record_count"] != calls
        or canonical + content_only != successful
        or numeric["content_free_tool_response_count"]
        + numeric["mixed_content_tool_response_count"]
        != canonical
        or recovery_counts not in ({0}, {1})
        or numeric["over_budget_response_count"] != 0
        or numeric["provider_total_tokens"]
        != numeric["provider_input_tokens"] + numeric["provider_output_tokens"]
        or numeric["provider_total_tokens"] > OPENHANDS_V20_MAX_PROVIDER_TOKENS
        or numeric["broker_decision_steps"] != canonical
    ):
        raise ValueError("OpenHands v20 protocol accounting changed")
    return copy.deepcopy(dict(value))


def benchmark_verifier_passed(scorecard: Mapping[str, Any]) -> bool:
    """Derive correctness from verifier nodes rather than policy or compatibility state."""

    results = scorecard.get("verifier_results")
    if not isinstance(results, list) or not results:
        return False
    for raw in results:
        if not isinstance(raw, Mapping):
            return False
        passed = raw.get("tests_passed")
        total = raw.get("tests_total")
        if (
            raw.get("status") != "passed"
            or raw.get("error_category") not in {None, "success"}
            or isinstance(passed, bool)
            or not isinstance(passed, int)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or total <= 0
            or passed != total
        ):
            return False
    return True


def classify_v20_campaign_result(
    scorecard: Mapping[str, Any],
    *,
    agent_protocol_valid: bool,
    trajectory_eligible: bool,
    infrastructure_valid: bool,
    security_valid: bool,
    admit_to_sft: bool,
) -> dict[str, Any]:
    """Record the six independent v20 admission planes for a fresh episode."""

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
        "format_id": OPENHANDS_V20_RESULT_FORMAT,
        "task_id": scorecard.get("task_id"),
        "run_id": scorecard.get("run_id"),
        "scorecard_content_hash": content_hash(scorecard),
        "scorecard_resolved_compatibility_value": scorecard.get("resolved"),
        **flags,
        "sft_admitted": admitted,
        "all_sft_admission_planes_satisfied": admitted,
        "evidence_origin": "fresh_v20_episode",
        "historical_trajectory_imported": False,
        "historical_trajectory_reconstructed": False,
        "historical_evidence_relabelled": False,
    }
    return validate_v20_campaign_result({**base, "result_hash": content_hash(base)})


def validate_v20_campaign_result(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on malformed or internally inconsistent v20 result planes."""

    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("result_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v20 campaign result identity changed")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V20_RESULT_FORMAT
        or not _HASH.fullmatch(str(result.get("scorecard_content_hash", "")))
        or any(not isinstance(result.get(key), bool) for key in _RESULT_PLANES)
        or not isinstance(result.get("scorecard_resolved_compatibility_value"), bool)
        or result.get("evidence_origin") != "fresh_v20_episode"
        or result.get("historical_trajectory_imported") is not False
        or result.get("historical_trajectory_reconstructed") is not False
        or result.get("historical_evidence_relabelled") is not False
    ):
        raise ValueError("OpenHands v20 campaign result is malformed")
    first_five = all(result[key] is True for key in _RESULT_PLANES[:-1])
    if result["sft_admitted"] is True and not first_five:
        raise ValueError("OpenHands v20 SFT admission bypassed a result plane")
    if result.get("all_sft_admission_planes_satisfied") is not result["sft_admitted"]:
        raise ValueError("OpenHands v20 SFT admission summary changed")
    return copy.deepcopy(dict(value))


def seal_v20_trajectory_receipt(
    *,
    transcript_hash: str,
    protocol_receipt: Mapping[str, Any],
    campaign_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a fresh exact trajectory to its v20 protocol and six-plane result."""

    _require_hash(transcript_hash, "transcript hash")
    protocol = validate_v20_protocol_receipt(protocol_receipt)
    result = validate_v20_campaign_result(campaign_result)
    if any(result[key] is not True for key in _RESULT_PLANES):
        raise ValueError("OpenHands v20 trajectory receipt requires SFT-admitted evidence")
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V20_TRAJECTORY_RECEIPT_FORMAT,
        "transcript_hash": transcript_hash,
        "protocol_receipt_hash": protocol["receipt_hash"],
        "campaign_result_hash": result["result_hash"],
        "decision_only_loss_mask": True,
        "abnormal_assistant_text_loss_mask": 0,
        "recovery_feedback_loss_mask": 0,
        "public_tool_thought_loss_mask": 1,
        "canonical_tool_decision_loss_mask": 1,
        "max_length": OPENHANDS_V20_MAX_CONTEXT_TOKENS,
        "truncation": "error",
    }
    return {**base, "receipt_hash": content_hash(base)}


def seal_v20_decision_receipt(
    *,
    records: Sequence[Mapping[str, Any]],
    trajectory_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind exact-64K v20 decision rows without rewriting transcript records."""

    trajectory = _validate_trajectory_receipt(trajectory_receipt)
    if not records:
        raise ValueError("OpenHands v20 decision receipt cannot be empty")
    hashes: list[str] = []
    token_counts: list[int] = []
    for raw in records:
        record_hash = str(raw.get("record_hash", ""))
        token_count = _integer(raw.get("token_count"), "decision token count")
        if (
            not _HASH.fullmatch(record_hash)
            or raw.get("transcript_hash") != trajectory["transcript_hash"]
            or raw.get("eligible") is not True
            or raw.get("truncation") != "error"
            or raw.get("input_loss_masked") is not True
            or token_count > OPENHANDS_V20_MAX_CONTEXT_TOKENS
        ):
            raise ValueError("OpenHands v20 decision row is not exact-64K eligible")
        hashes.append(record_hash)
        token_counts.append(token_count)
    if len(hashes) != len(set(hashes)):
        raise ValueError("OpenHands v20 decision rows are duplicated")
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V20_DECISION_RECEIPT_FORMAT,
        "trajectory_receipt_hash": trajectory["receipt_hash"],
        "transcript_hash": trajectory["transcript_hash"],
        "record_count": len(records),
        "record_hashes": hashes,
        "token_counts": token_counts,
        "maximum_token_count": max(token_counts),
        "max_length": OPENHANDS_V20_MAX_CONTEXT_TOKENS,
        "truncation": "error",
        "decision_only_loss_mask": True,
        "public_tool_thought_supervised": True,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _validate_trajectory_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("receipt_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v20 trajectory receipt identity changed")
    required = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V20_TRAJECTORY_RECEIPT_FORMAT,
        "decision_only_loss_mask": True,
        "abnormal_assistant_text_loss_mask": 0,
        "recovery_feedback_loss_mask": 0,
        "public_tool_thought_loss_mask": 1,
        "canonical_tool_decision_loss_mask": 1,
        "max_length": OPENHANDS_V20_MAX_CONTEXT_TOKENS,
        "truncation": "error",
    }
    if any(result.get(key) != item for key, item in required.items()):
        raise ValueError("OpenHands v20 trajectory receipt policy changed")
    for key in ("transcript_hash", "protocol_receipt_hash", "campaign_result_hash"):
        _require_hash(str(result.get(key, "")), key)
    return copy.deepcopy(dict(value))


def validate_v20_trajectory_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an exact v20 trajectory sidecar without rewriting the trajectory."""

    return _validate_trajectory_receipt(value)


def validate_v20_decision_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact-64K v20 decision receipt and all row bindings."""

    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("receipt_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v20 decision receipt identity changed")
    required = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V20_DECISION_RECEIPT_FORMAT,
        "max_length": OPENHANDS_V20_MAX_CONTEXT_TOKENS,
        "truncation": "error",
        "decision_only_loss_mask": True,
        "public_tool_thought_supervised": True,
    }
    if any(result.get(key) != item for key, item in required.items()):
        raise ValueError("OpenHands v20 decision receipt policy changed")
    for key in ("trajectory_receipt_hash", "transcript_hash"):
        _require_hash(str(result.get(key, "")), key)
    count = _integer(result.get("record_count"), "decision record count")
    hashes = result.get("record_hashes")
    tokens = result.get("token_counts")
    if (
        count == 0
        or not isinstance(hashes, list)
        or not isinstance(tokens, list)
        or len(hashes) != count
        or len(tokens) != count
        or len(set(str(item) for item in hashes)) != count
        or any(not isinstance(item, str) or not _HASH.fullmatch(item) for item in hashes)
    ):
        raise ValueError("OpenHands v20 decision receipt rows changed")
    token_counts = [_integer(item, "decision token count") for item in tokens]
    if any(item > OPENHANDS_V20_MAX_CONTEXT_TOKENS for item in token_counts) or result.get(
        "maximum_token_count"
    ) != max(token_counts):
        raise ValueError("OpenHands v20 decision receipt exceeded exact 64K")
    return copy.deepcopy(dict(value))


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"OpenHands v20 {label} must be a non-negative integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"OpenHands v20 {label} is invalid")
    return value


def _require_hash(value: str, label: str) -> None:
    if not _HASH.fullmatch(value):
        raise ValueError(f"OpenHands v20 {label} is invalid")


__all__ = [
    "OPENHANDS_V20_DECISION_RECEIPT_FORMAT",
    "OPENHANDS_V20_PROTOCOL_RECEIPT_FORMAT",
    "OPENHANDS_V20_RESULT_FORMAT",
    "OPENHANDS_V20_TRAJECTORY_RECEIPT_FORMAT",
    "benchmark_verifier_passed",
    "build_v20_protocol_receipt",
    "classify_v20_campaign_result",
    "seal_v20_decision_receipt",
    "seal_v20_trajectory_receipt",
    "validate_v20_campaign_result",
    "validate_v20_decision_receipt",
    "validate_v20_protocol_receipt",
    "validate_v20_trajectory_receipt",
]
