"""Frozen Codex CLI identities after recoverable workspace-request feedback."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from verigym.plugin_api import JsonValue

from .agenteval_config import (
    AgentEvalSettingsProfile,
    CodexAgentEvalSettings,
    agenteval_settings,
)
from .capabilities import CapabilityReport
from .functional_v2_agenteval_config import (
    FUNCTIONAL_V2_PROMPT_HASH,
    FUNCTIONAL_V2_PROMPT_INSTRUCTIONS,
)
from .util import stable_hash

FUNCTIONAL_V3_PROMPT_HASH = FUNCTIONAL_V2_PROMPT_HASH
FUNCTIONAL_V3_PROMPT_INSTRUCTIONS = FUNCTIONAL_V2_PROMPT_INSTRUCTIONS
FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT = stable_hash(
    {
        "availability": "verigym_direct_allowlisted_mcp_broker_attested_v6",
        "state_machine": "repository_action_state_machine_v3",
        "tools": [
            "list_files",
            "read_file",
            "apply_patch",
            "run_public_test",
            "inspect_diff",
            "finish",
        ],
        "patch_format_profile": "strict_unified_and_codex_native_v1",
        "public_validation": "compile_plus_independent_functional_smoke_v2",
        "repair_evidence": [
            "first_public_validation_passed",
            "public_validation_failures",
            "repair_patches_after_public_validation_failure",
            "public_validation_rechecks_after_repair_patch",
            "public_validation_failed_then_passed",
        ],
        "hidden_verifier_execution": "once_after_typed_finish",
        "terminal_path_violations": True,
        "malformed_patch_recoverable": True,
        "workspace_invalid_request_recoverable": ["file_list_not_directory"],
        "wall_time_state": "rounded_elapsed_and_remaining_without_deadline",
        "broker_finalization_guard": "reserve_90s_or_12_exploratory_calls_v1",
        "scoring_event_contract": "broker_sequence_attested_mcp_with_optional_final_message_v3",
    }
)

_CLI_VERSION = "codex-cli 0.147.0"
_EXECUTABLE_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"


@dataclass(frozen=True)
class FunctionalV3Identity:
    """One immutable model/reasoning identity for the repaired diagnostic."""

    tier: str
    agent_name: str
    agent_version_id: str
    agent_version_hash: str
    model_id: str
    reasoning_effort: str
    settings_profile: AgentEvalSettingsProfile


def _identity(*, tier: str, model_id: str, reasoning_effort: str) -> FunctionalV3Identity:
    agent_name = f"codex-cli-functional-v3-{tier}-agenteval-agent"
    agent_version_id = (
        f"codex-cli-agenteval-{model_id.replace('.', '').replace('-', '')}-"
        f"{reasoning_effort}-functional-v3"
    )
    agent_version_hash = stable_hash(
        {
            "agent_version_id": agent_version_id,
            "adapter": agent_name,
            "adapter_version": "3.0.0",
            "model_id": model_id,
            "reasoning_effort": reasoning_effort,
            "cli_version": _CLI_VERSION,
            "repository_action_protocol": "repository_action.v2",
            "state_machine": "repository_action_state_machine_v3",
            "prompt_hash": FUNCTIONAL_V3_PROMPT_HASH,
            "tool_policy_fingerprint": FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
            "prompt_policy_revision": "revision_bound_functional_agent_feedback_v3",
            "public_validation": "compile_plus_independent_functional_smoke_v2",
            "hidden_verifier_execution": "once_after_typed_finish",
            "max_tool_calls": 40,
            "max_patch_calls": 20,
            "max_consecutive_rejected_calls": 6,
            "max_exploratory_calls": 12,
            "finalization_reserve_s": 90,
            "workspace_invalid_request_recoverable": ["file_list_not_directory"],
            "training": False,
        }
    )
    profile = AgentEvalSettingsProfile(
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        cli_version=_CLI_VERSION,
        executable_sha256=_EXECUTABLE_SHA256,
        prompt_contract_id="repository_action_v2_prompt_v8",
        prompt_hash=FUNCTIONAL_V3_PROMPT_HASH,
        tool_policy_fingerprint=FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
        agent_version_id=agent_version_id,
        agent_version_hash=agent_version_hash,
        broker_limits=(40, 20, 6),
        patch_format_profile="strict_unified_and_codex_native_v1",
    )
    return FunctionalV3Identity(
        tier=tier,
        agent_name=agent_name,
        agent_version_id=agent_version_id,
        agent_version_hash=agent_version_hash,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        settings_profile=profile,
    )


FUNCTIONAL_V3_LOW_IDENTITY = _identity(tier="low", model_id="gpt-5.4-mini", reasoning_effort="low")
FUNCTIONAL_V3_MEDIUM_IDENTITY = _identity(
    tier="medium", model_id="gpt-5.4-mini", reasoning_effort="high"
)
FUNCTIONAL_V3_MINI_MEDIUM_IDENTITY = _identity(
    tier="mini-medium-control",
    model_id="gpt-5.4-mini",
    reasoning_effort="medium",
)
FUNCTIONAL_V3_HIGH_IDENTITY = _identity(tier="high", model_id="gpt-5.4", reasoning_effort="xhigh")
FUNCTIONAL_V3_IDENTITIES = {
    identity.tier: identity
    for identity in (
        FUNCTIONAL_V3_LOW_IDENTITY,
        FUNCTIONAL_V3_MINI_MEDIUM_IDENTITY,
        FUNCTIONAL_V3_MEDIUM_IDENTITY,
        FUNCTIONAL_V3_HIGH_IDENTITY,
    )
}


def _settings(
    tier: str,
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexAgentEvalSettings:
    return agenteval_settings(
        options,
        capabilities,
        task_wall_time_s=task_wall_time_s,
        profile=FUNCTIONAL_V3_IDENTITIES[tier].settings_profile,
    )


def functional_v3_low_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexAgentEvalSettings:
    return _settings("low", options, capabilities, task_wall_time_s=task_wall_time_s)


def functional_v3_medium_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexAgentEvalSettings:
    return _settings("medium", options, capabilities, task_wall_time_s=task_wall_time_s)


def functional_v3_mini_medium_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexAgentEvalSettings:
    return _settings(
        "mini-medium-control",
        options,
        capabilities,
        task_wall_time_s=task_wall_time_s,
    )


def functional_v3_high_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexAgentEvalSettings:
    return _settings("high", options, capabilities, task_wall_time_s=task_wall_time_s)


__all__ = [
    "FUNCTIONAL_V3_HIGH_IDENTITY",
    "FUNCTIONAL_V3_IDENTITIES",
    "FUNCTIONAL_V3_LOW_IDENTITY",
    "FUNCTIONAL_V3_MEDIUM_IDENTITY",
    "FUNCTIONAL_V3_MINI_MEDIUM_IDENTITY",
    "FUNCTIONAL_V3_PROMPT_HASH",
    "FUNCTIONAL_V3_PROMPT_INSTRUCTIONS",
    "FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT",
    "FunctionalV3Identity",
    "functional_v3_high_settings",
    "functional_v3_low_settings",
    "functional_v3_medium_settings",
    "functional_v3_mini_medium_settings",
]
