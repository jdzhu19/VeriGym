"""Offline trainer-input validation and fair two-arm handoff construction."""

from __future__ import annotations

import copy
import json
import os
import stat
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from verigym.core.hashing import content_hash
from verigym.hwe.coact import COACT_DATASET_FORMAT_ID, canonical_actions_from_messages
from verigym.hwe.nap import canonical_action_hash
from verigym.hwe.training_ready import READY_DATASET_FORMAT, load_jsonl_records
from verigym.schemas.hwe_training import (
    HweCoactDatasetManifest,
    HweCoactExample,
    HweTrainingReadyActionConditionedExample,
    HweTrainingReadyActionConditionedManifest,
)

TRAINING_HANDOFF_FORMAT = "verigym_hwe_dual_route_training_ready_handoff_v1"
SINGLE_ROUTE_TRAINING_HANDOFF_FORMAT = "verigym_hwe_single_route_training_ready_handoff_v1"
BASE_MODEL_ID = "Qwen3.5-9B"
BASE_MODEL_PATH = "/data/jzhu484/Agent/datasets/Qwen3.5-9B"
FAIR_SEED = 484
FAIR_EPOCHS = 3
FAIR_LEARNING_RATE = 1e-4
FAIR_OPTIMIZER_UPDATES = 6
FAIR_LORA_INIT = {"rank": 8, "alpha": 16, "dropout": 0.05}


@dataclass(frozen=True)
class TrainerDryRun:
    route: Literal["complexity_trap", "coact"]
    row_count: int
    supervised_message_count: int
    supervised_action_count: int
    supervised_action_hashes: tuple[str, ...]
    input_token_count: int
    supervised_token_count: int
    loss_mask_valid: bool
    dry_run_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "row_count": self.row_count,
            "supervised_message_count": self.supervised_message_count,
            "supervised_action_count": self.supervised_action_count,
            "supervised_action_hashes": list(self.supervised_action_hashes),
            "input_token_count": self.input_token_count,
            "supervised_token_count": self.supervised_token_count,
            "loss_mask_valid": self.loss_mask_valid,
            "dry_run_hash": self.dry_run_hash,
        }


@dataclass(frozen=True)
class HweTrainingInputs:
    route: Literal["complexity_trap", "coact"]
    manifest: Mapping[str, Any]
    rows: tuple[dict[str, Any], ...]
    action_hashes: tuple[str, ...]
    max_length: int


def load_training_ready_action_conditioned_dataset(root: Path) -> HweTrainingInputs:
    """Load a NAP-gated 419-row dataset and require its independent ready state."""

    directory = _safe_directory(root)
    manifest = HweTrainingReadyActionConditionedManifest.model_validate_json(
        _read_regular(directory / "dataset-manifest.json")
    ).model_dump(mode="json")
    if manifest["format_id"] != READY_DATASET_FORMAT or manifest["training_ready"] is not True:
        raise ValueError("Complexity-Trap dataset is not training-ready")
    rows = load_jsonl_records(directory / "train.jsonl")
    if len(rows) != 419:
        raise ValueError("Complexity-Trap trainer requires 419 rows")
    action_hashes: list[str] = []
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("format_id") != "verigym_hwe_training_ready_action_conditioned_sft_v1":
            raise ValueError("Complexity-Trap trainer found a foreign row format")
        validated = HweTrainingReadyActionConditionedExample.model_validate(row).model_dump(
            mode="json"
        )
        expected = validated.pop("record_hash", None)
        if not isinstance(expected, str) or content_hash(validated) != expected:
            raise ValueError("Complexity-Trap trainer row identity changed")
        validated["record_hash"] = expected
        normalized_rows.append(validated)
        row_action = {
            "name": validated.get("target_action"),
            "arguments": validated["messages"][-1]["tool_calls"][0]["function"]["arguments"],
        }
        action_hashes.append(canonical_action_hash(row_action))
    if sorted(action_hashes) != manifest["canonical_action_hashes"]:
        raise ValueError("Complexity-Trap canonical action set differs from its manifest")
    return HweTrainingInputs(
        "complexity_trap", manifest, tuple(normalized_rows), tuple(action_hashes), 32_768
    )


def load_coact_dataset(root: Path) -> HweTrainingInputs:
    """Load exactly eight complete CoACT rows with no truncation."""

    directory = _safe_directory(root)
    manifest = HweCoactDatasetManifest.model_validate_json(
        _read_regular(directory / "dataset-manifest.json")
    ).model_dump(mode="json")
    if manifest["format_id"] != COACT_DATASET_FORMAT_ID:
        raise ValueError("CoACT trainer found a foreign dataset format")
    rows = load_jsonl_records(directory / "train.jsonl")
    if len(rows) != 8:
        raise ValueError("CoACT trainer requires exactly eight rows")
    action_hashes: list[str] = []
    for row in rows:
        validated = HweCoactExample.model_validate(row).model_dump(mode="json")
        if validated["token_count"] > 65_536 or validated["truncation"] != "error":
            raise ValueError("CoACT trainer cannot accept a truncated or overlength row")
        action_hashes.extend(canonical_actions_from_messages(validated["messages"]))
    if sorted(action_hashes) != manifest["canonical_action_hashes"] or len(action_hashes) != 419:
        raise ValueError("CoACT canonical action set is incomplete or differs from its manifest")
    return HweTrainingInputs("coact", manifest, tuple(rows), tuple(action_hashes), 65_536)


def dry_run_trainer_inputs(
    inputs: HweTrainingInputs,
    *,
    token_counter: Any,
) -> TrainerDryRun:
    """Build loss masks in memory; no trainer, GPU, network, or checkpoint is touched."""

    input_tokens = 0
    supervised_tokens = 0
    supervised_messages = 0
    supervised_actions = 0
    supervised_hashes: list[str] = []
    for row in inputs.rows:
        messages = row["messages"]
        serialized = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        input_tokens += token_counter.count(serialized)
        if inputs.route == "complexity_trap":
            indices = [len(messages) - 1]
        else:
            indices = [
                index
                for index, message in enumerate(messages)
                if message.get("role") == "assistant"
            ]
        if not indices or any(messages[index].get("role") != "assistant" for index in indices):
            raise ValueError("trainer loss mask does not select assistant messages")
        supervised_messages += len(indices)
        for index in indices:
            message = messages[index]
            supervised_tokens += token_counter.count(
                json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            )
            calls = message.get("tool_calls")
            if isinstance(calls, list) and calls:
                if len(calls) != 1:
                    raise ValueError("trainer input contains a multi-action assistant message")
                function = calls[0].get("function") if isinstance(calls[0], Mapping) else None
                if not isinstance(function, Mapping):
                    raise ValueError("trainer input contains a malformed tool call")
                supervised_actions += 1
                supervised_hashes.append(
                    canonical_action_hash(
                        {"name": function.get("name"), "arguments": function.get("arguments")}
                    )
                )
    expected = Counter(inputs.action_hashes)
    observed = Counter(supervised_hashes)
    if expected != observed:
        raise ValueError("trainer supervised action set does not match the frozen 419-action set")
    payload = {
        "route": inputs.route,
        "row_count": len(inputs.rows),
        "supervised_message_count": supervised_messages,
        "supervised_action_count": supervised_actions,
        "supervised_action_hashes": sorted(supervised_hashes),
        "input_token_count": input_tokens,
        "supervised_token_count": supervised_tokens,
        "loss_mask_valid": True,
    }
    return TrainerDryRun(
        route=inputs.route,
        row_count=len(inputs.rows),
        supervised_message_count=supervised_messages,
        supervised_action_count=supervised_actions,
        supervised_action_hashes=tuple(supervised_hashes),
        input_token_count=input_tokens,
        supervised_token_count=supervised_tokens,
        loss_mask_valid=True,
        dry_run_hash=content_hash(payload),
    )


def compare_training_action_sets(
    complexity: HweTrainingInputs, coact: HweTrainingInputs
) -> dict[str, Any]:
    """Prove both arms supervise the same 419 canonical actions."""

    left = Counter(complexity.action_hashes)
    right = Counter(coact.action_hashes)
    if left != right or sum(left.values()) != 419:
        raise ValueError("HWE training arms do not contain the same 419-action multiset")
    return {
        "action_count": sum(left.values()),
        "unique_action_count": len(left),
        "complexity_action_hashes": sorted(left),
        "coact_action_hashes": sorted(right),
        "same_canonical_action_multiset": True,
        "each_action_per_epoch": True,
    }


def build_dual_route_handoff(
    complexity: HweTrainingInputs,
    coact: HweTrainingInputs,
    *,
    base_model_hash: str,
    tokenizer_hash: str,
    dry_runs: Mapping[str, TrainerDryRun],
) -> dict[str, Any]:
    """Return executable configurations while explicitly leaving execution disabled."""

    if not _is_hash(base_model_hash) or not _is_hash(tokenizer_hash):
        raise ValueError("dual-route handoff requires frozen base and tokenizer hashes")
    action_sets = compare_training_action_sets(complexity, coact)
    base = {
        "schema_version": "1.0",
        "format_id": TRAINING_HANDOFF_FORMAT,
        "model": {"id": BASE_MODEL_ID, "path": BASE_MODEL_PATH, "snapshot_hash": base_model_hash},
        "tokenizer_hash": tokenizer_hash,
        "fair_recipe": {
            "seed": FAIR_SEED,
            "epochs": FAIR_EPOCHS,
            "learning_rate": FAIR_LEARNING_RATE,
            "optimizer_updates": FAIR_OPTIMIZER_UPDATES,
            "lora_initialization": copy.deepcopy(FAIR_LORA_INIT),
            "gradient_grouping": "trajectory",
            "target_token_normalization": True,
            "report_input_tokens_flops_wall_time_separately": True,
        },
        "action_set_comparison": action_sets,
        "arms": {
            "complexity_trap": _trainer_arm(
                complexity,
                dataset_format=READY_DATASET_FORMAT,
                custom_dataset_class="VeriGymFinalAssistantHfTemplateSFTDataset",
                dry_run=dry_runs["complexity_trap"],
            ),
            "coact": _trainer_arm(
                coact,
                dataset_format=COACT_DATASET_FORMAT_ID,
                custom_dataset_class="VeriGymHfTemplateSFTDataset",
                dry_run=dry_runs["coact"],
            ),
        },
        "training_ready": True,
        "training_config_enabled": True,
        "training_started": False,
        "hpc_jobs_submitted": False,
        "heldout_evaluation_started": False,
    }
    return {**base, "handoff_hash": content_hash(base)}


def build_single_route_handoff(
    inputs: HweTrainingInputs,
    *,
    base_model_hash: str,
    tokenizer_hash: str,
    dry_run: TrainerDryRun,
    other_route_failure: str | None = None,
) -> dict[str, Any]:
    """Return a runnable handoff for one independently validated training arm.

    The dual-route comparison remains unavailable until both arms exist, but one route should
    not lose its training-ready state merely because the other route needs more inference
    resources.  This handoff keeps that distinction explicit for operators and reports.
    """

    if not _is_hash(base_model_hash) or not _is_hash(tokenizer_hash):
        raise ValueError("single-route handoff requires frozen base and tokenizer hashes")
    if len(inputs.action_hashes) != 419:
        raise ValueError("single-route handoff requires the frozen 419-action set")
    base = {
        "schema_version": "1.0",
        "format_id": SINGLE_ROUTE_TRAINING_HANDOFF_FORMAT,
        "route": inputs.route,
        "model": {"id": BASE_MODEL_ID, "path": BASE_MODEL_PATH, "snapshot_hash": base_model_hash},
        "tokenizer_hash": tokenizer_hash,
        "fair_recipe": {
            "seed": FAIR_SEED,
            "epochs": FAIR_EPOCHS,
            "learning_rate": FAIR_LEARNING_RATE,
            "optimizer_updates": FAIR_OPTIMIZER_UPDATES,
            "lora_initialization": copy.deepcopy(FAIR_LORA_INIT),
            "gradient_grouping": "trajectory",
            "target_token_normalization": True,
            "report_input_tokens_flops_wall_time_separately": True,
        },
        "frozen_action_set": {
            "action_count": len(inputs.action_hashes),
            "canonical_action_hashes": sorted(inputs.action_hashes),
            "each_action_per_epoch": True,
        },
        "arms": {
            inputs.route: _trainer_arm(
                inputs,
                dataset_format=(
                    READY_DATASET_FORMAT
                    if inputs.route == "complexity_trap"
                    else COACT_DATASET_FORMAT_ID
                ),
                custom_dataset_class=(
                    "VeriGymFinalAssistantHfTemplateSFTDataset"
                    if inputs.route == "complexity_trap"
                    else "VeriGymHfTemplateSFTDataset"
                ),
                dry_run=dry_run,
            )
        },
        "other_route_failure": other_route_failure,
        "training_ready": True,
        "training_config_enabled": True,
        "training_started": False,
        "hpc_jobs_submitted": False,
        "heldout_evaluation_started": False,
    }
    return {**base, "handoff_hash": content_hash(base)}


def _trainer_arm(
    inputs: HweTrainingInputs,
    *,
    dataset_format: str,
    custom_dataset_class: str,
    dry_run: TrainerDryRun,
) -> dict[str, Any]:
    return {
        "dataset_format": dataset_format,
        "dataset_hash": inputs.manifest.get("dataset_hash"),
        "record_count": len(inputs.rows),
        "max_length": inputs.max_length,
        "truncation": "error",
        "supervised_roles": ["assistant"],
        "custom_dataset_class": custom_dataset_class,
        "entrypoint": "rllm.AgentSFTTrainer",
        "backend": "verl",
        "epochs": FAIR_EPOCHS,
        "optimizer_updates": FAIR_OPTIMIZER_UPDATES,
        "dry_run": dry_run.as_dict(),
    }


def _safe_directory(path: Path) -> Path:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("HWE trainer dataset root must be a non-symlink directory")
    return path.resolve(strict=True)


def _read_regular(path: Path) -> str:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("HWE trainer input must be a regular file")
    return path.read_text(encoding="utf-8")


def _is_hash(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


__all__ = [
    "BASE_MODEL_ID",
    "BASE_MODEL_PATH",
    "FAIR_EPOCHS",
    "FAIR_LORA_INIT",
    "FAIR_LEARNING_RATE",
    "FAIR_OPTIMIZER_UPDATES",
    "FAIR_SEED",
    "HweTrainingInputs",
    "SINGLE_ROUTE_TRAINING_HANDOFF_FORMAT",
    "TrainerDryRun",
    "build_dual_route_handoff",
    "build_single_route_handoff",
    "compare_training_action_sets",
    "dry_run_trainer_inputs",
    "load_coact_dataset",
    "load_training_ready_action_conditioned_dataset",
]
