"""Frozen low, medium, and high Codex CLI functional-v2 adapters."""

from __future__ import annotations

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentDescriptor,
    AgentPromptPolicySpec,
)
from verigym.schemas.action_protocol import RepositoryActionProtocolSpec

from .agenteval_agent import CodexCliAgentEvalAdapter
from .functional_v2_agenteval_config import (
    FUNCTIONAL_V2_HIGH_IDENTITY,
    FUNCTIONAL_V2_LOW_IDENTITY,
    FUNCTIONAL_V2_MEDIUM_IDENTITY,
    FUNCTIONAL_V2_PROMPT_INSTRUCTIONS,
    functional_v2_high_settings,
    functional_v2_low_settings,
    functional_v2_medium_settings,
)


def _descriptor(name: str) -> AgentDescriptor:
    return AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name=name,
        version="2.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="openai-codex-cli",
        capabilities=[
            "agent_eval",
            "codex_native_patch",
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


class _CodexCliFunctionalV2AgentEvalAdapter(CodexCliAgentEvalAdapter):
    action_protocol_spec = RepositoryActionProtocolSpec(
        prompt_contract_id="repository_action_v2_prompt_v8",
        state_machine_id="repository_action_state_machine_v3",
    )
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="repository_action_v2_prompt_v8",
        prompt_contract_version="8.0.0",
        task_context_policy="revision_bound_functional_agent_feedback_v2",
        base_instruction_policy="generated_repository_action_registry_v8",
        content_visibility_policy="visible_assets_and_public_functional_feedback_v2",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    prompt_instructions = FUNCTIONAL_V2_PROMPT_INSTRUCTIONS
    required_prompt_contract_id = "repository_action_v2_prompt_v8"


class CodexCliFunctionalV2LowAgentEvalAdapter(_CodexCliFunctionalV2AgentEvalAdapter):
    """Run one gpt-5.4-mini/low functional-v2 scoring episode."""

    descriptor = _descriptor(FUNCTIONAL_V2_LOW_IDENTITY.agent_name)
    settings_resolver = staticmethod(functional_v2_low_settings)


class CodexCliFunctionalV2MediumAgentEvalAdapter(_CodexCliFunctionalV2AgentEvalAdapter):
    """Run one gpt-5.4-mini/high functional-v2 scoring episode."""

    descriptor = _descriptor(FUNCTIONAL_V2_MEDIUM_IDENTITY.agent_name)
    settings_resolver = staticmethod(functional_v2_medium_settings)


class CodexCliFunctionalV2HighAgentEvalAdapter(_CodexCliFunctionalV2AgentEvalAdapter):
    """Run one gpt-5.4/xhigh functional-v2 scoring episode."""

    descriptor = _descriptor(FUNCTIONAL_V2_HIGH_IDENTITY.agent_name)
    settings_resolver = staticmethod(functional_v2_high_settings)


__all__ = [
    "CodexCliFunctionalV2HighAgentEvalAdapter",
    "CodexCliFunctionalV2LowAgentEvalAdapter",
    "CodexCliFunctionalV2MediumAgentEvalAdapter",
]
