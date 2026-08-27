from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from verigym.core.hashing import content_hash
from verigym.schemas.evolution import TaskSplitManifest

from verigym_openhands.hwe_sft_pilot import (
    OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS,
    OPENHANDS_BOUNDED_SFT_TRAINING_TASKS,
    OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS,
    evaluate_bounded_sft_data_gate,
    load_bounded_sft_pilot_contract,
    validate_bounded_sft_pilot_contract,
    validate_bounded_sft_source,
)


def _config_path() -> Path:
    return (
        Path(__file__).parents[3]
        / "configs"
        / "training"
        / "qwen35_hwe_openhands_bounded_sft_pilot_v1.json"
    )


def _contract() -> dict[str, Any]:
    return json.loads(_config_path().read_text(encoding="utf-8"))


def _reseal(contract: dict[str, Any]) -> None:
    contract["contract_hash"] = content_hash(
        {key: value for key, value in contract.items() if key != "contract_hash"}
    )


def _eligible(episode_id: str, task_id: str) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "task_id": task_id,
        "infrastructure_valid": True,
        "ordinary_verifier_resolved": True,
        "exact_64k_eligible": True,
        "truncation_applied": False,
    }


def test_bounded_sft_contract_freezes_16_4_6_without_leakage() -> None:
    contract = load_bounded_sft_pilot_contract(_config_path())
    collection = contract["collection"]

    assert len(collection["training_schedule"]) == 16
    assert len(collection["validation_schedule"]) == 4
    assert tuple(collection["heldout_task_ids"]) == OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS
    assert len(OPENHANDS_BOUNDED_SFT_TRAINING_TASKS) == 11
    assert len(OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS) == 2
    assert not (
        set(OPENHANDS_BOUNDED_SFT_TRAINING_TASKS) & set(OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS)
    )
    assert not (
        set(OPENHANDS_BOUNDED_SFT_TRAINING_TASKS) & set(OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS)
    )


def test_bounded_sft_contract_rejects_resealed_policy_drift() -> None:
    contract = copy.deepcopy(_contract())
    contract["teacher"]["whole_episode_retries"] = 1
    _reseal(contract)

    with pytest.raises(ValueError, match="identity changed"):
        validate_bounded_sft_pilot_contract(contract)


def test_bounded_sft_contract_rejects_heldout_collection() -> None:
    attempts = [_eligible("heldout-leak", OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS[0])]

    with pytest.raises(ValueError, match="held-out task was collected"):
        evaluate_bounded_sft_data_gate(attempts)


def test_bounded_sft_gate_requires_eight_distinct_train_and_both_validation_tasks() -> None:
    attempts = [
        _eligible(f"train-{index}", task_id)
        for index, task_id in enumerate(OPENHANDS_BOUNDED_SFT_TRAINING_TASKS[:8])
    ]
    attempts.extend(
        _eligible(f"validation-{index}", task_id)
        for index, task_id in enumerate(OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS)
    )

    gate = evaluate_bounded_sft_data_gate(attempts)

    assert gate.satisfied is True
    assert gate.eligible_training_trajectories == 8
    assert gate.distinct_training_tasks == 8
    assert gate.eligible_validation_trajectories == 2
    assert gate.distinct_validation_tasks == 2


def test_bounded_sft_gate_counts_only_fully_eligible_trajectories() -> None:
    attempts = [
        _eligible(f"train-{index}", task_id)
        for index, task_id in enumerate(OPENHANDS_BOUNDED_SFT_TRAINING_TASKS[:8])
    ]
    attempts[-1]["ordinary_verifier_resolved"] = False
    attempts.extend(
        _eligible(f"validation-{index}", task_id)
        for index, task_id in enumerate(OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS)
    )

    gate = evaluate_bounded_sft_data_gate(attempts)

    assert gate.satisfied is False
    assert gate.reason == "minimum_training_trajectories_not_met"


def test_bounded_sft_source_rejects_file_or_role_drift(tmp_path: Path) -> None:
    contract = load_bounded_sft_pilot_contract(_config_path())
    split_source = Path(
        "/data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/task-split.json"
    )
    qualification_source = Path(
        "/data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/"
        "qualification-progress.json"
    )
    if not split_source.is_file() or not qualification_source.is_file():
        pytest.skip("local frozen HWE qualification evidence is unavailable")
    split_path = tmp_path / "task-split.json"
    qualification_path = tmp_path / "qualification-progress.json"
    split_path.write_bytes(split_source.read_bytes())
    qualification_path.write_bytes(qualification_source.read_bytes())
    split = TaskSplitManifest.model_validate_json(split_path.read_bytes())

    validate_bounded_sft_source(
        contract,
        split=split,
        task_split_path=split_path,
        qualification_progress_path=qualification_path,
    )
    qualification_path.write_bytes(qualification_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="qualification progress changed"):
        validate_bounded_sft_source(
            contract,
            split=split,
            task_split_path=split_path,
            qualification_progress_path=qualification_path,
        )
