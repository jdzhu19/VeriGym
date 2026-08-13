from __future__ import annotations

import json

import pytest
from verigym.core.repository_tool_broker import RepositoryToolBrokerTurn
from verigym.protocols.repository_action import canonical_action_json, canonical_tool_observation

from verigym_claude_cli.agent import _training_system_prompt
from verigym_claude_cli.events import (
    EventParseError,
    TranscriptNormalizationInfrastructureError,
    normalize_training_messages,
)


def _line(value: dict[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"))


def _turn(name: str, arguments: dict[str, object], observation: str) -> RepositoryToolBrokerTurn:
    envelope = json.loads(canonical_action_json(name, arguments))
    return RepositoryToolBrokerTurn(
        tool_name=name,
        arguments_json=json.dumps(
            envelope["arguments"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ),
        observation_json=observation,
    )


def _successful_finish_stream() -> str:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    return "\n".join(
        [
            _line(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_prompt_1",
                                "name": "mcp__verigym__finish",
                                "input": {"message": "done"},
                            }
                        ]
                    },
                }
            ),
            _line(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_prompt_1",
                                "content": observation,
                            }
                        ]
                    },
                }
            ),
            _line({"type": "result", "result": "complete"}),
        ]
    )


def test_claude_training_normalization_preserves_call_id_and_drops_thinking() -> None:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    stdout = "\n".join(
        [
            _line(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "thinking", "thinking": "private"},
                            {
                                "type": "tool_use",
                                "id": "toolu_exact_1",
                                "name": "mcp__verigym__finish",
                                "input": {"message": "done"},
                            },
                        ]
                    },
                }
            ),
            _line(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_exact_1",
                                "content": observation,
                            }
                        ]
                    },
                }
            ),
            _line({"type": "result", "result": "complete"}),
        ]
    )

    messages = normalize_training_messages(
        stdout,
        system_prompt="system",
        user_prompt="user",
        broker_turns=(_turn("finish", {"message": "done"}, observation),),
    )

    assert messages[2].tool_calls is not None
    assert messages[2].tool_calls[0].id == "toolu_exact_1"
    assert messages[3].tool_call_id == "toolu_exact_1"
    assert "private" not in json.dumps([message.model_dump() for message in messages])


def test_claude_training_normalization_rejects_non_registry_tool() -> None:
    stdout = _line(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "x", "name": "Bash", "input": {}}]},
        }
    )
    with pytest.raises(EventParseError, match="canonical MCP"):
        normalize_training_messages(
            stdout, system_prompt="system", user_prompt="user", broker_turns=()
        )


def test_frozen_claude_training_system_prompt_is_sft_safe() -> None:
    messages = normalize_training_messages(
        _successful_finish_stream(),
        system_prompt=_training_system_prompt(),
        user_prompt="public task",
        broker_turns=(
            _turn(
                "finish",
                {"message": "done"},
                canonical_tool_observation(
                    "finish", {"accepted": True, "terminal": True}, is_error=False
                ),
            ),
        ),
    )

    assert messages[0].content == _training_system_prompt()
    assert "*** Update File syntax is invalid" in messages[0].content


def test_claude_training_uses_broker_observation_not_provider_error_rendering() -> None:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    provider_events = [json.loads(line) for line in _successful_finish_stream().splitlines()]
    provider_events[1]["message"]["content"][0]["content"] = "Error: provider-decorated tool text"
    provider_rendered = "\n".join(_line(event) for event in provider_events)

    messages = normalize_training_messages(
        provider_rendered,
        system_prompt="system",
        user_prompt="user",
        broker_turns=(_turn("finish", {"message": "done"}, observation),),
    )

    assert messages[3].content == observation


def test_claude_training_fails_closed_on_broker_event_mismatch() -> None:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )

    with pytest.raises(TranscriptNormalizationInfrastructureError, match="differs"):
        normalize_training_messages(
            _successful_finish_stream(),
            system_prompt="system",
            user_prompt="user",
            broker_turns=(_turn("finish", {"message": "different"}, observation),),
        )
