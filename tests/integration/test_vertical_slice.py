from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from verigym.cli.app import app
from verigym.core.errors import ReplayError
from verigym.core.hashing import hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.core.trace import read_trace
from verigym.core.workspace import copy_tree_safely
from verigym.registry.collections import build_registries
from verigym.schemas.run import RunConfig
from verigym.schemas.verifier import VerifierStatus

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("iverilog") is None or shutil.which("vvp") is None,
        reason="Icarus Verilog is not installed",
    ),
]


def service() -> VeriGym:
    return VeriGym(build_registries(discover_external=False))


def test_good_agent_writes_complete_isolated_run_and_replays(tmp_path) -> None:
    result = service().run(
        RunConfig(
            task_id="toy-rtl/counter-basic",
            agent="scripted",
            runtime="local",
            output=tmp_path / "runs",
        )
    )
    assert result.scorecard.resolved
    assert result.scorecard.status == "completed"
    assert result.scorecard.quality.ppa is None
    assert result.manifest.model is None
    assert result.manifest.agent.name == "scripted"
    assert result.manifest.runtime.isolation_level == "local_trusted"
    required = {
        "run_manifest.json",
        "task_snapshot.json",
        "trace.jsonl",
        "scorecard.json",
        "workspace_diff.patch",
        "candidate",
        "logs",
        "artifacts",
    }
    assert required <= {path.name for path in result.run_dir.iterdir()}
    assert not (result.run_dir / "candidate" / "hidden").exists()
    assert not list((result.run_dir / "candidate").rglob("tb_counter.sv"))
    assert (result.run_dir / "artifacts" / "compile_hidden" / "executable").is_file()
    assert (result.run_dir / "artifacts" / "run_hidden" / "stdout.log").is_file()
    profile = json.loads(
        (result.run_dir / "artifacts" / "toolchain_profile.json").read_text(encoding="utf-8")
    )
    assert profile["id"] == "toy-iverilog-v1"
    assert all(tool["version"] for tool in profile["tools"])
    for log_name in ("agent.log", "runtime.log", "verifier.log"):
        log_lines = (result.run_dir / "logs" / log_name).read_text(encoding="utf-8").splitlines()
        assert log_lines
        assert all(json.loads(line)["run_id"] == result.manifest.run_id for line in log_lines)
    assert result.manifest.candidate_hash == hash_directory(result.run_dir / "candidate")
    events = read_trace(result.run_dir / "trace.jsonl", expected_run_id=result.manifest.run_id)
    assert [event.sequence for event in events] == list(range(len(events)))
    assert events[0].event_type == "episode_started"
    assert events[-1].event_type == "episode_terminated"
    serialized_trace = (result.run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "module tb_counter" not in serialized_trace

    replay = replay_run(result.run_dir, service=service())
    assert replay.scorecard.resolved
    assert replay.reverified_results is None
    verified_replay = replay_run(result.run_dir, verify=True, service=service())
    assert verified_replay.reverified_resolved is True
    candidate = result.run_dir / "candidate" / "rtl" / "counter.v"
    candidate.write_text(candidate.read_text(encoding="utf-8") + "// tampered\n", encoding="utf-8")
    with pytest.raises(ReplayError, match="candidate snapshot"):
        replay_run(result.run_dir, service=service())


def test_bad_agent_is_normal_candidate_failure_not_runtime_error(tmp_path) -> None:
    result = service().run(
        RunConfig(
            task_id="toy-rtl/counter-basic",
            agent="scripted-bad",
            runtime="local",
            output=tmp_path / "runs",
        )
    )
    assert not result.scorecard.resolved
    assert result.scorecard.status == "completed"
    assert not result.scorecard.correctness.infrastructure_error
    assert result.scorecard.correctness.compile_status == "passed"
    assert result.scorecard.correctness.hidden_regression_status == "failed"
    assert result.scorecard.verifier_results[-1].error_category.value == "test_failed"
    assert result.scorecard.quality.ppa is None


@pytest.mark.conformance
def test_adapter_known_candidates_match_expected_semantics_deterministically(tmp_path) -> None:
    vg = service()
    suite, task, assets = vg.load_task("toy-rtl/counter-basic")
    runtime = vg.registries.runtimes.get("local")
    for case in suite.conformance_cases():
        candidate_dir = tmp_path / case.name / "candidate"
        copy_tree_safely(Path(assets.visible_root), candidate_dir)
        for relative, content in case.candidate.files.items():
            target = candidate_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        normalized_runs = []
        for repeat in range(2):
            results = vg._verify_candidate(
                task=task,
                assets=assets,
                runtime=runtime,
                candidate_dir=candidate_dir,
                artifact_root=tmp_path / case.name / f"artifacts-{repeat}",
            )
            normalized_runs.append(
                [(result.node_id, result.status, result.error_category) for result in results]
            )
        assert normalized_runs[0] == normalized_runs[1]
        resolved = all(status == VerifierStatus.PASSED for _, status, _ in normalized_runs[0])
        assert resolved is case.expected_resolved


def test_reference_cli_command_and_replay_command(tmp_path) -> None:
    runner = CliRunner()
    output = tmp_path / "cli-runs"
    command = [
        "run",
        "--suite",
        "toy-rtl",
        "--task",
        "counter-basic",
        "--mode",
        "agent",
        "--agent",
        "scripted",
        "--runtime",
        "local",
        "--output",
        str(output),
    ]
    run_result = runner.invoke(app, command)
    assert run_result.exit_code == 0, run_result.output
    run_dir = next(output.iterdir())
    replay_result = runner.invoke(app, ["replay", str(run_dir), "--verify"])
    assert replay_result.exit_code == 0, replay_result.output
    assert "Reverification: resolved=True" in replay_result.output
    bad_result = runner.invoke(
        app,
        [
            "run",
            "--suite",
            "toy-rtl",
            "--task",
            "counter-basic",
            "--mode",
            "agent",
            "--agent",
            "scripted-bad",
            "--runtime",
            "local",
            "--output",
            str(tmp_path / "bad-cli-runs"),
        ],
    )
    assert bad_result.exit_code == 1, bad_result.output
