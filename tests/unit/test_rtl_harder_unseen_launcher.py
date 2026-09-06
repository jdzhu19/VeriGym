from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
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


def _observation(cell: object, launcher: ModuleType) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_count=1,
        requested_model_id=cell.model_id,
        observed_model_id=None,
        effective_reasoning_effort=cell.reasoning_effort,
        harness_id=cell.agent_version_id,
        agent_version_hash=cell.agent_version_hash,
        prompt_contract_hash=launcher.FUNCTIONAL_V3_PROMPT_HASH,
        tool_policy_fingerprint=launcher.FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
    )


def _execution_result(
    root: Path,
    config: RunConfig,
    cell: object,
    launcher: ModuleType,
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
        manifest=SimpleNamespace(external_agent_observations=[_observation(cell, launcher)]),
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
        launcher: ModuleType,
        outcomes: list[dict[str, object]],
    ) -> None:
        self.root = root
        self.cell = cell
        self.launcher = launcher
        self.outcomes = outcomes
        self.calls = 0

    def run(self, config: RunConfig) -> SimpleNamespace:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return _execution_result(self.root, config, self.cell, self.launcher, **outcome)


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
    outcomes[2] = {
        "failure": SimpleNamespace(kind="policy", infrastructure=False),
        "resolved": False,
    }
    service = _FakeService(tmp_path, cell, launcher, outcomes)

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
    assert [record["status"] for record in records[:3]] == [
        "contained_model_failure",
        "verifier_rejection",
        "policy_failure",
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
    service = _FakeService(tmp_path, cell, launcher, outcomes)

    with pytest.raises(launcher.CampaignInfrastructureError, match="infrastructure failure"):
        launcher._execute_exactly_twelve(
            service,
            _configs(output, launcher),
            output,
            cell=cell,
        )

    assert service.calls == 2


def test_execution_resumes_after_completed_prefix_without_retry(tmp_path: Path) -> None:
    launcher = _launcher_module()
    cell = launcher._CELLS["mini-medium"]
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    configs = _configs(output, launcher)
    completed = [_execution_result(tmp_path, config, cell, launcher) for config in configs[:9]]
    ledger = [
        {
            "ordinal": ordinal,
            "run_id": config.run_id,
            "task_id": config.task_id,
            "sample_index": config.sample_index,
            "authorization_granted": True,
            "process_started": True,
            "identity_observation_count": 1,
            "provider_observation_recorded": True,
            "retry_count": 0,
            "resolved": True,
            "status": "completed",
        }
        for ordinal, config in enumerate(configs[:9], start=1)
    ]
    ledger.append(
        {
            "ordinal": 10,
            "run_id": configs[9].run_id,
            "task_id": configs[9].task_id,
            "sample_index": configs[9].sample_index,
            "authorization_granted": True,
            "process_started": False,
            "identity_observation_count": 0,
            "provider_observation_recorded": False,
            "retry_count": 0,
            "status": "authorized",
        }
    )
    service = _FakeService(tmp_path, cell, launcher, [{}, {}, {}])

    results = launcher._execute_exactly_twelve(
        service,
        configs,
        output,
        cell=cell,
        initial_results=completed,
        initial_ledger=ledger,
    )
    stored = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == 12
    assert service.calls == 3
    assert len(stored) == 12
    assert stored[9]["retry_count"] == 0
    assert [record["ordinal"] for record in stored] == list(range(1, 13))


def test_execution_rejects_a_started_pending_resume_slot(tmp_path: Path) -> None:
    launcher = _launcher_module()
    cell = launcher._CELLS["mini-medium"]
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    configs = _configs(output, launcher)
    ledger = [
        {
            "ordinal": 1,
            "run_id": configs[0].run_id,
            "task_id": configs[0].task_id,
            "sample_index": configs[0].sample_index,
            "authorization_granted": True,
            "process_started": True,
            "identity_observation_count": 0,
            "provider_observation_recorded": False,
            "retry_count": 0,
            "status": "authorized",
        }
    ]
    service = _FakeService(tmp_path, cell, launcher, [{} for _ in range(12)])

    with pytest.raises(Exception, match="pending authorization is not resumable"):
        launcher._execute_exactly_twelve(
            service,
            configs,
            output,
            cell=cell,
            initial_results=[],
            initial_ledger=ledger,
        )

    assert service.calls == 0


def test_broker_environment_creates_new_root_and_reuses_existing_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _launcher_module()
    monkeypatch.delenv("VERIGYM_CODEX_BROKER_ROOT", raising=False)
    # Respect TMPDIR on the site and the runner default elsewhere; never require site paths in CI.
    with tempfile.TemporaryDirectory(prefix="bg-") as temporary:
        root = Path(temporary)
        fresh = root / "new"

        launcher._configure_broker_environment(fresh, create=True)

        assert fresh.is_dir()
        assert launcher.os.environ["VERIGYM_CODEX_BROKER_ROOT"] == str(fresh)
        existing = root / "old"
        existing.mkdir()
        launcher._configure_broker_environment(existing, create=False)
        assert launcher.os.environ["VERIGYM_CODEX_BROKER_ROOT"] == str(existing)


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
