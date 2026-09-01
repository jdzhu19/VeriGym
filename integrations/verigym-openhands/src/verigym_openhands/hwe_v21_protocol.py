"""V21 required-tool protocol with atomic multiple-call shape recovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from openhands.sdk.llm import LLMResponse, Message, TextContent, content_to_str
from openhands.sdk.tool import ToolDefinition as GenericToolDefinition
from pydantic import PrivateAttr
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID, canonical_hwe_action_json

from .hwe_stop_hook import read_recovery_count
from .hwe_tool_choice import _required_tool_choice_kwargs
from .hwe_v20_protocol import (
    OPENHANDS_V20_MAX_CONTEXT_TOKENS,
    OPENHANDS_V20_MAX_OUTPUT_TOKENS,
    OPENHANDS_V20_MAX_PROVIDER_CALLS,
    OPENHANDS_V20_MAX_PROVIDER_TOKENS,
    V20RequiredToolPublicThoughtLLM,
)

type ToolDefinition = GenericToolDefinition[Any, Any]

OPENHANDS_V21_TOOL_CHOICE_POLICY = "required_tool_atomic_shape_recovery_v21"
OPENHANDS_V21_MAX_PROVIDER_CALLS = OPENHANDS_V20_MAX_PROVIDER_CALLS
OPENHANDS_V21_MAX_PROVIDER_TOKENS = OPENHANDS_V20_MAX_PROVIDER_TOKENS
OPENHANDS_V21_MAX_CONTEXT_TOKENS = OPENHANDS_V20_MAX_CONTEXT_TOKENS
OPENHANDS_V21_MAX_OUTPUT_TOKENS = OPENHANDS_V20_MAX_OUTPUT_TOKENS
OPENHANDS_V21_CONTENT_RECOVERY_BUDGET = 1
OPENHANDS_V21_MULTI_TOOL_SHAPE_RECOVERY_BUDGET = 1
OPENHANDS_V21_RECOVERABLE_TOOL_CALL_COUNT = 2
OPENHANDS_V21_MULTI_TOOL_RECOVERY_MESSAGE = (
    "[Adapter response-shape rejection] A provider response containing two tool calls was "
    "rejected atomically before dispatch; neither call was executed."
)
OPENHANDS_V21_MULTI_TOOL_RECOVERY_MESSAGE_SHA256 = hashlib.sha256(
    OPENHANDS_V21_MULTI_TOOL_RECOVERY_MESSAGE.encode()
).hexdigest()

_HWE_TOOL_NAMES = frozenset(
    {"apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell"}
)


class V21ProtocolViolation(RuntimeError):
    """The provider response cannot enter the v21 OpenHands or broker state machine."""


class V21ProviderTokenBudgetExceeded(V21ProtocolViolation):
    """A completed provider response crossed the cumulative v21 token budget."""


class V21PseudoFinishViolation(V21ProtocolViolation):
    """A provider-emitted finish call was not a canonical HWE finish action."""


class V21RequiredToolAtomicShapeRecoveryLLM(V20RequiredToolPublicThoughtLLM):
    """Dispatch one canonical tool or recover one exact two-call response shape.

    The recoverable shape is deliberately narrow: exactly two tool calls, no
    visible text, no private reasoning, and no previous recovery. Both calls are
    discarded before OpenHands dispatch. A fixed argument-free assistant message
    enters the existing trusted Stop-hook path, which supplies the sole model-
    visible environment correction. The next response must satisfy the ordinary
    exact-one canonical-tool contract or the episode fails closed.
    """

    _multi_tool_shape_recovery_count: int = PrivateAttr(default=0)
    _rejected_provider_tool_call_count: int = PrivateAttr(default=0)
    _multi_tool_recovery_response_shape: dict[str, Any] = PrivateAttr(default_factory=dict)

    @property
    def multi_tool_shape_recovery_count(self) -> int:
        return self._multi_tool_shape_recovery_count

    @property
    def rejected_provider_tool_call_count(self) -> int:
        return self._rejected_provider_tool_call_count

    @property
    def multi_tool_recovery_response_shape(self) -> dict[str, Any]:
        return dict(self._multi_tool_recovery_response_shape)

    def _prepare_request(
        self,
        tools: Sequence[ToolDefinition] | None,
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        self._validate_exact_tools(tools)
        recovery_count = read_recovery_count(self.recovery_state_path)
        content_recoveries = self._content_only_response_count
        shape_recoveries = self._multi_tool_shape_recovery_count
        if content_recoveries not in {0, 1} or shape_recoveries not in {0, 1}:
            raise V21ProtocolViolation("OpenHands v21 recovery counters drifted")
        if content_recoveries + shape_recoveries not in {0, 1}:
            raise V21ProtocolViolation("OpenHands v21 combined recovery budget drifted")
        if recovery_count != content_recoveries + shape_recoveries:
            raise V21ProtocolViolation("OpenHands v21 recovery state does not match provider shape")
        recovery_request = recovery_count == 1 and self._recovery_forced_request_count == 0
        if self._recovery_forced_request_count not in {0, 1} or (
            self._recovery_validated_tool_count > self._recovery_forced_request_count
        ):
            raise V21ProtocolViolation("OpenHands v21 recovery request counters drifted")
        try:
            request = _required_tool_choice_kwargs(tools, dict(kwargs))
        except ValueError as exc:
            raise V21ProtocolViolation(
                "OpenHands v21 required-tool request policy was weakened"
            ) from exc
        return request, recovery_request

    def _record_claimed_request(self, before: int, *, recovery_request: bool) -> None:
        after = self.provider_call_count
        if after == before:
            return
        if after != before + 1:
            raise V21ProtocolViolation("OpenHands v21 provider request counter drifted")
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
        nonempty_text_part_count = sum(bool(part) for part in text_parts)
        has_text = nonempty_text_part_count > 0
        shape = self._safe_response_shape(
            response,
            call_count=len(calls),
            text_part_count=len(text_parts),
            nonempty_text_part_count=nonempty_text_part_count,
        )
        self._provider_response_shape = shape

        token_total = self._current_provider_tokens()
        if token_total is None:
            raise V21ProtocolViolation("OpenHands v21 provider token accounting is unavailable")
        if token_total > self.max_provider_tokens:
            self._over_budget_response_count += 1
            raise V21ProviderTokenBudgetExceeded(
                "OpenHands v21 cumulative provider token budget was exceeded"
            )

        self._validate_provider_response(response)
        message = response.message
        has_private_reasoning = (
            message.reasoning_content is not None
            or message.responses_reasoning_item is not None
            or bool(message.thinking_blocks)
        )
        if has_private_reasoning:
            raise V21ProtocolViolation(
                "OpenHands v21 provider emitted private reasoning outside public thought"
            )
        if not calls and has_text:
            self._content_only_response_count += 1
            if (
                recovery_request
                or self._content_only_response_count + self._multi_tool_shape_recovery_count > 1
            ):
                raise V21ProtocolViolation(
                    "OpenHands v21 received a second recoverable provider response"
                )
            return response
        if not calls:
            raise V21ProtocolViolation("OpenHands v21 provider response was empty")
        if len(calls) == OPENHANDS_V21_RECOVERABLE_TOOL_CALL_COUNT and not text_parts:
            if (
                recovery_request
                or self._content_only_response_count
                or self._multi_tool_shape_recovery_count
            ):
                raise V21ProtocolViolation(
                    "OpenHands v21 received multiple tool calls after recovery was consumed"
                )
            self._multi_tool_shape_recovery_count = 1
            self._rejected_provider_tool_call_count = len(calls)
            self._multi_tool_recovery_response_shape = shape
            return response.model_copy(
                update={
                    "message": Message(
                        role="assistant",
                        content=[TextContent(text=OPENHANDS_V21_MULTI_TOOL_RECOVERY_MESSAGE)],
                    )
                }
            )
        if len(calls) != 1:
            raise V21ProtocolViolation(
                "OpenHands v21 provider response did not contain exactly one tool call"
            )

        call = calls[0]
        allowed = frozenset(tool.name for tool in tools or [])
        if call.name not in allowed or call.name not in _HWE_TOOL_NAMES:
            raise V21ProtocolViolation("OpenHands v21 provider emitted an illegal tool")
        try:
            arguments = _strict_json_object(call.arguments)
            canonical_hwe_action_json(
                call.name,
                arguments,
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
        except (TypeError, ValueError) as exc:
            if call.name == "finish":
                raise V21PseudoFinishViolation(
                    "OpenHands v21 provider emitted a non-canonical finish"
                ) from exc
            raise V21ProtocolViolation(
                "OpenHands v21 provider emitted non-canonical tool arguments"
            ) from exc
        self._canonical_tool_response_count += 1
        if has_text:
            self._mixed_content_tool_response_count += 1
        if recovery_request:
            self._recovery_validated_tool_count += 1
        return response

    @staticmethod
    def _validate_exact_tools(tools: Sequence[ToolDefinition] | None) -> None:
        names = [tool.name for tool in tools or []]
        if len(names) != len(_HWE_TOOL_NAMES) or frozenset(names) != _HWE_TOOL_NAMES:
            raise V21ProtocolViolation("OpenHands v21 requires the exact six-tool contract")


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
    "OPENHANDS_V21_CONTENT_RECOVERY_BUDGET",
    "OPENHANDS_V21_MAX_CONTEXT_TOKENS",
    "OPENHANDS_V21_MAX_OUTPUT_TOKENS",
    "OPENHANDS_V21_MAX_PROVIDER_CALLS",
    "OPENHANDS_V21_MAX_PROVIDER_TOKENS",
    "OPENHANDS_V21_MULTI_TOOL_RECOVERY_MESSAGE",
    "OPENHANDS_V21_MULTI_TOOL_RECOVERY_MESSAGE_SHA256",
    "OPENHANDS_V21_MULTI_TOOL_SHAPE_RECOVERY_BUDGET",
    "OPENHANDS_V21_RECOVERABLE_TOOL_CALL_COUNT",
    "OPENHANDS_V21_TOOL_CHOICE_POLICY",
    "V21ProtocolViolation",
    "V21ProviderTokenBudgetExceeded",
    "V21PseudoFinishViolation",
    "V21RequiredToolAtomicShapeRecoveryLLM",
]
