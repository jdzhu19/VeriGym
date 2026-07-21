from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from verigym.core.episode import BudgetTracker, TerminationReason
from verigym.core.hashing import content_hash
from verigym.core.scoring import build_scorecard
from verigym.core.verifier_dag import VerifierExecutor
from verigym.registry.base import PluginRegistry
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.base import StrictModel
from verigym.schemas.common import (
    ErrorCategory,
    ToolchainProfileRef,
    ToolDescriptor,
    ToolVisibility,
)
from verigym.schemas.runtime import SessionSpec, WorkspaceDiff
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.schemas.verifier import VerifierGraph, VerifierNode, VerifierResult, VerifierStatus
from verigym.suites.toy_rtl.adapter import ToyRtlSuite
from verigym.tools.base import ToolContext, ToolPlugin


class EmptyRequest(StrictModel):
    pass


class FakeTool(ToolPlugin):
    def __init__(self, name: str, result: ToolResult) -> None:
        self.descriptor = ToolDescriptor(
            name=name,
            version="1.0.0",
            provider="tests",
            visibility=ToolVisibility.VERIFIER_ONLY,
        )
        self.result = result

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        return HealthCheckResult(healthy=True, message="fake")

    def validate_request(self, request: dict[str, Any]) -> BaseModel:
        return EmptyRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        raise NotImplementedError

    def parse_result(
        self, request: BaseModel, completed: CompletedCommand, context: ToolContext
    ) -> ToolResult:
        raise NotImplementedError

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        return self.result.model_copy(deep=True)


def test_verifier_dag_skips_dependents_after_failed_gate(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    session = LocalRuntime().create_session(SessionSpec(source_dir=str(source), label="dag"))
    registry: PluginRegistry[ToolPlugin] = PluginRegistry("tests.tools")
    registry.register(
        FakeTool(
            "fake.fail",
            ToolResult(
                tool="fake.fail",
                success=False,
                category=ErrorCategory.TEST_FAILED,
                message="candidate failure",
            ),
        )
    )
    registry.register(
        FakeTool(
            "fake.pass",
            ToolResult(tool="fake.pass", success=True, category=ErrorCategory.SUCCESS),
        )
    )
    graph = VerifierGraph(
        nodes=[
            VerifierNode(
                id="gate",
                plugin="fake.fail",
                gate=True,
                visibility="verifier_only",
                request={},
            ),
            VerifierNode(
                id="downstream",
                plugin="fake.pass",
                depends_on=["gate"],
                visibility="verifier_only",
                request={},
            ),
        ]
    )
    try:
        results = VerifierExecutor(registry).execute(
            graph, session, tmp_path / "artifacts", max_output_bytes=1000
        )
    finally:
        session.close()
    assert [result.node_id for result in results] == ["gate", "downstream"]
    assert results[0].status == VerifierStatus.FAILED
    assert results[1].status == VerifierStatus.SKIPPED


def test_scorecard_separates_candidate_and_infrastructure_failures() -> None:
    suite = ToyRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    profile = ToolchainProfileRef(id="toy", version="1", content_hash="0" * 64)
    common = {
        "run_id": "run",
        "task": task,
        "diff": WorkspaceDiff(),
        "termination_reason": TerminationReason.FINAL_SUBMISSION,
        "task_hash": content_hash(task),
        "candidate_hash": "1" * 64,
        "run_config_hash": "2" * 64,
        "profile_refs": [profile],
        "isolation_level": "local_trusted",
    }
    candidate_results = [
        VerifierResult(
            node_id="compile_hidden",
            plugin="iverilog.compile",
            status="passed",
        ),
        VerifierResult(
            node_id="run_hidden",
            plugin="iverilog.run",
            status="failed",
            error_category="test_failed",
        ),
    ]
    candidate = build_scorecard(
        results=candidate_results, tracker=BudgetTracker(task.budget), **common
    )
    assert candidate.status == "completed"
    assert not candidate.resolved
    assert not candidate.correctness.infrastructure_error
    assert candidate.quality.ppa is None

    infrastructure_results = [
        VerifierResult(
            node_id="compile_hidden",
            plugin="iverilog.compile",
            status="error",
            error_category="tool_not_found",
        ),
        VerifierResult(
            node_id="run_hidden",
            plugin="iverilog.run",
            status="skipped",
        ),
    ]
    infrastructure = build_scorecard(
        results=infrastructure_results, tracker=BudgetTracker(task.budget), **common
    )
    assert infrastructure.status == "error"
    assert not infrastructure.resolved
    assert infrastructure.correctness.infrastructure_error
