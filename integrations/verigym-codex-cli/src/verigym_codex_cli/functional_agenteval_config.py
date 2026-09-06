"""Frozen settings for the functional multi-turn Codex CLI AgentEval adapter."""

from __future__ import annotations

from collections.abc import Mapping

from verigym.plugin_api import JsonValue

from .agenteval_config import (
    AgentEvalSettingsProfile,
    CodexAgentEvalSettings,
    agenteval_settings,
)
from .capabilities import CapabilityReport
from .util import stable_hash

FUNCTIONAL_AGENTEVAL_PROMPT_INSTRUCTIONS = (
    "Use only repository-relative paths and copy editable paths verbatim from editable_globs.",
    "Use exactly one MCP tool per turn and no built-in tools.",
    "Read the visible task and candidate before editing, then produce a first valid candidate.",
    "Use only typed apply_patch with canonical unified-diff paths and numbered hunks.",
    "Treat compile as public validation: it compiles the candidate and runs the independent "
    "bounded public functional smoke declared by this task.",
    "After every successful patch, rerun compile for that exact current revision.",
    "If public validation fails, use its visible diagnostics to patch the candidate and "
    "revalidate.",
    "When PPA is available, call it only after public validation passes for the latest revision.",
    "Treat 40 tool calls, 20 patch calls, and 12 exploratory file calls as hard limits.",
    "Track broker elapsed_wall_time_s and remaining_wall_time_s after every tool response.",
    "Reserve the final 90 seconds for repair, validation/PPA, diff, and typed finish.",
    "When finalization_required is true, use only next_allowed_actions and finalize immediately.",
    "Before finishing, inspect the latest diff and call typed finish exactly once.",
    "Never end with assistant text before typed finish; typed finish is the only completion.",
    "Do not access shell, network, host files, hidden assets, or reference solutions.",
)
FUNCTIONAL_AGENTEVAL_PROMPT_HASH = stable_hash(
    {
        "prompt_contract_id": "repository_action_v2_prompt_v7",
        "prompt_contract_version": "7.0.0",
        "instructions": FUNCTIONAL_AGENTEVAL_PROMPT_INSTRUCTIONS,
        "public_validation": "compile_plus_independent_functional_smoke_v1",
        "repair_loop": "failed_public_validation_patch_revalidate_v1",
        "workspace_path_format": "editable_globs_verbatim_repository_relative_only",
        "budget_visibility": "task_process_static_and_dynamic_wall_time_v1",
        "finalization_reserve_s": 90,
        "max_exploratory_calls": 12,
    }
)
FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT = stable_hash(
    {
        "availability": "verigym_direct_allowlisted_mcp_broker_attested_v5",
        "state_machine": "repository_action_state_machine_v3",
        "tools": [
            "list_files",
            "read_file",
            "apply_patch",
            "run_public_test",
            "inspect_diff",
            "finish",
        ],
        "public_validation": "compile_plus_independent_functional_smoke_v1",
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
        "wall_time_state": "rounded_elapsed_and_remaining_without_deadline",
        "broker_finalization_guard": "reserve_90s_or_12_exploratory_calls_v1",
        "scoring_event_contract": "broker_sequence_attested_mcp_with_optional_final_message_v3",
    }
)
FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54mini-medium-functional-v1"
FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH = stable_hash(
    {
        "agent_version_id": FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID,
        "adapter": "codex-cli-functional-agenteval-agent",
        "adapter_version": "1.0.0",
        "model_id": "gpt-5.4-mini",
        "reasoning_effort": "medium",
        "cli_version": "codex-cli 0.147.0",
        "repository_action_protocol": "repository_action.v2",
        "state_machine": "repository_action_state_machine_v3",
        "prompt_hash": FUNCTIONAL_AGENTEVAL_PROMPT_HASH,
        "tool_policy_fingerprint": FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "public_validation": "compile_plus_independent_functional_smoke_v1",
        "hidden_verifier_execution": "once_after_typed_finish",
        "max_tool_calls": 40,
        "max_patch_calls": 20,
        "max_consecutive_rejected_calls": 3,
        "max_exploratory_calls": 12,
        "finalization_reserve_s": 90,
        "training": False,
    }
)
FUNCTIONAL_AGENTEVAL_PROFILE = AgentEvalSettingsProfile(
    model_id="gpt-5.4-mini",
    reasoning_effort="medium",
    cli_version="codex-cli 0.147.0",
    executable_sha256="134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477",
    prompt_contract_id="repository_action_v2_prompt_v7",
    prompt_hash=FUNCTIONAL_AGENTEVAL_PROMPT_HASH,
    tool_policy_fingerprint=FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    agent_version_id=FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID,
    agent_version_hash=FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH,
)


def functional_agenteval_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexAgentEvalSettings:
    """Resolve the exact mini/medium functional AgentEval identity."""

    return agenteval_settings(
        options,
        capabilities,
        task_wall_time_s=task_wall_time_s,
        profile=FUNCTIONAL_AGENTEVAL_PROFILE,
    )


__all__ = [
    "FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH",
    "FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID",
    "FUNCTIONAL_AGENTEVAL_PROFILE",
    "FUNCTIONAL_AGENTEVAL_PROMPT_HASH",
    "FUNCTIONAL_AGENTEVAL_PROMPT_INSTRUCTIONS",
    "FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT",
    "functional_agenteval_settings",
]
