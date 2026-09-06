"""Frozen Codex CLI functional-v3 adapters."""

from __future__ import annotations

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentDescriptor,
    AgentPromptPolicySpec,
)
from verigym.schemas.action_protocol import RepositoryActionProtocolSpec

from .agenteval_agent import CodexCliAgentEvalAdapter
from .functional_v3_agenteval_config import (
    FUNCTIONAL_V3_HIGH_IDENTITY,
    FUNCTIONAL_V3_LOW_IDENTITY,
    FUNCTIONAL_V3_MEDIUM_IDENTITY,
    FUNCTIONAL_V3_MINI_MEDIUM_IDENTITY,
    FUNCTIONAL_V3_PROMPT_INSTRUCTIONS,
    functional_v3_high_settings,
    functional_v3_low_settings,
    functional_v3_medium_settings,
    functional_v3_mini_medium_settings,
)


def _descriptor(name: str) -> AgentDescriptor:
    return AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name=name,
        version="3.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="openai-codex-cli",
        capabilities=[
            "agent_eval",
            "codex_native_patch",
            "external_coding_agent",
            "functional_public_feedback",
            "machine_readable_events",
            "multiturn_repair_evidence",
            "recoverable_workspace_invalid_request",
            "runtime_mcp_tools",
            "repository_action.v2",
            "scoring_only",
            "single_external_episode",
        ],
    )


class _CodexCliFunctionalV3AgentEvalAdapter(CodexCliAgentEvalAdapter):
    action_protocol_spec = RepositoryActionProtocolSpec(
        prompt_contract_id="repository_action_v2_prompt_v8",
        state_machine_id="repository_action_state_machine_v3",
    )
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="repository_action_v2_prompt_v8",
        prompt_contract_version="8.0.0",
        task_context_policy="revision_bound_functional_agent_feedback_v3",
        base_instruction_policy="generated_repository_action_registry_v8",
        content_visibility_policy="visible_assets_and_public_functional_feedback_v2",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    prompt_instructions = FUNCTIONAL_V3_PROMPT_INSTRUCTIONS
    required_prompt_contract_id = "repository_action_v2_prompt_v8"


class CodexCliFunctionalV3LowAgentEvalAdapter(_CodexCliFunctionalV3AgentEvalAdapter):
    descriptor = _descriptor(FUNCTIONAL_V3_LOW_IDENTITY.agent_name)
    settings_resolver = staticmethod(functional_v3_low_settings)


class CodexCliFunctionalV3MediumAgentEvalAdapter(_CodexCliFunctionalV3AgentEvalAdapter):
    descriptor = _descriptor(FUNCTIONAL_V3_MEDIUM_IDENTITY.agent_name)
    settings_resolver = staticmethod(functional_v3_medium_settings)


class CodexCliFunctionalV3MiniMediumAgentEvalAdapter(_CodexCliFunctionalV3AgentEvalAdapter):
    descriptor = _descriptor(FUNCTIONAL_V3_MINI_MEDIUM_IDENTITY.agent_name)
    settings_resolver = staticmethod(functional_v3_mini_medium_settings)


class CodexCliFunctionalV3HighAgentEvalAdapter(_CodexCliFunctionalV3AgentEvalAdapter):
    descriptor = _descriptor(FUNCTIONAL_V3_HIGH_IDENTITY.agent_name)
    settings_resolver = staticmethod(functional_v3_high_settings)


__all__ = [
    "CodexCliFunctionalV3HighAgentEvalAdapter",
    "CodexCliFunctionalV3LowAgentEvalAdapter",
    "CodexCliFunctionalV3MediumAgentEvalAdapter",
    "CodexCliFunctionalV3MiniMediumAgentEvalAdapter",
]
