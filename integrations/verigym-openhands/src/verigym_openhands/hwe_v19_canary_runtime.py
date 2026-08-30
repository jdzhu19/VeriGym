"""Runtime identity and evidence validation for the frozen v19 provider canary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.memory import build_agent_version, validate_agent_version
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions
from verigym.plugin_api import JsonValue
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.options import validate_plugin_options

from .hwe_agent import OpenHandsHweAgentAdapter
from .hwe_v19 import validate_v19_protocol_receipt
from .hwe_v19_campaign import (
    OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V19_CANARY_SEED,
    validate_v19_canary_contract,
)
from .hwe_v19_protocol import (
    OPENHANDS_V19_CONTENT_RECOVERY_BUDGET,
    OPENHANDS_V19_MAX_CONTEXT_TOKENS,
    OPENHANDS_V19_MAX_OUTPUT_TOKENS,
    OPENHANDS_V19_MAX_PROVIDER_CALLS,
    OPENHANDS_V19_MAX_PROVIDER_TOKENS,
    OPENHANDS_V19_TOOL_CHOICE_POLICY,
)

OPENHANDS_V19_CANARY_BASE_URL_ENV = "VERIGYM_DEEPSEEK_API_BASE_URL"
OPENHANDS_V19_CANARY_API_KEY_ENV = "VERIGYM_DEEPSEEK_API_KEY"
OPENHANDS_V19_CANARY_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V19_PROVIDER_CANARY_V1"
OPENHANDS_V19_CANARY_MODEL = "openai/deepseek-v4-flash"
OPENHANDS_V19_CANARY_MODEL_IDENTITY = "deepseek-v4-flash"
OPENHANDS_V19_CANARY_SDK_VERSION = "1.42.1"
OPENHANDS_V19_CANARY_LITELLM_VERSION = "1.93.0"
OPENHANDS_V19_CANARY_TIKTOKEN_VERSION = "0.7.0"
OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION = "4.57.6"

_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"


def build_v19_canary_agent_version(
    *,
    contract: Mapping[str, Any],
    source_commit: str,
    image_locks: Mapping[str, Any],
) -> AgentVersionManifest:
    """Bind the v19 agent to the merged source, static contract, and two images."""

    sealed = validate_v19_canary_contract(contract)
    if len(source_commit) != 40 or any(char not in "0123456789abcdef" for char in source_commit):
        raise ValueError("OpenHands v19 canary requires a full merged Git SHA")
    task_ids = [str(item["task_id"]) for item in sealed["schedule"]]
    if set(image_locks) != set(task_ids):
        raise ValueError("OpenHands v19 canary requires exactly its two image locks")

    image_hashes: dict[str, str] = {}
    lock_hashes: dict[str, str] = {}
    for task_id in task_ids:
        lock = image_locks[task_id]
        binding = sealed["task_bindings"][task_id]
        if (
            getattr(lock, "task_id", None) != task_id
            or getattr(lock, "task_hash", None) != binding["task_hash"]
            or getattr(lock, "source_hash", None) != binding["source_hash"]
            or getattr(lock, "lock_hash", None) != binding["image_lock_hash"]
            or getattr(lock, "derived_agent_image_id", None) != binding["agent_image"]
            or getattr(lock, "verifier_base_image_id", None) != binding["verifier_image"]
            or getattr(lock, "runtime_network", None) != "none"
            or getattr(lock, "security_scan_passed", None) is not True
            or getattr(lock, "hidden_assets_present", None) is not False
            or getattr(lock, "reference_patch_present", None) is not False
            or getattr(lock, "provider_credentials_present", None) is not False
            or getattr(lock, "verifier_payload_present", None) is not False
        ):
            raise ValueError("OpenHands v19 canary image-lock binding changed")
        suffix = task_id.rsplit("-", 1)[-1]
        lock_hashes[task_id] = str(binding["image_lock_hash"])
        image_hashes[f"pr{suffix}-agent"] = str(binding["agent_image"])[7:]
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
        agent_version_id=OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
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
                "canary_contract_hash": sealed["contract_hash"],
                "openhands_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
                "litellm_version": OPENHANDS_V19_CANARY_LITELLM_VERSION,
                "tiktoken_version": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
                "collection_profile_id": "hwe_production_native_shell_v2",
                "tool_contract_id": "hwe_native_shell_v2",
                "tool_choice_policy": OPENHANDS_V19_TOOL_CHOICE_POLICY,
                "ordinary_tool_choice": "required",
                "content_recovery_budget": OPENHANDS_V19_CONTENT_RECOVERY_BUDGET,
                "max_provider_calls": OPENHANDS_V19_MAX_PROVIDER_CALLS,
                "max_provider_tokens": OPENHANDS_V19_MAX_PROVIDER_TOKENS,
                "max_context_tokens": OPENHANDS_V19_MAX_CONTEXT_TOKENS,
                "max_output_tokens": OPENHANDS_V19_MAX_OUTPUT_TOKENS,
                "provider_call_accounting": "conversation_agent_attempt_counter_v2",
                "provider_token_accounting": "post_response_pre_dispatch_v19",
                "task_image_lock_hashes": lock_hashes,
                "seed": OPENHANDS_V19_CANARY_SEED,
                "agent_runtime_network": "none",
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


def build_v19_canary_agent_options(
    *, seed: int, agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Build the exact one-episode, no-retry v19 OpenHands options."""

    version = validate_agent_version(agent_version)
    if (
        seed != OPENHANDS_V19_CANARY_SEED
        or version.agent_version_id != OPENHANDS_V19_CANARY_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != OPENHANDS_V19_CANARY_MODEL
    ):
        raise ValueError("OpenHands v19 canary options require the frozen identity")
    return validate_plugin_options(
        {
            "model_id": OPENHANDS_V19_CANARY_MODEL,
            "base_url_env": OPENHANDS_V19_CANARY_BASE_URL_ENV,
            "api_key_env": OPENHANDS_V19_CANARY_API_KEY_ENV,
            "max_iterations": OPENHANDS_V19_MAX_PROVIDER_CALLS,
            "max_provider_tokens": OPENHANDS_V19_MAX_PROVIDER_TOKENS,
            "max_process_time_s": 3_600,
            "max_output_tokens": OPENHANDS_V19_MAX_OUTPUT_TOKENS,
            "max_context_tokens": OPENHANDS_V19_MAX_CONTEXT_TOKENS,
            "seed": seed,
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
            "tool_choice_policy": OPENHANDS_V19_TOOL_CHOICE_POLICY,
        }
    )


def validate_v19_canary_runtime_evidence(
    *,
    broker: Mapping[str, Any],
    summary: Mapping[str, Any],
    accounting: ExternalAgentAccounting,
    protocol_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the protocol/accounting/broker identity before SFT admission."""

    protocol = validate_v19_protocol_receipt(protocol_receipt)
    if (
        summary.get("tool_choice_policy") != OPENHANDS_V19_TOOL_CHOICE_POLICY
        or summary.get("v19_protocol_receipt_hash") != protocol["receipt_hash"]
        or summary.get("provider_call_budget") != OPENHANDS_V19_MAX_PROVIDER_CALLS
        or summary.get("provider_call_count") != protocol["provider_call_count"]
        or summary.get("provider_input_tokens") != protocol["provider_input_tokens"]
        or summary.get("provider_output_tokens") != protocol["provider_output_tokens"]
        or summary.get("provider_total_tokens") != protocol["provider_total_tokens"]
        or summary.get("required_tool_request_count") != protocol["required_tool_request_count"]
        or summary.get("canonical_tool_response_count") != protocol["canonical_tool_response_count"]
        or summary.get("content_only_response_count") != protocol["content_only_response_count"]
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
        raise ValueError("OpenHands v19 canary runtime evidence changed")
    return protocol


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V19_CANARY_")] + [
    "build_v19_canary_agent_options",
    "build_v19_canary_agent_version",
    "validate_v19_canary_runtime_evidence",
]
