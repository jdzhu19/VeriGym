"""Deterministic paired held-out comparison for frozen agent versions."""

from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path

from verigym.core.hashing import content_hash
from verigym.core.sampling import classify_sample_outcome, compute_pass_at_k
from verigym.reporting.loader import ValidatedRun, load_report_inputs
from verigym.schemas.evolution import (
    EvolvingEvaluationReport,
    PairedVersionDifference,
    TaskSplitManifest,
    TaskVersionMetric,
    VersionMetricSummary,
)

from .rewards import classify_outcome
from .splits import validate_task_split


def _version_id(run: ValidatedRun) -> str:
    if run.plan_item is None:
        raise ValueError("evolving evaluation requires experiment-bound child runs")
    value = run.plan_item.system.agent_options.get("agent_version_id")
    if not isinstance(value, str):
        raise ValueError("held-out plan item lacks a frozen agent-version identity")
    return value


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _macro_pass(
    groups: dict[str, list[ValidatedRun]],
    *,
    k: int,
    expected_samples: int,
) -> float | None:
    values: list[float] = []
    for runs in groups.values():
        evaluable = [run for run in runs if classify_sample_outcome(run.scorecard)[1]]
        if len(evaluable) != expected_samples:
            return None
        resolved = sum(run.scorecard.resolved for run in evaluable)
        value = compute_pass_at_k(len(evaluable), resolved, k)
        if value is None:
            return None
        values.append(value)
    return _mean(values)


def _summary(
    *,
    version_id: str,
    planned: int,
    runs: list[ValidatedRun],
    expected_tasks: set[str],
    expected_samples: int,
    indexed_infrastructure_failures: int,
) -> VersionMetricSummary:
    groups: dict[str, list[ValidatedRun]] = defaultdict(list)
    for run in runs:
        groups[run.manifest.task_id].append(run)
    if set(groups) - expected_tasks:
        raise ValueError("evolving report contains a task outside the held-out split")
    outcomes = [classify_outcome(run.scorecard) for run in runs]
    evaluable = sum(classify_sample_outcome(run.scorecard)[1] for run in runs)
    policy_failures = sum(outcome == "contained_workspace_policy_failure" for outcome in outcomes)
    tokens = [
        float(value)
        for run in runs
        for value in [
            run.scorecard.efficiency.external_total_tokens
            if run.scorecard.efficiency.external_total_tokens is not None
            else run.scorecard.efficiency.total_tokens
        ]
        if value is not None
    ]
    wall_times = [run.scorecard.efficiency.wall_time_s for run in runs]
    input_tokens = [
        float(value)
        for run in runs
        for value in [
            run.scorecard.efficiency.external_input_tokens
            if run.scorecard.efficiency.external_input_tokens is not None
            else run.scorecard.efficiency.model_input_tokens
        ]
        if value is not None
    ]
    output_tokens = [
        float(value)
        for run in runs
        for value in [
            run.scorecard.efficiency.external_output_tokens
            if run.scorecard.efficiency.external_output_tokens is not None
            else run.scorecard.efficiency.model_output_tokens
        ]
        if value is not None
    ]
    public_calls = [float(run.manifest.repository_public_tool_invocation_count) for run in runs]
    changed_files = [float(len(run.scorecard.patch.changed_files)) for run in runs]
    patch_lines = [
        float(run.scorecard.patch.added_lines + run.scorecard.patch.deleted_lines) for run in runs
    ]
    resolved_tokens = [
        float(value)
        for run in runs
        if run.scorecard.resolved
        for value in [
            run.scorecard.efficiency.external_total_tokens
            if run.scorecard.efficiency.external_total_tokens is not None
            else run.scorecard.efficiency.total_tokens
        ]
        if value is not None
    ]
    resolved_wall_times = [
        run.scorecard.efficiency.wall_time_s for run in runs if run.scorecard.resolved
    ]
    return VersionMetricSummary(
        agent_version_id=version_id,
        planned=planned,
        launched=len(runs) + indexed_infrastructure_failures,
        terminal=len(runs) + indexed_infrastructure_failures,
        evaluable=evaluable,
        resolved=sum(run.scorecard.resolved for run in runs),
        candidate_failures=sum(
            outcome
            in {
                "incorrect_policy_compliant_candidate",
                "strict_output_failure",
            }
            for outcome in outcomes
        ),
        contained_policy_failures=policy_failures,
        infrastructure_failures=sum(outcome == "infrastructure_invalid" for outcome in outcomes)
        + indexed_infrastructure_failures,
        public_test_reached=sum(bool(run.manifest.repository_public_tests) for run in runs),
        hidden_verifier_reached=sum(
            any(
                "hidden" in result.node_id and result.status.value != "skipped"
                for result in run.scorecard.verifier_results
            )
            for run in runs
        ),
        patch_reproducible=sum(
            run.manifest.repository_candidate is not None
            and run.manifest.repository_candidate.patch.reapply_exact
            for run in runs
        ),
        macro_pass_at_1=_macro_pass(
            groups,
            k=1,
            expected_samples=expected_samples,
        ),
        macro_pass_at_2=_macro_pass(
            groups,
            k=2,
            expected_samples=expected_samples,
        ),
        macro_pass_at_3=_macro_pass(
            groups,
            k=3,
            expected_samples=expected_samples,
        ),
        policy_failure_rate=policy_failures / evaluable if evaluable else None,
        mean_public_tool_calls=_mean(public_calls),
        mean_changed_files=_mean(changed_files),
        mean_patch_lines=_mean(patch_lines),
        mean_input_tokens=_mean(input_tokens),
        mean_output_tokens=_mean(output_tokens),
        mean_tokens=_mean(tokens),
        mean_wall_time_s=_mean(wall_times),
        missing_usage_count=len(runs) - len(tokens),
        mean_tokens_per_resolved=_mean(resolved_tokens),
        mean_wall_time_per_resolved_s=_mean(resolved_wall_times),
    )


def _task_summary(
    *,
    task_id: str,
    version_id: str,
    planned: int,
    runs: list[ValidatedRun],
    infrastructure_failures: int,
    expected_samples: int,
) -> TaskVersionMetric:
    evaluable_runs = [run for run in runs if classify_sample_outcome(run.scorecard)[1]]
    resolved = sum(run.scorecard.resolved for run in evaluable_runs)
    complete = len(evaluable_runs) == expected_samples

    def pass_at(k: int) -> float | None:
        return compute_pass_at_k(len(evaluable_runs), resolved, k) if complete else None

    return TaskVersionMetric(
        task_id=task_id,
        agent_version_id=version_id,
        planned=planned,
        terminal=len(runs) + infrastructure_failures,
        evaluable=len(evaluable_runs),
        resolved=resolved,
        contained_policy_failures=sum(
            classify_outcome(run.scorecard) == "contained_workspace_policy_failure" for run in runs
        ),
        infrastructure_failures=infrastructure_failures
        + sum(classify_outcome(run.scorecard) == "infrastructure_invalid" for run in runs),
        pass_at_1=pass_at(1),
        pass_at_2=pass_at(2),
        pass_at_3=pass_at(3),
    )


def _delta(left: float | None, right: float | None) -> float | None:
    return right - left if left is not None and right is not None else None


def build_evolving_evaluation(
    experiment_root: Path,
    *,
    split_manifest: TaskSplitManifest,
    baseline_version_id: str,
    evolved_version_id: str,
    samples_per_task: int = 3,
) -> EvolvingEvaluationReport:
    """Build separate v0/v1 metrics from one immutable held-out experiment."""

    validate_task_split(split_manifest)
    inputs = load_report_inputs(experiment_root)
    expected_tasks = {item.task_id for item in split_manifest.heldout}
    planned_by_version: dict[str, list[int]] = defaultdict(list)
    planned_by_task_version: dict[tuple[str, str], int] = defaultdict(int)
    for item in inputs.plan_items:
        if item.task_id not in expected_tasks:
            raise ValueError("held-out experiment plan includes a non-held-out task")
        value = item.system.agent_options.get("agent_version_id")
        if not isinstance(value, str):
            raise ValueError("held-out plan item lacks agent_version_id")
        planned_by_version[value].append(item.plan_index)
        planned_by_task_version[(item.task_id, value)] += 1
    expected_versions = {baseline_version_id, evolved_version_id}
    if set(planned_by_version) != expected_versions:
        raise ValueError("held-out plan does not contain exactly the frozen v0/v1 versions")
    expected_per_version = len(expected_tasks) * samples_per_task
    if any(len(indices) != expected_per_version for indices in planned_by_version.values()):
        raise ValueError("held-out plan does not contain the expected samples per version")
    runs_by_version: dict[str, list[ValidatedRun]] = defaultdict(list)
    for run in inputs.valid_runs:
        runs_by_version[_version_id(run)].append(run)
    indexed_infrastructure: dict[str, int] = defaultdict(int)
    indexed_infrastructure_by_task: dict[tuple[str, str], int] = defaultdict(int)
    by_index = {item.plan_index: item for item in inputs.plan_items}
    valid_indices = {run.plan_index for run in inputs.valid_runs}
    for record in inputs.index_records:
        if record.plan_index in valid_indices or not record.infrastructure_error:
            continue
        item = by_index[record.plan_index]
        value = item.system.agent_options.get("agent_version_id")
        if isinstance(value, str):
            indexed_infrastructure[value] += 1
            indexed_infrastructure_by_task[(item.task_id, value)] += 1
    summaries = [
        _summary(
            version_id=version_id,
            planned=len(planned_by_version[version_id]),
            runs=runs_by_version[version_id],
            expected_tasks=expected_tasks,
            expected_samples=samples_per_task,
            indexed_infrastructure_failures=indexed_infrastructure[version_id],
        )
        for version_id in (baseline_version_id, evolved_version_id)
    ]
    baseline, evolved = summaries
    task_metrics = [
        _task_summary(
            task_id=task_id,
            version_id=version_id,
            planned=planned_by_task_version[(task_id, version_id)],
            runs=[run for run in runs_by_version[version_id] if run.manifest.task_id == task_id],
            infrastructure_failures=indexed_infrastructure_by_task[(task_id, version_id)],
            expected_samples=samples_per_task,
        )
        for task_id in sorted(expected_tasks)
        for version_id in (baseline_version_id, evolved_version_id)
    ]
    paired = PairedVersionDifference(
        baseline_version_id=baseline_version_id,
        evolved_version_id=evolved_version_id,
        macro_pass_at_1_delta=_delta(baseline.macro_pass_at_1, evolved.macro_pass_at_1),
        macro_pass_at_2_delta=_delta(baseline.macro_pass_at_2, evolved.macro_pass_at_2),
        macro_pass_at_3_delta=_delta(baseline.macro_pass_at_3, evolved.macro_pass_at_3),
        policy_failure_rate_delta=_delta(
            baseline.policy_failure_rate,
            evolved.policy_failure_rate,
        ),
        mean_tokens_delta=_delta(baseline.mean_tokens, evolved.mean_tokens),
        mean_wall_time_s_delta=_delta(
            baseline.mean_wall_time_s,
            evolved.mean_wall_time_s,
        ),
    )
    base = {
        "schema_version": "1.0",
        "report_id": f"{inputs.experiment_id}-evolving-evaluation",
        "split_manifest_hash": split_manifest.manifest_hash,
        "heldout_plan_hash": inputs.plan_hash,
        "version_metrics": [item.model_dump(mode="json") for item in summaries],
        "task_version_metrics": [item.model_dump(mode="json") for item in task_metrics],
        "paired_difference": paired.model_dump(mode="json"),
        "heldout_task_count": len(expected_tasks),
        "samples_per_task_version": samples_per_task,
        "no_weight_update": True,
        "establishes_general_improvement": False,
        "required_interpretation": (
            "The before/after result is a bounded first-party Evolve-Context pilot and "
            "does not establish general performance improvement."
        ),
    }
    return EvolvingEvaluationReport.model_validate({**base, "report_hash": content_hash(base)})


def validate_evolving_evaluation(
    report: EvolvingEvaluationReport,
) -> EvolvingEvaluationReport:
    payload = report.model_dump(mode="json")
    expected = payload.pop("report_hash")
    if content_hash(payload) != expected:
        raise ValueError("evolving-evaluation report identity changed")
    version_ids = [item.agent_version_id for item in report.version_metrics]
    if len(version_ids) != 2 or len(set(version_ids)) != 2:
        raise ValueError("evolving-evaluation report requires distinct v0/v1 summaries")
    expected_task_rows = report.heldout_task_count * len(version_ids)
    if len(report.task_version_metrics) != expected_task_rows:
        raise ValueError("evolving-evaluation task/version coverage changed")
    pairs = {(item.task_id, item.agent_version_id) for item in report.task_version_metrics}
    if len(pairs) != expected_task_rows:
        raise ValueError("evolving-evaluation repeats a task/version group")
    return report


__all__ = ["build_evolving_evaluation", "validate_evolving_evaluation"]
