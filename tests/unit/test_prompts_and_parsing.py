from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from verigym.agents.parsing import (
    ModelOutputParseError,
    parse_react_action,
    parse_single_turn_rtl,
)
from verigym.core.episode import BudgetTracker
from verigym.prompts.builder import PromptBuilder
from verigym.schemas.agent import Observation
from verigym.schemas.common import InteractionMode
from verigym.schemas.task import VeriTask
from verigym.suites.toy_rtl.adapter import ToyRtlSuite

RTL = "module counter; endmodule\n"


def initial_observation() -> tuple[VeriTask, Observation]:
    suite = ToyRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    observation = Observation(
        task_id=task.id,
        task_description=task.description,
        visible_files=["visible/tb_smoke.sv", "rtl/counter.v", "README.md"],
        selected_files={"README.md": "Visible instructions only."},
        remaining_budget=BudgetTracker(task.budget).remaining(),
        policy_reminders=["Hidden verifier assets are inaccessible."],
        episode_status="running",
    )
    return task, observation


def test_prompt_construction_is_deterministic_and_chat_advertises_no_tools() -> None:
    task, observation = initial_observation()
    builder = PromptBuilder(InteractionMode.CHAT)
    first = builder.initial_messages(task, observation)
    second = builder.initial_messages(task, observation)
    assert first == second
    serialized = json.dumps([message.model_dump(mode="json") for message in first])
    assert "file.read" not in serialized
    assert "iverilog.simulate_visible" not in serialized
    assert "/tmp/" not in serialized
    assert "tb_counter.sv" not in serialized
    assert "check_result.py" not in serialized


def test_react_prompt_exposes_only_sorted_allowed_tools_and_visible_state() -> None:
    task, observation = initial_observation()
    builder = PromptBuilder(InteractionMode.AGENT)
    messages = builder.initial_messages(task, observation)
    payload = json.loads(messages[1].content)
    assert payload["allowed_tools"] == sorted(task.interaction.allowed_tools)
    assert list(payload["tool_schemas"]) == sorted(task.interaction.allowed_tools)
    serialized = json.dumps(payload)
    assert "file.write" not in serialized
    assert "tb_counter.sv" not in serialized
    assert "check_result.py" not in serialized


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (RTL, RTL),
        (f"```verilog\n{RTL}```", RTL),
        (f"```systemverilog\n{RTL}```", RTL),
    ],
)
def test_single_turn_parser_accepts_only_controlled_rtl_forms(text: str, expected: str) -> None:
    assert parse_single_turn_rtl(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain prose",
        f"before\n```verilog\n{RTL}```",
        f"```verilog\n{RTL}```\n```verilog\n{RTL}```",
        f"```python\n{RTL}```",
    ],
)
def test_single_turn_parser_rejects_empty_or_ambiguous_output(text: str) -> None:
    with pytest.raises(ModelOutputParseError):
        parse_single_turn_rtl(text)


def test_react_parser_is_strict_and_does_not_repair_free_form_output() -> None:
    action = parse_react_action(
        '{"type":"tool_call","tool":"file.read","arguments":{"path":"rtl/counter.v"}}'
    )
    assert action.type == "tool_call"
    with pytest.raises(ModelOutputParseError):
        parse_react_action("please run: cat rtl/counter.v")
    with pytest.raises(ModelOutputParseError):
        parse_react_action('{"type":"tool_call","tool":"file.read","arguments":{},"extra":1}')
    with pytest.raises(ModelOutputParseError):
        parse_react_action('{"type":"shell","command":"cat rtl/counter.v"}')


def test_strict_model_schema_rejects_unknown_prompt_fields() -> None:
    _, observation = initial_observation()
    document = observation.model_dump(mode="json")
    document["hidden_tests"] = ["not allowed"]
    with pytest.raises(ValidationError):
        Observation.model_validate(document)
