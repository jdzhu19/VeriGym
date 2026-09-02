"""V23 auto-tool protocol with public thought and atomic sibling validation."""

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
from .hwe_v20_protocol import (
    OPENHANDS_V20_MAX_CONTEXT_TOKENS,
    OPENHANDS_V20_MAX_OUTPUT_TOKENS,
    OPENHANDS_V20_MAX_PROVIDER_CALLS,
    OPENHANDS_V20_MAX_PROVIDER_TOKENS,
    V20RequiredToolPublicThoughtLLM,
)

type ToolDefinition = GenericToolDefinition[Any, Any]

OPENHANDS_V23_TOOL_CHOICE_POLICY = "auto_public_thought_atomic_recovery_v23"
OPENHANDS_V23_MAX_PROVIDER_CALLS = OPENHANDS_V20_MAX_PROVIDER_CALLS
OPENHANDS_V23_MAX_PROVIDER_TOKENS = OPENHANDS_V20_MAX_PROVIDER_TOKENS
OPENHANDS_V23_MAX_CONTEXT_TOKENS = OPENHANDS_V20_MAX_CONTEXT_TOKENS
OPENHANDS_V23_MAX_OUTPUT_TOKENS = OPENHANDS_V20_MAX_OUTPUT_TOKENS
OPENHANDS_V23_CONTENT_RECOVERY_BUDGET = 1

_HWE_TOOL_NAMES = frozenset(
    {"apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell"}
)


class V23ProtocolViolation(RuntimeError):
    """The provider response cannot enter the v23 agent or broker state machine."""


class V23ProviderTokenBudgetExceeded(V23ProtocolViolation):
    """A completed provider response crossed the cumulative v23 token budget."""


class V23PseudoFinishViolation(V23ProtocolViolation):
    """A provider-emitted finish call was not a canonical HWE finish action."""


class V23AutoPublicThoughtAtomicRecoveryLLM(V20RequiredToolPublicThoughtLLM):
    """Use provider-default auto tools and prevalidate every sibling atomically.

    Ordinary requests deliberately omit ``tool_choice``.  After the one allowed
    content-only response has been retained by OpenHands and its trusted Stop
    hook has written the private recovery receipt, exactly one recovery request
    uses ``tool_choice=required``.  Every call in an ordinary sibling decision is
    validated before this method returns the response to OpenHands, so a bad
    sibling prevents the complete decision from reaching tool dispatch.
    """

    _ordinary_auto_request_count: int = PrivateAttr(default=0)
    _canonical_tool_call_count: int = PrivateAttr(default=0)
    _public_text_decision_count: int = PrivateAttr(default=0)
    _sibling_tool_decision_count: int = PrivateAttr(default=0)
    _sibling_tool_call_count: int = PrivateAttr(default=0)
    _decision_tool_call_counts: list[int] = PrivateAttr(default_factory=list)

    @property
    def ordinary_auto_request_count(self) -> int:
        return self._ordinary_auto_request_count

    @property
    def canonical_tool_decision_count(self) -> int:
        return self.canonical_tool_response_count

    @property
    def canonical_tool_call_count(self) -> int:
        return self._canonical_tool_call_count

    @property
    def public_text_decision_count(self) -> int:
        return self._public_text_decision_count

    @property
    def sibling_tool_decision_count(self) -> int:
        return self._sibling_tool_decision_count

    @property
    def sibling_tool_call_count(self) -> int:
        return self._sibling_tool_call_count

    @property
    def decision_tool_call_counts(self) -> tuple[int, ...]:
        return tuple(self._decision_tool_call_counts)

    def _prepare_request(
        self,
        tools: Sequence[ToolDefinition] | None,
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        self._validate_exact_tools(tools)
        if "tool_choice" in kwargs:
            raise V23ProtocolViolation("OpenHands v23 tool choice is adapter-owned")
        recovery_count = read_recovery_count(self.recovery_state_path)
        if self._content_only_response_count not in {0, 1}:
            raise V23ProtocolViolation("OpenHands v23 content-only counter drifted")
        if recovery_count != self._content_only_response_count:
            raise V23ProtocolViolation("OpenHands v23 recovery state does not match provider text")
        recovery_request = recovery_count == 1 and self._recovery_forced_request_count == 0
        if self._recovery_forced_request_count not in {0, 1} or (
            self._recovery_validated_tool_count > self._recovery_forced_request_count
        ):
            raise V23ProtocolViolation("OpenHands v23 recovery request counters drifted")
        if not recovery_request:
            return dict(kwargs), False
        try:
            return _required_tool_choice_kwargs(tools, dict(kwargs)), True
        except ValueError as exc:
            raise V23ProtocolViolation("OpenHands v23 recovery tool choice was weakened") from exc

    def _record_claimed_request(self, before: int, *, recovery_request: bool) -> None:
        after = self.provider_call_count
        if after == before:
            return
        if after != before + 1:
            raise V23ProtocolViolation("OpenHands v23 provider request counter drifted")
        if recovery_request:
            self._required_tool_request_count += 1
            self._recovery_forced_request_count += 1
        else:
            self._ordinary_auto_request_count += 1

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
        self._provider_response_shape = self._safe_response_shape(
            response,
            call_count=len(calls),
            text_part_count=len(text_parts),
            nonempty_text_part_count=nonempty_text_part_count,
        )

        token_total = self._current_provider_tokens()
        if token_total is None:
            raise V23ProtocolViolation("OpenHands v23 provider token accounting is unavailable")
        if token_total > self.max_provider_tokens:
            self._over_budget_response_count += 1
            raise V23ProviderTokenBudgetExceeded(
                "OpenHands v23 cumulative provider token budget was exceeded"
            )

        self._validate_provider_response(response)
        message = response.message
        if (
            message.reasoning_content is not None
            or message.responses_reasoning_item is not None
            or bool(message.thinking_blocks)
        ):
            raise V23ProtocolViolation(
                "OpenHands v23 provider emitted private reasoning outside public thought"
            )
        if not calls and has_text:
            self._content_only_response_count += 1
            if recovery_request or self._content_only_response_count > 1:
                raise V23ProtocolViolation(
                    "OpenHands v23 received a second content-only provider response"
                )
            return response
        if not calls:
            raise V23ProtocolViolation("OpenHands v23 provider response was empty")
        if recovery_request and len(calls) != 1:
            raise V23ProtocolViolation(
                "OpenHands v23 recovery response must contain exactly one tool call"
            )

        allowed = frozenset(tool.name for tool in tools or [])
        # Do not update any accepted-decision counter until every sibling has
        # completed exact-name, JSON, schema, path, and shell-safety validation.
        for call in calls:
            if call.name not in allowed or call.name not in _HWE_TOOL_NAMES:
                raise V23ProtocolViolation("OpenHands v23 provider emitted an illegal tool")
            try:
                arguments = _strict_json_object(call.arguments)
                canonical_hwe_action_json(
                    call.name,
                    arguments,
                    profile_id=HWE_COLLECTION_PROFILE_V2_ID,
                )
            except (TypeError, ValueError) as exc:
                if call.name == "finish":
                    raise V23PseudoFinishViolation(
                        "OpenHands v23 provider emitted a non-canonical finish"
                    ) from exc
                raise V23ProtocolViolation(
                    "OpenHands v23 provider emitted non-canonical tool arguments"
                ) from exc
        if len(calls) > 1 and any(call.name == "finish" for call in calls):
            raise V23PseudoFinishViolation("OpenHands v23 finish cannot have sibling tool calls")

        self._canonical_tool_response_count += 1
        self._canonical_tool_call_count += len(calls)
        self._decision_tool_call_counts.append(len(calls))
        if has_text:
            self._mixed_content_tool_response_count += 1
            self._public_text_decision_count += 1
        if len(calls) > 1:
            self._sibling_tool_decision_count += 1
            self._sibling_tool_call_count += len(calls)
        if recovery_request:
            self._recovery_validated_tool_count += 1
        return response

    @staticmethod
    def _validate_exact_tools(tools: Sequence[ToolDefinition] | None) -> None:
        names = [tool.name for tool in tools or []]
        if len(names) != len(_HWE_TOOL_NAMES) or frozenset(names) != _HWE_TOOL_NAMES:
            raise V23ProtocolViolation("OpenHands v23 requires the exact six-tool contract")


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
    "OPENHANDS_V23_CONTENT_RECOVERY_BUDGET",
    "OPENHANDS_V23_MAX_CONTEXT_TOKENS",
    "OPENHANDS_V23_MAX_OUTPUT_TOKENS",
    "OPENHANDS_V23_MAX_PROVIDER_CALLS",
    "OPENHANDS_V23_MAX_PROVIDER_TOKENS",
    "OPENHANDS_V23_TOOL_CHOICE_POLICY",
    "V23AutoPublicThoughtAtomicRecoveryLLM",
    "V23ProtocolViolation",
    "V23ProviderTokenBudgetExceeded",
    "V23PseudoFinishViolation",
]
