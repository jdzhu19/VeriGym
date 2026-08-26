from __future__ import annotations

from dataclasses import dataclass

import pytest
from verigym.evolution.memory import validate_agent_version

from verigym_openhands.hwe_tool_choice_diagnostic import (
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_AGENT_VERSION_ID,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK,
    build_tool_choice_diagnostic_agent_version,
    classify_tool_choice_diagnostic,
)


@dataclass(frozen=True)
class _ImageLock:
    task_id: str = OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK
    lock_hash: str = "1" * 64
    derived_agent_image_id: str = "sha256:" + "2" * 64
    verifier_base_image_id: str = "sha256:" + "3" * 64


def test_tool_choice_diagnostic_agent_version_is_frozen_and_repeatable() -> None:
    first = build_tool_choice_diagnostic_agent_version(
        source_commit="4" * 40,
        image_lock=_ImageLock(),
    )
    second = build_tool_choice_diagnostic_agent_version(
        source_commit="4" * 40,
        image_lock=_ImageLock(),
    )

    assert validate_agent_version(first) == first
    assert first == second
    assert first.agent_version_id == OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_AGENT_VERSION_ID
    assert first.model_id == "openai/deepseek-v4-flash"
    assert first.source_commit == "4" * 40
    assert first.training_dataset_hash is None
    assert first.model_weights_modified is False


@pytest.mark.parametrize(
    ("infrastructure", "finished", "recoveries", "failure", "status", "passed"),
    [
        (True, True, 1, None, "recovery_forced_finish_regression_passed", True),
        (True, True, 0, None, "direct_finish_passed_recovery_not_exercised", False),
        (
            True,
            False,
            1,
            "openhands_hwe_missing_finish",
            "recovery_forced_finish_regression_failed",
            False,
        ),
        (True, False, 0, "other", "model_rejected_before_typed_finish", False),
        (False, False, 0, "runtime", "infrastructure_invalid", False),
    ],
)
def test_tool_choice_diagnostic_requires_direct_typed_finish(
    infrastructure: bool,
    finished: bool,
    recoveries: int,
    failure: str | None,
    status: str,
    passed: bool,
) -> None:
    assert classify_tool_choice_diagnostic(
        infrastructure_valid=infrastructure,
        typed_finish_observed=finished,
        recovery_count=recoveries,
        failure_category=failure,
    ) == (status, passed)


def test_tool_choice_diagnostic_rejects_out_of_budget_count() -> None:
    with pytest.raises(ValueError, match="outside the frozen budget"):
        classify_tool_choice_diagnostic(
            infrastructure_valid=True,
            typed_finish_observed=True,
            recovery_count=2,
            failure_category=None,
        )
