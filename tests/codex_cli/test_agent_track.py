from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym_codex_cli import CodexCliAgentAdapter

from verigym.core.hashing import hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunResult

pytestmark = [pytest.mark.codex_cli, pytest.mark.codex_cli_agent]


def _run(
    output: Path,
    *,
    task: str = "toy-rtl/and-gate-basic",
    max_process_time_s: float = 30,
    max_output_bytes: int | None = None,
    allow_proxy_environment: bool = False,
) -> RunResult:
    registries = build_registries(discover_external=False)
    registries.agents.register(CodexCliAgentAdapter())
    agent_options: dict[str, object] = {
        "model_id": "fake-model",
        "sandbox": "workspace-write",
        "approval_policy": "non-interactive",
        "max_process_time_s": max_process_time_s,
        "allow_proxy_environment": allow_proxy_environment,
    }
    if max_output_bytes is not None:
        agent_options["max_output_bytes"] = max_output_bytes
    return VeriGym(registries).run(
        RunConfig(
            task_id=task,
            mode=InteractionMode.AGENT,
            agent="codex-cli-agent",
            agent_options=agent_options,
            runtime="local",
            output=output,
        )
    )


def test_external_agent_good_candidate_uses_ordinary_freeze_and_verifier(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("agent_good")
    repository_hash = hash_directory(Path("src/verigym/suites/toy_rtl/assets"))
    result = _run(tmp_path / "runs")
    assert result.scorecard.resolved is True
    assert result.scorecard.efficiency.tool_calls == 0
    assert result.scorecard.efficiency.external_patch_count == 1
    assert result.scorecard.efficiency.external_command_count == 0
    assert len(result.manifest.external_agent_observations) == 1
    assert (result.run_dir / "candidate" / "rtl" / "and_gate.v").is_file()
    assert hash_directory(Path("src/verigym/suites/toy_rtl/assets")) == repository_hash
    model_records = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "model"
    ]
    assert len(model_records) == 1
    assert not any("hidden" in path for path in model_records[0]["initial_files"])
    assert "tb_and_gate.sv" not in model_records[0]["prompt"]
    assert "check_result.py" not in model_records[0]["prompt"]
    assert "mcp_servers={}" in model_records[0]["arguments"]
    assert "project_doc_max_bytes=0" in model_records[0]["arguments"]
    assert "sandbox_workspace_write.network_access=false" in model_records[0]["arguments"]
    assert model_records[0]["arguments"][-3:] == [
        "--config",
        'model_reasoning_effort="xhigh"',
        "-",
    ]
    summary = json.loads(
        (result.run_dir / "artifacts" / "codex_cli" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["candidate_modified_during_finish"] is False
    candidate_hash = hash_directory(result.run_dir / "candidate")
    before_replay = log.read_text(encoding="utf-8")
    replay = replay_run(result.run_dir, verify=False)
    assert replay.manifest.run_id == result.manifest.run_id
    assert log.read_text(encoding="utf-8") == before_replay
    assert hash_directory(result.run_dir / "candidate") == candidate_hash


def test_alias_mode_track_b_records_identity_and_replays_without_cli(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("agent_good")
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    result = _run(tmp_path / "runs")
    identity = result.manifest.external_agent_observations[-1]
    assert identity.auth_mode_label == "chatgpt_cli_session"
    assert identity.requested_auth_mode == "chatgpt_cli_session"
    assert identity.resolved_auth_mode == "inherited_codex_login"
    assert identity.auth_semantic_id == "codex.auth.inherited_chatgpt_session.v1"
    assert identity.auth_alias_used is True
    artifact = json.loads(
        (result.run_dir / "artifacts" / "codex_cli" / "identity.json").read_text(encoding="utf-8")
    )
    assert artifact["requested_auth_mode"] == "chatgpt_cli_session"
    assert artifact["resolved_auth_mode"] == "inherited_codex_login"
    assert artifact["auth_semantic_id"] == ("codex.auth.inherited_chatgpt_session.v1")
    before = log.read_bytes()
    replay_run(result.run_dir, verify=False)
    assert log.read_bytes() == before


def test_bad_candidate_is_normal_candidate_failure(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("agent_bad")
    result = _run(tmp_path / "runs")
    assert result.scorecard.resolved is False
    assert result.scorecard.status == "completed"
    assert result.scorecard.failure is None
    assert result.scorecard.correctness.infrastructure_error is False


def test_remote_failure_is_infrastructure_failure(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("auth_error")
    result = _run(tmp_path / "runs")
    assert result.scorecard.status == "error"
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "authentication"
    assert result.scorecard.failure.kind == "model"
    assert result.scorecard.failure.infrastructure is True


def test_path_escape_is_policy_failure(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("path_escape")
    result = _run(tmp_path / "runs")
    assert result.scorecard.status == "failed"
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.kind == "policy"
    assert result.scorecard.failure.infrastructure is False
    assert result.scorecard.termination_reason == "policy_violation"


@pytest.mark.parametrize(
    ("scenario_name", "category"),
    [
        ("agent_symlink", "workspace_policy"),
        ("agent_hardlink", "workspace_policy"),
        ("agent_credential_file", "external_workspace_policy"),
        ("agent_internal_file", "workspace_policy"),
    ],
)
def test_unsafe_external_workspace_mutations_are_policy_failures(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    scenario_name: str,
    category: str,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario(scenario_name)
    result = _run(tmp_path / "runs")
    assert result.scorecard.status == "failed"
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.kind == "policy"
    assert result.scorecard.failure.category == category
    assert result.scorecard.failure.infrastructure is False


def test_track_b_timeout_precedes_event_parsing_and_replay_is_model_free(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("timeout")
    result = _run(tmp_path / "runs", max_process_time_s=0.05)
    assert result.scorecard.status == "error"
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "timeout"
    assert result.scorecard.failure.category != "parser_error"
    assert result.scorecard.failure.infrastructure is True
    summary = json.loads(
        (result.run_dir / "artifacts" / "codex_cli" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["timed_out"] is True
    assert summary["diagnostic_only"] is True
    assert summary["canonical_stream_complete"] is False
    before_replay = log.read_bytes()
    replay_run(result.run_dir, verify=False)
    assert log.read_bytes() == before_replay


def test_track_b_timed_out_malformed_prefix_is_diagnostic_only(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("timeout_partial_malformed")
    result = _run(tmp_path / "runs", max_process_time_s=0.05)
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "timeout"
    artifact_root = result.run_dir / "artifacts" / "codex_cli"
    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    identity = json.loads((artifact_root / "identity.json").read_text(encoding="utf-8"))
    accounting = json.loads((artifact_root / "accounting.json").read_text(encoding="utf-8"))
    assert summary["diagnostic_only"] is True
    assert summary["canonical_stream_complete"] is False
    assert identity["observed_model_id"] is None
    assert identity["identity_confidence"] == "requested_only"
    assert accounting["cli_event_count"] == 1
    assert accounting["external_tool_call_count"] is None
    assert accounting["input_tokens"] is None


def test_track_b_output_overflow_precedes_event_parsing(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("oversized_stderr")
    result = _run(tmp_path / "runs", max_output_bytes=1024)
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "output_limit"
    assert result.scorecard.failure.category != "parser_error"
    summary = json.loads(
        (result.run_dir / "artifacts" / "codex_cli" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["stderr_truncated"] is True
    assert summary["diagnostic_only"] is True
    assert summary["canonical_stream_complete"] is False


def test_track_b_complete_malformed_stream_remains_parser_error(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("malformed")
    result = _run(tmp_path / "runs")
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "parser_error"


@pytest.mark.parametrize(
    ("scenario_name", "category"),
    [
        ("auth_error", "authentication"),
        ("rate_limit", "rate_limit"),
        ("transport_error", "transport"),
        ("nonzero", "remote_process_error"),
    ],
)
def test_track_b_non_timeout_remote_taxonomy_is_unchanged(
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


def test_track_b_fake_flow_succeeds_with_proxy_forwarding(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("agent_good")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.unit.invalid:8080")
    result = _run(tmp_path / "runs", allow_proxy_environment=True)
    assert result.scorecard.resolved is True
    record = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "model"
    ][-1]
    assert set(record["environment_names"]) & {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    }
