"""Offline campaign validation, aggregation, and atomic report generation."""

from __future__ import annotations

import json
import os
import stat
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.campaign.config import load_campaign_config
from verigym.campaign.render import render_campaign_csv, render_campaign_markdown
from verigym.campaign.schemas import (
    QUALITY_COMPARISON_POLICY,
    CampaignConfig,
    CampaignEvaluationSummary,
    CampaignInputConfig,
    CampaignModeCoverage,
    CampaignQualityPartition,
    CampaignReport,
)
from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.comparison import validate_evolving_evaluation
from verigym.experiments.schemas import ExperimentManifest, PlanItem
from verigym.experiments.state import atomic_write_text, load_json_model, load_jsonl_models
from verigym.provenance import get_build_provenance
from verigym.reporting.aggregate import ReportBuilder
from verigym.reporting.schemas import (
    AggregateReport,
    ExplicitRate,
    QualityPartition,
    QualityRunValue,
)
from verigym.schemas.evolution import EvolvingEvaluationReport, VersionMetricSummary


@dataclass(frozen=True)
class GeneratedCampaignReports:
    report: CampaignReport
    json_path: Path
    csv_path: Path
    markdown_path: Path
    hashes: dict[str, str]


@dataclass(frozen=True)
class _LoadedExperiment:
    root: Path
    manifest: ExperimentManifest
    plan_items: list[PlanItem]
    aggregate: AggregateReport


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"campaign path traverses a symlink: {current}")


def _existing_path(base_dir: Path, configured: Path, *, directory: bool) -> Path:
    candidate = configured.expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    _reject_symlink_components(candidate)
    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise ValueError(f"campaign input is unavailable: {configured.as_posix()}") from exc
    expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not expected:
        kind = "directory" if directory else "regular file"
        raise ValueError(f"campaign input must be a real {kind}: {configured.as_posix()}")
    return candidate.resolve(strict=True)


def _output_directory(base_dir: Path, configured: Path) -> Path:
    destination = configured.expanduser()
    if not destination.is_absolute():
        destination = base_dir / destination
    _reject_symlink_components(destination)
    destination.mkdir(parents=True, exist_ok=True)
    metadata = os.lstat(destination)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("campaign output must be a real directory")
    return destination.resolve(strict=True)


def _load_experiment(root: Path) -> _LoadedExperiment:
    manifest = load_json_model(root / "experiment_manifest.json", ExperimentManifest)
    plan_items = load_jsonl_models(root / "plan.jsonl", PlanItem)
    aggregate = ReportBuilder().build(
        root,
        group_by=("system", "interaction_mode", "task"),
    )
    if aggregate.source_kind != "experiment":
        raise ValueError("campaign inputs must be immutable experiment roots")
    if aggregate.experiment_id != manifest.experiment_id:
        raise ValueError("campaign aggregate and experiment identity differ")
    if (
        aggregate.plan_hash != manifest.plan_hash
        or aggregate.task_set_hash != manifest.task_set_hash
    ):
        raise ValueError("campaign aggregate and frozen experiment plan differ")
    if len(plan_items) != manifest.planned_item_count:
        raise ValueError("campaign plan item count differs from its manifest")
    return _LoadedExperiment(
        root=root,
        manifest=manifest,
        plan_items=plan_items,
        aggregate=aggregate,
    )


def _mean(aggregate: AggregateReport, *names: str) -> float | None:
    for name in names:
        summary = aggregate.efficiency_resolved.get(name)
        if summary is not None and summary.known_value_count:
            return summary.mean
    return None


def _pass_at_1(aggregate: AggregateReport) -> float | None:
    return next((item.macro_mean for item in aggregate.sampling.macro if item.k == 1), None)


def _cost(aggregate: AggregateReport) -> tuple[float | None, str | None]:
    accounting = aggregate.cost_accounting
    if (
        accounting is None
        or accounting.unknown_unit_count
        or accounting.incompatible_unit_count
        or len(accounting.partitions) != 1
    ):
        return None, None
    partition = accounting.partitions[0]
    return partition.sum, f"{partition.dimension}:{partition.identifier}"


def _license_count(aggregate: AggregateReport) -> int:
    return sum(
        count
        for category, count in aggregate.failure_taxonomy.verifier_tool.items()
        if "license" in category.lower()
    )


def _observed_model_calls(aggregate: AggregateReport) -> int | None:
    accounting = aggregate.metadata.get("model_process_accounting")
    if not isinstance(accounting, dict):
        return None
    value = accounting.get("observed_model_api_calls")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _ordinary_summary(
    entry: CampaignInputConfig,
    loaded: _LoadedExperiment,
) -> CampaignEvaluationSummary:
    manifest = loaded.manifest
    aggregate = loaded.aggregate
    if manifest.sampling_policy.mode.value != entry.evaluation_mode:
        raise ValueError(
            f"campaign input {entry.id!r} declares {entry.evaluation_mode!r} but its plan uses "
            f"{manifest.sampling_policy.mode.value!r}"
        )
    if len(manifest.system_identities) != 1:
        raise ValueError(
            f"ordinary campaign input {entry.id!r} must contain exactly one frozen system"
        )
    system = manifest.system_identities[0]
    cost_sum, cost_unit = _cost(aggregate)
    return CampaignEvaluationSummary(
        input_id=entry.id,
        evaluation_mode=entry.evaluation_mode,
        source_kind=entry.kind,
        source_report_hash=aggregate.input_set_hash,
        suite_id=manifest.suite_id,
        experiment_id=manifest.experiment_id,
        plan_hash=manifest.plan_hash,
        task_set_hash=manifest.task_set_hash,
        system_id=system.system_id,
        agent_id=system.agent_id,
        model_id=system.model_id,
        compatibility_partition_ids=sorted(
            item.partition_id for item in aggregate.compatibility_aggregates
        ),
        planned_count=aggregate.coverage.planned_plan_items,
        terminal_count=aggregate.coverage.terminal_child_runs,
        evaluable_count=aggregate.coverage.evaluable_candidate_runs,
        resolved_count=aggregate.coverage.resolved_runs,
        infrastructure_failure_count=aggregate.coverage.infrastructure_error_runs,
        resolved_rate_evaluable=aggregate.resolved_rate_evaluable,
        macro_pass_at_1=_pass_at_1(aggregate),
        mean_total_tokens=_mean(aggregate, "external_total_tokens", "total_tokens"),
        mean_tool_calls=_mean(aggregate, "external_tool_call_count", "tool_calls"),
        mean_wall_time_s=_mean(aggregate, "wall_time_s"),
        observed_model_api_calls=_observed_model_calls(aggregate),
        model_cost_sum=cost_sum,
        model_cost_unit=cost_unit,
        license_unavailable_count=_license_count(aggregate),
    )


_VERSION_OPTION_KEYS = {"agent_version_id", "agent_version_hash", "memory_pack"}


def _version_id(item: PlanItem) -> str:
    value = item.system.agent_options.get("agent_version_id")
    if not isinstance(value, str) or not value:
        raise ValueError("evolving campaign plan item lacks agent_version_id")
    return value


def _plan_comparison_key(item: PlanItem) -> tuple[str, int, int]:
    return item.task_id, item.base_seed, item.sample_index


def _plan_comparison_signature(item: PlanItem) -> dict[str, Any]:
    stable_agent_options = {
        key: value
        for key, value in item.system.agent_options.items()
        if key not in _VERSION_OPTION_KEYS
    }
    return {
        "task_id": item.task_id,
        "task_hash": item.task_hash,
        "source_hash": item.source_hash,
        "source_identity_hash": item.source_identity_hash,
        "suite": item.suite,
        "suite_version": item.suite_version,
        "release_id": item.release_id,
        "interaction_mode": item.interaction_mode,
        "agent_id": item.system.agent_id,
        "agent_descriptor": item.system.agent_descriptor,
        "stable_agent_options": stable_agent_options,
        "agent_requires_model": item.system.agent_requires_model,
        "model_id": item.system.model_id,
        "model_descriptor": item.system.model_descriptor,
        "model_configuration_hash": item.system.model_configuration_hash,
        "model_options": item.system.model_options,
        "prompt_policy_hash": item.prompt_policy_hash,
        "action_protocol": item.action_protocol,
        "tool_policy_hash": item.tool_policy_hash,
        "runtime_id": item.runtime_id,
        "runtime_identity_hash": item.runtime_identity_hash,
        "verifier_hash": item.verifier_hash,
        "correctness_definition_hash": item.correctness_definition_hash,
        "budget": item.budget,
        "generation": item.generation,
        "max_invalid_actions": item.max_invalid_actions,
        "toolchain_profiles": item.toolchain_profiles,
        "requested_profile_id": item.requested_profile_id,
        "declared_profile_hash": item.declared_profile_hash,
        "resolved_profile_hash": item.resolved_profile_hash,
        "reference_candidate_hash": item.reference_candidate_hash,
    }


def validate_evolving_plan_contract(
    plan_items: list[PlanItem],
    version_ids: set[str],
) -> dict[str, list[PlanItem]]:
    """Require paired versions to differ only through explicit version-memory options."""

    by_version: dict[str, list[PlanItem]] = {}
    for item in plan_items:
        if item.interaction_mode.value != "agent":
            raise ValueError("evolving campaign inputs require agent-mode plan items")
        by_version.setdefault(_version_id(item), []).append(item)
    if set(by_version) != version_ids:
        raise ValueError("evolving report versions differ from the frozen experiment plan")
    signatures: dict[str, dict[tuple[str, int, int], dict[str, Any]]] = {}
    for version_id, items in by_version.items():
        systems = {item.system.system_id for item in items}
        if len(systems) != 1:
            raise ValueError(f"agent version {version_id!r} must map to exactly one system")
        mapped = {_plan_comparison_key(item): _plan_comparison_signature(item) for item in items}
        if len(mapped) != len(items):
            raise ValueError(f"agent version {version_id!r} repeats a task/sample identity")
        signatures[version_id] = mapped
    ordered = sorted(version_ids)
    baseline = signatures[ordered[0]]
    for version_id in ordered[1:]:
        if signatures[version_id] != baseline:
            raise ValueError(
                "evolving v0/v1 must keep task, model, runtime, tools, verifier, and profile "
                "identical"
            )
    return {
        key: sorted(value, key=lambda item: item.plan_index) for key, value in by_version.items()
    }


def _validate_evolving_report_contract(
    loaded: _LoadedExperiment,
    report: EvolvingEvaluationReport,
    by_version: dict[str, list[PlanItem]],
) -> None:
    """Bind report coverage and correctness counts to the immutable experiment artifacts."""

    version_ids = set(by_version)
    paired_versions = {
        report.paired_difference.baseline_version_id,
        report.paired_difference.evolved_version_id,
    }
    if paired_versions != version_ids:
        raise ValueError("evolving paired comparison versions differ from the frozen plan")

    plan_pairs = {
        (item.task_id, version_id) for version_id, items in by_version.items() for item in items
    }
    task_metric_by_pair = {
        (metric.task_id, metric.agent_version_id): metric for metric in report.task_version_metrics
    }
    if set(task_metric_by_pair) != plan_pairs:
        raise ValueError("evolving task/version coverage differs from the frozen plan")
    plan_tasks = {task_id for task_id, _version_id_value in plan_pairs}
    if report.heldout_task_count != len(plan_tasks):
        raise ValueError("evolving held-out task count differs from the frozen plan")

    version_metric_by_id = {metric.agent_version_id: metric for metric in report.version_metrics}
    for version_id, items in by_version.items():
        system_id = items[0].system.system_id
        planned_by_task: dict[str, int] = {}
        for item in items:
            planned_by_task[item.task_id] = planned_by_task.get(item.task_id, 0) + 1
        if set(planned_by_task.values()) != {report.samples_per_task_version}:
            raise ValueError("evolving sample count differs from the frozen plan")

        groups = [
            group
            for group in loaded.aggregate.grouped_aggregates
            if group.dimensions.get("system") == system_id
        ]
        actual_by_task = {
            task_id: (
                sum(
                    group.planned_count
                    for group in groups
                    if group.dimensions.get("task") == task_id
                ),
                sum(
                    group.evaluable_count
                    for group in groups
                    if group.dimensions.get("task") == task_id
                ),
                sum(
                    group.resolved_count
                    for group in groups
                    if group.dimensions.get("task") == task_id
                ),
            )
            for task_id in planned_by_task
        }
        for task_id, counts in actual_by_task.items():
            task_metric = task_metric_by_pair[(task_id, version_id)]
            reported = (task_metric.planned, task_metric.evaluable, task_metric.resolved)
            if reported != counts:
                raise ValueError(
                    "evolving task metrics differ from the immutable experiment aggregate"
                )

        version_metric = version_metric_by_id[version_id]
        version_counts = (
            version_metric.planned,
            version_metric.evaluable,
            version_metric.resolved,
        )
        aggregate_counts = tuple(
            sum(values[index] for values in actual_by_task.values()) for index in range(3)
        )
        if version_counts != aggregate_counts:
            raise ValueError(
                "evolving version metrics differ from the immutable experiment aggregate"
            )

        task_metrics = [
            task_metric_by_pair[(task_id, version_id)] for task_id in sorted(planned_by_task)
        ]
        internally_summed = (
            sum(metric.planned for metric in task_metrics),
            sum(metric.terminal for metric in task_metrics),
            sum(metric.evaluable for metric in task_metrics),
            sum(metric.resolved for metric in task_metrics),
            sum(metric.contained_policy_failures for metric in task_metrics),
            sum(metric.infrastructure_failures for metric in task_metrics),
        )
        version_totals = (
            version_metric.planned,
            version_metric.terminal,
            version_metric.evaluable,
            version_metric.resolved,
            version_metric.contained_policy_failures,
            version_metric.infrastructure_failures,
        )
        if internally_summed != version_totals:
            raise ValueError("evolving task metrics do not sum to their version summary")


def _rate(numerator: int, denominator: int) -> ExplicitRate:
    return ExplicitRate(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
        unavailable_reason=None if denominator else "no_evaluable_runs",
    )


def _evolving_summary(
    entry: CampaignInputConfig,
    loaded: _LoadedExperiment,
    metric: VersionMetricSummary,
    items: list[PlanItem],
    source_report_hash: str,
) -> CampaignEvaluationSummary:
    first = items[0]
    system_id = first.system.system_id
    compatibility = sorted(
        {
            group.compatibility_partition_id
            for group in loaded.aggregate.grouped_aggregates
            if group.dimensions.get("system") == system_id
        }
    )
    return CampaignEvaluationSummary(
        input_id=entry.id,
        evaluation_mode="evolving_agent",
        source_kind=entry.kind,
        source_report_hash=source_report_hash,
        suite_id=loaded.manifest.suite_id,
        experiment_id=loaded.manifest.experiment_id,
        plan_hash=loaded.manifest.plan_hash,
        task_set_hash=loaded.manifest.task_set_hash,
        system_id=system_id,
        agent_id=first.system.agent_id,
        model_id=first.system.model_id,
        agent_version_id=metric.agent_version_id,
        compatibility_partition_ids=compatibility,
        planned_count=metric.planned,
        terminal_count=metric.terminal,
        evaluable_count=metric.evaluable,
        resolved_count=metric.resolved,
        infrastructure_failure_count=metric.infrastructure_failures,
        resolved_rate_evaluable=_rate(metric.resolved, metric.evaluable),
        macro_pass_at_1=metric.macro_pass_at_1,
        mean_total_tokens=metric.mean_tokens,
        mean_tool_calls=metric.mean_public_tool_calls,
        mean_wall_time_s=metric.mean_wall_time_s,
        observed_model_api_calls=None,
        model_cost_sum=None,
        model_cost_unit=None,
        license_unavailable_count=None,
    )


def _partition_identity(partition: QualityPartition) -> dict[str, Any]:
    return {
        "suite_source_identity": partition.suite_source_identity,
        "task_id": partition.task_id,
        "task_hash": partition.task_hash,
        "correctness_definition_hash": partition.correctness_definition_hash,
        "declared_profile_id": partition.declared_profile_id,
        "declared_profile_hash": partition.declared_profile_hash,
        "resolved_profile_hash": partition.resolved_profile_hash,
        "runtime_identity_hash": partition.runtime_identity_hash,
        "image_id": partition.image_id,
        "area_unit": partition.area_unit,
        "metric_scope": partition.metric_scope,
        "timing_unit": partition.timing_unit,
        "clock_period": partition.clock_period,
        "reference_candidate_hash": partition.reference_candidate_hash,
    }


def _median(values: list[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return statistics.median(known) if known else None


def _quality_row(
    entry: CampaignInputConfig,
    partition: QualityPartition,
    runs: list[QualityRunValue],
    *,
    version_id: str | None,
) -> CampaignQualityPartition:
    if content_hash(_partition_identity(partition)) != partition.partition_id:
        raise ValueError("quality partition identity does not match its content hash")
    return CampaignQualityPartition(
        input_id=entry.id,
        evaluation_mode=entry.evaluation_mode,
        agent_version_id=version_id,
        comparison_partition_id=partition.partition_id,
        suite_source_identity=partition.suite_source_identity,
        task_id=partition.task_id,
        task_hash=partition.task_hash,
        correctness_definition_hash=partition.correctness_definition_hash,
        declared_profile_id=partition.declared_profile_id,
        declared_profile_hash=partition.declared_profile_hash,
        resolved_profile_hash=partition.resolved_profile_hash,
        runtime_identity_hash=partition.runtime_identity_hash,
        image_id=partition.image_id,
        metric_scope=partition.metric_scope,
        area_unit=partition.area_unit,
        timing_unit=partition.timing_unit,
        clock_period=partition.clock_period,
        reference_candidate_hash=partition.reference_candidate_hash,
        eligible_run_count=sum(item.eligible for item in runs),
        ineligible_run_count=sum(not item.eligible for item in runs),
        area_ratio_median=_median([item.area_ratio for item in runs]),
        delay_ratio_median=_median([item.delay_ratio for item in runs]),
        worst_negative_slack_delta_median=_median(
            [item.worst_negative_slack_delta for item in runs]
        ),
    )


def validate_quality_comparison_partitions(
    rows: list[CampaignQualityPartition],
) -> list[CampaignQualityPartition]:
    """Reject any attempt to reuse one comparison ID for a different exact contract."""

    identities: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.model_dump(
            mode="json",
            include={
                "suite_source_identity",
                "task_id",
                "task_hash",
                "correctness_definition_hash",
                "declared_profile_id",
                "declared_profile_hash",
                "resolved_profile_hash",
                "runtime_identity_hash",
                "image_id",
                "metric_scope",
                "area_unit",
                "timing_unit",
                "clock_period",
                "reference_candidate_hash",
            },
        )
        incumbent = identities.setdefault(row.comparison_partition_id, identity)
        if incumbent != identity:
            raise ValueError("one quality comparison partition ID maps to different contracts")
    return rows


def validate_campaign_report(report: CampaignReport) -> CampaignReport:
    payload = report.model_dump(mode="json")
    expected = payload.pop("report_hash")
    if content_hash(payload) != expected:
        raise ValueError("campaign report identity changed")
    validate_quality_comparison_partitions(report.quality_partitions)
    return report


class CampaignService:
    """Build and write a path-free summary from already frozen local artifacts."""

    def build_from_path(self, config_path: Path) -> CampaignReport:
        configured = config_path.expanduser()
        _reject_symlink_components(configured)
        config = load_campaign_config(configured)
        config_file = configured.resolve(strict=True)
        return self.build(config, base_dir=config_file.parent)

    def build(self, config: CampaignConfig, *, base_dir: Path) -> CampaignReport:
        semantic_config = {
            "schema_version": config.schema_version,
            "name": config.name,
            "description": config.description,
            "inputs": [
                {
                    "id": entry.id,
                    "kind": entry.kind,
                    "evaluation_mode": entry.evaluation_mode,
                }
                for entry in config.inputs
            ],
        }
        config_hash = content_hash(semantic_config)
        evaluations: list[CampaignEvaluationSummary] = []
        quality: list[CampaignQualityPartition] = []
        input_identities: list[dict[str, str]] = []
        warnings: list[str] = []
        for entry in config.inputs:
            root = _existing_path(base_dir, entry.experiment_root, directory=True)
            loaded = _load_experiment(root)
            if entry.kind == "experiment":
                evaluations.append(_ordinary_summary(entry, loaded))
                quality.extend(
                    _quality_row(entry, partition, partition.runs, version_id=None)
                    for partition in loaded.aggregate.quality_partitions
                )
                source_hash = loaded.aggregate.input_set_hash
            else:
                assert entry.evolving_report is not None
                report_path = _existing_path(base_dir, entry.evolving_report, directory=False)
                evolution = validate_evolving_evaluation(
                    load_json_model(report_path, EvolvingEvaluationReport)
                )
                if evolution.heldout_plan_hash != loaded.manifest.plan_hash:
                    raise ValueError("evolving report does not bind the campaign experiment plan")
                version_ids = {item.agent_version_id for item in evolution.version_metrics}
                by_version = validate_evolving_plan_contract(loaded.plan_items, version_ids)
                _validate_evolving_report_contract(loaded, evolution, by_version)
                source_hash = content_hash(
                    {
                        "experiment_input_set_hash": loaded.aggregate.input_set_hash,
                        "evolving_report_hash": evolution.report_hash,
                    }
                )
                for metric in evolution.version_metrics:
                    evaluations.append(
                        _evolving_summary(
                            entry,
                            loaded,
                            metric,
                            by_version[metric.agent_version_id],
                            source_hash,
                        )
                    )
                version_by_plan = {
                    item.plan_index: version_id
                    for version_id, items in by_version.items()
                    for item in items
                }
                for partition in loaded.aggregate.quality_partitions:
                    for version_id in sorted(version_ids):
                        runs = [
                            run
                            for run in partition.runs
                            if version_by_plan.get(run.plan_index) == version_id
                        ]
                        if runs:
                            quality.append(
                                _quality_row(entry, partition, runs, version_id=version_id)
                            )
                warnings.append(f"{entry.id}: {evolution.required_interpretation}")
            input_identities.append(
                {
                    "input_id": entry.id,
                    "evaluation_mode": entry.evaluation_mode,
                    "source_hash": source_hash,
                }
            )
            warnings.extend(f"{entry.id}: {item}" for item in loaded.aggregate.warnings)
        coverage = CampaignModeCoverage(
            chat_inputs=sum(item.evaluation_mode == "chat" for item in config.inputs),
            agent_inputs=sum(item.evaluation_mode == "agent" for item in config.inputs),
            evolving_agent_inputs=sum(
                item.evaluation_mode == "evolving_agent" for item in config.inputs
            ),
            complete_platform_matrix=all(
                any(item.evaluation_mode == mode for item in config.inputs)
                for mode in ("chat", "agent", "evolving_agent")
            ),
        )
        if not coverage.complete_platform_matrix:
            warnings.append("campaign does not cover all chat, agent, and evolving_agent modes")
        quality = validate_quality_comparison_partitions(
            sorted(
                quality,
                key=lambda item: (
                    item.comparison_partition_id,
                    item.input_id,
                    item.agent_version_id or "",
                ),
            )
        )
        if len({item.comparison_partition_id for item in quality}) > 1:
            warnings.append("PPA rows span exact compatibility partitions and are not ranked")
        base = {
            "schema_version": "1.0",
            "campaign_id": f"campaign-{config_hash[:16]}",
            "campaign_name": config.name,
            "campaign_config_hash": config_hash,
            "input_set_hash": content_hash(input_identities),
            "build_provenance": get_build_provenance().model_dump(mode="json"),
            "mode_coverage": coverage.model_dump(mode="json"),
            "evaluations": [
                item.model_dump(mode="json")
                for item in sorted(
                    evaluations,
                    key=lambda item: (
                        item.evaluation_mode,
                        item.input_id,
                        item.agent_version_id or "",
                    ),
                )
            ],
            "quality_partitions": [item.model_dump(mode="json") for item in quality],
            "quality_comparison_policy": QUALITY_COMPARISON_POLICY,
            "offline_only": True,
            "model_calls_during_reporting": 0,
            "tool_calls_during_reporting": 0,
            "warnings": sorted(set(warnings)),
        }
        report = CampaignReport.model_validate({**base, "report_hash": content_hash(base)})
        return validate_campaign_report(report)

    def generate_from_path(
        self,
        config_path: Path,
        *,
        output_dir: Path | None = None,
    ) -> GeneratedCampaignReports:
        configured = config_path.expanduser()
        _reject_symlink_components(configured)
        config = load_campaign_config(configured)
        config_file = configured.resolve(strict=True)
        report = self.build(config, base_dir=config_file.parent)
        destination = _output_directory(
            config_file.parent,
            output_dir if output_dir is not None else config.output.root,
        )
        json_path = destination / "campaign_report.json"
        csv_path = destination / "campaign_report.csv"
        markdown_path = destination / "campaign_report.md"
        payloads = {
            json_path: json.dumps(
                report.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            csv_path: render_campaign_csv(report),
            markdown_path: render_campaign_markdown(report),
        }
        for path, text in payloads.items():
            if path.is_symlink():
                raise ValueError("campaign output files cannot be symlinks")
            atomic_write_text(path, text)
        return GeneratedCampaignReports(
            report=report,
            json_path=json_path,
            csv_path=csv_path,
            markdown_path=markdown_path,
            hashes={path.name: hash_bytes(path.read_bytes()) for path in payloads},
        )


__all__ = [
    "CampaignService",
    "GeneratedCampaignReports",
    "validate_campaign_report",
    "validate_evolving_plan_contract",
    "validate_quality_comparison_partitions",
]
