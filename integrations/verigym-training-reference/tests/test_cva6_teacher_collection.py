from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.api import RunConfig
from verigym.core.errors import ConfigurationError
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot

from verigym_training_reference.cva6_teacher_collection import (
    _CLAUDE_CONTEXT_WINDOW,
    _MAX_BUDGET_USD,
    _MAX_CAMPAIGN_COST_USD,
    _MAX_CAMPAIGN_PROVIDER_TOKENS,
    _MAX_CONSECUTIVE_REJECTED_CALLS,
    _MAX_EVIDENCE_BYTES,
    _MAX_PATCH_CALLS,
    _MAX_PROCESS_TIME_S,
    _MAX_PROVIDER_TOKENS,
    _MAX_TOOL_CALLS,
    _attempt_id,
    _campaign_output,
    _is_infrastructure_invalid,
    _provider_usage,
    _run_config,
    _stop_for_campaign_limit,
)


def test_teacher_campaign_uses_the_maximum_bounded_cli_evidence_stream() -> None:
    assert _MAX_EVIDENCE_BYTES == 16 * 1024 * 1024

    source = (
        Path(__file__).parents[1]
        / "src"
        / "verigym_training_reference"
        / "cva6_teacher_collection.py"
    ).read_text(encoding="utf-8")
    assert source.count('"max_output_bytes": _MAX_EVIDENCE_BYTES') == 2
    assert source.count('"max_tool_calls": _MAX_TOOL_CALLS') >= 2
    assert source.count('"max_patch_calls": _MAX_PATCH_CALLS') >= 2
    assert source.count('"max_consecutive_rejected_calls": _MAX_CONSECUTIVE_REJECTED_CALLS') >= 2
    assert source.count('"max_provider_billed_units": _MAX_PROVIDER_TOKENS') == 1
    assert source.count('"max_budget_usd": _MAX_BUDGET_USD') == 1
    assert source.count('"expected_context_window": _CLAUDE_CONTEXT_WINDOW') == 1
    assert _MAX_PROCESS_TIME_S == 600


def test_claude_run_config_uses_secret_safe_provider_limit_option(tmp_path: Path) -> None:
    source = SuiteSourceConfig(source_root=tmp_path / "source", variant="repo-repair-v1")
    snapshot = SuiteSourceSnapshot(
        source_root=str(tmp_path / "source"),
        dataset_root="instances.jsonl",
        variant="repo-repair-v1",
        native_layout="hwe-bench-v1",
        strict_compatibility=True,
        configuration_fingerprint="a" * 64,
        dataset_content_hash="b" * 64,
        synthetic_fixture=True,
    )
    config = _run_config(
        attempt_id="campaign-00-claude-sample-0",
        provider="claude",
        sample_index=0,
        task_id="cva6-example",
        task_hash="c" * 64,
        source_hash="d" * 64,
        source=source,
        source_snapshot=snapshot,
        docker_config=DockerRuntimeConfig(image="verigym/example:test"),
        output=tmp_path / "runs",
        max_process_time_s=_MAX_PROCESS_TIME_S,
        campaign_id="campaign",
    )

    assert config.agent_options["max_provider_billed_units"] == _MAX_PROVIDER_TOKENS
    assert "max_provider_tokens" not in config.agent_options

    unsafe = config.model_dump(mode="python")
    unsafe["agent_options"] = {"max_provider_tokens": _MAX_PROVIDER_TOKENS}
    with pytest.raises(ValueError, match="secret-bearing plugin option key"):
        RunConfig.model_validate(unsafe)


def test_campaign_identity_is_bound_into_progress_and_attempt_ids(tmp_path: Path) -> None:
    campaign_id = "cva6-verified-multiturn-teachers-v2"

    root, progress = _campaign_output(
        tmp_path / "teachers",
        campaign_id=campaign_id,
        split_hash="a" * 64,
        docker_config_hash="b" * 64,
        max_process_time_s=_MAX_PROCESS_TIME_S,
    )

    assert root == (tmp_path / "teachers").resolve()
    assert progress["campaign_id"] == campaign_id
    assert progress["episode_limits"] == {
        "max_process_time_s": _MAX_PROCESS_TIME_S,
        "max_tool_calls": _MAX_TOOL_CALLS,
        "max_patch_calls": _MAX_PATCH_CALLS,
        "max_consecutive_rejected_calls": _MAX_CONSECUTIVE_REJECTED_CALLS,
        "claude_max_provider_tokens": _MAX_PROVIDER_TOKENS,
        "claude_expected_context_window": _CLAUDE_CONTEXT_WINDOW,
        "claude_max_budget_usd": _MAX_BUDGET_USD,
        "max_campaign_provider_tokens": _MAX_CAMPAIGN_PROVIDER_TOKENS,
        "max_campaign_cost_usd": _MAX_CAMPAIGN_COST_USD,
    }
    assert _attempt_id(campaign_id, 3, "codex", 0) == (
        "cva6-verified-multiturn-teachers-v2-03-codex-sample-0"
    )


def test_campaign_cannot_resume_under_a_different_identity(tmp_path: Path) -> None:
    output = tmp_path / "teachers"
    _campaign_output(
        output,
        campaign_id="cva6-verified-multiturn-teachers-v1",
        split_hash="a" * 64,
        docker_config_hash="b" * 64,
        max_process_time_s=_MAX_PROCESS_TIME_S,
    )

    with pytest.raises(ConfigurationError, match="resume identity changed"):
        _campaign_output(
            output,
            campaign_id="cva6-verified-multiturn-teachers-v2",
            split_hash="a" * 64,
            docker_config_hash="b" * 64,
            max_process_time_s=_MAX_PROCESS_TIME_S,
        )


def test_campaign_cannot_resume_with_a_different_wall_clock_limit(tmp_path: Path) -> None:
    output = tmp_path / "teachers"
    _campaign_output(
        output,
        campaign_id="cva6-verified-multiturn-teachers-v1",
        split_hash="a" * 64,
        docker_config_hash="b" * 64,
        max_process_time_s=_MAX_PROCESS_TIME_S,
    )

    with pytest.raises(ConfigurationError, match="resume identity changed"):
        _campaign_output(
            output,
            campaign_id="cva6-verified-multiturn-teachers-v1",
            split_hash="a" * 64,
            docker_config_hash="b" * 64,
            max_process_time_s=_MAX_PROCESS_TIME_S - 1,
        )


def test_provider_usage_and_campaign_cap_include_claude_cache_tokens(tmp_path: Path) -> None:
    run = tmp_path / "run"
    artifact = run / "artifacts" / "claude_cli"
    artifact.mkdir(parents=True)
    (artifact / "provider-usage.json").write_text(
        json.dumps(
            {
                "usage_complete": True,
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_creation_input_tokens": 30,
                "cache_read_input_tokens": _MAX_CAMPAIGN_PROVIDER_TOKENS,
                "cost_usd": 1.5,
            }
        ),
        encoding="utf-8",
    )
    usage = _provider_usage(run)
    assert usage["billed_tokens_observed"] == _MAX_CAMPAIGN_PROVIDER_TOKENS + 60

    progress = {
        "status": "running",
        "attempts": [{"provider_usage": usage}],
        "successes": [],
    }
    assert _stop_for_campaign_limit(tmp_path, progress) is True
    assert progress["status"] == "incomplete_campaign_resource_limit"
    assert progress["stop_reason"] == "campaign_provider_token_limit"


def test_failed_codex_attempt_can_record_explicitly_missing_usage(tmp_path: Path) -> None:
    artifact = tmp_path / "run" / "artifacts" / "codex_cli"
    artifact.mkdir(parents=True)
    (artifact / "provider-usage.json").write_text(
        json.dumps(
            {
                "usage_complete": False,
                "input_tokens": None,
                "output_tokens": None,
                "cached_input_tokens": None,
                "cost_usd": None,
            }
        ),
        encoding="utf-8",
    )

    usage = _provider_usage(tmp_path / "run", require_observed=False)
    assert usage["usage_complete"] is False
    assert usage["billed_tokens_observed"] is None


@pytest.mark.parametrize(
    ("status", "failure", "expected"),
    [
        ("error", SimpleNamespace(kind="model", infrastructure=False), False),
        ("error", SimpleNamespace(kind="runtime", infrastructure=False), True),
        ("failed", SimpleNamespace(kind="model", infrastructure=True), True),
    ],
)
def test_teacher_campaign_distinguishes_agent_and_infrastructure_failures(
    status: str, failure: object, expected: bool
) -> None:
    scorecard = SimpleNamespace(
        status=status,
        failure=failure,
        correctness=SimpleNamespace(infrastructure_error=False),
    )

    assert _is_infrastructure_invalid(scorecard) is expected
