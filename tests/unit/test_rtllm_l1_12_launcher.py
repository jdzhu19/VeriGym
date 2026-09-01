from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from verigym.schemas.run import RunConfig
from verigym.schemas.verifier import VerifierStatus


def _launcher() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtllm_l1_multiturn_codex_12.py"
    spec = importlib.util.spec_from_file_location("rtllm_l1_12_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def test_matrix_freezes_twelve_diverse_unique_no_ppa_slots() -> None:
    launcher = _launcher()
    specs = launcher._RUN_SPECS

    assert len(specs) == 12
    assert len({spec.run_id for spec in specs}) == 12
    assert len({spec.task_id for spec in specs}) == 12
    assert [spec.ordinal for spec in specs] == list(range(1, 13))
    assert launcher._OPT_IN == "VERIGYM_RUN_RTLLM_FULL_L1_12"
    assert not set(launcher._TASK_NAMES).intersection(launcher._PRIOR_CAMPAIGN_TASK_NAMES)
    assert {"Arithmetic", "Control", "Memory", "Miscellaneous"}.issubset(
        {launcher.TASK_MANIFESTS[name].root.split("/", 1)[0] for name in launcher._TASK_NAMES}
    )
    assert all(
        spec.task_id.startswith(f"rtllm/{launcher.ALL_AGENT_EVAL_VARIANT}/") for spec in specs
    )
    assert launcher._AGENT_NAME == "codex-cli-agenteval-agent"
    assert launcher._MODEL_ID == "gpt-5.4"
    assert launcher._REASONING_EFFORT == "xhigh"


def _configs(output: Path, launcher: ModuleType) -> list[RunConfig]:
    return [
        RunConfig(task_id=spec.task_id, output=output / "runs", run_id=spec.run_id)
        for spec in launcher._RUN_SPECS
    ]


def _observation(launcher: ModuleType) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_count=1,
        requested_model_id=launcher._MODEL_ID,
        observed_model_id=None,
        effective_reasoning_effort=launcher._REASONING_EFFORT,
        harness_id=launcher.AGENTEVAL_AGENT_VERSION_ID,
        agent_version_hash=launcher.AGENTEVAL_AGENT_VERSION_HASH,
        prompt_contract_hash=launcher.AGENTEVAL_PROMPT_HASH,
        tool_policy_fingerprint=launcher.AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    )


class _Service:
    def __init__(self, root: Path, launcher: ModuleType, outcomes: list[dict[str, object]]) -> None:
        self.root = root
        self.launcher = launcher
        self.outcomes = outcomes
        self.calls = 0

    def run(self, config: RunConfig) -> SimpleNamespace:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        run_dir = self.root / "actual" / str(config.run_id)
        evidence = run_dir / "artifacts" / "codex_cli"
        evidence.mkdir(parents=True)
        (evidence / "process.json").write_text("{}", encoding="utf-8")
        (evidence / "identity.json").write_text("{}", encoding="utf-8")
        observations = [_observation(self.launcher)]
        if outcome.get("duplicate_identity"):
            observations.append(_observation(self.launcher))
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


def test_execution_authorizes_once_and_continues_model_failures(tmp_path: Path) -> None:
    launcher = _launcher()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{} for _ in range(12)]
    outcomes[0] = {
        "failure": SimpleNamespace(kind="model", infrastructure=False),
        "resolved": False,
    }
    outcomes[1] = {"resolved": False}
    service = _Service(tmp_path, launcher, outcomes)

    results = launcher._execute_exactly_twelve(service, _configs(output, launcher), output)
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == service.calls == len(records) == 12
    assert [record["status"] for record in records[:2]] == [
        "contained_model_failure",
        "verifier_rejection",
    ]
    assert all(record["retry_count"] == 0 for record in records)
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
def test_execution_stops_on_infrastructure_policy_or_identity_failure(
    tmp_path: Path, outcome: dict[str, object]
) -> None:
    launcher = _launcher()
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    service = _Service(tmp_path, launcher, [{}, outcome, *({} for _ in range(10))])

    with pytest.raises(launcher.functional.CampaignInfrastructureError):
        launcher._execute_exactly_twelve(service, _configs(output, launcher), output)

    assert service.calls == 2
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]
    assert len(records) == 2
    assert records[-1]["retry_count"] == 0


def test_hidden_execution_requires_typed_finish_and_exactly_one_node() -> None:
    launcher = _launcher()
    results = [
        SimpleNamespace(
            node_id="functional_hidden",
            plugin="iverilog.simulate",
            status=VerifierStatus.PASSED,
        )
    ]

    assert launcher._hidden_execution_valid(results, typed_finish=True) == (True, 1, 0)
    results[0].status = VerifierStatus.SKIPPED
    assert launcher._hidden_execution_valid(results, typed_finish=False) == (True, 0, 1)
    results[0].status = VerifierStatus.FAILED
    assert launcher._hidden_execution_valid(results, typed_finish=False) == (False, 1, 0)


def test_missing_usage_is_only_valid_for_unfinished_contained_model_failure() -> None:
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


def test_launcher_marks_diagnostic_and_has_no_ppa_or_retry_authorization() -> None:
    source = (
        Path(__file__).parents[2] / "scripts" / "run_rtllm_l1_multiturn_codex_12.py"
    ).read_text(encoding="utf-8")

    assert '"diagnostic_only": True' in source
    assert '"benchmark_score_claimed": False' in source
    assert '"ppa_enabled": False' in source
    assert '"automatic_retries_authorized": False' in source


def _valid_plan(launcher: ModuleType) -> dict[str, object]:
    return {
        "campaign_id": launcher._CAMPAIGN_ID,
        "launcher_sha256": launcher._launcher_hash(),
        "variant": launcher.ALL_AGENT_EVAL_VARIANT,
        "run_specs": [launcher._spec_payload(spec) for spec in launcher._RUN_SPECS],
        "model": launcher._MODEL_ID,
        "reasoning_effort": launcher._REASONING_EFFORT,
        "seed": 0,
        "samples_per_task": 1,
        "planned_codex_processes": 12,
        "automatic_retries": 0,
        "serial_execution": True,
        "public_feedback_level": "L1_candidate_only_compile",
        "ppa_enabled": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
        "codex": {
            "version": launcher.smoke._EXPECTED_CLI_VERSION,
            "executable_sha256": launcher.smoke._EXPECTED_CODEX_SHA256,
            "agent_name": launcher._AGENT_NAME,
            "agent_version_id": launcher.AGENTEVAL_AGENT_VERSION_ID,
            "agent_version_hash": launcher.AGENTEVAL_AGENT_VERSION_HASH,
            "prompt_hash": launcher.AGENTEVAL_PROMPT_HASH,
            "tool_policy_fingerprint": launcher.AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        },
        "runtime": {"image": {"resolved_image_id": launcher._EXPECTED_RUNTIME_IMAGE_ID}},
        "qualification": {
            "passed": True,
            "model_calls": 0,
            "task_count": 12,
            "records": [
                {
                    "task_id": spec.task_id,
                    "public_reference_passed": True,
                    "public_missing_module_rejected": True,
                    "hidden_reference_passed": True,
                    "hidden_missing_module_rejected": True,
                    "ppa_supported": False,
                }
                for spec in launcher._RUN_SPECS
            ],
        },
        "run_config_hashes": [f"{index:064x}" for index in range(1, 13)],
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("ppa_enabled",), True),
        (("launcher_sha256",), "0" * 64),
        (("automatic_retries",), 1),
        (("runtime", "image", "resolved_image_id"), "sha256:" + "0" * 64),
        (("qualification", "model_calls"), 1),
        (("qualification", "records", 0, "ppa_supported"), True),
    ],
)
def test_existing_plan_rejects_identity_qualification_or_policy_drift(
    path: tuple[str | int, ...], value: object
) -> None:
    launcher = _launcher()
    plan = _valid_plan(launcher)
    launcher._validate_existing_plan(plan)
    changed = deepcopy(plan)
    target: object = changed
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(Exception, match="frozen campaign|frozen identities"):
        launcher._validate_existing_plan(changed)
