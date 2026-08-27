from __future__ import annotations

from dataclasses import dataclass

import pytest
from verigym.evolution.memory import validate_agent_version

from verigym_openhands.hwe_responses_recovery_diagnostic import (
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_AGENT_VERSION_ID,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK,
    build_responses_recovery_diagnostic_agent_version,
    classify_responses_recovery_diagnostic,
)


@dataclass(frozen=True)
class _ImageLock:
    task_id: str = OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK
    lock_hash: str = "1" * 64
    derived_agent_image_id: str = "sha256:" + "2" * 64
    verifier_base_image_id: str = "sha256:" + "3" * 64


def test_responses_recovery_agent_version_is_frozen_and_repeatable() -> None:
    first = build_responses_recovery_diagnostic_agent_version(
        source_commit="4" * 40,
        image_lock=_ImageLock(),
    )
    second = build_responses_recovery_diagnostic_agent_version(
        source_commit="4" * 40,
        image_lock=_ImageLock(),
    )

    assert validate_agent_version(first) == first
    assert first == second
    assert first.agent_version_id == OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_AGENT_VERSION_ID
    assert first.model_id == "openai/deepseek-v4-flash"
    assert first.training_dataset_hash is None
    assert first.model_weights_modified is False


@pytest.mark.parametrize(
    (
        "infrastructure",
        "finished",
        "recoveries",
        "forced",
        "validated",
        "coalesced",
        "failure",
        "expected",
    ),
    [
        (
            True,
            True,
            1,
            1,
            1,
            1,
            None,
            ("responses_recovery_finish_regression_passed", True),
        ),
        (
            True,
            False,
            1,
            1,
            0,
            1,
            "openhands_hwe_recovery_tool_choice_violation",
            ("responses_recovery_finish_response_rejected", False),
        ),
        (
            True,
            True,
            1,
            1,
            1,
            0,
            None,
            ("responses_recovery_output_coalescing_not_exercised", False),
        ),
        (
            False,
            False,
            0,
            0,
            0,
            0,
            "runtime",
            ("infrastructure_invalid", False),
        ),
    ],
)
def test_responses_recovery_requires_broker_typed_finish(
    infrastructure: bool,
    finished: bool,
    recoveries: int,
    forced: int,
    validated: int,
    coalesced: int,
    failure: str | None,
    expected: tuple[str, bool],
) -> None:
    assert (
        classify_responses_recovery_diagnostic(
            infrastructure_valid=infrastructure,
            typed_finish_observed=finished,
            recovery_count=recoveries,
            forced_request_count=forced,
            validated_finish_count=validated,
            coalesced_output_count=coalesced,
            failure_category=failure,
        )
        == expected
    )
