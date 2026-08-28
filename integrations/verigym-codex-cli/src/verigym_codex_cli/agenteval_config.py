"""Frozen settings for the scoring-only Codex CLI AgentEval adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from verigym.plugin_api import JsonValue

from .capabilities import CapabilityReport
from .config import CodexSettings, readonly_agent_settings
from .util import stable_hash

AGENTEVAL_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54-xhigh-v1"
AGENTEVAL_AGENT_VERSION_HASH = stable_hash(
    {
        "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "adapter": "codex-cli-agenteval-agent",
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "cli_version": "codex-cli 0.147.0",
        "repository_action_protocol": "repository_action.v2",
        "state_machine": "repository_action_state_machine_v3",
        "tool_availability_policy": "verigym_required_allowlisted_mcp_only_v1",
        "max_tool_calls": 40,
        "max_patch_calls": 20,
        "max_consecutive_rejected_calls": 3,
        "training": False,
    }
)

_EXPECTED_MODEL = "gpt-5.4"
_EXPECTED_REASONING = "xhigh"
_EXPECTED_CLI_VERSION = "codex-cli 0.147.0"
_EXPECTED_EXECUTABLE_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
_PROMPT_CONTRACT_ID = "repository_action_v2_prompt_v3"
_BROKER_LIMITS = (40, 20, 3)
_OPTIONS = {
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
    max_tool_calls: int
    max_patch_calls: int
    max_consecutive_rejected_calls: int


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
        raise ValueError("Codex AgentEval prompt contract differs from AgentEval v1")
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
            "broker_limits": _BROKER_LIMITS,
            "training": False,
        }
    )
    execution = replace(
        base,
        integration_track="codex_cli_agenteval_scoring",
        prompt_contract_id=_PROMPT_CONTRACT_ID,
        tool_availability_policy="verigym_required_allowlisted_mcp_only_v1",
        tool_use_policy="repository_action_state_machine_v3",
        configuration_fingerprint=fingerprint,
    )
    return CodexAgentEvalSettings(
        execution=execution,
        agent_version_id=AGENTEVAL_AGENT_VERSION_ID,
        agent_version_hash=AGENTEVAL_AGENT_VERSION_HASH,
        max_tool_calls=_BROKER_LIMITS[0],
        max_patch_calls=_BROKER_LIMITS[1],
        max_consecutive_rejected_calls=_BROKER_LIMITS[2],
    )


__all__ = [
    "AGENTEVAL_AGENT_VERSION_HASH",
    "AGENTEVAL_AGENT_VERSION_ID",
    "CodexAgentEvalSettings",
    "agenteval_settings",
]
