from __future__ import annotations

import json

import pytest
from verigym.protocols.repository_action import canonical_tool_observation

from verigym_codex_cli.events import EventParseError, normalize_training_messages
from verigym_codex_cli.teacher_agent import _training_system_prompt


def _line(value: dict[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"))


def test_codex_teacher_preserves_completed_mcp_call_and_drops_reasoning() -> None:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    stdout = "\n".join(
        [
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "reasoning", "text": "private"},
                }
            ),
            _line(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "mcp_tool_call",
                        "server": "verigym",
                        "id": "call_exact_1",
                        "name": "finish",
                        "arguments": {"message": "done"},
                        "result": observation,
                    },
                }
            ),
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "complete"},
                }
            ),
        ]
    )

    messages = normalize_training_messages(stdout, system_prompt="system", user_prompt="user")

    assert messages[2].tool_calls is not None
    assert messages[2].tool_calls[0].id == "call_exact_1"
    assert messages[3].tool_call_id == "call_exact_1"
    assert "private" not in json.dumps([message.model_dump() for message in messages])


def test_codex_teacher_binds_pre_tool_assistant_text_to_that_tool_turn() -> None:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    stdout = "\n".join(
        [
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Submitting the repair."},
                }
            ),
            _line(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "mcp_tool_call",
                        "server": "verigym",
                        "id": "call_exact_2",
                        "name": "finish",
                        "arguments": {"message": "done"},
                        "result": observation,
                    },
                }
            ),
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "complete"},
                }
            ),
        ]
    )

    messages = normalize_training_messages(stdout, system_prompt="system", user_prompt="user")

    assert messages[2].content == "Submitting the repair."
    assert messages[2].tool_calls is not None
    assert messages[-1].content == "complete"


def test_codex_teacher_rejects_shell_event_instead_of_guessing_semantics() -> None:
    stdout = "\n".join(
        [
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": "pwd"},
                }
            ),
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "complete"},
                }
            ),
        ]
    )
    with pytest.raises(EventParseError, match="non-MCP"):
        normalize_training_messages(stdout, system_prompt="system", user_prompt="user")


def test_codex_teacher_rejects_unknown_item_instead_of_dropping_it() -> None:
    stdout = _line(
        {
            "type": "item.completed",
            "item": {"type": "future_tool", "name": "unrecognized"},
        }
    )
    with pytest.raises(EventParseError, match="unsupported item"):
        normalize_training_messages(stdout, system_prompt="system", user_prompt="user")


def test_frozen_codex_training_system_prompt_is_sft_safe() -> None:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    stdout = "\n".join(
        [
            _line(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "mcp_tool_call",
                        "server": "verigym",
                        "id": "call_prompt_1",
                        "name": "finish",
                        "arguments": {"message": "done"},
                        "result": observation,
                    },
                }
            ),
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "complete"},
                }
            ),
        ]
    )

    messages = normalize_training_messages(
        stdout, system_prompt=_training_system_prompt(), user_prompt="public task"
    )

    assert messages[0].content == _training_system_prompt()
    assert "*** Update File syntax is invalid" in messages[0].content
