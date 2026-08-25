"""Fail-closed preregistration for the 64K DeepSeek Harness development canary."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.schemas.hwe import (
    HweDeepSeekHarnessDecisionSftDatasetManifestV4,
    HweDeepSeekHarnessDecisionSftExampleV4,
)
from verigym.schemas.hwe_training import (
    HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
    HweDecisionSft64kDevelopmentTrainingPreregistration,
    HweDecisionSft64kDevelopmentTrainingPreregistrationReceipt,
    HweFrozenArtifactIdentity,
)

_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_DATASET_BYTES = 16 * 1024 * 1024
_EXPECTED_QUALIFICATION_PATHS = (
    "checkpoint-resume-qualification-summary.json",
    "execution-checkpoint-resume-report.json",
    "security-scan.json",
)
_EXECUTION_SOURCE_PATHS = (
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_development_canary.py",
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_development_canary_entry.py",
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_development_training.py",
    "scripts/run_hwe_deepseek_development_canary_v1.py",
)


def load_development_training_preregistration(
    path: Path,
) -> HweDecisionSft64kDevelopmentTrainingPreregistration:
    """Load one strict recipe without accepting symlinks or extra fields."""

    payload = _read_regular(path, max_bytes=_MAX_CONFIG_BYTES)
    return HweDecisionSft64kDevelopmentTrainingPreregistration.model_validate_json(payload)


def validate_development_training_preregistration(
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    *,
    config_path: Path,
    dataset_root: Path,
    model_root: Path,
    repository_root: Path,
    qualification_root: Path,
) -> HweDecisionSft64kDevelopmentTrainingPreregistrationReceipt:
    """Validate dataset, split, model, sources, and qualification without starting training."""

    config_payload = _read_regular(config_path, max_bytes=_MAX_CONFIG_BYTES)
    reparsed = HweDecisionSft64kDevelopmentTrainingPreregistration.model_validate_json(
        config_payload
    )
    if reparsed != preregistration:
        raise ValueError("development recipe object differs from its config bytes")

    dataset = _safe_directory(dataset_root, label="64K v4 dataset")
    model = _safe_directory(model_root, label="Qwen3.5 model")
    repository = _safe_directory(repository_root, label="VeriGym repository")
    qualification = _safe_directory(qualification_root, label="checkpoint/resume qualification")

    rows = _validate_dataset(preregistration, dataset=dataset)
    _validate_split_and_schedule(preregistration, rows=rows)
    _validate_artifacts(model, preregistration.model.artifacts, label="model")
    _validate_artifacts(repository, preregistration.sources.artifacts, label="source")
    qualification_payloads = _validate_artifacts(
        qualification,
        preregistration.qualification_artifacts,
        label="qualification",
        return_payloads=True,
    )
    _validate_qualification(qualification_payloads)

    receipt_base = {
        "schema_version": "1.0",
        "format_id": (
            "verigym_hwe_decision_sft_64k_development_training_preregistration_receipt_v1"
        ),
        "status": "preregistered_not_authorized",
        "campaign_id": preregistration.campaign_id,
        "recipe_hash": preregistration.recipe_hash,
        "config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "source_v4_dataset_hash": preregistration.source_v4_dataset_hash,
        "model_identity_hash": preregistration.model.model_identity_hash,
        "source_identity_hash": preregistration.sources.source_identity_hash,
        "split_hash": preregistration.split.split_hash,
        "canary_schedule_hash": preregistration.canary.schedule_hash,
        "train_record_count": 62,
        "heldout_record_count": 21,
        "whole_trajectory_leakage_check": "passed",
        "qualification_evidence_check": "passed",
        "model_artifact_check": "passed",
        "source_artifact_check": "passed",
        "canary_execution_authorized": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "existing_allocation_modified": False,
    }
    return HweDecisionSft64kDevelopmentTrainingPreregistrationReceipt.model_validate(
        {**receipt_base, "receipt_hash": content_hash(receipt_base)}
    )


def create_development_training_execution_authorization(
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    *,
    config_path: Path,
    preregistration_receipt_path: Path,
    dataset_root: Path,
    model_root: Path,
    repository_root: Path,
    qualification_root: Path,
) -> HweDecisionSft64kDevelopmentTrainingExecutionAuthorization:
    """Create a single-use authorization after revalidating every preregistration binding."""

    expected_receipt = validate_development_training_preregistration(
        preregistration,
        config_path=config_path,
        dataset_root=dataset_root,
        model_root=model_root,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    receipt_payload = _read_regular(
        preregistration_receipt_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    receipt_model = HweDecisionSft64kDevelopmentTrainingPreregistrationReceipt
    observed_receipt = receipt_model.model_validate_json(receipt_payload)
    if observed_receipt != expected_receipt:
        raise ValueError("development preregistration receipt differs from frozen evidence")

    repository = _safe_directory(repository_root, label="VeriGym repository")
    execution_artifacts = [_artifact_identity(repository, path) for path in _EXECUTION_SOURCE_PATHS]
    config_payload = _read_regular(config_path, max_bytes=_MAX_CONFIG_BYTES)
    authorization_base = {
        "schema_version": "1.0",
        "format_id": (
            "verigym_hwe_decision_sft_64k_development_training_execution_authorization_v1"
        ),
        "status": "authorized_for_single_32_step_canary",
        "authorization_basis": "explicit_user_instruction_authorize_32_step_canary",
        "authorization_scope": "single_preregistered_32_step_checkpoint_resume_canary",
        "recipe_hash": preregistration.recipe_hash,
        "preregistration_config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "preregistration_receipt_hash": observed_receipt.receipt_hash,
        "preregistration_receipt_sha256": hashlib.sha256(receipt_payload).hexdigest(),
        "source_v4_dataset_hash": preregistration.source_v4_dataset_hash,
        "model_identity_hash": preregistration.model.model_identity_hash,
        "source_identity_hash": preregistration.sources.source_identity_hash,
        "split_hash": preregistration.split.split_hash,
        "schedule_hash": preregistration.canary.schedule_hash,
        "execution_source_artifacts": [
            item.model_dump(mode="json") for item in execution_artifacts
        ],
        "execution_source_manifest_hash": content_hash(
            [item.model_dump(mode="json") for item in execution_artifacts]
        ),
        "optimizer_steps_authorized": 32,
        "producer_optimizer_steps": 16,
        "resumed_optimizer_steps": 16,
        "checkpoint_allowed": True,
        "checkpoint_global_step": 16,
        "checkpoint_count_allowed": 1,
        "checkpoint_save_contents": ["model", "optimizer", "extra"],
        "checkpoint_load_contents": ["model", "optimizer", "extra"],
        "heldout_evaluation_steps": [0, 16, 32],
        "heldout_evaluation_record_count": 21,
        "heldout_evaluation_forward_only": True,
        "gradient_clip_target": 1.0,
        "post_clip_global_norm_relative_tolerance": 0.015625,
        "post_clip_global_norm_acceptance_lte": 1.015625,
        "tolerance_basis": "qualified_two_bfloat16_eps_relative_rounding_margin",
        "temporary_checkpoint_deletion_required": True,
        "adapter_allowed": False,
        "offload_fallback_allowed": False,
        "new_hpc_jobs_allowed": False,
        "release_existing_allocation": False,
        "existing_lsf_job_id": preregistration.existing_lsf_job_id,
        "planned_host": preregistration.planned_host,
        "selected_gpu_indices": list(preregistration.selected_gpu_indices),
        "production_training_ready": False,
    }
    return HweDecisionSft64kDevelopmentTrainingExecutionAuthorization.model_validate(
        {**authorization_base, "authorization_hash": content_hash(authorization_base)}
    )


def load_development_training_execution_authorization(
    path: Path,
) -> HweDecisionSft64kDevelopmentTrainingExecutionAuthorization:
    """Load one strict single-use development execution authorization."""

    payload = _read_regular(path, max_bytes=_MAX_CONFIG_BYTES)
    return HweDecisionSft64kDevelopmentTrainingExecutionAuthorization.model_validate_json(payload)


def validate_development_training_execution_authorization(
    authorization: HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
    *,
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    config_path: Path,
    preregistration_receipt_path: Path,
    dataset_root: Path,
    model_root: Path,
    repository_root: Path,
    qualification_root: Path,
) -> None:
    """Reject authorization drift against evidence or execution source bytes."""

    expected = create_development_training_execution_authorization(
        preregistration,
        config_path=config_path,
        preregistration_receipt_path=preregistration_receipt_path,
        dataset_root=dataset_root,
        model_root=model_root,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    if authorization != expected:
        raise ValueError("development execution authorization changed")


def _validate_dataset(
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    *,
    dataset: Path,
) -> list[HweDeepSeekHarnessDecisionSftExampleV4]:
    manifest_payload = _read_regular(
        dataset / "dataset-manifest.json",
        max_bytes=_MAX_DATASET_BYTES,
    )
    train_payload = _read_regular(dataset / "train.jsonl", max_bytes=_MAX_DATASET_BYTES)
    if hashlib.sha256(manifest_payload).hexdigest() != preregistration.source_v4_manifest_sha256:
        raise ValueError("development source v4 manifest SHA-256 changed")
    if hashlib.sha256(train_payload).hexdigest() != preregistration.source_v4_train_jsonl_sha256:
        raise ValueError("development source v4 train JSONL SHA-256 changed")
    manifest = HweDeepSeekHarnessDecisionSftDatasetManifestV4.model_validate_json(manifest_payload)
    if manifest.dataset_hash != preregistration.source_v4_dataset_hash:
        raise ValueError("development source v4 dataset hash changed")
    if manifest.source_v3_dataset_hash != preregistration.source_v3_dataset_hash:
        raise ValueError("development source v3 binding changed")
    raw_lines = train_payload.decode("utf-8").splitlines()
    if len(raw_lines) != 83 or any(not line for line in raw_lines):
        raise ValueError("development source v4 must contain exactly 83 records")
    return [HweDeepSeekHarnessDecisionSftExampleV4.model_validate_json(line) for line in raw_lines]


def _validate_split_and_schedule(
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    *,
    rows: list[HweDeepSeekHarnessDecisionSftExampleV4],
) -> None:
    split = preregistration.split
    train_indices = split.train_record_indices
    heldout_indices = split.heldout_record_indices
    if set(train_indices).intersection(heldout_indices):
        raise ValueError("development train and held-out partitions overlap")
    if sorted([*train_indices, *heldout_indices]) != list(range(83)):
        raise ValueError("development split does not cover all v4 records exactly once")

    expected_hashes = {
        "train_record_hashes_hash": content_hash(
            [rows[index].record_hash for index in train_indices]
        ),
        "heldout_record_hashes_hash": content_hash(
            [rows[index].record_hash for index in heldout_indices]
        ),
        "train_input_ids_hashes_hash": content_hash(
            [rows[index].input_ids_sha256 for index in train_indices]
        ),
        "heldout_input_ids_hashes_hash": content_hash(
            [rows[index].input_ids_sha256 for index in heldout_indices]
        ),
        "train_loss_mask_hashes_hash": content_hash(
            [rows[index].loss_mask_sha256 for index in train_indices]
        ),
        "heldout_loss_mask_hashes_hash": content_hash(
            [rows[index].loss_mask_sha256 for index in heldout_indices]
        ),
    }
    for field, expected in expected_hashes.items():
        if getattr(split, field) != expected:
            raise ValueError(f"development split {field} changed")

    train_rows = [rows[index] for index in train_indices]
    heldout_rows = [rows[index] for index in heldout_indices]
    for field in split.leakage_keys:
        train_values = {getattr(row, field) for row in train_rows}
        heldout_values = {getattr(row, field) for row in heldout_rows}
        if train_values.intersection(heldout_values):
            raise ValueError(f"development held-out leakage detected for {field}")
    if {row.task_id for row in train_rows} != {split.train_task_id}:
        raise ValueError("development train trajectory identity changed")
    if {row.task_id for row in heldout_rows} != {split.heldout_task_id}:
        raise ValueError("development held-out trajectory identity changed")

    canary = preregistration.canary
    for index, record_hash, token_count in zip(
        canary.schedule_indices,
        canary.schedule_record_hashes,
        canary.schedule_token_counts,
        strict=True,
    ):
        if index not in train_indices:
            raise ValueError("development canary selected a held-out record")
        row = rows[index]
        if row.record_hash != record_hash or row.token_count != token_count:
            raise ValueError("development canary schedule receipt changed")


def _validate_artifacts(
    root: Path,
    artifacts: list[HweFrozenArtifactIdentity],
    *,
    label: str,
    return_payloads: bool = False,
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for artifact in artifacts:
        path = root.joinpath(*artifact.path.split("/"))
        _require_within(root, path, label=label)
        metadata = _regular_stat(path, label=f"{label} artifact")
        if metadata.st_size != artifact.size_bytes:
            raise ValueError(f"{label} artifact size changed: {artifact.path}")
        digest, payload = _hash_regular(path, capture=return_payloads)
        if digest != artifact.sha256:
            raise ValueError(f"{label} artifact SHA-256 changed: {artifact.path}")
        if payload is not None:
            payloads[artifact.path] = payload
    return payloads


def _artifact_identity(root: Path, relative_path: str) -> HweFrozenArtifactIdentity:
    path = root.joinpath(*relative_path.split("/"))
    _require_within(root, path, label="execution source")
    metadata = _regular_stat(path, label="execution source")
    digest, _ = _hash_regular(path, capture=False)
    return HweFrozenArtifactIdentity(
        path=relative_path,
        size_bytes=metadata.st_size,
        sha256=digest,
    )


def _validate_qualification(payloads: dict[str, bytes]) -> None:
    if tuple(sorted(payloads)) != _EXPECTED_QUALIFICATION_PATHS:
        raise ValueError("development qualification artifact set changed")
    summary = _json_object(
        payloads["checkpoint-resume-qualification-summary.json"],
        label="qualification summary",
    )
    report = _json_object(
        payloads["execution-checkpoint-resume-report.json"],
        label="qualification report",
    )
    security = _json_object(payloads["security-scan.json"], label="qualification security scan")
    for value in (summary, report):
        if value.get("status") != "passed":
            raise ValueError("development qualification is not passing")
        if value.get("development_training_ready") is not True:
            raise ValueError("development qualification did not establish readiness")
        if value.get("production_training_ready") is not False:
            raise ValueError("development qualification made a production-readiness claim")
        comparison = value.get("comparison")
        if (
            not isinstance(comparison, dict)
            or not comparison
            or not all(item is True for item in comparison.values())
        ):
            raise ValueError("development qualification exact comparisons changed")
    if report.get("checkpoint_resume_ready") is not True:
        raise ValueError("development qualification lacks checkpoint/resume readiness")
    if report.get("temporary_checkpoint_deleted_after_validation") is not True:
        raise ValueError("development qualification retained its temporary checkpoint")
    if report.get("adapter_written") is not False:
        raise ValueError("development qualification unexpectedly wrote an adapter")
    if (
        security.get("gate") != "pass"
        or security.get("hard_secret_leak_count") != 0
        or security.get("scanner_error_count") != 0
        or security.get("proxy_values_persisted_or_hashed") is not False
    ):
        raise ValueError("development qualification security evidence is not clean")


def _safe_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    metadata = path.stat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a directory")
    return path.resolve(strict=True)


def _require_within(root: Path, path: Path, *, label: str) -> None:
    resolved_parent = path.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} artifact escapes its root") from error
    if path.is_symlink():
        raise ValueError(f"{label} artifact must not be a symlink")


def _regular_stat(path: Path, *, label: str) -> os.stat_result:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular file")
    return metadata


def _read_regular(path: Path, *, max_bytes: int) -> bytes:
    metadata = _regular_stat(path, label=str(path))
    if metadata.st_size > max_bytes:
        raise ValueError(f"{path} exceeds the allowed size")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if opened.st_dev != metadata.st_dev or opened.st_ino != metadata.st_ino:
            raise ValueError(f"{path} changed while opening")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining and (chunk := os.read(descriptor, min(1024 * 1024, remaining))):
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    if len(payload) > max_bytes:
        raise ValueError(f"{path} exceeds the allowed size")
    return payload


def _hash_regular(path: Path, *, capture: bool) -> tuple[str, bytes | None]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    captured = bytearray() if capture else None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{path} must be a regular file")
        while chunk := os.read(descriptor, 8 * 1024 * 1024):
            digest.update(chunk)
            if captured is not None:
                captured.extend(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), bytes(captured) if captured is not None else None


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


__all__ = [
    "create_development_training_execution_authorization",
    "load_development_training_preregistration",
    "load_development_training_execution_authorization",
    "validate_development_training_execution_authorization",
    "validate_development_training_preregistration",
]
