from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.core.errors import ConfigurationError

from verigym_training_reference.cva6_teacher_collection import (
    _attempt_id,
    _campaign_output,
    _is_infrastructure_invalid,
)


def test_campaign_identity_is_bound_into_progress_and_attempt_ids(tmp_path: Path) -> None:
    campaign_id = "cva6-verified-multiturn-teachers-v2"

    root, progress = _campaign_output(
        tmp_path / "teachers",
        campaign_id=campaign_id,
        split_hash="a" * 64,
        docker_config_hash="b" * 64,
    )

    assert root == (tmp_path / "teachers").resolve()
    assert progress["campaign_id"] == campaign_id
    assert _attempt_id(campaign_id, 3, "codex", 0) == (
        "cva6-verified-multiturn-teachers-v2-03-codex-sample-0"
    )


def test_campaign_cannot_resume_under_a_different_identity(tmp_path: Path) -> None:
    output = tmp_path / "teachers"
    _campaign_output(
        output,
        campaign_id="cva6-verified-multiturn-teachers-v1",
        split_hash="a" * 64,
        docker_config_hash="b" * 64,
    )

    with pytest.raises(ConfigurationError, match="resume identity changed"):
        _campaign_output(
            output,
            campaign_id="cva6-verified-multiturn-teachers-v2",
            split_hash="a" * 64,
            docker_config_hash="b" * 64,
        )


@pytest.mark.parametrize(
    ("status", "failure", "expected"),
    [
        ("error", SimpleNamespace(kind="model", infrastructure=False), False),
        ("error", SimpleNamespace(kind="runtime", infrastructure=False), True),
        ("failed", SimpleNamespace(kind="model", infrastructure=True), True),
    ],
)
def test_teacher_campaign_distinguishes_agent_and_infrastructure_failures(
    status: str, failure: object, expected: bool
) -> None:
    scorecard = SimpleNamespace(
        status=status,
        failure=failure,
        correctness=SimpleNamespace(infrastructure_error=False),
    )

    assert _is_infrastructure_invalid(scorecard) is expected
