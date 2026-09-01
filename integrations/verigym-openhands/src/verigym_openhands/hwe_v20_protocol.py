"""Successor required-tool protocol for provider tool calls with public thought text."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from openhands.sdk.llm import LLMResponse, content_to_str
from openhands.sdk.tool import ToolDefinition as GenericToolDefinition
from pydantic import PrivateAttr
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID, canonical_hwe_action_json

from .hwe_stop_hook import read_recovery_count
from .hwe_tool_choice import _required_tool_choice_kwargs
from .hwe_v19_protocol import (
    OPENHANDS_V19_MAX_CONTEXT_TOKENS,
    OPENHANDS_V19_MAX_OUTPUT_TOKENS,
    OPENHANDS_V19_MAX_PROVIDER_CALLS,
    OPENHANDS_V19_MAX_PROVIDER_TOKENS,
    V19RequiredToolContentRecoveryLLM,
)

type ToolDefinition = GenericToolDefinition[Any, Any]

OPENHANDS_V20_TOOL_CHOICE_POLICY = "required_tool_public_thought_content_recovery_v20"
OPENHANDS_V20_MAX_PROVIDER_CALLS = OPENHANDS_V19_MAX_PROVIDER_CALLS
OPENHANDS_V20_MAX_PROVIDER_TOKENS = OPENHANDS_V19_MAX_PROVIDER_TOKENS
OPENHANDS_V20_MAX_CONTEXT_TOKENS = OPENHANDS_V19_MAX_CONTEXT_TOKENS
OPENHANDS_V20_MAX_OUTPUT_TOKENS = OPENHANDS_V19_MAX_OUTPUT_TOKENS
OPENHANDS_V20_CONTENT_RECOVERY_BUDGET = 1

_HWE_TOOL_NAMES = frozenset(
    {"apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell"}
)


class V20ProtocolViolation(RuntimeError):
    """The provider response cannot enter the v20 OpenHands or broker state machine."""


class V20ProviderTokenBudgetExceeded(V20ProtocolViolation):
    """A completed provider response crossed the cumulative v20 token budget."""


class V20PseudoFinishViolation(V20ProtocolViolation):
    """A provider-emitted finish call was not a canonical HWE finish action."""


class V20RequiredToolPublicThoughtLLM(V19RequiredToolContentRecoveryLLM):
    """Accept one canonical tool call with optional public assistant thought text.

    OpenHands SDK 1.42.1 treats tool calls as authoritative when a response also
    contains text and attaches that text to the first ActionEvent as public thought.
    V20 follows that upstream response model while preserving v19's exact tool set,
    one-call-per-decision rule, one content-only recovery, and token accounting.
    """

    _mixed_content_tool_response_count: int = PrivateAttr(default=0)
    _provider_response_shape: dict[str, Any] = PrivateAttr(default_factory=dict)

    @property
    def mixed_content_tool_response_count(self) -> int:
        return self._mixed_content_tool_response_count

    @property
    def content_free_tool_response_count(self) -> int:
        return self.canonical_tool_response_count - self._mixed_content_tool_response_count

    @property
    def provider_response_shape(self) -> dict[str, Any]:
        return dict(self._provider_response_shape)

    def _prepare_request(
        self,
        tools: Sequence[ToolDefinition] | None,
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        self._validate_exact_tools(tools)
        recovery_count = read_recovery_count(self.recovery_state_path)
        if self._content_only_response_count not in {0, 1}:
            raise V20ProtocolViolation("OpenHands v20 content-only counter drifted")
        if recovery_count != self._content_only_response_count:
            raise V20ProtocolViolation("OpenHands v20 recovery state does not match provider text")
        recovery_request = recovery_count == 1 and self._recovery_forced_request_count == 0
        if self._recovery_forced_request_count not in {0, 1} or (
            self._recovery_validated_tool_count > self._recovery_forced_request_count
        ):
            raise V20ProtocolViolation("OpenHands v20 recovery request counters drifted")
        try:
            request = _required_tool_choice_kwargs(tools, dict(kwargs))
        except ValueError as exc:
            raise V20ProtocolViolation(
                "OpenHands v20 required-tool request policy was weakened"
            ) from exc
        return request, recovery_request

    def _record_claimed_request(self, before: int, *, recovery_request: bool) -> None:
        after = self.provider_call_count
        if after == before:
            return
        if after != before + 1:
            raise V20ProtocolViolation("OpenHands v20 provider request counter drifted")
        self._required_tool_request_count += 1
        if recovery_request:
            self._recovery_forced_request_count += 1

    def _accept_response(
        self,
        response: LLMResponse,
        *,
        tools: Sequence[ToolDefinition] | None,
        recovery_request: bool,
    ) -> LLMResponse:
        calls = response.message.tool_calls or []
        text_parts = content_to_str(response.message.content)
        has_text = any(part for part in text_parts)
        self._provider_response_shape = self._safe_response_shape(
            response,
            call_count=len(calls),
            text_part_count=len(text_parts),
            nonempty_text_part_count=sum(bool(part) for part in text_parts),
        )

        token_total = self._current_provider_tokens()
        if token_total is None:
            raise V20ProtocolViolation("OpenHands v20 provider token accounting is unavailable")
        if token_total > self.max_provider_tokens:
            self._over_budget_response_count += 1
            raise V20ProviderTokenBudgetExceeded(
                "OpenHands v20 cumulative provider token budget was exceeded"
            )

        self._validate_provider_response(response)
        if (
            response.message.reasoning_content is not None
            or response.message.responses_reasoning_item is not None
            or response.message.thinking_blocks
        ):
            raise V20ProtocolViolation(
                "OpenHands v20 provider emitted private reasoning outside public thought"
            )
        if not calls and has_text:
            self._content_only_response_count += 1
            if recovery_request or self._content_only_response_count > 1:
                raise V20ProtocolViolation(
                    "OpenHands v20 received a second content-only provider response"
                )
            return response
        if not calls:
            raise V20ProtocolViolation("OpenHands v20 provider response was empty")
        if len(calls) != 1:
            raise V20ProtocolViolation(
                "OpenHands v20 provider response did not contain exactly one tool call"
            )

        call = calls[0]
        allowed = frozenset(tool.name for tool in tools or [])
        if call.name not in allowed or call.name not in _HWE_TOOL_NAMES:
            raise V20ProtocolViolation("OpenHands v20 provider emitted an illegal tool")
        try:
            arguments = _strict_json_object(call.arguments)
            canonical_hwe_action_json(
                call.name,
                arguments,
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
        except (TypeError, ValueError) as exc:
            if call.name == "finish":
                raise V20PseudoFinishViolation(
                    "OpenHands v20 provider emitted a non-canonical finish"
                ) from exc
            raise V20ProtocolViolation(
                "OpenHands v20 provider emitted non-canonical tool arguments"
            ) from exc
        self._canonical_tool_response_count += 1
        if has_text:
            self._mixed_content_tool_response_count += 1
        if recovery_request:
            self._recovery_validated_tool_count += 1
        return response

    @staticmethod
    def _safe_response_shape(
        response: LLMResponse,
        *,
        call_count: int,
        text_part_count: int,
        nonempty_text_part_count: int,
    ) -> dict[str, Any]:
        message = response.message
        if call_count:
            classification = "tool_calls_with_content" if nonempty_text_part_count else "tool_calls"
        elif nonempty_text_part_count:
            classification = "content_only"
        elif (
            getattr(message, "reasoning_content", None) is not None
            or getattr(message, "responses_reasoning_item", None) is not None
            or bool(getattr(message, "thinking_blocks", None))
        ):
            classification = "reasoning_only"
        else:
            classification = "empty"
        return {
            "classification": classification,
            "tool_call_count": call_count,
            "text_part_count": text_part_count,
            "nonempty_text_part_count": nonempty_text_part_count,
            "reasoning_content_present": getattr(message, "reasoning_content", None) is not None,
            "responses_reasoning_present": (
                getattr(message, "responses_reasoning_item", None) is not None
            ),
            "thinking_blocks_present": bool(getattr(message, "thinking_blocks", None)),
            "raw_model_content_persisted": False,
            "raw_tool_arguments_persisted": False,
        }

    @staticmethod
    def _validate_exact_tools(tools: Sequence[ToolDefinition] | None) -> None:
        names = [tool.name for tool in tools or []]
        if len(names) != len(_HWE_TOOL_NAMES) or frozenset(names) != _HWE_TOOL_NAMES:
            raise V20ProtocolViolation("OpenHands v20 requires the exact six-tool contract")


def _strict_json_object(value: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    decoded = json.loads(
        value,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )
    if not isinstance(decoded, dict):
        raise ValueError("tool arguments are not an object")
    return decoded


__all__ = [
    "OPENHANDS_V20_CONTENT_RECOVERY_BUDGET",
    "OPENHANDS_V20_MAX_CONTEXT_TOKENS",
    "OPENHANDS_V20_MAX_OUTPUT_TOKENS",
    "OPENHANDS_V20_MAX_PROVIDER_CALLS",
    "OPENHANDS_V20_MAX_PROVIDER_TOKENS",
    "OPENHANDS_V20_TOOL_CHOICE_POLICY",
    "V20ProtocolViolation",
    "V20ProviderTokenBudgetExceeded",
    "V20PseudoFinishViolation",
    "V20RequiredToolPublicThoughtLLM",
]
