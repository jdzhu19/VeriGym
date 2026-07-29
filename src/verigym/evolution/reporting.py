"""Deterministic JSON and Markdown reports for observable evolution artifacts."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from verigym.core.hashing import content_hash
from verigym.experiments.state import (
    atomic_dump_json,
    atomic_write_text,
    load_json_model,
    load_jsonl_models,
)
from verigym.reporting.markdown import markdown_escape
from verigym.schemas.evolution import (
    AgentLineage,
    EvolvingEvaluationReport,
    MemoryPack,
    MemoryPackAudit,
    RewardAnalysisReport,
    RewardChannelStatistics,
    RewardDerivationRecord,
    RewardProfile,
    TrajectoryDatasetManifest,
    TrajectoryDatasetReport,
    TrajectoryDatasetStatistics,
)

from .comparison import validate_evolving_evaluation
from .exporter import validate_trajectory_dataset
from .memory import validate_memory_pack
from .versions import validate_agent_lineage

_CHANNEL_UNITS = {
    "infrastructure_valid": "binary",
    "policy_compliance": "binary",
    "public_test_reached": "binary",
    "public_test_passed": "binary",
    "patch_reproducible": "binary",
    "candidate_compile_passed": "binary",
    "hidden_regression_passed": "binary",
    "task_resolved": "binary",
    "changed_file_count": "count",
    "added_lines": "lines",
    "deleted_lines": "lines",
    "public_tool_calls": "count",
    "wall_time_s": "seconds",
    "input_tokens": "tokens",
    "output_tokens": "tokens",
}


@dataclass(frozen=True)
class GeneratedEvolutionReports:
    paths: tuple[Path, ...]


def _output_directory(path: Path) -> Path:
    destination = path.expanduser()
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("evolution report output must be a real directory")
    else:
        destination.mkdir(parents=True)
    return destination.resolve(strict=True)


def _dataset_report(
    manifest: TrajectoryDatasetManifest,
    statistics: TrajectoryDatasetStatistics,
) -> TrajectoryDatasetReport:
    base = {
        "schema_version": "1.0",
        "report_id": f"trajectory-report:{manifest.dataset_hash[:16]}",
        "dataset_hash": manifest.dataset_hash,
        "record_count": statistics.record_count,
        "eligible_count": statistics.eligible_count,
        "ineligible_count": statistics.record_count - statistics.eligible_count,
        "outcome_counts": statistics.outcome_counts,
        "split_counts": statistics.split_counts,
        "agent_version_counts": statistics.agent_version_counts,
        "no_model_calls": True,
        "no_runtime_calls": True,
    }
    return TrajectoryDatasetReport.model_validate({**base, "report_hash": content_hash(base)})


def _reward_report(
    manifest: TrajectoryDatasetManifest,
    profile: RewardProfile,
    rewards: list[RewardDerivationRecord],
) -> RewardAnalysisReport:
    channels: list[RewardChannelStatistics] = []
    for channel, unit in _CHANNEL_UNITS.items():
        values = [
            float(value)
            for record in rewards
            for value in [getattr(record.reward, channel)]
            if value is not None
        ]
        channels.append(
            RewardChannelStatistics(
                channel=channel,
                unit=unit,  # type: ignore[arg-type]
                available=len(values),
                missing=len(rewards) - len(values),
                minimum=min(values) if values else None,
                mean=statistics.fmean(values) if values else None,
                maximum=max(values) if values else None,
            )
        )
    base = {
        "schema_version": "1.0",
        "report_id": f"reward-analysis:{manifest.dataset_hash[:16]}",
        "dataset_hash": manifest.dataset_hash,
        "reward_schema_id": "repo_rtl_reward_vector_v1",
        "reward_profile_id": profile.profile_id,
        "reward_profile_hash": profile.profile_hash,
        "vector_authoritative": True,
        "universal_benchmark_score": False,
        "record_count": len(rewards),
        "outcome_counts": dict(
            sorted(Counter(record.reward.outcome_kind for record in rewards).items())
        ),
        "channels": [channel.model_dump(mode="json") for channel in channels],
    }
    return RewardAnalysisReport.model_validate({**base, "report_hash": content_hash(base)})


def _trajectory_markdown(report: TrajectoryDatasetReport) -> str:
    lines = [
        "# Trajectory dataset report",
        "",
        f"- Dataset: `{markdown_escape(report.dataset_hash)}`",
        f"- Records: {report.record_count}",
        f"- Eligible: {report.eligible_count}",
        f"- Ineligible: {report.ineligible_count}",
        "- Export used model/runtime calls: false",
        "",
        "## Outcomes",
        "",
        "| Outcome | Count |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {markdown_escape(name)} | {count} |"
        for name, count in sorted(report.outcome_counts.items())
    )
    return "\n".join(lines) + "\n"


def _reward_markdown(report: RewardAnalysisReport) -> str:
    lines = [
        "# Reward analysis",
        "",
        "The decomposed vector is authoritative. The named scalar profile is for "
        "training experiments only and is not a universal benchmark score.",
        "",
        f"- Dataset: `{markdown_escape(report.dataset_hash)}`",
        f"- Profile: `{markdown_escape(report.reward_profile_id or 'none')}`",
        f"- Records: {report.record_count}",
        "",
        "| Channel | Available | Missing | Mean | Unit |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for item in report.channels:
        mean = "unavailable" if item.mean is None else f"{item.mean:.12g}"
        lines.append(
            f"| {markdown_escape(item.channel)} | {item.available} | {item.missing} | "
            f"{mean} | {markdown_escape(item.unit)} |"
        )
    return "\n".join(lines) + "\n"


def build_memory_pack_audit(memory: MemoryPack) -> MemoryPackAudit:
    validate_memory_pack(memory)
    base = {
        "schema_version": "1.0",
        "memory_pack_id": memory.memory_pack_id,
        "memory_pack_hash": memory.content_hash,
        "policy_id": memory.policy_id,
        "section_count": 5,
        "item_count": sum(len(section.items) for section in memory.sections),
        "total_utf8_bytes": memory.total_utf8_bytes,
        "content_policy_passed": True,
        "task_independent": True,
        "code_free": True,
        "hidden_assets_included": False,
        "references_included": False,
        "credentials_included": False,
        "heldout_content_included": False,
    }
    return MemoryPackAudit.model_validate({**base, "audit_hash": content_hash(base)})


def _lineage_markdown(lineage: AgentLineage) -> str:
    parent, result = lineage.versions
    return "\n".join(
        [
            "# Agent lineage",
            "",
            f"- Lineage: `{markdown_escape(lineage.lineage_hash)}`",
            f"- v0: `{markdown_escape(parent.agent_version_id)}` "
            f"(`{markdown_escape(parent.version_hash)}`)",
            f"- v1: `{markdown_escape(result.agent_version_id)}` "
            f"(`{markdown_escape(result.version_hash)}`)",
            "- Update: bounded read-only context memory",
            "- Model weights modified: false",
            "",
        ]
    )


def render_evolving_markdown(report: EvolvingEvaluationReport) -> str:
    validate_evolving_evaluation(report)
    lines = [
        "# Evolving-agent evaluation",
        "",
        report.required_interpretation,
        "",
        "- Model weights modified: false",
        f"- Held-out tasks: {report.heldout_task_count}",
        f"- Samples per task/version: {report.samples_per_task_version}",
        "",
        "| Version | Planned | Terminal | Evaluable | Resolved | pass@1 | pass@2 | pass@3 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report.version_metrics:
        values = [
            "unavailable" if value is None else f"{value:.12g}"
            for value in (
                item.macro_pass_at_1,
                item.macro_pass_at_2,
                item.macro_pass_at_3,
            )
        ]
        lines.append(
            f"| {markdown_escape(item.agent_version_id)} | {item.planned} | {item.terminal} | "
            f"{item.evaluable} | {item.resolved} | {values[0]} | {values[1]} | {values[2]} |"
        )
    return "\n".join(lines) + "\n"


class EvolutionReportService:
    """Write canonical report pairs from already-frozen offline artifacts."""

    def generate_dataset(
        self,
        dataset: Path,
        output: Path,
    ) -> GeneratedEvolutionReports:
        manifest = validate_trajectory_dataset(dataset)
        statistics_report = load_json_model(
            dataset / "statistics.json",
            TrajectoryDatasetStatistics,
        )
        profile = load_json_model(
            dataset / "reward-profile-manifest.json",
            RewardProfile,
        )
        rewards = load_jsonl_models(dataset / "rewards.jsonl", RewardDerivationRecord)
        trajectory = _dataset_report(manifest, statistics_report)
        reward = _reward_report(manifest, profile, rewards)
        output = _output_directory(output)
        paths = (
            output / "trajectory-dataset-report.json",
            output / "trajectory-dataset-report.md",
            output / "reward-analysis.json",
            output / "reward-analysis.md",
        )
        atomic_dump_json(paths[0], trajectory)
        atomic_write_text(paths[1], _trajectory_markdown(trajectory))
        atomic_dump_json(paths[2], reward)
        atomic_write_text(paths[3], _reward_markdown(reward))
        return GeneratedEvolutionReports(paths=paths)

    def generate_lineage(
        self,
        *,
        lineage: AgentLineage,
        memory: MemoryPack,
        output: Path,
    ) -> GeneratedEvolutionReports:
        validate_agent_lineage(lineage)
        audit = build_memory_pack_audit(memory)
        output = _output_directory(output)
        paths = (
            output / "agent-lineage.json",
            output / "agent-lineage.md",
            output / "memory-pack-audit.json",
        )
        atomic_dump_json(paths[0], lineage)
        atomic_write_text(paths[1], _lineage_markdown(lineage))
        atomic_dump_json(paths[2], audit)
        return GeneratedEvolutionReports(paths=paths)

    def generate_evaluation(
        self,
        report: EvolvingEvaluationReport,
        output: Path,
    ) -> GeneratedEvolutionReports:
        validate_evolving_evaluation(report)
        output = _output_directory(output)
        paths = (
            output / "evolving-evaluation.json",
            output / "evolving-evaluation.md",
        )
        atomic_dump_json(paths[0], report)
        atomic_write_text(paths[1], render_evolving_markdown(report))
        return GeneratedEvolutionReports(paths=paths)


__all__ = [
    "EvolutionReportService",
    "GeneratedEvolutionReports",
    "build_memory_pack_audit",
    "render_evolving_markdown",
]
