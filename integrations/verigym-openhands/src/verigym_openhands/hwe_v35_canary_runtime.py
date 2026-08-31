"""Runtime identity for the Codex-free v35 provider canary."""

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
    validate_v19_canary_runtime_evidence,
)
from .hwe_v19_protocol import (
    OPENHANDS_V19_CONTENT_RECOVERY_BUDGET,
    OPENHANDS_V19_MAX_CONTEXT_TOKENS,
    OPENHANDS_V19_MAX_OUTPUT_TOKENS,
    OPENHANDS_V19_MAX_PROVIDER_CALLS,
    OPENHANDS_V19_MAX_PROVIDER_TOKENS,
    OPENHANDS_V19_TOOL_CHOICE_POLICY,
)

OPENHANDS_V35_CANARY_CAMPAIGN_ID = "openhands-hwe-v35-codex-free-required-tool-canary-v1"
OPENHANDS_V35_CANARY_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v35-codex-free-canary-v1"
OPENHANDS_V35_CANARY_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V35_PROVIDER_CANARY_V1"
OPENHANDS_V35_CANARY_SEED = 489
OPENHANDS_V35_CANARY_SAMPLE_INDEX = 5
OPENHANDS_V35_COMMAND_EXECUTION_BACKEND: Literal["episode_container_exec_v1"] = (
    "episode_container_exec_v1"
)

_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"


def build_v35_canary_agent_version(
    *,
    contract: Mapping[str, Any],
    source_commit: str,
    command_image_locks: Mapping[str, Any],
    predecessor_report_hash: str,
    control_plane_contract_hash: str,
) -> AgentVersionManifest:
    """Bind a fresh successor identity to v33 runtime and the sealed v34 stop."""

    if len(source_commit) != 40 or any(char not in "0123456789abcdef" for char in source_commit):
        raise ValueError("OpenHands v35 canary requires a full merged Git SHA")
    for value in (predecessor_report_hash, control_plane_contract_hash):
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("OpenHands v35 predecessor/control identity changed")
    contract_hash = contract.get("contract_hash")
    schedule = contract.get("schedule")
    bindings = contract.get("task_bindings")
    if (
        contract.get("format_id") != "verigym_openhands_hwe_v33_codex_free_canary_contract_v1"
        or contract.get("protocol_profile") != OPENHANDS_V19_TOOL_CHOICE_POLICY
        or not isinstance(contract_hash, str)
        or not isinstance(schedule, list)
        or not isinstance(bindings, Mapping)
    ):
        raise ValueError("OpenHands v35 predecessor contract changed")
    contract_base = dict(contract)
    contract_base.pop("contract_hash", None)
    if content_hash(contract_base) != contract_hash:
        raise ValueError("OpenHands v35 predecessor contract identity changed")
    task_ids = [str(item.get("task_id")) for item in schedule if isinstance(item, Mapping)]
    if len(task_ids) != 2 or set(command_image_locks) != set(task_ids):
        raise ValueError("OpenHands v35 requires exactly its two command-image locks")

    image_hashes: dict[str, str] = {}
    lock_hashes: dict[str, str] = {}
    security_scan_ids: dict[str, str] = {}
    for task_id in task_ids:
        lock = command_image_locks[task_id]
        binding = bindings.get(task_id)
        if not isinstance(binding, Mapping):
            raise ValueError("OpenHands v35 command-image binding is missing")
        if (
            getattr(lock, "task_id", None) != task_id
            or getattr(lock, "task_hash", None) != binding.get("task_hash")
            or getattr(lock, "source_hash", None) != binding.get("source_hash")
            or getattr(lock, "lock_hash", None) != binding.get("command_image_lock_hash")
            or getattr(lock, "derived_command_image_id", None) != binding.get("command_image")
            or getattr(lock, "verifier_base_image_id", None) != binding.get("verifier_image")
            or getattr(lock, "security_scan_id", None) != binding.get("security_scan_id")
            or getattr(lock, "runtime_network", None) != "none"
            or getattr(lock, "security_scan_passed", None) is not True
            or getattr(lock, "codex_present", None) is not False
            or getattr(lock, "provider_credentials_present", None) is not False
            or getattr(lock, "hidden_assets_present", None) is not False
            or getattr(lock, "reference_patch_present", None) is not False
            or getattr(lock, "verifier_payload_present", None) is not False
            or OPENHANDS_V35_COMMAND_EXECUTION_BACKEND
            not in getattr(lock, "supported_execution_backends", ())
        ):
            raise ValueError("OpenHands v35 command-image binding changed")
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
        agent_version_id=OPENHANDS_V35_CANARY_AGENT_VERSION_ID,
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
                "campaign_id": OPENHANDS_V35_CANARY_CAMPAIGN_ID,
                "predecessor_contract_hash": contract_hash,
                "stopped_v34_report_hash": predecessor_report_hash,
                "control_plane_contract_hash": control_plane_contract_hash,
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
                "runtime_role": "credential_free_command_image",
                "command_execution_backend": OPENHANDS_V35_COMMAND_EXECUTION_BACKEND,
                "task_command_image_lock_hashes": lock_hashes,
                "task_security_scan_ids": security_scan_ids,
                "seed": OPENHANDS_V35_CANARY_SEED,
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


def build_v35_canary_agent_options(
    *, seed: int, agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Build the exact one-episode, no-retry v19 protocol options for v35."""

    version = validate_agent_version(agent_version)
    if (
        seed != OPENHANDS_V35_CANARY_SEED
        or version.agent_version_id != OPENHANDS_V35_CANARY_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != OPENHANDS_V19_CANARY_MODEL
    ):
        raise ValueError("OpenHands v35 canary options require the frozen identity")
    return validate_plugin_options(
        {
            "model_id": OPENHANDS_V19_CANARY_MODEL,
            "base_url_env": OPENHANDS_V19_CANARY_BASE_URL_ENV,
            "api_key_env": OPENHANDS_V19_CANARY_API_KEY_ENV,
            "max_iterations": OPENHANDS_V19_MAX_PROVIDER_CALLS,
            "max_provider_billed_units": OPENHANDS_V19_MAX_PROVIDER_TOKENS,
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


def validate_v35_canary_runtime_evidence(
    *,
    broker: Mapping[str, Any],
    summary: Mapping[str, Any],
    accounting: ExternalAgentAccounting,
    protocol_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Retain the exact v19 protocol/accounting validation under the v35 identity."""

    return validate_v19_canary_runtime_evidence(
        broker=broker,
        summary=summary,
        accounting=accounting,
        protocol_receipt=protocol_receipt,
    )


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V35_CANARY_")] + [
    "OPENHANDS_V35_COMMAND_EXECUTION_BACKEND",
    "build_v35_canary_agent_options",
    "build_v35_canary_agent_version",
    "validate_v35_canary_runtime_evidence",
]
