"""Bounded CVA6 candidate selection and base-FAIL/reference-PASS qualification."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.workspace import normalize_relative_path
from verigym.evolution.splits import build_task_split, validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.plugin_api import (
    ConfigurationError,
    SuiteSourceConfig,
    VerifierResult,
    VerifierStatus,
    content_hash,
    copy_tree_safely,
)
from verigym.schemas.evolution import TaskSplitEntry, TaskSplitManifest

from .adapter import HweBenchSuite
from .dataset import VARIANT
from .prepare import prepare_source

_PREFERRED = (2032, 2248, 2282, 2468, 2469, 2549, 2589, 2802, 2916, 2944, 3168, 3191, 3204)
_EXCLUDED = frozenset({2170, 2374, 2945, 3107, 3171})
_OPT_IN_ENV = "VERIGYM_RUN_CVA6_QUALIFICATION"


@dataclass(frozen=True)
class Cva6Candidate:
    instance_id: str
    number: int
    modified_file_count: int
    changed_line_count: int
    preferred: bool


def select_cva6_candidates(dataset: Path) -> list[Cva6Candidate]:
    """Return preferred tasks followed by ascending two-file fallback tasks."""

    rows = _bounded_jsonl(dataset)
    candidates: dict[int, Cva6Candidate] = {}
    for row in rows:
        if row.get("org") != "openhwgroup" or row.get("repo") != "cva6":
            continue
        number = row.get("number")
        modified = row.get("modified_files")
        patch = row.get("fix_patch")
        if (
            not isinstance(number, int)
            or number in _EXCLUDED
            or not isinstance(modified, list)
            or not all(isinstance(value, str) for value in modified)
            or not isinstance(patch, str)
        ):
            continue
        changed = _changed_lines(patch)
        file_count = len(set(modified))
        preferred = number in _PREFERRED
        accepted_shape = (preferred and file_count == 1) or (not preferred and file_count == 2)
        if changed <= 20 and accepted_shape:
            candidates[number] = Cva6Candidate(
                instance_id=f"openhwgroup/cva6:pr-{number}",
                number=number,
                modified_file_count=file_count,
                changed_line_count=changed,
                preferred=preferred,
            )
    ordered = [candidates[number] for number in _PREFERRED if number in candidates]
    ordered.extend(
        candidate for number, candidate in sorted(candidates.items()) if number not in _PREFERRED
    )
    if len(ordered) < 13:
        raise ConfigurationError("official CVA6 data has fewer than 13 eligible candidates")
    return ordered


def qualify_cva6_teacher_pool(
    *,
    dataset: Path,
    output: Path,
    existing_split_paths: list[Path],
    pull: bool = False,
    official_dataset_revision: str | None = None,
    official_source_commit: str | None = None,
) -> dict[str, Any]:
    """Qualify 13 tasks in order and freeze 11 training plus two validation tasks."""

    if os.environ.get(_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{_OPT_IN_ENV}=1 is required")
    if not existing_split_paths:
        raise ConfigurationError("at least one existing split is required for overlap exclusion")
    root = _new_directory(output)
    existing = [_load_split(path) for path in existing_split_paths]
    excluded_ids = {
        entry.task_id
        for split in existing
        for entry in (*split.training, *split.validation, *split.heldout)
    }
    excluded_sources = {
        entry.source_hash
        for split in existing
        for entry in (*split.training, *split.validation, *split.heldout)
    }
    heldout = _combined_heldout(existing)
    progress: dict[str, Any] = {
        "format_id": "verigym_cva6_teacher_qualification_progress_v1",
        "status": "running",
        "target_count": 13,
        "excluded_pr_numbers": sorted(_EXCLUDED),
        "outcomes": [],
        "qualified": [],
        "model_process_count": 0,
    }
    atomic_dump_json(root / "qualification-progress.json", progress)

    qualified: list[tuple[Cva6Candidate, TaskSplitEntry, str]] = []
    for candidate in select_cva6_candidates(dataset):
        if len(qualified) == 13:
            break
        source_relative = f"sources/pr-{candidate.number}"
        smoke_relative = f"smokes/pr-{candidate.number}"
        source = root / source_relative
        smoke = root / smoke_relative
        outcome: dict[str, Any] = {
            "instance_id": candidate.instance_id,
            "preferred": candidate.preferred,
            "modified_file_count": candidate.modified_file_count,
            "changed_line_count": candidate.changed_line_count,
            "source": source_relative,
            "status": "started",
        }
        progress["outcomes"].append(outcome)
        atomic_dump_json(root / "qualification-progress.json", progress)
        try:
            prepare_source(
                dataset=dataset,
                output=source,
                selected_tasks=[candidate.instance_id],
                pull=pull,
                official_dataset_revision=official_dataset_revision,
                official_source_commit=official_source_commit,
            )
            report = run_zero_model_smoke(source=source, output=smoke)
        except (ConfigurationError, OSError) as exc:
            report_path = smoke / "smoke-report.json"
            if report_path.is_file() and not report_path.is_symlink():
                report = json.loads(report_path.read_bytes())
                if zero_model_infrastructure_valid(report):
                    outcome.update({"status": "not_qualified", "reason": "fail_pass_mismatch"})
                    atomic_dump_json(root / "qualification-progress.json", progress)
                    continue
            outcome.update({"status": "infrastructure_invalid", "reason": type(exc).__name__})
            progress["status"] = "stopped_infrastructure_invalid"
            atomic_dump_json(root / "qualification-progress.json", progress)
            raise ConfigurationError(
                f"CVA6 qualification stopped on infrastructure-invalid {candidate.instance_id}"
            ) from exc
        if not zero_model_fail_to_pass_eligible(report):
            outcome.update({"status": "not_qualified", "reason": "fail_pass_mismatch"})
            atomic_dump_json(root / "qualification-progress.json", progress)
            continue
        suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=source, variant=VARIANT))
        refs = list(suite.discover())
        if len(refs) != 1:
            raise ConfigurationError("qualified source did not expose exactly one task")
        task = suite.load_task(refs[0])
        if task.id in excluded_ids or task.source.content_hash in excluded_sources:
            outcome.update({"status": "excluded_existing_split"})
            atomic_dump_json(root / "qualification-progress.json", progress)
            continue
        if (
            task.source.content_hash is None
            or task.source.license is None
            or task.source.attribution is None
        ):
            raise ConfigurationError("qualified CVA6 task lacks frozen source provenance")
        entry = TaskSplitEntry(
            task_id=task.id,
            source_hash=task.source.content_hash,
            task_hash=content_hash(task),
            license=task.source.license,
            attribution=task.source.attribution,
        )
        qualified.append((candidate, entry, source_relative))
        outcome.update(
            {
                "status": "qualified",
                "task_id": task.id,
                "source_hash": entry.source_hash,
                "task_hash": entry.task_hash,
            }
        )
        progress["qualified"] = [item[1].task_id for item in qualified]
        atomic_dump_json(root / "qualification-progress.json", progress)

    if len(qualified) < 13:
        progress["status"] = "incomplete"
        progress["qualified_count"] = len(qualified)
        atomic_dump_json(root / "qualification-progress.json", progress)
        return progress
    training = [item[1] for item in qualified[:11]]
    validation = [item[1] for item in qualified[11:13]]
    split = build_task_split(
        split_id="cva6-multiturn-sft-2026-08-v1",
        training=training,
        validation=validation,
        heldout=heldout,
    )
    validate_task_split(split)
    atomic_dump_json(root / "task-split.json", split)
    progress.update(
        {
            "status": "completed",
            "qualified_count": 13,
            "training_pool": [
                {"task_id": entry.task_id, "source": source}
                for _candidate, entry, source in qualified[:11]
            ],
            "development_validation": [
                {"task_id": entry.task_id, "source": source}
                for _candidate, entry, source in qualified[11:13]
            ],
            "task_split_hash": split.manifest_hash,
        }
    )
    atomic_dump_json(root / "qualification-progress.json", progress)
    return progress


def _bounded_jsonl(path: Path) -> list[dict[str, Any]]:
    expanded = path.expanduser()
    if (
        expanded.is_symlink()
        or not expanded.is_file()
        or expanded.stat().st_size > 512 * 1024 * 1024
    ):
        raise ConfigurationError("official CVA6 JSONL must be a bounded regular file")
    rows: list[dict[str, Any]] = []
    try:
        for line in expanded.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("record is not an object")
            rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ConfigurationError("official CVA6 JSONL is malformed") from exc
    return rows


def _changed_lines(patch: str) -> int:
    return sum(
        1
        for line in patch.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _load_split(path: Path) -> TaskSplitManifest:
    try:
        split = TaskSplitManifest.model_validate_json(path.read_bytes())
        return validate_task_split(split)
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"invalid existing task split: {path.name}") from exc


def _combined_heldout(splits: list[TaskSplitManifest]) -> list[TaskSplitEntry]:
    by_id: dict[str, TaskSplitEntry] = {}
    sources: set[str] = set()
    for split in splits:
        for entry in split.heldout:
            previous = by_id.get(entry.task_id)
            if previous is not None and previous != entry:
                raise ConfigurationError("existing splits disagree on a held-out task")
            if previous is None and entry.source_hash in sources:
                raise ConfigurationError("existing held-out splits reuse a source hash")
            by_id[entry.task_id] = entry
            sources.add(entry.source_hash)
    return list(by_id.values())


def zero_model_infrastructure_valid(report: dict[str, Any]) -> bool:
    """Return whether both zero-model verifier invocations produced usable results."""

    base_results = report.get("base_verifier_results")
    reference_results = report.get("verifier_results")
    return (
        report.get("base_infrastructure_error") is False
        and isinstance(base_results, list)
        and bool(base_results)
        and isinstance(reference_results, list)
        and bool(reference_results)
        and all(
            isinstance(result, dict) and result.get("status") != "error"
            for result in (*base_results, *reference_results)
        )
    )


def zero_model_fail_to_pass_eligible(report: dict[str, Any]) -> bool:
    """Return whether a zero-model report proves base-FAIL/reference-PASS."""

    return (
        zero_model_infrastructure_valid(report)
        and report.get("base_failed") is True
        and report.get("base_resolved") is False
        and report.get("reference_passed") is True
        and report.get("model_process_count") == 0
    )


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("qualification output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def run_zero_model_smoke(*, source: Path, output: Path) -> dict[str, Any]:
    """Verify base and reference candidates without opening an untrusted LocalRuntime."""

    if output.exists() or output.is_symlink():
        raise ConfigurationError("qualification smoke output already exists")
    output.mkdir(parents=True)
    suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=source, variant=VARIANT))
    references = list(suite.discover())
    if len(references) != 1:
        raise ConfigurationError("qualified source did not expose exactly one task")
    task = suite.load_task(references[0])
    visible = source / "workspaces" / references[0].native_id
    if visible.is_symlink() or not visible.is_dir():
        raise ConfigurationError("prepared CVA6 visible workspace is missing or unsafe")
    reference = suite.reference_solution(task)
    if reference is None:
        raise ConfigurationError("selected CVA6 task lacks its reference candidate")

    with tempfile.TemporaryDirectory(prefix="candidates-", dir=output) as temporary:
        candidates = Path(temporary)
        base_candidate = candidates / "base"
        reference_candidate = candidates / "reference"
        copy_tree_safely(visible, base_candidate)
        copy_tree_safely(visible, reference_candidate)
        for relative, content in reference.files.items():
            normalized = normalize_relative_path(relative)
            destination = reference_candidate / normalized
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        base_results = suite.verify_candidate(
            task=task,
            candidate_dir=base_candidate,
            artifact_root=output / "base-verifier",
        )
        reference_results = suite.verify_candidate(
            task=task,
            candidate_dir=reference_candidate,
            artifact_root=output / "reference-verifier",
        )
    if base_results is None or reference_results is None:
        raise ConfigurationError("CVA6 suite did not claim its Docker verifier")
    base_failed = bool(base_results) and all(
        result.status == VerifierStatus.FAILED for result in base_results
    )
    reference_passed = bool(reference_results) and all(
        result.status == VerifierStatus.PASSED for result in reference_results
    )
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "kind": "hwe_bench_zero_model_fail_to_pass_qualification",
        "task_id": task.id,
        "base_failed": base_failed,
        "base_resolved": bool(base_results)
        and all(result.status == VerifierStatus.PASSED for result in base_results),
        "base_infrastructure_error": any(
            result.status == VerifierStatus.ERROR for result in base_results
        ),
        "reference_passed": reference_passed,
        "model_process_count": 0,
        "full_campaign": False,
        "base_verifier_results": [_verifier_summary(result) for result in base_results],
        "verifier_results": [_verifier_summary(result) for result in reference_results],
    }
    atomic_dump_json(output / "smoke-report.json", report)
    if not base_failed or not reference_passed:
        raise ConfigurationError("CVA6 smoke did not reproduce base-FAIL/reference-PASS")
    return report


def _verifier_summary(result: VerifierResult) -> dict[str, Any]:
    return {
        "node_id": result.node_id,
        "status": result.status.value,
        "error_category": result.error_category.value,
        "tests_passed": result.tests_passed,
        "tests_total": result.tests_total,
    }


# Retain the private spellings for older callers while exposing descriptive public helpers.
_infrastructure_valid = zero_model_infrastructure_valid
_eligible_report = zero_model_fail_to_pass_eligible
_zero_model_smoke = run_zero_model_smoke


__all__ = [
    "Cva6Candidate",
    "qualify_cva6_teacher_pool",
    "run_zero_model_smoke",
    "select_cva6_candidates",
    "zero_model_fail_to_pass_eligible",
    "zero_model_infrastructure_valid",
]
