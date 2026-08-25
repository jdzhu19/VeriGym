#!/usr/bin/env python3
"""Recover only the final checkpoint cleanup/report after the plural-basename guard failure."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_adapter_canary import (
    load_adapter_canary_authorization,
    validate_adapter_canary_authorization,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--predecessor-execution-report", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--execution-log", type=Path, required=True)
    return parser


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError(f"recovery input is not a safe regular file: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"recovery input is not an object: {path.name}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_branch(value: dict[str, Any], *, branch: str) -> None:
    start = 1 if branch == "producer" else 17
    end = 16 if branch == "producer" else 32
    if (
        value.get("status") != "passed"
        or value.get("branch") != branch
        or value.get("start_step") != start
        or value.get("end_step") != end
        or value.get("optimizer_steps_observed") != end
        or value.get("optimizer_steps_executed_in_branch") != 16
        or value.get("loader_rows_validated") != 83
        or value.get("exact_receipts_revalidated") != 83
        or value.get("adapter_written") is not False
        or value.get("production_training_ready") is not False
    ):
        raise ValueError(f"recovery rejected the {branch} report")
    steps = value.get("step_results")
    if not isinstance(steps, list) or [item.get("step") for item in steps] != list(
        range(start, end + 1)
    ):
        raise ValueError(f"recovery rejected the {branch} schedule")
    for step in steps:
        ranks = step.get("rank_results")
        if not isinstance(ranks, list) or len(ranks) != 4:
            raise ValueError(f"recovery found incomplete {branch} rank evidence")
        for rank in ranks:
            losses = rank.get("loss_values")
            invariants = rank.get("post_step_invariants")
            if (
                not isinstance(losses, list)
                or not losses
                or not all(math.isfinite(float(loss)) and float(loss) > 0 for loss in losses)
                or not isinstance(invariants, dict)
                or not invariants
                or not all(value is True for value in invariants.values())
            ):
                raise ValueError(f"recovery found invalid {branch} loss/step evidence")


def _validate_adapter(output: Path, inference: dict[str, Any]) -> tuple[str, int]:
    adapter = output / "lora_adapter"
    if adapter.is_symlink() or not adapter.is_dir():
        raise ValueError("recovery compact adapter is unsafe")
    config = _json(adapter / "adapter_config.json")
    if (
        config.get("r") != 8
        or config.get("lora_alpha") != 16
        or float(config.get("lora_dropout", -1)) != 0.05
    ):
        raise ValueError("recovery compact adapter config changed")
    observed: list[dict[str, Any]] = []
    total = 0
    for path in sorted(adapter.rglob("*")):
        if path.is_symlink():
            raise ValueError("recovery compact adapter contains a symlink")
        if not path.is_file():
            continue
        item = {
            "path": path.relative_to(adapter).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        total += path.stat().st_size
        observed.append(item)
    if observed != inference.get("adapter_artifacts"):
        raise ValueError("recovery compact adapter inventory changed")
    artifact_hash = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if artifact_hash != inference.get("adapter_artifact_hash"):
        raise ValueError("recovery compact adapter aggregate hash changed")
    return artifact_hash, total


def _validate_and_delete_checkpoints(
    root: Path,
    *,
    output: Path,
    producer: dict[str, Any],
    resumed: dict[str, Any],
) -> tuple[int, int]:
    if root.name != "temporary-fsdp2-checkpoints" or root.parent != output:
        raise ValueError("recovery checkpoint target differs from the exact authorized path")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("recovery checkpoint target is unsafe")
    producer_manifest = producer.get("checkpoint_manifest")
    resumed_manifest = resumed.get("checkpoint_manifest")
    if not isinstance(producer_manifest, dict) or not isinstance(resumed_manifest, dict):
        raise ValueError("recovery checkpoint manifests are missing")
    producer_files = producer_manifest.get("files")
    resumed_files = resumed_manifest.get("files")
    if not isinstance(producer_files, list) or not isinstance(resumed_files, list):
        raise ValueError("recovery checkpoint manifest files are missing")
    step16 = {
        item["relative_path"]: item
        for item in producer_files
        if isinstance(item, dict)
        and str(item.get("relative_path", "")).startswith("global_step_16/")
    }
    step32 = {
        f"global_step_32/{item['relative_path']}": item
        for item in resumed_files
        if isinstance(item, dict) and isinstance(item.get("relative_path"), str)
    }
    expected = {*step16, *step32, "latest_checkpointed_iteration.txt"}
    observed: set[str] = set()
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("recovery checkpoint contains a symlink")
        if not path.is_file():
            continue
        if path.stat().st_nlink != 1 or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("recovery checkpoint contains an unsafe file")
        relative = path.relative_to(root).as_posix()
        observed.add(relative)
        total += path.stat().st_size
        if relative in step16:
            expected_item = step16[relative]
        elif relative in step32:
            expected_item = step32[relative]
        elif relative == "latest_checkpointed_iteration.txt":
            if path.read_text(encoding="utf-8").strip() != "32":
                raise ValueError("recovery checkpoint tracker changed")
            continue
        else:
            raise ValueError("recovery checkpoint contains an unexpected file")
        if path.stat().st_size != expected_item.get("size_bytes") or _sha256_file(
            path
        ) != expected_item.get("sha256"):
            raise ValueError("recovery checkpoint file identity changed")
    if observed != expected:
        raise ValueError("recovery checkpoint file set changed")
    file_count = len(observed)
    shutil.rmtree(root)
    if root.exists() or root.is_symlink():
        raise RuntimeError("recovery failed to delete the validated temporary checkpoint")
    return file_count, total


def main() -> None:
    arguments = _parser().parse_args()
    output = arguments.output_root.resolve(strict=True)
    report = output / "adapter-native-canary-report.json"
    recovery_report = output / "cleanup-recovery-report.json"
    if report.exists() or recovery_report.exists():
        raise SystemExit("recovery reports already exist")
    authorization = load_adapter_canary_authorization(arguments.authorization)
    validate_adapter_canary_authorization(
        authorization,
        config_path=arguments.config,
        preregistration_receipt_path=arguments.preregistration_receipt,
        predecessor_execution_report_path=arguments.predecessor_execution_report,
        dataset_root=arguments.dataset_root,
        model_root=arguments.model_root,
        repository_root=arguments.repository_root,
        qualification_root=arguments.qualification_root,
    )
    evidence = output / "canary-evidence"
    producer = _json(evidence / "producer-branch-report.json")
    resumed = _json(evidence / "resume-branch-report.json")
    inference = _json(evidence / "native-inference-smoke.json")
    _validate_branch(producer, branch="producer")
    _validate_branch(resumed, branch="resume")
    if producer.get("final_rank_state") != resumed.get("initial_rank_state"):
        raise ValueError("recovery fresh-resume state is not exact")
    if (
        inference.get("status") != "passed"
        or inference.get("independent_reload_passed") is not True
        or inference.get("native_tool_call_smoke_passed") is not True
        or inference.get("heldout_transcript_loaded") is not False
    ):
        raise ValueError("recovery native inference evidence is not passing")
    adapter_hash, adapter_bytes = _validate_adapter(output, inference)
    checkpoint_files, checkpoint_bytes = _validate_and_delete_checkpoints(
        arguments.checkpoint_root,
        output=output,
        producer=producer,
        resumed=resumed,
    )
    if arguments.execution_log.is_symlink() or not arguments.execution_log.is_file():
        raise ValueError("recovery execution log is unsafe")
    log_target = output / "execution.log"
    with arguments.execution_log.open("rb") as source, log_target.open("xb") as target:
        shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    os.chmod(log_target, 0o600)
    finalizer_hash = _sha256_file(Path(__file__))
    recovery_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_adapter_canary_cleanup_recovery_v1",
        "status": "passed",
        "authorization_hash": authorization.authorization_hash,
        "recovery_scope": "validate_and_delete_exact_temporary_checkpoint_then_seal_report",
        "first_error_type": "RuntimeError",
        "first_error_message": "checkpoint/resume refused to delete an unexpected path",
        "root_cause": "plural_checkpoint_basename_rejected_by_legacy_singular_guard",
        "training_rerun": False,
        "optimizer_steps_added": 0,
        "adapter_reexported": False,
        "inference_rerun": False,
        "checkpoint_files_revalidated": checkpoint_files,
        "checkpoint_bytes_deleted": checkpoint_bytes,
        "temporary_checkpoint_deleted": True,
        "compact_adapter_retained": True,
        "finalizer_sha256": finalizer_hash,
    }
    atomic_dump_json(
        recovery_report,
        {**recovery_base, "recovery_report_hash": content_hash(recovery_base)},
    )
    marker = arguments.authorization.with_name("adapter-execution-started.json")
    wall = time.time() - marker.stat().st_mtime
    gpu_seconds = 4 * (
        float(producer["execution_wall_seconds"]) + float(resumed["execution_wall_seconds"])
    ) + float(inference["wall_seconds"])
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_adapter_retention_and_native_inference_canary_v1",
        "status": "passed_with_cleanup_recovery",
        "authorization_hash": authorization.authorization_hash,
        "recipe_hash": authorization.recipe_hash,
        "source_v4_dataset_hash": authorization.source_v4_dataset_hash,
        "model_identity_hash": authorization.model_identity_hash,
        "split_hash": authorization.split_hash,
        "schedule_hash": authorization.schedule_hash,
        "optimizer_steps": 32,
        "producer_optimizer_steps": 16,
        "resumed_optimizer_steps": 16,
        "fresh_resume_exact": True,
        "loader_rows_validated_per_branch": 83,
        "exact_receipts_revalidated_per_branch": 83,
        "checkpoint_steps_written": [16, 32],
        "step_32_optimizer_or_extra_state_retained": False,
        "temporary_checkpoints_retained": False,
        "temporary_checkpoints_deleted_after_export": True,
        "cleanup_recovery_required": True,
        "cleanup_recovery_report_sha256": _sha256_file(recovery_report),
        "adapter_written": True,
        "adapter_path": "lora_adapter",
        "adapter_artifact_hash": adapter_hash,
        "adapter_size_bytes": adapter_bytes,
        "independent_reload_passed": True,
        "native_tool_call_smoke_passed": True,
        "base_tool_calls": inference["base"]["tool_calls"],
        "adapter_tool_calls": inference["adapter"]["tool_calls"],
        "base_adapter_smoke_outputs_identical": (
            inference["base"]["generated_ids_sha256"]
            == inference["adapter"]["generated_ids_sha256"]
        ),
        "heldout_base_adapter_k1_started": False,
        "heldout_base_adapter_k1_status": "separate_fail_closed_stage_pending",
        "quality_improvement_claimed": False,
        "training_started": True,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
        "offload_used": False,
        "truncation_used": False,
        "world_size": 4,
        "ulysses_sequence_parallel_size": 4,
        "selected_gpu_indices": [0, 1, 2, 3],
        "existing_lsf_job_id": "466876",
        "host": "gpu03",
        "new_hpc_jobs_submitted": False,
        "allocation_released": False,
        "peak_memory_allocated_bytes": max(
            int(producer["peak_memory_allocated_bytes"]),
            int(resumed["peak_memory_allocated_bytes"]),
            int(inference["adapter"]["peak_memory_allocated_bytes"]),
        ),
        "peak_memory_reserved_bytes": max(
            int(producer["peak_memory_reserved_bytes"]),
            int(resumed["peak_memory_reserved_bytes"]),
            int(inference["adapter"]["peak_memory_reserved_bytes"]),
        ),
        "training_branch_wall_seconds": (
            float(producer["execution_wall_seconds"]) + float(resumed["execution_wall_seconds"])
        ),
        "wall_seconds_since_authorization_consumed": wall,
        "gpu_seconds": gpu_seconds,
    }
    atomic_dump_json(report, {**base, "report_hash": content_hash(base)})
    print(json.dumps({"status": base["status"], "report_hash": content_hash(base)}))


if __name__ == "__main__":
    main()
