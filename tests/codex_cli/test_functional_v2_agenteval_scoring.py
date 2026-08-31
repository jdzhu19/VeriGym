from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.functional_v2_agenteval_agent import (
    CodexCliFunctionalV2HighAgentEvalAdapter,
    CodexCliFunctionalV2LowAgentEvalAdapter,
    CodexCliFunctionalV2MediumAgentEvalAdapter,
)
from verigym_codex_cli.functional_v2_agenteval_config import (
    FUNCTIONAL_V2_IDENTITIES,
    FUNCTIONAL_V2_PROMPT_HASH,
    FUNCTIONAL_V2_TOOL_POLICY_FINGERPRINT,
    functional_v2_high_settings,
    functional_v2_low_settings,
    functional_v2_medium_settings,
)

pytestmark = pytest.mark.codex_cli

_CLI_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"


@pytest.mark.parametrize(
    ("tier", "resolver", "adapter"),
    [
        ("low", functional_v2_low_settings, CodexCliFunctionalV2LowAgentEvalAdapter),
        ("medium", functional_v2_medium_settings, CodexCliFunctionalV2MediumAgentEvalAdapter),
        ("high", functional_v2_high_settings, CodexCliFunctionalV2HighAgentEvalAdapter),
    ],
)
def test_functional_v2_tiers_have_exact_distinct_identities(
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
    identity = FUNCTIONAL_V2_IDENTITIES[tier]
    options = {
        "model_id": identity.model_id,
        "reasoning_effort": identity.reasoning_effort,
        "expected_cli_version": "codex-cli 0.147.0",
        "expected_cli_executable_sha256": _CLI_SHA256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_prompt_hash": FUNCTIONAL_V2_PROMPT_HASH,
        "expected_tool_policy_fingerprint": FUNCTIONAL_V2_TOOL_POLICY_FINGERPRINT,
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
    assert settings.max_consecutive_rejected_calls == 6
    assert settings.patch_format_profile == "strict_unified_and_codex_native_v1"
    assert adapter.descriptor.name == identity.agent_name  # type: ignore[attr-defined]
    assert adapter.prompt_policy_spec.prompt_contract_id == (  # type: ignore[attr-defined]
        "repository_action_v2_prompt_v8"
    )


def test_functional_v2_fingerprints_are_frozen_literals() -> None:
    assert FUNCTIONAL_V2_PROMPT_HASH == (
        "14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9"
    )
    assert FUNCTIONAL_V2_TOOL_POLICY_FINGERPRINT == (
        "5cb057a7cb6722538144acf1e9ef3265eae3c3391af0ab97eb2b96b93e941a1c"
    )
    assert {
        tier: identity.agent_version_hash for tier, identity in FUNCTIONAL_V2_IDENTITIES.items()
    } == {
        "low": "6f310dc8c2459afda70899911155f08383ae21dfc2f9977e903e0b0ccb2f00f2",
        "medium": "4ae411e4dd59e6ecbfd6333b730989decd2c2bfe3b0cdf280926a2742b1ebbae",
        "high": "505dd28a93683aa478da731b4bbe3e03417cd51b6e1589695962a0a3c04cfc3d",
    }
