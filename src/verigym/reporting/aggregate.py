"""Deterministic aggregation with explicit denominators and compatibility partitions."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.core.sampling import (
    classify_sample_outcome,
    compute_pass_at_k,
    manifest_configuration_fingerprint,
)
from verigym.experiments.schemas import PlanItem
from verigym.provenance import get_build_provenance
from verigym.reporting.loader import LoadedReportInputs, ValidatedRun, load_report_inputs
from verigym.reporting.schemas import (
    AggregateReport,
    CompatibilityAggregate,
    CostAccounting,
    CostPartition,
    CoverageCounts,
    ExplicitRate,
    FailureTaxonomy,
    GroupAggregate,
    NumericSummary,
    PassAtKMacro,
    QualityPartition,
    QualityRunValue,
    SampleGroupAggregate,
    SamplingAggregate,
    StageRate,
)
from verigym.schemas.sampling import PassAtKEntry, SampleOutcome

_GROUP_DIMENSIONS = {
    "suite",
    "release",
    "category",
    "difficulty",
    "task",
    "system",
    "model",
    "agent",
    "interaction_mode",
    "runtime",
    "profile_id",
    "profile_hash",
    "base_seed",
    "integration_track",
    "cli_version",
    "cli_executable_sha256",
    "capability_fingerprint",
    "requested_model_id",
    "observed_model_id",
    "identity_confidence",
    "auth_mode_label",
    "sandbox_policy",
    "approval_policy",
}


class ReportBuilder:
    """Build canonical reports without invoking a model, tool, runtime, or network."""

    def build(
        self,
        root: Path,
        *,
        group_by: Iterable[str] = ("system",),
    ) -> AggregateReport:
        return self.build_inputs(load_report_inputs(root), group_by=group_by)

    def build_inputs(
        self,
        inputs: LoadedReportInputs,
        *,
        group_by: Iterable[str] = ("system",),
    ) -> AggregateReport:
        """Aggregate one already validated, immutable ingestion snapshot."""

        dimensions = list(group_by)
        unknown = sorted(set(dimensions) - _GROUP_DIMENSIONS)
        if unknown:
            raise ValueError(f"unsupported report grouping dimensions: {', '.join(unknown)}")
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("report grouping dimensions must be unique")
        runs = _current_runs(inputs)
        coverage = _coverage(inputs, runs)
        warnings = _compatibility_warnings(inputs, runs)
        compatibility = _compatibility_partitions(runs)
        compatibility_aggregates = _compatibility_aggregates(inputs, runs)
        mixed_correctness_scope = len(compatibility_aggregates) > 1
        coarse_reason = (
            "mixed_release_or_correctness_partitions" if mixed_correctness_scope else None
        )
        efficiency = _efficiency_summaries(runs)
        cost, cost_accounting = _cost_summary(runs)
        sampling = _sampling(inputs, runs)
        if cost.missing_value_count:
            warnings.append(
                f"Model cost is missing for {cost.missing_value_count} resolved run(s)."
            )
        if cost_accounting.unknown_unit_count:
            warnings.append(
                f"{cost_accounting.unknown_unit_count} model cost value(s) have no persisted "
                "currency or provider-unit identity and are not summed."
            )
        if cost_accounting.incompatible_unit_count:
            warnings.append(
                "Model costs span incompatible units and are partitioned, not combined."
            )
        missing_efficiency = sorted(
            name for name, summary in efficiency.items() if summary.missing_value_count
        )
        if missing_efficiency:
            warnings.append(
                "Resolved-run efficiency values are missing for: "
                + ", ".join(missing_efficiency)
                + "."
            )
        if inputs.invalid_inputs:
            warnings.append(
                f"{len(inputs.invalid_inputs)} corrupt, incompatible, or unsafe artifact(s) "
                "were excluded."
            )
        legacy_integrity = sum(run.integrity_status == "legacy_unverified" for run in runs) + int(
            inputs.parent_integrity_status == "legacy_unverified"
        )
        if legacy_integrity:
            warnings.append(f"{legacy_integrity} legacy artifact set(s) had no integrity manifest.")
        if inputs.parent_integrity_status == "integrity_failed":
            warnings.append(
                "The experiment parent integrity manifest failed validation; "
                "affected records are diagnostic-only."
            )
        invalid_sample_groups = sum(not group.canonical_valid for group in sampling.groups)
        if invalid_sample_groups:
            warnings.append(
                f"{invalid_sample_groups} canonical sample group(s) are incomplete or invalid."
            )
        aggregate = AggregateReport(
            experiment_id=inputs.experiment_id,
            source_kind=inputs.source_kind,  # type: ignore[arg-type]
            config_hash=inputs.config_hash,
            plan_hash=inputs.plan_hash,
            task_set_hash=inputs.task_set_hash,
            input_set_hash=_input_set_hash(inputs, runs),
            build_provenance=get_build_provenance(),
            compatibility_partitions=compatibility,
            compatibility_aggregates=compatibility_aggregates,
            coverage=coverage,
            resolved_rate_evaluable=_rate(
                coverage.resolved_runs,
                coverage.evaluable_candidate_runs,
                unavailable_reason=coarse_reason,
            ),
            resolved_rate_planned=_rate(
                coverage.resolved_runs,
                coverage.planned_plan_items,
                unavailable_reason=coarse_reason,
            ),
            evaluation_completion_rate=_rate(
                coverage.evaluable_candidate_runs, coverage.planned_plan_items
            ),
            correctness_stages=[] if mixed_correctness_scope else _stage_rates(runs),
            efficiency_resolved=efficiency,
            cost_resolved=cost,
            cost_accounting=cost_accounting,
            failure_taxonomy=_failure_taxonomy(inputs, runs),
            sampling=sampling,
            quality_partitions=_quality_partitions(runs),
            grouped_aggregates=_grouped(inputs, runs, dimensions),
            warnings=sorted(set(warnings)),
            invalid_inputs=sorted(
                inputs.invalid_inputs,
                key=lambda item: (
                    item.plan_index if item.plan_index is not None else 2**63,
                    item.attempt if item.attempt is not None else 0,
                    item.relative_path,
                ),
            ),
            metadata={
                "resolved_population": "valid evaluable child artifacts",
                "efficiency_population": "resolved runs",
                "cost_currency_policy": "unknown currency is never summed",
                "quality_scope": "profile-relative synthesis area only",
                "universal_score": None,
                "parent_integrity_status": inputs.parent_integrity_status,
                "legacy_unverified_run_count": sum(
                    run.integrity_status == "legacy_unverified" for run in runs
                ),
                "model_identity_reproducibility_scopes": dict(
                    sorted(
                        Counter(
                            observation.reproducibility_scope
                            for run in runs
                            for observation in run.manifest.model_observations
                        ).items()
                    )
                ),
                "codex_cli_identity_partitions": _codex_cli_partitions(runs),
                "codex_cli_comparison_policy": (
                    "tracks, executable versions, and capability fingerprints remain distinct"
                ),
                "combined_correctness_scope": (
                    "unavailable_for_mixed_release_or_correctness_partitions"
                    if mixed_correctness_scope
                    else "single_compatibility_partition"
                ),
            },
        )
        return AggregateReport.model_validate(aggregate.model_dump(mode="json"))


def _current_runs(inputs: LoadedReportInputs) -> list[ValidatedRun]:
    if inputs.source_kind == "runs_root":
        return sorted(inputs.valid_runs, key=lambda item: (item.plan_index, item.attempt))
    latest_records = {
        record.plan_index: record
        for record in sorted(inputs.index_records, key=lambda item: (item.plan_index, item.attempt))
    }
    valid_by_attempt = {(run.plan_index, run.attempt): run for run in inputs.valid_runs}
    current: list[ValidatedRun] = []
    for plan_index in sorted(latest_records):
        record = latest_records[plan_index]
        run = valid_by_attempt.get((plan_index, record.attempt))
        if run is not None:
            current.append(run)
    return current


def _is_infrastructure(run: ValidatedRun) -> bool:
    score = run.scorecard
    return bool(
        score.status == "error"
        or score.correctness.infrastructure_error
        or (score.failure is not None and score.failure.infrastructure)
    )


def _is_cancelled(run: ValidatedRun) -> bool:
    outcome, _verdict = classify_sample_outcome(run.scorecard)
    return outcome == SampleOutcome.CANCELLED_TRUNCATED


def _is_evaluable(run: ValidatedRun) -> bool:
    return not _is_infrastructure(run) and not _is_cancelled(run)


def _coverage(inputs: LoadedReportInputs, runs: list[ValidatedRun]) -> CoverageCounts:
    latest_records = _latest_index_records(inputs)
    valid_plan_indices = {run.plan_index for run in runs}
    started = (
        len({record.plan_index for record in inputs.index_records})
        if inputs.source_kind == "experiment"
        else len(runs) + len(inputs.invalid_inputs)
    )
    terminal = (
        len(
            {
                record.plan_index
                for record in inputs.index_records
                if record.terminal_status not in {"started", "scheduled"}
            }
        )
        if inputs.source_kind == "experiment"
        else len(runs) + len(inputs.invalid_inputs)
    )
    evaluable = sum(_is_evaluable(run) for run in runs)
    resolved = sum(run.scorecard.resolved for run in runs if _is_evaluable(run))
    infrastructure = sum(_is_infrastructure(run) for run in runs) + sum(
        record.infrastructure_error
        for plan_index, record in latest_records.items()
        if plan_index not in valid_plan_indices
    )
    cancelled = sum(_is_cancelled(run) for run in runs) + sum(
        record.terminal_status in {"cancelled", "interrupted"}
        for plan_index, record in latest_records.items()
        if plan_index not in valid_plan_indices
    )
    return CoverageCounts(
        planned_plan_items=inputs.planned_count,
        started_plan_items=started,
        terminal_child_runs=terminal,
        valid_terminal_artifacts=len(runs),
        evaluable_candidate_runs=evaluable,
        resolved_runs=resolved,
        unresolved_evaluable_runs=evaluable - resolved,
        infrastructure_error_runs=infrastructure,
        cancelled_interrupted_runs=cancelled,
        corrupt_incompatible_artifacts=len(inputs.invalid_inputs),
        missing_plan_items=max(0, inputs.planned_count - len(runs)),
    )


def _rate(
    numerator: int,
    denominator: int,
    *,
    unavailable_reason: str | None = None,
) -> ExplicitRate:
    return ExplicitRate(
        numerator=numerator,
        denominator=denominator,
        value=(numerator / denominator if denominator and unavailable_reason is None else None),
        unavailable_reason=unavailable_reason,
    )


def _stage_rates(runs: list[ValidatedRun]) -> list[StageRate]:
    fields = (
        ("compile", "compile_status"),
        ("hidden_regression", "hidden_regression_status"),
        ("formal", "formal_status"),
        ("equivalence", "equivalence_status"),
    )
    results: list[StageRate] = []
    for stage, field in fields:
        applicable = [
            run
            for run in runs
            if getattr(run.scorecard.correctness, field) is not None and not _is_infrastructure(run)
        ]
        numerator = sum(getattr(run.scorecard.correctness, field) == "passed" for run in applicable)
        results.append(
            StageRate(
                stage=stage,
                numerator=numerator,
                denominator=len(applicable),
                rate=numerator / len(applicable) if applicable else None,
                missing_count=sum(
                    getattr(run.scorecard.correctness, field) is None for run in runs
                ),
                infrastructure_error_count=sum(
                    _is_infrastructure(run)
                    and getattr(run.scorecard.correctness, field) is not None
                    for run in runs
                ),
            )
        )
    return results


def _numeric_summary(
    values: list[float | int | None],
    *,
    population: str,
    unit: str | None,
    include_sum: bool = False,
) -> NumericSummary:
    known = [float(value) for value in values if value is not None]
    return NumericSummary(
        population=population,
        known_value_count=len(known),
        missing_value_count=len(values) - len(known),
        mean=statistics.fmean(known) if known else None,
        median=statistics.median(known) if known else None,
        sum=sum(known) if known and include_sum else None,
        unit=unit,
    )


def _efficiency_summaries(runs: list[ValidatedRun]) -> dict[str, NumericSummary]:
    resolved = [run for run in runs if run.scorecard.resolved and _is_evaluable(run)]
    fields = {
        "wall_time_s": ("wall_time_s", "seconds"),
        "model_input_tokens": ("model_input_tokens", "tokens"),
        "model_output_tokens": ("model_output_tokens", "tokens"),
        "total_tokens": ("total_tokens", "tokens"),
        "tool_calls": ("tool_calls", "calls"),
        "turns": ("turns", "turns"),
        "external_tool_call_count": ("external_tool_call_count", "calls"),
        "external_command_count": ("external_command_count", "commands"),
        "external_input_tokens": ("external_input_tokens", "tokens"),
        "external_output_tokens": ("external_output_tokens", "tokens"),
        "external_total_tokens": ("external_total_tokens", "tokens"),
    }
    summaries = {
        key: _numeric_summary(
            [getattr(run.scorecard.efficiency, field) for run in resolved],
            population="resolved_runs",
            unit=unit,
        )
        for key, (field, unit) in fields.items()
    }
    summaries["cli_process_wall_time_s"] = _numeric_summary(
        [
            (
                run.codex_cli_accounting.process_wall_time_s
                if run.codex_cli_accounting is not None
                else None
            )
            for run in resolved
        ],
        population="resolved_runs",
        unit="seconds",
    )
    summaries["external_cli_process_wall_time_s"] = _numeric_summary(
        [
            (
                run.scorecard.efficiency.external_cli_process_wall_time_s
                if run.manifest.external_agent_observations
                else None
            )
            for run in resolved
        ],
        population="resolved_runs",
        unit="seconds",
    )
    return summaries


def _cost_summary(runs: list[ValidatedRun]) -> tuple[NumericSummary, CostAccounting]:
    resolved = [run for run in runs if run.scorecard.resolved and _is_evaluable(run)]
    missing = 0
    unknown = 0
    partitions: dict[tuple[str, str], list[float]] = {}
    observed = 0
    for run in resolved:
        efficiency = run.scorecard.efficiency
        value = efficiency.model_api_cost
        if value is None:
            missing += 1
            continue
        observed += 1
        if efficiency.model_api_cost_currency is not None:
            key = ("currency", efficiency.model_api_cost_currency)
        elif efficiency.model_api_cost_unit is not None:
            key = ("provider_unit", efficiency.model_api_cost_unit)
        else:
            unknown += 1
            continue
        partitions.setdefault(key, []).append(value)
    summaries = [
        CostPartition(
            dimension=dimension,  # type: ignore[arg-type]
            identifier=identifier,
            known_value_count=len(values),
            sum=sum(values),
        )
        for (dimension, identifier), values in sorted(partitions.items())
    ]
    incompatible = sum(item.known_value_count for item in summaries) if len(summaries) > 1 else 0
    single = summaries[0] if len(summaries) == 1 and unknown == 0 else None
    legacy = NumericSummary(
        population="resolved_runs",
        known_value_count=observed,
        missing_value_count=missing,
        mean=None,
        median=None,
        sum=single.sum if single is not None else None,
        unit=(
            single.identifier
            if single is not None and single.dimension == "provider_unit"
            else "currency"
        ),
        currency=(
            single.identifier if single is not None and single.dimension == "currency" else None
        ),
    )
    return legacy, CostAccounting(
        population="resolved_runs",
        observed_value_count=observed,
        missing_value_count=missing,
        unknown_unit_count=unknown,
        incompatible_unit_count=incompatible,
        partitions=summaries,
    )


def _failure_taxonomy(
    inputs: LoadedReportInputs,
    runs: list[ValidatedRun],
) -> FailureTaxonomy:
    candidate: Counter[str] = Counter()
    model: Counter[str] = Counter()
    runtime: Counter[str] = Counter()
    verifier: Counter[str] = Counter()
    batch: Counter[str] = Counter(item.category for item in inputs.invalid_inputs)
    for run in runs:
        score = run.scorecard
        outcome, _candidate_verdict = classify_sample_outcome(score)
        if _is_evaluable(run):
            # Candidate outcomes use the same structured Milestone 6 taxonomy as
            # sampling.  In particular, do not turn agent prose such as a final
            # message into a failure category.
            candidate[outcome.value] += 1
        if score.failure is not None and score.failure.infrastructure:
            target = model if score.failure.kind == "model" else runtime
            target[score.failure.category] += 1
        for result in score.verifier_results:
            if result.status.value == "error":
                verifier[result.error_category.value] += 1
    valid_plan_indices = {run.plan_index for run in runs}
    for plan_index, record in _latest_index_records(inputs).items():
        if plan_index in valid_plan_indices or not record.infrastructure_error:
            continue
        if record.child_exit_category == "MissingDependencyError":
            verifier[record.child_exit_category] += 1
        else:
            runtime[record.child_exit_category] += 1
    return FailureTaxonomy(
        candidate_outcomes=dict(sorted(candidate.items())),
        model_infrastructure=dict(sorted(model.items())),
        runtime_sandbox=dict(sorted(runtime.items())),
        verifier_tool=dict(sorted(verifier.items())),
        batch_artifact=dict(sorted(batch.items())),
    )


def _sample_group_key(run: ValidatedRun) -> dict[str, Any]:
    manifest = run.manifest
    return {
        "configuration_fingerprint": manifest_configuration_fingerprint(manifest),
        "release_id": manifest.release_id,
        "declared_profile_hash": manifest.declared_profile_hash,
        "resolved_profile_hash": manifest.resolved_profile_hash,
        "base_seed": manifest.base_seed if manifest.base_seed is not None else manifest.seed,
        "system_id": manifest.system_id or _fallback_system(run),
    }


def _sampling(
    inputs: LoadedReportInputs,
    runs: list[ValidatedRun],
) -> SamplingAggregate:
    expected: dict[str, list[Any]] = defaultdict(list)
    if inputs.plan_items:
        for item in inputs.plan_items:
            key = content_hash(
                {
                    "task_id": item.task_id,
                    "task_hash": item.task_hash,
                    "source_identity_hash": item.source_identity_hash,
                    "system": item.system,
                    "prompt_policy": item.prompt_policy,
                    "tool_policy": item.tool_policy,
                    "interaction_mode": item.interaction_mode,
                    "budget": item.budget,
                    "generation": item.generation,
                    "max_invalid_actions": item.max_invalid_actions,
                    "verifier_hash": item.verifier_hash,
                    "correctness_definition_hash": item.correctness_definition_hash,
                    "runtime_identity_hash": item.runtime_identity_hash,
                    "declared_profile_hash": item.declared_profile_hash,
                    "resolved_profile_hash": item.resolved_profile_hash,
                    "base_seed": item.base_seed,
                }
            )
            expected[key].append(item)
    observed: dict[str, list[ValidatedRun]] = defaultdict(list)
    for run in runs:
        if run.plan_item is not None:
            item = run.plan_item
            key = content_hash(
                {
                    "task_id": item.task_id,
                    "task_hash": item.task_hash,
                    "source_identity_hash": item.source_identity_hash,
                    "system": item.system,
                    "prompt_policy": item.prompt_policy,
                    "tool_policy": item.tool_policy,
                    "interaction_mode": item.interaction_mode,
                    "budget": item.budget,
                    "generation": item.generation,
                    "max_invalid_actions": item.max_invalid_actions,
                    "verifier_hash": item.verifier_hash,
                    "correctness_definition_hash": item.correctness_definition_hash,
                    "runtime_identity_hash": item.runtime_identity_hash,
                    "declared_profile_hash": item.declared_profile_hash,
                    "resolved_profile_hash": item.resolved_profile_hash,
                    "base_seed": item.base_seed,
                }
            )
        else:
            key = content_hash(_sample_group_key(run))
            expected[key].append(run)
        observed[key].append(run)
    latest_records = _latest_index_records(inputs)
    valid_by_plan_index = {run.plan_index: run for run in runs}
    groups: list[SampleGroupAggregate] = []
    for key in sorted(expected):
        planned = expected[key]
        present = sorted(
            observed.get(key, []),
            key=lambda item: item.manifest.sample_index or 0,
        )
        first_plan = planned[0] if planned and not isinstance(planned[0], ValidatedRun) else None
        if first_plan is not None:
            task_id = first_plan.task_id
            system_id = first_plan.system.system_id
            base_seed = first_plan.base_seed
        elif present:
            first_run = present[0]
            task_id = first_run.manifest.task_id
            system_id = _fallback_system(first_run)
            base_seed = (
                first_run.manifest.base_seed
                if first_run.manifest.base_seed is not None
                else first_run.manifest.seed
            )
        else:  # Defensive: every arbitrary-root expected group contains its source run.
            raise ValueError("sample group has neither a plan item nor a child run")
        outcomes = [classify_sample_outcome(run.scorecard)[0] for run in present]
        resolved = outcomes.count(SampleOutcome.RESOLVED)
        indexed_infrastructure = 0
        indexed_cancelled = 0
        if first_plan is not None:
            for item in planned:
                if item.plan_index in valid_by_plan_index:
                    continue
                record = latest_records.get(item.plan_index)
                if record is None:
                    continue
                indexed_infrastructure += int(record.infrastructure_error)
                indexed_cancelled += int(record.terminal_status in {"cancelled", "interrupted"})
        infrastructure = outcomes.count(SampleOutcome.INFRASTRUCTURE_ERROR) + indexed_infrastructure
        cancelled = outcomes.count(SampleOutcome.CANCELLED_TRUNCATED) + indexed_cancelled
        evaluable = sum(
            outcome
            in {
                SampleOutcome.RESOLVED,
                SampleOutcome.CANDIDATE_FAILURE,
                SampleOutcome.MODEL_OUTPUT_FAILURE,
            }
            for outcome in outcomes
        )
        expected_n = len(planned)
        missing = expected_n - len(present) - indexed_infrastructure - indexed_cancelled
        sample_indices = [run.manifest.sample_index for run in present]
        duplicate_sample_index = len(
            {index for index in sample_indices if index is not None}
        ) != len([index for index in sample_indices if index is not None])
        codex_identities = {
            (
                identity.get("integration_track", ""),
                identity.get("requested_model_id", ""),
                identity.get("observed_model_id", ""),
                identity.get("cli_version", ""),
                identity.get("cli_executable_sha256", ""),
                identity.get("capability_fingerprint", ""),
            )
            for run in present
            if (identity := _run_codex_identity(run))
        }
        reason = (
            "duplicate_sample_index"
            if duplicate_sample_index
            else "mixed_codex_cli_identity"
            if len(codex_identities) > 1
            else "infrastructure_error"
            if infrastructure
            else "cancelled_or_truncated"
            if cancelled
            else "missing_child_results"
            if missing
            else "incomplete_candidate_verdicts"
            if evaluable != expected_n
            else None
        )
        entries = [
            PassAtKEntry(
                k=k,
                n=expected_n,
                c=resolved,
                value=compute_pass_at_k(expected_n, resolved, k) if reason is None else None,
                valid=reason is None,
                invalid_reason=reason,
            )
            for k in inputs.requested_k
        ]
        groups.append(
            SampleGroupAggregate(
                group_id=key,
                task_id=task_id,
                system_id=system_id,
                base_seed=base_seed,
                expected_n=expected_n,
                observed_n=len(present) + indexed_infrastructure + indexed_cancelled,
                resolved_c=resolved,
                evaluable_count=evaluable,
                infrastructure_error_count=infrastructure,
                cancelled_count=cancelled,
                missing_count=missing,
                canonical_valid=reason is None,
                invalid_reason=reason,
                best_of_n_success=resolved > 0 if reason is None else None,
                entries=entries,
            )
        )
    groups.sort(key=lambda group: (group.task_id, group.system_id, group.base_seed, group.group_id))
    macro: list[PassAtKMacro] = []
    for k in inputs.requested_k:
        entries = [next(entry for entry in group.entries if entry.k == k) for group in groups]
        values = [entry.value for entry in entries if entry.valid and entry.value is not None]
        macro.append(
            PassAtKMacro(
                k=k,
                valid_group_count=len(values),
                invalid_group_count=sum(not entry.valid for entry in entries),
                missing_group_count=sum(
                    group.invalid_reason == "missing_child_results" for group in groups
                ),
                macro_mean=statistics.fmean(values) if values else None,
                macro_median=statistics.median(values) if values else None,
            )
        )
    return SamplingAggregate(groups=groups, macro=macro)


def _quality_partitions(runs: list[ValidatedRun]) -> list[QualityPartition]:
    grouped: dict[str, list[ValidatedRun]] = defaultdict(list)
    identities: dict[str, dict[str, str | None]] = {}
    for run in runs:
        ppa = run.scorecard.quality.ppa
        manifest = run.manifest
        plan = run.plan_item
        if ppa is None:
            continue
        declared_id = manifest.requested_toolchain_profile_id or ppa.profile_id
        partition_identity = {
            "suite_source_identity": content_hash(
                manifest.suite_source
                or {"suite": manifest.suite, "version": manifest.suite_version}
            ),
            "task_id": manifest.task_id,
            "task_hash": manifest.task_hash,
            "correctness_definition_hash": (
                plan.correctness_definition_hash if plan is not None else manifest.verifier_hash
            ),
            "declared_profile_id": declared_id,
            "declared_profile_hash": manifest.declared_profile_hash,
            "resolved_profile_hash": manifest.resolved_profile_hash,
            "runtime_identity_hash": (
                plan.runtime_identity_hash
                if plan is not None
                else content_hash(
                    manifest.runtime.model_dump(
                        mode="json",
                        exclude={"sessions", "cleanup"},
                    )
                )
            ),
            "image_id": (
                manifest.runtime.image.resolved_image_id if manifest.runtime.image else None
            ),
            "area_unit": ppa.area_unit,
            "reference_candidate_hash": manifest.reference_candidate_hash,
        }
        if any(
            partition_identity[key] is None
            for key in (
                "declared_profile_hash",
                "resolved_profile_hash",
                "area_unit",
                "reference_candidate_hash",
            )
        ):
            continue
        key = content_hash(partition_identity)
        identities[key] = partition_identity
        grouped[key].append(run)
    partitions: list[QualityPartition] = []
    for key in sorted(grouped):
        members = sorted(grouped[key], key=lambda item: (item.plan_index, item.attempt))
        identity = identities[key]
        reason_counts: Counter[str] = Counter()
        run_values: list[QualityRunValue] = []
        ratios: list[float] = []
        coverage: Counter[str] = Counter()
        for run in members:
            ppa = run.scorecard.quality.ppa
            assert ppa is not None
            reason_counts.update(ppa.ineligible_reasons)
            synthesis = run.scorecard.quality.synthesis
            reference = run.scorecard.quality.reference_synthesis
            raw_area = synthesis.mapped_area_raw if synthesis is not None else ppa.area
            raw_reference = (
                reference.mapped_area_raw if reference is not None else ppa.reference_area
            )
            if ppa.area_ratio is not None:
                ratios.append(ppa.area_ratio)
            system = run.plan_item.system.system_id if run.plan_item else _fallback_system(run)
            coverage[f"{run.manifest.task_id}|{system}"] += 1
            run_values.append(
                QualityRunValue(
                    plan_index=run.plan_index,
                    run_id=run.manifest.run_id,
                    task_id=run.manifest.task_id,
                    system_id=system,
                    eligible=ppa.eligible,
                    ineligible_reasons=ppa.ineligible_reasons,
                    area=raw_area,
                    reference_area=raw_reference,
                    area_ratio=ppa.area_ratio,
                )
            )
        partitions.append(
            QualityPartition(
                partition_id=key,
                suite_source_identity=str(identity["suite_source_identity"]),
                task_id=str(identity["task_id"]),
                task_hash=str(identity["task_hash"]),
                correctness_definition_hash=str(identity["correctness_definition_hash"]),
                declared_profile_id=str(identity["declared_profile_id"]),
                declared_profile_hash=str(identity["declared_profile_hash"]),
                resolved_profile_hash=str(identity["resolved_profile_hash"]),
                runtime_identity_hash=str(identity["runtime_identity_hash"]),
                image_id=identity["image_id"],
                area_unit=str(identity["area_unit"]),
                reference_candidate_hash=str(identity["reference_candidate_hash"]),
                eligible_run_count=sum(value.eligible for value in run_values),
                ineligible_run_count=sum(not value.eligible for value in run_values),
                ineligible_reasons=dict(sorted(reason_counts.items())),
                task_system_coverage=dict(sorted(coverage.items())),
                ratio_min=min(ratios) if ratios else None,
                ratio_median=statistics.median(ratios) if ratios else None,
                ratio_max=max(ratios) if ratios else None,
                runs=run_values,
            )
        )
    return partitions


def _grouped(
    inputs: LoadedReportInputs,
    runs: list[ValidatedRun],
    dimensions: list[str],
) -> list[GroupAggregate]:
    conflicts = _compatibility_conflicts(inputs, runs)
    run_groups: dict[tuple[str, ...], list[ValidatedRun]] = defaultdict(list)
    for run in runs:
        key = (
            _run_compatibility_partition_id(run, conflicts),
            *(_group_value(run, dimension) for dimension in dimensions),
        )
        run_groups[key].append(run)
    planned_groups: Counter[tuple[str, ...]] = Counter()
    if inputs.plan_items:
        for item in inputs.plan_items:
            key = (
                _plan_compatibility_partition_id(item, conflicts),
                *(_plan_group_value(item, dimension) for dimension in dimensions),
            )
            planned_groups[key] += 1
    else:
        planned_groups.update({key: len(value) for key, value in run_groups.items()})
    results: list[GroupAggregate] = []
    for key in sorted(planned_groups):
        members = run_groups.get(key, [])
        evaluable = [run for run in members if _is_evaluable(run)]
        resolved = sum(run.scorecard.resolved for run in evaluable)
        results.append(
            GroupAggregate(
                compatibility_partition_id=key[0],
                dimensions=dict(zip(dimensions, key[1:], strict=True)),
                planned_count=planned_groups[key],
                valid_count=len(members),
                evaluable_count=len(evaluable),
                resolved_count=resolved,
                resolved_rate_evaluable=_rate(resolved, len(evaluable)),
                task_coverage_count=len({run.manifest.task_id for run in members}),
            )
        )
    return results


def _run_suite_release_identity(run: ValidatedRun) -> str:
    return content_hash(
        {
            "suite": run.manifest.suite,
            "version": run.manifest.suite_version,
            "release": run.manifest.release_id,
            "source": run.manifest.suite_source,
        }
    )


def _plan_suite_release_identity(item: PlanItem) -> str:
    return content_hash(
        {
            "suite": item.suite,
            "version": item.suite_version,
            "release": item.release_id,
            "source": item.suite_source_snapshot,
        }
    )


def _run_correctness_identity(run: ValidatedRun) -> str:
    return (
        run.plan_item.correctness_definition_hash
        if run.plan_item is not None
        else run.manifest.verifier_hash
    )


def _run_compatibility_partition_id(
    run: ValidatedRun,
    conflicts: set[tuple[str, str]],
) -> str:
    suite_identity = _run_suite_release_identity(run)
    payload: dict[str, Any] = {"suite_release_identity": suite_identity}
    if (suite_identity, run.manifest.task_id) in conflicts:
        payload["conflicting_task"] = {
            "task_id": run.manifest.task_id,
            "task_hash": run.manifest.task_hash,
            "correctness_definition_hash": _run_correctness_identity(run),
        }
    return content_hash(payload)


def _plan_compatibility_partition_id(
    item: PlanItem,
    conflicts: set[tuple[str, str]],
) -> str:
    suite_identity = _plan_suite_release_identity(item)
    payload: dict[str, Any] = {"suite_release_identity": suite_identity}
    if (suite_identity, item.task_id) in conflicts:
        payload["conflicting_task"] = {
            "task_id": item.task_id,
            "task_hash": item.task_hash,
            "correctness_definition_hash": item.correctness_definition_hash,
        }
    return content_hash(payload)


def _compatibility_conflicts(
    inputs: LoadedReportInputs,
    runs: list[ValidatedRun],
) -> set[tuple[str, str]]:
    contracts: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    if inputs.plan_items:
        for item in inputs.plan_items:
            key = (_plan_suite_release_identity(item), item.task_id)
            contracts[key].add((item.task_hash, item.correctness_definition_hash))
    else:
        for run in runs:
            key = (_run_suite_release_identity(run), run.manifest.task_id)
            contracts[key].add((run.manifest.task_hash, _run_correctness_identity(run)))
    return {key for key, values in contracts.items() if len(values) > 1}


def _compatibility_aggregates(
    inputs: LoadedReportInputs,
    runs: list[ValidatedRun],
) -> list[CompatibilityAggregate]:
    conflicts = _compatibility_conflicts(inputs, runs)
    members: dict[str, list[ValidatedRun]] = defaultdict(list)
    planned_members: dict[str, list[PlanItem]] = defaultdict(list)
    suite_identities: dict[str, str] = {}
    for run in runs:
        partition_id = _run_compatibility_partition_id(run, conflicts)
        suite_identity = _run_suite_release_identity(run)
        suite_identities[partition_id] = suite_identity
        members[partition_id].append(run)

    planned: Counter[str] = Counter()
    if inputs.plan_items:
        for item in inputs.plan_items:
            partition_id = _plan_compatibility_partition_id(item, conflicts)
            suite_identities[partition_id] = _plan_suite_release_identity(item)
            planned_members[partition_id].append(item)
            planned[partition_id] += 1
    else:
        planned.update({key: len(value) for key, value in members.items()})

    aggregates: list[CompatibilityAggregate] = []
    for partition_id in sorted(planned):
        partition_runs = sorted(
            members.get(partition_id, []),
            key=lambda run: (run.plan_index, run.attempt),
        )
        evaluable = [run for run in partition_runs if _is_evaluable(run)]
        resolved = sum(run.scorecard.resolved for run in evaluable)
        if planned_members[partition_id]:
            correctness_contract = [
                {
                    "task_id": item.task_id,
                    "task_hash": item.task_hash,
                    "correctness_definition_hash": item.correctness_definition_hash,
                }
                for item in planned_members[partition_id]
            ]
        else:
            correctness_contract = [
                {
                    "task_id": run.manifest.task_id,
                    "task_hash": run.manifest.task_hash,
                    "correctness_definition_hash": _run_correctness_identity(run),
                }
                for run in partition_runs
            ]
        correctness_identity = content_hash(
            sorted(
                {content_hash(value): value for value in correctness_contract}.values(),
                key=lambda value: (value["task_id"], value["task_hash"]),
            )
        )
        aggregates.append(
            CompatibilityAggregate(
                partition_id=partition_id,
                suite_release_identity=suite_identities[partition_id],
                correctness_definition_hash=correctness_identity,
                planned_count=planned[partition_id],
                valid_count=len(partition_runs),
                evaluable_count=len(evaluable),
                resolved_count=resolved,
                resolved_rate_evaluable=_rate(resolved, len(evaluable)),
                resolved_rate_planned=_rate(resolved, planned[partition_id]),
                correctness_stages=_stage_rates(partition_runs),
                task_coverage_count=len({run.manifest.task_id for run in partition_runs}),
                system_coverage_count=len(
                    {
                        run.plan_item.system.system_id
                        if run.plan_item is not None
                        else _fallback_system(run)
                        for run in partition_runs
                    }
                ),
            )
        )
    return aggregates


def _group_value(run: ValidatedRun, dimension: str) -> str:
    manifest = run.manifest
    plan = run.plan_item
    codex = _run_codex_identity(run)
    values: dict[str, str] = {
        "suite": manifest.suite,
        "release": manifest.release_id or manifest.suite_version,
        "category": plan.category if plan and plan.category else "",
        "difficulty": plan.difficulty if plan and plan.difficulty else "",
        "task": manifest.task_id,
        "system": plan.system.system_id if plan else _fallback_system(run),
        "model": manifest.model.model_id if manifest.model else "",
        "agent": manifest.agent.name,
        "interaction_mode": manifest.interaction_mode,
        "runtime": manifest.runtime.name,
        "profile_id": manifest.requested_toolchain_profile_id or "",
        "profile_hash": manifest.resolved_profile_hash or "",
        "base_seed": str(
            plan.base_seed
            if plan
            else (manifest.base_seed if manifest.base_seed is not None else manifest.seed)
        ),
        "integration_track": codex.get("integration_track", ""),
        "cli_version": codex.get("cli_version", ""),
        "cli_executable_sha256": codex.get("cli_executable_sha256", ""),
        "capability_fingerprint": codex.get("capability_fingerprint", ""),
        "requested_model_id": codex.get("requested_model_id", ""),
        "observed_model_id": codex.get("observed_model_id", ""),
        "identity_confidence": codex.get("identity_confidence", ""),
        "auth_mode_label": codex.get("auth_mode_label", ""),
        "sandbox_policy": codex.get("sandbox_policy", ""),
        "approval_policy": codex.get("approval_policy", ""),
    }
    return values[dimension]


def _plan_group_value(item: PlanItem, dimension: str) -> str:
    codex = _plan_codex_identity(item)
    values: dict[str, str] = {
        "suite": item.suite,
        "release": item.release_id or item.suite_version,
        "category": item.category or "",
        "difficulty": item.difficulty or "",
        "task": item.task_id,
        "system": item.system.system_id,
        "model": item.system.model_descriptor.model_id if item.system.model_descriptor else "",
        "agent": item.system.agent_descriptor.name,
        "interaction_mode": item.interaction_mode.value,
        "runtime": item.runtime_id,
        "profile_id": item.requested_profile_id or "",
        "profile_hash": item.resolved_profile_hash or "",
        "base_seed": str(item.base_seed),
        "integration_track": codex.get("integration_track", ""),
        "cli_version": codex.get("cli_version", ""),
        "cli_executable_sha256": codex.get("cli_executable_sha256", ""),
        "capability_fingerprint": codex.get("capability_fingerprint", ""),
        "requested_model_id": codex.get("requested_model_id", ""),
        "observed_model_id": codex.get("observed_model_id", ""),
        "identity_confidence": codex.get("identity_confidence", ""),
        "auth_mode_label": codex.get("auth_mode_label", ""),
        "sandbox_policy": codex.get("sandbox_policy", ""),
        "approval_policy": codex.get("approval_policy", ""),
    }
    return values[dimension]


def _compatibility_partitions(runs: list[ValidatedRun]) -> dict[str, list[str]]:
    values = {
        "suite_release": sorted({_run_suite_release_identity(run) for run in runs}),
        "correctness_definition": sorted({_run_correctness_identity(run) for run in runs}),
        "resolved_profile": sorted(
            {
                run.manifest.resolved_profile_hash
                for run in runs
                if run.manifest.resolved_profile_hash
            }
        ),
    }
    return values


def _compatibility_warnings(
    inputs: LoadedReportInputs,
    runs: list[ValidatedRun],
) -> list[str]:
    partitions = _compatibility_partitions(runs)
    warnings: list[str] = []
    if len(partitions["suite_release"]) > 1:
        warnings.append("Multiple suite release/source identities are reported as partitions.")
    task_correctness: dict[str, set[str]] = defaultdict(set)
    if inputs.plan_items:
        for item in inputs.plan_items:
            task_correctness[item.task_id].add(item.correctness_definition_hash)
    else:
        for run in runs:
            task_correctness[run.manifest.task_id].add(_run_correctness_identity(run))
    if any(len(values) > 1 for values in task_correctness.values()):
        warnings.append("Multiple correctness definitions are reported as partitions.")
    if len(partitions["resolved_profile"]) > 1:
        warnings.append("Multiple area profiles are partitioned and are never ranked together.")
    codex_partitions = _codex_cli_partitions(runs)
    tracks = {item["integration_track"] for item in codex_partitions}
    identities = {
        (
            item["requested_model_id"],
            item["observed_model_id"],
            item["cli_version"],
            item["cli_executable_sha256"],
            item["capability_fingerprint"],
        )
        for item in codex_partitions
    }
    if len(tracks) > 1:
        warnings.append(
            "Codex CLI model-proxy and external-agent tracks are distinct systems, not pooled."
        )
    if len(identities) > 1:
        warnings.append(
            "Codex model identities, executable versions/hashes, or capability fingerprints "
            "differ and are not comparable without an explicit partition."
        )
    if any(
        item["observed_model_id"] and item["observed_model_id"] != item["requested_model_id"]
        for item in codex_partitions
    ):
        warnings.append(
            "At least one observed Codex model identity differs from the requested identity."
        )
    if any(
        item["identity_confidence"] in {"requested_only", "unknown"} for item in codex_partitions
    ):
        warnings.append(
            "At least one Codex run has no provider-observed model identity; "
            "requested identity is not treated as observed."
        )
    return warnings


def _input_set_hash(inputs: LoadedReportInputs, runs: list[ValidatedRun]) -> str:
    return content_hash(
        {
            "experiment_id": inputs.experiment_id,
            "plan_hash": inputs.plan_hash,
            "runs": [
                {
                    "plan_index": run.plan_index,
                    "attempt": run.attempt,
                    "run_id": run.manifest.run_id,
                    "candidate_hash": run.manifest.candidate_hash,
                    "run_config_hash": run.manifest.run_config_hash,
                }
                for run in runs
            ],
            "invalid_inputs": inputs.invalid_inputs,
        }
    )


def _latest_index_records(inputs: LoadedReportInputs) -> dict[int, Any]:
    return {
        record.plan_index: record
        for record in sorted(
            inputs.index_records,
            key=lambda item: (item.plan_index, item.attempt),
        )
    }


def _fallback_system(run: ValidatedRun) -> str:
    model = run.manifest.model.model_id if run.manifest.model else "model-free"
    return f"{run.manifest.agent.name}:{model}"


def _run_codex_identity(run: ValidatedRun) -> dict[str, str]:
    manifest = run.manifest
    if manifest.external_agent_observations:
        identity = manifest.external_agent_observations[-1]
        return {
            "integration_track": identity.integration_track or "codex_cli_external_agent",
            "cli_version": identity.executable_version,
            "cli_executable_sha256": identity.executable_sha256,
            "capability_fingerprint": identity.capability_fingerprint,
            "requested_model_id": identity.requested_model_id or "",
            "observed_model_id": identity.observed_model_id or "",
            "identity_confidence": identity.identity_confidence,
            "auth_mode_label": identity.auth_mode_label or "",
            "sandbox_policy": identity.sandbox_policy or "",
            "approval_policy": identity.approval_policy or "",
        }
    if (
        manifest.model is not None
        and manifest.model.configuration.get("integration_track") == "codex_cli_model_proxy"
    ):
        configuration = manifest.model.configuration
        observation = manifest.model_observations[-1] if manifest.model_observations else None
        return {
            "integration_track": "codex_cli_model_proxy",
            "cli_version": str(configuration.get("cli_version") or ""),
            "cli_executable_sha256": str(configuration.get("cli_executable_sha256") or ""),
            "capability_fingerprint": str(configuration.get("capability_fingerprint") or ""),
            "requested_model_id": manifest.model.model_id,
            "observed_model_id": (
                observation.observed_provider_model_id if observation is not None else ""
            )
            or "",
            "identity_confidence": (
                observation.identity_confidence if observation is not None else "unknown"
            ),
            "auth_mode_label": str(configuration.get("auth_mode_label") or ""),
            "sandbox_policy": str(configuration.get("sandbox_policy") or ""),
            "approval_policy": str(configuration.get("approval_policy") or ""),
        }
    return {}


def _plan_codex_identity(item: PlanItem) -> dict[str, str]:
    descriptor = item.system.model_descriptor
    if (
        descriptor is not None
        and descriptor.configuration.get("integration_track") == "codex_cli_model_proxy"
    ):
        return {
            "integration_track": "codex_cli_model_proxy",
            "cli_version": str(descriptor.configuration.get("cli_version") or ""),
            "cli_executable_sha256": str(
                descriptor.configuration.get("cli_executable_sha256") or ""
            ),
            "capability_fingerprint": str(
                descriptor.configuration.get("capability_fingerprint") or ""
            ),
            "requested_model_id": descriptor.model_id,
            "observed_model_id": "",
            "identity_confidence": "unknown",
            "auth_mode_label": str(descriptor.configuration.get("auth_mode_label") or ""),
            "sandbox_policy": str(descriptor.configuration.get("sandbox_policy") or ""),
            "approval_policy": str(descriptor.configuration.get("approval_policy") or ""),
        }
    if "external_coding_agent" in item.system.agent_descriptor.capabilities:
        requested = item.system.agent_options.get("model_id")
        return {
            "integration_track": "codex_cli_external_agent",
            "cli_version": "",
            "cli_executable_sha256": "",
            "capability_fingerprint": "",
            "requested_model_id": requested if isinstance(requested, str) else "",
            "observed_model_id": "",
            "identity_confidence": "unknown",
            "auth_mode_label": "",
            "sandbox_policy": str(item.system.agent_options.get("sandbox") or ""),
            "approval_policy": str(item.system.agent_options.get("approval_policy") or ""),
        }
    return {}


def _codex_cli_partitions(runs: list[ValidatedRun]) -> list[dict[str, str]]:
    unique = {
        (
            identity.get("integration_track", ""),
            identity.get("cli_version", ""),
            identity.get("cli_executable_sha256", ""),
            identity.get("capability_fingerprint", ""),
            identity.get("requested_model_id", ""),
            identity.get("observed_model_id", ""),
            identity.get("identity_confidence", ""),
            identity.get("auth_mode_label", ""),
            identity.get("sandbox_policy", ""),
            identity.get("approval_policy", ""),
        )
        for run in runs
        if (identity := _run_codex_identity(run))
    }
    return [
        {
            "integration_track": track,
            "cli_version": version,
            "cli_executable_sha256": executable_sha256,
            "capability_fingerprint": fingerprint,
            "requested_model_id": requested_model,
            "observed_model_id": observed_model,
            "identity_confidence": confidence,
            "auth_mode_label": auth_mode,
            "sandbox_policy": sandbox,
            "approval_policy": approval,
        }
        for (
            track,
            version,
            executable_sha256,
            fingerprint,
            requested_model,
            observed_model,
            confidence,
            auth_mode,
            sandbox,
            approval,
        ) in sorted(unique)
    ]


__all__ = ["ReportBuilder"]
