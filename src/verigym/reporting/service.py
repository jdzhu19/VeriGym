"""Atomic JSON, CSV, and Markdown report generation."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from verigym.core.hashing import hash_bytes
from verigym.core.integrity import write_experiment_artifact_manifest
from verigym.experiments.state import atomic_write_text
from verigym.reporting.aggregate import ReportBuilder
from verigym.reporting.csv_report import build_run_rows, render_csv
from verigym.reporting.loader import load_report_inputs
from verigym.reporting.markdown import render_markdown
from verigym.reporting.schemas import AggregateReport

if TYPE_CHECKING:
    from verigym.reporting.full_scale import GeneratedFullScaleReports


@dataclass(frozen=True)
class GeneratedReports:
    aggregate: AggregateReport
    aggregate_path: Path
    csv_path: Path
    markdown_path: Path
    hashes: dict[str, str]


class ReportService:
    def __init__(self, builder: ReportBuilder | None = None) -> None:
        self.builder = builder or ReportBuilder()

    def generate_all(
        self,
        root: Path,
        *,
        output_dir: Path | None = None,
        group_by: tuple[str, ...] = ("system",),
    ) -> GeneratedReports:
        inputs = load_report_inputs(root)
        aggregate = self.builder.build_inputs(inputs, group_by=group_by)
        destination = _safe_output_directory(output_dir or inputs.root / "reports")
        aggregate_path = destination / "aggregate.json"
        csv_path = destination / "runs.csv"
        markdown_path = destination / "report.md"
        payloads = {
            aggregate_path: json.dumps(
                aggregate.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            csv_path: render_csv(build_run_rows(inputs)),
            markdown_path: render_markdown(aggregate, inputs),
        }
        for path, text in payloads.items():
            atomic_write_text(path, text)
        experiment_manifest = inputs.root / "experiment_manifest.json"
        if destination == inputs.root / "reports" and experiment_manifest.is_file():
            write_experiment_artifact_manifest(inputs.root, inputs.experiment_id)
        return GeneratedReports(
            aggregate=aggregate,
            aggregate_path=aggregate_path,
            csv_path=csv_path,
            markdown_path=markdown_path,
            hashes={path.name: hash_bytes(path.read_bytes()) for path in payloads},
        )

    def generate_one(
        self,
        root: Path,
        *,
        format_name: str,
        output: Path,
        group_by: tuple[str, ...] = ("system",),
    ) -> Path:
        inputs = load_report_inputs(root)
        aggregate = self.builder.build_inputs(inputs, group_by=group_by)
        if format_name == "json":
            text = (
                json.dumps(
                    aggregate.model_dump(mode="json"),
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n"
            )
        elif format_name == "csv":
            text = render_csv(build_run_rows(inputs))
        elif format_name == "markdown":
            text = render_markdown(aggregate, inputs)
        else:
            raise ValueError("report format must be json, csv, or markdown")
        safe_output = _safe_output_file(output)
        atomic_write_text(safe_output, text)
        return safe_output

    def generate_full_scale(
        self,
        root: Path,
        *,
        output_dir: Path | None = None,
        bootstrap_resamples: int = 10_000,
        bootstrap_seed: int = 548_219_773,
    ) -> GeneratedFullScaleReports:
        """Generate deterministic task-level full-scale analysis artifacts."""

        from verigym.reporting.full_scale import FullScaleReportService

        return FullScaleReportService(self.builder).generate(
            root,
            output_dir=output_dir,
            bootstrap_resamples=bootstrap_resamples,
            bootstrap_seed=bootstrap_seed,
        )


def _reject_symlink_components(path: Path) -> None:
    expanded = path.expanduser()
    current = Path(expanded.anchor) if expanded.is_absolute() else Path.cwd()
    parts = expanded.parts[1:] if expanded.is_absolute() else expanded.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"report output traverses a symlink: {current}")


def _safe_output_directory(path: Path) -> Path:
    destination = path.expanduser()
    _reject_symlink_components(destination)
    destination.mkdir(parents=True, exist_ok=True)
    metadata = os.lstat(destination)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("report output must be a real directory")
    return destination


def _safe_output_file(path: Path) -> Path:
    output = path.expanduser()
    _safe_output_directory(output.parent)
    if output.is_symlink():
        raise ValueError("report output file cannot be a symlink")
    return output


__all__ = ["GeneratedReports", "ReportService"]
