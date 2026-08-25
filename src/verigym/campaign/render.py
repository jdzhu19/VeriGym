"""Deterministic CSV and Markdown rendering for campaign reports."""

from __future__ import annotations

import csv
import io
from typing import Any

from verigym.campaign.schemas import CampaignReport
from verigym.reporting.markdown import markdown_escape

CAMPAIGN_CSV_COLUMNS = [
    "record_type",
    "input_id",
    "evaluation_mode",
    "source_kind",
    "suite_id",
    "experiment_id",
    "system_id",
    "agent_id",
    "model_client_id",
    "model_provider",
    "model_id",
    "agent_version_id",
    "planned_count",
    "terminal_count",
    "evaluable_count",
    "resolved_count",
    "resolved_rate_evaluable",
    "infrastructure_failure_count",
    "license_unavailable_count",
    "macro_pass_at_1",
    "mean_total_tokens",
    "mean_tool_calls",
    "mean_wall_time_s",
    "observed_model_api_calls",
    "model_cost_sum",
    "model_cost_unit",
    "comparison_partition_id",
    "task_id",
    "declared_profile_id",
    "resolved_profile_hash",
    "metric_scope",
    "area_unit",
    "timing_unit",
    "clock_period",
    "ppa_eligible_count",
    "ppa_ineligible_count",
    "area_median",
    "reference_area_median",
    "area_ratio_median",
    "delay_median",
    "reference_delay_median",
    "delay_ratio_median",
    "worst_negative_slack_median",
    "reference_worst_negative_slack_median",
    "worst_negative_slack_delta_median",
    "power_unit",
    "power_median",
    "reference_power_median",
    "power_ratio_median",
]


def _cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def render_campaign_csv(report: CampaignReport) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CAMPAIGN_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for evaluation in report.evaluations:
        writer.writerow(
            {
                key: _cell(value)
                for key, value in {
                    "record_type": "evaluation",
                    "input_id": evaluation.input_id,
                    "evaluation_mode": evaluation.evaluation_mode,
                    "source_kind": evaluation.source_kind,
                    "suite_id": evaluation.suite_id,
                    "experiment_id": evaluation.experiment_id,
                    "system_id": evaluation.system_id,
                    "agent_id": evaluation.agent_id,
                    "model_client_id": evaluation.model_client_id,
                    "model_provider": evaluation.model_provider,
                    "model_id": evaluation.model_id,
                    "agent_version_id": evaluation.agent_version_id,
                    "planned_count": evaluation.planned_count,
                    "terminal_count": evaluation.terminal_count,
                    "evaluable_count": evaluation.evaluable_count,
                    "resolved_count": evaluation.resolved_count,
                    "resolved_rate_evaluable": evaluation.resolved_rate_evaluable.value,
                    "infrastructure_failure_count": evaluation.infrastructure_failure_count,
                    "license_unavailable_count": evaluation.license_unavailable_count,
                    "macro_pass_at_1": evaluation.macro_pass_at_1,
                    "mean_total_tokens": evaluation.mean_total_tokens,
                    "mean_tool_calls": evaluation.mean_tool_calls,
                    "mean_wall_time_s": evaluation.mean_wall_time_s,
                    "observed_model_api_calls": evaluation.observed_model_api_calls,
                    "model_cost_sum": evaluation.model_cost_sum,
                    "model_cost_unit": evaluation.model_cost_unit,
                }.items()
            }
        )
    for quality in report.quality_partitions:
        writer.writerow(
            {
                key: _cell(value)
                for key, value in {
                    "record_type": "quality_partition",
                    "input_id": quality.input_id,
                    "evaluation_mode": quality.evaluation_mode,
                    "agent_version_id": quality.agent_version_id,
                    "comparison_partition_id": quality.comparison_partition_id,
                    "task_id": quality.task_id,
                    "declared_profile_id": quality.declared_profile_id,
                    "resolved_profile_hash": quality.resolved_profile_hash,
                    "metric_scope": quality.metric_scope,
                    "area_unit": quality.area_unit,
                    "timing_unit": quality.timing_unit,
                    "clock_period": quality.clock_period,
                    "ppa_eligible_count": quality.eligible_run_count,
                    "ppa_ineligible_count": quality.ineligible_run_count,
                    "area_median": quality.area_median,
                    "reference_area_median": quality.reference_area_median,
                    "area_ratio_median": quality.area_ratio_median,
                    "delay_median": quality.delay_median,
                    "reference_delay_median": quality.reference_delay_median,
                    "delay_ratio_median": quality.delay_ratio_median,
                    "worst_negative_slack_median": quality.worst_negative_slack_median,
                    "reference_worst_negative_slack_median": (
                        quality.reference_worst_negative_slack_median
                    ),
                    "worst_negative_slack_delta_median": (
                        quality.worst_negative_slack_delta_median
                    ),
                    "power_unit": quality.power_unit,
                    "power_median": quality.power_median,
                    "reference_power_median": quality.reference_power_median,
                    "power_ratio_median": quality.power_ratio_median,
                }.items()
            }
        )
    return stream.getvalue()


def _number(value: float | int | None) -> str:
    return "unavailable" if value is None else f"{value:.12g}"


def _rate(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.2%}"


def render_campaign_markdown(report: CampaignReport) -> str:
    coverage = report.mode_coverage
    lines = [
        "# VeriGym evaluation campaign",
        "",
        f"- Campaign: `{markdown_escape(report.campaign_id)}`",
        f"- Name: {markdown_escape(report.campaign_name)}",
        "- Inputs: "
        f"{coverage.chat_inputs + coverage.agent_inputs + coverage.evolving_agent_inputs}",
        "- Reporting model/tool calls: 0/0",
        f"- Complete chat/agent/evolving matrix: "
        f"{'yes' if coverage.complete_platform_matrix else 'no'}",
        "",
        "## Evaluation matrix",
        "",
        "| Input | Mode | Suite | System/version | Model | Resolved | pass@1 | "
        "Tokens | Tools | Wall s |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for evaluation in report.evaluations:
        system = evaluation.agent_version_id or evaluation.system_id
        model = evaluation.model_id or "none"
        if evaluation.model_provider is not None:
            model = f"{evaluation.model_provider}/{model}"
        lines.append(
            f"| {markdown_escape(evaluation.input_id)} | "
            f"{markdown_escape(evaluation.evaluation_mode)} | "
            f"{markdown_escape(evaluation.suite_id)} | {markdown_escape(system)} | "
            f"{markdown_escape(model)} | "
            f"{evaluation.resolved_count}/{evaluation.evaluable_count} "
            f"({_rate(evaluation.resolved_rate_evaluable.value)}) | "
            f"{_rate(evaluation.macro_pass_at_1)} | "
            f"{_number(evaluation.mean_total_tokens)} | "
            f"{_number(evaluation.mean_tool_calls)} | "
            f"{_number(evaluation.mean_wall_time_s)} |"
        )
    lines.extend(
        [
            "",
            "## Exact PPA compatibility partitions",
            "",
            report.quality_comparison_policy,
            "",
        ]
    )
    if not report.quality_partitions:
        lines.append("No correctness-gated synthesis quality data is present.")
    else:
        lines.extend(
            [
                "| Input/version | Partition | Task | Eligible | Area cand/ref | "
                "Delay cand/ref | WNS cand/ref | Power cand/ref | Ratios A/D/P |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for quality in report.quality_partitions:
            label = f"{quality.input_id}/{quality.agent_version_id or '-'}"
            lines.append(
                f"| {markdown_escape(label)} | "
                f"`{markdown_escape(quality.comparison_partition_id[:16])}` | "
                f"{markdown_escape(quality.task_id)} | {quality.eligible_run_count} | "
                f"{_number(quality.area_median)}/{_number(quality.reference_area_median)} "
                f"{markdown_escape(quality.area_unit)} | "
                f"{_number(quality.delay_median)}/{_number(quality.reference_delay_median)} "
                f"{markdown_escape(quality.timing_unit or '-')} | "
                f"{_number(quality.worst_negative_slack_median)}/"
                f"{_number(quality.reference_worst_negative_slack_median)} "
                f"{markdown_escape(quality.timing_unit or '-')} | "
                f"{_number(quality.power_median)}/"
                f"{_number(quality.reference_power_median)} "
                f"{markdown_escape(quality.power_unit or '-')} | "
                f"{_number(quality.area_ratio_median)}/"
                f"{_number(quality.delay_ratio_median)}/"
                f"{_number(quality.power_ratio_median)} |"
            )
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {markdown_escape(item)}" for item in report.warnings)
    return "\n".join(lines) + "\n"


__all__ = ["CAMPAIGN_CSV_COLUMNS", "render_campaign_csv", "render_campaign_markdown"]
