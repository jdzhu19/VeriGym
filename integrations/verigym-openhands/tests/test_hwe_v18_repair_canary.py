from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from verigym.evolution.memory import validate_agent_version

from verigym_openhands.hwe_v18_repair_canary import (
    OPENHANDS_V18_REPAIR_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V18_REPAIR_CANARY_CAMPAIGN_ID,
    OPENHANDS_V18_REPAIR_CANARY_OPT_IN_ENV,
    OPENHANDS_V18_REPAIR_CANARY_PR2469,
    OPENHANDS_V18_REPAIR_CANARY_PR3204,
    OPENHANDS_V18_REPAIR_CANARY_SAMPLE_INDEX,
    OPENHANDS_V18_REPAIR_CANARY_SEED,
    OPENHANDS_V18_REPAIR_CANARY_TASKS,
    OPENHANDS_V18_REPAIR_EXCLUDED_ATTEMPTS,
    OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES,
    OPENHANDS_V18_REPAIR_REMAINING_TRAINING_ORDER,
    OPENHANDS_V18_REPAIR_REMAINING_VALIDATION_ORDER,
    build_v18_repair_canary_agent_options,
    build_v18_repair_canary_agent_version,
    evaluate_v18_repair_canary_gate,
    load_v18_repair_canary_contract,
)


@dataclass(frozen=True)
class _Lock:
    task_id: str
    task_hash: str
    source_hash: str
    lock_hash: str
    derived_agent_image_id: str
    verifier_base_image_id: str


def _root() -> Path:
    return Path(__file__).parents[3]


def _contract_path() -> Path:
    return _root() / "configs" / "training" / "qwen35_hwe_openhands_v18_repair_canary_v1.json"


def _locks() -> dict[str, _Lock]:
    contract = load_v18_repair_canary_contract(_contract_path())
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


def _attempt(task_id: str, *, resolved: bool) -> dict[str, object]:
    return {
        "task_id": task_id,
        "infrastructure_valid": True,
        "runtime_evidence_valid": True,
        "security_scan_passed": True,
        "truncation_applied": False,
        "recovery_accounting_valid": True,
        "ordinary_verifier_resolved": resolved,
        "fresh_exact_trajectory": resolved,
    }


def test_v18_contract_freezes_two_unused_tasks_and_zero_slack_capacity(
    tmp_path: Path,
) -> None:
    contract = load_v18_repair_canary_contract(_contract_path())

    assert contract["contract_hash"] == (
        "73841ad308d4db91fbe6c7190a832071bf4b94242bef01f18932e8958f4d3661"
    )
    assert [item["task_id"] for item in contract["schedule"]] == list(
        OPENHANDS_V18_REPAIR_CANARY_TASKS
    )
    assert [item["role"] for item in contract["schedule"]] == ["training", "validation"]
    assert {item["seed"] for item in contract["schedule"]} == {OPENHANDS_V18_REPAIR_CANARY_SEED}
    assert {item["sample_index"] for item in contract["schedule"]} == {
        OPENHANDS_V18_REPAIR_CANARY_SAMPLE_INDEX
    }
    capacity = contract["formal_collection_capacity"]
    assert capacity["prior_successful_training_task_ids"] == list(
        OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES
    )
    assert capacity["attempted_task_ids_excluded_from_reexecution"] == list(
        OPENHANDS_V18_REPAIR_EXCLUDED_ATTEMPTS
    )
    assert capacity["post_canary_training_attempt_order"] == list(
        OPENHANDS_V18_REPAIR_REMAINING_TRAINING_ORDER
    )
    assert capacity["post_canary_validation_attempt_order"] == list(
        OPENHANDS_V18_REPAIR_REMAINING_VALIDATION_ORDER
    )
    assert capacity["heldout_tasks_eligible"] is False
    assert contract["heldout_task_ids_loaded"] == []

    changed = json.loads(_contract_path().read_bytes())
    changed["contract_hash"] = "0" * 64
    invalid = tmp_path / _contract_path().name
    invalid.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="identity changed"):
        load_v18_repair_canary_contract(invalid)


def test_v18_agent_version_and_options_have_a_distinct_fixed_identity() -> None:
    version = build_v18_repair_canary_agent_version(
        source_commit="a" * 40,
        image_locks=_locks(),
    )

    assert validate_agent_version(version) == version
    assert version.agent_version_id == OPENHANDS_V18_REPAIR_CANARY_AGENT_VERSION_ID
    assert set(version.image_hashes) == {
        "pr2469-agent",
        "pr2469-verifier",
        "pr3204-agent",
        "pr3204-verifier",
    }
    options = build_v18_repair_canary_agent_options(
        seed=OPENHANDS_V18_REPAIR_CANARY_SEED,
        agent_version=version,
    )
    assert options["seed"] == OPENHANDS_V18_REPAIR_CANARY_SEED
    assert options["whole_episode_retries"] == 0
    assert options["agent_version_id"] == OPENHANDS_V18_REPAIR_CANARY_AGENT_VERSION_ID
    assert OPENHANDS_V18_REPAIR_CANARY_CAMPAIGN_ID.endswith("v1")
    assert OPENHANDS_V18_REPAIR_CANARY_OPT_IN_ENV.endswith("V1")
    with pytest.raises(ValueError, match="frozen identity"):
        build_v18_repair_canary_agent_options(seed=487, agent_version=version)


def test_v18_gate_requires_both_zero_slack_tasks_to_pass() -> None:
    passed = evaluate_v18_repair_canary_gate(
        [
            _attempt(OPENHANDS_V18_REPAIR_CANARY_PR2469, resolved=True),
            _attempt(OPENHANDS_V18_REPAIR_CANARY_PR3204, resolved=True),
        ]
    )
    assert passed.canary_passed is True
    assert passed.formal_collection_allowed is True
    assert passed.maximum_training_pass_count == 8
    assert passed.maximum_validation_pass_count == 2
    assert passed.reason is None

    training_failure = evaluate_v18_repair_canary_gate(
        [
            _attempt(OPENHANDS_V18_REPAIR_CANARY_PR2469, resolved=False),
            _attempt(OPENHANDS_V18_REPAIR_CANARY_PR3204, resolved=True),
        ]
    )
    assert training_failure.formal_collection_allowed is False
    assert training_failure.maximum_training_pass_count == 7
    assert training_failure.reason == "pr2469_required_pass_missing"

    validation_failure = evaluate_v18_repair_canary_gate(
        [
            _attempt(OPENHANDS_V18_REPAIR_CANARY_PR2469, resolved=True),
            _attempt(OPENHANDS_V18_REPAIR_CANARY_PR3204, resolved=False),
        ]
    )
    assert validation_failure.formal_collection_allowed is False
    assert validation_failure.maximum_validation_pass_count == 1
    assert validation_failure.reason == "pr3204_required_pass_missing"


def test_v18_gate_rejects_order_drift_and_invalid_evidence() -> None:
    with pytest.raises(ValueError, match="out of order"):
        evaluate_v18_repair_canary_gate(
            [
                _attempt(OPENHANDS_V18_REPAIR_CANARY_PR3204, resolved=True),
                _attempt(OPENHANDS_V18_REPAIR_CANARY_PR2469, resolved=True),
            ]
        )

    invalid = _attempt(OPENHANDS_V18_REPAIR_CANARY_PR2469, resolved=True)
    invalid["security_scan_passed"] = False
    gate = evaluate_v18_repair_canary_gate(
        [invalid, _attempt(OPENHANDS_V18_REPAIR_CANARY_PR3204, resolved=True)]
    )
    assert gate.formal_collection_allowed is False
    assert gate.reason == "invalid_attempt_evidence"


def test_v18_runner_installs_every_independent_policy_export() -> None:
    from scripts import collect_cva6_hwe_openhands_v18_repair_canary as runner

    runner._install_v18_policy()

    assert runner._runner.OPENHANDS_V17_CANARY_CAMPAIGN_ID == (
        OPENHANDS_V18_REPAIR_CANARY_CAMPAIGN_ID
    )
    assert runner._runner.OPENHANDS_V17_CANARY_AGENT_VERSION_ID == (
        OPENHANDS_V18_REPAIR_CANARY_AGENT_VERSION_ID
    )
    assert runner._runner.OPENHANDS_V17_CANARY_TASKS == OPENHANDS_V18_REPAIR_CANARY_TASKS
    assert runner._runner.load_v17_canary_contract is load_v18_repair_canary_contract
