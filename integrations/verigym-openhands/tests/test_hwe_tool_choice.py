from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.tool import FinishTool, ToolDefinition

from verigym_openhands.hwe_tool_choice import RequiredToolChoiceLLM


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
