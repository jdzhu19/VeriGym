from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "run_codex_training_sampler.py"
_NAMESPACE = runpy.run_path(str(_SCRIPT))
_task_requests = cast(Any, _NAMESPACE["_task_requests"])
_summary = cast(Any, _NAMESPACE["_summary"])
_run = cast(Any, _NAMESPACE["_run"])


def test_multi_source_task_requests_are_ordered(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    arguments = SimpleNamespace(
        source=None,
        task=None,
        source_task=[f"{first}::suite/one", f"{second}::suite/two"],
    )

    requests = _task_requests(arguments)

    assert [(request.source, request.task_id) for request in requests] == [
        (first, "suite/one"),
        (second, "suite/two"),
    ]


def test_progress_summary_distinguishes_rejection_from_infrastructure() -> None:
    summary = _summary(
        plan={"model_id": "model", "reasoning_effort": "max", "plan_hash": "1" * 64},
        records=[
            {"resolved": True, "infrastructure_invalid": False},
            {"resolved": False, "infrastructure_invalid": False},
            {"resolved": False, "infrastructure_invalid": True},
        ],
        planned=4,
        stopped_early=True,
    )

    assert summary["completed"] == 3
    assert summary["resolved"] == 1
    assert summary["rejected"] == 1
    assert summary["infrastructure_invalid"] == 1
    assert summary["stopped_early"] is True


def test_auth_mode_preflight_runs_before_output_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VERIGYM_RUN_CODEX_TRAINING_SAMPLER", "1")
    monkeypatch.delenv("VERIGYM_CODEX_AUTH_MODE", raising=False)
    output = tmp_path / "campaign"
    arguments = SimpleNamespace(samples=1, max_process_time_s=1, output=output)

    with pytest.raises(SystemExit, match="VERIGYM_CODEX_AUTH_MODE"):
        _run(arguments)

    assert not output.exists()
