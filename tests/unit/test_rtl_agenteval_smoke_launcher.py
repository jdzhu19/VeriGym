from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from verigym_codex_cli.agenteval_agent import CodexCliAgentEvalAdapter

from tests.milestone9_helpers import offline_service
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig


def _launcher_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtl_agenteval_codex_smoke.py"
    spec = importlib.util.spec_from_file_location("rtl_agenteval_smoke_test_module", path)
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


def test_launcher_preserves_all_prelaunch_agent_resolutions() -> None:
    launcher = _launcher_module()
    service = offline_service()
    service.registries.agents.register(CodexCliAgentEvalAdapter())
    runtime = service.registries.runtimes.get("local").descriptor
    config = RunConfig(
        task_id="repo-rtl/counter-wrap",
        mode=InteractionMode.AGENT,
        agent="codex-cli-agenteval-agent",
        agent_options={"max_completion_calls": 1},
        runtime="local",
    )

    frozen = launcher._freeze_run_config(
        service,
        config,
        runtime_descriptor=runtime,
        expected_profile=None,
    )

    assert frozen.expected_prompt_policy == frozen.resolved_prompt_policy
    assert frozen.expected_prompt_policy_hash == frozen.resolved_prompt_policy_hash
    assert frozen.expected_agent_configuration_hash == frozen.resolved_agent_configuration_hash
    assert frozen.expected_action_protocol == frozen.resolved_action_protocol
    assert frozen.expected_agent_feedback_contract == frozen.resolved_agent_feedback_contract


def test_commercial_diagnostic_scan_allows_only_local_mcp_configuration() -> None:
    launcher = _launcher_module()

    assert launcher._COMMERCIAL_DIAGNOSTIC.search(b"mcp_servers.verigym.command") is None
    assert launcher._COMMERCIAL_DIAGNOSTIC.search(b"mcp_server_profile_id") is not None
    assert launcher._COMMERCIAL_DIAGNOSTIC.search(b"license server unavailable") is not None


def test_broker_regression_qualification_exercises_empty_visible_files(tmp_path: Path) -> None:
    launcher = _launcher_module()
    visible = tmp_path / "visible"
    visible.mkdir()
    (visible / "completion.txt").write_text("", encoding="utf-8")

    class Service:
        def load_task(self, task_id: str, config: object) -> tuple[object, object, object]:
            del task_id, config
            return object(), object(), SimpleNamespace(visible_root=visible)

    configs = {key: object() for key in ("counter", "up_down", "verilog_eval", "rtl_repo")}
    qualification = launcher._repository_broker_regression_qualification(  # noqa: SLF001
        Service(),  # type: ignore[arg-type]
        configs,  # type: ignore[arg-type]
    )

    assert qualification["passed"] is True
    assert qualification["model_calls"] == 0
    assert qualification["empty_file_views_checked"] == 8
    assert all(record["empty_files_checked"] == 1 for record in qualification["records"])


def _configs(output: Path) -> list[RunConfig]:
    return [
        RunConfig(task_id=f"fake/task-{index}", output=output / "runs", run_id=f"run-{index}")
        for index in range(4)
    ]


def _fake_result(
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
        return _fake_result(self.root, config, **outcome)


def test_launcher_continues_contained_failures_and_records_real_processes(
    tmp_path: Path,
) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    model_failure = SimpleNamespace(kind="model", infrastructure=False)
    policy_failure = SimpleNamespace(kind="policy", infrastructure=False)
    service = _FakeService(
        tmp_path,
        [
            {"failure": model_failure, "resolved": False},
            {"resolved": False},
            {"failure": policy_failure, "resolved": False},
            {},
        ],
    )

    results = launcher._execute_exactly_four(service, _configs(output), output)
    ledger = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == 4
    assert service.calls == 4
    assert [record["status"] for record in ledger] == [
        "contained_model_failure",
        "verifier_rejection",
        "policy_failure",
        "completed",
    ]
    assert all(record["authorization_granted"] for record in ledger)
    assert all(record["process_started"] for record in ledger)
    assert all(record["provider_observation_recorded"] for record in ledger)
    assert all(record["retry_count"] == 0 for record in ledger)
    assert all("authorized_process_count" not in record for record in ledger)


def test_launcher_stops_immediately_after_infrastructure_failure(tmp_path: Path) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    infrastructure = SimpleNamespace(kind="runtime", infrastructure=True)
    service = _FakeService(tmp_path, [{}, {"failure": infrastructure}, {}, {}])

    with pytest.raises(launcher.CampaignInfrastructureError, match="infrastructure-invalid"):
        launcher._execute_exactly_four(service, _configs(output), output)

    ledger = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]
    assert service.calls == 2
    assert len(ledger) == 2
    assert ledger[-1]["status"] == "infrastructure_failure"
    assert ledger[-1]["retry_count"] == 0


def test_launcher_finalizes_after_fourth_infrastructure_failure(tmp_path: Path) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    infrastructure = SimpleNamespace(kind="runtime", infrastructure=True)
    service = _FakeService(tmp_path, [{}, {}, {}, {"failure": infrastructure}])

    results = launcher._execute_exactly_four(service, _configs(output), output)

    ledger = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]
    assert len(results) == 4
    assert service.calls == 4
    assert len(ledger) == 4
    assert ledger[-1]["status"] == "infrastructure_failure"
    assert ledger[-1]["retry_count"] == 0


def test_launcher_does_not_claim_a_process_started_during_preflight_failure(
    tmp_path: Path,
) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)

    class FailingService:
        def run(self, config: RunConfig) -> SimpleNamespace:
            del config
            raise RuntimeError("preflight failed")

    with pytest.raises(RuntimeError, match="preflight"):
        launcher._execute_exactly_four(FailingService(), _configs(output), output)

    record = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"][0]
    assert record["authorization_granted"] is True
    assert record["process_started"] is False
    assert record["provider_observation_recorded"] is False
    assert record["retry_count"] == 0


def test_smoke_v5_identity_and_release_preconditions_are_frozen(tmp_path: Path) -> None:
    launcher = _launcher_module()
    release_hash = "a" * 64
    profile = SimpleNamespace(
        metadata={
            "agent_feedback_worker_release_protocol": "commercial_worker_release.v1",
            "agent_feedback_worker_release_hash": release_hash,
            "commercial_worker_release_protocol": "commercial_worker_release.v1",
            "commercial_worker_release_hash": release_hash,
        }
    )

    assert launcher._CAMPAIGN_ID.endswith("smoke-v5")
    assert launcher._require_commercial_worker_release(profile) == release_hash
    with pytest.raises(Exception, match="release contract"):
        launcher._require_commercial_worker_release(SimpleNamespace(metadata={}))

    plan_path = tmp_path / "smoke-v2-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "campaign_id": "rtl-agenteval-codex-gpt54-xhigh-smoke-v2",
                "profiles": {
                    name: {"resolved_hash": "b" * 64}
                    for name in ("counter_dc", "counter_open", "up_down_dc", "up_down_open")
                },
            }
        ),
        encoding="utf-8",
    )
    prepared = {
        name: SimpleNamespace(resolved=SimpleNamespace(resolved_profile_hash="c" * 64))
        for name in ("counter_dc", "counter_open", "up_down_dc", "up_down_open")
    }
    audit = launcher._smoke_v2_identity_audit(plan_path, prepared)

    assert audit["model_calls"] == 0
    assert audit["drift_observed"] is True
    assert all(
        record["changed_components"] == list(launcher.RESOLVED_PROFILE_IDENTITY_COMPONENTS)
        for record in audit["records"]
    )


def test_smoke_v5_pilot_gate_requires_all_acceptance_evidence(tmp_path: Path) -> None:
    launcher = _launcher_module()
    results = []
    for index in range(4):
        run_dir = tmp_path / f"run-{index}"
        evidence = run_dir / "artifacts" / "codex_cli"
        evidence.mkdir(parents=True)
        (evidence / "process.json").write_text("{}", encoding="utf-8")
        (evidence / "identity.json").write_text("{}", encoding="utf-8")
        (evidence / "broker.json").write_text(
            json.dumps({"finished": True, "finish_calls": 1}), encoding="utf-8"
        )
        candidate_hash = f"{index + 1:x}" * 64
        profile_hash = "a" * 64 if index < 2 else None
        evaluations = (
            [
                SimpleNamespace(
                    passed=True,
                    metrics=object(),
                    candidate_hash=candidate_hash,
                    profile_hash=profile_hash,
                )
            ]
            if index < 2
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
        results.append(
            SimpleNamespace(
                run_dir=run_dir,
                manifest=SimpleNamespace(
                    run_id=f"run-{index}",
                    task_id=launcher._TASKS[index],
                    candidate_hash=candidate_hash,
                    resolved_profile_hash=profile_hash,
                    external_agent_observations=[observation],
                    agent_feedback_evaluations=evaluations,
                ),
                scorecard=SimpleNamespace(
                    resolved=True,
                    correctness=SimpleNamespace(infrastructure_error=False),
                    failure=None,
                ),
            )
        )

    summary = launcher._campaign_summary(
        results,
        {"all_valid": True},
        {"passed": True},
    )

    assert summary["fully_successful"] is True
    assert summary["pilot_authorized"] is True
    assert summary["benchmark_score_claimed"] is False
    assert summary["codex_processes_started"] == 4
    assert summary["provider_observations_recorded"] == 4

    results[0].scorecard.failure = SimpleNamespace(kind="policy", infrastructure=False)
    rejected = launcher._campaign_summary(results, {"all_valid": True}, {"passed": True})
    assert rejected["fully_successful"] is False
    assert rejected["pilot_authorized"] is False
