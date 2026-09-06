"""No commercial jobs: fail-closed scripted control flow before final submission."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from test_source_projection import source_fixture
from verigym_realbench.adapter import RealBenchSuite

from verigym.agents.base import AgentContext
from verigym.schemas.agent import AbortAction, FinalSubmissionAction, Observation
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.tool import ToolResult


def setup_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Observation]:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    module = importlib.import_module("realbench_scripted_sec_slice")
    source_fixture(tmp_path)
    suite = RealBenchSuite(SuiteSourceConfig(source_root=tmp_path))
    task = suite.load_task(next(iter(suite.discover()))).model_copy(
        update={"id": "realbench/fixture/aes/aes_sbox"}
    )
    agent = module.ScriptedSboxAgent("module aes_sbox(input [7:0] a, output [7:0] b); endmodule\n")
    agent.start(AgentContext(run_id="fixture", task=task, seed=0))
    observation = Observation(
        task_id=task.id,
        remaining_budget={"turns": 20, "tool_calls": 40, "wall_time_s": 300},
        episode_status="running",
    )
    return agent, observation


def test_scripted_sec_requires_expected_public_failure_then_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent, observation = setup_agent(tmp_path, monkeypatch)
    for index in range(7):
        action = agent.act(observation)
        assert not isinstance(action, AbortAction)
        assert isinstance(action, FinalSubmissionAction) == (index == 6)
        observation = observation.model_copy(
            update={
                "previous_tool_result": ToolResult(
                    tool="synthetic",
                    success=index != 2,
                    category="test_failed" if index == 2 else "success",
                )
            }
        )
    assert isinstance(agent.act(observation), AbortAction)


@pytest.mark.parametrize("category", ["sandbox_error", "timeout", "compile_failed", "success"])
def test_scripted_sec_aborts_instead_of_submitting_after_unexpected_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, category: str
) -> None:
    agent, observation = setup_agent(tmp_path, monkeypatch)
    # Reach the deliberately wrong candidate's public-test response.
    for _ in range(3):
        agent.act(observation)
        observation = observation.model_copy(
            update={
                "previous_tool_result": ToolResult(
                    tool="synthetic", success=True, category="success"
                )
            }
        )
    observation = observation.model_copy(
        update={
            "previous_tool_result": ToolResult(
                tool="repository.public_test", success=category == "success", category=category
            )
        }
    )
    assert isinstance(agent.act(observation), AbortAction)
