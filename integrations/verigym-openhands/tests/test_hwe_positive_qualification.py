from __future__ import annotations

from dataclasses import dataclass

import pytest
from verigym.evolution.memory import validate_agent_version

from verigym_openhands.hwe_positive_qualification import (
    OPENHANDS_POSITIVE_QUALIFICATION_AGENT_VERSION_ID,
    OPENHANDS_POSITIVE_QUALIFICATION_TASK,
    build_positive_qualification_agent_version,
    classify_positive_qualification,
)


@dataclass(frozen=True)
class _ImageLock:
    task_id: str = OPENHANDS_POSITIVE_QUALIFICATION_TASK
    lock_hash: str = "1" * 64
    derived_agent_image_id: str = "sha256:" + "2" * 64
    verifier_base_image_id: str = "sha256:" + "3" * 64


def test_positive_qualification_agent_version_is_frozen_and_repeatable() -> None:
    first = build_positive_qualification_agent_version(
        source_commit="4" * 40,
        image_lock=_ImageLock(),
    )
    second = build_positive_qualification_agent_version(
        source_commit="4" * 40,
        image_lock=_ImageLock(),
    )

    assert validate_agent_version(first) == first
    assert first == second
    assert first.agent_version_id == OPENHANDS_POSITIVE_QUALIFICATION_AGENT_VERSION_ID
    assert first.model_id == "openai/deepseek-v4-flash"
    assert first.training_dataset_hash is None
    assert first.model_weights_modified is False


@pytest.mark.parametrize(
    (
        "infrastructure_valid",
        "evidence_complete",
        "tool_choice_bound",
        "typed_finish",
        "verifier_resolved",
        "trajectory_exported",
        "expected",
    ),
    [
        (True, True, True, True, True, True, ("verifier_passed_trajectory_exported", True)),
        (False, False, False, False, False, False, ("infrastructure_invalid", False)),
        (True, False, True, True, True, True, ("runtime_evidence_invalid", False)),
        (True, True, False, True, True, True, ("runtime_evidence_invalid", False)),
        (True, True, True, False, False, False, ("model_did_not_finish", False)),
        (True, True, True, True, False, False, ("verifier_rejected", False)),
        (True, True, True, True, True, False, ("eligible_trajectory_missing", False)),
    ],
)
def test_positive_qualification_is_fail_closed(
    infrastructure_valid: bool,
    evidence_complete: bool,
    tool_choice_bound: bool,
    typed_finish: bool,
    verifier_resolved: bool,
    trajectory_exported: bool,
    expected: tuple[str, bool],
) -> None:
    assert (
        classify_positive_qualification(
            infrastructure_valid=infrastructure_valid,
            evidence_complete=evidence_complete,
            tool_choice_bound=tool_choice_bound,
            typed_finish_observed=typed_finish,
            ordinary_verifier_resolved=verifier_resolved,
            trajectory_exported=trajectory_exported,
        )
        == expected
    )


def test_positive_qualification_rejects_wrong_task_lock() -> None:
    with pytest.raises(ValueError, match="image-lock task changed"):
        build_positive_qualification_agent_version(
            source_commit="4" * 40,
            image_lock=_ImageLock(task_id="hwe-bench/repo-repair-v1/wrong"),
        )
