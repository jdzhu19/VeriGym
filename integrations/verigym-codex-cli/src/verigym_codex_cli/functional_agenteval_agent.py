"""Functional multi-turn Codex CLI AgentEval adapter."""

from __future__ import annotations

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentDescriptor,
    AgentPromptPolicySpec,
)
from verigym.schemas.action_protocol import RepositoryActionProtocolSpec

from .agenteval_agent import CodexCliAgentEvalAdapter
from .functional_agenteval_config import (
    FUNCTIONAL_AGENTEVAL_PROMPT_INSTRUCTIONS,
    functional_agenteval_settings,
)


class CodexCliFunctionalAgentEvalAdapter(CodexCliAgentEvalAdapter):
    """Run one gpt-5.4-mini/medium functional-feedback scoring episode."""

    action_protocol_spec = RepositoryActionProtocolSpec(
        prompt_contract_id="repository_action_v2_prompt_v7",
        state_machine_id="repository_action_state_machine_v3",
    )
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="repository_action_v2_prompt_v7",
        prompt_contract_version="7.0.0",
        task_context_policy="revision_bound_functional_agent_feedback_v1",
        base_instruction_policy="generated_repository_action_registry_v7",
        content_visibility_policy="visible_assets_and_public_functional_feedback_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="codex-cli-functional-agenteval-agent",
        version="1.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="openai-codex-cli",
        capabilities=[
            "agent_eval",
            "external_coding_agent",
            "functional_public_feedback",
            "machine_readable_events",
            "multiturn_repair_evidence",
            "runtime_mcp_tools",
            "repository_action.v2",
            "scoring_only",
            "single_external_episode",
        ],
    )
    settings_resolver = staticmethod(functional_agenteval_settings)
    prompt_instructions = FUNCTIONAL_AGENTEVAL_PROMPT_INSTRUCTIONS
    required_prompt_contract_id = "repository_action_v2_prompt_v7"


__all__ = ["CodexCliFunctionalAgentEvalAdapter"]
