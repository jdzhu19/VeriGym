"""Frozen identity and outcome policy for the OpenHands required-tool diagnostic."""

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

from ._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
)
from .hwe_agent import OpenHandsHweAgentAdapter

OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_FORMAT = "verigym_openhands_hwe_tool_choice_diagnostic_v4"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_REPORT_FORMAT = (
    "verigym_openhands_hwe_tool_choice_diagnostic_report_v4"
)
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_CAMPAIGN_ID = "openhands-hwe-recovery-forced-finish-diagnostic-v4"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-recovery-forced-finish-diagnostic-v4"
)
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_TOOL_CHOICE_DIAGNOSTIC"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL = "openai/deepseek-v4-flash"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL_IDENTITY = "deepseek-v4-flash"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SDK_VERSION = "1.42.1"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_LITELLM_VERSION = "1.93.0"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TIKTOKEN_VERSION = "0.7.0"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_BASE_URL_ENV = "VERIGYM_DEEPSEEK_API_BASE_URL"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_API_KEY_ENV = "VERIGYM_DEEPSEEK_API_KEY"
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SEED = 484
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_ITERATIONS = 200
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_OUTPUT_TOKENS = 2_048
OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_CONTEXT_TOKENS = 65_536
OPENHANDS_TOOL_CHOICE_POLICY = "recovery_forced_finish"

_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"


def build_tool_choice_diagnostic_agent_version(
    *, source_commit: str, image_lock: Any
) -> AgentVersionManifest:
    """Freeze the exact required-tool policy used for the one-task diagnostic."""

    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise ValueError("OpenHands tool-choice diagnostic requires a full Git SHA")
    if getattr(image_lock, "task_id", None) != OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK:
        raise ValueError("OpenHands tool-choice diagnostic image-lock task changed")
    lock_hash = str(getattr(image_lock, "lock_hash", ""))
    agent_image = str(getattr(image_lock, "derived_agent_image_id", ""))
    verifier_image = str(getattr(image_lock, "verifier_base_image_id", ""))
    if (
        len(lock_hash) != 64
        or not agent_image.startswith("sha256:")
        or not verifier_image.startswith("sha256:")
    ):
        raise ValueError("OpenHands tool-choice diagnostic image lock is incomplete")

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
        agent_version_id=OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_AGENT_VERSION_ID,
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=False,
        base_agent_id=agent.descriptor.name,
        agent_descriptor_hash=content_hash(agent.descriptor),
        model_id=OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL,
        reasoning_effort="thinking-disabled",
        auth_semantic_id="deepseek.env-bearer.v1",
        runtime_identity_hash=content_hash(
            {
                "python_executable_sha256": hash_bytes(Path(sys.executable).read_bytes()),
                "openhands_sdk_version": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SDK_VERSION,
                "litellm_version": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_LITELLM_VERSION,
                "tiktoken_version": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TIKTOKEN_VERSION,
                "diagnostic_profile_id": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_FORMAT,
                "collection_profile_id": "hwe_production_native_shell_v2",
                "tool_contract_id": "hwe_native_shell_v2",
                "tool_choice_policy": OPENHANDS_TOOL_CHOICE_POLICY,
                "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
                "same_session_recovery": True,
                "whole_episode_retries": 0,
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


def classify_tool_choice_diagnostic(
    *,
    infrastructure_valid: bool,
    typed_finish_observed: bool,
    recovery_count: int,
    failure_category: str | None,
) -> tuple[str, bool]:
    """Require the trusted recovery turn to produce broker-authoritative typed finish."""

    if recovery_count not in {0, 1}:
        raise ValueError("OpenHands tool-choice diagnostic count is outside the frozen budget")
    if not infrastructure_valid:
        return "infrastructure_invalid", False
    if typed_finish_observed and recovery_count == 1:
        return "recovery_forced_finish_regression_passed", True
    if typed_finish_observed:
        return "direct_finish_passed_recovery_not_exercised", False
    if failure_category == "openhands_hwe_missing_finish":
        return "recovery_forced_finish_regression_failed", False
    return "model_rejected_before_typed_finish", False


def seal_tool_choice_diagnostic_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal a sanitized required-tool diagnostic report."""

    base = {key: item for key, item in value.items() if key != "report_hash"}
    return {**base, "report_hash": content_hash(base)}


__all__ = [
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_AGENT_VERSION_ID",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_API_KEY_ENV",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_BASE_URL_ENV",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_CAMPAIGN_ID",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_FORMAT",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_LITELLM_VERSION",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_CONTEXT_TOKENS",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_ITERATIONS",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_OUTPUT_TOKENS",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL_IDENTITY",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_OPT_IN_ENV",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_REPORT_FORMAT",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SDK_VERSION",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SEED",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK",
    "OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TIKTOKEN_VERSION",
    "OPENHANDS_TOOL_CHOICE_POLICY",
    "build_tool_choice_diagnostic_agent_version",
    "classify_tool_choice_diagnostic",
    "seal_tool_choice_diagnostic_report",
]
