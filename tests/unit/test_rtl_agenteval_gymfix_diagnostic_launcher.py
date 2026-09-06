from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from verigym.schemas.run import RunConfig


def _launcher_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtl_agenteval_codex_gymfix_diagnostic.py"
    spec = importlib.util.spec_from_file_location("rtl_agenteval_gymfix_test_module", path)
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


def test_diagnostic_matrix_freezes_exactly_six_single_process_slots() -> None:
    launcher = _launcher_module()
    specs = launcher._RUN_SPECS

    assert len(specs) == 6
    assert len({spec.run_id for spec in specs}) == 6
    assert all(spec.run_id.startswith(f"{ordinal:02d}-") for ordinal, spec in enumerate(specs, 1))
    assert [(spec.source_key, spec.profile_name, spec.ppa) for spec in specs[:2]] == [
        ("counter", "counter_open", True),
        ("counter", "counter_dc", True),
    ]
    assert [spec.task_id.rsplit("/", 1)[-1] for spec in specs[2:]] == [
        "test-000002",
        "test-000003",
        "test-000005",
        "test-000004",
    ]
    assert all("official-parquet-v1-agent-eval-v2" in spec.task_id for spec in specs[2:])
    assert launcher._PPA_RUN_IDS == {"01-counter-open", "02-counter-dc"}


def test_diagnostic_pilot_receipt_accepts_completed_readonly_pilot(tmp_path: Path) -> None:
    launcher = _launcher_module()
    summary = {
        "campaign_id": "rtl-agenteval-codex-gpt54-xhigh-pilot-v1",
        "pilot_complete": True,
        "infrastructure_complete": True,
        "fully_successful": False,
        "benchmark_score_claimed": False,
        "codex_processes_started": 14,
        "provider_observations_recorded": 14,
        "automatic_retries": 0,
        "runs": [
            {"process_started": True, "provider_observation_recorded": True} for _ in range(14)
        ],
    }
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_pilot_summary(path)

    assert receipt["read_only"] is True
    assert receipt["fully_successful"] is False
    assert launcher.smoke._SHA256.fullmatch(receipt["summary_hash"])

    summary["runs"][0]["provider_observation_recorded"] = False
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="complete read-only pilot-v1"):
        launcher._validate_pilot_summary(path)


def _configs(output: Path, launcher: ModuleType) -> list[RunConfig]:
    return [
        RunConfig(task_id=spec.task_id, output=output / "runs", run_id=spec.run_id)
        for spec in launcher._RUN_SPECS
    ]


def _observation(launcher: ModuleType) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_count=1,
        requested_model_id="gpt-5.4",
        observed_model_id=None,
        effective_reasoning_effort="xhigh",
        harness_id=launcher.AGENTEVAL_AGENT_VERSION_ID,
        agent_version_hash=launcher.AGENTEVAL_AGENT_VERSION_HASH,
        prompt_contract_hash=launcher.AGENTEVAL_PROMPT_HASH,
        tool_policy_fingerprint=launcher.AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    )


def _execution_result(
    root: Path,
    config: RunConfig,
    launcher: ModuleType,
    *,
    failure: object | None = None,
    infrastructure_error: bool = False,
    resolved: bool = True,
    observation_count: int = 1,
) -> SimpleNamespace:
    run_dir = root / "actual-runs" / str(config.run_id)
    evidence = run_dir / "artifacts" / "codex_cli"
    evidence.mkdir(parents=True)
    (evidence / "process.json").write_text("{}", encoding="utf-8")
    (evidence / "identity.json").write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        run_dir=run_dir,
        manifest=SimpleNamespace(
            external_agent_observations=[_observation(launcher) for _ in range(observation_count)]
        ),
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
        launcher: ModuleType,
        outcomes: list[dict[str, object]],
    ) -> None:
        self.root = root
        self.launcher = launcher
        self.outcomes = outcomes
        self.calls = 0

    def run(self, config: RunConfig) -> SimpleNamespace:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return _execution_result(self.root, config, self.launcher, **outcome)


def test_diagnostic_continues_model_failure_and_verifier_rejection_without_retry(
    tmp_path: Path,
) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{} for _ in range(6)]
    outcomes[0] = {
        "failure": SimpleNamespace(kind="model", infrastructure=False),
        "resolved": False,
    }
    outcomes[1] = {"resolved": False}
    service = _FakeService(tmp_path, launcher, outcomes)

    results = launcher._execute_exactly_six(service, _configs(output, launcher), output)
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == 6
    assert service.calls == 6
    assert [record["status"] for record in records[:2]] == [
        "contained_model_failure",
        "verifier_rejection",
    ]
    assert all(record["authorization_granted"] for record in records)
    assert all(record["process_started"] for record in records)
    assert all(record["identity_observation_count"] == 1 for record in records)
    assert all(record["provider_observation_recorded"] for record in records)
    assert all(record["retry_count"] == 0 for record in records)


@pytest.mark.parametrize(
    "outcome",
    [
        {
            "failure": SimpleNamespace(kind="runtime", infrastructure=True),
            "infrastructure_error": True,
        },
        {"failure": SimpleNamespace(kind="policy", infrastructure=False), "resolved": False},
    ],
)
def test_diagnostic_stops_after_infrastructure_or_policy_failure(
    tmp_path: Path,
    outcome: dict[str, object],
) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{}, outcome, {}, {}, {}, {}]
    service = _FakeService(tmp_path, launcher, outcomes)

    with pytest.raises(launcher.CampaignInfrastructureError, match="infrastructure or safety"):
        launcher._execute_exactly_six(service, _configs(output, launcher), output)

    assert service.calls == 2
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]
    assert len(records) == 2
    assert records[-1]["status"] in {"infrastructure_failure", "policy_failure"}
    assert records[-1]["retry_count"] == 0


def test_diagnostic_stops_on_duplicate_identity_observation(tmp_path: Path) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{"observation_count": 2}, {}, {}, {}, {}, {}]
    service = _FakeService(tmp_path, launcher, outcomes)

    with pytest.raises(launcher.CampaignInfrastructureError, match="duplicate"):
        launcher._execute_exactly_six(service, _configs(output, launcher), output)

    assert service.calls == 1


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
        "planned_codex_processes": 6,
        "automatic_retries": 0,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_pilot_v2_authorized": False,
        "run_config_hashes": [str(index) * 64 for index in range(1, 7)],
        "codex": {
            "agent_version_id": launcher.AGENTEVAL_AGENT_VERSION_ID,
            "agent_version_hash": launcher.AGENTEVAL_AGENT_VERSION_HASH,
            "prompt_hash": launcher.AGENTEVAL_PROMPT_HASH,
            "tool_policy_fingerprint": launcher.AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        },
    }


def test_existing_diagnostic_plan_validation_is_exact() -> None:
    launcher = _launcher_module()
    plan = _valid_plan(launcher)

    launcher._validate_existing_plan(plan)

    plan["automatic_retries"] = 1
    with pytest.raises(Exception, match="frozen gym-fix diagnostic"):
        launcher._validate_existing_plan(plan)


def _summary_result(
    launcher: ModuleType,
    tmp_path: Path,
    index: int,
) -> SimpleNamespace:
    spec = launcher._RUN_SPECS[index]
    run_dir = tmp_path / spec.run_id
    evidence = run_dir / "artifacts" / "codex_cli"
    evidence.mkdir(parents=True)
    (evidence / "identity.json").write_text("{}", encoding="utf-8")
    (evidence / "broker.json").write_text(
        json.dumps({"finished": True, "finish_calls": 1}),
        encoding="utf-8",
    )
    (evidence / "process.json").write_text(json.dumps({"timed_out": False}), encoding="utf-8")
    (evidence / "provider-usage.json").write_text(
        json.dumps({"usage_complete": True}),
        encoding="utf-8",
    )
    candidate_hash = str(index + 1) * 64
    profile_hash = "f" * 64 if spec.ppa else None
    evaluations = []
    if spec.ppa:
        evaluations = [
            SimpleNamespace(
                test_id="compile",
                passed=True,
                metrics=None,
                candidate_hash=candidate_hash,
                profile_hash=None,
            ),
            SimpleNamespace(
                test_id="ppa",
                passed=True,
                metrics=object(),
                candidate_hash=candidate_hash,
                profile_hash=profile_hash,
            ),
        ]
    return SimpleNamespace(
        run_dir=run_dir,
        manifest=SimpleNamespace(
            run_id=spec.run_id,
            task_id=spec.task_id,
            candidate_hash=candidate_hash,
            resolved_profile_hash=profile_hash,
            external_agent_observations=[_observation(launcher)],
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


def test_diagnostic_success_requires_six_finishes_resolutions_and_ppa(tmp_path: Path) -> None:
    launcher = _launcher_module()
    results = [_summary_result(launcher, tmp_path, index) for index in range(6)]

    summary = launcher._campaign_summary(
        results,
        {"all_valid": True},
        {"passed": True},
        {"passed": True},
    )

    assert summary["diagnostic_complete"] is True
    assert summary["fully_successful"] is True
    assert summary["codex_processes_started"] == 6
    assert summary["provider_observations_recorded"] == 6
    assert summary["diagnostic_only"] is True
    assert summary["benchmark_score_claimed"] is False
    assert summary["automatic_pilot_v2_authorized"] is False

    results[0].scorecard.quality.ppa.eligible = False
    rejected = launcher._campaign_summary(
        results,
        {"all_valid": True},
        {"passed": True},
        {"passed": True},
    )
    assert rejected["diagnostic_complete"] is True
    assert rejected["fully_successful"] is False


def test_diagnostic_refuses_existing_output_and_has_distinct_opt_in(tmp_path: Path) -> None:
    launcher = _launcher_module()
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "user-data").write_text("preserve", encoding="utf-8")

    with pytest.raises(Exception, match="must not already exist"):
        launcher.smoke._new_path(occupied, "diagnostic output")

    source = Path(launcher.__file__).read_text(encoding="utf-8")
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_GYMFIX_DIAGNOSTIC" in source
    assert '"automatic_retries": 0' in source
    assert '"diagnostic_only": True' in source
    assert '"benchmark_score_claimed": False' in source
    assert (occupied / "user-data").read_text(encoding="utf-8") == "preserve"
