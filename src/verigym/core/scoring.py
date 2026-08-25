"""Scorecard construction without an opaque universal scalar."""

from __future__ import annotations

import math
from typing import Literal

from verigym.core.episode import BudgetTracker, TerminationReason
from verigym.core.hashing import content_hash
from verigym.core.verifier_dag import has_infrastructure_error
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.schemas.common import ToolchainProfileRef
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.runtime import WorkspaceDiff
from verigym.schemas.score import (
    CorrectnessMetrics,
    EfficiencyMetrics,
    EpisodeFailure,
    PatchMetrics,
    PPAMetrics,
    QualityMetrics,
    ReproducibilityMetrics,
    ScoreCard,
)
from verigym.schemas.synthesis import SynthesisMetrics
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
    resolved_profile: ResolvedToolchainProfile | None = None,
    candidate_synthesis: SynthesisMetrics | None = None,
    reference_synthesis: SynthesisMetrics | None = None,
    external_accounting: ExternalAgentAccounting | None = None,
) -> ScoreCard:
    by_id = {result.node_id: result for result in results}
    required = [by_id[node_id] for node_id in task.scoring.correctness_required_nodes]
    functional_resolved = episode_failure is None and all(
        result.status == VerifierStatus.PASSED for result in required
    )
    infrastructure_error = has_infrastructure_error(
        results if resolved_profile is not None else required
    ) or bool(episode_failure and episode_failure.infrastructure)
    resolved = functional_resolved and not infrastructure_error
    compile_result = next((r for r in results if "compile" in r.plugin), None)
    run_result = next(
        (
            r
            for r in results
            if r.plugin
            in {
                "hwe_bench.simulate",
                "iverilog.run",
                "synopsys.vcs.simulate",
                "verilog_eval.v2.regression",
            }
        ),
        None,
    )
    tests_passed = sum(r.tests_passed or 0 for r in results if r.tests_total is not None)
    tests_total = sum(r.tests_total or 0 for r in results if r.tests_total is not None)
    correctness = CorrectnessMetrics(
        compile_status=compile_result.status.value if compile_result else None,
        hidden_regression_status=run_result.status.value if run_result else None,
        tests_passed=tests_passed if tests_total else None,
        tests_total=tests_total if tests_total else None,
        resolved=functional_resolved,
        infrastructure_error=has_infrastructure_error(required)
        or bool(episode_failure and episode_failure.infrastructure),
    )
    status: Literal["error", "failed", "completed"] = (
        "error" if infrastructure_error else "failed" if episode_failure else "completed"
    )
    warnings = []
    if isolation_level == "local_trusted":
        warnings.append(
            "LocalRuntime is for trusted development fixtures and is not an untrusted-code sandbox."
        )
    quality = QualityMetrics(ppa=None, synthesis=None, reference_synthesis=None)
    if resolved_profile is not None:
        timing_scope = resolved_profile.metric_scope in {
            "synthesis_area_timing",
            "synthesis_area_timing_power",
        }
        power_scope = resolved_profile.metric_scope == "synthesis_area_timing_power"
        reasons: list[str] = []
        if not functional_resolved:
            reasons.append("correctness_gate_failed")
        if candidate_synthesis is None or not candidate_synthesis.synthesis_ok:
            reasons.append("candidate_synthesis_not_passed")
        elif candidate_synthesis.mapped_area_raw is None:
            reasons.append("candidate_area_missing")
        if reference_synthesis is None or not reference_synthesis.synthesis_ok:
            reasons.append("reference_contract_not_satisfied")
        elif reference_synthesis.mapped_area_raw is None:
            reasons.append("reference_area_missing")
        if (
            candidate_synthesis is not None
            and candidate_synthesis.synthesis_ok
            and (
                candidate_synthesis.resolved_profile_hash != resolved_profile.resolved_profile_hash
            )
        ):
            reasons.append("candidate_profile_identity_mismatch")
        if (
            reference_synthesis is not None
            and reference_synthesis.synthesis_ok
            and (
                reference_synthesis.resolved_profile_hash != resolved_profile.resolved_profile_hash
            )
        ):
            reasons.append("reference_profile_identity_mismatch")
        if (
            candidate_synthesis is not None
            and candidate_synthesis.synthesis_ok
            and (candidate_synthesis.mapped_area_unit != resolved_profile.area_unit)
        ):
            reasons.append("candidate_area_unit_mismatch")
        if (
            reference_synthesis is not None
            and reference_synthesis.synthesis_ok
            and (reference_synthesis.mapped_area_unit != resolved_profile.area_unit)
        ):
            reasons.append("reference_area_unit_mismatch")
        if resolved_profile.reference_candidate_hash is None:
            reasons.append("reference_identity_missing")
        if timing_scope:
            if candidate_synthesis is None or candidate_synthesis.critical_path_delay_raw is None:
                reasons.append("candidate_delay_missing")
            if candidate_synthesis is None or candidate_synthesis.worst_negative_slack_raw is None:
                reasons.append("candidate_wns_missing")
            if reference_synthesis is None or reference_synthesis.critical_path_delay_raw is None:
                reasons.append("reference_delay_missing")
            if reference_synthesis is None or reference_synthesis.worst_negative_slack_raw is None:
                reasons.append("reference_wns_missing")
            for role, metrics in (
                ("candidate", candidate_synthesis),
                ("reference", reference_synthesis),
            ):
                if metrics is not None and metrics.synthesis_ok:
                    if metrics.timing_unit != resolved_profile.timing_unit:
                        reasons.append(f"{role}_timing_unit_mismatch")
                    if metrics.clock_period is None:
                        reasons.append(f"{role}_clock_period_missing")
        if power_scope:
            expected_activity_mode = resolved_profile.metadata.get("power_activity_mode")
            for role, metrics in (
                ("candidate", candidate_synthesis),
                ("reference", reference_synthesis),
            ):
                if metrics is None or metrics.total_power_raw is None:
                    reasons.append(f"{role}_power_missing")
                    continue
                if metrics.power_unit != resolved_profile.power_unit:
                    reasons.append(f"{role}_power_unit_mismatch")
                if metrics.power_activity_mode != expected_activity_mode:
                    reasons.append(f"{role}_power_activity_mismatch")
        reasons = list(dict.fromkeys(reasons))
        eligible = not reasons
        candidate_area = (
            candidate_synthesis.mapped_area_raw
            if eligible and candidate_synthesis is not None
            else None
        )
        reference_area = (
            reference_synthesis.mapped_area_raw
            if eligible and reference_synthesis is not None
            else None
        )
        ratio = (
            reference_area / candidate_area
            if reference_area is not None and candidate_area is not None
            else None
        )
        candidate_delay = (
            candidate_synthesis.critical_path_delay_raw
            if eligible and timing_scope and candidate_synthesis is not None
            else None
        )
        reference_delay = (
            reference_synthesis.critical_path_delay_raw
            if eligible and timing_scope and reference_synthesis is not None
            else None
        )
        delay_ratio = (
            reference_delay / candidate_delay
            if reference_delay is not None and candidate_delay is not None
            else None
        )
        candidate_wns = (
            candidate_synthesis.worst_negative_slack_raw
            if eligible and timing_scope and candidate_synthesis is not None
            else None
        )
        reference_wns = (
            reference_synthesis.worst_negative_slack_raw
            if eligible and timing_scope and reference_synthesis is not None
            else None
        )
        candidate_power = (
            candidate_synthesis.total_power_raw
            if eligible and power_scope and candidate_synthesis is not None
            else None
        )
        reference_power = (
            reference_synthesis.total_power_raw
            if eligible and power_scope and reference_synthesis is not None
            else None
        )
        quality = QualityMetrics(
            ppa=PPAMetrics(
                profile_id=resolved_profile.profile_id,
                profile_version=resolved_profile.profile_version,
                resolved_profile_hash=resolved_profile.resolved_profile_hash,
                scope=resolved_profile.metric_scope,
                eligible=eligible,
                ineligible_reasons=reasons,
                area=candidate_area,
                area_unit=resolved_profile.area_unit,
                reference_area=reference_area,
                area_ratio=ratio,
                delay=candidate_delay,
                frequency=None,
                power=candidate_power,
                power_unit=resolved_profile.power_unit if eligible and power_scope else None,
                worst_negative_slack=candidate_wns,
                total_negative_slack=None,
                timing_unit=resolved_profile.timing_unit if eligible and timing_scope else None,
                clock_period=(
                    candidate_synthesis.clock_period
                    if eligible and timing_scope and candidate_synthesis is not None
                    else None
                ),
                reference_delay=reference_delay,
                reference_worst_negative_slack=reference_wns,
                reference_power=reference_power,
                delay_ratio=delay_ratio,
                worst_negative_slack_delta=(
                    candidate_wns - reference_wns
                    if candidate_wns is not None and reference_wns is not None
                    else None
                ),
                power_ratio=(
                    reference_power / candidate_power
                    if reference_power is not None and candidate_power is not None
                    else None
                ),
            ),
            synthesis=candidate_synthesis,
            reference_synthesis=reference_synthesis,
        )
        scope_label = (
            "area, timing, and power"
            if power_scope
            else "area and timing"
            if timing_scope
            else "area-only"
        )
        warnings.append(f"Synthesis quality is profile-relative, {scope_label}, and non-signoff.")
    edit_similarity_values = [
        value
        for result in results
        if isinstance((value := result.metadata.get("edit_similarity")), (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ]
    edit_similarity = float(edit_similarity_values[0]) if len(edit_similarity_values) == 1 else None
    return ScoreCard(
        run_id=run_id,
        task_id=task.id,
        status=status,
        resolved=resolved,
        correctness=correctness,
        quality=quality,
        efficiency=EfficiencyMetrics(
            wall_time_s=tracker.wall_time_s,
            agent_time_s=tracker.agent_time_s,
            tool_time_s=tracker.tool_time_s,
            verifier_time_s=tracker.verifier_time_s,
            model_input_tokens=tracker.model_input_tokens,
            model_output_tokens=tracker.model_output_tokens,
            total_tokens=tracker.total_tokens,
            model_calls=tracker.model_calls,
            model_api_cost=tracker.model_api_cost,
            model_api_cost_currency=tracker.model_api_cost_currency,
            model_api_cost_unit=tracker.model_api_cost_unit,
            turns=tracker.turns,
            tool_calls=tracker.tool_calls,
            failed_tool_calls=tracker.failed_tool_calls,
            external_cli_process_wall_time_s=(
                external_accounting.process_wall_time_s if external_accounting is not None else 0.0
            ),
            external_cli_event_count=(
                external_accounting.cli_event_count if external_accounting is not None else 0
            ),
            external_model_call_count=(
                external_accounting.model_call_count if external_accounting is not None else None
            ),
            external_tool_call_count=(
                external_accounting.external_tool_call_count
                if external_accounting is not None
                else None
            ),
            external_command_count=(
                external_accounting.external_command_count
                if external_accounting is not None
                else None
            ),
            external_file_read_count=(
                external_accounting.external_file_read_count
                if external_accounting is not None
                else None
            ),
            external_file_write_count=(
                external_accounting.external_file_write_count
                if external_accounting is not None
                else None
            ),
            external_patch_count=(
                external_accounting.external_patch_count
                if external_accounting is not None
                else None
            ),
            external_input_tokens=(
                external_accounting.input_tokens if external_accounting is not None else None
            ),
            external_output_tokens=(
                external_accounting.output_tokens if external_accounting is not None else None
            ),
            external_total_tokens=(
                external_accounting.total_tokens if external_accounting is not None else None
            ),
            external_cost=(external_accounting.cost if external_accounting is not None else None),
            external_cost_currency=(
                external_accounting.currency if external_accounting is not None else None
            ),
        ),
        patch=PatchMetrics(
            changed_files=diff.changed_files,
            added_lines=diff.added_lines,
            deleted_lines=diff.deleted_lines,
            total_diff_lines=diff.added_lines + diff.deleted_lines,
            changes_outside_expected_files=diff.changes_outside_expected_files,
            edit_similarity=edit_similarity,
        ),
        reproducibility=ReproducibilityMetrics(
            task_hash=task_hash,
            candidate_hash=candidate_hash,
            verifier_hash=content_hash(task.verifier),
            run_config_hash=run_config_hash,
            toolchain_profile_ids=[ref.id for ref in profile_refs],
            resolved_toolchain_profile_hashes=(
                [resolved_profile.resolved_profile_hash] if resolved_profile is not None else []
            ),
            deterministic=True,
            isolation_level=isolation_level,
        ),
        verifier_results=results,
        termination_reason=termination_reason.value,
        failure=episode_failure,
        warnings=warnings,
    )
