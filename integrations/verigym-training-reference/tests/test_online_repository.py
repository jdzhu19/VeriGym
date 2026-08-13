from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from verigym.agents.base import AgentTerminationError
from verigym.core.episode import TerminationReason
from verigym.schemas.task import BudgetSpec

from verigym_training_reference.online_repository import (
    OnlineRepositoryBrokerAgent,
    _is_infrastructure_invalid,
)
from verigym_training_reference.repository_broker_protocol import read_hashed_message


def _context() -> Any:
    return SimpleNamespace(
        model_gateway=None,
        external_bridge=None,
        task=SimpleNamespace(
            id="suite/repository-task",
            budget=BudgetSpec(
                max_turns=3,
                max_model_calls=3,
                max_wall_time_s=60,
            ),
            metadata={},
        ),
    )


def _agent(tmp_path: Path) -> OnlineRepositoryBrokerAgent:
    broker = tmp_path / "broker"
    (broker / "requests").mkdir(parents=True)
    (broker / "responses").mkdir()
    agent = OnlineRepositoryBrokerAgent(
        broker_root=broker,
        session_id="a" * 64,
        public_input_hash="b" * 64,
    )
    agent.start(_context())
    return agent


def test_repository_episode_deadline_is_session_scoped_and_model_classified(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    original_deadline = agent._session_deadline
    assert original_deadline is not None
    expired_deadline = time.monotonic() - 1
    agent._session_deadline = expired_deadline

    with pytest.raises(AgentTerminationError) as captured:
        agent._wait_for_action(0)

    assert agent._session_deadline == expired_deadline
    assert agent._session_deadline != original_deadline
    assert captured.value.reason == TerminationReason.WALL_TIME_EXHAUSTED
    assert captured.value.failure.kind == "model"
    assert captured.value.failure.category == "repository_agent_action_timeout"
    assert captured.value.failure.infrastructure is False


def test_repository_terminal_is_independent_and_immutable(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = {
        "infrastructure_valid": True,
        "resolved": False,
        "compile_status": None,
        "task_hash": "c" * 64,
        "verifier_hash": "d" * 64,
        "candidate_hash": "e" * 64,
        "termination_reason": "wall_time_exhausted",
        "run_id": "run-1",
    }

    terminal_hash = agent.publish_terminal(2, result)
    terminal_path = tmp_path / "broker" / "responses" / ("a" * 64) / "terminal.json"
    terminal = read_hashed_message(terminal_path, hash_field="response_hash")

    assert terminal["terminal"] is True
    assert terminal["turn"] == 2
    assert terminal["response_hash"] == terminal_hash
    assert not (terminal_path.parent / "turn-0002.json").exists()
    with pytest.raises(RuntimeError, match="already exists"):
        agent.publish_terminal(2, {**result, "resolved": True})
    assert json.loads(terminal_path.read_text(encoding="utf-8"))["resolved"] is False


@pytest.mark.parametrize(
    ("status", "failure", "expected"),
    [
        (
            "error",
            SimpleNamespace(kind="model", infrastructure=False),
            False,
        ),
        (
            "error",
            SimpleNamespace(kind="runtime", infrastructure=False),
            True,
        ),
        (
            "failed",
            SimpleNamespace(kind="model", infrastructure=True),
            True,
        ),
    ],
)
def test_model_episode_timeout_is_not_infrastructure_invalid(
    status: str, failure: object, expected: bool
) -> None:
    scorecard = SimpleNamespace(
        status=status,
        failure=failure,
        correctness=SimpleNamespace(infrastructure_error=False),
    )

    assert _is_infrastructure_invalid(scorecard) is expected
