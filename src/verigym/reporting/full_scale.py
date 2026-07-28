"""Deterministic full-scale experiment analysis built from canonical reports."""

from __future__ import annotations

import csv
import io
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import hash_bytes
from verigym.core.integrity import write_experiment_artifact_manifest
from verigym.core.sampling import classify_sample_outcome
from verigym.experiments.state import atomic_write_text
from verigym.reporting.aggregate import ReportBuilder
from verigym.reporting.loader import LoadedReportInputs, ValidatedRun, load_report_inputs

_BOOTSTRAP_SEED = 548_219_773
_BOOTSTRAP_RESAMPLES = 10_000


@dataclass(frozen=True)
class GeneratedFullScaleReports:
    output_dir: Path
    paths: dict[str, Path]
    hashes: dict[str, str]


class FullScaleReportService:
    """Produce offline task-level metrics and paired bootstrap intervals."""

    def __init__(self, builder: ReportBuilder | None = None) -> None:
        self.builder = builder or ReportBuilder()

    def generate(
        self,
        root: Path,
        *,
        output_dir: Path | None = None,
        bootstrap_resamples: int = _BOOTSTRAP_RESAMPLES,
        bootstrap_seed: int = _BOOTSTRAP_SEED,
    ) -> GeneratedFullScaleReports:
        if bootstrap_resamples < 1:
            raise ValueError("bootstrap_resamples must be positive")
        inputs = load_report_inputs(root)
        aggregate = self.builder.build_inputs(inputs, group_by=("system", "task"))
        destination = output_dir or inputs.root / "reports" / "full-scale"
        destination.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("full-scale report destination must be a real directory")

        task_rows, metric_vectors = _task_system_rows(aggregate)
        efficiency = _efficiency(inputs)
        failure = _failure_taxonomy(inputs)
        policy = _policy_compatibility(inputs)
        statistics_payload = _statistics(
            metric_vectors,
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        coverage = {
            "planned_plan_items": inputs.planned_count,
            "valid_terminal_artifacts": len(inputs.valid_runs),
            "invalid_input_count": len(inputs.invalid_inputs),
            "planned_task_count": len({item.task_id for item in inputs.plan_items}),
            "planned_system_count": len({item.system.system_id for item in inputs.plan_items}),
            "canonical_task_system_group_count": len(task_rows),
            "canonical_valid_task_system_group_count": sum(
                bool(row["canonical_valid"]) for row in task_rows
            ),
        }
        payload = {
            "schema_version": "1.0",
            "analysis_kind": "full_scale_agent_evaluation",
            "experiment_id": inputs.experiment_id,
            "config_hash": inputs.config_hash,
            "plan_hash": inputs.plan_hash,
            "task_set_hash": inputs.task_set_hash,
            "coverage": coverage,
            "pass_at_k": task_rows,
            "failure_taxonomy": failure,
            "policy_compatibility": policy,
            "efficiency": efficiency,
            "statistical_analysis": statistics_payload,
            "claims": {
                "direct_api_evaluation": False,
                "official_upstream_model_score": False,
                "best_of_n_selection": False,
            },
        }
        grouped = {
            "schema_version": "1.0",
            "dimensions": ["system", "task"],
            "groups": [group.model_dump(mode="json") for group in aggregate.grouped_aggregates],
        }
        payloads = {
            "full-scale.json": _json_text(payload),
            "per-task-system.csv": _render_task_csv(task_rows),
            "failure-taxonomy.json": _json_text(failure),
            "policy-compatibility.json": _json_text(policy),
            "efficiency.json": _json_text(efficiency),
            "statistical-analysis.json": _json_text(statistics_payload),
            "grouped-aggregates.json": _json_text(grouped),
            "report.md": _render_markdown(payload),
        }
        paths: dict[str, Path] = {}
        for name, text in payloads.items():
            path = destination / name
            atomic_write_text(path, text)
            paths[name] = path
        if destination == inputs.root / "reports" / "full-scale":
            write_experiment_artifact_manifest(inputs.root, inputs.experiment_id)
        return GeneratedFullScaleReports(
            output_dir=destination,
            paths=paths,
            hashes={name: hash_bytes(path.read_bytes()) for name, path in paths.items()},
        )


def _task_system_rows(
    aggregate: Any,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[float]]]]:
    rows: list[dict[str, Any]] = []
    vectors: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for group in aggregate.sampling.groups:
        values = {entry.k: entry.value for entry in group.entries}
        row = {
            "task_id": group.task_id,
            "system_id": group.system_id,
            "base_seed": group.base_seed,
            "expected_n": group.expected_n,
            "observed_n": group.observed_n,
            "resolved_c": group.resolved_c,
            "evaluable_count": group.evaluable_count,
            "infrastructure_error_count": group.infrastructure_error_count,
            "cancelled_count": group.cancelled_count,
            "missing_count": group.missing_count,
            "canonical_valid": group.canonical_valid,
            "invalid_reason": group.invalid_reason,
            "pass_at_1": values.get(1),
            "pass_at_2": values.get(2),
            "pass_at_3": values.get(3),
            "task_success_at_3": (1.0 if group.resolved_c > 0 else 0.0)
            if group.canonical_valid
            else None,
        }
        rows.append(row)
        if group.canonical_valid:
            for name in ("pass_at_1", "pass_at_2", "pass_at_3", "task_success_at_3"):
                value = row[name]
                if value is not None:
                    vectors[group.system_id][name].append(float(value))
    rows.sort(key=lambda row: (str(row["task_id"]), str(row["system_id"])))
    return rows, {
        system: {metric: list(values) for metric, values in sorted(metrics.items())}
        for system, metrics in sorted(vectors.items())
    }


def _current_runs(inputs: LoadedReportInputs) -> list[ValidatedRun]:
    by_index: dict[int, ValidatedRun] = {}
    for run in sorted(inputs.valid_runs, key=lambda item: (item.plan_index, item.attempt)):
        by_index[run.plan_index] = run
    return [by_index[index] for index in sorted(by_index)]


def _failure_taxonomy(inputs: LoadedReportInputs) -> dict[str, Any]:
    by_system: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: {
            "sample_outcomes": Counter(),
            "score_failures": Counter(),
            "verifier_errors": Counter(),
        }
    )
    for run in _current_runs(inputs):
        system = (
            run.plan_item.system.system_id
            if run.plan_item is not None
            else run.manifest.system_id or "unknown"
        )
        outcome, _candidate = classify_sample_outcome(run.scorecard)
        by_system[system]["sample_outcomes"][outcome.value] += 1
        if run.scorecard.failure is not None:
            failure = run.scorecard.failure
            by_system[system]["score_failures"][f"{failure.kind}:{failure.category}"] += 1
        for result in run.scorecard.verifier_results:
            if result.status.value in {"failed", "error"}:
                by_system[system]["verifier_errors"][
                    f"{result.status.value}:{result.error_category.value}"
                ] += 1
    index_failures: dict[str, Counter[str]] = defaultdict(Counter)
    items = {item.plan_index: item for item in inputs.plan_items}
    valid = {run.plan_index for run in _current_runs(inputs)}
    for record in inputs.index_records:
        if record.plan_index in valid:
            continue
        item = items.get(record.plan_index)
        system = item.system.system_id if item is not None else "unknown"
        index_failures[system][record.child_exit_category] += 1
    return {
        "population": "current_valid_terminal_runs_plus_indexed_terminal_failures",
        "by_system": {
            system: {name: dict(sorted(counter.items())) for name, counter in sorted(parts.items())}
            for system, parts in sorted(by_system.items())
        },
        "indexed_nonvalid_by_system": {
            system: dict(sorted(counter.items()))
            for system, counter in sorted(index_failures.items())
        },
    }


def _policy_compatibility(inputs: LoadedReportInputs) -> dict[str, Any]:
    by_system: dict[str, dict[str, Any]] = {}
    for run in _current_runs(inputs):
        system = (
            run.plan_item.system.system_id
            if run.plan_item is not None
            else run.manifest.system_id or "unknown"
        )
        state = by_system.setdefault(
            system,
            {
                "terminal_count": 0,
                "policy_failure_count": 0,
                "policy_failure_categories": Counter(),
                "tool_use_policy_ids": Counter(),
                "tool_event_count": 0,
                "side_effecting_tool_event_count": 0,
                "read_only_tool_event_count": 0,
                "workspace_write_count": 0,
            },
        )
        state["terminal_count"] += 1
        failure = run.scorecard.failure
        if failure is not None and failure.kind == "policy":
            state["policy_failure_count"] += 1
            state["policy_failure_categories"][failure.category] += 1
        for identity in run.manifest.external_agent_observations:
            if identity.tool_use_policy is not None:
                state["tool_use_policy_ids"][identity.tool_use_policy] += 1
            state["tool_event_count"] += identity.tool_event_count or 0
            state["side_effecting_tool_event_count"] += (
                identity.side_effecting_tool_event_count or 0
            )
            state["read_only_tool_event_count"] += identity.read_only_tool_event_count or 0
            state["workspace_write_count"] += identity.workspace_write_count or 0
    rendered: dict[str, Any] = {}
    for system, state in sorted(by_system.items()):
        terminal = int(state["terminal_count"])
        failures = int(state["policy_failure_count"])
        rendered[system] = {
            **{key: value for key, value in state.items() if not isinstance(value, Counter)},
            "policy_compatible_count": terminal - failures,
            "policy_compatibility_rate": ((terminal - failures) / terminal if terminal else None),
            "policy_failure_categories": dict(sorted(state["policy_failure_categories"].items())),
            "tool_use_policy_ids": dict(sorted(state["tool_use_policy_ids"].items())),
        }
    return {
        "population": "current_valid_terminal_runs",
        "by_system": rendered,
    }


def _efficiency(inputs: LoadedReportInputs) -> dict[str, Any]:
    values: dict[str, dict[str, list[float | None]]] = defaultdict(lambda: defaultdict(list))
    cleanup_failures: Counter[str] = Counter()
    for run in _current_runs(inputs):
        system = (
            run.plan_item.system.system_id
            if run.plan_item is not None
            else run.manifest.system_id or "unknown"
        )
        efficiency = run.scorecard.efficiency
        accounting = run.codex_cli_accounting
        values[system]["wall_time_s"].append(efficiency.wall_time_s)
        values[system]["agent_time_s"].append(efficiency.agent_time_s)
        values[system]["tool_time_s"].append(efficiency.tool_time_s)
        values[system]["verifier_time_s"].append(efficiency.verifier_time_s)
        values[system]["external_cli_process_wall_time_s"].append(
            accounting.process_wall_time_s if accounting is not None else None
        )
        values[system]["input_tokens"].append(
            float(accounting.input_tokens)
            if accounting is not None and accounting.input_tokens is not None
            else None
        )
        values[system]["output_tokens"].append(
            float(accounting.output_tokens)
            if accounting is not None and accounting.output_tokens is not None
            else None
        )
        values[system]["total_tokens"].append(
            float(accounting.total_tokens)
            if accounting is not None and accounting.total_tokens is not None
            else None
        )
    result: dict[str, Any] = {}
    for system, metrics in sorted(values.items()):
        metric_summaries = {
            metric: _numeric_summary(metric_values)
            for metric, metric_values in sorted(metrics.items())
        }
        resolved_count = sum(
            run.scorecard.resolved
            for run in _current_runs(inputs)
            if run.plan_item is not None and run.plan_item.system.system_id == system
        )
        wall_total = metric_summaries["wall_time_s"]["sum"]
        token_total = metric_summaries["total_tokens"]["sum"]
        result[system] = {
            "terminal_count": len(metrics["wall_time_s"]),
            "resolved_count": resolved_count,
            "metrics": metric_summaries,
            "wall_seconds_per_resolved_candidate": (
                wall_total / resolved_count if wall_total is not None and resolved_count else None
            ),
            "tokens_per_resolved_candidate": (
                token_total / resolved_count if token_total is not None and resolved_count else None
            ),
            "cleanup_failure_count": cleanup_failures[system],
        }
    return {
        "population": "current_valid_terminal_runs",
        "by_system": result,
    }


def _numeric_summary(values: list[float | None]) -> dict[str, Any]:
    known = [float(value) for value in values if value is not None]
    return {
        "known_value_count": len(known),
        "missing_value_count": len(values) - len(known),
        "sum": sum(known) if known else None,
        "mean": statistics.fmean(known) if known else None,
        "median": statistics.median(known) if known else None,
        "p90": _percentile(known, 0.90),
        "p95": _percentile(known, 0.95),
        "max": max(known) if known else None,
    }


def _statistics(
    vectors: dict[str, dict[str, list[float]]],
    *,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    systems: dict[str, Any] = {}
    for system, metrics in sorted(vectors.items()):
        systems[system] = {}
        for metric, values in sorted(metrics.items()):
            rng = random.Random(_derived_seed(seed, system, metric))
            samples = _bootstrap_means(values, resamples, rng)
            systems[system][metric] = {
                "task_count": len(values),
                "macro_mean": statistics.fmean(values) if values else None,
                "ci_95": _interval(samples),
            }

    paired: dict[str, Any] = {}
    system_ids = sorted(vectors)
    if len(system_ids) == 2:
        left, right = system_ids
        metric_names = sorted(set(vectors[left]) & set(vectors[right]))
        for metric in metric_names:
            left_values = vectors[left][metric]
            right_values = vectors[right][metric]
            if len(left_values) != len(right_values):
                paired[metric] = {
                    "task_count": min(len(left_values), len(right_values)),
                    "difference": None,
                    "ci_95": None,
                    "invalid_reason": "paired_task_coverage_differs",
                }
                continue
            differences = [
                right_value - left_value
                for left_value, right_value in zip(left_values, right_values, strict=True)
            ]
            rng = random.Random(_derived_seed(seed, "paired", metric))
            samples = _bootstrap_means(differences, resamples, rng)
            paired[metric] = {
                "system_order": [left, right],
                "difference_definition": f"{right} minus {left}",
                "task_count": len(differences),
                "difference": statistics.fmean(differences) if differences else None,
                "ci_95": _interval(samples),
                "invalid_reason": None,
            }
    return {
        "method": "deterministic_paired_task_level_nonparametric_bootstrap",
        "bootstrap_unit": "task",
        "resamples": resamples,
        "seed": seed,
        "confidence_level": 0.95,
        "percentile_method": "linear_interpolation",
        "systems": systems,
        "paired_differences": paired,
    }


def _derived_seed(seed: int, *parts: str) -> int:
    payload = f"{seed}:" + ":".join(parts)
    return int(hash_bytes(payload.encode("utf-8"))[:16], 16)


def _bootstrap_means(
    values: list[float],
    resamples: int,
    rng: random.Random,
) -> list[float]:
    if not values:
        return []
    length = len(values)
    return [
        statistics.fmean(values[rng.randrange(length)] for _index in range(length))
        for _sample in range(resamples)
    ]


def _interval(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "lower": _percentile(values, 0.025) or 0.0,
        "upper": _percentile(values, 0.975) or 0.0,
    }


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _render_task_csv(rows: list[dict[str, Any]]) -> str:
    fields = [
        "task_id",
        "system_id",
        "base_seed",
        "expected_n",
        "observed_n",
        "resolved_c",
        "evaluable_count",
        "infrastructure_error_count",
        "cancelled_count",
        "missing_count",
        "canonical_valid",
        "invalid_reason",
        "pass_at_1",
        "pass_at_2",
        "pass_at_3",
        "task_success_at_3",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_value(row.get(field)) for field in fields})
    return stream.getvalue()


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        clean = "".join(character for character in value if ord(character) >= 32)
        if clean.startswith(("=", "+", "-", "@", "\t")):
            return "'" + clean
        return clean
    return value


def _render_markdown(payload: dict[str, Any]) -> str:
    coverage = payload["coverage"]
    lines = [
        "# Full-Scale Agent Evaluation",
        "",
        "This report compares Codex CLI agent execution identities. It is not a direct API",
        "evaluation and is not an official upstream model score.",
        "",
        "## Coverage",
        "",
        f"- Planned items: {coverage['planned_plan_items']}",
        f"- Valid terminal artifacts: {coverage['valid_terminal_artifacts']}",
        f"- Planned tasks: {coverage['planned_task_count']}",
        f"- Canonical task/system groups: "
        f"{coverage['canonical_valid_task_system_group_count']}/"
        f"{coverage['canonical_task_system_group_count']}",
        "",
        "## Macro pass@k",
        "",
        "| System | Tasks | pass@1 | pass@2 | pass@3 | success@3 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    systems = payload["statistical_analysis"]["systems"]
    for system, metrics in sorted(systems.items()):
        task_count = metrics.get("pass_at_1", {}).get("task_count", 0)
        values = [
            _format_rate(metrics.get(name, {}).get("macro_mean"))
            for name in (
                "pass_at_1",
                "pass_at_2",
                "pass_at_3",
                "task_success_at_3",
            )
        ]
        lines.append(f"| {_markdown(system)} | {task_count} | " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "## Statistical method",
            "",
            "Confidence intervals use 10,000 deterministic task-level bootstrap resamples.",
            "Paired differences resample the same task indices for both systems.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;")


def _format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f}"


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = ["FullScaleReportService", "GeneratedFullScaleReports"]
