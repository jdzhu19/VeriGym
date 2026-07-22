from __future__ import annotations

import csv
import shutil
from io import StringIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.milestone9_helpers import experiment_config
from verigym.cli.app import app
from verigym.core.replay import replay_run
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.reporting.aggregate import ReportBuilder
from verigym.reporting.loader import load_report_inputs

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("iverilog") is None or shutil.which("vvp") is None,
        reason="Icarus Verilog is not installed",
    ),
]


def test_real_icarus_eight_child_experiment_and_individual_replay(tmp_path: Path) -> None:
    config = experiment_config(tmp_path / "real-eight")
    plan = ExperimentPlanner().build(config)
    result = BatchRunner().run(plan)
    aggregate = ReportBuilder().build(result.experiment_dir)
    assert result.exit_code == 0
    assert aggregate.coverage.planned_plan_items == 8
    assert aggregate.coverage.valid_terminal_artifacts == 8
    assert aggregate.coverage.evaluable_candidate_runs == 8
    assert aggregate.coverage.resolved_runs == 4
    assert aggregate.coverage.unresolved_evaluable_runs == 4
    assert aggregate.coverage.infrastructure_error_runs == 0
    assert aggregate.resolved_rate_evaluable.value == 0.5
    assert aggregate.resolved_rate_planned.value == 0.5

    for child in load_report_inputs(result.experiment_dir).valid_runs:
        replay = replay_run(result.experiment_dir / child.relative_path, verify=True)
        assert replay.reverified_resolved is child.scorecard.resolved


def test_real_icarus_n4_c2_sampling_report(tmp_path: Path) -> None:
    config = experiment_config(
        tmp_path / "real-sampling",
        tasks=["and-gate-basic"],
        mode="chat",
        systems=[
            {
                "id": "mixed",
                "agent": {"id": "single-turn"},
                "model": {"id": "static-and-gate-mixed"},
            }
        ],
        seeds=[11],
        samples=4,
        pass_k=[1, 2, 3],
    )
    plan = ExperimentPlanner().build(config)
    result = BatchRunner().run(plan)
    group = ReportBuilder().build(result.experiment_dir).sampling.groups[0]
    assert result.exit_code == 0
    assert group.canonical_valid
    assert (group.expected_n, group.resolved_c) == (4, 2)
    assert [entry.value for entry in group.entries] == pytest.approx([0.5, 5 / 6, 1.0])


def test_batch_and_report_cli_dry_run_execute_resume(tmp_path: Path) -> None:
    output = tmp_path / "cli-experiment"
    config = experiment_config(
        output,
        tasks=["and-gate-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0],
    )
    config_path = tmp_path / "experiment.json"
    config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    cli = CliRunner()

    dry = cli.invoke(app, ["batch", "--config", str(config_path), "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "Planned child runs: 1" in dry.output
    assert not output.exists()

    executed = cli.invoke(app, ["batch", "--config", str(config_path)])
    assert executed.exit_code == 0, executed.output
    assert "Child runs: 1/1" in executed.output
    assert (output / "reports" / "aggregate.json").is_file()

    csv_output = tmp_path / "regenerated.csv"
    report = cli.invoke(
        app,
        [
            "report",
            "generate",
            str(output),
            "--format",
            "csv",
            "--output",
            str(csv_output),
        ],
    )
    assert report.exit_code == 0, report.output
    rows = list(csv.DictReader(StringIO(csv_output.read_text(encoding="utf-8"))))
    assert len(rows) == 1 and rows[0]["artifact_validation_status"] == "valid"

    resumed = cli.invoke(app, ["batch", "--resume", str(output)])
    assert resumed.exit_code == 0, resumed.output
    assert "Child runs: 1/1" in resumed.output
