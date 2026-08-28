from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from verigym.evolution.memory import validate_agent_version

from verigym_openhands.hwe_v17_collection import (
    OPENHANDS_V17_ALL_COLLECTION_TASKS,
    OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
    OPENHANDS_V17_COLLECTION_SEED,
    OPENHANDS_V17_FORMAL_TRAINING_ORDER,
    OPENHANDS_V17_FORMAL_VALIDATION_ORDER,
    OPENHANDS_V17_IDENTITY_TASKS,
    OPENHANDS_V17_IMPORTED_TRAINING_TASKS,
    build_v17_collection_agent_options,
    build_v17_collection_agent_version,
    evaluate_v17_collection_gate,
    load_v17_collection_contract,
)


@dataclass(frozen=True)
class _Lock:
    task_id: str
    task_hash: str
    source_hash: str
    lock_hash: str
    derived_agent_image_id: str
    verifier_base_image_id: str
    runtime_network: str = "none"
    hidden_assets_present: bool = False
    reference_patch_present: bool = False
    provider_credentials_present: bool = False
    verifier_payload_present: bool = False
    security_scan_passed: bool = True


def _contract_path() -> Path:
    return (
        Path(__file__).parents[3]
        / "configs"
        / "training"
        / "qwen35_hwe_openhands_v17_collection_v1.json"
    )


def _locks() -> dict[str, _Lock]:
    contract = load_v17_collection_contract(_contract_path())
    return {
        task_id: _Lock(
            task_id=task_id,
            task_hash=binding["task_hash"],
            source_hash=binding["source_hash"],
            lock_hash=binding["image_lock_hash"],
            derived_agent_image_id=binding["agent_image"],
            verifier_base_image_id=binding["verifier_image"],
        )
        for task_id, binding in contract["task_bindings"].items()
    }


def _attempt(task_id: str, role: str, *, passed: bool = True) -> dict[str, object]:
    return {
        "task_id": task_id,
        "role": role,
        "infrastructure_valid": True,
        "security_scan_passed": True,
        "truncation_applied": False,
        "ordinary_verifier_resolved": passed,
        "fresh_exact_trajectory": passed,
        "exact_64k_eligible": passed,
    }


def _imports() -> list[dict[str, object]]:
    return [_attempt(task_id, "training") for task_id in OPENHANDS_V17_IMPORTED_TRAINING_TASKS]


def test_formal_contract_is_compact_exact_and_loads_no_heldout(tmp_path: Path) -> None:
    contract = load_v17_collection_contract(_contract_path())

    assert contract["contract_hash"] == (
        "886aefb295c822554eba6fa8efb9e83a8d4da8d6812930843592048a4f2260e4"
    )
    assert contract["heldout_task_ids_loaded"] == []
    assert contract["collection"]["task_retries"] == 0
    assert contract["collection"]["provider_request_retries"] == 0
    assert tuple(contract["collection"]["training_attempt_order"]) == (
        OPENHANDS_V17_FORMAL_TRAINING_ORDER
    )
    assert tuple(contract["collection"]["validation_attempt_order"]) == (
        OPENHANDS_V17_FORMAL_VALIDATION_ORDER
    )
    assert set(contract["task_bindings"]) == set(OPENHANDS_V17_IDENTITY_TASKS)
    assert len(OPENHANDS_V17_ALL_COLLECTION_TASKS) == 11

    changed = json.loads(_contract_path().read_bytes())
    changed["formal_contract_hash"] = "0" * 64
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="identity changed"):
        load_v17_collection_contract(path)


def test_formal_agent_identity_is_distinct_and_frozen() -> None:
    version = build_v17_collection_agent_version(source_commit="a" * 40, image_locks=_locks())

    assert validate_agent_version(version) == version
    assert version.agent_version_id == OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID
    options = build_v17_collection_agent_options(
        seed=OPENHANDS_V17_COLLECTION_SEED,
        agent_version=version,
    )
    assert options["agent_version_id"] == OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID
    assert options["whole_episode_retries"] == 0
    with pytest.raises(ValueError, match="frozen identity"):
        build_v17_collection_agent_options(seed=486, agent_version=version)


def test_capacity_gate_stops_training_at_six_new_passes_then_requires_both_validation() -> None:
    attempts = _imports()
    for task_id in OPENHANDS_V17_FORMAL_TRAINING_ORDER[:6]:
        attempts.append(_attempt(task_id, "training"))
    gate = evaluate_v17_collection_gate(attempts)
    assert gate.possible is True
    assert gate.next_role == "validation"
    assert gate.training_pass_count == 8
    assert gate.remaining_training_task_count == 1

    attempts.append(_attempt(OPENHANDS_V17_FORMAL_VALIDATION_ORDER[0], "validation"))
    gate = evaluate_v17_collection_gate(attempts)
    assert gate.reason == "continue_validation"
    assert gate.maximum_validation_pass_count == 2

    attempts.append(_attempt(OPENHANDS_V17_FORMAL_VALIDATION_ORDER[1], "validation"))
    gate = evaluate_v17_collection_gate(attempts)
    assert gate.satisfied is True
    assert gate.reason == "targets_satisfied"


def test_capacity_gate_allows_one_training_failure_but_no_validation_failure() -> None:
    attempts = _imports()
    attempts.append(_attempt(OPENHANDS_V17_FORMAL_TRAINING_ORDER[0], "training", passed=False))
    gate = evaluate_v17_collection_gate(attempts)
    assert gate.possible is True
    assert gate.maximum_training_pass_count == 8

    for task_id in OPENHANDS_V17_FORMAL_TRAINING_ORDER[1:]:
        attempts.append(_attempt(task_id, "training"))
    attempts.append(_attempt(OPENHANDS_V17_FORMAL_VALIDATION_ORDER[0], "validation", passed=False))
    gate = evaluate_v17_collection_gate(attempts)
    assert gate.possible is False
    assert gate.reason == "validation_capacity_exhausted"


def test_capacity_gate_fails_closed_on_invalid_evidence() -> None:
    attempt = _imports()[0]
    attempt["security_scan_passed"] = False
    gate = evaluate_v17_collection_gate([attempt])
    assert gate.possible is False
    assert gate.reason == "infrastructure_or_security_invalid"


def test_capacity_gate_rejects_schedule_drift_and_work_after_target() -> None:
    attempts = _imports()
    with pytest.raises(ValueError, match="training order"):
        evaluate_v17_collection_gate(
            [*attempts, _attempt(OPENHANDS_V17_FORMAL_TRAINING_ORDER[1], "training")]
        )

    for task_id in OPENHANDS_V17_FORMAL_TRAINING_ORDER[:6]:
        attempts.append(_attempt(task_id, "training"))
    with pytest.raises(ValueError, match="stop target"):
        evaluate_v17_collection_gate(
            [*attempts, _attempt(OPENHANDS_V17_FORMAL_TRAINING_ORDER[6], "training")]
        )
