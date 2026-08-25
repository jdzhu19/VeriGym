#!/usr/bin/env python3
"""Validate a completed HWE dual-route handoff without starting training."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.observation import TiktokenO200kCounter
from verigym.hwe.training import (
    compare_training_action_sets,
    dry_run_trainer_inputs,
    load_coact_dataset,
    load_training_ready_action_conditioned_dataset,
)
from verigym.hwe.training_ready import freeze_old_jsonl_identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--old-source-root",
        type=Path,
        default=Path(
            "/data/jzhu484/Agent/experiments/"
            "cva6-hwe-codex-native-shell-v2/campaign-action-conditioned-m1p1-v9-lifecycle2-1"
        ),
    )
    arguments = parser.parse_args(argv)
    report = validate(arguments.root, arguments.old_source_root)
    atomic_dump_json(arguments.root / "validation-report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0


def validate(root: Path, old_source_root: Path) -> dict[str, Any]:
    _directory(root)
    status = _read_json(root / "run-status.json")
    if status.get("training_ready") is not True or status.get("hpc_jobs_submitted") is not False:
        raise ValueError("handoff status is not training-ready and non-submitted")
    old_manifest = _read_json(old_source_root / "action-conditioned-dataset-manifest.json")
    old_identity = freeze_old_jsonl_identity(
        old_source_root / "hwe-action-conditioned-sft.jsonl", old_manifest
    )
    if _read_json(root / "old-source-identity.json") != old_identity:
        raise ValueError("historical action-conditioned identity changed")
    complexity = load_training_ready_action_conditioned_dataset(root / "complexity-trap")
    coact = load_coact_dataset(root / "coact")
    counter = TiktokenO200kCounter()
    complexity_dry_run = dry_run_trainer_inputs(complexity, token_counter=counter)
    coact_dry_run = dry_run_trainer_inputs(coact, token_counter=counter)
    actions = compare_training_action_sets(complexity, coact)
    _scan_artifacts(root)
    report_base = {
        "format_id": "verigym_hwe_dual_route_validation_report_v1",
        "training_ready": True,
        "complexity": complexity_dry_run.as_dict(),
        "coact": coact_dry_run.as_dict(),
        "action_set_comparison": actions,
        "hpc_jobs_submitted": False,
        "secret_scan": "passed",
        "artifact_scan": "passed",
    }
    return {**report_base, "report_hash": content_hash(report_base)}


def _scan_artifacts(root: Path) -> None:
    forbidden_fragments = ("sk-", "ghp_", "xoxb-", "BEGIN PRIVATE KEY")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"handoff contains a symlink: {path.name}")
        if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        if any(fragment in text for fragment in forbidden_fragments):
            raise ValueError(f"handoff contains a credential-like value: {path.name}")
        if "hpc_jobs_submitted" in text and '"hpc_jobs_submitted": true' in text.lower():
            raise ValueError(f"handoff claims an HPC submission: {path.name}")


def _directory(path: Path) -> None:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("HWE handoff root must be a non-symlink directory")


def _read_json(path: Path) -> dict[str, Any]:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"handoff artifact is not a regular file: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"handoff artifact is not an object: {path.name}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
