"""Fail-closed 64K derivation of the frozen DeepSeek Harness decision pilot."""

from __future__ import annotations

import copy
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.hwe.qwen_action_tokenizer import (
    QwenDecisionExampleTokenizer,
    dry_run_decision_record_v4,
    exact_decision_token_receipt,
)
from verigym.schemas.hwe import (
    HweDeepSeekHarnessDecisionSftDatasetManifestV3,
    HweDeepSeekHarnessDecisionSftDatasetManifestV4,
    HweDeepSeekHarnessDecisionSftExampleV3,
    HweDeepSeekHarnessDecisionSftExampleV4,
)

V3_DATASET_HASH = "b362cc1df0969f1bad368c939110175502d8ff0d97aef62c93cccd18871e351a"
V3_MANIFEST_SHA256 = "a2605512edac128e66ac0afdf07a9245098f0bdd3b07ca485defc484b3b01c46"
V3_TRAIN_JSONL_SHA256 = "1b7522c3bae396aeed4464486a3c8ba60b9b4f3fde8defa2d4903ff852618cec"
V4_RECORD_FORMAT = "verigym_hwe_deepseek_harness_decision_sft_64k_v4"
V4_DATASET_FORMAT = "verigym_hwe_deepseek_harness_decision_sft_dataset_64k_v4"
V4_MAX_LENGTH = 65_536
V4_EXPECTED_RECORDS = 83
V4_EXPECTED_TRAJECTORIES = 2
V4_EXPECTED_TOOL_ACTIONS = 85
V4_EXPECTED_MAX_TOKENS = 50_117
_MAX_SOURCE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class FrozenDecisionDatasetV3:
    """Validated source files whose bytes remain untouched by derivation."""

    root: Path
    manifest: HweDeepSeekHarnessDecisionSftDatasetManifestV3
    rows: tuple[dict[str, Any], ...]
    manifest_sha256: str
    train_jsonl_sha256: str


@dataclass(frozen=True)
class DerivedDecisionDatasetV4:
    """In-memory v4 rows and their sealed dataset receipt."""

    source: FrozenDecisionDatasetV3
    manifest: HweDeepSeekHarnessDecisionSftDatasetManifestV4
    rows: tuple[dict[str, Any], ...]
    dry_runs: tuple[dict[str, Any], ...]


def load_frozen_decision_dataset_v3(root: Path) -> FrozenDecisionDatasetV3:
    """Load only the two expected v3 files and require their qualified hashes."""

    directory = _safe_directory(root)
    manifest_payload = _read_regular(directory / "dataset-manifest.json")
    train_payload = _read_regular(directory / "train.jsonl")
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    train_sha256 = hashlib.sha256(train_payload).hexdigest()
    if manifest_sha256 != V3_MANIFEST_SHA256 or train_sha256 != V3_TRAIN_JSONL_SHA256:
        raise ValueError("DeepSeek Harness v3 source file SHA-256 changed")
    manifest = HweDeepSeekHarnessDecisionSftDatasetManifestV3.model_validate_json(manifest_payload)
    if manifest.dataset_hash != V3_DATASET_HASH:
        raise ValueError("DeepSeek Harness v3 dataset hash changed")
    raw_lines = train_payload.decode("utf-8").splitlines()
    if len(raw_lines) != V4_EXPECTED_RECORDS or any(not line for line in raw_lines):
        raise ValueError("DeepSeek Harness v3 train.jsonl row count changed")
    models = [
        HweDeepSeekHarnessDecisionSftExampleV3.model_validate_json(line) for line in raw_lines
    ]
    if [item.record_hash for item in models] != manifest.record_hashes:
        raise ValueError("DeepSeek Harness v3 record order or hash changed")
    rows = tuple(item.model_dump(mode="json") for item in models)
    return FrozenDecisionDatasetV3(
        root=directory,
        manifest=manifest,
        rows=rows,
        manifest_sha256=manifest_sha256,
        train_jsonl_sha256=train_sha256,
    )


def derive_decision_dataset_64k_v4(
    source: FrozenDecisionDatasetV3,
    *,
    tokenizer: QwenDecisionExampleTokenizer,
) -> DerivedDecisionDatasetV4:
    """Derive exact-token receipts without compressing, masking, or reordering context."""

    rows: list[dict[str, Any]] = []
    dry_runs: list[dict[str, Any]] = []
    for index, source_row in enumerate(source.rows):
        tools = copy.deepcopy(source_row["tools"])
        input_messages = copy.deepcopy(source_row["input_messages"])
        target_message = copy.deepcopy(source_row["target_message"])
        receipt = exact_decision_token_receipt(
            tokenizer=tokenizer,
            tools=tools,
            input_messages=input_messages,
            target_message=target_message,
        )
        if receipt["token_count"] != source_row["token_count"]:
            raise ValueError(f"DeepSeek Harness v3 token receipt drifted at row {index}")
        base = {
            key: copy.deepcopy(value)
            for key, value in source_row.items()
            if key not in {"format_id", "record_hash", "max_length", "eligible"}
        }
        base.update(
            {
                "format_id": V4_RECORD_FORMAT,
                "source_v3_format_id": source_row["format_id"],
                "source_v3_dataset_hash": source.manifest.dataset_hash,
                "source_v3_record_index": index,
                "source_v3_record_hash": source_row["record_hash"],
                "tools": tools,
                "tool_schema_hash": content_hash(tools),
                "input_messages": input_messages,
                "target_message": target_message,
                **receipt,
                "max_length": V4_MAX_LENGTH,
                "eligible": receipt["token_count"] <= V4_MAX_LENGTH,
            }
        )
        model = HweDeepSeekHarnessDecisionSftExampleV4.model_validate(
            {**base, "record_hash": content_hash(base)}
        )
        row = model.model_dump(mode="json")
        _assert_source_payload_unchanged(source_row, row)
        rows.append(row)
        dry_runs.append(dry_run_decision_record_v4(row, tokenizer=tokenizer))

    max_tokens = max(item["token_count"] for item in rows)
    action_count = sum(item["tool_action_count"] for item in rows)
    represented = sorted({str(item["task_id"]) for item in rows})
    if (
        len(rows) != V4_EXPECTED_RECORDS
        or len(represented) != V4_EXPECTED_TRAJECTORIES
        or action_count != V4_EXPECTED_TOOL_ACTIONS
        or max_tokens != V4_EXPECTED_MAX_TOKENS
        or any(item["eligible"] is not True for item in rows)
    ):
        raise ValueError("DeepSeek Harness v4 frozen dataset expectations changed")
    manifest_base = {
        "schema_version": "1.0",
        "format_id": V4_DATASET_FORMAT,
        "source_v3_format_id": source.manifest.format_id,
        "source_v3_dataset_hash": source.manifest.dataset_hash,
        "source_v3_manifest_sha256": source.manifest_sha256,
        "source_v3_train_jsonl_sha256": source.train_jsonl_sha256,
        "source_v3_record_hashes": list(source.manifest.record_hashes),
        "record_count": len(rows),
        "record_hashes": [str(item["record_hash"]) for item in rows],
        "pilot_task_ids": list(source.manifest.pilot_task_ids),
        "represented_task_ids": represented,
        "trajectory_count": len(represented),
        "supervised_decision_count": len(rows),
        "supervised_tool_action_count": action_count,
        "masked_policy_error_decision_count": source.manifest.masked_policy_error_decision_count,
        "masked_format_error_decision_count": source.manifest.masked_format_error_decision_count,
        "format_repair_count": source.manifest.format_repair_count,
        "max_observed_token_count": max_tokens,
        "max_length": V4_MAX_LENGTH,
        "truncation": "error",
        "overlength_records": [],
        "exact_token_receipts": True,
        "loader_ready": True,
        "nap_required": False,
        "production_training_ready": False,
        "training_started": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    manifest = HweDeepSeekHarnessDecisionSftDatasetManifestV4.model_validate(
        {**manifest_base, "dataset_hash": content_hash(manifest_base)}
    )
    return DerivedDecisionDatasetV4(
        source=source,
        manifest=manifest,
        rows=tuple(rows),
        dry_runs=tuple(dry_runs),
    )


def _assert_source_payload_unchanged(source: dict[str, Any], derived: dict[str, Any]) -> None:
    for key in ("tools", "input_messages", "target_message"):
        if source[key] != derived[key]:
            raise ValueError(f"DeepSeek Harness v4 changed source {key}")
    if source["token_count"] != derived["token_count"]:
        raise ValueError("DeepSeek Harness v4 changed the exact source token count")


def _safe_directory(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("DeepSeek Harness v3 dataset root cannot be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("DeepSeek Harness v3 dataset root must be a directory")
    return resolved


def _read_regular(path: Path) -> bytes:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"DeepSeek Harness source is not a regular file: {path.name}")
    if metadata.st_size <= 0 or metadata.st_size > _MAX_SOURCE_BYTES:
        raise ValueError(f"DeepSeek Harness source size is invalid: {path.name}")
    return path.read_bytes()


__all__ = [
    "DerivedDecisionDatasetV4",
    "FrozenDecisionDatasetV3",
    "V3_DATASET_HASH",
    "V3_MANIFEST_SHA256",
    "V3_TRAIN_JSONL_SHA256",
    "V4_DATASET_FORMAT",
    "V4_MAX_LENGTH",
    "V4_RECORD_FORMAT",
    "derive_decision_dataset_64k_v4",
    "load_frozen_decision_dataset_v3",
]
