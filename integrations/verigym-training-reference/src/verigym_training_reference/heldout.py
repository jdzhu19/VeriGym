"""Freeze and summarize public-only RTL held-out evaluations."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.splits import build_task_split, validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.registry.collections import build_registries
from verigym.schemas.evolution import TaskSplitEntry, TaskSplitManifest
from verigym.schemas.suite import SuiteSourceConfig

_MAX_JSON_BYTES = 8 * 1024 * 1024


def _read_json(path: Path) -> dict[str, Any]:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"expected a regular JSON file: {path.name}")
    if not 0 < metadata.st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError(f"JSON file is empty or oversized: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid JSON file: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"JSON root must be an object: {path.name}")
    return value


def _validated_public_training_entry(path: Path) -> TaskSplitEntry:
    value = _read_json(path)
    expected = value.get("record_hash")
    identity = dict(value)
    identity.pop("record_hash", None)
    if not isinstance(expected, str) or content_hash(identity) != expected:
        raise ConfigurationError("training public input identity differs from its record hash")
    if value.get("hidden_assets_included") is not False:
        raise ConfigurationError("training public input must exclude hidden assets")
    return TaskSplitEntry(
        task_id=value["task_id"],
        source_hash=value["source_hash"],
        task_hash=value["task_hash"],
        license="upstream-benchmark",
        attribution="VeriGym prior training campaign public task",
    )


def build_public_input_record(task: Any, visible_root: Path) -> dict[str, Any]:
    """Build the public-only model input for one already-loaded task."""

    candidate_path = task.interaction.final_submission.path
    if candidate_path is None:
        raise ConfigurationError("held-out export requires a single-file final submission")
    readme_path = visible_root / "README.md"
    candidate = visible_root / candidate_path
    if not readme_path.is_file() or not candidate.is_file():
        raise ConfigurationError("held-out visible workspace omits README or candidate skeleton")
    base = {
        "schema_version": "1.0",
        "task_id": task.id,
        "task_description": task.description,
        "public_readme": readme_path.read_text(encoding="utf-8"),
        "candidate_path": candidate_path,
        "candidate_skeleton": candidate.read_text(encoding="utf-8"),
        "source_hash": task.source.content_hash,
        "task_hash": content_hash(task),
        "hidden_assets_included": False,
    }
    return {**base, "record_hash": content_hash(base)}


def freeze_heldout_evaluation(
    *,
    split_id: str,
    suite_id: str,
    source_root: Path,
    variant: str,
    task_ids: Sequence[str],
    training_public_inputs: Sequence[Path],
    output: Path,
    frozen_after_policy_hash: str,
) -> TaskSplitManifest:
    """Write a new, hash-bound held-out split without exporting verifier assets."""

    if output.exists():
        if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
            raise ConfigurationError("held-out output must be a new or empty real directory")
    else:
        output.mkdir(parents=True)
    resolved_source = source_root.resolve(strict=True)
    source_config = SuiteSourceConfig(source_root=resolved_source, variant=variant)
    suite = build_registries().suites.get(suite_id).with_source(source_config)
    references = {reference.id: reference for reference in suite.discover()}
    native_references = {reference.native_id: reference for reference in references.values()}
    if len(task_ids) != len(set(task_ids)) or not task_ids:
        raise ConfigurationError("held-out task IDs must be nonempty and unique")

    entries: list[TaskSplitEntry] = []
    public_records: list[tuple[str, dict[str, Any]]] = []
    for requested in task_ids:
        reference = references.get(requested) or native_references.get(requested)
        if reference is None:
            raise ConfigurationError(f"held-out task was not found: {requested}")
        task = suite.load_task(reference)
        assets = suite.resolve_assets(task)
        public = build_public_input_record(task, Path(assets.visible_root))
        native_id = str(task.metadata.get("native_task_id", reference.native_id))
        public_records.append((native_id, public))
        entries.append(
            TaskSplitEntry(
                task_id=task.id,
                source_hash=task.source.content_hash,
                task_hash=content_hash(task),
                license="MIT",
                attribution="VerilogEval upstream dataset",
            )
        )

    training = [_validated_public_training_entry(path) for path in training_public_inputs]
    manifest = build_task_split(
        split_id=split_id,
        training=training,
        heldout=entries,
        heldout_assets_loaded_after_version_hash=frozen_after_policy_hash,
    )
    validate_task_split(manifest)
    inputs_root = output / "public-inputs"
    inputs_root.mkdir()
    for native_id, public in public_records:
        task_root = inputs_root / native_id
        task_root.mkdir()
        atomic_dump_json(task_root / "public-input.json", public)
    atomic_dump_json(output / "task-split.json", manifest)
    inventory_base = {
        "schema_version": "1.0",
        "format_id": "verigym_heldout_public_inputs_v1",
        "split_manifest_hash": manifest.manifest_hash,
        "task_ids": sorted(entry.task_id for entry in entries),
        "public_input_hashes": sorted(public["record_hash"] for _, public in public_records),
        "public_input_file_hashes": {
            native_id: hash_bytes((inputs_root / native_id / "public-input.json").read_bytes())
            for native_id, _ in sorted(public_records)
        },
        "sample_eligible_for_training": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
    }
    atomic_dump_json(
        output / "public-input-manifest.json",
        {**inventory_base, "manifest_hash": content_hash(inventory_base)},
    )
    return manifest


def summarize_heldout_results(
    *,
    split: Path,
    policy_roots: Mapping[str, Path],
    output: Path,
) -> dict[str, Any]:
    """Aggregate completed scorecards while preserving infrastructure failures."""

    manifest = TaskSplitManifest.model_validate(_read_json(split))
    validate_task_split(manifest)
    heldout_ids = {entry.task_id for entry in manifest.heldout}
    policies: list[dict[str, Any]] = []
    for policy_id, root in sorted(policy_roots.items()):
        scorecards = [_read_json(path) for path in sorted(root.rglob("runs/*/scorecard.json"))]
        if not scorecards:
            raise ConfigurationError(f"policy evaluation has no scorecards: {policy_id}")
        observed_ids = {scorecard.get("task_id") for scorecard in scorecards}
        if observed_ids != heldout_ids:
            raise ConfigurationError(f"policy {policy_id} did not evaluate the exact held-out set")
        per_task: list[dict[str, Any]] = []
        for task_id in sorted(heldout_ids):
            task_cards = [card for card in scorecards if card.get("task_id") == task_id]
            valid = [
                card
                for card in task_cards
                if card.get("status") != "error"
                and card.get("correctness", {}).get("infrastructure_error") is False
            ]
            resolved = sum(card.get("resolved") is True for card in valid)
            compiled = sum(
                card.get("correctness", {}).get("compile_status") == "passed" for card in valid
            )
            per_task.append(
                {
                    "task_id": task_id,
                    "sample_count": len(task_cards),
                    "infrastructure_invalid_count": len(task_cards) - len(valid),
                    "compile_pass_count": compiled,
                    "resolved_count": resolved,
                    "pass_at_k": resolved > 0,
                    "wall_time_s": sum(
                        float(card.get("efficiency", {}).get("wall_time_s", 0.0))
                        for card in task_cards
                    ),
                }
            )
        total = sum(item["sample_count"] for item in per_task)
        valid_total = total - sum(item["infrastructure_invalid_count"] for item in per_task)
        resolved_total = sum(item["resolved_count"] for item in per_task)
        compile_total = sum(item["compile_pass_count"] for item in per_task)
        policies.append(
            {
                "policy_id": policy_id,
                "task_count": len(per_task),
                "sample_count": total,
                "valid_sample_count": valid_total,
                "infrastructure_invalid_count": total - valid_total,
                "compile_rate": compile_total / valid_total if valid_total else None,
                "resolved_rate": resolved_total / valid_total if valid_total else None,
                "pass_at_k_task_rate": (
                    sum(item["pass_at_k"] for item in per_task) / len(per_task)
                ),
                "verifier_wall_time_s": sum(item["wall_time_s"] for item in per_task),
                "tasks": per_task,
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_heldout_policy_comparison_v1",
        "split_manifest_hash": manifest.manifest_hash,
        "policy_count": len(policies),
        "policies": policies,
        "training_reuse_allowed": False,
    }
    report = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(output, report)
    return report
