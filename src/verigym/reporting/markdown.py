"""Human-readable Markdown report rendering with untrusted-text escaping."""

from __future__ import annotations

from urllib.parse import quote

from verigym.reporting.csv_report import build_run_rows
from verigym.reporting.loader import LoadedReportInputs
from verigym.reporting.schemas import AggregateReport, ExplicitRate


def markdown_escape(value: object) -> str:
    text = str(value)
    text = "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " " for character in text
    )
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )[:4096]


def render_markdown(aggregate: AggregateReport, inputs: LoadedReportInputs) -> str:
    coverage = aggregate.coverage
    lines = [
        f"# VeriGym experiment report: {markdown_escape(aggregate.experiment_id)}",
        "",
        "This report keeps correctness, coverage, cost, and profile-relative area separate. "
        "It does not define a universal VeriGym score.",
        "",
        "## Identity and compatibility scope",
        "",
        f"- Source: `{markdown_escape(aggregate.source_kind)}`",
        f"- Config hash: `{markdown_escape(aggregate.config_hash or 'unavailable')}`",
        f"- Plan hash: `{markdown_escape(aggregate.plan_hash or 'unavailable')}`",
        f"- Input-set hash: `{markdown_escape(aggregate.input_set_hash)}`",
        "",
        "## Compatibility partitions",
        "",
        "Correctness is never pooled across different suite release/source or correctness "
        "identities.",
        "",
        "| Partition | Planned | Valid | Evaluable | Resolved | "
        "Resolved/evaluable | Tasks | Systems |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for compatibility_partition in aggregate.compatibility_aggregates:
        lines.append(
            f"| `{markdown_escape(compatibility_partition.partition_id)}` | "
            f"{compatibility_partition.planned_count} | "
            f"{compatibility_partition.valid_count} | "
            f"{compatibility_partition.evaluable_count} | "
            f"{compatibility_partition.resolved_count} | "
            f"{_format_rate(compatibility_partition.resolved_rate_evaluable.value)} | "
            f"{compatibility_partition.task_coverage_count} | "
            f"{compatibility_partition.system_coverage_count} |"
        )
    lines.extend(
        [
            "",
            "## Codex CLI integration partitions",
            "",
            "A CLI model proxy is not a direct API benchmark. Model-proxy and external-agent "
            "tracks, CLI versions, and capability fingerprints are reported as distinct "
            "systems. Authentication comparison uses the semantic ID; requested labels remain "
            "provenance.",
            "",
            "| Track | Requested model | Observed model | Confidence | CLI version | "
            "Executable SHA-256 | Capability fingerprint | Requested effort | Effective effort | "
            "Effort source | Inherited effort | Requested auth | Resolved auth | "
            "Auth semantic ID | Alias used | Sandbox | Approval |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
            "--- | --- | --- | --- |",
        ]
    )
    codex_partitions = aggregate.metadata.get("codex_cli_identity_partitions", [])
    if isinstance(codex_partitions, list):
        for partition in codex_partitions:
            if not isinstance(partition, dict):
                continue
            lines.append(
                f"| {markdown_escape(partition.get('integration_track', ''))} | "
                f"{markdown_escape(partition.get('requested_model_id', ''))} | "
                f"{markdown_escape(partition.get('observed_model_id', ''))} | "
                f"{markdown_escape(partition.get('identity_confidence', ''))} | "
                f"{markdown_escape(partition.get('cli_version', ''))} | "
                f"`{markdown_escape(partition.get('cli_executable_sha256', ''))}` | "
                f"`{markdown_escape(partition.get('capability_fingerprint', ''))}` | "
                f"{markdown_escape(partition.get('requested_reasoning_effort', ''))} | "
                f"{markdown_escape(partition.get('effective_reasoning_effort', ''))} | "
                f"{markdown_escape(partition.get('reasoning_effort_source', ''))} | "
                f"{markdown_escape(partition.get('inherited_reasoning_effort_allowed', ''))} | "
                f"{markdown_escape(partition.get('requested_auth_mode', ''))} | "
                f"{markdown_escape(partition.get('resolved_auth_mode', ''))} | "
                f"`{markdown_escape(partition.get('auth_semantic_id', ''))}` | "
                f"{markdown_escape(partition.get('auth_alias_used', ''))} | "
                f"{markdown_escape(partition.get('sandbox_policy', ''))} | "
                f"{markdown_escape(partition.get('approval_policy', ''))} |"
            )
    lines.extend(
        [
            "",
            "## Plan and completion coverage",
            "",
            "| Measure | Count |",
            "| --- | ---: |",
            f"| Planned plan items | {coverage.planned_plan_items} |",
            f"| Started plan items | {coverage.started_plan_items} |",
            f"| Terminal child runs | {coverage.terminal_child_runs} |",
            f"| Valid terminal artifacts | {coverage.valid_terminal_artifacts} |",
            f"| Evaluable candidate runs | {coverage.evaluable_candidate_runs} |",
            f"| Resolved runs | {coverage.resolved_runs} |",
            f"| Unresolved evaluable runs | {coverage.unresolved_evaluable_runs} |",
            f"| Infrastructure errors | {coverage.infrastructure_error_runs} |",
            f"| Corrupt/incompatible artifacts | {coverage.corrupt_incompatible_artifacts} |",
            f"| Missing plan items | {coverage.missing_plan_items} |",
            "",
            "## Correctness with explicit denominators",
            "",
            _rate_line(
                "Resolved rate over evaluable candidates", aggregate.resolved_rate_evaluable
            ),
            _rate_line("Resolved rate over planned items", aggregate.resolved_rate_planned),
            _rate_line("Evaluation completion rate", aggregate.evaluation_completion_rate),
            "",
            "| Stage | Passed | Applicable | Rate | Missing | Infrastructure errors |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for stage in aggregate.correctness_stages:
        lines.append(
            f"| {markdown_escape(stage.stage)} | {stage.numerator} | {stage.denominator} | "
            f"{_format_rate(stage.rate)} | {stage.missing_count} | "
            f"{stage.infrastructure_error_count} |"
        )
    lines.extend(
        [
            "",
            "## Failure taxonomy",
            "",
            _taxonomy_line("Candidate outcomes", aggregate.failure_taxonomy.candidate_outcomes),
            _taxonomy_line("Model infrastructure", aggregate.failure_taxonomy.model_infrastructure),
            _taxonomy_line("Runtime/sandbox", aggregate.failure_taxonomy.runtime_sandbox),
            _taxonomy_line("Verifier/tool", aggregate.failure_taxonomy.verifier_tool),
            _taxonomy_line("Batch/artifact", aggregate.failure_taxonomy.batch_artifact),
            "",
            "## Efficiency and cost",
            "",
            "Efficiency summaries use resolved runs only. Missing cost is not zero, and costs "
            "without a persisted currency identity are not summed.",
            "",
            "| Metric | Known | Missing | Mean | Median | Unit |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for name, summary in aggregate.efficiency_resolved.items():
        lines.append(
            f"| {markdown_escape(name)} | {summary.known_value_count} | "
            f"{summary.missing_value_count} | {_format_number(summary.mean)} | "
            f"{_format_number(summary.median)} | {markdown_escape(summary.unit or '')} |"
        )
    cost = aggregate.cost_resolved
    accounting = aggregate.cost_accounting
    lines.append(
        f"| model_api_cost | {cost.known_value_count} | {cost.missing_value_count} | "
        f"unavailable | unavailable | partitioned below |"
    )
    if accounting is not None:
        lines.extend(
            [
                "",
                f"Unknown cost unit/currency values: {accounting.unknown_unit_count}; "
                f"incompatible-unit values: {accounting.incompatible_unit_count}.",
                "",
                "| Cost dimension | Identifier | Known | Sum |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        for partition in accounting.partitions:
            lines.append(
                f"| {markdown_escape(partition.dimension)} | "
                f"{markdown_escape(partition.identifier)} | "
                f"{partition.known_value_count} | {_format_number(partition.sum)} |"
            )
    lines.extend(
        [
            "",
            "## Per-system coverage",
            "",
            "| Group | Planned | Valid | Evaluable | Resolved | Resolved/evaluable | Tasks |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for group in aggregate.grouped_aggregates:
        label = ", ".join(f"{key}={value}" for key, value in group.dimensions.items())
        lines.append(
            f"| {markdown_escape(group.compatibility_partition_id[:12] + ':' + label)} | "
            f"{group.planned_count} | {group.valid_count} | "
            f"{group.evaluable_count} | {group.resolved_count} | "
            f"{_format_rate(group.resolved_rate_evaluable.value)} | "
            f"{group.task_coverage_count} |"
        )
    lines.extend(
        [
            "",
            "## Sampling, Best-of-N, and pass@k",
            "",
            "Samples are grouped by exact evaluation identity and base seed; base seeds are not "
            "pooled. Infrastructure errors invalidate canonical pass@k.",
            "",
            "| Task | System | Base seed | n | c | Valid | Best-of-N | pass@k |",
            "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for sample_group in aggregate.sampling.groups:
        entries = ", ".join(
            (
                f"pass@{entry.k}={_format_rate(entry.value)}"
                if entry.valid
                else f"pass@{entry.k}=invalid:{entry.invalid_reason}"
            )
            for entry in sample_group.entries
        )
        lines.append(
            f"| {markdown_escape(sample_group.task_id)} | "
            f"{markdown_escape(sample_group.system_id)} | "
            f"{sample_group.base_seed} | {sample_group.expected_n} | "
            f"{sample_group.resolved_c} | "
            f"{'yes' if sample_group.canonical_valid else 'no'} | "
            f"{markdown_escape(sample_group.best_of_n_success)} | "
            f"{markdown_escape(entries)} |"
        )
    lines.extend(
        [
            "",
            "## Area-only quality partitions",
            "",
            "Area is educational, profile-relative, correctness-gated, and non-signoff. "
            "Partitions are never ranked against each other; timing and power are unavailable.",
            "",
        ]
    )
    if not aggregate.quality_partitions:
        lines.append("No profile-enabled area results are present.")
    for quality_partition in aggregate.quality_partitions:
        lines.extend(
            [
                f"### `{markdown_escape(quality_partition.partition_id)}`",
                "",
                f"- Task: `{markdown_escape(quality_partition.task_id)}`",
                f"- Resolved profile: `{markdown_escape(quality_partition.resolved_profile_hash)}`",
                f"- Unit: `{markdown_escape(quality_partition.area_unit)}`",
                f"- Eligible/ineligible: {quality_partition.eligible_run_count}/"
                f"{quality_partition.ineligible_run_count}",
                "- Area-ratio min/median/max: "
                f"{_format_number(quality_partition.ratio_min)} / "
                f"{_format_number(quality_partition.ratio_median)} / "
                f"{_format_number(quality_partition.ratio_max)}",
                "",
            ]
        )
    lines.extend(
        [
            "## Child runs",
            "",
            "| Plan | Attempt | Track | Status | Run |",
            "| ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in build_run_rows(inputs):
        path = row.get("relative_run_path")
        run_id = markdown_escape(row.get("run_id") or "unavailable")
        safe_path = quote(str(path), safe="/-._~") if path else None
        link = f"[{run_id}](../{safe_path})" if safe_path else run_id
        lines.append(
            f"| {row['plan_index']} | {row['attempt']} | "
            f"{markdown_escape(row.get('integration_track') or '')} | "
            f"{markdown_escape(row.get('status') or '')} | {link} |"
        )
    lines.extend(["", "## Warnings and invalid artifacts", ""])
    if not aggregate.warnings and not aggregate.invalid_inputs:
        lines.append("None.")
    for warning in aggregate.warnings:
        lines.append(f"- Warning: {markdown_escape(warning)}")
    for invalid in aggregate.invalid_inputs:
        lines.append(
            f"- Invalid `{markdown_escape(invalid.relative_path)}` "
            f"({markdown_escape(invalid.category)}): {markdown_escape(invalid.message)}"
        )
    return "\n".join(lines) + "\n"


def _rate_line(label: str, rate: ExplicitRate) -> str:
    value = f"- {label}: {_format_rate(rate.value)} ({rate.numerator}/{rate.denominator})"
    if rate.unavailable_reason is not None:
        value += f"; unavailable: {markdown_escape(rate.unavailable_reason)}"
    return value


def _format_rate(value: float | None) -> str:
    return "null" if value is None else f"{value:.12g}"


def _format_number(value: float | None) -> str:
    return "null" if value is None else f"{value:.12g}"


def _taxonomy_line(label: str, values: dict[str, int]) -> str:
    detail = ", ".join(f"{key}={value}" for key, value in sorted(values.items())) or "none"
    return f"- {label}: {markdown_escape(detail)}"


__all__ = ["markdown_escape", "render_markdown"]
