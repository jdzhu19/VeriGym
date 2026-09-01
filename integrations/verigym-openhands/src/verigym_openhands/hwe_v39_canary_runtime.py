"""Runtime identity for the v39 atomic-shape-recovery provider canary."""

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
    OPENHANDS_V19_CANARY_SDK_VERSION,
    OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
)
from .hwe_v21 import validate_v21_protocol_receipt
from .hwe_v21_protocol import (
    OPENHANDS_V21_CONTENT_RECOVERY_BUDGET,
    OPENHANDS_V21_MAX_CONTEXT_TOKENS,
    OPENHANDS_V21_MAX_OUTPUT_TOKENS,
    OPENHANDS_V21_MAX_PROVIDER_CALLS,
    OPENHANDS_V21_MAX_PROVIDER_TOKENS,
    OPENHANDS_V21_MULTI_TOOL_SHAPE_RECOVERY_BUDGET,
    OPENHANDS_V21_RECOVERABLE_TOOL_CALL_COUNT,
    OPENHANDS_V21_TOOL_CHOICE_POLICY,
)

OPENHANDS_V39_CANARY_CONTRACT_FORMAT = "verigym_openhands_hwe_v39_provider_canary_contract_v1"
OPENHANDS_V39_CANARY_CAMPAIGN_ID = "openhands-hwe-v39-atomic-shape-recovery-canary-v1"
OPENHANDS_V39_CANARY_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-v39-atomic-shape-recovery-canary-v1"
)
OPENHANDS_V39_CANARY_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V39_PROVIDER_CANARY_V1"
OPENHANDS_V39_CANARY_SEED = 492
OPENHANDS_V39_CANARY_SAMPLE_INDEX = 8
OPENHANDS_V39_NUMPY_VERSION = "2.2.6"
OPENHANDS_V39_PILLOW_VERSION = "12.1.1"
OPENHANDS_V39_COMMAND_EXECUTION_BACKEND: Literal["episode_container_exec_v1"] = (
    "episode_container_exec_v1"
)

_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"


def validate_v39_canary_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact fresh schedule and v33 command-image bindings."""

    result = dict(value)
    expected_hash = result.pop("contract_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v39 canary contract identity changed")
    schedule = result.get("schedule")
    bindings = result.get("task_bindings")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V39_CANARY_CONTRACT_FORMAT
        or result.get("protocol_profile") != OPENHANDS_V21_TOOL_CHOICE_POLICY
        or not isinstance(schedule, list)
        or len(schedule) != 2
        or not isinstance(bindings, Mapping)
    ):
        raise ValueError("OpenHands v39 canary contract changed")
    expected_schedule = (
        ("hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3231", "training"),
        ("hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204", "validation"),
    )
    for raw, (task_id, role) in zip(schedule, expected_schedule, strict=True):
        if not isinstance(raw, Mapping) or dict(raw) != {
            "task_id": task_id,
            "role": role,
            "seed": OPENHANDS_V39_CANARY_SEED,
            "sample_index": OPENHANDS_V39_CANARY_SAMPLE_INDEX,
        }:
            raise ValueError("OpenHands v39 canary schedule changed")
        binding = bindings.get(task_id)
        if not isinstance(binding, Mapping) or set(binding) != {
            "task_hash",
            "source_hash",
            "command_image_lock_hash",
            "command_image",
            "verifier_image",
            "security_scan_id",
        }:
            raise ValueError("OpenHands v39 task binding changed")
    if set(bindings) != {task_id for task_id, _ in expected_schedule}:
        raise ValueError("OpenHands v39 task inventory changed")
    return {**result, "contract_hash": expected_hash}


def build_v39_canary_agent_version(
    *,
    contract: Mapping[str, Any],
    source_commit: str,
    command_image_locks: Mapping[str, Any],
    failed_v38_report_hash: str,
    v21_protocol_audit_sha256: str,
    v33_catalog_hash: str,
    control_plane_contract_hash: str,
) -> AgentVersionManifest:
    """Bind v39 to v21, the sealed v38 failure and two unused task episodes."""

    sealed = validate_v39_canary_contract(contract)
    hashes = (
        failed_v38_report_hash,
        v21_protocol_audit_sha256,
        v33_catalog_hash,
        control_plane_contract_hash,
    )
    if (
        len(source_commit) != 40
        or any(char not in "0123456789abcdef" for char in source_commit)
        or any(len(value) != 64 for value in hashes)
        or any(any(char not in "0123456789abcdef" for char in value) for value in hashes)
    ):
        raise ValueError("OpenHands v39 predecessor or source identity changed")
    task_ids = [str(item["task_id"]) for item in sealed["schedule"]]
    if set(command_image_locks) != set(task_ids):
        raise ValueError("OpenHands v39 requires exactly its two command-image locks")

    image_hashes: dict[str, str] = {}
    lock_hashes: dict[str, str] = {}
    security_scan_ids: dict[str, str] = {}
    for task_id in task_ids:
        lock = command_image_locks[task_id]
        binding = sealed["task_bindings"][task_id]
        if (
            getattr(lock, "task_id", None) != task_id
            or getattr(lock, "task_hash", None) != binding["task_hash"]
            or getattr(lock, "source_hash", None) != binding["source_hash"]
            or getattr(lock, "lock_hash", None) != binding["command_image_lock_hash"]
            or getattr(lock, "derived_command_image_id", None) != binding["command_image"]
            or getattr(lock, "verifier_base_image_id", None) != binding["verifier_image"]
            or getattr(lock, "security_scan_id", None) != binding["security_scan_id"]
            or getattr(lock, "runtime_network", None) != "none"
            or getattr(lock, "security_scan_passed", None) is not True
            or getattr(lock, "codex_present", None) is not False
            or getattr(lock, "provider_credentials_present", None) is not False
            or getattr(lock, "hidden_assets_present", None) is not False
            or getattr(lock, "reference_patch_present", None) is not False
            or getattr(lock, "verifier_payload_present", None) is not False
            or OPENHANDS_V39_COMMAND_EXECUTION_BACKEND
            not in getattr(lock, "supported_execution_backends", ())
        ):
            raise ValueError("OpenHands v39 command-image binding changed")
        suffix = task_id.rsplit("-", 1)[-1]
        lock_hashes[task_id] = str(binding["command_image_lock_hash"])
        security_scan_ids[task_id] = str(binding["security_scan_id"])
        image_hashes[f"pr{suffix}-command"] = str(binding["command_image"])[7:]
        image_hashes[f"pr{suffix}-verifier"] = str(binding["verifier_image"])[7:]

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
    source_hashes = {
        path.name: hash_bytes(path.read_bytes())
        for path in sorted(package_root.glob("*.py"))
        if path.is_file() and not path.is_symlink()
    }
    version = build_agent_version(
        agent_version_id=OPENHANDS_V39_CANARY_AGENT_VERSION_ID,
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
                "campaign_id": OPENHANDS_V39_CANARY_CAMPAIGN_ID,
                "canary_contract_hash": sealed["contract_hash"],
                "failed_v38_report_hash": failed_v38_report_hash,
                "v21_protocol_audit_sha256": v21_protocol_audit_sha256,
                "v33_catalog_hash": v33_catalog_hash,
                "control_plane_contract_hash": control_plane_contract_hash,
                "openhands_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
                "litellm_version": OPENHANDS_V19_CANARY_LITELLM_VERSION,
                "tiktoken_version": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
                "numpy_version": OPENHANDS_V39_NUMPY_VERSION,
                "pillow_version": OPENHANDS_V39_PILLOW_VERSION,
                "collection_profile_id": "hwe_production_native_shell_v2",
                "tool_contract_id": "hwe_native_shell_v2",
                "tool_choice_policy": OPENHANDS_V21_TOOL_CHOICE_POLICY,
                "ordinary_tool_choice": "required",
                "public_tool_thought_allowed": True,
                "maximum_tool_calls_per_response": 1,
                "combined_shape_recovery_budget": 1,
                "content_recovery_budget": OPENHANDS_V21_CONTENT_RECOVERY_BUDGET,
                "multi_tool_shape_recovery_budget": (
                    OPENHANDS_V21_MULTI_TOOL_SHAPE_RECOVERY_BUDGET
                ),
                "recoverable_provider_tool_call_count": (OPENHANDS_V21_RECOVERABLE_TOOL_CALL_COUNT),
                "multiple_tool_response_rejected_atomically": True,
                "rejected_sibling_tool_calls_dispatched": False,
                "max_provider_calls": OPENHANDS_V21_MAX_PROVIDER_CALLS,
                "max_provider_tokens": OPENHANDS_V21_MAX_PROVIDER_TOKENS,
                "max_context_tokens": OPENHANDS_V21_MAX_CONTEXT_TOKENS,
                "max_output_tokens": OPENHANDS_V21_MAX_OUTPUT_TOKENS,
                "provider_call_accounting": "conversation_agent_attempt_counter_v2",
                "provider_token_accounting": "post_response_pre_dispatch_v21",
                "runtime_role": "credential_free_command_image",
                "command_execution_backend": OPENHANDS_V39_COMMAND_EXECUTION_BACKEND,
                "task_command_image_lock_hashes": lock_hashes,
                "task_security_scan_ids": security_scan_ids,
                "seed": OPENHANDS_V39_CANARY_SEED,
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
            "numpy-version-lock": content_hash(f"numpy=={OPENHANDS_V39_NUMPY_VERSION}"),
            "pillow-version-lock": content_hash(f"pillow=={OPENHANDS_V39_PILLOW_VERSION}"),
            "verigym-openhands-source": content_hash(source_hashes),
            "verigym-source-commit": content_hash(source_commit),
        },
        image_hashes=image_hashes,
        training_dataset_hash=None,
        reward_schema_hash=None,
        reward_profile_hash=None,
        memory_builder_identity_hash=None,
        memory_pack_hash=None,
        model_weights_modified=False,
    )
    return validate_agent_version(version)


def build_v39_canary_agent_options(
    *, seed: int, role: Literal["training", "validation"], agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Build one exact v21 episode with role-specific campaign evidence."""

    version = validate_agent_version(agent_version)
    if (
        seed != OPENHANDS_V39_CANARY_SEED
        or role not in {"training", "validation"}
        or version.agent_version_id != OPENHANDS_V39_CANARY_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != OPENHANDS_V19_CANARY_MODEL
    ):
        raise ValueError("OpenHands v39 canary options require the frozen identity")
    return validate_plugin_options(
        {
            "model_id": OPENHANDS_V19_CANARY_MODEL,
            "base_url_env": OPENHANDS_V19_CANARY_BASE_URL_ENV,
            "api_key_env": OPENHANDS_V19_CANARY_API_KEY_ENV,
            "max_iterations": OPENHANDS_V21_MAX_PROVIDER_CALLS,
            "max_provider_billed_units": OPENHANDS_V21_MAX_PROVIDER_TOKENS,
            "max_process_time_s": 3_600,
            "max_output_tokens": OPENHANDS_V21_MAX_OUTPUT_TOKENS,
            "max_context_tokens": OPENHANDS_V21_MAX_CONTEXT_TOKENS,
            "seed": seed,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "expected_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
            "campaign_role": role,
            "capture_training_transcript": True,
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": json.dumps(
                version.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ),
            "collection_profile_id": "hwe_production_native_shell_v2",
            "tool_choice_policy": OPENHANDS_V21_TOOL_CHOICE_POLICY,
        }
    )


def validate_v39_canary_runtime_evidence(
    *,
    broker: Mapping[str, Any],
    summary: Mapping[str, Any],
    accounting: ExternalAgentAccounting,
    protocol_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate v21 protocol, atomic recovery, accounting and broker identity."""

    protocol = validate_v21_protocol_receipt(protocol_receipt)
    shape = summary.get("provider_response_shape")
    if (
        not isinstance(shape, Mapping)
        or shape.get("raw_model_content_persisted") is not False
        or shape.get("raw_tool_arguments_persisted") is not False
        or shape.get("reasoning_content_present") is not False
        or shape.get("responses_reasoning_present") is not False
        or shape.get("thinking_blocks_present") is not False
        or summary.get("tool_choice_policy") != OPENHANDS_V21_TOOL_CHOICE_POLICY
        or summary.get("v21_protocol_receipt_hash") != protocol["receipt_hash"]
        or summary.get("provider_call_budget") != OPENHANDS_V21_MAX_PROVIDER_CALLS
        or summary.get("provider_call_count") != protocol["provider_call_count"]
        or summary.get("provider_input_tokens") != protocol["provider_input_tokens"]
        or summary.get("provider_output_tokens") != protocol["provider_output_tokens"]
        or summary.get("provider_total_tokens") != protocol["provider_total_tokens"]
        or summary.get("required_tool_request_count") != protocol["required_tool_request_count"]
        or summary.get("canonical_tool_response_count") != protocol["canonical_tool_response_count"]
        or summary.get("content_free_tool_response_count")
        != protocol["content_free_tool_response_count"]
        or summary.get("mixed_content_tool_response_count")
        != protocol["mixed_content_tool_response_count"]
        or summary.get("content_only_response_count") != protocol["content_only_response_count"]
        or summary.get("multi_tool_shape_recovery_count")
        != protocol["multi_tool_shape_recovery_count"]
        or summary.get("rejected_provider_tool_call_count")
        != protocol["rejected_provider_tool_call_count"]
        or summary.get("multi_tool_recovery_response_shape")
        != protocol["multi_tool_recovery_response_shape"]
        or summary.get("whole_episode_retries") != 0
        or summary.get("local_repository_exposed_to_openhands") is not False
        or summary.get("docker_socket_exposed_to_openhands") is not False
        or summary.get("default_tools_exposed") is not False
        or summary.get("plugins_loaded") is not False
        or broker.get("finished") is not True
        or broker.get("infrastructure_failure") is not None
        or broker.get("decision_steps") != protocol["broker_decision_steps"]
        or accounting.model_call_count != protocol["provider_call_count"]
        or accounting.input_tokens != protocol["provider_input_tokens"]
        or accounting.output_tokens != protocol["provider_output_tokens"]
    ):
        raise ValueError("OpenHands v39 canary runtime evidence changed")
    return protocol


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V39_")] + [
    "build_v39_canary_agent_options",
    "build_v39_canary_agent_version",
    "validate_v39_canary_contract",
    "validate_v39_canary_runtime_evidence",
]
