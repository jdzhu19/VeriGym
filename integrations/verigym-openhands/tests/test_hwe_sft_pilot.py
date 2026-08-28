from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from verigym.core.hashing import content_hash, hash_bytes
from verigym.schemas.evolution import TaskSplitManifest

from verigym_openhands.hwe_sft_pilot import (
    OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS,
    OPENHANDS_BOUNDED_SFT_TRAINING_TASKS,
    OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS,
    build_bounded_sft_agent_options,
    build_bounded_sft_agent_version,
    evaluate_bounded_sft_data_gate,
    load_bounded_sft_pilot_contract,
    load_bounded_sft_pilot_contract_v2,
    validate_bounded_sft_pilot_contract,
    validate_bounded_sft_source,
    validate_bounded_sft_source_v2,
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


def _config_v2_path() -> Path:
    return _config_path().with_name("qwen35_hwe_openhands_bounded_sft_pilot_v2.json")


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


def _locks() -> dict[str, Any]:
    tasks = (*OPENHANDS_BOUNDED_SFT_TRAINING_TASKS, *OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS)
    return {
        task_id: SimpleNamespace(
            task_id=task_id,
            lock_hash=f"{index + 1:064x}",
            derived_agent_image_id=f"sha256:{index + 101:064x}",
            verifier_base_image_id=f"sha256:{index + 201:064x}",
        )
        for index, task_id in enumerate(tasks)
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


def test_bounded_sft_v2_contract_binds_unchanged_v1_and_exact_policy_delta() -> None:
    v1_before = _config_path().read_bytes()

    contract = load_bounded_sft_pilot_contract_v2(_config_v2_path())

    assert hash_bytes(v1_before) == (
        "b75992052e85998a0f7550902302ce9c58f95b423bc821054865ef2ee0c663e8"
    )
    assert _config_path().read_bytes() == v1_before
    assert contract["format_id"] == "verigym_qwen35_hwe_openhands_bounded_sft_pilot_v2"
    assert contract["teacher"]["tool_choice_policy"] == (
        "validated_responses_recovery_state_required_tool_v12"
    )
    assert contract["verifier_replay"]["model_calls"] == 0
    assert contract["dataset"]["allowed_output_formats"][-1].endswith("_v5")
    assert contract["dataset"]["allowed_row_formats"][-1].endswith("_v5")


def test_bounded_sft_v2_contract_rejects_parent_or_delta_drift(tmp_path: Path) -> None:
    parent_path = tmp_path / _config_path().name
    parent_path.write_bytes(_config_path().read_bytes())
    overlay = json.loads(_config_v2_path().read_text(encoding="utf-8"))
    overlay["teacher_delta"]["sdk_stop_continuation_budget"] = 2
    overlay["contract_hash"] = content_hash(
        {key: value for key, value in overlay.items() if key != "contract_hash"}
    )
    overlay_path = tmp_path / _config_v2_path().name
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")

    with pytest.raises(ValueError, match="identity changed"):
        load_bounded_sft_pilot_contract_v2(overlay_path)


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


def test_bounded_sft_agent_version_binds_all_train_and_validation_images() -> None:
    version = build_bounded_sft_agent_version(source_commit="a" * 40, image_locks=_locks())

    assert version.agent_version_id == ("openhands-deepseek-v4-flash-hwe-bounded-sft-pilot-v2")
    assert set(version.image_hashes) == {
        "bounded_sft_agent_image_set",
        "bounded_sft_verifier_image_set",
    }
    assert version.training_dataset_hash is None
    assert version.model_weights_modified is False

    changed_locks = _locks()
    changed_locks[OPENHANDS_BOUNDED_SFT_TRAINING_TASKS[0]].derived_agent_image_id = (
        "sha256:" + "f" * 64
    )
    changed = build_bounded_sft_agent_version(
        source_commit="a" * 40,
        image_locks=changed_locks,
    )
    assert changed.version_hash != version.version_hash

    locks = _locks()
    locks.pop(OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS[-1])
    with pytest.raises(ValueError, match="every train/validation image lock"):
        build_bounded_sft_agent_version(source_commit="a" * 40, image_locks=locks)


def test_bounded_sft_agent_options_fit_core_plugin_bounds() -> None:
    version = build_bounded_sft_agent_version(source_commit="a" * 40, image_locks=_locks())

    options = build_bounded_sft_agent_options(seed=484, agent_version=version)

    manifest = options["agent_version_manifest_json"]
    assert isinstance(manifest, str)
    assert len(manifest.encode("utf-8")) <= 4096
    assert options["agent_version_hash"] == version.version_hash
    assert options["tool_choice_policy"] == ("validated_responses_recovery_state_required_tool_v12")


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
    validate_bounded_sft_source_v2(
        load_bounded_sft_pilot_contract_v2(_config_v2_path()),
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


def test_bounded_sft_collector_has_no_training_gpu_or_heldout_execution_path() -> None:
    source = (
        Path(__file__).parents[3] / "scripts" / "collect_cva6_hwe_openhands_bounded_sft.py"
    ).read_text(encoding="utf-8")

    assert '"whole_episode_retries": 0' in source
    assert '"provider_request_retries": 0' in source
    assert '"optimizer_steps": 0' in source
    assert '"new_hpc_jobs_submitted": False' in source
    assert '"heldout_episodes_collected": 0' in source
    assert "dry_run_decision_record_v4" in source
    assert "optimizer.step" not in source
    assert "bsub" not in source
