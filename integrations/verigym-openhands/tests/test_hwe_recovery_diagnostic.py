from __future__ import annotations

from dataclasses import dataclass

import pytest
from verigym.evolution.memory import validate_agent_version

from verigym_openhands.hwe_recovery_diagnostic import (
    OPENHANDS_RECOVERY_DIAGNOSTIC_AGENT_VERSION_ID,
    OPENHANDS_RECOVERY_DIAGNOSTIC_TASK,
    build_recovery_diagnostic_agent_version,
    classify_recovery_diagnostic,
)


@dataclass(frozen=True)
class _ImageLock:
    task_id: str = OPENHANDS_RECOVERY_DIAGNOSTIC_TASK
    lock_hash: str = "1" * 64
    derived_agent_image_id: str = "sha256:" + "2" * 64
    verifier_base_image_id: str = "sha256:" + "3" * 64


def test_recovery_diagnostic_agent_version_is_frozen_and_repeatable() -> None:
    first = build_recovery_diagnostic_agent_version(
        source_commit="4" * 40,
        image_lock=_ImageLock(),
    )
    second = build_recovery_diagnostic_agent_version(
        source_commit="4" * 40,
        image_lock=_ImageLock(),
    )

    assert validate_agent_version(first) == first
    assert first == second
    assert first.agent_version_id == OPENHANDS_RECOVERY_DIAGNOSTIC_AGENT_VERSION_ID
    assert first.model_id == "openai/deepseek-v4-flash"
    assert first.source_commit == "4" * 40
    assert first.training_dataset_hash is None
    assert first.model_weights_modified is False


def test_recovery_diagnostic_agent_version_rejects_wrong_task() -> None:
    with pytest.raises(ValueError, match="image-lock task"):
        build_recovery_diagnostic_agent_version(
            source_commit="4" * 40,
            image_lock=_ImageLock(task_id="hwe-bench/repo-repair-v1/example__wrong__pr-1"),
        )


@pytest.mark.parametrize(
    ("infrastructure_valid", "finished", "count", "failure", "status", "passed"),
    [
        (True, True, 1, None, "recovery_regression_passed", True),
        (True, True, 0, None, "direct_finish_passed_recovery_not_exercised", False),
        (True, False, 1, "openhands_hwe_missing_finish", "termination_regression_failed", False),
        (True, False, 0, "other", "model_rejected_before_typed_finish", False),
        (False, False, 0, "runtime", "infrastructure_invalid", False),
    ],
)
def test_recovery_diagnostic_outcome_is_independent_of_verifier_correctness(
    infrastructure_valid: bool,
    finished: bool,
    count: int,
    failure: str | None,
    status: str,
    passed: bool,
) -> None:
    assert classify_recovery_diagnostic(
        infrastructure_valid=infrastructure_valid,
        typed_finish_observed=finished,
        recovery_count=count,
        failure_category=failure,
    ) == (status, passed)


def test_recovery_diagnostic_rejects_out_of_budget_count() -> None:
    with pytest.raises(ValueError, match="outside the frozen budget"):
        classify_recovery_diagnostic(
            infrastructure_valid=True,
            typed_finish_observed=True,
            recovery_count=2,
            failure_category=None,
        )
