from __future__ import annotations

import csv
import json
import stat
import threading
import time
from collections.abc import Callable
from io import StringIO
from pathlib import Path

import pytest

from tests.milestone9_helpers import experiment_config, offline_service
from verigym.core.errors import ConfigurationError, RuntimeExecutionError
from verigym.core.loaders import dump_json
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import PlanItem
from verigym.models.base import ModelClientError
from verigym.models.static import AND_GATE_BAD_SOURCE, AND_GATE_GOOD_SOURCE, StaticModelClient
from verigym.reporting.aggregate import ReportBuilder
from verigym.reporting.csv_report import CSV_COLUMNS, render_csv
from verigym.reporting.loader import load_report_inputs
from verigym.reporting.markdown import markdown_escape
from verigym.reporting.schemas import AggregateReport
from verigym.reporting.service import ReportService
from verigym.schemas.model import (
    ModelClientErrorInfo,
    ModelErrorCategory,
    ModelRequest,
    ModelResponse,
    ModelRunConfig,
)
from verigym.schemas.run import RunConfig, RunResult
from verigym.schemas.score import PPAMetrics, QualityMetrics


class InfrastructureSampleModel(StaticModelClient):
    def __init__(
        self,
        calls: list[int],
        *,
        selected_sample_index: int | None = None,
    ) -> None:
        self.calls = calls
        super().__init__(
            name="m9-infrastructure-sample",
            responses=[AND_GATE_GOOD_SOURCE],
            sample_responses=[
                [AND_GATE_GOOD_SOURCE],
                [AND_GATE_BAD_SOURCE],
                [AND_GATE_GOOD_SOURCE],
                [AND_GATE_BAD_SOURCE],
            ],
            _selected_sample_index=selected_sample_index,
        )

    def clone_for_run(
        self,
        configuration: ModelRunConfig | None = None,
    ) -> InfrastructureSampleModel:
        return InfrastructureSampleModel(
            self.calls,
            selected_sample_index=configuration.sample_index if configuration else 0,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        index = self._selected_sample_index or 0
        self.calls.append(index)
        if index == 1:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.TRANSPORT,
                    message="synthetic transport outage",
                    retryable=True,
                )
            )
        return super().generate(request)


def _planner() -> ExperimentPlanner:
    return ExperimentPlanner(offline_service())


def _runner(
    *,
    child_executor: Callable[[PlanItem, RunConfig], RunResult] | None = None,
    service_factory: Callable[[], VeriGym] = offline_service,
) -> BatchRunner:
    return BatchRunner(
        planner=_planner(),
        child_executor=child_executor,
        service_factory=service_factory,
    )


def test_offline_eight_child_acceptance_and_replay(tmp_path: Path) -> None:
    config = experiment_config(tmp_path / "experiment")
    plan = _planner().build(config)
    result = _runner().run(plan)
    assert result.exit_code == 0
    assert result.state.status == "completed"
    assert result.state.planned_count == 8
    assert result.state.valid_terminal_count == 8
    assert result.state.observed_max_concurrency == 1

    required_parent = {
        "experiment_manifest.json",
        "experiment_config.json",
        "plan.jsonl",
        "events.jsonl",
        "state.json",
        "run_index.jsonl",
        "logs",
        "runs",
        "reports",
    }
    assert required_parent <= {entry.name for entry in result.experiment_dir.iterdir()}
    for name in ("experiment_manifest.json", "experiment_config.json", "state.json"):
        json.loads((result.experiment_dir / name).read_text(encoding="utf-8"))
    for name in ("plan.jsonl", "events.jsonl", "run_index.jsonl"):
        for line in (result.experiment_dir / name).read_text(encoding="utf-8").splitlines():
            json.loads(line)

    aggregate = AggregateReport.model_validate_json(
        (result.experiment_dir / "reports" / "aggregate.json").read_text(encoding="utf-8")
    )
    assert aggregate.coverage.planned_plan_items == 8
    assert aggregate.coverage.valid_terminal_artifacts == 8
    assert aggregate.coverage.evaluable_candidate_runs == 8
    assert aggregate.coverage.resolved_runs == 4
    assert aggregate.coverage.unresolved_evaluable_runs == 4
    assert aggregate.coverage.infrastructure_error_runs == 0
    assert aggregate.resolved_rate_evaluable.numerator == 4
    assert aggregate.resolved_rate_evaluable.denominator == 8
    assert aggregate.resolved_rate_evaluable.value == 0.5
    assert aggregate.resolved_rate_evaluable.unavailable_reason is None
    assert aggregate.resolved_rate_planned.value == 0.5
    assert aggregate.evaluation_completion_rate.value == 1.0
    assert aggregate.failure_taxonomy.candidate_outcomes == {
        "candidate_failure": 4,
        "resolved": 4,
    }
    assert aggregate.cost_resolved.known_value_count == 0
    assert aggregate.cost_resolved.missing_value_count == 4
    assert aggregate.metadata["universal_score"] is None

    inputs = load_report_inputs(result.experiment_dir)
    assert len(inputs.valid_runs) == 8
    for child in inputs.valid_runs:
        replay = replay_run(
            result.experiment_dir / child.relative_path,
            verify=True,
            service=offline_service(),
        )
        assert replay.reverified_resolved is child.scorecard.resolved

    csv_text = (result.experiment_dir / "reports" / "runs.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(StringIO(csv_text)))
    assert list(rows[0]) == CSV_COLUMNS
    assert [int(row["plan_index"]) for row in rows] == list(range(8))
    assert {row["artifact_validation_status"] for row in rows} == {"valid"}
    assert "VeriGym Score" not in (result.experiment_dir / "reports" / "report.md").read_text(
        encoding="utf-8"
    )

    first_hashes = ReportService().generate_all(result.experiment_dir).hashes
    second_hashes = ReportService().generate_all(result.experiment_dir).hashes
    assert first_hashes == second_hashes


def test_bounded_parallel_execution_is_serialized_and_ordered(tmp_path: Path) -> None:
    config = experiment_config(tmp_path / "parallel", max_workers=2)
    plan = _planner().build(config)
    lock = threading.Lock()
    active = 0
    maximum = 0
    calls: list[str] = []

    def child(item: PlanItem, run_config: RunConfig) -> RunResult:
        nonlocal active, maximum
        with lock:
            calls.append(item.plan_item_id)
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.02)
            return offline_service().run(run_config)
        finally:
            with lock:
                active -= 1

    result = _runner(child_executor=child).run(plan)
    assert result.exit_code == 0
    assert maximum == 2
    assert result.state.observed_max_concurrency == 2
    assert len(calls) == len(set(calls)) == 8
    rows = list(
        csv.DictReader(
            StringIO((result.experiment_dir / "reports" / "runs.csv").read_text(encoding="utf-8"))
        )
    )
    assert [int(row["plan_index"]) for row in rows] == list(range(8))
    for path in (
        result.experiment_dir / "experiment_manifest.json",
        result.experiment_dir / "state.json",
    ):
        json.loads(path.read_text(encoding="utf-8"))
    for path in (
        result.experiment_dir / "events.jsonl",
        result.experiment_dir / "run_index.jsonl",
    ):
        assert all(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def test_batch_report_preserves_exact_n4_c2_pass_at_k(tmp_path: Path) -> None:
    config = experiment_config(
        tmp_path / "sampling",
        tasks=["and-gate-basic"],
        mode="chat",
        systems=[
            {
                "id": "mixed",
                "agent": {"id": "single-turn"},
                "model": {"id": "static-and-gate-mixed"},
            }
        ],
        seeds=[7],
        samples=4,
        pass_k=[1, 2, 3],
    )
    result = _runner().run(_planner().build(config))
    aggregate = ReportBuilder().build(result.experiment_dir)
    assert result.exit_code == 0
    assert len(aggregate.sampling.groups) == 1
    group = aggregate.sampling.groups[0]
    assert group.canonical_valid
    assert (group.expected_n, group.observed_n, group.resolved_c) == (4, 4, 2)
    assert [entry.value for entry in group.entries] == pytest.approx([0.5, 5 / 6, 1.0])
    assert [entry.macro_mean for entry in aggregate.sampling.macro] == pytest.approx(
        [0.5, 5 / 6, 1.0]
    )

    full_scale = ReportService().generate_full_scale(
        result.experiment_dir,
        bootstrap_resamples=100,
        bootstrap_seed=17,
    )
    payload = json.loads(full_scale.paths["full-scale.json"].read_text(encoding="utf-8"))
    assert payload["claims"] == {
        "best_of_n_selection": False,
        "direct_api_evaluation": False,
        "official_upstream_model_score": False,
    }
    row = payload["pass_at_k"][0]
    assert (row["pass_at_1"], row["pass_at_2"], row["pass_at_3"]) == pytest.approx(
        (0.5, 5 / 6, 1.0)
    )
    statistics_payload = payload["statistical_analysis"]
    assert statistics_payload["method"].startswith("deterministic_paired_task_level")
    assert statistics_payload["resamples"] == 100
    assert statistics_payload["systems"]["mixed"]["pass_at_1"]["task_count"] == 1


def test_infrastructure_failure_invalidates_group_and_is_not_candidate_failure(
    tmp_path: Path,
) -> None:
    calls: list[int] = []

    def service() -> VeriGym:
        return offline_service(InfrastructureSampleModel(calls))

    config = experiment_config(
        tmp_path / "infrastructure",
        tasks=["and-gate-basic"],
        mode="chat",
        systems=[
            {
                "id": "infra",
                "agent": {"id": "single-turn"},
                "model": {"id": "m9-infrastructure-sample"},
            }
        ],
        seeds=[4],
        samples=4,
        pass_k=[1, 2],
    )
    planner = ExperimentPlanner(service())
    runner = BatchRunner(planner=planner, service_factory=service)
    result = runner.run(planner.build(config))
    aggregate = ReportBuilder().build(result.experiment_dir)
    assert result.exit_code == 4
    assert sorted(calls) == [0, 1, 2, 3]
    assert aggregate.coverage.infrastructure_error_runs == 1
    assert aggregate.coverage.evaluable_candidate_runs == 3
    group = aggregate.sampling.groups[0]
    assert not group.canonical_valid
    assert group.invalid_reason == "infrastructure_error"
    assert all(not entry.valid and entry.value is None for entry in group.entries)
    assert aggregate.failure_taxonomy.model_infrastructure == {"transport": 1}
    assert sum(aggregate.failure_taxonomy.candidate_outcomes.values()) == 3


def test_preartifact_runtime_failure_remains_infrastructure_data(tmp_path: Path) -> None:
    config = experiment_config(
        tmp_path / "preartifact-infrastructure",
        tasks=["and-gate-basic"],
        seeds=[3],
        samples=2,
        pass_k=[1, 2],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
    )
    plan = _planner().build(config)

    def child(item: PlanItem, run_config: RunConfig) -> RunResult:
        if item.sample_index == 1:
            raise RuntimeExecutionError("synthetic runtime outage before child artifacts")
        return offline_service().run(run_config)

    result = _runner(child_executor=child).run(plan)
    aggregate = ReportBuilder().build(result.experiment_dir)

    assert result.exit_code == 4
    assert result.infrastructure_failures == 1
    assert aggregate.coverage.valid_terminal_artifacts == 1
    assert aggregate.coverage.evaluable_candidate_runs == 1
    assert aggregate.coverage.infrastructure_error_runs == 1
    assert aggregate.coverage.missing_plan_items == 1
    assert aggregate.failure_taxonomy.runtime_sandbox == {"RuntimeExecutionError": 1}
    group = aggregate.sampling.groups[0]
    assert (group.expected_n, group.observed_n, group.missing_count) == (2, 2, 0)
    assert group.infrastructure_error_count == 1
    assert group.invalid_reason == "infrastructure_error"
    assert all(entry.value is None for entry in group.entries)


def test_resume_reuses_valid_children_and_executes_only_missing(tmp_path: Path) -> None:
    config = experiment_config(tmp_path / "resume")
    plan = _planner().build(config)
    first_calls: list[int] = []

    def interrupting(item: PlanItem, run_config: RunConfig) -> RunResult:
        index = item.plan_index
        first_calls.append(index)
        if len(first_calls) == 3:
            raise KeyboardInterrupt
        return offline_service().run(run_config)

    with pytest.raises(KeyboardInterrupt):
        _runner(child_executor=interrupting).run(plan)
    state = json.loads((config.output.root / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "interrupted"
    assert state["valid_terminal_count"] == 2

    resume_calls: list[int] = []

    def completing(item: PlanItem, run_config: RunConfig) -> RunResult:
        resume_calls.append(item.plan_index)
        return offline_service().run(run_config)

    result = _runner(child_executor=completing).resume(config.output.root)
    assert result.exit_code == 0
    assert resume_calls == [2, 3, 4, 5, 6, 7]
    assert result.manifest.config_hash == plan.config_hash
    assert result.manifest.plan_hash == plan.plan_hash
    events = [
        json.loads(line)
        for line in (result.experiment_dir / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    reused = [event for event in events if event["event_type"] == "plan_item_reused_on_resume"]
    assert [event["plan_index"] for event in reused] == [0, 1]
    assert all(event["detail"] == {"model_calls": 0, "runtime_calls": 0} for event in reused)

    clean_config = config.model_copy(
        update={"output": config.output.model_copy(update={"root": tmp_path / "clean"})}
    )
    clean = _runner().run(_planner().build(clean_config))
    resumed_aggregate = ReportBuilder().build(result.experiment_dir).model_dump(mode="json")
    clean_aggregate = ReportBuilder().build(clean.experiment_dir).model_dump(mode="json")
    for payload in (resumed_aggregate, clean_aggregate):
        payload["input_set_hash"] = "runtime-noise"
        wall_time = payload["efficiency_resolved"]["wall_time_s"]
        wall_time["mean"] = None
        wall_time["median"] = None
    assert resumed_aggregate == clean_aggregate

    def normalized_csv(root: Path) -> list[dict[str, str]]:
        rows = list(
            csv.DictReader(StringIO((root / "reports" / "runs.csv").read_text(encoding="utf-8")))
        )
        for row in rows:
            for field in ("run_id", "relative_run_path", "wall_time_s"):
                row[field] = "runtime-noise"
        return rows

    assert normalized_csv(result.experiment_dir) == normalized_csv(clean.experiment_dir)

    changed = config.model_copy(
        update={"execution": config.execution.model_copy(update={"max_workers": 2})}
    )
    with pytest.raises(ConfigurationError, match="configuration hash differs"):
        _runner().resume(config.output.root, supplied_config=changed)


def test_strict_model_process_resume_never_launches_an_authorized_item_twice(
    tmp_path: Path,
) -> None:
    config = experiment_config(
        tmp_path / "strict-resume",
        tasks=["and-gate-basic"],
        mode="chat",
        systems=[
            {
                "id": "chat",
                "agent": {"id": "single-turn"},
                "model": {"id": "static-and-gate-mixed"},
            }
        ],
        seeds=[0],
    )
    config = config.model_copy(
        update={
            "execution": config.execution.model_copy(
                update={
                    "max_model_processes": 1,
                    "resume_model_process_policy": "never_rerun_after_authorization",
                    "seal_plan_before_execution": True,
                    "frozen_campaign_identity": {"campaign": "strict_resume_zero_call_test"},
                }
            )
        }
    )
    plan = _planner().build(config)
    first_calls = 0

    def interrupt_after_authorization(
        _item: PlanItem,
        _run_config: RunConfig,
    ) -> RunResult:
        nonlocal first_calls
        first_calls += 1
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _runner(child_executor=interrupt_after_authorization).run(plan)
    assert first_calls == 1
    ledger = [
        json.loads(line)
        for line in (config.output.root / "process-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(ledger) == 1
    assert ledger[0]["authorization_state"] == "launch_authorized"
    assert ledger[0]["retry"] is False

    def forbidden(_item: PlanItem, _run_config: RunConfig) -> RunResult:
        raise AssertionError("strict resume must not relaunch an authorized item")

    resumed = _runner(child_executor=forbidden).resume(config.output.root)
    assert resumed.exit_code == 4
    assert resumed.state.authorized_model_process_count == 1
    records = [
        json.loads(line)
        for line in (resumed.experiment_dir / "run_index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(records) == 1
    assert records[0]["terminal_status"] == "interrupted_after_model_authorization"
    assert records[0]["child_exit_category"] == "model_process_authorization_consumed"


def test_prepare_seals_plan_and_generic_infrastructure_breaker_checkpoints(
    tmp_path: Path,
) -> None:
    config = experiment_config(
        tmp_path / "scale-controls",
        tasks=["and-gate-basic", "counter-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0, 1],
    )
    config = config.model_copy(
        update={
            "execution": config.execution.model_copy(
                update={
                    "max_total_infrastructure_failures": 2,
                    "summary_checkpoint_interval": 1,
                    "seal_plan_before_execution": True,
                }
            )
        }
    )
    plan = _planner().build(config)
    runner = _runner(
        child_executor=lambda _item, _config: (_ for _ in ()).throw(
            RuntimeExecutionError("shared synthetic outage")
        )
    )
    root = runner.prepare(plan)
    assert stat.S_IMODE((root / "plan.jsonl").stat().st_mode) & 0o222 == 0
    assert not (root / "process-ledger.jsonl").read_text(encoding="utf-8")
    audit = json.loads((root / "plan-audit.json").read_text(encoding="utf-8"))
    assert audit["planned_item_count"] == 4
    assert audit["plan_hash"] == plan.plan_hash

    result = runner.resume(root)
    assert result.exit_code == 4
    assert result.state.terminal_count == 2
    checkpoints = [
        json.loads(line)
        for line in (root / "summary-checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [checkpoint["terminal_count"] for checkpoint in checkpoints] == [1, 2]
    events = [
        json.loads(line)
        for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    breaker = [event for event in events if event["event_type"] == "circuit_breaker_opened"]
    assert breaker[-1]["detail"]["reason"] == "total_infrastructure_failures:2"


def test_resume_recovers_complete_child_created_before_parent_index_write(
    tmp_path: Path,
) -> None:
    config = experiment_config(
        tmp_path / "orphan-recovery",
        tasks=["and-gate-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0],
    )
    plan = _planner().build(config)

    def complete_then_interrupt(_item: PlanItem, run_config: RunConfig) -> RunResult:
        offline_service().run(run_config)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _runner(child_executor=complete_then_interrupt).run(plan)
    assert not (config.output.root / "run_index.jsonl").read_text(encoding="utf-8").strip()
    assert len(list((config.output.root / "runs").iterdir())) == 1

    def forbidden(_item: PlanItem, _run_config: RunConfig) -> RunResult:
        raise AssertionError("recovered valid child must not execute again")

    resumed = _runner(child_executor=forbidden).resume(config.output.root)
    assert resumed.exit_code == 0
    records = [
        json.loads(line)
        for line in (resumed.experiment_dir / "run_index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(records) == 1
    assert records[0]["artifact_validation_status"] == "valid"
    events = [
        json.loads(line)
        for line in (resumed.experiment_dir / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(event["event_type"] == "plan_item_reused_on_resume" for event in events)


def test_resume_rejects_symlinked_parent_directories(tmp_path: Path) -> None:
    config = experiment_config(
        tmp_path / "parent-directory-symlink",
        tasks=["and-gate-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0],
    )
    result = _runner().run(_planner().build(config))
    log_path = result.experiment_dir / "logs" / "batch.log"
    log_path.unlink()
    log_path.parent.rmdir()
    outside = tmp_path / "outside-logs"
    outside.mkdir()
    (result.experiment_dir / "logs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="parent path must be a real directory"):
        _runner().resume(result.experiment_dir)


def test_corrupt_attempt_is_preserved_replaced_and_excluded(tmp_path: Path) -> None:
    config = experiment_config(
        tmp_path / "corrupt",
        tasks=["and-gate-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0],
    )
    runner = _runner()
    first = runner.run(_planner().build(config))
    child = load_report_inputs(first.experiment_dir).valid_runs[0]
    score_path = first.experiment_dir / child.relative_path / "scorecard.json"
    score_path.write_text(score_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    calls: list[int] = []

    def rerun(item: PlanItem, run_config: RunConfig) -> RunResult:
        calls.append(item.plan_index)
        return offline_service().run(run_config)

    resumed = _runner(child_executor=rerun).resume(first.experiment_dir)
    assert calls == [0]
    records = [
        json.loads(line)
        for line in (resumed.experiment_dir / "run_index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [(record["attempt"], record["artifact_validation_status"]) for record in records] == [
        (1, "corrupt"),
        (2, "valid"),
    ]
    assert resumed.state.valid_terminal_count == 1
    assert resumed.state.corrupt_attempt_count == 1
    aggregate = ReportBuilder().build(resumed.experiment_dir)
    assert aggregate.coverage.valid_terminal_artifacts == 1
    assert aggregate.coverage.corrupt_incompatible_artifacts == 1
    assert aggregate.invalid_inputs[0].attempt == 1


def test_zero_denominators_csv_markdown_and_safe_discovery(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    aggregate = ReportBuilder().build(empty)
    assert aggregate.resolved_rate_evaluable.value is None
    assert aggregate.resolved_rate_evaluable.denominator == 0
    assert aggregate.resolved_rate_planned.value is None
    assert aggregate.evaluation_completion_rate.value is None

    csv_text = render_csv(
        [
            {
                "experiment_id": "safe",
                "plan_index": 1,
                "attempt": 1,
                "task_id": '=HYPERLINK("bad")',
                "model_id": "+cmd",
                "agent_id": "@agent",
                "failure_category": "-1",
            }
        ]
    )
    row = next(csv.DictReader(StringIO(csv_text)))
    assert list(row) == CSV_COLUMNS
    assert row["task_id"].startswith("'=")
    assert row["model_id"].startswith("'+")
    assert row["agent_id"].startswith("'@")
    assert row["failure_category"].startswith("'-")
    assert "\x1b" not in render_csv([{"failure_category": "bad\x1bvalue"}])
    escaped = markdown_escape("<script>|[task]`code`\n")
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped
    assert "\\|" in escaped and "\\[task\\]" in escaped
    assert "\x7f" not in markdown_escape("bad\x7fvalue")

    target = tmp_path / "outside"
    target.mkdir()
    link = empty / "linked-run"
    link.symlink_to(target, target_is_directory=True)
    inputs = load_report_inputs(empty)
    assert inputs.invalid_inputs[0].category == "symlink_rejected"
    root_link = tmp_path / "root-link"
    root_link.symlink_to(empty, target_is_directory=True)
    with pytest.raises(ConfigurationError, match="symlink"):
        load_report_inputs(root_link)
    nested = target / "nested"
    nested.mkdir()
    intermediate_link = tmp_path / "intermediate-link"
    intermediate_link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ConfigurationError, match="symlink"):
        load_report_inputs(intermediate_link / "nested")


def _write_profiled_run(
    root: Path,
    *,
    profile_hash: str,
    release_id: str,
    verifier_hash: str | None = None,
) -> Path:
    result = offline_service().run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            agent="scripted",
            output=root,
        )
    )
    effective_verifier = verifier_hash or result.manifest.verifier_hash
    manifest = result.manifest.model_copy(
        update={
            "release_id": release_id,
            "requested_toolchain_profile_id": "educational-area",
            "declared_profile_hash": "d" * 64,
            "resolved_profile_hash": profile_hash,
            "reference_candidate_hash": "e" * 64,
            "verifier_hash": effective_verifier,
        }
    )
    ppa = PPAMetrics(
        profile_id="educational-area",
        profile_version="1.0.0",
        resolved_profile_hash=profile_hash,
        eligible=True,
        area=10.0,
        area_unit="educational_cell_area",
        reference_area=12.0,
        area_ratio=1.2,
    )
    reproducibility = result.scorecard.reproducibility.model_copy(
        update={"verifier_hash": effective_verifier}
    )
    score = result.scorecard.model_copy(
        update={
            "quality": QualityMetrics(ppa=ppa),
            "reproducibility": reproducibility,
        }
    )
    dump_json(result.run_dir / "run_manifest.json", manifest)
    dump_json(result.run_dir / "scorecard.json", score)
    return result.run_dir


def test_area_profiles_and_mixed_compatibility_are_partitioned(tmp_path: Path) -> None:
    root = tmp_path / "runs-root"
    _write_profiled_run(
        root / "first",
        profile_hash="a" * 64,
        release_id="release-a",
    )
    _write_profiled_run(
        root / "second",
        profile_hash="b" * 64,
        release_id="release-b",
        verifier_hash="c" * 64,
    )
    aggregate = ReportBuilder().build(root)
    assert len(aggregate.quality_partitions) == 2
    assert len(aggregate.compatibility_aggregates) == 2
    assert aggregate.resolved_rate_evaluable.value is None
    assert (
        aggregate.resolved_rate_evaluable.unavailable_reason
        == "mixed_release_or_correctness_partitions"
    )
    assert {partition.resolved_profile_hash for partition in aggregate.quality_partitions} == {
        "a" * 64,
        "b" * 64,
    }
    assert all(partition.eligible_run_count == 1 for partition in aggregate.quality_partitions)
    assert all(
        partition.area_unit == "educational_cell_area" for partition in aggregate.quality_partitions
    )
    assert any("suite release/source" in warning.lower() for warning in aggregate.warnings)
    assert any("correctness definitions" in warning.lower() for warning in aggregate.warnings)
    assert any("area profiles" in warning.lower() for warning in aggregate.warnings)
    assert aggregate.metadata["quality_scope"] == "profile-relative synthesis area only"


def test_batch_internal_exception_is_structured_and_not_silently_candidate_data(
    tmp_path: Path,
) -> None:
    config = experiment_config(
        tmp_path / "internal",
        tasks=["and-gate-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0],
    )

    def broken(_item: PlanItem, _run_config: RunConfig) -> RunResult:
        raise AssertionError("synthetic evaluator bug")

    result = _runner(child_executor=broken).run(_planner().build(config))
    assert result.exit_code == 5
    assert result.state.status == "failed_internal"
    record = json.loads(
        (result.experiment_dir / "run_index.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["artifact_validation_status"] == "missing"
    assert record["child_exit_category"] == "internal_verigym_error"
    assert record["infrastructure_error"] is False
    aggregate = ReportBuilder().build(result.experiment_dir)
    assert aggregate.coverage.evaluable_candidate_runs == 0
    assert aggregate.coverage.missing_plan_items == 1
    assert aggregate.failure_taxonomy.candidate_outcomes == {}
    assert aggregate.invalid_inputs[0].category == "missing"


def test_report_continues_on_out_of_range_parent_index(tmp_path: Path) -> None:
    config = experiment_config(
        tmp_path / "out-of-range-index",
        tasks=["and-gate-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0],
    )
    result = _runner().run(_planner().build(config))
    index_path = result.experiment_dir / "run_index.jsonl"
    record = json.loads(index_path.read_text(encoding="utf-8"))
    record["plan_index"] = 999
    index_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    reports = ReportService().generate_all(result.experiment_dir)
    assert reports.aggregate.coverage.valid_terminal_artifacts == 0
    assert reports.aggregate.invalid_inputs[0].category == "plan_mismatch"
    rows = list(csv.DictReader(StringIO(reports.csv_path.read_text(encoding="utf-8"))))
    assert [int(row["plan_index"]) for row in rows] == [0, 999]


def test_frozen_task_mismatch_fails_before_model_or_runtime_output(tmp_path: Path) -> None:
    service = offline_service()
    model = service.registries.models.get("static-and-gate-mixed")
    with pytest.raises(ConfigurationError, match="task identity changed"):
        service.run(
            RunConfig(
                task_id="toy-rtl/and-gate-basic",
                mode="chat",
                agent="single-turn",
                model="static-and-gate-mixed",
                output=tmp_path / "must-not-exist",
                expected_task_hash="0" * 64,
                expected_source_hash="1" * 64,
            )
        )
    assert model.call_count == 0
    assert not (tmp_path / "must-not-exist").exists()
