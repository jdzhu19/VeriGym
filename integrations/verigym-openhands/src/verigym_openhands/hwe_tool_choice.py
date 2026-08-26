"""OpenHands LLM policies for bounded native HWE tool selection."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openhands.sdk.llm import (  # type: ignore[import-not-found]
    LLM,
    LLMResponse,
    Message,
    content_to_str,
)
from openhands.sdk.llm.llm import LLMCallContext  # type: ignore[import-not-found]
from openhands.sdk.llm.streaming import (  # type: ignore[import-not-found]
    AnyTokenCallbackType,
    TokenCallbackType,
)
from openhands.sdk.tool import ToolDefinition  # type: ignore[import-not-found]

from ._recovery import OPENHANDS_FORMAT_RECOVERY_MESSAGE
from .hwe_stop_hook import read_recovery_count

OPENHANDS_HWE_TOOL_CHOICE_REQUIRED = "required"
OPENHANDS_HWE_RECOVERY_FORCED_FINISH = "recovery_forced_finish"
OPENHANDS_HWE_RECOVERY_STATE_FORCED_FINISH = "recovery_state_forced_finish_v6"


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


def _recovery_finish_kwargs(
    messages: list[Message],
    tools: Sequence[ToolDefinition] | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Force only the recovery turn to express its existing completion intent as `finish`."""

    if "tool_choice" in kwargs:
        raise ValueError("OpenHands HWE recovery tool choice is adapter-owned")
    if not messages:
        return kwargs
    latest = messages[-1]
    content_parts = content_to_str(latest.content)
    recovery_turn = (
        latest.role == "user"
        and latest.tool_calls is None
        and bool(content_parts)
        and content_parts[-1] == OPENHANDS_FORMAT_RECOVERY_MESSAGE
    )
    if not recovery_turn:
        return kwargs
    finish_tools = [tool for tool in tools or [] if tool.name == "finish"]
    if len(finish_tools) != 1:
        raise ValueError("OpenHands HWE recovery requires exactly one finish tool")
    return {
        **kwargs,
        "tool_choice": {"type": "function", "function": {"name": "finish"}},
    }


class RecoveryForcedFinishLLM(LLM):  # type: ignore[misc]
    """Keep normal tool choice until the trusted Stop hook confirms completion intent."""

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
            **_recovery_finish_kwargs(messages, tools, kwargs),
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
            **_recovery_finish_kwargs(messages, tools, kwargs),
        )


def _recovery_state_finish_kwargs(
    recovery_state_path: Path,
    tools: Sequence[ToolDefinition] | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Force finish only after validating the Stop hook's private recovery receipt."""

    if "tool_choice" in kwargs:
        raise ValueError("OpenHands HWE recovery tool choice is adapter-owned")
    if read_recovery_count(recovery_state_path) == 0:
        return kwargs
    finish_tools = [tool for tool in tools or [] if tool.name == "finish"]
    if len(finish_tools) != 1:
        raise ValueError("OpenHands HWE recovery requires exactly one finish tool")
    return {
        **kwargs,
        "tool_choice": {"type": "function", "function": {"name": "finish"}},
    }


class RecoveryStateForcedFinishLLM(LLM):  # type: ignore[misc]
    """Bind recovery tool choice to the Stop hook's validated private state receipt."""

    recovery_state_path: Path

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
            **_recovery_state_finish_kwargs(self.recovery_state_path, tools, kwargs),
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
            **_recovery_state_finish_kwargs(self.recovery_state_path, tools, kwargs),
        )


__all__ = [
    "OPENHANDS_HWE_TOOL_CHOICE_REQUIRED",
    "OPENHANDS_HWE_RECOVERY_FORCED_FINISH",
    "OPENHANDS_HWE_RECOVERY_STATE_FORCED_FINISH",
    "RecoveryForcedFinishLLM",
    "RecoveryStateForcedFinishLLM",
    "RequiredToolChoiceLLM",
]
