from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym_codex_cli import CodexCliReadonlyAgentAdapter

from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunResult

pytestmark = [pytest.mark.codex_cli, pytest.mark.codex_cli_readonly_agent]


def _run(
    output: Path,
    *,
    max_process_time_s: float = 30,
    max_output_bytes: int | None = None,
    allow_proxy_environment: bool = False,
) -> RunResult:
    registries = build_registries(discover_external=False)
    registries.agents.register(CodexCliReadonlyAgentAdapter())
    options: dict[str, object] = {
        "model_id": "fake-model",
        "sandbox": "read-only",
        "approval_policy": "non-interactive",
        "reasoning_effort": "xhigh",
        "max_process_time_s": max_process_time_s,
        "allow_proxy_environment": allow_proxy_environment,
    }
    if max_output_bytes is not None:
        options["max_output_bytes"] = max_output_bytes
    return VeriGym(registries).run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            mode=InteractionMode.AGENT,
            agent="codex-cli-readonly-agent",
            agent_options=options,
            runtime="local",
            output=output,
        )
    )


def test_one_episode_runs_in_empty_directory_and_uses_ordinary_verifier(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, _scenario = fake_codex
    result = _run(tmp_path / "runs")
    assert result.scorecard.resolved is True
    assert result.scorecard.efficiency.tool_calls == 1
    assert result.manifest.model is None
    assert len(result.manifest.external_agent_observations) == 1
    identity = result.manifest.external_agent_observations[-1]
    assert identity.integration_track == "codex_cli_readonly_single_turn_agent"
    assert identity.interaction_class == "cli_agent_single_turn_readonly"
    assert identity.chat_eval_compatible is False
    assert identity.pure_api_model_eval is False
    assert identity.direct_api_benchmark is False
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    model_calls = [record for record in calls if record["kind"] == "model"]
    assert len(model_calls) == 1
    assert model_calls[0]["initial_files"] == []
    assert str(Path.cwd()) not in model_calls[0]["prompt"]
    artifact_root = result.run_dir / "artifacts" / "codex_cli"
    assert {
        "accounting.json",
        "capabilities.json",
        "event_policy.json",
        "identity.json",
        "invocation.json",
        "parsed_events.jsonl",
        "raw_stderr.log",
        "raw_stdout.jsonl",
        "summary.json",
    } == {path.name for path in artifact_root.iterdir()}
    policy = json.loads((artifact_root / "event_policy.json").read_text(encoding="utf-8"))
    assert policy["policy_id"] == "typed_readonly_empty_workdir_v1"
    assert policy["policy_passed"] is True
    assert policy["tool_event_count"] == 0
    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["candidate_materialization"] == "ordinary_file_apply_patch"
    assert summary["candidate_materialization_succeeded"] is True
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in artifact_root.iterdir())
    assert "private fake reasoning" not in persisted


def test_alias_identity_and_model_free_replay(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, log, _scenario = fake_codex
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    result = _run(tmp_path / "runs")
    identity = result.manifest.external_agent_observations[-1]
    assert identity.requested_auth_mode == "chatgpt_cli_session"
    assert identity.resolved_auth_mode == "inherited_codex_login"
    assert identity.auth_semantic_id == "codex.auth.inherited_chatgpt_session.v1"
    assert identity.auth_alias_used is True
    before = log.read_bytes()
    replay_run(result.run_dir, verify=False)
    assert log.read_bytes() == before


def test_unknown_usage_remains_null(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("unknown_usage")
    result = _run(tmp_path / "runs")
    assert result.scorecard.efficiency.external_input_tokens is None
    assert result.scorecard.efficiency.external_output_tokens is None
    assert result.scorecard.efficiency.external_total_tokens is None


def test_bounded_empty_workdir_read_events_are_typed_and_permitted(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("tool_use")
    result = _run(tmp_path / "runs")
    assert result.scorecard.status == "completed"
    identity = result.manifest.external_agent_observations[-1]
    assert identity.tool_event_count == 2
    assert identity.read_only_tool_event_count == 2
    assert identity.side_effecting_tool_event_count == 0
    policy = json.loads(
        (result.run_dir / "artifacts" / "codex_cli" / "event_policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy["policy_passed"] is True
    assert policy["classification_counts"] == {"read_only_empty_workdir_inspection": 2}


@pytest.mark.parametrize("scenario_name", ["unknown_event", "path_escape"])
def test_unknown_and_outside_reads_fail_closed(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    scenario_name: str,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario(scenario_name)
    result = _run(tmp_path / "runs")
    assert result.scorecard.status == "failed"
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.kind == "policy"
    assert result.scorecard.failure.category == "readonly_event_policy"


@pytest.mark.parametrize(
    ("scenario_name", "category"),
    [
        ("auth_error", "authentication"),
        ("rate_limit", "rate_limit"),
        ("transport_error", "transport"),
        ("nonzero", "remote_process_error"),
        ("malformed", "parser_error"),
    ],
)
def test_remote_and_parser_failures_remain_distinct(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    scenario_name: str,
    category: str,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario(scenario_name)
    result = _run(tmp_path / "runs")
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == category


def test_timeout_precedes_parser_taxonomy_and_replay_is_model_free(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("timeout_partial_malformed")
    result = _run(tmp_path / "runs", max_process_time_s=0.05)
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "timeout"
    summary = json.loads(
        (result.run_dir / "artifacts" / "codex_cli" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["diagnostic_only"] is True
    assert summary["canonical_stream_complete"] is False
    before = log.read_bytes()
    replay_run(result.run_dir, verify=False)
    assert log.read_bytes() == before


def test_output_overflow_precedes_parser_taxonomy(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("oversized_stderr")
    result = _run(tmp_path / "runs", max_output_bytes=1024)
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "output_limit"


def test_secret_shaped_output_and_proxy_values_are_not_persisted(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    proxy = "http://proxy-user:proxy-password@proxy.unit.invalid:8080"
    monkeypatch.setenv("HTTP_PROXY", proxy)
    scenario("proxy_output")
    result = _run(tmp_path / "runs", allow_proxy_environment=True)
    assert result.scorecard.failure is not None
    artifact_root = result.run_dir / "artifacts" / "codex_cli"
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in artifact_root.iterdir())
    assert proxy not in persisted
    assert "proxy-user" not in persisted
    invocation = json.loads((artifact_root / "invocation.json").read_text(encoding="utf-8"))
    assert invocation["proxy_values_persisted"] is False
