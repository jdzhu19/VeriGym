"""Frozen runtime identity for the v58 Ibex PR-54 v23 provider canary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.memory import build_agent_version, validate_agent_version
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions
from verigym.plugin_api import JsonValue
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.options import validate_plugin_options

from .hwe_agent import OpenHandsHweAgentAdapter
from .hwe_v19_canary_runtime import (
    OPENHANDS_V19_CANARY_API_KEY_ENV,
    OPENHANDS_V19_CANARY_BASE_URL_ENV,
    OPENHANDS_V19_CANARY_LITELLM_VERSION,
    OPENHANDS_V19_CANARY_MODEL,
    OPENHANDS_V19_CANARY_MODEL_IDENTITY,
    OPENHANDS_V19_CANARY_SDK_VERSION,
    OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
    OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
)
from .hwe_v23 import validate_v23_protocol_receipt
from .hwe_v23_protocol import (
    OPENHANDS_V23_MAX_CONTEXT_TOKENS,
    OPENHANDS_V23_MAX_OUTPUT_TOKENS,
    OPENHANDS_V23_MAX_PROVIDER_CALLS,
    OPENHANDS_V23_MAX_PROVIDER_TOKENS,
    OPENHANDS_V23_TOOL_CHOICE_POLICY,
)

OPENHANDS_V58_AUTHORIZATION_FORMAT = (
    "verigym_openhands_hwe_v58_ibex_pr54_provider_canary_authorization_v1"
)
OPENHANDS_V58_REPORT_FORMAT = "verigym_openhands_hwe_v58_ibex_pr54_provider_canary_report_v1"
OPENHANDS_V58_CAMPAIGN_ID = "openhands-hwe-v58-ibex-pr54-v23-provider-canary-v1"
OPENHANDS_V58_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v58-ibex-v23-canary-v1"
OPENHANDS_V58_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V58_IBEX_PROVIDER_CANARY_V1"
OPENHANDS_V58_SEED = 498
OPENHANDS_V58_SAMPLE_INDEX = 14
OPENHANDS_V58_NUMPY_VERSION = "2.2.6"
OPENHANDS_V58_PILLOW_VERSION = "12.1.1"
OPENHANDS_V58_COMMAND_EXECUTION_BACKEND: Literal["episode_container_exec_v1"] = (
    "episode_container_exec_v1"
)
OPENHANDS_V58_TASK_ID = "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-54"

_QUALIFICATION_MERGE_COMMIT = "0a71773a3acb52414739bebbb6e4e73a7d2ab37c"
_QUALIFICATION_MAIN_RUN_ID = 33_618_065_213
_TASK_HASH = "b03b430845b6bb97a0b0443c52d337817b4ff33e3cc1b3ea15800bb8bfb4a14a"
_SOURCE_HASH = "5393fbc4261f1a8e19ba7af7b1501367a6c1f3c28bed72f556291f734d095914"
_COMMAND_LOCK_HASH = "3f7e090239e1230054620a7a51330a16bef54e084a395dcd294e60de003bb798"
_COMMAND_IMAGE = "sha256:6f88fdae127f75326407b4ebff529fea5f87aeb64997970d4408678fab942c3b"
_VERIFIER_IMAGE = "sha256:a35075b506d4d8b4e9434e31f38ee0699afdb18f7119e324d49bee60565f5bfa"
_SECURITY_SCAN_ID = "1bd004e75bdf245596bd1bcd3021d184123203711c30fda24969d040656ed281"
_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"


def validate_v58_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the one-task authorization without accepting identity substitutions."""

    result = dict(value)
    observed_hash = result.pop("authorization_hash", None)
    if not isinstance(observed_hash, str) or content_hash(result) != observed_hash:
        raise ValueError("OpenHands v58 authorization identity changed")
    expected_schedule = [
        {
            "task_id": OPENHANDS_V58_TASK_ID,
            "role": "training",
            "seed": OPENHANDS_V58_SEED,
            "sample_index": OPENHANDS_V58_SAMPLE_INDEX,
        }
    ]
    binding = result.get("task_binding")
    expected_binding = {
        "task_id": OPENHANDS_V58_TASK_ID,
        "task_hash": _TASK_HASH,
        "source_hash": _SOURCE_HASH,
        "command_image_lock_hash": _COMMAND_LOCK_HASH,
        "command_image": _COMMAND_IMAGE,
        "verifier_image": _VERIFIER_IMAGE,
        "security_scan_id": _SECURITY_SCAN_ID,
        "source_whiteout_path": "/home/ibex",
    }
    expected_protocol = {
        "profile": OPENHANDS_V23_TOOL_CHOICE_POLICY,
        "ordinary_tool_choice": "auto",
        "content_only_recovery_tool_choice": "required",
        "content_only_recovery_budget": 1,
        "public_rationale_allowed": True,
        "sibling_calls_allowed": True,
        "sibling_prevalidation_atomic": True,
        "sibling_dispatch_order": "provider_decision_order",
        "private_reasoning_rejected": True,
        "provider_hidden_thinking": "disabled",
        "failed_decisions_supervised": False,
        "content_only_recovery_supervised": False,
    }
    expected_budget = {
        "temperature": 0,
        "max_provider_calls": OPENHANDS_V23_MAX_PROVIDER_CALLS,
        "max_provider_tokens": OPENHANDS_V23_MAX_PROVIDER_TOKENS,
        "max_context_tokens": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
        "max_output_tokens": OPENHANDS_V23_MAX_OUTPUT_TOKENS,
        "provider_request_retries": 0,
        "whole_episode_retries": 0,
    }
    expected_actions = {
        "invoke_provider_for_pr54_once": True,
        "retry_pr54": False,
        "run_formal_collection": False,
        "start_training": False,
    }
    expected_software = {
        "model": OPENHANDS_V19_CANARY_MODEL,
        "model_identity": OPENHANDS_V19_CANARY_MODEL_IDENTITY,
        "openhands_sdk": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers": OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
        "numpy": OPENHANDS_V58_NUMPY_VERSION,
        "pillow": OPENHANDS_V58_PILLOW_VERSION,
    }
    if (
        set(result)
        != {
            "schema_version",
            "format_id",
            "status",
            "identity",
            "qualification_merge_commit",
            "qualification_post_merge_main_run_id",
            "qualification_post_merge_main_all_eight_classes_passed",
            "schedule",
            "task_binding",
            "protocol",
            "provider_budget",
            "software",
            "authorized_actions",
            "provider_calls_before_canary",
            "benchmark_task_consumed_before_canary",
            "formal_collection_allowed",
            "formal_collection_started",
            "collection_started",
            "training_started",
            "production_training_ready",
        }
        or result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V58_AUTHORIZATION_FORMAT
        or result.get("status") != "authorized_pending_provider_canary"
        or result.get("identity") != OPENHANDS_V58_CAMPAIGN_ID
        or result.get("qualification_merge_commit") != _QUALIFICATION_MERGE_COMMIT
        or result.get("qualification_post_merge_main_run_id") != _QUALIFICATION_MAIN_RUN_ID
        or result.get("qualification_post_merge_main_all_eight_classes_passed") is not True
        or result.get("schedule") != expected_schedule
        or binding != expected_binding
        or result.get("protocol") != expected_protocol
        or result.get("provider_budget") != expected_budget
        or result.get("software") != expected_software
        or result.get("authorized_actions") != expected_actions
        or result.get("provider_calls_before_canary") != 0
        or result.get("benchmark_task_consumed_before_canary") is not False
        or result.get("formal_collection_allowed") is not False
        or result.get("formal_collection_started") is not False
        or result.get("collection_started") is not False
        or result.get("training_started") is not False
        or result.get("production_training_ready") is not False
    ):
        raise ValueError("OpenHands v58 authorization policy changed")
    return {**result, "authorization_hash": observed_hash}


def build_v58_agent_version(
    *,
    authorization: Mapping[str, Any],
    source_commit: str,
    command_image_lock: Any,
) -> AgentVersionManifest:
    """Bind the v58 model identity to v23 and the exact Ibex image pair."""

    approved = validate_v58_authorization(authorization)
    binding = approved["task_binding"]
    if (
        len(source_commit) != 40
        or any(char not in "0123456789abcdef" for char in source_commit)
        or getattr(command_image_lock, "task_id", None) != OPENHANDS_V58_TASK_ID
        or getattr(command_image_lock, "task_hash", None) != binding["task_hash"]
        or getattr(command_image_lock, "source_hash", None) != binding["source_hash"]
        or getattr(command_image_lock, "lock_hash", None) != binding["command_image_lock_hash"]
        or getattr(command_image_lock, "derived_command_image_id", None) != binding["command_image"]
        or getattr(command_image_lock, "verifier_base_image_id", None) != binding["verifier_image"]
        or getattr(command_image_lock, "security_scan_id", None) != binding["security_scan_id"]
        or getattr(command_image_lock, "source_whiteout_path", None) != "/home/ibex"
        or getattr(command_image_lock, "runtime_network", None) != "none"
        or getattr(command_image_lock, "security_scan_passed", None) is not True
        or getattr(command_image_lock, "codex_present", None) is not False
        or getattr(command_image_lock, "provider_credentials_present", None) is not False
        or getattr(command_image_lock, "hidden_assets_present", None) is not False
        or getattr(command_image_lock, "reference_patch_present", None) is not False
        or getattr(command_image_lock, "verifier_payload_present", None) is not False
    ):
        raise ValueError("OpenHands v58 command-image binding changed")

    agent = OpenHandsHweAgentAdapter()
    spec = agent.prompt_policy_spec
    assert spec is not None
    prompt_contract_hash = content_hash(
        {
            "resolver_id": "agent_execution_prompt_policy_v1",
            "prompt_contract_id": spec.prompt_contract_id,
            "prompt_contract_version": spec.prompt_contract_version,
            "interaction_mode": InteractionMode.AGENT,
            "task_context_policy": spec.task_context_policy,
            "base_instruction_policy": spec.base_instruction_policy,
            "content_visibility_policy": spec.content_visibility_policy,
            "max_prompt_bytes": spec.max_prompt_bytes,
            "max_task_context_bytes": spec.max_task_context_bytes,
            "agent_descriptor_hash": content_hash(agent.descriptor),
        }
    )
    package_root = Path(__file__).resolve().parent
    critical_sources = (
        "agent.py",
        "hwe_agent.py",
        "hwe_command_runtime.py",
        "hwe_v23.py",
        "hwe_v23_protocol.py",
        "hwe_v58_ibex_canary_runtime.py",
        "trajectory.py",
    )
    source_hashes = {
        name: hash_bytes((package_root / name).read_bytes()) for name in critical_sources
    }
    version = build_agent_version(
        agent_version_id=OPENHANDS_V58_AGENT_VERSION_ID,
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=False,
        base_agent_id=agent.descriptor.name,
        agent_descriptor_hash=content_hash(agent.descriptor),
        model_id=OPENHANDS_V19_CANARY_MODEL,
        reasoning_effort="thinking-disabled",
        auth_semantic_id="deepseek.env-bearer.v1",
        runtime_identity_hash=content_hash(
            {
                "campaign_id": OPENHANDS_V58_CAMPAIGN_ID,
                "authorization_hash": approved["authorization_hash"],
                "qualification_merge_commit": _QUALIFICATION_MERGE_COMMIT,
                "qualification_post_merge_main_run_id": _QUALIFICATION_MAIN_RUN_ID,
                "tool_choice_policy": OPENHANDS_V23_TOOL_CHOICE_POLICY,
                "ordinary_tool_choice": "auto",
                "recovery_tool_choice": "required",
                "provider_hidden_thinking": "disabled",
                "max_provider_calls": OPENHANDS_V23_MAX_PROVIDER_CALLS,
                "max_provider_tokens": OPENHANDS_V23_MAX_PROVIDER_TOKENS,
                "max_context_tokens": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
                "max_output_tokens": OPENHANDS_V23_MAX_OUTPUT_TOKENS,
                "command_image_lock_hash": binding["command_image_lock_hash"],
                "security_scan_id": binding["security_scan_id"],
                "seed": OPENHANDS_V58_SEED,
                "sample_index": OPENHANDS_V58_SAMPLE_INDEX,
                "runtime_network": "none",
                "whole_episode_retries": 0,
                "provider_request_retries": 0,
            }
        ),
        tool_policy_hash=content_hash(deepseek_harness_tool_definitions()),
        prompt_contract_hash=prompt_contract_hash,
        source_commit=source_commit,
        package_hashes={
            "litellm-1.93.0-wheel": _LITELLM_WHEEL_SHA256,
            "openhands-sdk-1.42.1-wheel": _OPENHANDS_SDK_WHEEL_SHA256,
            "tiktoken-0.7.0-wheel": _TIKTOKEN_WHEEL_SHA256,
            "numpy-version-lock": content_hash(f"numpy=={OPENHANDS_V58_NUMPY_VERSION}"),
            "pillow-version-lock": content_hash(f"pillow=={OPENHANDS_V58_PILLOW_VERSION}"),
            "verigym-openhands-critical-source": content_hash(source_hashes),
            "verigym-source-commit": content_hash(source_commit),
        },
        image_hashes={
            "ibex-pr54-command": binding["command_image"][7:],
            "ibex-pr54-verifier": binding["verifier_image"][7:],
        },
        training_dataset_hash=None,
        reward_schema_hash=None,
        reward_profile_hash=None,
        memory_builder_identity_hash=None,
        memory_pack_hash=None,
        model_weights_modified=False,
    )
    return validate_agent_version(version)


def build_v58_agent_options(*, agent_version: AgentVersionManifest) -> dict[str, JsonValue]:
    """Build the only provider episode allowed by the v58 identity."""

    version = validate_agent_version(agent_version)
    if (
        version.agent_version_id != OPENHANDS_V58_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != OPENHANDS_V19_CANARY_MODEL
    ):
        raise ValueError("OpenHands v58 agent version changed")
    return validate_plugin_options(
        {
            "model_id": OPENHANDS_V19_CANARY_MODEL,
            "base_url_env": OPENHANDS_V19_CANARY_BASE_URL_ENV,
            "api_key_env": OPENHANDS_V19_CANARY_API_KEY_ENV,
            "max_iterations": OPENHANDS_V23_MAX_PROVIDER_CALLS,
            "max_provider_billed_units": OPENHANDS_V23_MAX_PROVIDER_TOKENS,
            "max_process_time_s": 3_600,
            "max_output_tokens": OPENHANDS_V23_MAX_OUTPUT_TOKENS,
            "max_context_tokens": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
            "seed": OPENHANDS_V58_SEED,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "expected_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
            "campaign_role": "training",
            "capture_training_transcript": True,
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": json.dumps(
                version.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ),
            "collection_profile_id": "hwe_production_native_shell_v2",
            "tool_choice_policy": OPENHANDS_V23_TOOL_CHOICE_POLICY,
        }
    )


def validate_v58_runtime_evidence(
    *,
    broker: Mapping[str, Any],
    summary: Mapping[str, Any],
    accounting: ExternalAgentAccounting,
    protocol_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconcile provider, broker, v23, hidden-reasoning, and retry evidence."""

    protocol = validate_v23_protocol_receipt(protocol_receipt)
    shape = summary.get("provider_response_shape")
    if (
        not isinstance(shape, Mapping)
        or shape.get("raw_model_content_persisted") is not False
        or shape.get("raw_tool_arguments_persisted") is not False
        or shape.get("reasoning_content_present") is not False
        or shape.get("responses_reasoning_present") is not False
        or shape.get("thinking_blocks_present") is not False
        or summary.get("private_reasoning_persisted") is not False
        or summary.get("tool_choice_policy") != OPENHANDS_V23_TOOL_CHOICE_POLICY
        or summary.get("v23_protocol_receipt_hash") != protocol["receipt_hash"]
        or summary.get("provider_call_budget") != OPENHANDS_V23_MAX_PROVIDER_CALLS
        or summary.get("provider_call_count") != protocol["provider_call_count"]
        or summary.get("provider_input_tokens") != protocol["provider_input_tokens"]
        or summary.get("provider_output_tokens") != protocol["provider_output_tokens"]
        or summary.get("provider_total_tokens") != protocol["provider_total_tokens"]
        or summary.get("ordinary_auto_request_count") != protocol["ordinary_auto_request_count"]
        or summary.get("recovery_required_request_count")
        != protocol["recovery_required_request_count"]
        or summary.get("canonical_tool_decision_count") != protocol["canonical_tool_decision_count"]
        or summary.get("canonical_tool_call_count") != protocol["canonical_tool_call_count"]
        or summary.get("public_text_decision_count") != protocol["public_text_decision_count"]
        or summary.get("sibling_tool_decision_count") != protocol["sibling_tool_decision_count"]
        or summary.get("sibling_tool_call_count") != protocol["sibling_tool_call_count"]
        or summary.get("first_effective_modification_action")
        != protocol["first_effective_modification_action"]
        or summary.get("progress_checkpoint_injected") != protocol["progress_checkpoint_injected"]
        or summary.get("no_progress_terminated") != protocol["no_progress_terminated"]
        or summary.get("stuck_status") != protocol["stuck_status"]
        or summary.get("whole_episode_retries") != 0
        or summary.get("local_repository_exposed_to_openhands") is not False
        or summary.get("docker_socket_exposed_to_openhands") is not False
        or summary.get("default_tools_exposed") is not False
        or summary.get("plugins_loaded") is not False
        or broker.get("infrastructure_failure") is not None
        or accounting.model_call_count != protocol["provider_call_count"]
        or accounting.input_tokens != protocol["provider_input_tokens"]
        or accounting.output_tokens != protocol["provider_output_tokens"]
    ):
        raise ValueError("OpenHands v58 runtime evidence changed")
    return protocol


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V58_")] + [
    "build_v58_agent_options",
    "build_v58_agent_version",
    "validate_v58_authorization",
    "validate_v58_runtime_evidence",
]
