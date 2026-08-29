from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym_openhands.hwe_v19 import (
    benchmark_verifier_passed,
    build_v19_protocol_receipt,
    classify_v19_campaign_result,
    seal_v19_decision_receipt,
    seal_v19_trajectory_receipt,
)


def _fixture() -> dict[str, object]:
    path = Path(__file__).with_name("fixtures") / "pr2469_v18_scorecard_summary.json"
    return json.loads(path.read_bytes())


def _protocol_receipt() -> dict[str, object]:
    return build_v19_protocol_receipt(
        provider={
            "provider_call_count": 3,
            "successful_provider_response_count": 3,
            "provider_usage_record_count": 3,
            "input_tokens": 900,
            "output_tokens": 100,
        },
        protocol={
            "required_tool_request_count": 3,
            "canonical_tool_response_count": 2,
            "content_only_response_count": 1,
            "format_recovery_count": 1,
            "recovery_forced_request_count": 1,
            "recovery_validated_tool_count": 1,
            "over_budget_response_count": 0,
        },
        broker_decision_steps=2,
    )


def test_pr2469_offline_regression_uses_actual_verifier_results() -> None:
    scorecard = _fixture()

    assert scorecard["resolved"] is False
    assert benchmark_verifier_passed(scorecard) is True
    result = classify_v19_campaign_result(
        scorecard,
        agent_protocol_valid=False,
        trajectory_eligible=False,
        infrastructure_valid=True,
        security_valid=True,
        admit_to_sft=True,
        evidence_origin="sealed_historical_scorecard_regression",
    )

    assert result["benchmark_verifier_pass"] is True
    assert result["scorecard_resolved_compatibility_value"] is False
    assert result["agent_protocol_valid"] is False
    assert result["trajectory_eligible"] is False
    assert result["sft_admitted"] is False
    assert result["historical_trajectory_reconstructed"] is False
    assert result["evidence_origin"] == "sealed_historical_scorecard_regression"


def test_v19_sft_admission_requires_every_independent_plane() -> None:
    scorecard = _fixture()
    admitted = classify_v19_campaign_result(
        scorecard,
        agent_protocol_valid=True,
        trajectory_eligible=True,
        infrastructure_valid=True,
        security_valid=True,
        admit_to_sft=True,
    )
    assert admitted["sft_admitted"] is True

    rejected = classify_v19_campaign_result(
        scorecard,
        agent_protocol_valid=True,
        trajectory_eligible=True,
        infrastructure_valid=True,
        security_valid=False,
        admit_to_sft=True,
    )
    assert rejected["benchmark_verifier_pass"] is True
    assert rejected["sft_admitted"] is False


def test_v19_protocol_receipt_enforces_accounting_identity() -> None:
    receipt = _protocol_receipt()
    assert receipt["required_tool_request_count"] == 3
    assert receipt["canonical_tool_response_count"] == 2
    assert receipt["content_only_response_count"] == 1
    assert receipt["provider_total_tokens"] == 1000

    changed = dict(receipt)
    changed["canonical_tool_response_count"] = 3
    changed.pop("receipt_hash")
    from verigym.core.hashing import content_hash

    changed["receipt_hash"] = content_hash(changed)
    with pytest.raises(ValueError, match="accounting changed"):
        from verigym_openhands.hwe_v19 import validate_v19_protocol_receipt

        validate_v19_protocol_receipt(changed)


def test_v19_trajectory_and_decision_receipts_bind_exact_64k_rows() -> None:
    campaign = classify_v19_campaign_result(
        _fixture(),
        agent_protocol_valid=True,
        trajectory_eligible=True,
        infrastructure_valid=True,
        security_valid=True,
        admit_to_sft=True,
    )
    trajectory = seal_v19_trajectory_receipt(
        transcript_hash="a" * 64,
        protocol_receipt=_protocol_receipt(),
        campaign_result=campaign,
    )
    assert trajectory["abnormal_assistant_text_loss_mask"] == 0
    assert trajectory["recovery_feedback_loss_mask"] == 0
    assert trajectory["canonical_tool_decision_loss_mask"] == 1
    decisions = seal_v19_decision_receipt(
        records=[
            {
                "record_hash": "b" * 64,
                "transcript_hash": "a" * 64,
                "token_count": 65_536,
                "eligible": True,
                "truncation": "error",
                "input_loss_masked": True,
            }
        ],
        trajectory_receipt=trajectory,
    )
    assert decisions["maximum_token_count"] == 65_536

    with pytest.raises(ValueError, match="exact-64K"):
        seal_v19_decision_receipt(
            records=[
                {
                    "record_hash": "c" * 64,
                    "transcript_hash": "a" * 64,
                    "token_count": 65_537,
                    "eligible": True,
                    "truncation": "error",
                    "input_loss_masked": True,
                }
            ],
            trajectory_receipt=trajectory,
        )
