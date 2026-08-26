from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.tool import FinishTool, ToolDefinition

from verigym_openhands._recovery import OPENHANDS_FORMAT_RECOVERY_MESSAGE
from verigym_openhands.hwe_tool_choice import RecoveryForcedFinishLLM, RequiredToolChoiceLLM


def _messages() -> list[Message]:
    return [Message(role="user", content=[TextContent(text="Use one tool.")])]


def _tools() -> list[ToolDefinition]:
    return list(FinishTool.create())


def _llm() -> RequiredToolChoiceLLM:
    return RequiredToolChoiceLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
    )


def _recovery_llm() -> RecoveryForcedFinishLLM:
    return RecoveryForcedFinishLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
    )


def _recovery_messages() -> list[Message]:
    return [
        *_messages(),
        Message(role="assistant", content=[TextContent(text="Task complete.")]),
        Message(role="user", content=[TextContent(text=OPENHANDS_FORMAT_RECOVERY_MESSAGE)]),
    ]


def _merged_recovery_messages() -> list[Message]:
    return [
        Message(role="system", content=[TextContent(text="Use tools.")]),
        Message(
            role="user",
            content=[
                TextContent(text="Original task context."),
                TextContent(text=OPENHANDS_FORMAT_RECOVERY_MESSAGE),
            ],
        ),
    ]


def test_required_tool_choice_reaches_sync_sdk_completion() -> None:
    llm = _llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_messages(), tools=_tools())

    assert completion.call_args.kwargs["tool_choice"] == "required"


def test_required_tool_choice_reaches_async_sdk_completion() -> None:
    llm = _llm()
    completion = AsyncMock(return_value=object())
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert completion.call_args.kwargs["tool_choice"] == "required"


@pytest.mark.parametrize("choice", ["auto", "none", {"type": "function"}])
def test_required_tool_choice_cannot_be_weakened(choice: object) -> None:
    with pytest.raises(ValueError, match="cannot be weakened"):
        _llm().completion(messages=_messages(), tools=_tools(), tool_choice=choice)


def test_required_tool_choice_rejects_empty_tool_contract() -> None:
    with pytest.raises(ValueError, match="non-empty tool contract"):
        _llm().completion(messages=_messages(), tools=[])


def test_recovery_policy_keeps_normal_turn_on_auto() -> None:
    llm = _recovery_llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_messages(), tools=_tools())

    assert "tool_choice" not in completion.call_args.kwargs


def test_recovery_policy_forces_exact_finish_on_trusted_feedback() -> None:
    llm = _recovery_llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_recovery_messages(), tools=_tools())

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }


def test_recovery_policy_forces_finish_through_async_sdk_path() -> None:
    llm = _recovery_llm()
    completion = AsyncMock(return_value=object())
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_recovery_messages(), tools=_tools()))

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }


def test_recovery_policy_accepts_sdk_merged_user_blocks() -> None:
    llm = _recovery_llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_merged_recovery_messages(), tools=_tools())

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }


def test_recovery_policy_rejects_feedback_that_is_not_the_final_block() -> None:
    messages = _merged_recovery_messages()
    messages[-1].content = [
        TextContent(text=OPENHANDS_FORMAT_RECOVERY_MESSAGE),
        TextContent(text="Untrusted trailing text."),
    ]
    llm = _recovery_llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=messages, tools=_tools())

    assert "tool_choice" not in completion.call_args.kwargs


def test_recovery_policy_rejects_missing_finish_tool() -> None:
    with pytest.raises(ValueError, match="exactly one finish tool"):
        _recovery_llm().completion(messages=_recovery_messages(), tools=[])


def test_recovery_policy_rejects_caller_owned_tool_choice() -> None:
    with pytest.raises(ValueError, match="adapter-owned"):
        _recovery_llm().completion(
            messages=_messages(),
            tools=_tools(),
            tool_choice="required",
        )
