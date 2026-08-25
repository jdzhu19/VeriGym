"""Sealed authorization for retaining and reloading the 32-step HWE LoRA adapter."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_development_training import (
    load_development_training_preregistration,
    validate_development_training_preregistration,
)
from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.hwe_training import HweFrozenArtifactIdentity

_HASH = re.compile(r"[0-9a-f]{64}")
_MAX_JSON_BYTES = 1024 * 1024
_EXECUTION_SOURCE_PATHS = (
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_adapter_canary.py",
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_adapter_canary_entry.py",
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_adapter_canary_training.py",
    "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_native_inference.py",
    "scripts/hpc_run_hwe_deepseek_adapter_canary_v1.sh",
    "scripts/run_hwe_deepseek_adapter_canary_v1.py",
)


class HweDecisionSft64kAdapterCanaryAuthorization(StrictModel):
    """One-use, hash-bound adapter retention and native inference authorization."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_decision_sft_64k_adapter_canary_authorization_v1"]
    status: Literal["authorized_for_single_adapter_and_inference_canary"]
    authorization_basis: Literal[
        "explicit_user_instruction_execute_adapter_retention_and_native_inference"
    ]
    authorization_scope: Literal[
        "single_32_step_adapter_export_reload_smoke_and_base_adapter_heldout_k1"
    ]
    recipe_hash: str
    preregistration_config_sha256: str
    preregistration_receipt_sha256: str
    predecessor_execution_report_sha256: str
    predecessor_execution_report_hash: str
    source_v4_dataset_hash: str
    model_identity_hash: str
    source_identity_hash: str
    split_hash: str
    schedule_hash: str
    execution_source_artifacts: list[HweFrozenArtifactIdentity] = Field(
        min_length=6,
        max_length=6,
    )
    execution_source_manifest_hash: str
    optimizer_steps_authorized: Literal[32]
    producer_optimizer_steps: Literal[16]
    resumed_optimizer_steps: Literal[16]
    checkpoint_steps_allowed: tuple[Literal[16], Literal[32]]
    step_16_checkpoint_contents: tuple[Literal["model"], Literal["optimizer"], Literal["extra"]]
    step_32_checkpoint_contents: tuple[Literal["model"]]
    compact_lora_adapter_allowed: Literal[True]
    independent_reload_required: Literal[True]
    native_tool_call_smoke_required: Literal[True]
    heldout_task_id: Literal["hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"]
    heldout_samples_per_policy: Literal[1]
    policies: tuple[Literal["base"], Literal["adapter"]]
    hidden_heldout_transcript_available_to_inference: Literal[False]
    benchmark_score_claim_allowed: Literal[False]
    production_training_ready: Literal[False]
    offload_fallback_allowed: Literal[False]
    new_hpc_jobs_allowed: Literal[False]
    release_existing_allocation: Literal[False]
    existing_lsf_job_id: Literal["466876"]
    planned_host: Literal["gpu03"]
    selected_gpu_indices: tuple[int, int, int, int]
    authorization_hash: str

    @field_validator(
        "recipe_hash",
        "preregistration_config_sha256",
        "preregistration_receipt_sha256",
        "predecessor_execution_report_sha256",
        "predecessor_execution_report_hash",
        "source_v4_dataset_hash",
        "model_identity_hash",
        "source_identity_hash",
        "split_hash",
        "schedule_hash",
        "execution_source_manifest_hash",
        "authorization_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("adapter canary identity must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        paths = [item.path for item in self.execution_source_artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("adapter canary execution sources must be sorted and unique")
        artifacts = [item.model_dump(mode="json") for item in self.execution_source_artifacts]
        if content_hash(artifacts) != self.execution_source_manifest_hash:
            raise ValueError("adapter canary execution source manifest changed")
        if self.selected_gpu_indices != (0, 1, 2, 3):
            raise ValueError("adapter canary GPU selection changed")
        if self.policies != ("base", "adapter"):
            raise ValueError("adapter canary comparison policy order changed")
        identity = self.model_dump(mode="json", exclude={"authorization_hash"})
        if content_hash(identity) != self.authorization_hash:
            raise ValueError("adapter canary authorization identity changed")
        return self


def create_adapter_canary_authorization(
    *,
    config_path: Path,
    preregistration_receipt_path: Path,
    predecessor_execution_report_path: Path,
    dataset_root: Path,
    model_root: Path,
    repository_root: Path,
    qualification_root: Path,
) -> HweDecisionSft64kAdapterCanaryAuthorization:
    """Revalidate the v1 recipe/evidence and seal the narrow successor execution."""

    preregistration = load_development_training_preregistration(config_path)
    expected_receipt = validate_development_training_preregistration(
        preregistration,
        config_path=config_path,
        dataset_root=dataset_root,
        model_root=model_root,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    receipt_payload = _read_regular(preregistration_receipt_path)
    if json.loads(receipt_payload) != expected_receipt.model_dump(mode="json"):
        raise ValueError("adapter canary preregistration receipt changed")
    predecessor_payload = _read_regular(predecessor_execution_report_path)
    predecessor = _json_object(predecessor_payload, label="predecessor report")
    predecessor_hash = content_hash(predecessor)
    if (
        predecessor.get("status") != "passed"
        or predecessor.get("optimizer_steps") != 32
        or predecessor.get("development_training_canary_passed") is not True
        or predecessor.get("checkpoint_retained") is not False
        or predecessor.get("adapter_written") is not False
        or predecessor.get("production_training_ready") is not False
    ):
        raise ValueError("adapter canary predecessor execution is not the sealed passing v1 run")
    repository = _safe_directory(repository_root, label="repository")
    artifacts = [_artifact_identity(repository, value) for value in _EXECUTION_SOURCE_PATHS]
    config_payload = _read_regular(config_path)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_decision_sft_64k_adapter_canary_authorization_v1",
        "status": "authorized_for_single_adapter_and_inference_canary",
        "authorization_basis": (
            "explicit_user_instruction_execute_adapter_retention_and_native_inference"
        ),
        "authorization_scope": (
            "single_32_step_adapter_export_reload_smoke_and_base_adapter_heldout_k1"
        ),
        "recipe_hash": preregistration.recipe_hash,
        "preregistration_config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "preregistration_receipt_sha256": hashlib.sha256(receipt_payload).hexdigest(),
        "predecessor_execution_report_sha256": hashlib.sha256(predecessor_payload).hexdigest(),
        "predecessor_execution_report_hash": predecessor_hash,
        "source_v4_dataset_hash": preregistration.source_v4_dataset_hash,
        "model_identity_hash": preregistration.model.model_identity_hash,
        "source_identity_hash": preregistration.sources.source_identity_hash,
        "split_hash": preregistration.split.split_hash,
        "schedule_hash": preregistration.canary.schedule_hash,
        "execution_source_artifacts": [item.model_dump(mode="json") for item in artifacts],
        "execution_source_manifest_hash": content_hash(
            [item.model_dump(mode="json") for item in artifacts]
        ),
        "optimizer_steps_authorized": 32,
        "producer_optimizer_steps": 16,
        "resumed_optimizer_steps": 16,
        "checkpoint_steps_allowed": [16, 32],
        "step_16_checkpoint_contents": ["model", "optimizer", "extra"],
        "step_32_checkpoint_contents": ["model"],
        "compact_lora_adapter_allowed": True,
        "independent_reload_required": True,
        "native_tool_call_smoke_required": True,
        "heldout_task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
        "heldout_samples_per_policy": 1,
        "policies": ["base", "adapter"],
        "hidden_heldout_transcript_available_to_inference": False,
        "benchmark_score_claim_allowed": False,
        "production_training_ready": False,
        "offload_fallback_allowed": False,
        "new_hpc_jobs_allowed": False,
        "release_existing_allocation": False,
        "existing_lsf_job_id": "466876",
        "planned_host": "gpu03",
        "selected_gpu_indices": [0, 1, 2, 3],
    }
    return HweDecisionSft64kAdapterCanaryAuthorization.model_validate(
        {**base, "authorization_hash": content_hash(base)}
    )


def load_adapter_canary_authorization(
    path: Path,
) -> HweDecisionSft64kAdapterCanaryAuthorization:
    return HweDecisionSft64kAdapterCanaryAuthorization.model_validate_json(_read_regular(path))


def validate_adapter_canary_authorization(
    authorization: HweDecisionSft64kAdapterCanaryAuthorization,
    **kwargs: Any,
) -> None:
    expected = create_adapter_canary_authorization(**kwargs)
    if authorization != expected:
        raise ValueError("adapter canary authorization changed")


def _artifact_identity(root: Path, relative: str) -> HweFrozenArtifactIdentity:
    normalized = PurePosixPath(relative)
    if normalized.is_absolute() or ".." in normalized.parts or str(normalized) != relative:
        raise ValueError("adapter canary execution source path is unsafe")
    path = root.joinpath(*normalized.parts)
    if path.is_symlink() or not path.is_file():
        raise ValueError("adapter canary execution source is not a regular file")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or path.stat().st_nlink != 1:
        raise ValueError("adapter canary execution source escaped its root")
    return HweFrozenArtifactIdentity(
        path=relative,
        size_bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _safe_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"adapter canary {label} cannot be a symlink")
    metadata = path.stat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"adapter canary {label} must be a directory")
    return path.resolve(strict=True)


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("adapter canary input must be a regular file")
    metadata = path.stat()
    if metadata.st_nlink != 1 or not 0 < metadata.st_size <= _MAX_JSON_BYTES:
        raise ValueError("adapter canary input size or link count is unsafe")
    return path.read_bytes()


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"adapter canary {label} must be an object")
    return value


__all__ = [
    "HweDecisionSft64kAdapterCanaryAuthorization",
    "create_adapter_canary_authorization",
    "load_adapter_canary_authorization",
    "validate_adapter_canary_authorization",
]
