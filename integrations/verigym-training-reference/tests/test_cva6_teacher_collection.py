from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.core.errors import ConfigurationError

from verigym_training_reference.cva6_teacher_collection import (
    _MAX_CONSECUTIVE_REJECTED_CALLS,
    _MAX_EVIDENCE_BYTES,
    _MAX_PATCH_CALLS,
    _MAX_PROCESS_TIME_S,
    _MAX_TOOL_CALLS,
    _attempt_id,
    _campaign_output,
    _is_infrastructure_invalid,
)


def test_teacher_campaign_uses_the_maximum_bounded_cli_evidence_stream() -> None:
    assert _MAX_EVIDENCE_BYTES == 16 * 1024 * 1024

    source = (
        Path(__file__).parents[1]
        / "src"
        / "verigym_training_reference"
        / "cva6_teacher_collection.py"
    ).read_text(encoding="utf-8")
    assert source.count('"max_output_bytes": _MAX_EVIDENCE_BYTES') == 2
    assert source.count('"max_tool_calls": _MAX_TOOL_CALLS') >= 2
    assert source.count('"max_patch_calls": _MAX_PATCH_CALLS') >= 2
    assert source.count('"max_consecutive_rejected_calls": _MAX_CONSECUTIVE_REJECTED_CALLS') >= 2
    assert _MAX_PROCESS_TIME_S == 600


def test_campaign_identity_is_bound_into_progress_and_attempt_ids(tmp_path: Path) -> None:
    campaign_id = "cva6-verified-multiturn-teachers-v2"

    root, progress = _campaign_output(
        tmp_path / "teachers",
        campaign_id=campaign_id,
        split_hash="a" * 64,
        docker_config_hash="b" * 64,
        max_process_time_s=_MAX_PROCESS_TIME_S,
    )

    assert root == (tmp_path / "teachers").resolve()
    assert progress["campaign_id"] == campaign_id
    assert progress["episode_limits"] == {
        "max_process_time_s": _MAX_PROCESS_TIME_S,
        "max_tool_calls": _MAX_TOOL_CALLS,
        "max_patch_calls": _MAX_PATCH_CALLS,
        "max_consecutive_rejected_calls": _MAX_CONSECUTIVE_REJECTED_CALLS,
    }
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
        max_process_time_s=_MAX_PROCESS_TIME_S,
    )

    with pytest.raises(ConfigurationError, match="resume identity changed"):
        _campaign_output(
            output,
            campaign_id="cva6-verified-multiturn-teachers-v2",
            split_hash="a" * 64,
            docker_config_hash="b" * 64,
            max_process_time_s=_MAX_PROCESS_TIME_S,
        )


def test_campaign_cannot_resume_with_a_different_wall_clock_limit(tmp_path: Path) -> None:
    output = tmp_path / "teachers"
    _campaign_output(
        output,
        campaign_id="cva6-verified-multiturn-teachers-v1",
        split_hash="a" * 64,
        docker_config_hash="b" * 64,
        max_process_time_s=_MAX_PROCESS_TIME_S,
    )

    with pytest.raises(ConfigurationError, match="resume identity changed"):
        _campaign_output(
            output,
            campaign_id="cva6-verified-multiturn-teachers-v1",
            split_hash="a" * 64,
            docker_config_hash="b" * 64,
            max_process_time_s=_MAX_PROCESS_TIME_S - 1,
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
