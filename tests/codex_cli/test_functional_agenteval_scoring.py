from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.functional_agenteval_agent import (
    CodexCliFunctionalAgentEvalAdapter,
)
from verigym_codex_cli.functional_agenteval_config import (
    FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH,
    FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID,
    FUNCTIONAL_AGENTEVAL_PROMPT_HASH,
    FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    functional_agenteval_settings,
)

from verigym.prompts.policy import resolve_prompt_policy
from verigym.protocols.repository_action import resolve_repository_action_protocol
from verigym.schemas.common import InteractionMode
from verigym.schemas.task import TaskRef
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite

pytestmark = pytest.mark.codex_cli

_CLI_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"


def test_functional_agent_has_distinct_exact_mini_medium_identity(
    fake_codex: tuple[Path, Path, object],
) -> None:
    del fake_codex
    _identity, discovered = discover_capabilities(force=True)
    capabilities = replace(
        discovered,
        version_output="codex-cli 0.147.0",
        executable_sha256=_CLI_SHA256,
    )
    options = {
        "model_id": "gpt-5.4-mini",
        "reasoning_effort": "medium",
        "expected_cli_version": "codex-cli 0.147.0",
        "expected_cli_executable_sha256": _CLI_SHA256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_prompt_hash": FUNCTIONAL_AGENTEVAL_PROMPT_HASH,
        "expected_tool_policy_fingerprint": FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": "inherited_codex_login",
        "expected_resolved_auth_mode": "inherited_codex_login",
        "expected_auth_semantic_id": "codex.auth.inherited_chatgpt_session.v1",
        "prompt_contract_id": "repository_action_v2_prompt_v7",
        "scoring_agent_version_id": FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH,
    }
    settings = functional_agenteval_settings(options, capabilities, task_wall_time_s=300)

    assert settings.execution.model_id == "gpt-5.4-mini"
    assert settings.execution.effective_reasoning_effort == "medium"
    assert settings.agent_version_id == FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID
    assert CodexCliFunctionalAgentEvalAdapter.descriptor.name == (
        "codex-cli-functional-agenteval-agent"
    )
    assert CodexCliFunctionalAgentEvalAdapter.descriptor.version == "1.0.0"
    assert CodexCliFunctionalAgentEvalAdapter.prompt_policy_spec.prompt_contract_id == (
        "repository_action_v2_prompt_v7"
    )


def test_functional_agent_frozen_fingerprints_are_literal() -> None:
    assert FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID == (
        "codex-cli-agenteval-gpt54mini-medium-functional-v1"
    )
    assert FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH == (
        "0258bfa172121f0010e023e30790efe8042d242310c30c8409374cb14e74bc79"
    )
    assert FUNCTIONAL_AGENTEVAL_PROMPT_HASH == (
        "c01db084d23d79c89bcd7d9374fcb7586748983d9bbc57b4e049c62378db8153"
    )
    assert FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT == (
        "7692a4acfe39a4cf3511fe4a4be7e9eac5037a34c4e911a2bfec3d9bcea7047d"
    )


def test_functional_agent_resolves_its_declared_prompt_v7_policy() -> None:
    task = RepositoryRtlSuite().load_task(
        TaskRef(id="repo-rtl/counter-wrap", suite="repo-rtl", native_id="counter-wrap")
    )

    policy = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=CodexCliFunctionalAgentEvalAdapter(),
        agent_options={
            "prompt_contract_id": "repository_action_v2_prompt_v7",
            "max_completion_calls": 1,
        },
        task=task,
    )

    assert policy is not None
    assert policy.id == "repository_action_v2_prompt_v7"
    assert policy.version == "7.0.0"
    assert policy.task_context_policy == "revision_bound_functional_agent_feedback_v1"
    assert policy.base_instruction_policy == "generated_repository_action_registry_v7"
    assert policy.content_visibility_policy == ("visible_assets_and_public_functional_feedback_v1")
    protocol = resolve_repository_action_protocol(
        agent_descriptor=CodexCliFunctionalAgentEvalAdapter.descriptor,
        protocol_spec=CodexCliFunctionalAgentEvalAdapter.action_protocol_spec,
        agent_options={
            "prompt_contract_id": "repository_action_v2_prompt_v7",
            "max_completion_calls": 1,
        },
        task=task,
    )
    assert protocol is not None
    assert protocol.prompt_contract_id == "repository_action_v2_prompt_v7"
    assert protocol.state_machine_id == "repository_action_state_machine_v3"
