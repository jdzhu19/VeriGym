from __future__ import annotations

import json

import pytest

from verigym.core.episode import BudgetTracker, TerminationReason
from verigym.core.errors import ReplayError
from verigym.core.redaction import redact_mapping
from verigym.core.trace import TraceWriter, read_trace
from verigym.schemas.task import BudgetSpec


def test_budget_accounting_returns_structured_reasons() -> None:
    tracker = BudgetTracker(BudgetSpec(max_turns=2, max_tool_calls=1, max_wall_time_s=30))
    assert tracker.exhausted_before_turn() is None
    tracker.consume_turn()
    tracker.consume_turn()
    assert tracker.exhausted_before_turn() == TerminationReason.TURN_BUDGET_EXHAUSTED
    tracker.consume_tool()
    assert tracker.exhausted_before_tool() == TerminationReason.TOOL_BUDGET_EXHAUSTED
    assert tracker.remaining().turns == 0
    assert tracker.remaining().tool_calls == 0


def test_trace_is_append_only_and_sequence_validated(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = TraceWriter(path, "run-1")
    writer.emit("episode_started", {"task_id": "toy"})
    writer.emit("episode_terminated", {"resolved": True})
    events = read_trace(path, expected_run_id="run-1")
    assert [event.sequence for event in events] == [0, 1]
    lines = path.read_text(encoding="utf-8").splitlines()
    damaged = json.loads(lines[1])
    damaged["sequence"] = 3
    lines[1] = json.dumps(damaged)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ReplayError, match="sequence gap"):
        read_trace(path, expected_run_id="run-1")


def test_secret_redaction_is_recursive_and_case_insensitive() -> None:
    values = {
        "VERIGYM_MODEL_API_KEY": "top-secret",
        "safe": "visible",
        "nested": {"access_token": "secret", "count": 2},
        "items": [{"db_password": "secret"}],
    }
    redacted = redact_mapping(values)
    assert redacted["VERIGYM_MODEL_API_KEY"] == "<redacted>"
    assert redacted["safe"] == "visible"
    assert redacted["nested"]["access_token"] == "<redacted>"
    assert redacted["items"][0]["db_password"] == "<redacted>"
