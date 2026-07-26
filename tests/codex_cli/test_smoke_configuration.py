from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest
import yaml
from verigym_codex_cli.capabilities import runtime_capabilities
from verigym_codex_cli.config import agent_settings, model_settings

from verigym.core.orchestrator import VeriGym
from verigym.registry.collections import build_registries
from verigym.schemas.model import ModelRunConfig
from verigym.schemas.run import RunConfig

pytestmark = [pytest.mark.codex_cli]

ROOT = Path(__file__).resolve().parents[2]


def test_real_smoke_uses_budget_aligned_five_minute_process_timeouts() -> None:
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
    assert track_a.model_options.request_timeout_s == 300
    assert track_a.model_options.client_options["allow_proxy_environment"] is True
    assert track_a.model_options.client_options["max_process_time_s"] == 300
    assert track_a.model_options.client_options["reasoning_effort"] == "xhigh"
    assert track_b.agent_options["allow_proxy_environment"] is True
    assert track_b.agent_options["max_process_time_s"] == 300
    assert track_b.agent_options["reasoning_effort"] == "xhigh"
    assert namespace["_MAX_TOTAL_WALL_TIME_S"] == 1800


def test_smoke_example_matches_launcher_time_limits() -> None:
    path = ROOT / "examples" / "experiments" / "codex-cli-smoke.yaml"
    payload: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    execution = payload["execution"]

    assert execution["requested_reasoning_effort"] == "xhigh"
    assert execution["effective_reasoning_effort"] == "xhigh"
    assert execution["reasoning_effort_source"] == "verigym_explicit_cli_override"
    assert execution["inherited_reasoning_effort_allowed"] is False
    assert execution["max_process_time_s"] == 300
    assert execution["max_total_wall_time_s"] == 1800
    assert execution["max_total_wall_time_s"] >= (
        execution["planned_runs"] * execution["max_process_time_s"]
    )


@pytest.mark.parametrize(
    "task_id",
    ["toy-rtl/and-gate-basic", "toy-rtl/counter-basic"],
)
def test_actual_settings_resolvers_match_each_toy_task_budget(
    fake_codex: tuple[Path, Path, object],
    task_id: str,
) -> None:
    _executable, _log, _scenario = fake_codex
    _identity, capabilities = runtime_capabilities()
    task = VeriGym(build_registries(discover_external=False)).load_task(task_id)[1]
    assert task.budget.max_wall_time_s == 300

    track_a = model_settings(
        ModelRunConfig(
            model_id="fake-model",
            request_timeout_s=300,
            client_options={
                "allow_proxy_environment": True,
                "max_process_time_s": 300,
                "reasoning_effort": "xhigh",
            },
        ),
        capabilities,
    )
    track_b = agent_settings(
        {
            "model_id": "fake-model",
            "allow_proxy_environment": True,
            "max_process_time_s": 300,
            "reasoning_effort": "xhigh",
        },
        capabilities,
        task_wall_time_s=task.budget.max_wall_time_s,
    )
    for settings in (track_a, track_b):
        assert settings.requested_process_timeout_s == 300
        assert settings.task_wall_time_s == 300
        assert settings.effective_process_timeout_s == 300
        assert settings.max_process_time_s == 300
        assert settings.timeout_clamped is False
        assert settings.requested_reasoning_effort == "xhigh"
        assert settings.effective_reasoning_effort == "xhigh"
        assert settings.reasoning_effort_source == "verigym_explicit_cli_override"
        assert settings.inherited_reasoning_effort_allowed is False


def test_actual_settings_resolvers_make_generic_clamping_observable(
    fake_codex: tuple[Path, Path, object],
) -> None:
    _executable, _log, _scenario = fake_codex
    _identity, capabilities = runtime_capabilities()
    track_a = model_settings(
        ModelRunConfig(
            model_id="fake-model",
            request_timeout_s=300,
            client_options={"max_process_time_s": 600},
        ),
        capabilities,
    )
    track_b = agent_settings(
        {"model_id": "fake-model", "max_process_time_s": 600},
        capabilities,
        task_wall_time_s=300,
    )
    for settings in (track_a, track_b):
        assert settings.requested_process_timeout_s == 600
        assert settings.task_wall_time_s == 300
        assert settings.effective_process_timeout_s == 300
        assert settings.timeout_clamped is True
