from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.functional_v3_agenteval_agent import (
    CodexCliFunctionalV3HighAgentEvalAdapter,
    CodexCliFunctionalV3LowAgentEvalAdapter,
    CodexCliFunctionalV3MediumAgentEvalAdapter,
    CodexCliFunctionalV3MiniMediumAgentEvalAdapter,
)
from verigym_codex_cli.functional_v3_agenteval_config import (
    FUNCTIONAL_V3_IDENTITIES,
    FUNCTIONAL_V3_PROMPT_HASH,
    FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
    functional_v3_high_settings,
    functional_v3_low_settings,
    functional_v3_medium_settings,
    functional_v3_mini_medium_settings,
)

pytestmark = pytest.mark.codex_cli

_CLI_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"


@pytest.mark.parametrize(
    ("tier", "resolver", "adapter"),
    [
        ("low", functional_v3_low_settings, CodexCliFunctionalV3LowAgentEvalAdapter),
        ("medium", functional_v3_medium_settings, CodexCliFunctionalV3MediumAgentEvalAdapter),
        (
            "mini-medium-control",
            functional_v3_mini_medium_settings,
            CodexCliFunctionalV3MiniMediumAgentEvalAdapter,
        ),
        ("high", functional_v3_high_settings, CodexCliFunctionalV3HighAgentEvalAdapter),
    ],
)
def test_functional_v3_tiers_freeze_the_repaired_tool_policy(
    fake_codex: tuple[Path, Path, object],
    tier: str,
    resolver: object,
    adapter: type[object],
) -> None:
    del fake_codex
    _identity, discovered = discover_capabilities(force=True)
    capabilities = replace(
        discovered,
        version_output="codex-cli 0.147.0",
        executable_sha256=_CLI_SHA256,
    )
    identity = FUNCTIONAL_V3_IDENTITIES[tier]
    options = {
        "model_id": identity.model_id,
        "reasoning_effort": identity.reasoning_effort,
        "expected_cli_version": "codex-cli 0.147.0",
        "expected_cli_executable_sha256": _CLI_SHA256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_prompt_hash": FUNCTIONAL_V3_PROMPT_HASH,
        "expected_tool_policy_fingerprint": FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": "inherited_codex_login",
        "expected_resolved_auth_mode": "inherited_codex_login",
        "expected_auth_semantic_id": "codex.auth.inherited_chatgpt_session.v1",
        "prompt_contract_id": "repository_action_v2_prompt_v8",
        "scoring_agent_version_id": identity.agent_version_id,
        "scoring_agent_version_hash": identity.agent_version_hash,
    }

    settings = resolver(options, capabilities, task_wall_time_s=300)  # type: ignore[operator]

    assert settings.execution.model_id == identity.model_id
    assert settings.execution.effective_reasoning_effort == identity.reasoning_effort
    assert settings.tool_policy_fingerprint == FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT
    assert adapter.descriptor.name == identity.agent_name  # type: ignore[attr-defined]
    assert adapter.descriptor.version == "3.0.0"  # type: ignore[attr-defined]


def test_functional_v3_fingerprints_are_frozen_literals() -> None:
    assert FUNCTIONAL_V3_PROMPT_HASH == (
        "14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9"
    )
    assert FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT == (
        "6a0cf3b44d0bdb1b6ba2a016607db639e857af8979389ece947c8bea55415ef4"
    )
    assert {
        tier: identity.agent_version_hash for tier, identity in FUNCTIONAL_V3_IDENTITIES.items()
    } == {
        "low": "d41741d8f4cee7e4cf53e3c99f3aad9512a9ea0266c4be89522fc1d5e94d85ef",
        "medium": "cad433bd3e90d5623d889229971069993321ab765f677946bf1bb698c9405239",
        "mini-medium-control": "2bc08440bad001e83a238aceaa9da4fa647e04723d9f85124609e0f232f43f81",
        "high": "467d2ba0847fab60f39ee7d85a7073abc832e5c35fa299d8e09cb5761c230b3c",
    }
