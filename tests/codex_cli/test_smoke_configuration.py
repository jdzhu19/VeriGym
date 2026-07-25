from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest
import yaml

from verigym.schemas.model import ModelRunConfig
from verigym.schemas.run import RunConfig

pytestmark = [pytest.mark.codex_cli]

ROOT = Path(__file__).resolve().parents[2]


def test_real_smoke_uses_ten_minute_process_timeouts() -> None:
    namespace = runpy.run_path(str(ROOT / "scripts" / "run_codex_cli_smoke.py"))
    build_config = namespace["_run_config"]

    track_a = build_config(
        {
            "task_id": "toy-rtl/and-gate-basic",
            "seed": 0,
            "sample_index": 0,
            "run_id": "track-a",
            "track": "codex_cli_model_proxy",
        },
        "gpt-5.4",
        Path("runs"),
    )
    track_b = build_config(
        {
            "task_id": "toy-rtl/and-gate-basic",
            "seed": 0,
            "sample_index": 0,
            "run_id": "track-b",
            "track": "codex_cli_external_agent",
        },
        "gpt-5.4",
        Path("runs"),
    )

    assert isinstance(track_a, RunConfig)
    assert isinstance(track_a.model_options, ModelRunConfig)
    assert track_a.model_options.request_timeout_s == 600
    assert track_a.model_options.client_options["allow_proxy_environment"] is True
    assert track_a.model_options.client_options["max_process_time_s"] == 600
    assert track_b.agent_options["allow_proxy_environment"] is True
    assert track_b.agent_options["max_process_time_s"] == 600
    assert namespace["_MAX_TOTAL_WALL_TIME_S"] == 3000


def test_smoke_example_matches_launcher_time_limits() -> None:
    path = ROOT / "examples" / "experiments" / "codex-cli-smoke.yaml"
    payload: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    execution = payload["execution"]

    assert execution["max_process_time_s"] == 600
    assert execution["max_total_wall_time_s"] == 3000
    assert execution["max_total_wall_time_s"] >= (
        execution["planned_runs"] * execution["max_process_time_s"]
    )
