from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from verigym.schemas.run import RunConfig
from verigym.schemas.verifier import VerifierStatus


def _launcher() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtllm_harder_multiturn_codex_32.py"
    spec = importlib.util.spec_from_file_location("rtllm_harder_32_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def test_matrix_freezes_exactly_32_unique_zero_retry_slots() -> None:
    launcher = _launcher()
    specs = launcher._RUN_SPECS

    assert len(specs) == 32
    assert len({spec.run_id for spec in specs}) == 32
    assert [spec.ordinal for spec in specs] == list(range(1, 33))
    assert launcher._OPT_IN == "VERIGYM_RUN_RTLLM_HARDER_32"
    for agent_key in launcher._AGENT_CELLS:
        cell = [spec for spec in specs if spec.agent_key == agent_key]
        assert len(cell) == 8
        assert {spec.task_name for spec in cell} == set(launcher.HARDER_TASK_NAMES)
        assert {spec.backend for spec in cell} == {"open", "commercial"}
        assert all(spec.task_id.startswith(f"rtllm/{launcher.HARDER_VARIANT}/") for spec in cell)


def test_async_sdc_freezes_two_asynchronous_clocks_and_wclk_power_base() -> None:
    launcher = _launcher()
    sdc = launcher._sdc("asyn_fifo")

    assert "create_clock -name wclk -period 10 [get_ports wclk]" in sdc
    assert "create_clock -name rclk -period 14 [get_ports rclk]" in sdc
    assert (
        "set_clock_groups -asynchronous -group [get_clocks wclk] -group [get_clocks rclk]"
    ) in sdc
    assert launcher.TASK_MANIFESTS["asyn_fifo"].power_base_clock == "wclk"


def test_named_profiles_require_exact_nonempty_four_task_binding(tmp_path: Path) -> None:
    launcher = _launcher()
    values = []
    for name in launcher.HARDER_TASK_NAMES:
        path = tmp_path / f"{name}.yaml"
        path.write_text("profile\n", encoding="utf-8")
        values.append(f"{name}={path}")

    parsed = launcher._named_paths(values, "VCS")
    assert set(parsed) == set(launcher.HARDER_TASK_NAMES)
    with pytest.raises(Exception, match="cover exactly"):
        launcher._named_paths(values[:-1], "VCS")
    with pytest.raises(Exception, match="unique"):
        launcher._named_paths([*values, values[0]], "VCS")


def _configs(output: Path, launcher: ModuleType) -> list[RunConfig]:
    return [
        RunConfig(task_id=spec.task_id, output=output / "runs", run_id=spec.run_id)
        for spec in launcher._RUN_SPECS
    ]


def _observation(launcher: ModuleType, spec: object) -> SimpleNamespace:
    identity = launcher._AGENT_CELLS[spec.agent_key].identity
    return SimpleNamespace(
        invocation_count=1,
        requested_model_id=identity.model_id,
        observed_model_id=None,
        effective_reasoning_effort=identity.reasoning_effort,
        harness_id=identity.agent_version_id,
        agent_version_hash=identity.agent_version_hash,
        prompt_contract_hash=launcher.FUNCTIONAL_V3_PROMPT_HASH,
        tool_policy_fingerprint=launcher.FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
    )


class _Service:
    def __init__(self, root: Path, launcher: ModuleType, outcomes: list[dict[str, object]]) -> None:
        self.root = root
        self.launcher = launcher
        self.outcomes = outcomes
        self.calls = 0

    def run(self, config: RunConfig) -> SimpleNamespace:
        spec = self.launcher._RUN_SPECS[self.calls]
        outcome = self.outcomes[self.calls]
        self.calls += 1
        run_dir = self.root / "actual" / str(config.run_id)
        evidence = run_dir / "artifacts" / "codex_cli"
        evidence.mkdir(parents=True)
        (evidence / "process.json").write_text("{}", encoding="utf-8")
        (evidence / "identity.json").write_text("{}", encoding="utf-8")
        observations = [_observation(self.launcher, spec)]
        if outcome.get("duplicate_identity"):
            observations.append(_observation(self.launcher, spec))
        return SimpleNamespace(
            run_dir=run_dir,
            manifest=SimpleNamespace(external_agent_observations=observations),
            scorecard=SimpleNamespace(
                resolved=outcome.get("resolved", True),
                correctness=SimpleNamespace(
                    infrastructure_error=outcome.get("infrastructure_error", False)
                ),
                failure=outcome.get("failure"),
            ),
        )


def test_execution_authorizes_32_once_and_continues_model_rejections(tmp_path: Path) -> None:
    launcher = _launcher()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{} for _ in range(32)]
    outcomes[0] = {
        "failure": SimpleNamespace(kind="model", infrastructure=False),
        "resolved": False,
    }
    outcomes[1] = {"resolved": False}
    service = _Service(tmp_path, launcher, outcomes)

    results = launcher._execute_exactly_32(service, _configs(output, launcher), output)
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == service.calls == len(records) == 32
    assert [record["status"] for record in records[:2]] == [
        "contained_model_failure",
        "verifier_rejection",
    ]
    assert all(record["retry_count"] == 0 for record in records)
    assert all(record["identity_observation_count"] == 1 for record in records)
    launcher._validate_authorization_ledger(records)

    records[0]["retry_count"] = 1
    with pytest.raises(Exception, match="non-terminal frozen slot"):
        launcher._validate_authorization_ledger(records)


@pytest.mark.parametrize(
    "outcome",
    [
        {
            "failure": SimpleNamespace(kind="runtime", infrastructure=True),
            "infrastructure_error": True,
        },
        {"failure": SimpleNamespace(kind="policy", infrastructure=False), "resolved": False},
        {"duplicate_identity": True},
    ],
)
def test_execution_stops_immediately_on_infrastructure_policy_or_identity_failure(
    tmp_path: Path, outcome: dict[str, object]
) -> None:
    launcher = _launcher()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    service = _Service(tmp_path, launcher, [{}, outcome, *({} for _ in range(30))])

    with pytest.raises(launcher.functional.CampaignInfrastructureError):
        launcher._execute_exactly_32(service, _configs(output, launcher), output)

    assert service.calls == 2
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]
    assert len(records) == 2
    assert records[-1]["retry_count"] == 0


def test_launcher_source_marks_results_diagnostic_not_benchmark_score() -> None:
    source = (
        Path(__file__).parents[2] / "scripts" / "run_rtllm_harder_multiturn_codex_32.py"
    ).read_text(encoding="utf-8")
    assert '"diagnostic_only": True' in source
    assert '"benchmark_score_claimed": False' in source
    assert "automatic_retries_authorized" in source


def test_hidden_execution_audit_counts_only_the_functional_node() -> None:
    launcher = _launcher()
    results = [
        SimpleNamespace(
            node_id="functional_hidden",
            plugin="iverilog.simulate",
            status=VerifierStatus.PASSED,
        ),
        SimpleNamespace(
            node_id="candidate_synthesis",
            plugin="yosys.synth",
            status=VerifierStatus.PASSED,
        ),
        SimpleNamespace(
            node_id="reference_synthesis",
            plugin="yosys.synth",
            status=VerifierStatus.PASSED,
        ),
        SimpleNamespace(
            node_id="quality_projection",
            plugin="verigym.quality_projection",
            status=VerifierStatus.PASSED,
        ),
    ]

    assert launcher._hidden_verifier_execution(
        results,
        typed_finish=True,
        expected_plugin="iverilog.simulate",
    ) == (True, 1, 0)

    results[0].status = VerifierStatus.SKIPPED
    assert launcher._hidden_verifier_execution(
        results,
        typed_finish=False,
        expected_plugin="iverilog.simulate",
    ) == (True, 0, 1)

    results[0].status = VerifierStatus.FAILED
    assert launcher._hidden_verifier_execution(
        results,
        typed_finish=False,
        expected_plugin="iverilog.simulate",
    ) == (False, 1, 0)


def test_missing_provider_usage_is_valid_only_for_unfinished_contained_model_failure() -> None:
    launcher = _launcher()

    assert launcher._provider_usage_valid(
        usage_complete=True,
        typed_finish=True,
        contained_model_failure=False,
    )
    assert launcher._provider_usage_valid(
        usage_complete=False,
        typed_finish=False,
        contained_model_failure=True,
    )
    assert not launcher._provider_usage_valid(
        usage_complete=False,
        typed_finish=True,
        contained_model_failure=True,
    )
