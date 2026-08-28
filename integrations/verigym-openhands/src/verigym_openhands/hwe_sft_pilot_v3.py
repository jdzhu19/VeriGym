"""Fresh metadata-free v13 collection overlay for the bounded SFT pilot."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash, hash_bytes
from verigym.schemas.evolution import TaskSplitManifest

from .hwe_sft_pilot import (
    OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS,
    OPENHANDS_BOUNDED_SFT_PILOT_V2_CONTRACT_HASH,
    OPENHANDS_BOUNDED_SFT_PILOT_V3_CONTRACT_HASH,
    OPENHANDS_BOUNDED_SFT_PILOT_V3_FORMAT,
    OPENHANDS_BOUNDED_SFT_TRAINING_TASKS,
    OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS,
    _load_small_json_object,
    _regular_bytes,
    _validate_bounded_sft_source_files,
    load_bounded_sft_pilot_contract_v2,
)

OPENHANDS_BOUNDED_SFT_PILOT_V2_FILE = "qwen35_hwe_openhands_bounded_sft_pilot_v2.json"
OPENHANDS_BOUNDED_SFT_PILOT_V2_FILE_SHA256 = (
    "ec76e19015c3df3a8291d4d46dcc6bf02d155dcee05c7ece1a18f9bc4a16f765"
)


def load_bounded_sft_pilot_contract_v3(path: Path) -> dict[str, Any]:
    """Load the exact v13 policy/schedule overlay on the frozen v2 contract."""

    overlay = _load_small_json_object(path)
    if overlay != expected_bounded_sft_pilot_v3_overlay():
        raise ValueError("bounded SFT v3 pilot contract identity changed")
    parent_path = path.parent / OPENHANDS_BOUNDED_SFT_PILOT_V2_FILE
    if hash_bytes(_regular_bytes(parent_path)) != OPENHANDS_BOUNDED_SFT_PILOT_V2_FILE_SHA256:
        raise ValueError("bounded SFT v2 parent file changed")
    parent = load_bounded_sft_pilot_contract_v2(parent_path)
    merged = deepcopy(parent)
    merged["format_id"] = OPENHANDS_BOUNDED_SFT_PILOT_V3_FORMAT
    merged["contract_hash"] = OPENHANDS_BOUNDED_SFT_PILOT_V3_CONTRACT_HASH
    merged["parent"] = deepcopy(overlay["parent"])
    merged["teacher"].update(deepcopy(overlay["teacher_delta"]))
    merged["collection"].update(deepcopy(overlay["collection_delta"]))
    return validate_bounded_sft_pilot_contract_v3(merged)


def validate_bounded_sft_pilot_contract_v3(value: Mapping[str, Any]) -> dict[str, Any]:
    """Reject drift in the fresh, uniform-v13 11/3 collection contract."""

    contract = deepcopy(dict(value))
    overlay = expected_bounded_sft_pilot_v3_overlay()
    if (
        contract.get("format_id") != OPENHANDS_BOUNDED_SFT_PILOT_V3_FORMAT
        or contract.get("contract_hash") != OPENHANDS_BOUNDED_SFT_PILOT_V3_CONTRACT_HASH
        or contract.get("parent") != overlay["parent"]
    ):
        raise ValueError("bounded SFT v3 pilot contract identity changed")
    teacher = contract.get("teacher")
    collection = contract.get("collection")
    if not isinstance(teacher, dict) or not isinstance(collection, dict):
        raise ValueError("bounded SFT v3 contract sections are malformed")
    if any(teacher.get(key) != expected for key, expected in overlay["teacher_delta"].items()):
        raise ValueError("bounded SFT v3 teacher policy changed")
    if any(
        collection.get(key) != expected for key, expected in overlay["collection_delta"].items()
    ):
        raise ValueError("bounded SFT v3 collection schedule changed")
    training = collection["training_schedule"]
    validation = collection["validation_schedule"]
    if (
        [item["task_id"] for item in training] != list(OPENHANDS_BOUNDED_SFT_TRAINING_TASKS)
        or set(item["task_id"] for item in validation)
        != set(OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS)
        or any(item.get("predecessor") for item in (*training, *validation))
        or tuple(collection.get("heldout_task_ids", ())) != OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS
    ):
        raise ValueError("bounded SFT v3 role boundary changed")
    if len({item["episode_id"] for item in (*training, *validation)}) != 14:
        raise ValueError("bounded SFT v3 episode identity changed")
    return contract


def validate_bounded_sft_source_v3(
    contract: Mapping[str, Any],
    *,
    split: TaskSplitManifest,
    task_split_path: Path,
    qualification_progress_path: Path,
) -> None:
    """Bind v3 to the same frozen train/validation/held-out task split."""

    validate_bounded_sft_pilot_contract_v3(contract)
    _validate_bounded_sft_source_files(
        contract,
        split=split,
        task_split_path=task_split_path,
        qualification_progress_path=qualification_progress_path,
    )


def expected_bounded_sft_pilot_v3_overlay() -> dict[str, Any]:
    """Return the byte-content-bound v13 overlay."""

    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_BOUNDED_SFT_PILOT_V3_FORMAT,
        "parent": {
            "file": OPENHANDS_BOUNDED_SFT_PILOT_V2_FILE,
            "file_sha256": OPENHANDS_BOUNDED_SFT_PILOT_V2_FILE_SHA256,
            "contract_hash": OPENHANDS_BOUNDED_SFT_PILOT_V2_CONTRACT_HASH,
        },
        "teacher_delta": {
            "scaffold": "openhands-sdk-1.42.1-verigym-broker-v2-v13",
            "tool_choice_policy": "validated_responses_recovery_state_required_tool_v13",
            "provider_tool_schema_policy": "canonical_hwe_without_sdk_metadata_v1",
            "provider_argument_policy": ("predispatch_raw_host_path_and_sdk_metadata_reject_v1"),
            "raw_host_path_policy": "provider_predispatch_reject_training_ineligible_v2",
        },
        "collection_delta": {
            "schedule_policy": "fresh_uniform_v13_11_train_3_validation_v1",
            "scheduled_training_episodes": 11,
            "scheduled_validation_episodes": 3,
            "new_provider_episode_limit": 14,
            "predecessor_reused": False,
            "training_schedule": [
                _episode("training", task_id, seed=486, sample_index=2)
                for task_id in OPENHANDS_BOUNDED_SFT_TRAINING_TASKS
            ],
            "validation_schedule": [
                _episode(
                    "validation",
                    OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS[0],
                    seed=486,
                    sample_index=2,
                ),
                _episode(
                    "validation",
                    OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS[1],
                    seed=486,
                    sample_index=2,
                ),
                _episode(
                    "validation",
                    OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS[0],
                    seed=487,
                    sample_index=3,
                ),
            ],
        },
    }
    return {**base, "contract_hash": content_hash(base)}


def _episode(role: str, task_id: str, *, seed: int, sample_index: int) -> dict[str, Any]:
    suffix = task_id.rsplit("-", 1)[-1]
    prefix = "train" if role == "training" else role
    return {
        "episode_id": f"{prefix}-pr{suffix}-s{seed}",
        "task_id": task_id,
        "sample_index": sample_index,
        "seed": seed,
    }


__all__ = [
    "OPENHANDS_BOUNDED_SFT_PILOT_V2_FILE_SHA256",
    "expected_bounded_sft_pilot_v3_overlay",
    "load_bounded_sft_pilot_contract_v3",
    "validate_bounded_sft_pilot_contract_v3",
    "validate_bounded_sft_source_v3",
]
