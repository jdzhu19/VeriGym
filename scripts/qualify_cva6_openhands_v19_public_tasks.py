#!/usr/bin/env python3
"""Qualify the frozen OpenHands v19 public CVA6 reserve without model calls."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any

from verigym_hwe_bench.adapter import HweBenchSuite
from verigym_hwe_bench.cva6_qualification import (
    run_zero_model_smoke,
    zero_model_fail_to_pass_eligible,
    zero_model_infrastructure_valid,
)
from verigym_hwe_bench.dataset import VARIANT
from verigym_hwe_bench.models import ImageLockV2
from verigym_hwe_bench.prepare import prepare_source
from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_QUALIFICATION_CANDIDATES,
    evaluate_v19_qualification_gate,
    frozen_v19_candidate_inventory,
)

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.state import atomic_dump_json
from verigym.plugin_api import SuiteSourceConfig

OPENHANDS_V19_PUBLIC_QUALIFICATION_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V19_PUBLIC_QUALIFICATION"
OPENHANDS_V19_PUBLIC_QUALIFICATION_FORMAT = (
    "verigym_openhands_hwe_v19_public_qualification_progress_v1"
)
_MAX_JSON_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verifier-cache", type=Path)
    parser.add_argument("--official-dataset-revision")
    parser.add_argument("--official-source-commit")
    return parser


def qualify_v19_public_tasks(
    *,
    dataset: Path,
    output: Path,
    verifier_cache: Path | None = None,
    official_dataset_revision: str | None = None,
    official_source_commit: str | None = None,
) -> dict[str, Any]:
    """Run the frozen seven-task, five-success zero-model qualification gate."""

    if os.environ.get(OPENHANDS_V19_PUBLIC_QUALIFICATION_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V19_PUBLIC_QUALIFICATION_OPT_IN_ENV}=1 is required")
    expanded_dataset = dataset.expanduser()
    if expanded_dataset.is_symlink() or not expanded_dataset.is_file():
        raise ConfigurationError("OpenHands v19 qualification dataset is unsafe")
    resolved_dataset = expanded_dataset.resolve(strict=True)
    inventory = frozen_v19_candidate_inventory(resolved_dataset)
    root = _new_directory(output)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V19_PUBLIC_QUALIFICATION_FORMAT,
        "status": "running",
        "candidate_order": list(OPENHANDS_V19_QUALIFICATION_CANDIDATES),
        "candidate_inventory": inventory,
        "official_dataset_sha256": hash_bytes(resolved_dataset.read_bytes()),
        "implicit_image_pulls_allowed": False,
        "verifier_network": "none",
        "model_process_count": 0,
        "heldout_task_ids_loaded": [],
        "active_task_id": None,
        "outcomes": [],
        "qualified_bindings": {},
    }
    _write_progress(root, progress)

    for candidate in inventory:
        gate = evaluate_v19_qualification_gate(progress["outcomes"])
        if gate.satisfied or gate.stopped:
            break
        task_id = str(candidate["task_id"])
        if task_id != gate.next_task_id:
            raise ConfigurationError("OpenHands v19 qualification schedule changed")
        suffix = str(candidate["number"])
        source_relative = f"sources/pr-{suffix}"
        smoke_relative = f"smokes/pr-{suffix}"
        source = root / source_relative
        smoke = root / smoke_relative
        progress["active_task_id"] = task_id
        _write_progress(root, progress)

        binding: dict[str, str] | None = None
        report: dict[str, Any] | None = None
        failure: Exception | None = None
        try:
            prepare_source(
                dataset=resolved_dataset,
                output=source,
                selected_tasks=[str(candidate["instance_id"])],
                pull=False,
                official_dataset_revision=official_dataset_revision,
                official_source_commit=official_source_commit,
                verifier_cache=verifier_cache,
            )
            binding = _source_binding(source, expected_task_id=task_id)
            report = run_zero_model_smoke(source=source, output=smoke)
        except Exception as exc:
            failure = exc
            report = _load_optional_report(smoke / "smoke-report.json")

        if report is not None and zero_model_infrastructure_valid(report):
            if binding is None:
                try:
                    binding = _source_binding(source, expected_task_id=task_id)
                except Exception as exc:
                    failure = exc
            if binding is not None:
                outcome = _completed_outcome(
                    candidate=candidate,
                    binding=binding,
                    report=report,
                )
                progress["outcomes"].append(outcome)
                if zero_model_fail_to_pass_eligible(report):
                    progress["qualified_bindings"][task_id] = {
                        **binding,
                        "source": source_relative,
                        "smoke": smoke_relative,
                    }
                progress["active_task_id"] = None
                _write_progress(root, progress)
                continue

        progress["outcomes"].append(
            {
                "task_id": task_id,
                "instance_id": candidate["instance_id"],
                "changed_line_count": candidate["changed_line_count"],
                "modified_file_count": candidate["modified_file_count"],
                "infrastructure_valid": False,
                "verifier_network": "none",
                "verifier_image": binding["verifier_image"] if binding else None,
                "model_process_count": 0,
                "base_failed": False,
                "reference_passed": False,
                "status": "infrastructure_invalid",
                "failure_type": type(failure).__name__ if failure is not None else "UnknownError",
            }
        )
        progress["active_task_id"] = None
        progress["status"] = "stopped_infrastructure_invalid"
        _write_progress(root, progress)
        raise ConfigurationError(
            f"OpenHands v19 qualification stopped on infrastructure-invalid {task_id}"
        ) from failure

    gate = evaluate_v19_qualification_gate(progress["outcomes"])
    progress["active_task_id"] = None
    progress["qualified_task_ids"] = list(gate.qualified_task_ids)
    progress["training_reserve_task_ids"] = list(gate.training_reserve_task_ids)
    progress["validation_reserve_task_ids"] = list(gate.validation_reserve_task_ids)
    if gate.satisfied:
        progress["status"] = "qualified_pending_agent_images"
    else:
        progress["status"] = "stopped_insufficient_capacity"
        progress["stop_reason"] = gate.reason
    _write_progress(root, progress)
    return _sealed_progress(progress)


def _source_binding(source: Path, *, expected_task_id: str) -> dict[str, str]:
    lock_path = source / "image-lock.json"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ConfigurationError("OpenHands v19 prepared source lacks a safe image lock")
    lock = ImageLockV2.model_validate_json(lock_path.read_bytes())
    if len(lock.entries) != 1:
        raise ConfigurationError("OpenHands v19 prepared source must bind exactly one image")
    entry = lock.entries[0]
    suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=source, variant=VARIANT))
    references = list(suite.discover())
    if len(references) != 1:
        raise ConfigurationError("OpenHands v19 prepared source exposed multiple tasks")
    task = suite.load_task(references[0])
    if task.id != expected_task_id or entry.slug != references[0].native_id:
        raise ConfigurationError("OpenHands v19 prepared source task identity changed")
    if task.source.content_hash is None:
        raise ConfigurationError("OpenHands v19 prepared source lacks a source hash")
    return {
        "task_hash": content_hash(task),
        "source_hash": task.source.content_hash,
        "source_image_lock_sha256": hash_bytes(lock_path.read_bytes()),
        "verifier_image": entry.image_id,
        "verifier_manifest_digest": entry.manifest_digest,
    }


def _completed_outcome(
    *,
    candidate: dict[str, Any],
    binding: dict[str, str],
    report: dict[str, Any],
) -> dict[str, Any]:
    eligible = zero_model_fail_to_pass_eligible(report)
    return {
        "task_id": candidate["task_id"],
        "instance_id": candidate["instance_id"],
        "changed_line_count": candidate["changed_line_count"],
        "modified_file_count": candidate["modified_file_count"],
        "infrastructure_valid": True,
        "verifier_network": "none",
        "verifier_image": binding["verifier_image"],
        "model_process_count": 0,
        "base_failed": report.get("base_failed") is True,
        "reference_passed": report.get("reference_passed") is True,
        "status": "qualified" if eligible else "not_qualified",
    }


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("OpenHands v19 qualification output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _load_optional_report(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _sealed_progress(progress: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(progress)
    base.pop("progress_hash", None)
    return {**base, "progress_hash": content_hash(base)}


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "qualification-progress.json", _sealed_progress(progress))


def main() -> int:
    arguments = _parser().parse_args()
    progress = qualify_v19_public_tasks(
        dataset=arguments.dataset,
        output=arguments.output,
        verifier_cache=arguments.verifier_cache,
        official_dataset_revision=arguments.official_dataset_revision,
        official_source_commit=arguments.official_source_commit,
    )
    print(
        json.dumps(
            {
                "status": progress["status"],
                "qualified_task_ids": progress.get("qualified_task_ids", []),
                "progress_hash": progress["progress_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if progress["status"] == "qualified_pending_agent_images" else 2


if __name__ == "__main__":
    raise SystemExit(main())
