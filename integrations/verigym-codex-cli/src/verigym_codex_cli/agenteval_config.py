"""Frozen settings for the scoring-only Codex CLI AgentEval adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from verigym.plugin_api import JsonValue

from .capabilities import CapabilityReport
from .config import CodexSettings, readonly_agent_settings
from .util import stable_hash

AGENTEVAL_PROMPT_INSTRUCTIONS = (
    "Use only repository-relative paths and copy editable paths verbatim from editable_globs.",
    "Use exactly one MCP tool per turn and no built-in tools.",
    "Start with a shallow list_files view and use bounded read_file views for large files.",
    "Read visible task files before editing.",
    "Use only the typed apply_patch action with canonical unified-diff paths and hunks.",
    "If apply_patch returns a recoverable patch category, refresh exact lines and correct it.",
    "For an empty editable file, add content with a numbered @@ -0,0 +1,count @@ hunk.",
    "After every successful patch, compile the current revision again before relying on it.",
    "When PPA is available, call it at least once for the latest compiled revision.",
    "Treat 40 tool calls, 20 patch calls, and 12 exploratory file calls as hard limits.",
    "Track broker elapsed_wall_time_s and remaining_wall_time_s after every tool response.",
    "Reserve the final 90 seconds for patch completion, compile/PPA, diff, and typed finish.",
    "When finalization_required is true, use only next_allowed_actions and finalize immediately.",
    "Before finishing, inspect the latest diff and call the typed finish action exactly once.",
    "Never end the turn with assistant text before typed finish; typed finish is the only "
    "accepted completion.",
    "Do not access shell, network, host files, hidden assets, or reference solutions.",
)
AGENTEVAL_PROMPT_HASH = stable_hash(
    {
        "prompt_contract_id": "repository_action_v2_prompt_v6",
        "prompt_contract_version": "6.0.0",
        "instructions": AGENTEVAL_PROMPT_INSTRUCTIONS,
        "workspace_path_format": "editable_globs_verbatim_repository_relative_only",
        "budget_visibility": "task_process_static_and_dynamic_wall_time_v1",
        "finalization_reserve_s": 90,
        "max_exploratory_calls": 12,
        "conditional_compile": True,
        "conditional_ppa": True,
    }
)
AGENTEVAL_TOOL_POLICY_FINGERPRINT = stable_hash(
    {
        "availability": "verigym_direct_allowlisted_mcp_broker_attested_v5",
        "codex_apps_disabled": True,
        "state_machine": "repository_action_state_machine_v3",
        "tools": [
            "list_files",
            "read_file",
            "apply_patch",
            "run_public_test",
            "inspect_diff",
            "finish",
        ],
        "terminal_path_violations": True,
        "malformed_patch_recoverable": True,
        "recoverable_patch_categories": [
            "patch_body",
            "patch_context",
            "patch_count",
            "patch_empty",
            "patch_format",
            "patch_header",
            "patch_range",
            "patch_rename",
        ],
        "terminal_path_categories": [
            "absolute",
            "hardlink",
            "hidden_or_protected",
            "outside_editable",
            "readonly",
            "symlink",
            "traversal",
            "unspecified",
        ],
        "terminal_tool_name": "allowlisted_only",
        "wall_time_state": "rounded_elapsed_and_remaining_without_deadline",
        "broker_finalization_guard": "reserve_90s_or_12_exploratory_calls_v1",
        "scoring_event_contract": "broker_sequence_attested_mcp_with_optional_final_message_v3",
        "broker_tool_sequence": "exact_completed_event_sequence_v1",
        "mcp_server_label": "bounded_advisory_category_only_v1",
        "mcp_tool_exposure": "direct_only_by_omitting_deferred_v1",
        "accepted_finish_authority": "broker_call_index_v1",
        "scoring_event_failure_categories": [
            "blank_line",
            "invalid_event",
            "malformed_item",
            "malformed_json",
            "mcp_tool",
            "missing_finish",
            "missing_observation",
            "multiple_post_finish_messages",
            "non_mcp_tool",
            "post_finish_tool",
            "unsupported_event",
            "unsupported_item",
            "tool_sequence_mismatch",
        ],
        "bounded_terminal_failure_subcategory": True,
        "commercial_feedback_failure_subcategories": [
            "agent_feedback_dispatch_internal",
            "agent_feedback_infrastructure",
            "agent_worker_configuration",
            "agent_worker_execution",
            "agent_worker_identity",
            "agent_worker_infrastructure",
            "agent_worker_response",
            "agent_worker_scheduler",
            "agent_worker_start",
            "agent_worker_timeout",
            "mcp_service_rejected",
        ],
    }
)
AGENTEVAL_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54-xhigh-v10"
AGENTEVAL_AGENT_VERSION_HASH = stable_hash(
    {
        "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "adapter": "codex-cli-agenteval-agent",
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "cli_version": "codex-cli 0.147.0",
        "repository_action_protocol": "repository_action.v2",
        "state_machine": "repository_action_state_machine_v3",
        "prompt_hash": AGENTEVAL_PROMPT_HASH,
        "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "tool_availability_policy": "verigym_direct_allowlisted_mcp_broker_attested_v5",
        "event_processing": "broker_sequence_and_finish_index_attested_direct_mcp_v9",
        "scoring_event_contract": ("broker_sequence_attested_mcp_with_optional_final_message_v3"),
        "returned_process_identity": "exactly_one_requested_or_observed_v4",
        "broker_error_contract": "typed_patch_and_sanitized_terminal_path_v3",
        "broker_budget_contract": "rounded_wall_time_static_limits_and_finalization_guard_v2",
        "commercial_feedback_error_contract": "allowlisted_worker_subcategory_v1",
        "empty_file_observation": "bounded_zero_line_view_v1",
        "max_tool_calls": 40,
        "max_patch_calls": 20,
        "max_consecutive_rejected_calls": 3,
        "max_exploratory_calls": 12,
        "finalization_reserve_s": 90,
        "training": False,
    }
)

_EXPECTED_MODEL = "gpt-5.4"
_EXPECTED_REASONING = "xhigh"
_EXPECTED_CLI_VERSION = "codex-cli 0.147.0"
_EXPECTED_EXECUTABLE_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
_PROMPT_CONTRACT_ID = "repository_action_v2_prompt_v6"
_BROKER_LIMITS = (40, 20, 3)
_MAX_EXPLORATORY_CALLS = 12
_FINALIZATION_RESERVE_S = 90
_OPTIONS = {
    "model_id",
    "reasoning_effort",
    "max_process_time_s",
    "max_output_bytes",
    "allow_proxy_environment",
    "expected_cli_version",
    "expected_cli_executable_sha256",
    "expected_capability_fingerprint",
    "expected_prompt_hash",
    "expected_tool_policy_fingerprint",
    "expected_requested_auth_mode",
    "expected_resolved_auth_mode",
    "expected_auth_semantic_id",
    "prompt_contract_id",
    "scoring_agent_version_id",
    "scoring_agent_version_hash",
    "observation_policy_id",
    "observation_policy",
    "action_protocol",
    "action_transport",
    "max_completion_calls",
    "max_response_bytes",
}
_PASSTHROUGH = {
    "model_id",
    "reasoning_effort",
    "max_process_time_s",
    "max_output_bytes",
    "allow_proxy_environment",
    "expected_cli_version",
    "expected_cli_executable_sha256",
    "expected_capability_fingerprint",
    "expected_requested_auth_mode",
    "expected_resolved_auth_mode",
    "expected_auth_semantic_id",
}


@dataclass(frozen=True)
class CodexAgentEvalSettings:
    execution: CodexSettings
    agent_version_id: str
    agent_version_hash: str
    prompt_hash: str
    tool_policy_fingerprint: str
    capability_fingerprint: str
    max_tool_calls: int
    max_patch_calls: int
    max_consecutive_rejected_calls: int
    max_exploratory_calls: int
    finalization_reserve_s: int


def agenteval_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexAgentEvalSettings:
    """Resolve the exact scoring identity without accepting training controls."""

    unknown = sorted(set(options) - _OPTIONS)
    if unknown:
        raise ValueError("unsupported Codex AgentEval options: " + ", ".join(unknown))
    required = {
        "model_id": _EXPECTED_MODEL,
        "reasoning_effort": _EXPECTED_REASONING,
        "expected_cli_version": _EXPECTED_CLI_VERSION,
        "expected_cli_executable_sha256": _EXPECTED_EXECUTABLE_SHA256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_prompt_hash": AGENTEVAL_PROMPT_HASH,
        "expected_tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
    }
    for name, expected in required.items():
        if options.get(name) != expected:
            raise ValueError(f"Codex AgentEval requires exact {name}")
    if capabilities.version_output != _EXPECTED_CLI_VERSION:
        raise ValueError("Codex AgentEval requires Codex CLI 0.147.0")
    if capabilities.executable_sha256 != _EXPECTED_EXECUTABLE_SHA256:
        raise ValueError("Codex AgentEval executable hash differs from the frozen identity")
    prompt_contract = options.get("prompt_contract_id")
    if prompt_contract not in {None, _PROMPT_CONTRACT_ID}:
        raise ValueError("Codex AgentEval prompt contract differs from AgentEval v10")
    for name in (
        "expected_requested_auth_mode",
        "expected_resolved_auth_mode",
        "expected_auth_semantic_id",
    ):
        if not isinstance(options.get(name), str):
            raise ValueError(f"Codex AgentEval requires frozen {name}")
    base = readonly_agent_settings(
        {name: options[name] for name in _PASSTHROUGH if name in options},
        capabilities,
        task_wall_time_s=task_wall_time_s,
    )
    fingerprint = stable_hash(
        {
            "base_configuration_fingerprint": base.configuration_fingerprint,
            "integration_track": "codex_cli_agenteval_scoring",
            "prompt_contract_id": _PROMPT_CONTRACT_ID,
            "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
            "agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
            "prompt_hash": AGENTEVAL_PROMPT_HASH,
            "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
            "capability_fingerprint": capabilities.capability_fingerprint,
            "broker_limits": _BROKER_LIMITS,
            "max_exploratory_calls": _MAX_EXPLORATORY_CALLS,
            "finalization_reserve_s": _FINALIZATION_RESERVE_S,
            "training": False,
        }
    )
    execution = replace(
        base,
        integration_track="codex_cli_agenteval_scoring",
        prompt_contract_id=_PROMPT_CONTRACT_ID,
        tool_availability_policy="verigym_direct_allowlisted_mcp_broker_attested_v5",
        tool_use_policy="repository_action_state_machine_v3",
        configuration_fingerprint=fingerprint,
    )
    return CodexAgentEvalSettings(
        execution=execution,
        agent_version_id=AGENTEVAL_AGENT_VERSION_ID,
        agent_version_hash=AGENTEVAL_AGENT_VERSION_HASH,
        prompt_hash=AGENTEVAL_PROMPT_HASH,
        tool_policy_fingerprint=AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        capability_fingerprint=capabilities.capability_fingerprint,
        max_tool_calls=_BROKER_LIMITS[0],
        max_patch_calls=_BROKER_LIMITS[1],
        max_consecutive_rejected_calls=_BROKER_LIMITS[2],
        max_exploratory_calls=_MAX_EXPLORATORY_CALLS,
        finalization_reserve_s=_FINALIZATION_RESERVE_S,
    )


__all__ = [
    "AGENTEVAL_AGENT_VERSION_HASH",
    "AGENTEVAL_AGENT_VERSION_ID",
    "AGENTEVAL_PROMPT_HASH",
    "AGENTEVAL_PROMPT_INSTRUCTIONS",
    "AGENTEVAL_TOOL_POLICY_FINGERPRINT",
    "CodexAgentEvalSettings",
    "agenteval_settings",
]
