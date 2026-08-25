#!/usr/bin/env python3
"""Freeze one base/adapter K=1 heldout replay authorization without running it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

_TASK_ID = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"
_SOURCES = (
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_heldout.py",
    "scripts/run_hwe_deepseek_heldout_k1_v1.py",
    "scripts/hpc_run_hwe_deepseek_heldout_k1_v1.sh",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--adapter-report", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def authorize(
    *,
    repository_root: Path,
    adapter_report: Path,
    qualification_root: Path,
    image_lock: Path,
    output: Path,
) -> dict[str, Any]:
    """Bind public task, adapter, model, execution code, and zero-training constraints."""

    if output.exists() or output.is_symlink():
        raise ValueError("heldout authorization output already exists")
    repository = repository_root.resolve(strict=True)
    report_path = adapter_report.resolve(strict=True)
    qualification = qualification_root.resolve(strict=True)
    lock_path = image_lock.resolve(strict=True)
    report = _json(report_path)
    lock = _json(lock_path)
    progress = _json(qualification / "qualification-progress.json")
    split = _json(qualification / "task-split.json")
    if (
        report.get("status") != "passed_with_cleanup_recovery"
        or report.get("report_hash")
        != "a3a9563f54d31436f3ab4d334a1400c6c2cffefbe437d780014a76314a07b3ee"
        or report.get("adapter_artifact_hash")
        != "b051f5e3cbebac921c718884aa8190b560c8ebe63dd6f312c1aed95bde8a88bd"
        or report.get("model_identity_hash")
        != "d78dfb66d84251270506badb72fa0a3513e856ff43b6046d0d55cc810d8f6ce4"
        or report.get("optimizer_steps") != 32
    ):
        raise ValueError("adapter canary predecessor differs from its passing receipt")
    adapter_root = report_path.parent / "lora_adapter"
    from verigym_training_reference.hwe_decision_sft_64k_heldout import (
        adapter_artifact_inventory,
    )

    adapter_inventory, adapter_hash = adapter_artifact_inventory(adapter_root)
    if adapter_hash != report["adapter_artifact_hash"]:
        raise ValueError("retained adapter differs from the passing canary report")
    if progress.get("status") != "completed":
        raise ValueError("heldout qualification is incomplete")
    task_entries = [
        item
        for item in split.get("training", [])
        if isinstance(item, dict) and item.get("task_id") == _TASK_ID
    ]
    source_entries = [
        item
        for item in progress.get("training_pool", [])
        if isinstance(item, dict) and item.get("task_id") == _TASK_ID
    ]
    if len(task_entries) != 1 or len(source_entries) != 1:
        raise ValueError("heldout task is missing from the frozen qualification")
    entry = task_entries[0]
    if (
        lock.get("format_id") != "verigym_hwe_agent_image_lock_v2"
        or lock.get("task_id") != _TASK_ID
        or lock.get("task_hash") != entry.get("task_hash")
        or lock.get("source_hash") != entry.get("source_hash")
        or lock.get("security_scan_passed") is not True
        or lock.get("runtime_network") != "none"
        or lock.get("hidden_assets_present") is not False
        or lock.get("reference_patch_present") is not False
    ):
        raise ValueError("heldout image lock differs from the frozen safe task")
    sources = [_source_receipt(repository, relative) for relative in _SOURCES]
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_qwen35_64k_heldout_k1_authorization_v1",
        "status": "authorized_for_single_base_adapter_heldout_k1",
        "authorization_basis": "explicit_user_instruction_execute_heldout_native_inference",
        "task_id": _TASK_ID,
        "task_hash": entry["task_hash"],
        "source_hash": entry["source_hash"],
        "source_relative_path": source_entries[0]["source"],
        "qualification_task_split_hash": split["manifest_hash"],
        "qualification_progress_sha256": _sha256_file(
            qualification / "qualification-progress.json"
        ),
        "image_lock_hash": lock["lock_hash"],
        "image_lock_sha256": _sha256_file(lock_path),
        "runtime_network": "none",
        "policies": ["base", "adapter"],
        "samples_per_policy": 1,
        "seed": 484,
        "temperature": 0,
        "do_sample": False,
        "max_context_tokens": 65_536,
        "max_new_tokens_per_decision": 256,
        "max_decisions": 200,
        "model_identity_hash": report["model_identity_hash"],
        "dependency_wheels": [
            {
                "filename": (
                    "tiktoken-0.7.0-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
                ),
                "size_bytes": 1080830,
                "sha256": "86b6e7dc2e7ad1b3757e8a24597415bafcfb454cebf9a33a01f2e6ba2e663992",
            }
        ],
        "adapter_artifact_hash": adapter_hash,
        "adapter_artifacts": adapter_inventory,
        "adapter_predecessor_report_hash": report["report_hash"],
        "adapter_predecessor_report_sha256": _sha256_file(report_path),
        "execution_source_artifacts": sources,
        "execution_source_manifest_hash": content_hash(sources),
        "existing_lsf_job_id": "466876",
        "planned_host": "gpu03",
        "selected_gpu_indices": [0],
        "new_hpc_jobs_allowed": False,
        "release_existing_allocation": False,
        "training_allowed": False,
        "optimizer_steps_allowed": 0,
        "checkpoint_writes_allowed": False,
        "hidden_heldout_transcript_available_to_inference": False,
        "training_dataset_available_to_inference": False,
        "reference_solution_available_to_inference": False,
        "ordinary_verifier_required": True,
        "benchmark_score_claim_allowed": False,
        "quality_improvement_claim_allowed": False,
        "production_training_ready": False,
    }
    value = {**base, "authorization_hash": content_hash(base)}
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_dump_json(output, value)
    return value


def _source_receipt(repository: Path, relative: str) -> dict[str, Any]:
    path = repository / relative
    if path.is_symlink() or not path.resolve(strict=True).is_file():
        raise ValueError(f"heldout execution source is unsafe: {relative}")
    if not path.resolve(strict=True).is_relative_to(repository):
        raise ValueError(f"heldout execution source escapes repository: {relative}")
    return {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError(f"unsafe heldout JSON input: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"heldout JSON input is not an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    arguments = _parser().parse_args()
    value = authorize(
        repository_root=arguments.repository_root,
        adapter_report=arguments.adapter_report,
        qualification_root=arguments.qualification_root,
        image_lock=arguments.image_lock,
        output=arguments.output,
    )
    os.chmod(arguments.output, 0o600)
    print(value["authorization_hash"])


if __name__ == "__main__":
    main()
