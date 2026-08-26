"""OpenHands LLM policy that requires one native tool call on every HWE turn."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from openhands.sdk.llm import LLM, LLMResponse, Message  # type: ignore[import-not-found]
from openhands.sdk.llm.llm import LLMCallContext  # type: ignore[import-not-found]
from openhands.sdk.llm.streaming import (  # type: ignore[import-not-found]
    AnyTokenCallbackType,
    TokenCallbackType,
)
from openhands.sdk.tool import ToolDefinition  # type: ignore[import-not-found]

OPENHANDS_HWE_TOOL_CHOICE_REQUIRED = "required"


def _required_tool_choice_kwargs(
    tools: Sequence[ToolDefinition] | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Return fail-closed request kwargs for the exact HWE tool-only protocol."""

    if not tools:
        raise ValueError("required OpenHands HWE tool choice needs a non-empty tool contract")
    requested = kwargs.pop("tool_choice", OPENHANDS_HWE_TOOL_CHOICE_REQUIRED)
    if requested != OPENHANDS_HWE_TOOL_CHOICE_REQUIRED:
        raise ValueError("OpenHands HWE tool choice cannot be weakened from required")
    return {**kwargs, "tool_choice": OPENHANDS_HWE_TOOL_CHOICE_REQUIRED}


class RequiredToolChoiceLLM(LLM):  # type: ignore[misc]
    """Use the public LLM completion interface while forcing native tool selection."""

    def completion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: TokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return super().completion(
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            **_required_tool_choice_kwargs(tools, kwargs),
        )

    async def acompletion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: AnyTokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await super().acompletion(
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            **_required_tool_choice_kwargs(tools, kwargs),
        )


__all__ = [
    "OPENHANDS_HWE_TOOL_CHOICE_REQUIRED",
    "RequiredToolChoiceLLM",
]
