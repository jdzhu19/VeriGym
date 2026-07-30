"""Fail-closed binding between the resolved core policy and the Codex harness."""

from __future__ import annotations

from verigym.plugin_api import AgentContext, PromptPolicyDescriptor

from .config import CodexSettings


def bind_prompt_policy(
    context: AgentContext,
    settings: CodexSettings,
    *,
    versioned_context_allowed: bool,
) -> PromptPolicyDescriptor:
    """Validate the descriptor supplied by ordinary orchestration."""

    policy = context.prompt_policy
    if policy is None or policy.resolver_id != "agent_execution_prompt_policy_v1":
        raise ValueError("Codex CLI harness requires a resolved agent prompt policy")
    if policy.id != settings.prompt_contract_id:
        raise ValueError("Codex CLI prompt contract differs from resolved prompt policy")
    if policy.agent_descriptor_hash is None or policy.task_context_hash is None:
        raise ValueError("Codex CLI resolved prompt policy is incomplete")
    if not versioned_context_allowed and any(
        value is not None
        for value in (
            policy.agent_version_id,
            policy.agent_version_hash,
            policy.memory_pack_hash,
        )
    ):
        raise ValueError("read-only Codex CLI prompt may not carry versioned memory")
    if (
        policy.agent_version_id != settings.agent_version_id
        or policy.agent_version_hash != settings.agent_version_hash
        or policy.memory_pack_hash != settings.memory_pack_hash
    ):
        raise ValueError("Codex CLI versioned prompt identity differs from resolved policy")
    return policy


__all__ = ["bind_prompt_policy"]
