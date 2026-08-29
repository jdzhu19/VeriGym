from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym_openhands.hwe_v19 import (
    build_v19_protocol_receipt,
    classify_v19_campaign_result,
    seal_v19_decision_receipt,
    seal_v19_trajectory_receipt,
)
from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_CANARY_VALIDATION_TASK,
    OPENHANDS_V19_FIXED_TRAINING_ORDER,
    OPENHANDS_V19_FIXED_VALIDATION_ORDER,
    OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS,
    OPENHANDS_V19_QUALIFICATION_CANDIDATES,
    build_v19_canary_contract,
    evaluate_v19_canary_gate,
    evaluate_v19_collection_gate,
    evaluate_v19_qualification_gate,
    frozen_v19_candidate_inventory,
    seal_v19_qualification_receipt,
    validate_v19_canary_contract,
)


def _patch(changed: int) -> str:
    lines = ["--- a/a.sv", "+++ b/a.sv"]
    lines.extend(f"+new_{index}" for index in range(changed))
    return "\n".join(lines)


def _dataset(path: Path) -> Path:
    counts = {2330: 4, 3226: 6, 2844: 7, 3231: 7, 2989: 8, 1482: 14, 3059: 15}
    rows = [
        {
            "org": "openhwgroup",
            "repo": "cva6",
            "number": number,
            "modified_files": ["a.sv", "b.sv"],
            "fix_patch": _patch(counts[number]),
        }
        for number in reversed(OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS)
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _outcome(
    task_id: str, *, qualified: bool = True, infrastructure: bool = True
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "infrastructure_valid": infrastructure,
        "verifier_network": "none",
        "verifier_image": "sha256:" + "a" * 64,
        "model_process_count": 0,
        "base_failed": qualified,
        "reference_passed": qualified,
    }


def _scorecard(task_id: str) -> dict[str, object]:
    return {
        "task_id": task_id,
        "run_id": "run-" + task_id.rsplit("-", 1)[-1],
        "resolved": True,
        "verifier_results": [
            {
                "status": "passed",
                "error_category": "success",
                "tests_passed": 1,
                "tests_total": 1,
            }
        ],
    }


def _result(
    task_id: str,
    *,
    admitted: bool = True,
    infrastructure: bool = True,
    security: bool = True,
) -> dict[str, object]:
    return classify_v19_campaign_result(
        _scorecard(task_id),
        agent_protocol_valid=admitted,
        trajectory_eligible=admitted,
        infrastructure_valid=infrastructure,
        security_valid=security,
        admit_to_sft=admitted,
    )


def _attempt(
    task_id: str,
    *,
    admitted: bool = True,
    infrastructure: bool = True,
    security: bool = True,
) -> dict[str, object]:
    result = _result(
        task_id,
        admitted=admitted,
        infrastructure=infrastructure,
        security=security,
    )
    attempt: dict[str, object] = {
        "task_id": task_id,
        "result": result,
        "security_scan_hash": "e" * 64 if security else None,
        "protocol_receipt": None,
        "trajectory_receipt": None,
        "decision_receipt": None,
    }
    if not admitted:
        return attempt
    protocol = build_v19_protocol_receipt(
        provider={
            "provider_call_count": 1,
            "successful_provider_response_count": 1,
            "provider_usage_record_count": 1,
            "input_tokens": 100,
            "output_tokens": 10,
        },
        protocol={
            "required_tool_request_count": 1,
            "canonical_tool_response_count": 1,
            "content_only_response_count": 0,
            "format_recovery_count": 0,
            "recovery_forced_request_count": 0,
            "recovery_validated_tool_count": 0,
            "over_budget_response_count": 0,
        },
        broker_decision_steps=1,
    )
    transcript_hash = ("a" * 63) + str(int(task_id.rsplit("-", 1)[-1]) % 10)
    trajectory = seal_v19_trajectory_receipt(
        transcript_hash=transcript_hash,
        protocol_receipt=protocol,
        campaign_result=result,
    )
    decision = seal_v19_decision_receipt(
        records=[
            {
                "record_hash": ("b" * 63) + str(int(task_id.rsplit("-", 1)[-1]) % 10),
                "transcript_hash": transcript_hash,
                "token_count": 1_024,
                "eligible": True,
                "truncation": "error",
                "input_loss_masked": True,
            }
        ],
        trajectory_receipt=trajectory,
    )
    attempt.update(
        {
            "protocol_receipt": protocol,
            "trajectory_receipt": trajectory,
            "decision_receipt": decision,
        }
    )
    return attempt


def test_v19_candidate_inventory_is_frozen_by_changed_lines_then_pr(tmp_path: Path) -> None:
    inventory = frozen_v19_candidate_inventory(_dataset(tmp_path / "cva6.jsonl"))

    assert [item["number"] for item in inventory] == list(
        OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS
    )
    assert [item["changed_line_count"] for item in inventory] == [4, 6, 7, 7, 8, 14, 15]


def test_v19_qualification_requires_five_and_assigns_three_plus_two() -> None:
    outcomes = [
        _outcome(OPENHANDS_V19_QUALIFICATION_CANDIDATES[0]),
        _outcome(OPENHANDS_V19_QUALIFICATION_CANDIDATES[1], qualified=False),
        *[_outcome(task_id) for task_id in OPENHANDS_V19_QUALIFICATION_CANDIDATES[2:6]],
    ]
    gate = evaluate_v19_qualification_gate(outcomes)

    assert gate.satisfied is True
    assert gate.stopped is True
    assert gate.training_reserve_task_ids == (
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[0],
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[2],
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[3],
    )
    assert gate.validation_reserve_task_ids == (
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[4],
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[5],
    )

    with pytest.raises(ValueError, match="continued after"):
        evaluate_v19_qualification_gate(
            [*outcomes, _outcome(OPENHANDS_V19_QUALIFICATION_CANDIDATES[6])]
        )


def test_v19_qualification_stops_immediately_on_infrastructure_invalid() -> None:
    gate = evaluate_v19_qualification_gate(
        [
            _outcome(OPENHANDS_V19_QUALIFICATION_CANDIDATES[0]),
            _outcome(OPENHANDS_V19_QUALIFICATION_CANDIDATES[1], infrastructure=False),
        ]
    )
    assert gate.satisfied is False
    assert gate.stopped is True
    assert gate.reason == "infrastructure_invalid"
    assert gate.next_task_id is None


def test_v19_qualification_receipt_builds_static_canary_contract() -> None:
    outcomes = [_outcome(task_id) for task_id in OPENHANDS_V19_QUALIFICATION_CANDIDATES[:5]]
    bindings = {
        task_id: {
            "task_hash": "a" * 64,
            "source_hash": "b" * 64,
            "image_lock_hash": "c" * 64,
            "agent_image": "sha256:" + "f" * 64,
            "verifier_image": "sha256:" + "a" * 64,
        }
        for task_id in OPENHANDS_V19_QUALIFICATION_CANDIDATES[:5]
    }
    receipt = seal_v19_qualification_receipt(outcomes, bindings=bindings)
    contract = build_v19_canary_contract(
        receipt,
        validation_binding={
            "task_hash": "1" * 64,
            "source_hash": "2" * 64,
            "image_lock_hash": "3" * 64,
            "agent_image": "sha256:" + "5" * 64,
            "verifier_image": "sha256:" + "4" * 64,
        },
    )

    assert contract["schedule"][0]["task_id"] == receipt["training_reserve_task_ids"][0]
    assert contract["schedule"][1]["task_id"] == OPENHANDS_V19_CANARY_VALIDATION_TASK
    assert contract["teacher"]["max_provider_calls"] == 64
    assert contract["teacher"]["max_provider_tokens"] == 1_000_000
    assert contract["heldout_task_ids_loaded"] == []
    assert validate_v19_canary_contract(contract) == contract

    changed = dict(contract)
    changed["qualification_receipt_hash"] = "0" * 64
    with pytest.raises(ValueError, match="identity changed"):
        validate_v19_canary_contract(changed)


def test_v19_canary_has_zero_automatic_fallback() -> None:
    training = OPENHANDS_V19_QUALIFICATION_CANDIDATES[0]
    assert evaluate_v19_canary_gate(
        [_attempt(training), _attempt(OPENHANDS_V19_CANARY_VALIDATION_TASK)],
        training_reserve_task_id=training,
    )
    assert not evaluate_v19_canary_gate(
        [
            _attempt(training, admitted=False),
            _attempt(OPENHANDS_V19_CANARY_VALIDATION_TASK),
        ],
        training_reserve_task_id=training,
    )


def test_v19_collection_stops_exactly_at_eight_plus_two() -> None:
    training_reserves = OPENHANDS_V19_QUALIFICATION_CANDIDATES[:3]
    validation_reserves = OPENHANDS_V19_QUALIFICATION_CANDIDATES[3:5]
    initial = evaluate_v19_collection_gate(
        [],
        training_reserves=training_reserves,
        validation_reserves=validation_reserves,
    )
    assert initial.training_pass_count == 4
    assert initial.validation_pass_count == 1
    assert initial.next_task_id == OPENHANDS_V19_FIXED_TRAINING_ORDER[0]

    attempts = [
        {"role": "training", **_attempt(task_id)} for task_id in OPENHANDS_V19_FIXED_TRAINING_ORDER
    ]
    training_done = evaluate_v19_collection_gate(
        attempts,
        training_reserves=training_reserves,
        validation_reserves=validation_reserves,
    )
    assert training_done.training_pass_count == 8
    assert training_done.next_role == "validation"
    assert training_done.next_task_id == OPENHANDS_V19_FIXED_VALIDATION_ORDER[0]

    complete = evaluate_v19_collection_gate(
        [
            *attempts,
            {
                "role": "validation",
                **_attempt(OPENHANDS_V19_FIXED_VALIDATION_ORDER[0]),
            },
        ],
        training_reserves=training_reserves,
        validation_reserves=validation_reserves,
    )
    assert complete.satisfied is True
    assert complete.stopped is True
    assert complete.training_pass_count == 8
    assert complete.validation_pass_count == 2


def test_v19_collection_verifier_pass_without_trajectory_does_not_count() -> None:
    training_reserves = OPENHANDS_V19_QUALIFICATION_CANDIDATES[:3]
    validation_reserves = OPENHANDS_V19_QUALIFICATION_CANDIDATES[3:5]
    first = evaluate_v19_collection_gate(
        [
            {
                "role": "training",
                **_attempt(OPENHANDS_V19_FIXED_TRAINING_ORDER[0], admitted=False),
            }
        ],
        training_reserves=training_reserves,
        validation_reserves=validation_reserves,
    )
    assert first.training_pass_count == 4
    assert first.next_task_id == OPENHANDS_V19_FIXED_TRAINING_ORDER[1]

    exhausted = evaluate_v19_collection_gate(
        [
            {"role": "training", **_attempt(task_id, admitted=False)}
            for task_id in OPENHANDS_V19_FIXED_TRAINING_ORDER[:3]
        ],
        training_reserves=training_reserves,
        validation_reserves=validation_reserves,
    )
    assert exhausted.possible is False
    assert exhausted.stopped is True
    assert exhausted.reason == "training_capacity_exhausted"


def test_v19_collection_security_failure_stops_immediately() -> None:
    gate = evaluate_v19_collection_gate(
        [
            {
                "role": "training",
                **_attempt(
                    OPENHANDS_V19_FIXED_TRAINING_ORDER[0],
                    admitted=False,
                    security=False,
                ),
            }
        ],
        training_reserves=OPENHANDS_V19_QUALIFICATION_CANDIDATES[:3],
        validation_reserves=OPENHANDS_V19_QUALIFICATION_CANDIDATES[3:5],
    )
    assert gate.stopped is True
    assert gate.possible is False
    assert gate.reason == "infrastructure_or_security_invalid"
