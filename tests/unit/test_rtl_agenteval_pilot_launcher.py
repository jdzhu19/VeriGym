from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from verigym.schemas.run import RunConfig


def _launcher_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtl_agenteval_codex_pilot.py"
    spec = importlib.util.spec_from_file_location("rtl_agenteval_pilot_test_module", path)
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


def _accepted_smoke_summary(launcher: ModuleType) -> dict[str, object]:
    return {
        "campaign_id": launcher.smoke._CAMPAIGN_ID,
        "fully_successful": True,
        "pilot_authorized": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 4,
        "provider_observations_recorded": 4,
        "automatic_retries": 0,
        "runs": [
            {
                "model_identity_valid": True,
                "process_started": True,
                "provider_observation_recorded": True,
                "typed_finish": True,
                "resolved": True,
                "policy_failure": False,
                "infrastructure_failure": False,
            }
            for _ in range(4)
        ],
    }


def test_pilot_matrix_freezes_fourteen_single_process_slots() -> None:
    launcher = _launcher_module()
    specs = launcher._RUN_SPECS

    assert len(specs) == 14
    assert len({spec.run_id for spec in specs}) == 14
    assert all(spec.run_id.startswith(f"{ordinal:02d}-") for ordinal, spec in enumerate(specs, 1))
    assert [(spec.source_key, spec.profile_name, spec.ppa) for spec in specs[:4]] == [
        ("counter", "counter_open", True),
        ("counter", "counter_dc", True),
        ("up_down", "up_down_open", True),
        ("up_down", "up_down_dc", True),
    ]
    assert sum(spec.source_key == "verilog_eval" for spec in specs) == 5
    assert sum(spec.source_key == "rtl_repo" for spec in specs) == 5
    assert len({spec.task_id for spec in specs[4:9]}) == 5
    assert len({spec.task_id for spec in specs[9:]}) == 5
    assert all(spec.profile_name is None and not spec.ppa for spec in specs[4:])


def test_pilot_predecessor_gate_requires_complete_smoke_v7(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    accepted = _accepted_smoke_summary(launcher)
    path.write_text(json.dumps(accepted), encoding="utf-8")

    receipt = launcher._validate_predecessor(path)

    assert receipt["fully_successful"] is True
    assert receipt["pilot_authorized"] is True
    assert launcher.smoke._SHA256.fullmatch(receipt["summary_hash"])

    accepted["runs"][0]["typed_finish"] = False  # type: ignore[index]
    path.write_text(json.dumps(accepted), encoding="utf-8")
    with pytest.raises(Exception, match="per-run acceptance"):
        launcher._validate_predecessor(path)


def _configs(output: Path, launcher: ModuleType) -> list[RunConfig]:
    return [
        RunConfig(task_id=spec.task_id, output=output / "runs", run_id=spec.run_id)
        for spec in launcher._RUN_SPECS
    ]


def _execution_result(
    root: Path,
    config: RunConfig,
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
        manifest=SimpleNamespace(external_agent_observations=[object()]),
        scorecard=SimpleNamespace(
            resolved=resolved,
            correctness=SimpleNamespace(infrastructure_error=infrastructure_error),
            failure=failure,
        ),
    )


class _FakeService:
    def __init__(self, root: Path, outcomes: list[dict[str, object]]) -> None:
        self.root = root
        self.outcomes = outcomes
        self.calls = 0

    def run(self, config: RunConfig) -> SimpleNamespace:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return _execution_result(self.root, config, **outcome)


def test_pilot_continues_contained_failures_without_retries(tmp_path: Path) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{} for _ in range(14)]
    outcomes[0] = {
        "failure": SimpleNamespace(kind="model", infrastructure=False),
        "resolved": False,
    }
    outcomes[1] = {
        "failure": SimpleNamespace(kind="policy", infrastructure=False),
        "resolved": False,
    }
    outcomes[2] = {"resolved": False}
    service = _FakeService(tmp_path, outcomes)

    results = launcher._execute_exactly_fourteen(
        service,
        _configs(output, launcher),
        output,
    )
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == 14
    assert service.calls == 14
    assert [record["status"] for record in records[:3]] == [
        "contained_model_failure",
        "policy_failure",
        "verifier_rejection",
    ]
    assert all(record["process_started"] for record in records)
    assert all(record["provider_observation_recorded"] for record in records)
    assert all(record["retry_count"] == 0 for record in records)


def test_pilot_stops_after_infrastructure_failure(tmp_path: Path) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{} for _ in range(14)]
    outcomes[1] = {
        "failure": SimpleNamespace(kind="runtime", infrastructure=True),
    }
    service = _FakeService(tmp_path, outcomes)

    with pytest.raises(launcher.CampaignInfrastructureError, match="infrastructure-invalid"):
        launcher._execute_exactly_fourteen(
            service,
            _configs(output, launcher),
            output,
        )

    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]
    assert service.calls == 2
    assert len(records) == 2
    assert records[-1]["status"] == "infrastructure_failure"
    assert records[-1]["retry_count"] == 0


def _valid_plan(launcher: ModuleType) -> dict[str, object]:
    return {
        "campaign_id": launcher._CAMPAIGN_ID,
        "run_specs": [
            {
                "run_id": spec.run_id,
                "task_id": spec.task_id,
                "source_key": spec.source_key,
                "profile_name": spec.profile_name,
                "agent_ppa_feedback": spec.ppa,
            }
            for spec in launcher._RUN_SPECS
        ],
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "seed": 0,
        "samples_per_task_profile": 1,
        "planned_codex_processes": 14,
        "automatic_retries": 0,
        "pilot_is_benchmark_score": False,
        "benchmark_score_claimed": False,
        "predecessor_summary_hash": "a" * 64,
        "run_config_hashes": [f"{index:x}" * 64 for index in range(1, 15)],
        "codex": {
            "agent_version_id": launcher.AGENTEVAL_AGENT_VERSION_ID,
            "agent_version_hash": launcher.AGENTEVAL_AGENT_VERSION_HASH,
            "prompt_hash": launcher.AGENTEVAL_PROMPT_HASH,
            "tool_policy_fingerprint": launcher.AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        },
    }


def test_existing_pilot_plan_validation_is_exact() -> None:
    launcher = _launcher_module()
    plan = _valid_plan(launcher)

    launcher._validate_existing_plan(plan)

    plan["automatic_retries"] = 1
    with pytest.raises(Exception, match="frozen pilot-v1"):
        launcher._validate_existing_plan(plan)


def _accepted_pilot_result(
    launcher: ModuleType,
    tmp_path: Path,
    index: int,
) -> SimpleNamespace:
    spec = launcher._RUN_SPECS[index]
    run_dir = tmp_path / spec.run_id
    evidence = run_dir / "artifacts" / "codex_cli"
    evidence.mkdir(parents=True)
    (evidence / "process.json").write_text("{}", encoding="utf-8")
    (evidence / "identity.json").write_text("{}", encoding="utf-8")
    (evidence / "broker.json").write_text(
        json.dumps({"finished": True, "finish_calls": 1}), encoding="utf-8"
    )
    candidate_hash = f"{index + 1:x}" * 64
    profile_hash = "f" * 64 if spec.ppa else None
    evaluations = (
        [
            SimpleNamespace(
                passed=True,
                metrics=object(),
                candidate_hash=candidate_hash,
                profile_hash=profile_hash,
            )
        ]
        if spec.ppa
        else []
    )
    observation = SimpleNamespace(
        invocation_count=1,
        requested_model_id="gpt-5.4",
        observed_model_id="gpt-5.4",
        effective_reasoning_effort="xhigh",
        harness_id=launcher.AGENTEVAL_AGENT_VERSION_ID,
        agent_version_hash=launcher.AGENTEVAL_AGENT_VERSION_HASH,
        prompt_contract_hash=launcher.AGENTEVAL_PROMPT_HASH,
        tool_policy_fingerprint=launcher.AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    )
    return SimpleNamespace(
        run_dir=run_dir,
        manifest=SimpleNamespace(
            run_id=spec.run_id,
            task_id=spec.task_id,
            candidate_hash=candidate_hash,
            resolved_profile_hash=profile_hash,
            external_agent_observations=[observation],
            agent_feedback_evaluations=evaluations,
        ),
        scorecard=SimpleNamespace(
            resolved=True,
            correctness=SimpleNamespace(infrastructure_error=False),
            failure=None,
            quality=SimpleNamespace(
                ppa=SimpleNamespace(eligible=True) if spec.ppa else None,
            ),
        ),
    )


def test_pilot_success_requires_all_processes_finishes_and_ppa(tmp_path: Path) -> None:
    launcher = _launcher_module()
    results = [_accepted_pilot_result(launcher, tmp_path, index) for index in range(14)]

    summary = launcher._campaign_summary(
        results,
        {"all_valid": True},
        {"passed": True},
    )

    assert summary["pilot_complete"] is True
    assert summary["fully_successful"] is True
    assert summary["codex_processes_started"] == 14
    assert summary["provider_observations_recorded"] == 14
    assert summary["pilot_is_benchmark_score"] is False
    assert summary["benchmark_score_claimed"] is False

    results[0].scorecard.quality.ppa.eligible = False
    rejected = launcher._campaign_summary(
        results,
        {"all_valid": True},
        {"passed": True},
    )
    assert rejected["pilot_complete"] is True
    assert rejected["fully_successful"] is False


def test_pilot_execution_has_a_distinct_opt_in_guard() -> None:
    launcher = _launcher_module()
    source = Path(launcher.__file__).read_text(encoding="utf-8")

    assert "VERIGYM_RUN_RTL_AGENT_EVAL_PILOT" in source
    assert '"automatic_retries": 0' in source
    assert '"benchmark_score_claimed": False' in source
