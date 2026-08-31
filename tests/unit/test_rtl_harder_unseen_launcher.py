from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from verigym.schemas.run import RunConfig


def _launcher_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtl_harder_unseen_codex_multi_episode.py"
    spec = importlib.util.spec_from_file_location("rtl_harder_unseen_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts_path = str(path.parent)
    sys.path.insert(0, scripts_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


def test_matrix_is_four_unseen_tasks_by_three_independent_episodes() -> None:
    launcher = _launcher_module()

    assert launcher._NATIVE_TASKS == (
        "Prob140_fsm_hdlc",
        "Prob144_conwaylife",
        "Prob153_gshare",
        "Prob155_lemmings4",
    )
    assert launcher._PREFLIGHT_EXCLUSIONS == {
        "Prob156_review2015_fancytimer": (
            "official reference emitted the native timeout marker after 200000 samples "
            "with zero mismatches"
        )
    }
    assert len(launcher._RUN_SPECS) == 12
    assert len({spec.run_id for spec in launcher._RUN_SPECS}) == 12
    assert [spec.ordinal for spec in launcher._RUN_SPECS] == list(range(1, 13))
    for native_id in launcher._NATIVE_TASKS:
        selected = [spec for spec in launcher._RUN_SPECS if spec.native_id == native_id]
        assert [spec.episode_index for spec in selected] == [0, 1, 2]
    assert not {
        "Prob038_count15",
        "Prob067_countslow",
        "Prob096_review2015_fsmseq",
        "Prob100_fsm3comb",
        "Prob107_fsm1s",
        "Prob118_history_shift",
        "Prob124_rule110",
        "Prob128_fsm_ps2",
        "Prob137_fsm_serial",
        "Prob150_review2015_fsmonehot",
    }.intersection(launcher._NATIVE_TASKS)


def test_cells_support_overall_and_same_model_reasoning_comparisons() -> None:
    launcher = _launcher_module()
    same_model = [launcher._CELLS[key] for key in ("mini-low", "mini-medium", "mini-high")]
    overall = [launcher._CELLS[key] for key in ("mini-low", "mini-high", "full-xhigh")]

    assert {cell.model_id for cell in same_model} == {"gpt-5.4-mini"}
    assert [cell.reasoning_effort for cell in same_model] == ["low", "medium", "high"]
    assert [(cell.model_id, cell.reasoning_effort) for cell in overall] == [
        ("gpt-5.4-mini", "low"),
        ("gpt-5.4-mini", "high"),
        ("gpt-5.4", "xhigh"),
    ]
    assert len({cell.agent_version_hash for cell in launcher._CELLS.values()}) == 4


def _configs(output: Path, launcher: ModuleType) -> list[RunConfig]:
    return [
        RunConfig(
            task_id=spec.task_id,
            output=output / "runs",
            run_id=spec.run_id,
            sample_index=spec.episode_index,
            seed=spec.episode_index,
        )
        for spec in launcher._RUN_SPECS
    ]


def _observation(cell: object) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_count=1,
        requested_model_id=cell.model_id,
        observed_model_id=None,
        effective_reasoning_effort=cell.reasoning_effort,
        harness_id=cell.agent_version_id,
        agent_version_hash=cell.agent_version_hash,
        prompt_contract_hash=("14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9"),
        tool_policy_fingerprint=(
            "5cb057a7cb6722538144acf1e9ef3265eae3c3391af0ab97eb2b96b93e941a1c"
        ),
    )


def _execution_result(
    root: Path,
    config: RunConfig,
    cell: object,
    *,
    failure: object | None = None,
    infrastructure_error: bool = False,
    resolved: bool = True,
) -> SimpleNamespace:
    run_dir = root / "actual-runs" / str(config.run_id)
    evidence = run_dir / "artifacts" / "codex_cli"
    evidence.mkdir(parents=True)
    (evidence / "process.json").write_text("{}", encoding="utf-8")
    (evidence / "identity.json").write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        run_dir=run_dir,
        manifest=SimpleNamespace(external_agent_observations=[_observation(cell)]),
        scorecard=SimpleNamespace(
            resolved=resolved,
            correctness=SimpleNamespace(infrastructure_error=infrastructure_error),
            failure=failure,
        ),
    )


class _FakeService:
    def __init__(
        self,
        root: Path,
        cell: object,
        outcomes: list[dict[str, object]],
    ) -> None:
        self.root = root
        self.cell = cell
        self.outcomes = outcomes
        self.calls = 0

    def run(self, config: RunConfig) -> SimpleNamespace:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return _execution_result(self.root, config, self.cell, **outcome)


def test_execution_continues_model_failures_without_retry(tmp_path: Path) -> None:
    launcher = _launcher_module()
    cell = launcher._CELLS["mini-low"]
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{} for _ in range(12)]
    outcomes[0] = {
        "failure": SimpleNamespace(kind="model", infrastructure=False),
        "resolved": False,
    }
    outcomes[1] = {"resolved": False}
    service = _FakeService(tmp_path, cell, outcomes)

    results = launcher._execute_exactly_twelve(
        service,
        _configs(output, launcher),
        output,
        cell=cell,
    )
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == 12
    assert service.calls == 12
    assert [record["status"] for record in records[:2]] == [
        "contained_model_failure",
        "verifier_rejection",
    ]
    assert all(record["retry_count"] == 0 for record in records)
    assert [record["sample_index"] for record in records[:3]] == [0, 1, 2]


def test_execution_stops_after_infrastructure_failure(tmp_path: Path) -> None:
    launcher = _launcher_module()
    cell = launcher._CELLS["mini-medium"]
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [
        {},
        {
            "failure": SimpleNamespace(kind="runtime", infrastructure=True),
            "infrastructure_error": True,
        },
        *({} for _ in range(10)),
    ]
    service = _FakeService(tmp_path, cell, outcomes)

    with pytest.raises(launcher.CampaignInfrastructureError, match="infrastructure or safety"):
        launcher._execute_exactly_twelve(
            service,
            _configs(output, launcher),
            output,
            cell=cell,
        )

    assert service.calls == 2


def test_wilson_interval_and_progress_are_bounded(tmp_path: Path) -> None:
    launcher = _launcher_module()
    cell = launcher._CELLS["full-xhigh"]
    path = tmp_path / "progress.json"

    assert launcher._wilson_interval(12, 12) == {"lower": 0.757506, "upper": 1.0}
    launcher._record_progress(
        path,
        cell,
        phase="execution",
        status="running",
        completed_processes=5,
        active_process_ordinal=6,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["completed_processes"] == 5
    assert payload["active_process_ordinal"] == 6
    serialized = json.dumps(payload, sort_keys=True)
    assert "/" not in serialized
    assert "task_id" not in serialized

    with pytest.raises(Exception, match="out of range"):
        launcher._record_progress(
            path,
            cell,
            phase="execution",
            status="running",
            completed_processes=13,
        )
