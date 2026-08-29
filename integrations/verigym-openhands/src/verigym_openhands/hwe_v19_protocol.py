"""Independent v19 required-tool protocol for OpenHands HWE collection."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from openhands.sdk.llm import LLMResponse, Message, content_to_str
from openhands.sdk.llm.llm import LLMCallContext
from openhands.sdk.llm.streaming import AnyTokenCallbackType, TokenCallbackType
from openhands.sdk.tool import ToolDefinition as GenericToolDefinition
from pydantic import Field, PrivateAttr
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID, canonical_hwe_action_json

from .hwe_stop_hook import read_recovery_count
from .hwe_tool_choice import (
    BoundedProviderCallLLM,
    WorkspaceRelativeMetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM,
    _required_tool_choice_kwargs,
)

type ToolDefinition = GenericToolDefinition[Any, Any]

OPENHANDS_V19_TOOL_CHOICE_POLICY = "required_tool_content_recovery_v19"
OPENHANDS_V19_MAX_PROVIDER_CALLS = 64
OPENHANDS_V19_MAX_PROVIDER_TOKENS = 1_000_000
OPENHANDS_V19_MAX_CONTEXT_TOKENS = 65_536
OPENHANDS_V19_MAX_OUTPUT_TOKENS = 2_048
OPENHANDS_V19_CONTENT_RECOVERY_BUDGET = 1

_HWE_TOOL_NAMES = frozenset(
    {"apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell"}
)


class V19ProtocolViolation(RuntimeError):
    """The provider response cannot enter the OpenHands or broker state machine."""


class V19ProviderTokenBudgetExceeded(V19ProtocolViolation):
    """A completed provider response crossed the cumulative v19 token budget."""


class V19PseudoFinishViolation(V19ProtocolViolation):
    """A provider-emitted finish call was not a canonical HWE finish action."""


class V19RequiredToolContentRecoveryLLM(
    WorkspaceRelativeMetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM
):
    """Require one canonical tool on every active request, with one prose recovery.

    A provider may ignore ``tool_choice=required`` once and return public text. That
    response is handed to OpenHands so its trusted Stop hook can retain the text and
    inject the canonical ``source=environment`` feedback. A second content-only
    response, a mixed text/tool response, a foreign or non-canonical tool, or any
    recovery counter drift is rejected before OpenHands or the broker sees it.

    The cumulative token check happens after the SDK has accounted the provider
    response but before this class returns it. Consequently an over-budget response
    is present in accounting and absent from the agent/broker transcript.
    """

    max_provider_tokens: int = Field(
        default=OPENHANDS_V19_MAX_PROVIDER_TOKENS,
        ge=1,
        le=OPENHANDS_V19_MAX_PROVIDER_TOKENS,
    )
    _required_tool_request_count: int = PrivateAttr(default=0)
    _canonical_tool_response_count: int = PrivateAttr(default=0)
    _content_only_response_count: int = PrivateAttr(default=0)
    _recovery_forced_request_count: int = PrivateAttr(default=0)
    _recovery_validated_tool_count: int = PrivateAttr(default=0)
    _over_budget_response_count: int = PrivateAttr(default=0)

    @property
    def required_tool_request_count(self) -> int:
        return self._required_tool_request_count

    @property
    def canonical_tool_response_count(self) -> int:
        return self._canonical_tool_response_count

    @property
    def content_only_response_count(self) -> int:
        return self._content_only_response_count

    @property
    def recovery_forced_request_count(self) -> int:
        return self._recovery_forced_request_count

    @property
    def recovery_validated_tool_count(self) -> int:
        return self._recovery_validated_tool_count

    @property
    def over_budget_response_count(self) -> int:
        return self._over_budget_response_count

    def completion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: TokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request_kwargs, recovery_request = self._prepare_request(tools, kwargs)
        before = self.provider_call_count
        try:
            response = BoundedProviderCallLLM.completion(
                self,
                messages=messages,
                tools=tools,
                add_security_risk_prediction=add_security_risk_prediction,
                on_token=on_token,
                call_context=call_context,
                **request_kwargs,
            )
        finally:
            self._record_claimed_request(before, recovery_request=recovery_request)
        return self._accept_response(
            response,
            tools=tools,
            recovery_request=recovery_request,
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
        request_kwargs, recovery_request = self._prepare_request(tools, kwargs)
        before = self.provider_call_count
        try:
            response = await BoundedProviderCallLLM.acompletion(
                self,
                messages=messages,
                tools=tools,
                add_security_risk_prediction=add_security_risk_prediction,
                on_token=on_token,
                call_context=call_context,
                **request_kwargs,
            )
        finally:
            self._record_claimed_request(before, recovery_request=recovery_request)
        return self._accept_response(
            response,
            tools=tools,
            recovery_request=recovery_request,
        )

    def responses(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        include: list[str] | None = None,
        store: bool | None = None,
        add_security_risk_prediction: bool = False,
        on_token: TokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request_kwargs, recovery_request = self._prepare_request(tools, kwargs)
        before = self.provider_call_count
        try:
            response = BoundedProviderCallLLM.responses(
                self,
                messages=messages,
                tools=tools,
                include=include,
                store=store,
                add_security_risk_prediction=add_security_risk_prediction,
                on_token=on_token,
                call_context=call_context,
                **request_kwargs,
            )
        finally:
            self._record_claimed_request(before, recovery_request=recovery_request)
        return self._accept_response(
            response,
            tools=tools,
            recovery_request=recovery_request,
        )

    async def aresponses(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        include: list[str] | None = None,
        store: bool | None = None,
        add_security_risk_prediction: bool = False,
        on_token: AnyTokenCallbackType | None = None,
        call_context: LLMCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request_kwargs, recovery_request = self._prepare_request(tools, kwargs)
        before = self.provider_call_count
        try:
            response = await BoundedProviderCallLLM.aresponses(
                self,
                messages=messages,
                tools=tools,
                include=include,
                store=store,
                add_security_risk_prediction=add_security_risk_prediction,
                on_token=on_token,
                call_context=call_context,
                **request_kwargs,
            )
        finally:
            self._record_claimed_request(before, recovery_request=recovery_request)
        return self._accept_response(
            response,
            tools=tools,
            recovery_request=recovery_request,
        )

    def _prepare_request(
        self,
        tools: Sequence[ToolDefinition] | None,
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        self._validate_exact_tools(tools)
        recovery_count = read_recovery_count(self.recovery_state_path)
        if self._content_only_response_count not in {0, 1}:
            raise V19ProtocolViolation("OpenHands v19 content-only counter drifted")
        if recovery_count != self._content_only_response_count:
            raise V19ProtocolViolation("OpenHands v19 recovery state does not match provider text")
        recovery_request = recovery_count == 1 and self._recovery_forced_request_count == 0
        if self._recovery_forced_request_count not in {0, 1} or (
            self._recovery_validated_tool_count > self._recovery_forced_request_count
        ):
            raise V19ProtocolViolation("OpenHands v19 recovery request counters drifted")
        try:
            request = _required_tool_choice_kwargs(tools, dict(kwargs))
        except ValueError as exc:
            raise V19ProtocolViolation(
                "OpenHands v19 required-tool request policy was weakened"
            ) from exc
        return request, recovery_request

    def _record_claimed_request(self, before: int, *, recovery_request: bool) -> None:
        after = self.provider_call_count
        if after == before:
            return
        if after != before + 1:
            raise V19ProtocolViolation("OpenHands v19 provider request counter drifted")
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
        token_total = self._current_provider_tokens()
        if token_total is None:
            raise V19ProtocolViolation("OpenHands v19 provider token accounting is unavailable")
        if token_total > self.max_provider_tokens:
            self._over_budget_response_count += 1
            raise V19ProviderTokenBudgetExceeded(
                "OpenHands v19 cumulative provider token budget was exceeded"
            )

        self._validate_provider_response(response)
        calls = response.message.tool_calls or []
        text_parts = content_to_str(response.message.content)
        has_text = any(part for part in text_parts)
        if not calls and has_text:
            self._content_only_response_count += 1
            if recovery_request or self._content_only_response_count > 1:
                raise V19ProtocolViolation(
                    "OpenHands v19 received a second content-only provider response"
                )
            return response
        if not calls and not has_text:
            raise V19ProtocolViolation("OpenHands v19 provider response was empty")
        if has_text or len(calls) != 1:
            raise V19ProtocolViolation(
                "OpenHands v19 provider response was not one content-free tool call"
            )

        call = calls[0]
        allowed = frozenset(tool.name for tool in tools or [])
        if call.name not in allowed or call.name not in _HWE_TOOL_NAMES:
            raise V19ProtocolViolation("OpenHands v19 provider emitted an illegal tool")
        try:
            arguments = _strict_json_object(call.arguments)
            canonical_hwe_action_json(
                call.name,
                arguments,
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
        except (TypeError, ValueError) as exc:
            if call.name == "finish":
                raise V19PseudoFinishViolation(
                    "OpenHands v19 provider emitted a non-canonical finish"
                ) from exc
            raise V19ProtocolViolation(
                "OpenHands v19 provider emitted non-canonical tool arguments"
            ) from exc
        self._canonical_tool_response_count += 1
        if recovery_request:
            self._recovery_validated_tool_count += 1
        return response

    def _current_provider_tokens(self) -> int | None:
        metrics = getattr(self, "metrics", None)
        accumulated = getattr(metrics, "accumulated_token_usage", None)
        prompt = getattr(accumulated, "prompt_tokens", None)
        completion = getattr(accumulated, "completion_tokens", None)
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in (prompt, completion)
        ):
            return None
        assert isinstance(prompt, int) and isinstance(completion, int)
        if prompt < 0 or completion < 0:
            return None
        return prompt + completion

    @staticmethod
    def _validate_exact_tools(tools: Sequence[ToolDefinition] | None) -> None:
        names = [tool.name for tool in tools or []]
        if len(names) != len(_HWE_TOOL_NAMES) or frozenset(names) != _HWE_TOOL_NAMES:
            raise V19ProtocolViolation("OpenHands v19 requires the exact six-tool contract")


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
    "OPENHANDS_V19_CONTENT_RECOVERY_BUDGET",
    "OPENHANDS_V19_MAX_CONTEXT_TOKENS",
    "OPENHANDS_V19_MAX_OUTPUT_TOKENS",
    "OPENHANDS_V19_MAX_PROVIDER_CALLS",
    "OPENHANDS_V19_MAX_PROVIDER_TOKENS",
    "OPENHANDS_V19_TOOL_CHOICE_POLICY",
    "V19ProtocolViolation",
    "V19ProviderTokenBudgetExceeded",
    "V19PseudoFinishViolation",
    "V19RequiredToolContentRecoveryLLM",
]
