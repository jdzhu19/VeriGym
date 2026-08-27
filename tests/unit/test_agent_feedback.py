from __future__ import annotations

import json
from pathlib import Path
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
from verigym.schemas.agent_feedback import AgentFeedbackContract
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


def _declared_task(*, ppa_supported: bool):  # type: ignore[no-untyped-def]
    task = _task()
    metadata = dict(task.metadata)
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


def test_feedback_resolution_rejects_unsupported_and_commercial_ppa() -> None:
    with pytest.raises(ConfigurationError, match="does not support PPA"):
        resolve_agent_feedback_contract(
            task=_declared_task(ppa_supported=False),
            ppa_enabled=True,
            ppa_max_executions=3,
            resolved_profile=None,
            profile_backend=None,
        )

    with pytest.raises(ConfigurationError, match="commercial PPA is unavailable in phase one"):
        resolve_agent_feedback_contract(
            task=_declared_task(ppa_supported=True),
            ppa_enabled=True,
            ppa_max_executions=3,
            resolved_profile=cast(Any, object()),
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

    def synthesize(**_kwargs: Any) -> tuple[VerifierResult, SynthesisMetrics]:
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
