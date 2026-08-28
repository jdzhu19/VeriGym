"""Frozen v17 canary v4 contract with bounded iteration-limit classification."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.evolution.memory import build_agent_version, validate_agent_version
from verigym.plugin_api import JsonValue
from verigym.schemas.evolution import AgentVersionManifest, TaskSplitManifest
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.options import validate_plugin_options

from . import hwe_v17_canary_v3 as _v3
from ._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
    OPENHANDS_PATH_POLICY_RECOVERY_BUDGET,
    OPENHANDS_PATH_POLICY_RECOVERY_POLICY,
    OPENHANDS_SDK_STOP_CONTINUATION_BUDGET,
    OPENHANDS_SDK_STOP_CONTINUATION_POLICY,
)
from .hwe_agent import OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY

OPENHANDS_V17_CANARY_FORMAT = "verigym_openhands_hwe_v17_collection_canary_v4"
OPENHANDS_V17_CANARY_REPORT_FORMAT = "verigym_openhands_hwe_v17_collection_canary_report_v4"
OPENHANDS_V17_CANARY_GATE_FORMAT = "verigym_openhands_hwe_v17_collection_canary_gate_v4"
OPENHANDS_V17_CANARY_CAMPAIGN_ID = "openhands-hwe-v17-collection-canary-v4"
OPENHANDS_V17_CANARY_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v17-collection-canary-v4"
OPENHANDS_V17_CANARY_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V17_COLLECTION_CANARY_V4"
OPENHANDS_V17_CANARY_CONTRACT_FILE = "qwen35_hwe_openhands_v17_canary_v4.json"

OPENHANDS_V17_CANARY_BASE_URL_ENV = _v3.OPENHANDS_V17_CANARY_BASE_URL_ENV
OPENHANDS_V17_CANARY_API_KEY_ENV = _v3.OPENHANDS_V17_CANARY_API_KEY_ENV
OPENHANDS_V17_CANARY_MODEL = _v3.OPENHANDS_V17_CANARY_MODEL
OPENHANDS_V17_CANARY_MODEL_IDENTITY = _v3.OPENHANDS_V17_CANARY_MODEL_IDENTITY
OPENHANDS_V17_CANARY_SDK_VERSION = _v3.OPENHANDS_V17_CANARY_SDK_VERSION
OPENHANDS_V17_CANARY_LITELLM_VERSION = _v3.OPENHANDS_V17_CANARY_LITELLM_VERSION
OPENHANDS_V17_CANARY_TIKTOKEN_VERSION = _v3.OPENHANDS_V17_CANARY_TIKTOKEN_VERSION
OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY = _v3.OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY
OPENHANDS_V17_CANARY_SEED = _v3.OPENHANDS_V17_CANARY_SEED
OPENHANDS_V17_CANARY_SAMPLE_INDEX = _v3.OPENHANDS_V17_CANARY_SAMPLE_INDEX
OPENHANDS_V17_CANARY_MAX_ITERATIONS = _v3.OPENHANDS_V17_CANARY_MAX_ITERATIONS
OPENHANDS_V17_CANARY_MAX_OUTPUT_TOKENS = _v3.OPENHANDS_V17_CANARY_MAX_OUTPUT_TOKENS
OPENHANDS_V17_CANARY_MAX_CONTEXT_TOKENS = _v3.OPENHANDS_V17_CANARY_MAX_CONTEXT_TOKENS

OPENHANDS_V17_CANARY_PR2944 = _v3.OPENHANDS_V17_CANARY_PR2944
OPENHANDS_V17_CANARY_PR2248 = _v3.OPENHANDS_V17_CANARY_PR2248
OPENHANDS_V17_CANARY_PR3191 = _v3.OPENHANDS_V17_CANARY_PR3191
OPENHANDS_V17_CANARY_PR2032 = _v3.OPENHANDS_V17_CANARY_PR2032
OPENHANDS_V17_CANARY_PR3168 = _v3.OPENHANDS_V17_CANARY_PR3168
OPENHANDS_V17_CANARY_PR3204 = _v3.OPENHANDS_V17_CANARY_PR3204
OPENHANDS_V17_CANARY_SCHEDULE = _v3.OPENHANDS_V17_CANARY_SCHEDULE
OPENHANDS_V17_CANARY_TASKS = _v3.OPENHANDS_V17_CANARY_TASKS
OPENHANDS_V17_FORMAL_TRAINING_ORDER = _v3.OPENHANDS_V17_FORMAL_TRAINING_ORDER
OPENHANDS_V17_FORMAL_VALIDATION_ORDER = _v3.OPENHANDS_V17_FORMAL_VALIDATION_ORDER
OPENHANDS_V17_TRAINING_TARGET = _v3.OPENHANDS_V17_TRAINING_TARGET
OPENHANDS_V17_VALIDATION_TARGET = _v3.OPENHANDS_V17_VALIDATION_TARGET

V17CanaryGate = _v3.V17CanaryGate
derive_v17_v3_task_split = _v3.derive_v17_v3_task_split
evaluate_v17_canary_gate = _v3.evaluate_v17_canary_gate
seal_v17_canary_report = _v3.seal_v17_canary_report
validate_v17_canonical_tool_shape = _v3.validate_v17_canonical_tool_shape
validate_v17_recovery_accounting = _v3.validate_v17_recovery_accounting


def expected_v17_canary_contract() -> dict[str, Any]:
    """Return the exact v4 contract without mutating the frozen v3 contract."""

    base = copy.deepcopy(_v3.expected_v17_canary_contract())
    base.pop("contract_hash")
    base["format_id"] = OPENHANDS_V17_CANARY_FORMAT
    teacher = base["teacher"]
    teacher["scaffold"] = "openhands-sdk-1.42.1-verigym-broker-v2-v18-bounded-limit-v1"
    teacher["bounded_iteration_termination_policy_id"] = (
        OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY
    )
    gate = base["gate"]
    gate["bounded_iteration_limit_is_model_nonfinish"] = True
    gate["bounded_iteration_limit_exact_shape"] = {
        "provider_calls": OPENHANDS_V17_CANARY_MAX_ITERATIONS,
        "accepted_tool_calls": OPENHANDS_V17_CANARY_MAX_ITERATIONS,
        "broker_decision_steps": OPENHANDS_V17_CANARY_MAX_ITERATIONS + 1,
        "rejected_calls": 1,
        "rejection_code": "episode_limit",
        "policy_failure": "decision_steps_hard_limit",
        "conversation_error_events": 1,
        "trajectory_exported": False,
    }
    return {**base, "contract_hash": content_hash(base)}


def load_v17_canary_contract(path: Path) -> dict[str, Any]:
    """Load only the exact v4 canary contract."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 256 * 1024:
        raise ValueError("OpenHands v17 canary v4 contract must be a small regular file")
    parsed = json.loads(path.read_bytes())
    if not isinstance(parsed, dict) or parsed != expected_v17_canary_contract():
        raise ValueError("OpenHands v17 canary v4 contract identity changed")
    return parsed


def validate_v17_canary_source(
    contract: Mapping[str, Any],
    *,
    split: TaskSplitManifest,
    task_split_path: Path,
    qualification_progress_path: Path,
) -> None:
    """Reuse the frozen v3 public-source bindings after validating the v4 identity."""

    if dict(contract) != expected_v17_canary_contract():
        raise ValueError("OpenHands v17 canary v4 contract identity changed")
    _v3.validate_v17_canary_source(
        _v3.expected_v17_canary_contract(),
        split=split,
        task_split_path=task_split_path,
        qualification_progress_path=qualification_progress_path,
    )


def build_v17_canary_agent_version(
    *, source_commit: str, image_locks: Mapping[str, Any]
) -> AgentVersionManifest:
    """Freeze a v4 identity over the v3 inputs plus the bounded-limit policy."""

    template = _v3.build_v17_canary_agent_version(
        source_commit=source_commit,
        image_locks=image_locks,
    )
    values = template.model_dump(mode="json", exclude={"version_hash"})
    values.update(
        {
            "agent_version_id": OPENHANDS_V17_CANARY_AGENT_VERSION_ID,
            "runtime_identity_hash": content_hash(
                {
                    "runtime_template_hash": template.runtime_identity_hash,
                    "canary_contract_hash": expected_v17_canary_contract()["contract_hash"],
                    "bounded_iteration_termination_policy_id": (
                        OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY
                    ),
                    "bounded_iteration_limit": OPENHANDS_V17_CANARY_MAX_ITERATIONS,
                    "bounded_iteration_limit_classification": "model_nonfinish",
                    "bounded_iteration_limit_retries": 0,
                }
            ),
        }
    )
    return validate_agent_version(build_agent_version(**values))


def build_v17_canary_agent_options(
    *, seed: int, agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Build the exact v4 no-retry options."""

    version = validate_agent_version(agent_version)
    if (
        version.agent_version_id != OPENHANDS_V17_CANARY_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != OPENHANDS_V17_CANARY_MODEL
    ):
        raise ValueError("OpenHands v17 canary v4 options require the frozen version")
    manifest_json = json.dumps(
        version.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return validate_plugin_options(
        {
            "model_id": OPENHANDS_V17_CANARY_MODEL,
            "base_url_env": OPENHANDS_V17_CANARY_BASE_URL_ENV,
            "api_key_env": OPENHANDS_V17_CANARY_API_KEY_ENV,
            "max_iterations": OPENHANDS_V17_CANARY_MAX_ITERATIONS,
            "max_process_time_s": 3_600,
            "max_output_tokens": OPENHANDS_V17_CANARY_MAX_OUTPUT_TOKENS,
            "max_context_tokens": OPENHANDS_V17_CANARY_MAX_CONTEXT_TOKENS,
            "seed": seed,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "expected_sdk_version": OPENHANDS_V17_CANARY_SDK_VERSION,
            "campaign_role": "training",
            "capture_training_transcript": True,
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": manifest_json,
            "collection_profile_id": "hwe_production_native_shell_v2",
            "tool_choice_policy": OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY,
        }
    )


def validate_v17_runtime_evidence(
    broker: Mapping[str, Any],
    summary: Mapping[str, Any],
    accounting: ExternalAgentAccounting,
    *,
    verifier_resolved: bool,
) -> str:
    """Accept ordinary v18 evidence or one exact bounded iteration-limit receipt."""

    if summary.get("bounded_iteration_limit_exhausted") is not True:
        return _v3.validate_v17_runtime_evidence(
            broker,
            summary,
            accounting,
            verifier_resolved=verifier_resolved,
        )
    recovery_path = validate_v17_recovery_accounting(summary)
    event_counts = summary.get("event_type_counts")
    raw_audit = broker.get("raw_audit_manifest")
    limit = OPENHANDS_V17_CANARY_MAX_ITERATIONS
    input_tokens = accounting.input_tokens
    output_tokens = accounting.output_tokens
    total_tokens = accounting.total_tokens
    exact = (
        recovery_path == "direct"
        and verifier_resolved is False
        and accounting.model_call_count == limit
        and accounting.external_tool_call_count == limit
        and accounting.external_command_count == broker.get("command_calls")
        and accounting.external_file_read_count == broker.get("file_reads")
        and accounting.external_file_write_count == broker.get("patches")
        and accounting.external_patch_count == broker.get("patches")
        and input_tokens is not None
        and output_tokens is not None
        and total_tokens == input_tokens + output_tokens
        and summary.get("provider_call_budget") == limit
        and summary.get("provider_call_count") == limit
        and summary.get("successful_provider_response_count") == limit
        and summary.get("provider_usage_record_count") == limit
        and summary.get("provider_input_tokens") == input_tokens
        and summary.get("provider_output_tokens") == output_tokens
        and summary.get("broker_decision_steps") == limit + 1
        and broker.get("tool_calls") == limit
        and broker.get("decision_steps") == limit + 1
        and broker.get("finished") is False
        and broker.get("finish_calls") == 0
        and broker.get("policy_failure") == "decision_steps_hard_limit"
        and broker.get("infrastructure_failure") is None
        and broker.get("rejected_calls") == 1
        and broker.get("rejection_codes") == ["episode_limit"]
        and event_counts
        == {
            "ActionEvent": limit + 1,
            "ConversationErrorEvent": 1,
            "MessageEvent": 1,
            "ObservationEvent": limit + 1,
            "SystemPromptEvent": 1,
        }
        and summary.get("bounded_iteration_termination_policy_id")
        == OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY
        and summary.get("termination_authority") == "sdk_iteration_limit"
        and summary.get("tool_choice_policy") == OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY
        and summary.get("sdk_version") == OPENHANDS_V17_CANARY_SDK_VERSION
        and summary.get("whole_episode_retries") == 0
        and summary.get("default_tools_exposed") is False
        and summary.get("docker_socket_exposed_to_openhands") is False
        and summary.get("local_repository_exposed_to_openhands") is False
        and summary.get("private_reasoning_persisted") is False
        and summary.get("message_content_persisted") is False
        and summary.get("ordinary_hidden_verifier_pending") is False
        and summary.get("ordinary_verifier_resolved") is False
        and summary.get("training_trajectory_captured") is False
        and summary.get("training_trajectory_exported") is False
        and summary.get("same_session_recovery") is True
        and summary.get("format_recovery_policy_id") == OPENHANDS_FORMAT_RECOVERY_POLICY
        and summary.get("format_recovery_budget") == OPENHANDS_FORMAT_RECOVERY_BUDGET
        and summary.get("sdk_stop_continuation_policy_id") == OPENHANDS_SDK_STOP_CONTINUATION_POLICY
        and summary.get("sdk_stop_continuation_budget") == OPENHANDS_SDK_STOP_CONTINUATION_BUDGET
        and summary.get("sdk_continuation_tool_choice_policy") == "responses_required_validated_v1"
        and summary.get("path_policy_recovery_policy_id") == OPENHANDS_PATH_POLICY_RECOVERY_POLICY
        and summary.get("path_policy_recovery_budget") == OPENHANDS_PATH_POLICY_RECOVERY_BUDGET
        and summary.get("path_policy_recovery_tool_choice_policy")
        == "responses_required_validated_v1"
        and summary.get("recovery_coalesced_output_count") == 0
        and summary.get("recovery_response_shape") == {}
        and summary.get("sdk_continuation_response_shape") == {}
        and summary.get("path_policy_recovery_response_shape") == {}
        and summary.get("raw_rejected_provider_arguments_persisted") is False
        and isinstance(raw_audit, dict)
        and raw_audit.get("secret_scan") == "passed"
    )
    if not exact:
        raise ValueError("OpenHands v17 bounded iteration-limit evidence changed")
    return "bounded_iteration_limit_model_nonfinish"


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V17_CANARY_")] + [
    "V17CanaryGate",
    "build_v17_canary_agent_options",
    "build_v17_canary_agent_version",
    "derive_v17_v3_task_split",
    "evaluate_v17_canary_gate",
    "expected_v17_canary_contract",
    "load_v17_canary_contract",
    "seal_v17_canary_report",
    "validate_v17_canary_source",
    "validate_v17_canonical_tool_shape",
    "validate_v17_recovery_accounting",
    "validate_v17_runtime_evidence",
]
