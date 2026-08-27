"""Frozen identity and outcome policy for one positive OpenHands HWE qualification."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.memory import build_agent_version, validate_agent_version
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest

from ._recovery import OPENHANDS_FORMAT_RECOVERY_BUDGET, OPENHANDS_FORMAT_RECOVERY_POLICY
from .hwe_agent import OpenHandsHweAgentAdapter
from .hwe_responses_recovery_diagnostic import OPENHANDS_RESPONSES_RECOVERY_POLICY

OPENHANDS_POSITIVE_QUALIFICATION_FORMAT = (
    "verigym_openhands_hwe_positive_trajectory_qualification_v1"
)
OPENHANDS_POSITIVE_QUALIFICATION_REPORT_FORMAT = (
    "verigym_openhands_hwe_positive_trajectory_qualification_report_v1"
)
OPENHANDS_POSITIVE_QUALIFICATION_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"
OPENHANDS_POSITIVE_QUALIFICATION_CAMPAIGN_ID = "openhands-hwe-positive-trajectory-qualification-v1"
OPENHANDS_POSITIVE_QUALIFICATION_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-positive-trajectory-qualification-v1"
)
OPENHANDS_POSITIVE_QUALIFICATION_OPT_IN_ENV = (
    "VERIGYM_RUN_OPENHANDS_HWE_POSITIVE_TRAJECTORY_QUALIFICATION_V1"
)
OPENHANDS_POSITIVE_QUALIFICATION_MODEL = "openai/deepseek-v4-flash"
OPENHANDS_POSITIVE_QUALIFICATION_MODEL_IDENTITY = "deepseek-v4-flash"
OPENHANDS_POSITIVE_QUALIFICATION_SDK_VERSION = "1.42.1"
OPENHANDS_POSITIVE_QUALIFICATION_LITELLM_VERSION = "1.93.0"
OPENHANDS_POSITIVE_QUALIFICATION_TIKTOKEN_VERSION = "0.7.0"
OPENHANDS_POSITIVE_QUALIFICATION_BASE_URL_ENV = "VERIGYM_DEEPSEEK_API_BASE_URL"
OPENHANDS_POSITIVE_QUALIFICATION_API_KEY_ENV = "VERIGYM_DEEPSEEK_API_KEY"
OPENHANDS_POSITIVE_QUALIFICATION_SEED = 484
OPENHANDS_POSITIVE_QUALIFICATION_MAX_ITERATIONS = 200
OPENHANDS_POSITIVE_QUALIFICATION_MAX_OUTPUT_TOKENS = 2_048
OPENHANDS_POSITIVE_QUALIFICATION_MAX_CONTEXT_TOKENS = 65_536

_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"


def build_positive_qualification_agent_version(
    *, source_commit: str, image_lock: Any
) -> AgentVersionManifest:
    """Freeze the current no-retry collection policy for CVA6 PR-2944."""

    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise ValueError("OpenHands positive qualification requires a full Git SHA")
    if getattr(image_lock, "task_id", None) != OPENHANDS_POSITIVE_QUALIFICATION_TASK:
        raise ValueError("OpenHands positive qualification image-lock task changed")
    lock_hash = str(getattr(image_lock, "lock_hash", ""))
    agent_image = str(getattr(image_lock, "derived_agent_image_id", ""))
    verifier_image = str(getattr(image_lock, "verifier_base_image_id", ""))
    if (
        len(lock_hash) != 64
        or not agent_image.startswith("sha256:")
        or not verifier_image.startswith("sha256:")
    ):
        raise ValueError("OpenHands positive qualification image lock is incomplete")

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
        agent_version_id=OPENHANDS_POSITIVE_QUALIFICATION_AGENT_VERSION_ID,
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=False,
        base_agent_id=agent.descriptor.name,
        agent_descriptor_hash=content_hash(agent.descriptor),
        model_id=OPENHANDS_POSITIVE_QUALIFICATION_MODEL,
        reasoning_effort="thinking-disabled",
        auth_semantic_id="deepseek.env-bearer.v1",
        runtime_identity_hash=content_hash(
            {
                "python_executable_sha256": hash_bytes(Path(sys.executable).read_bytes()),
                "openhands_sdk_version": OPENHANDS_POSITIVE_QUALIFICATION_SDK_VERSION,
                "litellm_version": OPENHANDS_POSITIVE_QUALIFICATION_LITELLM_VERSION,
                "tiktoken_version": OPENHANDS_POSITIVE_QUALIFICATION_TIKTOKEN_VERSION,
                "qualification_profile_id": OPENHANDS_POSITIVE_QUALIFICATION_FORMAT,
                "collection_profile_id": "hwe_production_native_shell_v2",
                "tool_contract_id": "hwe_native_shell_v2",
                "tool_choice_policy": OPENHANDS_RESPONSES_RECOVERY_POLICY,
                "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
                "same_session_recovery": True,
                "whole_episode_retries": 0,
                "recovery_transport": "responses_api",
                "termination_authority": "broker_typed_finish",
                "task_image_lock_hash": lock_hash,
                "agent_runtime_network": "none",
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
        image_hashes={
            "task-agent": agent_image.removeprefix("sha256:"),
            "task-verifier": verifier_image.removeprefix("sha256:"),
        },
        training_dataset_hash=None,
        reward_schema_hash=None,
        reward_profile_hash=None,
        memory_builder_identity_hash=None,
        memory_pack_hash=None,
        model_weights_modified=False,
    )
    return validate_agent_version(version)


def classify_positive_qualification(
    *,
    infrastructure_valid: bool,
    evidence_complete: bool,
    tool_choice_bound: bool,
    typed_finish_observed: bool,
    ordinary_verifier_resolved: bool,
    trajectory_exported: bool,
) -> tuple[str, bool]:
    """Require complete runtime evidence, verifier pass, and one eligible trajectory."""

    if not infrastructure_valid:
        return "infrastructure_invalid", False
    if not evidence_complete or not tool_choice_bound:
        return "runtime_evidence_invalid", False
    if not typed_finish_observed:
        return "model_did_not_finish", False
    if not ordinary_verifier_resolved:
        return "verifier_rejected", False
    if not trajectory_exported:
        return "eligible_trajectory_missing", False
    return "verifier_passed_trajectory_exported", True


def seal_positive_qualification_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal one sanitized positive-qualification record."""

    base = {key: item for key, item in value.items() if key != "report_hash"}
    return {**base, "report_hash": content_hash(base)}


__all__ = [
    "OPENHANDS_POSITIVE_QUALIFICATION_AGENT_VERSION_ID",
    "OPENHANDS_POSITIVE_QUALIFICATION_API_KEY_ENV",
    "OPENHANDS_POSITIVE_QUALIFICATION_BASE_URL_ENV",
    "OPENHANDS_POSITIVE_QUALIFICATION_CAMPAIGN_ID",
    "OPENHANDS_POSITIVE_QUALIFICATION_FORMAT",
    "OPENHANDS_POSITIVE_QUALIFICATION_LITELLM_VERSION",
    "OPENHANDS_POSITIVE_QUALIFICATION_MAX_CONTEXT_TOKENS",
    "OPENHANDS_POSITIVE_QUALIFICATION_MAX_ITERATIONS",
    "OPENHANDS_POSITIVE_QUALIFICATION_MAX_OUTPUT_TOKENS",
    "OPENHANDS_POSITIVE_QUALIFICATION_MODEL",
    "OPENHANDS_POSITIVE_QUALIFICATION_MODEL_IDENTITY",
    "OPENHANDS_POSITIVE_QUALIFICATION_OPT_IN_ENV",
    "OPENHANDS_POSITIVE_QUALIFICATION_REPORT_FORMAT",
    "OPENHANDS_POSITIVE_QUALIFICATION_SDK_VERSION",
    "OPENHANDS_POSITIVE_QUALIFICATION_SEED",
    "OPENHANDS_POSITIVE_QUALIFICATION_TASK",
    "OPENHANDS_POSITIVE_QUALIFICATION_TIKTOKEN_VERSION",
    "build_positive_qualification_agent_version",
    "classify_positive_qualification",
    "seal_positive_qualification_report",
]
