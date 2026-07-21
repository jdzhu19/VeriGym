"""Scorecard construction without an opaque universal scalar."""

from __future__ import annotations

from typing import Literal

from verigym.core.episode import BudgetTracker, TerminationReason
from verigym.core.hashing import content_hash
from verigym.core.verifier_dag import has_infrastructure_error
from verigym.schemas.common import ToolchainProfileRef
from verigym.schemas.runtime import WorkspaceDiff
from verigym.schemas.score import (
    CorrectnessMetrics,
    EfficiencyMetrics,
    EpisodeFailure,
    PatchMetrics,
    QualityMetrics,
    ReproducibilityMetrics,
    ScoreCard,
)
from verigym.schemas.task import VeriTask
from verigym.schemas.verifier import VerifierResult, VerifierStatus


def build_scorecard(
    *,
    run_id: str,
    task: VeriTask,
    results: list[VerifierResult],
    diff: WorkspaceDiff,
    tracker: BudgetTracker,
    termination_reason: TerminationReason,
    task_hash: str,
    candidate_hash: str,
    run_config_hash: str,
    profile_refs: list[ToolchainProfileRef],
    isolation_level: str,
    episode_failure: EpisodeFailure | None = None,
) -> ScoreCard:
    by_id = {result.node_id: result for result in results}
    required = [by_id[node_id] for node_id in task.scoring.correctness_required_nodes]
    resolved = episode_failure is None and all(
        result.status == VerifierStatus.PASSED for result in required
    )
    infrastructure_error = has_infrastructure_error(required) or bool(
        episode_failure and episode_failure.infrastructure
    )
    compile_result = next((r for r in results if "compile" in r.plugin), None)
    run_result = next(
        (r for r in results if r.plugin in {"iverilog.run", "verilog_eval.v2.regression"}),
        None,
    )
    tests_passed = sum(r.tests_passed or 0 for r in results if r.tests_total is not None)
    tests_total = sum(r.tests_total or 0 for r in results if r.tests_total is not None)
    correctness = CorrectnessMetrics(
        compile_status=compile_result.status.value if compile_result else None,
        hidden_regression_status=run_result.status.value if run_result else None,
        tests_passed=tests_passed if tests_total else None,
        tests_total=tests_total if tests_total else None,
        resolved=resolved,
        infrastructure_error=infrastructure_error,
    )
    status: Literal["error", "failed", "completed"] = (
        "error" if infrastructure_error else "failed" if episode_failure else "completed"
    )
    warnings = []
    if isolation_level == "local_trusted":
        warnings.append(
            "LocalRuntime is for trusted development fixtures and is not an untrusted-code sandbox."
        )
    return ScoreCard(
        run_id=run_id,
        task_id=task.id,
        status=status,
        resolved=resolved,
        correctness=correctness,
        quality=QualityMetrics(ppa=None, synthesis=None),
        efficiency=EfficiencyMetrics(
            wall_time_s=tracker.wall_time_s,
            agent_time_s=tracker.agent_time_s,
            tool_time_s=tracker.tool_time_s,
            verifier_time_s=tracker.verifier_time_s,
            model_input_tokens=tracker.model_input_tokens,
            model_output_tokens=tracker.model_output_tokens,
            total_tokens=tracker.total_tokens,
            model_calls=tracker.model_calls,
            turns=tracker.turns,
            tool_calls=tracker.tool_calls,
            failed_tool_calls=tracker.failed_tool_calls,
        ),
        patch=PatchMetrics(
            changed_files=diff.changed_files,
            added_lines=diff.added_lines,
            deleted_lines=diff.deleted_lines,
            total_diff_lines=diff.added_lines + diff.deleted_lines,
            changes_outside_expected_files=diff.changes_outside_expected_files,
        ),
        reproducibility=ReproducibilityMetrics(
            task_hash=task_hash,
            candidate_hash=candidate_hash,
            verifier_hash=content_hash(task.verifier),
            run_config_hash=run_config_hash,
            toolchain_profile_ids=[ref.id for ref in profile_refs],
            deterministic=True,
            isolation_level=isolation_level,
        ),
        verifier_results=results,
        termination_reason=termination_reason.value,
        failure=episode_failure,
        warnings=warnings,
    )
