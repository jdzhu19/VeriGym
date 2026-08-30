from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from verigym.schemas.run import RunConfig


def _launcher_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtl_functional_multiturn_codex_14.py"
    spec = importlib.util.spec_from_file_location("rtl_functional_multiturn_test_module", path)
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


def test_matrix_freezes_exactly_fourteen_single_process_slots() -> None:
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
    assert [spec.task_id.rsplit("/", 1)[-1] for spec in specs[4:]] == list(launcher._VE_TASKS)
    assert all("agent_eval_functional_v1" in spec.task_id for spec in specs[:4])
    assert all(launcher._VE_VARIANT in spec.task_id for spec in specs[4:])
    assert launcher._PPA_RUN_IDS == {
        "01-counter-open",
        "02-counter-dc",
        "03-up-down-open",
        "04-up-down-dc",
    }


def _configs(output: Path, launcher: ModuleType) -> list[RunConfig]:
    return [
        RunConfig(task_id=spec.task_id, output=output / "runs", run_id=spec.run_id)
        for spec in launcher._RUN_SPECS
    ]


def _observation(launcher: ModuleType) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_count=1,
        requested_model_id="gpt-5.4-mini",
        observed_model_id=None,
        effective_reasoning_effort="medium",
        harness_id=launcher.FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID,
        agent_version_hash=launcher.FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH,
        prompt_contract_hash=launcher.FUNCTIONAL_AGENTEVAL_PROMPT_HASH,
        tool_policy_fingerprint=launcher.FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT,
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


def test_continues_model_failure_and_verifier_rejection_without_retry(tmp_path: Path) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{} for _ in range(14)]
    outcomes[0] = {
        "failure": SimpleNamespace(kind="model", infrastructure=False),
        "resolved": False,
    }
    outcomes[1] = {"resolved": False}
    service = _FakeService(tmp_path, launcher, outcomes)

    results = launcher._execute_exactly_fourteen(service, _configs(output, launcher), output)
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == 14
    assert service.calls == 14
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
def test_stops_after_infrastructure_or_policy_failure(
    tmp_path: Path,
    outcome: dict[str, object],
) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{}, outcome, *({} for _ in range(12))]
    service = _FakeService(tmp_path, launcher, outcomes)

    with pytest.raises(launcher.CampaignInfrastructureError, match="infrastructure or safety"):
        launcher._execute_exactly_fourteen(service, _configs(output, launcher), output)

    assert service.calls == 2
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]
    assert len(records) == 2
    assert records[-1]["status"] in {"infrastructure_failure", "policy_failure"}
    assert records[-1]["retry_count"] == 0


def test_stops_on_duplicate_identity_observation(tmp_path: Path) -> None:
    launcher = _launcher_module()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{"observation_count": 2}, *({} for _ in range(13))]
    service = _FakeService(tmp_path, launcher, outcomes)

    with pytest.raises(launcher.CampaignInfrastructureError, match="invalid identity evidence"):
        launcher._execute_exactly_fourteen(service, _configs(output, launcher), output)

    assert service.calls == 1


def test_existing_plan_validation_is_exact() -> None:
    launcher = _launcher_module()
    plan = {
        "campaign_id": launcher._CAMPAIGN_ID,
        "run_specs": [launcher._run_spec_payload(spec) for spec in launcher._RUN_SPECS],
        "model": "gpt-5.4-mini",
        "reasoning_effort": "medium",
        "seed": 0,
        "samples_per_task_profile": 1,
        "planned_codex_processes": 14,
        "automatic_retries": 0,
        "benchmark_suites": ["rtllm", "verilog-eval"],
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
        "run_config_hashes": [f"{index:064x}" for index in range(1, 15)],
        "codex": {
            "agent_version_id": launcher.FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID,
            "agent_version_hash": launcher.FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH,
            "prompt_hash": launcher.FUNCTIONAL_AGENTEVAL_PROMPT_HASH,
            "tool_policy_fingerprint": launcher.FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        },
    }

    launcher._validate_existing_plan(plan)

    plan["automatic_retries"] = 1
    with pytest.raises(Exception, match="frozen functional diagnostic"):
        launcher._validate_existing_plan(plan)


def test_completed_zero_mismatch_reference_timeout_is_infrastructure() -> None:
    launcher = _launcher_module()
    results = [
        SimpleNamespace(
            status=launcher.VerifierStatus.PASSED,
            exit_code=0,
            metadata={},
        ),
        SimpleNamespace(
            status=launcher.VerifierStatus.FAILED,
            exit_code=0,
            metadata={
                "process_timed_out": True,
                "native_result_marker_found": True,
                "native_timeout": False,
                "mismatches": 0,
                "samples_checked": 499,
            },
        ),
    ]

    assert launcher._completed_reference_misclassified_as_timeout(results) is True

    results[1].metadata["mismatches"] = 1
    assert launcher._completed_reference_misclassified_as_timeout(results) is False


def test_commercial_scan_ignores_only_content_free_mcp_category_keys() -> None:
    launcher = _launcher_module()
    safe = b'{"mcp_server_category_counts":{},"scoring_event_mcp_server":0}'
    dangerous = b'{"mcp_server_endpoint":"commercial-host"}'

    assert (
        launcher.smoke._COMMERCIAL_DIAGNOSTIC.search(launcher._without_safe_event_categories(safe))
        is None
    )
    assert (
        launcher.smoke._COMMERCIAL_DIAGNOSTIC.search(
            launcher._without_safe_event_categories(dangerous)
        )
        is not None
    )
