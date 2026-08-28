from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.external_agent import ExternalAgentAccounting

from verigym_openhands.hwe_v17_canary_v3 import (
    OPENHANDS_V17_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V17_CANARY_PR2248,
    OPENHANDS_V17_CANARY_PR2944,
    OPENHANDS_V17_CANARY_PR3168,
    OPENHANDS_V17_CANARY_PR3191,
    OPENHANDS_V17_CANARY_TASKS,
    OPENHANDS_V17_FORMAL_TRAINING_ORDER,
    OPENHANDS_V17_FORMAL_VALIDATION_ORDER,
    build_v17_canary_agent_options,
    build_v17_canary_agent_version,
    derive_v17_v3_task_split,
    evaluate_v17_canary_gate,
    load_v17_canary_contract,
    validate_v17_canary_source,
    validate_v17_canonical_tool_shape,
    validate_v17_recovery_accounting,
    validate_v17_runtime_evidence,
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
    return _root() / "configs" / "training" / "qwen35_hwe_openhands_v17_canary_v3.json"


def _locks() -> dict[str, _Lock]:
    contract = load_v17_canary_contract(_contract_path())
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


def test_v17_canary_contract_loads_exact_three_tasks_without_heldout() -> None:
    contract = load_v17_canary_contract(_contract_path())

    assert [episode["task_id"] for episode in contract["schedule"]] == list(
        OPENHANDS_V17_CANARY_TASKS
    )
    assert [episode["seed"] for episode in contract["schedule"]] == [486, 486, 486]
    assert [episode["sample_index"] for episode in contract["schedule"]] == [2, 2, 2]
    assert contract["heldout_task_ids_loaded"] == []
    assert set(contract["task_bindings"]) == set(OPENHANDS_V17_CANARY_TASKS)
    capacity = contract["formal_collection_capacity"]
    assert capacity["training_attempt_order"] == list(OPENHANDS_V17_FORMAL_TRAINING_ORDER)
    assert capacity["validation_attempt_order"] == list(OPENHANDS_V17_FORMAL_VALIDATION_ORDER)
    assert capacity["heldout_tasks_eligible"] is False


def test_v17_canary_contract_rejects_even_resealed_or_extra_task_drift(tmp_path: Path) -> None:
    changed = json.loads(_contract_path().read_bytes())
    changed["schedule"][0]["seed"] = 999
    path = tmp_path / _contract_path().name
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="identity changed"):
        load_v17_canary_contract(path)


def test_v17_canary_source_binds_frozen_public_split() -> None:
    qualification = Path("/data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1")
    split_path = qualification / "task-split.json"
    progress_path = qualification / "qualification-progress.json"
    if not split_path.is_file() or not progress_path.is_file():
        pytest.skip("local frozen HWE qualification evidence is unavailable")

    source_split = TaskSplitManifest.model_validate_json(split_path.read_bytes())
    validate_v17_canary_source(
        load_v17_canary_contract(_contract_path()),
        split=source_split,
        task_split_path=split_path,
        qualification_progress_path=progress_path,
    )
    derived = derive_v17_v3_task_split(source_split)

    assert OPENHANDS_V17_CANARY_PR3168 not in {entry.task_id for entry in derived.training}
    assert OPENHANDS_V17_CANARY_PR3168 in {entry.task_id for entry in derived.validation}
    assert derived.heldout == source_split.heldout


def test_v17_canary_agent_version_has_new_non_diagnostic_identity() -> None:
    first = build_v17_canary_agent_version(source_commit="a" * 40, image_locks=_locks())
    second = build_v17_canary_agent_version(source_commit="a" * 40, image_locks=_locks())
    options = build_v17_canary_agent_options(seed=486, agent_version=first)

    assert first == second
    assert first.agent_version_id == OPENHANDS_V17_CANARY_AGENT_VERSION_ID
    assert first.agent_version_id.endswith("-canary-v3")
    assert "diagnostic" not in first.agent_version_id
    assert first.model_weights_modified is False
    assert set(first.image_hashes) == {
        "pr2248-agent",
        "pr2248-verifier",
        "pr2944-agent",
        "pr2944-verifier",
        "pr3191-agent",
        "pr3191-verifier",
    }
    assert options["tool_choice_policy"].endswith("_v18")
    assert options["whole_episode_retries"] == 0
    assert options["temperature"] == 0


def test_v17_canary_agent_version_rejects_missing_or_drifted_lock() -> None:
    locks = _locks()
    locks.pop(OPENHANDS_V17_CANARY_PR3191)
    with pytest.raises(ValueError, match="exactly three"):
        build_v17_canary_agent_version(source_commit="a" * 40, image_locks=locks)

    locks = _locks()
    changed = locks[OPENHANDS_V17_CANARY_PR2944]
    locks[OPENHANDS_V17_CANARY_PR2944] = _Lock(**{**changed.__dict__, "lock_hash": "f" * 64})
    with pytest.raises(ValueError, match="binding changed"):
        build_v17_canary_agent_version(source_commit="a" * 40, image_locks=locks)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((0, 0, 0, 0, 0, 0, 0, 0, 0, 0), "direct"),
        ((1, 1, 0, 1, 1, 1, 1, 0, 0, 0), "validated_required_tool_continuation"),
        ((0, 0, 0, 0, 0, 0, 0, 1, 1, 1), "validated_path_policy_recovery"),
        (
            (1, 1, 0, 1, 0, 0, 0, 1, 1, 1),
            "validated_format_and_path_policy_recovery",
        ),
        (
            (1, 1, 0, 1, 1, 1, 1, 1, 1, 1),
            "validated_format_continuation_and_path_policy_recovery",
        ),
    ],
)
def test_v17_recovery_accepts_only_frozen_states(values: tuple[int, ...], expected: str) -> None:
    names = (
        "format_recovery_count",
        "recovery_forced_request_count",
        "recovery_validated_finish_count",
        "recovery_validated_tool_count",
        "sdk_stop_continuation_count",
        "sdk_continuation_forced_request_count",
        "sdk_continuation_validated_tool_count",
        "path_policy_recovery_count",
        "path_policy_recovery_forced_request_count",
        "path_policy_recovery_validated_tool_count",
    )
    assert validate_v17_recovery_accounting(dict(zip(names, values, strict=True))) == expected


def test_v17_recovery_rejects_partial_or_finish_recovery() -> None:
    summary = {
        "format_recovery_count": 1,
        "recovery_forced_request_count": 1,
        "recovery_validated_finish_count": 1,
        "recovery_validated_tool_count": 0,
        "sdk_stop_continuation_count": 0,
        "sdk_continuation_forced_request_count": 0,
        "sdk_continuation_validated_tool_count": 0,
        "path_policy_recovery_count": 0,
        "path_policy_recovery_forced_request_count": 0,
        "path_policy_recovery_validated_tool_count": 0,
    }
    with pytest.raises(ValueError, match="escaped"):
        validate_v17_recovery_accounting(summary)


def test_v17_canary_requires_one_canonical_tool_in_each_recovery_receipt() -> None:
    receipt = {
        "raw_output_count": 1,
        "raw_output_types": ["function_call"],
        "raw_function_names": ["read_file"],
        "converted_tool_call_count": 1,
        "converted_tool_names": ["read_file"],
        "converted_text_part_count": 0,
    }
    validate_v17_canonical_tool_shape(receipt, label="test")

    receipt["converted_tool_names"] = ["python"]
    with pytest.raises(ValueError, match="canonical tool receipt changed"):
        validate_v17_canonical_tool_shape(receipt, label="test")


def test_v17_runtime_evidence_accepts_only_sanitized_exact_path_recovery() -> None:
    shape = {
        "raw_output_count": 1,
        "raw_output_types": ["function_call"],
        "raw_function_names": ["read_file"],
        "converted_tool_call_count": 1,
        "converted_tool_names": ["read_file"],
        "converted_text_part_count": 0,
    }
    accounting = ExternalAgentAccounting(
        process_wall_time_s=1.0,
        cli_event_count=0,
        model_call_count=2,
        external_tool_call_count=1,
        external_command_count=0,
        public_test_invocation_count=0,
        external_file_read_count=1,
        external_file_write_count=0,
        external_patch_count=0,
        input_tokens=10,
        output_tokens=2,
        total_tokens=12,
    )
    broker = {
        "finished": True,
        "tool_calls": 1,
        "command_calls": 0,
        "file_reads": 1,
        "patches": 0,
        "infrastructure_failure": None,
        "policy_failure": None,
        "rejection_codes": [],
        "rejected_calls": 0,
        "raw_audit_manifest": {"secret_scan": "passed"},
    }
    summary = {
        "provider_call_count": 2,
        "successful_provider_response_count": 2,
        "provider_usage_record_count": 2,
        "provider_input_tokens": 10,
        "provider_output_tokens": 2,
        "tool_choice_policy": "validated_responses_recovery_state_required_tool_v18",
        "sdk_version": "1.42.1",
        "whole_episode_retries": 0,
        "default_tools_exposed": False,
        "docker_socket_exposed_to_openhands": False,
        "local_repository_exposed_to_openhands": False,
        "private_reasoning_persisted": False,
        "message_content_persisted": True,
        "event_type_counts": {"ConversationErrorEvent": 1, "InterruptEvent": 0},
        "recovery_coalesced_output_count": 0,
        "termination_authority": "broker_typed_finish",
        "ordinary_hidden_verifier_pending": True,
        "ordinary_verifier_resolved": True,
        "training_trajectory_captured": True,
        "training_trajectory_exported": True,
        "format_recovery_count": 0,
        "recovery_forced_request_count": 0,
        "recovery_validated_finish_count": 0,
        "recovery_validated_tool_count": 0,
        "sdk_stop_continuation_count": 0,
        "sdk_continuation_forced_request_count": 0,
        "sdk_continuation_validated_tool_count": 0,
        "path_policy_recovery_policy_id": "openhands_provider_path_policy_recovery_v1",
        "path_policy_recovery_budget": 1,
        "path_policy_recovery_count": 1,
        "path_policy_recovery_tool_choice_policy": "responses_required_validated_v1",
        "path_policy_recovery_forced_request_count": 1,
        "path_policy_recovery_validated_tool_count": 1,
        "raw_rejected_provider_arguments_persisted": False,
        "recovery_response_shape": {},
        "sdk_continuation_response_shape": {},
        "path_policy_recovery_response_shape": shape,
    }

    assert (
        validate_v17_runtime_evidence(
            broker,
            summary,
            accounting,
            verifier_resolved=True,
        )
        == "validated_path_policy_recovery"
    )

    changed = {**summary, "raw_rejected_provider_arguments_persisted": True}
    with pytest.raises(ValueError, match="path-policy recovery evidence"):
        validate_v17_runtime_evidence(
            broker,
            changed,
            accounting,
            verifier_resolved=True,
        )


def test_v17_canary_gate_uses_frozen_non_heldout_validation_reserve() -> None:
    passed = evaluate_v17_canary_gate(
        [
            _attempt(OPENHANDS_V17_CANARY_PR2944, resolved=True),
            _attempt(OPENHANDS_V17_CANARY_PR2248, resolved=False),
            _attempt(OPENHANDS_V17_CANARY_PR3191, resolved=True),
        ]
    )
    reserve_required = evaluate_v17_canary_gate(
        [
            _attempt(OPENHANDS_V17_CANARY_PR2944, resolved=True),
            _attempt(OPENHANDS_V17_CANARY_PR2248, resolved=True),
            _attempt(OPENHANDS_V17_CANARY_PR3191, resolved=False),
        ]
    )

    assert passed.canary_passed is True
    assert passed.formal_collection_allowed is True
    assert passed.maximum_training_pass_count == 8
    assert passed.maximum_validation_pass_count == 3
    assert reserve_required.canary_passed is True
    assert reserve_required.pr3191_passed is False
    assert reserve_required.validation_capacity_sufficient is True
    assert reserve_required.maximum_validation_pass_count == 2
    assert reserve_required.formal_collection_allowed is True
    assert reserve_required.reason is None


def test_v17_canary_gate_fails_closed_on_invalid_evidence() -> None:
    attempts = [
        _attempt(OPENHANDS_V17_CANARY_PR2944, resolved=True),
        _attempt(OPENHANDS_V17_CANARY_PR2248, resolved=True),
        _attempt(OPENHANDS_V17_CANARY_PR3191, resolved=True),
    ]
    attempts[1]["security_scan_passed"] = False

    gate = evaluate_v17_canary_gate(attempts)

    assert gate.canary_passed is False
    assert gate.formal_collection_allowed is False
    assert gate.reason == "invalid_attempt_evidence"


def test_v17_canary_runner_has_no_gpu_or_heldout_execution_path() -> None:
    source = (_root() / "scripts" / "collect_cva6_hwe_openhands_v17_canary_v3.py").read_text(
        encoding="utf-8"
    )

    assert '"whole_episode_retries": 0' in source
    assert '"provider_request_retries": 0' in source
    assert '"heldout_task_ids_loaded": []' in source
    assert '"optimizer_steps": 0' in source
    assert "optimizer.step" not in source
    assert "bsub" not in source
    assert source.index("atomic_dump_json(scans") < source.index("require_security_scan_pass(scan)")
