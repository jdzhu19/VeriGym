#!/usr/bin/env python3
"""Freeze one adapter-only replay after an infrastructure-invalid heldout attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from verigym_training_reference.hwe_decision_sft_64k_heldout import (
    adapter_artifact_inventory,
)

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

_TASK_ID = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"
_SOURCES = (
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_heldout.py",
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_native_inference.py",
    "integrations/verigym-hwe-bench/src/verigym_hwe_bench/docker_verifier.py",
    "scripts/run_hwe_deepseek_heldout_k1_v1.py",
    "scripts/run_hwe_deepseek_heldout_adapter_recovery_v1.py",
    "scripts/hpc_run_hwe_deepseek_heldout_adapter_recovery_v1.sh",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--adapter-report", type=Path, required=True)
    parser.add_argument("--prior-heldout-report", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def authorize(
    *,
    repository_root: Path,
    adapter_report: Path,
    prior_heldout_report: Path,
    qualification_root: Path,
    image_lock: Path,
    output: Path,
) -> dict[str, Any]:
    """Bind the prior invalid attempt, four-GPU probe, sources, and zero-training scope."""

    if output.exists() or output.is_symlink():
        raise ValueError("heldout adapter recovery authorization output already exists")
    repository = repository_root.resolve(strict=True)
    adapter_report_path = adapter_report.resolve(strict=True)
    prior_path = prior_heldout_report.resolve(strict=True)
    qualification = qualification_root.resolve(strict=True)
    lock_path = image_lock.resolve(strict=True)
    report = _json(adapter_report_path)
    prior = _json(prior_path)
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
    adapter_root = adapter_report_path.parent / "lora_adapter"
    adapter_inventory, adapter_hash = adapter_artifact_inventory(adapter_root)
    if adapter_hash != report["adapter_artifact_hash"]:
        raise ValueError("retained adapter differs from the passing canary report")
    _validate_prior(prior, prior_path)
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
    prior_evidence_path = prior_path.parent / (
        "runs/cva6-hwe-qwen35-sft-heldout-k1-v1-adapter-k1/"
        "artifacts/deepseek_harness/heldout-native-inference.json"
    )
    prior_evidence = _json(prior_evidence_path)
    if (
        prior_evidence.get("status") != "infrastructure_invalid"
        or prior_evidence.get("failure_message_sanitized") != "CUDA driver error: invalid argument"
        or prior_evidence.get("model_generate_calls") != 86
        or prior_evidence.get("raw_model_text_persisted") is not False
        or prior_evidence.get("evidence_hash")
        != prior["attempts"][1]["model_episode_evidence_hash"]
    ):
        raise ValueError("prior adapter infrastructure evidence changed")
    sources = [_source_receipt(repository, relative) for relative in _SOURCES]
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_qwen35_64k_heldout_adapter_recovery_authorization_v1",
        "status": "authorized_for_single_adapter_infrastructure_recovery_k1",
        "authorization_basis": "explicit_user_instruction_execute_heldout_native_inference",
        "recovery_reason": "prior_adapter_attempt_was_infrastructure_invalid",
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
        "policies": ["adapter"],
        "samples_per_policy": 1,
        "base_sample_reused": True,
        "base_sample_repeated": False,
        "prior_invalid_attempt_excluded_from_quality": True,
        "seed": 484,
        "temperature": 0,
        "do_sample": False,
        "max_context_tokens": 65_536,
        "max_new_tokens_per_decision": 256,
        "max_decisions": 200,
        "model_identity_hash": report["model_identity_hash"],
        "adapter_artifact_hash": adapter_hash,
        "adapter_artifacts": adapter_inventory,
        "adapter_predecessor_report_hash": report["report_hash"],
        "adapter_predecessor_report_sha256": _sha256_file(adapter_report_path),
        "prior_heldout_report_hash": prior["report_hash"],
        "prior_heldout_report_sha256": _sha256_file(prior_path),
        "prior_base_attempt_run_hash": prior["attempts"][0]["run_hash"],
        "prior_invalid_attempt_run_hash": prior["attempts"][1]["run_hash"],
        "prior_invalid_attempt_evidence_sha256": _sha256_file(prior_evidence_path),
        "prior_invalid_attempt_model_generate_calls": 86,
        "execution_source_artifacts": sources,
        "execution_source_manifest_hash": content_hash(sources),
        "existing_lsf_job_id": "466876",
        "planned_host": "gpu03",
        "selected_gpu_indices": [0, 1, 2, 3],
        "inference_gpu_count": 4,
        "model_parallelism": "balanced_layer_sharding",
        "max_memory_per_gpu_bytes": 20 * 1024**3,
        "synthetic_context_qualification": {
            "heldout_data_loaded": False,
            "single_gpu": {
                "16384_tokens": "passed",
                "24576_tokens": "cuda_driver_invalid_argument",
            },
            "two_gpu": {"65536_tokens": "cuda_driver_invalid_argument"},
            "four_gpu": {
                "65536_tokens": "passed",
                "peak_memory_allocated_bytes": [
                    17473647104,
                    19622677504,
                    19354242048,
                    19814584320,
                ],
                "peak_memory_reserved_bytes": [
                    18022924288,
                    19987955712,
                    20323500032,
                    20166213632,
                ],
            },
        },
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


def _validate_prior(prior: dict[str, Any], path: Path) -> None:
    unsealed = {key: value for key, value in prior.items() if key != "report_hash"}
    attempts = prior.get("attempts")
    if (
        content_hash(unsealed) != prior.get("report_hash")
        or prior.get("status") != "stopped_infrastructure_invalid"
        or prior.get("optimizer_steps") != 0
        or prior.get("checkpoint_written") is not False
        or prior.get("training_dataset_loaded") is not False
        or not isinstance(attempts, list)
        or len(attempts) != 2
        or attempts[0].get("policy") != "base"
        or attempts[0].get("infrastructure_valid") is not True
        or attempts[1].get("policy") != "adapter"
        or attempts[1].get("infrastructure_valid") is not False
    ):
        raise ValueError(f"prior heldout report is not the expected invalid predecessor: {path}")


def _source_receipt(repository: Path, relative: str) -> dict[str, Any]:
    path = repository / relative
    if path.is_symlink() or not path.resolve(strict=True).is_file():
        raise ValueError(f"heldout recovery source is unsafe: {relative}")
    if not path.resolve(strict=True).is_relative_to(repository):
        raise ValueError(f"heldout recovery source escapes repository: {relative}")
    return {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError(f"unsafe heldout recovery JSON input: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"heldout recovery JSON input is not an object: {path}")
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
        prior_heldout_report=arguments.prior_heldout_report,
        qualification_root=arguments.qualification_root,
        image_lock=arguments.image_lock,
        output=arguments.output,
    )
    os.chmod(arguments.output, 0o600)
    print(value["authorization_hash"])


if __name__ == "__main__":
    main()
