from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from verigym.agents.api_repository_v2 import ProviderNeutralApiRepositoryAgent
from verigym.core.agent_feedback import (
    AgentFeedbackController,
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.prompts.policy import resolve_prompt_policy
from verigym.protocols.repository_action import (
    action_registry,
    legacy_repository_action_registry_hash,
    repository_action_state_failure,
    resolve_repository_action_protocol,
)
from verigym.schemas.agent_feedback import (
    AgentFeedbackContract,
    AgentFeedbackEvaluation,
    AgentFeedbackEvaluationV2,
)
from verigym.schemas.common import ErrorCategory, InteractionMode
from verigym.schemas.synthesis import SynthesisMetrics
from verigym.schemas.task import TaskRef
from verigym.schemas.tool import CompletedCommand
from verigym.schemas.verifier import VerifierResult, VerifierStatus
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite


class _Session:
    def __init__(self, root: Path) -> None:
        self.root = root

    def execute_public_test(self, test_id: str) -> CompletedCommand:
        payload = {
            "schema_version": "1.0",
            "protocol": "verigym_public_test_v1",
            "test_id": test_id,
            "passed": True,
            "category": "passed",
        }
        return CompletedCommand(
            argv=["public", test_id],
            cwd=".",
            exit_code=0,
            stdout=json.dumps(payload),
            duration_s=0,
            metadata={"public_assets_read_only": True},
        )


class _MissingCompilerSession(_Session):
    def execute_public_test(self, test_id: str) -> CompletedCommand:
        payload = {
            "schema_version": "1.0",
            "protocol": "verigym_public_test_v1",
            "test_id": test_id,
            "passed": False,
            "category": "command_failed",
            "commands": [
                {
                    "category": "command_failed",
                    "exit_code": None,
                    "passed": False,
                }
            ],
        }
        return CompletedCommand(
            argv=["public", test_id],
            cwd=".",
            exit_code=1,
            stdout=json.dumps(payload),
            duration_s=0,
            metadata={"public_assets_read_only": True},
        )


def _task():  # type: ignore[no-untyped-def]
    suite = RepositoryRtlSuite()
    return suite.load_task(
        TaskRef(id="repo-rtl/counter-wrap", suite="repo-rtl", native_id="counter-wrap")
    )


def _contract(*, quota: int = 1) -> AgentFeedbackContract:
    payload: dict[str, Any] = {
        "task_id": "fixture/task",
        "benchmark_variant": "fixture-agent-eval-v1",
        "compile_test_id": "compile",
        "ppa_test_id": "ppa",
        "public_test_ids": ["compile", "ppa"],
        "compile_required_for_finish": True,
        "ppa_supported": True,
        "ppa_enabled": True,
        "ppa_max_executions": quota,
        "resolved_profile_hash": "a" * 64,
        "profile_backend": "yosys.synth",
        "public_test_contract_hash": "b" * 64,
    }
    return AgentFeedbackContract.model_validate(
        {**payload, "configuration_fingerprint": content_hash(payload)}
    )


def _v2_contract(*, quota: int = 2) -> AgentFeedbackContract:
    payload: dict[str, Any] = {
        "contract_id": "agent_feedback_contract.v2",
        "resolver_id": "agent_feedback_contract_resolver_v2",
        "task_id": "fixture/task",
        "benchmark_variant": "fixture-agent-eval-v1",
        "compile_test_id": "compile",
        "ppa_test_id": "ppa",
        "public_test_ids": ["compile", "ppa"],
        "compile_required_for_finish": True,
        "ppa_supported": True,
        "ppa_enabled": True,
        "ppa_max_executions": quota,
        "resolved_profile_hash": "a" * 64,
        "profile_backend": "synopsys.dc.mcp",
        "ppa_execution_semantics": "dispatched_synthesis_attempt",
        "metric_semantics": [
            {"name": "area", "direction": "minimize", "unit": "um^2"},
            {"name": "maximum_path_delay", "direction": "minimize", "unit": "ns"},
            {"name": "worst_negative_slack", "direction": "maximize", "unit": "ns"},
            {"name": "power", "direction": "minimize", "unit": "uW"},
        ],
        "agent_worker_contract_hash": "d" * 64,
        "agent_worker_isolation_kind": "lsf_job",
        "public_test_contract_hash": "b" * 64,
    }
    return AgentFeedbackContract.model_validate(
        {**payload, "configuration_fingerprint": content_hash(payload)}
    )


def _declared_task(*, ppa_supported: bool):  # type: ignore[no-untyped-def]
    task = _task()
    metadata = dict(task.metadata)
    metadata["candidate_top"] = "counter_wrap"
    metadata["agent_eval"] = {
        "benchmark_variant": "fixture-agent-eval-v1",
        "compile_test_id": "compile",
        "ppa_supported": ppa_supported,
        "public_test_contract_hash": "b" * 64,
    }
    return task.model_copy(update={"metadata": metadata}, deep=True)


def test_v3_invalidates_revision_evidence_without_changing_registry() -> None:
    assert content_hash(action_registry()) == (
        "2237501cabfa3a0871ee468a187b5c7caa212fb3a0655982e9a625c50478a20f"
    )
    assert legacy_repository_action_registry_hash() == (
        "c60164616d37a85b33d6aa3df39ba3ac422ac4650b32265f7da5ae2aaf69f03b"
    )
    assert (
        repository_action_state_failure(
            "run_public_test",
            state_machine_id="repository_action_state_machine_v3",
            public_test_required=True,
            patch_applied=True,
            public_observed=False,
            diff_observed=False,
            finished=False,
            public_test_id="ppa",
            compile_test_id="compile",
            compile_passed=False,
            compile_required_for_finish=True,
        )
        == "agent_invalid_state_transition"
    )
    assert (
        repository_action_state_failure(
            "finish",
            state_machine_id="repository_action_state_machine_v3",
            public_test_required=True,
            patch_applied=True,
            public_observed=True,
            diff_observed=True,
            finished=False,
            compile_test_id="compile",
            compile_passed=False,
            compile_required_for_finish=True,
        )
        == "agent_finish_invalid"
    )
    assert (
        repository_action_state_failure(
            "finish",
            state_machine_id="repository_action_state_machine_v3",
            public_test_required=True,
            patch_applied=True,
            public_observed=True,
            diff_observed=True,
            finished=False,
            compile_test_id="compile",
            compile_passed=True,
            compile_required_for_finish=True,
        )
        is None
    )


def test_historical_v1_feedback_evaluation_shape_is_unchanged() -> None:
    payload = {
        "schema_version": "1.0",
        "sequence": 0,
        "test_id": "ppa",
        "candidate_hash": "a" * 64,
        "profile_hash": "b" * 64,
        "cache_hit": False,
        "synthesis_executed": True,
        "duration_s": 0.25,
        "category": "passed",
        "passed": True,
        "metrics": {
            "area": 12.5,
            "area_unit": "um^2",
            "maximum_path_delay": None,
            "worst_negative_slack": None,
            "timing_unit": None,
            "power": None,
            "power_unit": None,
        },
        "observation_hash": "c" * 64,
    }

    evaluation = AgentFeedbackEvaluation.model_validate(payload)

    assert evaluation.model_dump(mode="json") == payload


def _commercial_profile(
    *,
    isolated: bool,
    release: bool = False,
    flow_template_id: str = "synopsys-dc-area-timing-power-explicit-v4",
) -> Any:
    metadata: dict[str, Any] = {}
    if isolated:
        metadata = {
            "agent_feedback_worker_contract_hash": "d" * 64,
            "agent_feedback_worker_isolation_kind": "lsf_job",
            "agent_feedback_worker_contract": {
                "disposable_worker": True,
                "one_candidate_per_worker": True,
                "cleanup_before_response": True,
                "raw_artifacts_returned": False,
            },
        }
        if release:
            metadata.update(
                {
                    "agent_feedback_worker_release_protocol": "commercial_worker_release.v1",
                    "agent_feedback_worker_release_hash": "e" * 64,
                }
            )
    return SimpleNamespace(
        flow_template_id=flow_template_id,
        metric_scope="synthesis_area_timing_power",
        metadata=metadata,
        top_module="counter_wrap",
        resolved_profile_hash="a" * 64,
        area_unit="um^2",
        timing_unit="ns",
        power_unit="uW",
    )


@pytest.mark.parametrize(
    "flow_template_id",
    [
        "verigym-yosys-opensta-atp-v2",
        "verigym-yosys-opensta-atp-v3",
        "verigym-yosys-opensta-atp-v4",
    ],
)
def test_feedback_resolution_accepts_approved_opensta_flows(flow_template_id: str) -> None:
    profile = _commercial_profile(isolated=False, flow_template_id=flow_template_id)

    contract = resolve_agent_feedback_contract(
        task=_declared_task(ppa_supported=True),
        ppa_enabled=True,
        ppa_max_executions=3,
        resolved_profile=profile,
        profile_backend="yosys.synth",
    )

    assert contract is not None
    assert contract.contract_id == "agent_feedback_contract.v1"
    assert contract.resolved_profile_hash == "a" * 64


def test_feedback_resolution_rejects_unsupported_and_unisolated_commercial_ppa() -> None:
    with pytest.raises(ConfigurationError, match="does not support PPA"):
        resolve_agent_feedback_contract(
            task=_declared_task(ppa_supported=False),
            ppa_enabled=True,
            ppa_max_executions=3,
            resolved_profile=None,
            profile_backend=None,
        )

    with pytest.raises(ConfigurationError, match="disposable worker contract"):
        resolve_agent_feedback_contract(
            task=_declared_task(ppa_supported=True),
            ppa_enabled=True,
            ppa_max_executions=3,
            resolved_profile=_commercial_profile(isolated=False),
            profile_backend="synopsys.dc.mcp",
        )


@pytest.mark.parametrize(
    "flow_template_id",
    [
        "synopsys-dc-area-timing-power-explicit-v4",
        "synopsys-dc-area-timing-power-multiclock-explicit-v5",
    ],
)
def test_feedback_resolution_accepts_hash_bound_isolated_dc_mcp(
    flow_template_id: str,
) -> None:
    contract = resolve_agent_feedback_contract(
        task=_declared_task(ppa_supported=True),
        ppa_enabled=True,
        ppa_max_executions=3,
        resolved_profile=_commercial_profile(isolated=True, flow_template_id=flow_template_id),
        profile_backend="synopsys.dc.mcp",
    )

    assert contract is not None
    assert contract.contract_id == "agent_feedback_contract.v2"
    assert contract.ppa_execution_semantics == "dispatched_synthesis_attempt"
    assert contract.agent_worker_contract_hash == "d" * 64
    assert contract.agent_worker_release_hash is None
    assert [(item.name, item.direction) for item in contract.metric_semantics] == [
        ("area", "minimize"),
        ("maximum_path_delay", "minimize"),
        ("worst_negative_slack", "maximize"),
        ("power", "minimize"),
    ]


def test_feedback_resolution_binds_optional_v2_worker_release_identity() -> None:
    contract = resolve_agent_feedback_contract(
        task=_declared_task(ppa_supported=True),
        ppa_enabled=True,
        ppa_max_executions=3,
        resolved_profile=_commercial_profile(isolated=True, release=True),
        profile_backend="synopsys.dc.mcp",
    )

    assert contract is not None
    assert contract.agent_worker_release_protocol == "commercial_worker_release.v1"
    assert contract.agent_worker_release_hash == "e" * 64

    invalid = _commercial_profile(isolated=True)
    invalid.metadata["agent_feedback_worker_release_hash"] = "e" * 64
    with pytest.raises(ConfigurationError, match="release identity"):
        resolve_agent_feedback_contract(
            task=_declared_task(ppa_supported=True),
            ppa_enabled=True,
            ppa_max_executions=3,
            resolved_profile=invalid,
            profile_backend="synopsys.dc.mcp",
        )


def test_feedback_resolution_without_ppa_preserves_compile_only_contract() -> None:
    contract = resolve_agent_feedback_contract(
        task=_declared_task(ppa_supported=True),
        ppa_enabled=False,
        ppa_max_executions=3,
        resolved_profile=None,
        profile_backend=None,
    )

    assert contract is not None
    assert contract.public_test_ids == ["compile"]
    assert contract.ppa_test_id is None
    assert contract.resolved_profile_hash is None


def test_feedback_contract_resolves_v3_prompt_without_changing_six_actions() -> None:
    contract = resolve_agent_feedback_contract(
        task=_declared_task(ppa_supported=True),
        ppa_enabled=False,
        ppa_max_executions=3,
        resolved_profile=None,
        profile_backend=None,
    )
    execution_task = task_with_agent_feedback_contract(_declared_task(ppa_supported=True), contract)
    agent = ProviderNeutralApiRepositoryAgent()

    prompt = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options={},
        task=execution_task,
    )
    protocol = resolve_repository_action_protocol(
        agent_descriptor=agent.descriptor,
        protocol_spec=agent.action_protocol_spec,
        agent_options={"max_completion_calls": 1},
        task=execution_task,
    )

    assert prompt is not None and prompt.id == "repository_action_v2_prompt_v3"
    assert protocol is not None
    assert protocol.state_machine_id == "repository_action_state_machine_v3"
    assert protocol.action_registry_hash == content_hash(action_registry())
    assert set(action_registry()["actions"]) == {
        "list_files",
        "read_file",
        "apply_patch",
        "run_public_test",
        "inspect_diff",
        "finish",
    }


def test_candidate_only_ppa_is_compile_gated_cached_and_quota_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    rtl = repository / "candidate.v"
    rtl.write_text("module candidate; endmodule\n", encoding="utf-8")
    executions = 0

    def synthesize(**_kwargs: Any) -> tuple[VerifierResult, SynthesisMetrics, bool]:
        nonlocal executions
        executions += 1
        return (
            VerifierResult(
                node_id="agent_ppa",
                plugin="yosys.synth",
                status=VerifierStatus.PASSED,
                error_category=ErrorCategory.SUCCESS,
            ),
            SynthesisMetrics(
                status="passed",
                synthesis_ok=True,
                role="candidate",
                top="candidate",
                mapped_area_raw=12.5,
                mapped_area_unit="um^2",
                critical_path_delay_raw=1.2,
                worst_negative_slack_raw=-0.2,
                timing_unit="ns",
                timing_constraints_hash="c" * 64,
                total_power_raw=0.4,
                power_unit="mW",
                power_activity_mode="vectorless",
            ),
            True,
        )

    monkeypatch.setattr(
        "verigym.core.agent_feedback.execute_candidate_synthesis_feedback", synthesize
    )
    controller = AgentFeedbackController(
        contract=_contract(),
        task=_task(),
        runtime=cast(Any, object()),
        profile=cast(Any, object()),
        resolved_profile=cast(Any, object()),
        backend=cast(Any, object()),
    )
    session = cast(Any, _Session(tmp_path))

    assert controller.execute("ppa", session).failure_reason == "compile_required"
    assert controller.execute("compile", session).exit_code == 0
    first = controller.execute("ppa", session)
    second = controller.execute("ppa", session)
    assert executions == 1
    assert json.loads(first.stdout)["cache_hit"] is False
    cached = json.loads(second.stdout)
    assert cached["cache_hit"] is True
    assert set(cached["candidate_metrics"]) == {
        "area",
        "area_unit",
        "maximum_path_delay",
        "worst_negative_slack",
        "timing_unit",
        "power",
        "power_unit",
    }
    assert not {
        "reference",
        "ratio",
        "netlist",
        "critical_path",
        "raw_report",
    } & set(cached)

    rtl.write_text("module candidate; wire changed; endmodule\n", encoding="utf-8")
    assert controller.execute("ppa", session).failure_reason == "compile_required"
    assert controller.execute("compile", session).exit_code == 0
    assert controller.execute("ppa", session).failure_reason == "ppa_quota_exhausted"
    assert [item.sequence for item in controller.evaluations] == list(
        range(len(controller.evaluations))
    )


def test_missing_public_compiler_is_infrastructure_not_candidate_failure(tmp_path: Path) -> None:
    (tmp_path / "candidate.v").write_text("module candidate; endmodule\n", encoding="utf-8")
    controller = AgentFeedbackController(
        contract=_contract(),
        task=_task(),
        runtime=cast(Any, object()),
        profile=cast(Any, object()),
        resolved_profile=cast(Any, object()),
        backend=cast(Any, object()),
    )

    completed = controller.execute("compile", cast(Any, _MissingCompilerSession(tmp_path)))

    assert completed.failure_origin == "control_plane"
    assert completed.failure_reason == "agent_compile_infrastructure"
    assert controller.evaluations[-1].category == "infrastructure_error"


def test_v2_feedback_exposes_directions_budget_and_last_valid_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rtl = tmp_path / "candidate.v"
    rtl.write_text("module candidate; endmodule\n", encoding="utf-8")
    calls = 0

    def synthesize(**_kwargs: Any) -> tuple[VerifierResult, SynthesisMetrics, bool]:
        nonlocal calls
        calls += 1
        passed = calls == 1
        return (
            VerifierResult(
                node_id="agent_ppa",
                plugin="synopsys.dc.mcp",
                status=VerifierStatus.PASSED if passed else VerifierStatus.FAILED,
                error_category=(ErrorCategory.SUCCESS if passed else ErrorCategory.COMPILE_FAILED),
            ),
            SynthesisMetrics(
                status="passed" if passed else "failed",
                synthesis_ok=passed,
                role="candidate",
                top="candidate",
                mapped_area_raw=12.5 if passed else None,
                mapped_area_unit="um^2" if passed else None,
                critical_path_delay_raw=1.2 if passed else None,
                worst_negative_slack_raw=-0.2 if passed else None,
                timing_unit="ns" if passed else None,
                timing_constraints_hash="c" * 64 if passed else None,
                total_power_raw=0.4 if passed else None,
                power_unit="uW" if passed else None,
                power_activity_mode="global_clock_relative" if passed else None,
            ),
            True,
        )

    monkeypatch.setattr(
        "verigym.core.agent_feedback.execute_candidate_synthesis_feedback", synthesize
    )
    controller = AgentFeedbackController(
        contract=_v2_contract(),
        task=_task(),
        runtime=cast(Any, object()),
        profile=cast(Any, object()),
        resolved_profile=cast(Any, object()),
        backend=cast(Any, object()),
    )
    session = cast(Any, _Session(tmp_path))
    controller.execute("compile", session)
    first = json.loads(controller.execute("ppa", session).stdout)
    first_hash = first["candidate_hash"]
    assert first["protocol"] == "verigym_agent_feedback_v2"
    assert first["execution_budget"]["ppa_executions_remaining"] == 1
    assert first["metric_semantics"][2] == {
        "name": "worst_negative_slack",
        "direction": "maximize",
        "unit": "ns",
    }

    rtl.write_text("module candidate; bad syntax\n", encoding="utf-8")
    controller.execute("compile", session)
    failed = json.loads(controller.execute("ppa", session).stdout)
    assert failed["category"] == "synthesis_failed"
    assert failed["last_valid"]["candidate_hash"] == first_hash
    assert failed["execution_budget"]["ppa_executions_used"] == 2
    ledger = controller.evaluations[-1]
    assert isinstance(ledger, AgentFeedbackEvaluationV2)
    assert ledger.evaluation_contract_id == "agent_feedback_evaluation.v2"
    assert ledger.execution_dispatched is True
    assert ledger.last_valid_candidate_hash == first_hash


def test_v2_pre_dispatch_failure_does_not_consume_synthesis_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "candidate.v").write_text("module candidate; endmodule\n", encoding="utf-8")

    def synthesize(**_kwargs: Any) -> tuple[VerifierResult, SynthesisMetrics, bool]:
        metrics = SynthesisMetrics(
            status="error",
            synthesis_ok=False,
            role="candidate",
            top="candidate",
            failure_category="sandbox_error",
        )
        return (
            VerifierResult(
                node_id="agent_ppa",
                plugin="synopsys.dc.mcp",
                status=VerifierStatus.ERROR,
                error_category=ErrorCategory.SANDBOX_ERROR,
            ),
            metrics,
            False,
        )

    monkeypatch.setattr(
        "verigym.core.agent_feedback.execute_candidate_synthesis_feedback", synthesize
    )
    controller = AgentFeedbackController(
        contract=_v2_contract(quota=1),
        task=_task(),
        runtime=cast(Any, object()),
        profile=cast(Any, object()),
        resolved_profile=cast(Any, object()),
        backend=cast(Any, object()),
    )
    session = cast(Any, _Session(tmp_path))
    controller.execute("compile", session)
    first = json.loads(controller.execute("ppa", session).stdout)
    second = json.loads(controller.execute("ppa", session).stdout)

    assert first["category"] == second["category"] == "infrastructure_error"
    assert first["execution_budget"]["ppa_executions_used"] == 0
    assert second["execution_budget"]["ppa_executions_remaining"] == 1
    assert controller.evaluations[-1].synthesis_executed is False


def test_v2_post_dispatch_infrastructure_failure_consumes_synthesis_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "candidate.v").write_text("module candidate; endmodule\n", encoding="utf-8")

    def synthesize(**_kwargs: Any) -> tuple[VerifierResult, SynthesisMetrics, bool]:
        metrics = SynthesisMetrics(
            status="error",
            synthesis_ok=False,
            role="candidate",
            top="candidate",
            failure_category="timeout",
        )
        return (
            VerifierResult(
                node_id="agent_ppa",
                plugin="synopsys.dc.mcp",
                status=VerifierStatus.ERROR,
                error_category=ErrorCategory.TIMEOUT,
            ),
            metrics,
            True,
        )

    monkeypatch.setattr(
        "verigym.core.agent_feedback.execute_candidate_synthesis_feedback", synthesize
    )
    controller = AgentFeedbackController(
        contract=_v2_contract(quota=1),
        task=_task(),
        runtime=cast(Any, object()),
        profile=cast(Any, object()),
        resolved_profile=cast(Any, object()),
        backend=cast(Any, object()),
    )
    session = cast(Any, _Session(tmp_path))
    controller.execute("compile", session)
    first = json.loads(controller.execute("ppa", session).stdout)
    second = json.loads(controller.execute("ppa", session).stdout)

    assert first["category"] == "infrastructure_error"
    assert first["execution_budget"]["execution_dispatched"] is True
    assert first["execution_budget"]["ppa_executions_used"] == 1
    assert second["category"] == "ppa_quota_exhausted"
    assert controller.evaluations[-2].synthesis_executed is True


def test_v2_feedback_preserves_only_allowlisted_worker_infrastructure_subcategory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "candidate.v").write_text("module candidate; endmodule\n", encoding="utf-8")

    def synthesize(**_kwargs: Any) -> tuple[VerifierResult, SynthesisMetrics, bool]:
        metrics = SynthesisMetrics(
            status="error",
            synthesis_ok=False,
            role="candidate",
            top="candidate",
            failure_category="agent_worker_scheduler",
            failure_message="private scheduler detail at /private/site/path",
        )
        return (
            VerifierResult(
                node_id="agent_ppa",
                plugin="synopsys.dc.mcp",
                status=VerifierStatus.ERROR,
                error_category=ErrorCategory.PARSER_ERROR,
            ),
            metrics,
            True,
        )

    monkeypatch.setattr(
        "verigym.core.agent_feedback.execute_candidate_synthesis_feedback", synthesize
    )
    controller = AgentFeedbackController(
        contract=_v2_contract(quota=1),
        task=_task(),
        runtime=cast(Any, object()),
        profile=cast(Any, object()),
        resolved_profile=cast(Any, object()),
        backend=cast(Any, object()),
    )
    session = cast(Any, _Session(tmp_path))
    controller.execute("compile", session)
    completed = controller.execute("ppa", session)
    payload = json.loads(completed.stdout)

    assert completed.failure_origin == "control_plane"
    assert completed.failure_reason == "agent_worker_scheduler"
    assert payload["infrastructure_subcategory"] == "agent_worker_scheduler"
    assert "/private/site/path" not in completed.stdout
