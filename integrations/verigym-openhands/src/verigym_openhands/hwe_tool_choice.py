"""OpenHands LLM policies for bounded native HWE tool selection."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

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
from pydantic import PrivateAttr

from ._recovery import OPENHANDS_FORMAT_RECOVERY_MESSAGE
from .hwe_stop_hook import read_recovery_count

OPENHANDS_HWE_TOOL_CHOICE_REQUIRED = "required"
OPENHANDS_HWE_RECOVERY_FORCED_FINISH = "recovery_forced_finish"
OPENHANDS_HWE_RECOVERY_STATE_FORCED_FINISH = "recovery_state_forced_finish_v6"
OPENHANDS_HWE_VALIDATED_RECOVERY_STATE_FORCED_FINISH = "validated_recovery_state_forced_finish_v7"
OPENHANDS_HWE_VALIDATED_RESPONSES_RECOVERY_STATE_FORCED_FINISH = (
    "validated_responses_recovery_state_forced_finish_v9"
)
OPENHANDS_HWE_VALIDATED_RESPONSES_RECOVERY_STATE_REQUIRED_TOOL = (
    "validated_responses_recovery_state_required_tool_v11"
)

_RESPONSES_FINISH_TOOL_CHOICE = {"type": "function", "name": "finish"}
_RESPONSES_REQUIRED_TOOL_CHOICE = "required"


class RecoveryToolChoiceViolation(RuntimeError):
    """The provider violated the recovery turn's named-finish response contract."""


def _coalesce_responses_function_outputs(
    input_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Emit one text output per Responses function call without losing content.

    OpenHands SDK 1.42.1 emits one ``function_call_output`` item for every
    ``TextContent`` in a tool message.  A tool error, for example, contains a
    header block followed by its detail block.  The Responses protocol accepts
    only one output for a given ``call_id``, so adjacent blocks from the same
    OpenHands message must be joined before the recovery request is sent.

    Only adjacent string outputs are coalesced.  Reusing a call ID later in the
    history or encountering a non-text output remains a fail-closed error for
    this text-only HWE contract.
    """

    normalized: list[dict[str, Any]] = []
    closed_call_ids: set[str] = set()
    active_call_id: str | None = None
    coalesced = 0
    for original in input_items:
        item = dict(original)
        if item.get("type") != "function_call_output":
            if active_call_id is not None:
                closed_call_ids.add(active_call_id)
                active_call_id = None
            normalized.append(item)
            continue

        call_id = item.get("call_id")
        output = item.get("output")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("OpenHands Responses tool output lacks a call ID")
        if not isinstance(output, str):
            raise ValueError("OpenHands HWE Responses recovery requires text tool outputs")
        if active_call_id == call_id:
            previous = normalized[-1]
            previous_output = previous.get("output")
            if not isinstance(previous_output, str):
                raise ValueError("OpenHands Responses tool output merge state is invalid")
            previous["output"] = previous_output + output
            coalesced += 1
            continue
        if call_id in closed_call_ids:
            raise ValueError("OpenHands Responses history reused a closed tool call ID")
        if active_call_id is not None:
            closed_call_ids.add(active_call_id)
        active_call_id = call_id
        normalized.append(item)

    return normalized, coalesced


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
) -> tuple[dict[str, Any], bool]:
    """Force finish only after validating the Stop hook's private recovery receipt."""

    if "tool_choice" in kwargs:
        raise ValueError("OpenHands HWE recovery tool choice is adapter-owned")
    if read_recovery_count(recovery_state_path) == 0:
        return kwargs, False
    finish_tools = [tool for tool in tools or [] if tool.name == "finish"]
    if len(finish_tools) != 1:
        raise ValueError("OpenHands HWE recovery requires exactly one finish tool")
    return (
        {
            **kwargs,
            "tool_choice": {"type": "function", "function": {"name": "finish"}},
        },
        True,
    )


def _validate_recovery_finish_response(response: LLMResponse) -> None:
    calls = response.message.tool_calls or []
    if len(calls) != 1 or calls[0].name != "finish":
        raise RecoveryToolChoiceViolation(
            "OpenHands HWE recovery response was not exactly one finish tool call"
        )


def _validate_recovery_required_tool_response(
    response: LLMResponse, *, allowed_tool_names: frozenset[str]
) -> None:
    calls = response.message.tool_calls or []
    text_parts = content_to_str(response.message.content)
    if len(calls) != 1 or calls[0].name not in allowed_tool_names or bool(text_parts):
        raise RecoveryToolChoiceViolation(
            "OpenHands HWE recovery response was not exactly one allowed tool call"
        )


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
        request_kwargs, _forced = _recovery_state_finish_kwargs(
            self.recovery_state_path, tools, kwargs
        )
        return super().completion(
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            **request_kwargs,
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
        request_kwargs, _forced = _recovery_state_finish_kwargs(
            self.recovery_state_path, tools, kwargs
        )
        return await super().acompletion(
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            **request_kwargs,
        )


class ValidatedRecoveryStateForcedFinishLLM(LLM):  # type: ignore[misc]
    """Require the provider to honor the recovery turn's named finish choice."""

    recovery_state_path: Path
    _recovery_forced_request_count: int = PrivateAttr(default=0)
    _recovery_validated_finish_count: int = PrivateAttr(default=0)

    @property
    def recovery_forced_request_count(self) -> int:
        return self._recovery_forced_request_count

    @property
    def recovery_validated_finish_count(self) -> int:
        return self._recovery_validated_finish_count

    def completion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: TokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request_kwargs, forced = _recovery_state_finish_kwargs(
            self.recovery_state_path, tools, kwargs
        )
        if forced:
            self._recovery_forced_request_count += 1
        response = super().completion(
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            **request_kwargs,
        )
        if forced:
            _validate_recovery_finish_response(response)
            self._recovery_validated_finish_count += 1
        return response

    async def acompletion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: AnyTokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request_kwargs, forced = _recovery_state_finish_kwargs(
            self.recovery_state_path, tools, kwargs
        )
        if forced:
            self._recovery_forced_request_count += 1
        response = await super().acompletion(
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            **request_kwargs,
        )
        if forced:
            _validate_recovery_finish_response(response)
            self._recovery_validated_finish_count += 1
        return response


class ValidatedResponsesRecoveryStateForcedFinishLLM(LLM):  # type: ignore[misc]
    """Use DeepSeek's Responses API only for the receipt-bound finish turn.

    Ordinary OpenHands turns retain the frozen Chat Completions path.  After the
    trusted Stop hook writes its private recovery receipt, the same full message
    history and exact tool contract are converted by the SDK's public Responses
    serializer and sent with a named ``finish`` choice.  The provider must still
    emit the typed call; this class never synthesizes a finish action.
    """

    recovery_state_path: Path
    _recovery_forced_request_count: int = PrivateAttr(default=0)
    _recovery_validated_finish_count: int = PrivateAttr(default=0)
    _recovery_coalesced_output_count: int = PrivateAttr(default=0)
    _recovery_allowed_tool_names: tuple[str, ...] = PrivateAttr(default=())
    _recovery_response_shape: dict[str, Any] = PrivateAttr(default_factory=dict)

    @property
    def recovery_forced_request_count(self) -> int:
        return self._recovery_forced_request_count

    @property
    def recovery_validated_finish_count(self) -> int:
        return self._recovery_validated_finish_count

    @property
    def recovery_coalesced_output_count(self) -> int:
        return self._recovery_coalesced_output_count

    @property
    def recovery_response_shape(self) -> dict[str, Any]:
        return dict(self._recovery_response_shape)

    def _safe_response_name(self, value: Any) -> str:
        if isinstance(value, str) and value in self._recovery_allowed_tool_names:
            return value
        if isinstance(value, str):
            return "unexpected_sha256:" + hashlib.sha256(value.encode()).hexdigest()
        return "missing"

    def _build_responses_result(self, resp: Any) -> LLMResponse:
        """Capture content-free raw and converted response structure."""

        output = getattr(resp, "output", None) or []
        raw_types: list[str] = []
        raw_function_names: list[str] = []
        for item in list(output)[:16]:
            item_type = getattr(item, "type", None)
            if not isinstance(item_type, str) and isinstance(item, dict):
                item_type = item.get("type")
            if item_type in {"function_call", "message", "reasoning"}:
                raw_types.append(item_type)
            elif isinstance(item_type, str):
                raw_types.append(
                    "unexpected_sha256:" + hashlib.sha256(item_type.encode()).hexdigest()
                )
            else:
                raw_types.append("missing")
            if item_type == "function_call":
                name = getattr(item, "name", None)
                if name is None and isinstance(item, dict):
                    name = item.get("name")
                raw_function_names.append(self._safe_response_name(name))

        result = super()._build_responses_result(resp)
        converted_calls = result.message.tool_calls or []
        self._recovery_response_shape = {
            "raw_output_count": len(output),
            "raw_output_types": raw_types,
            "raw_function_names": raw_function_names,
            "converted_tool_call_count": len(converted_calls),
            "converted_tool_names": [
                self._safe_response_name(call.name) for call in converted_calls[:16]
            ],
            "converted_text_part_count": len(content_to_str(result.message.content)),
        }
        return result

    def _finalize_responses_params(
        self,
        instructions: str | None,
        input_items: list[dict[str, Any]],
        tools: Sequence[ToolDefinition] | None,
        include: list[str] | None,
        store: bool | None,
        add_security_risk_prediction: bool,
        kwargs: dict[str, Any],
        call_context: LLMCallContext | None = None,
    ) -> tuple[
        str | None,
        list[dict[str, Any]],
        list[Any] | None,
        dict[str, Any],
        dict[str, Any],
    ]:
        requested = kwargs.get("tool_choice")
        result = cast(
            tuple[
                str | None,
                list[dict[str, Any]],
                list[Any] | None,
                dict[str, Any],
                dict[str, Any],
            ],
            super()._finalize_responses_params(
                instructions,
                input_items,
                tools,
                include,
                store,
                add_security_risk_prediction,
                kwargs,
                call_context=call_context,
            ),
        )
        if (
            requested != _RESPONSES_REQUIRED_TOOL_CHOICE
            and requested != _RESPONSES_FINISH_TOOL_CHOICE
        ):
            return result

        resolved_instructions, resolved_input, resolved_tools, call_kwargs, telemetry = result
        self._recovery_allowed_tool_names = tuple(sorted(tool.name for tool in tools or []))
        normalized_input, coalesced = _coalesce_responses_function_outputs(resolved_input)
        self._recovery_coalesced_output_count = coalesced
        # OpenHands SDK 1.42.1 currently overwrites Responses tool_choice with
        # ``auto``. Rebind the adapter-owned named choice after the public SDK
        # serializer has completed, without modifying the installed package.
        rebound = dict(call_kwargs)
        rebound["tool_choice"] = (
            dict(_RESPONSES_FINISH_TOOL_CHOICE)
            if requested == _RESPONSES_FINISH_TOOL_CHOICE
            else _RESPONSES_REQUIRED_TOOL_CHOICE
        )
        rebound.pop("extra_body", None)
        rebound["reasoning"] = {"effort": "none"}
        rebound["store"] = False
        return (
            resolved_instructions,
            normalized_input,
            resolved_tools,
            rebound,
            telemetry,
        )

    def completion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: TokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request_kwargs, forced = _recovery_state_finish_kwargs(
            self.recovery_state_path, tools, kwargs
        )
        if not forced:
            return super().completion(
                messages=messages,
                tools=tools,
                add_security_risk_prediction=add_security_risk_prediction,
                on_token=on_token,
                call_context=call_context,
                **request_kwargs,
            )
        self._recovery_forced_request_count += 1
        request_kwargs.pop("tool_choice")
        response = super().responses(
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            tool_choice=dict(_RESPONSES_FINISH_TOOL_CHOICE),
            **request_kwargs,
        )
        _validate_recovery_finish_response(response)
        self._recovery_validated_finish_count += 1
        return response

    async def acompletion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: AnyTokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request_kwargs, forced = _recovery_state_finish_kwargs(
            self.recovery_state_path, tools, kwargs
        )
        if not forced:
            return await super().acompletion(
                messages=messages,
                tools=tools,
                add_security_risk_prediction=add_security_risk_prediction,
                on_token=on_token,
                call_context=call_context,
                **request_kwargs,
            )
        self._recovery_forced_request_count += 1
        request_kwargs.pop("tool_choice")
        response = await super().aresponses(
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            tool_choice=dict(_RESPONSES_FINISH_TOOL_CHOICE),
            **request_kwargs,
        )
        _validate_recovery_finish_response(response)
        self._recovery_validated_finish_count += 1
        return response


class ValidatedResponsesRecoveryStateRequiredToolLLM(
    ValidatedResponsesRecoveryStateForcedFinishLLM
):
    """Require one known tool on the single receipt-bound recovery turn.

    A successful recovery may continue the agent loop with a non-terminal tool.
    The persistent hook receipt is consumed in-memory exactly once; subsequent
    turns return to the ordinary Chat Completions path.
    """

    _recovery_validated_tool_count: int = PrivateAttr(default=0)

    @property
    def recovery_validated_tool_count(self) -> int:
        return self._recovery_validated_tool_count

    def _recovery_required(self) -> bool:
        return (
            self._recovery_forced_request_count == 0
            and read_recovery_count(self.recovery_state_path) == 1
        )

    def completion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: TokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if "tool_choice" in kwargs:
            raise ValueError("OpenHands HWE recovery tool choice is adapter-owned")
        if not self._recovery_required():
            return LLM.completion(
                self,
                messages=messages,
                tools=tools,
                add_security_risk_prediction=add_security_risk_prediction,
                on_token=on_token,
                call_context=call_context,
                **kwargs,
            )
        allowed = frozenset(tool.name for tool in tools or [])
        if not allowed:
            raise ValueError("OpenHands HWE recovery requires a non-empty tool contract")
        self._recovery_forced_request_count += 1
        response = LLM.responses(
            self,
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            tool_choice=_RESPONSES_REQUIRED_TOOL_CHOICE,
            **kwargs,
        )
        _validate_recovery_required_tool_response(response, allowed_tool_names=allowed)
        self._recovery_validated_tool_count += 1
        return response

    async def acompletion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: AnyTokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if "tool_choice" in kwargs:
            raise ValueError("OpenHands HWE recovery tool choice is adapter-owned")
        if not self._recovery_required():
            return await LLM.acompletion(
                self,
                messages=messages,
                tools=tools,
                add_security_risk_prediction=add_security_risk_prediction,
                on_token=on_token,
                call_context=call_context,
                **kwargs,
            )
        allowed = frozenset(tool.name for tool in tools or [])
        if not allowed:
            raise ValueError("OpenHands HWE recovery requires a non-empty tool contract")
        self._recovery_forced_request_count += 1
        response = await LLM.aresponses(
            self,
            messages=messages,
            tools=tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            tool_choice=_RESPONSES_REQUIRED_TOOL_CHOICE,
            **kwargs,
        )
        _validate_recovery_required_tool_response(response, allowed_tool_names=allowed)
        self._recovery_validated_tool_count += 1
        return response


__all__ = [
    "OPENHANDS_HWE_TOOL_CHOICE_REQUIRED",
    "OPENHANDS_HWE_RECOVERY_FORCED_FINISH",
    "OPENHANDS_HWE_RECOVERY_STATE_FORCED_FINISH",
    "OPENHANDS_HWE_VALIDATED_RECOVERY_STATE_FORCED_FINISH",
    "OPENHANDS_HWE_VALIDATED_RESPONSES_RECOVERY_STATE_FORCED_FINISH",
    "OPENHANDS_HWE_VALIDATED_RESPONSES_RECOVERY_STATE_REQUIRED_TOOL",
    "RecoveryForcedFinishLLM",
    "RecoveryStateForcedFinishLLM",
    "RecoveryToolChoiceViolation",
    "RequiredToolChoiceLLM",
    "ValidatedRecoveryStateForcedFinishLLM",
    "ValidatedResponsesRecoveryStateForcedFinishLLM",
    "ValidatedResponsesRecoveryStateRequiredToolLLM",
]
