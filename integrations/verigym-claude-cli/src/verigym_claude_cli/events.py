"""Bounded Claude stream-JSON parsing without persisting message or reasoning content."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from dataclasses import dataclass
from typing import Any

from verigym.core.repository_tool_broker import RepositoryToolBrokerTurn
from verigym.protocols.repository_action import canonical_action_json
from verigym.schemas.multiturn_sft import MultiTurnSftMessage, SftToolCall

from .mcp_tools import CLAUDE_TOOL_NAMES

_MAX_LINE_BYTES = 2 * 1024 * 1024


class EventParseError(RuntimeError):
    """Claude emitted an unsafe or structurally invalid event stream."""


class TranscriptNormalizationInfrastructureError(EventParseError):
    """Provider events disagreed with the broker-owned canonical transcript."""


@dataclass(frozen=True)
class ProviderTokenSnapshot:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int

    @property
    def billed_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


class ProviderTokenMonitor:
    """Track cache-inclusive Claude usage from the live stream without retaining content."""

    def __init__(self, maximum: int) -> None:
        if maximum < 1:
            raise ValueError("provider token limit must be positive")
        self.maximum = maximum
        self._messages: dict[str, ProviderTokenSnapshot] = {}
        self._terminal: ProviderTokenSnapshot | None = None
        self._lock = threading.Lock()

    def observe(self, line: bytes) -> None:
        if not line.strip() or len(line) > _MAX_LINE_BYTES:
            return
        try:
            payload = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        event_type = payload.get("type")
        if event_type == "assistant":
            message = payload.get("message")
            if not isinstance(message, dict):
                return
            message_id = message.get("id")
            usage = message.get("usage")
            if (
                not isinstance(message_id, str)
                or not message_id
                or len(message_id) > 512
                or not isinstance(usage, dict)
            ):
                return
            snapshot = _provider_token_snapshot(usage)
            if snapshot is None:
                return
            with self._lock:
                previous = self._messages.get(message_id)
                self._messages[message_id] = _maximum_snapshot(previous, snapshot)
        elif event_type == "result":
            usage = payload.get("usage")
            if not isinstance(usage, dict):
                return
            snapshot = _provider_token_snapshot(usage)
            if snapshot is None:
                return
            with self._lock:
                self._terminal = _maximum_snapshot(self._terminal, snapshot)

    def snapshot(self) -> ProviderTokenSnapshot:
        with self._lock:
            messages = ProviderTokenSnapshot(0, 0, 0, 0)
            for snapshot in self._messages.values():
                messages = ProviderTokenSnapshot(
                    input_tokens=messages.input_tokens + snapshot.input_tokens,
                    output_tokens=messages.output_tokens + snapshot.output_tokens,
                    cache_creation_input_tokens=(
                        messages.cache_creation_input_tokens + snapshot.cache_creation_input_tokens
                    ),
                    cache_read_input_tokens=(
                        messages.cache_read_input_tokens + snapshot.cache_read_input_tokens
                    ),
                )
            return _maximum_snapshot(messages, self._terminal)

    def exhausted(self) -> bool:
        return self.snapshot().billed_tokens >= self.maximum


@dataclass(frozen=True)
class EventSummary:
    sequence: int
    upstream_type: str
    subtype: str | None
    model_id: str | None
    tool_names: tuple[str, ...]
    thinking_block_present: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "upstream_type": self.upstream_type,
            "subtype": self.subtype,
            "model_id": self.model_id,
            "tool_names": list(self.tool_names),
            "thinking_block_present": self.thinking_block_present,
            "message_content_persisted": False,
            "reasoning_content_persisted": False,
        }


@dataclass(frozen=True)
class ParsedEventStream:
    events: tuple[EventSummary, ...]
    init_seen: bool
    terminal_seen: bool
    successful: bool
    requested_model_id: str
    observed_model_id: str | None
    tool_names: tuple[str, ...]
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cache_creation_input_tokens: int | None
    cache_read_input_tokens: int | None
    cost_usd: float | None
    context_window_tokens: int | None
    per_response_max_output_tokens: int | None
    num_turns: int | None
    final_result_sha256: str | None
    thinking_block_count: int
    failure_message: str | None


def parse_event_stream(
    stdout: str,
    *,
    requested_model_id: str,
    expected_context_window_tokens: int | None,
) -> ParsedEventStream:
    summaries: list[EventSummary] = []
    init_seen = False
    terminal_seen = False
    successful = False
    observed_models: list[str] = []
    tools: list[str] = []
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cost_usd: float | None = None
    context_window: int | None = None
    per_response_max: int | None = None
    num_turns: int | None = None
    final_hash: str | None = None
    thinking_count = 0
    failure_message: str | None = None
    synthetic_failure_seen = False
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise EventParseError("Claude event stream is empty")
    for sequence, line in enumerate(lines):
        if len(line.encode("utf-8")) > _MAX_LINE_BYTES:
            raise EventParseError("Claude event exceeds the per-event byte bound")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EventParseError("Claude emitted malformed stream JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
            raise EventParseError("Claude event must be a typed object")
        event_type = payload["type"]
        subtype = payload.get("subtype") if isinstance(payload.get("subtype"), str) else None
        event_model: str | None = None
        event_tools: list[str] = []
        event_thinking = False
        if event_type == "system" and subtype == "init":
            if init_seen:
                raise EventParseError("Claude emitted more than one init event")
            init_seen = True
            event_model = _optional_string(payload.get("model"))
            if event_model is not None:
                observed_models.append(event_model)
            advertised = payload.get("tools")
            if not isinstance(advertised, list) or not all(
                isinstance(value, str) for value in advertised
            ):
                raise EventParseError("Claude init event omits its tool inventory")
            unexpected = sorted(set(advertised) - set(CLAUDE_TOOL_NAMES))
            missing = sorted(set(CLAUDE_TOOL_NAMES) - set(advertised))
            if unexpected:
                raise EventParseError(
                    "Claude init event exposed tools outside the MCP allowlist: "
                    + ", ".join(unexpected)
                )
            if missing:
                raise EventParseError(
                    "Claude init event omitted required VeriGym MCP tools: " + ", ".join(missing)
                )
        elif event_type == "assistant":
            message = payload.get("message")
            if not isinstance(message, dict):
                raise EventParseError("Claude assistant event omits its message object")
            event_model = _optional_string(message.get("model"))
            assistant_error = _optional_string(payload.get("error"))
            synthetic_failure = event_model == "<synthetic>" and bool(
                assistant_error and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", assistant_error)
            )
            if synthetic_failure:
                synthetic_failure_seen = True
                failure_message = f"Claude assistant reported {assistant_error}"
            elif event_model is not None:
                observed_models.append(event_model)
            content = message.get("content")
            if not isinstance(content, list):
                raise EventParseError("Claude assistant message content must be a list")
            for block in content:
                if not isinstance(block, dict) or not isinstance(block.get("type"), str):
                    raise EventParseError("Claude assistant content block is malformed")
                block_type = block["type"]
                if block_type in {"thinking", "redacted_thinking"}:
                    event_thinking = True
                    thinking_count += 1
                if block_type == "tool_use":
                    if synthetic_failure:
                        raise EventParseError("Claude synthetic failure attempted a tool call")
                    name = block.get("name")
                    if not isinstance(name, str) or name not in CLAUDE_TOOL_NAMES:
                        raise EventParseError("Claude invoked a tool outside the MCP allowlist")
                    event_tools.append(name)
                    tools.append(name)
        elif event_type == "result":
            if terminal_seen:
                raise EventParseError("Claude emitted more than one terminal result")
            terminal_seen = True
            successful = subtype == "success" and payload.get("is_error") is False
            result_text = payload.get("result")
            if isinstance(result_text, str):
                final_hash = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
            num_turns = _optional_nonnegative_int(payload.get("num_turns"))
            usage = payload.get("usage")
            if isinstance(usage, dict):
                input_tokens = _usage_int(usage, "input_tokens")
                output_tokens = _usage_int(usage, "output_tokens")
                cache_creation_input_tokens = _usage_int(usage, "cache_creation_input_tokens")
                cache_read_input_tokens = _usage_int(usage, "cache_read_input_tokens")
            cost_usd = _usage_float(payload, "total_cost_usd")
            model_usage = payload.get("modelUsage")
            if isinstance(model_usage, dict):
                for model_name, model_payload in model_usage.items():
                    if isinstance(model_name, str):
                        observed_models.append(model_name)
                    if not isinstance(model_payload, dict):
                        continue
                    if input_tokens is None:
                        input_tokens = _usage_int(model_payload, "inputTokens")
                    if output_tokens is None:
                        output_tokens = _usage_int(model_payload, "outputTokens")
                    if cache_creation_input_tokens is None:
                        cache_creation_input_tokens = _usage_int(
                            model_payload, "cacheCreationInputTokens"
                        )
                    if cache_read_input_tokens is None:
                        cache_read_input_tokens = _usage_int(model_payload, "cacheReadInputTokens")
                    if cost_usd is None:
                        cost_usd = _usage_float(model_payload, "costUSD")
                    candidate_context = _usage_int(model_payload, "contextWindow")
                    candidate_output = _usage_int(model_payload, "maxOutputTokens")
                    if candidate_context is not None:
                        context_window = max(context_window or 0, candidate_context)
                    if candidate_output is not None:
                        per_response_max = max(per_response_max or 0, candidate_output)
            if not successful:
                errors = payload.get("errors")
                if isinstance(errors, list) and errors and isinstance(errors[0], str):
                    failure_message = errors[0][:1000]
                elif failure_message is None:
                    failure_message = "Claude terminal result reported an error"
        elif event_type not in {"system", "user", "rate_limit_event", "stream_event"}:
            raise EventParseError(f"Claude emitted unsupported event type: {event_type}")
        summaries.append(
            EventSummary(
                sequence=sequence,
                upstream_type=event_type,
                subtype=subtype,
                model_id=event_model,
                tool_names=tuple(event_tools),
                thinking_block_present=event_thinking,
            )
        )
    if not init_seen or not terminal_seen:
        raise EventParseError("Claude event stream lacks init or terminal evidence")
    if synthetic_failure_seen and successful:
        raise EventParseError("Claude synthetic failure ended with a successful result")
    observed_model = _select_observed_model(observed_models, requested_model_id)
    if expected_context_window_tokens is not None and (
        (successful and context_window != expected_context_window_tokens)
        or (context_window is not None and context_window != expected_context_window_tokens)
    ):
        raise EventParseError("Claude observed context window differs from the frozen expectation")
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    return ParsedEventStream(
        events=tuple(summaries),
        init_seen=init_seen,
        terminal_seen=terminal_seen,
        successful=successful,
        requested_model_id=requested_model_id,
        observed_model_id=observed_model,
        tool_names=tuple(tools),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cost_usd=cost_usd,
        context_window_tokens=context_window,
        per_response_max_output_tokens=per_response_max,
        num_turns=num_turns,
        final_result_sha256=final_hash,
        thinking_block_count=thinking_count,
        failure_message=failure_message,
    )


def normalize_training_messages(
    stdout: str,
    *,
    system_prompt: str,
    user_prompt: str,
    broker_turns: tuple[RepositoryToolBrokerTurn, ...],
    mask_nonfinal_assistant_prose: bool = False,
) -> list[MultiTurnSftMessage]:
    """Normalize public Claude MCP events while dropping private or masked text blocks."""

    messages = [
        MultiTurnSftMessage(role="system", content=system_prompt),
        MultiTurnSftMessage(role="user", content=user_prompt),
    ]
    assistant_text_snapshots: list[str] = []
    terminal_text: str | None = None
    terminal_seen = False
    broker_turn_index = 0
    pending_calls: list[SftToolCall] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EventParseError("Claude training event is malformed") from exc
        if not isinstance(event, dict):
            raise EventParseError("Claude training event must be an object")
        event_type = event.get("type")
        if event_type == "assistant":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                raise EventParseError("Claude assistant training message is malformed")
            calls: list[MultiTurnSftMessage] = []
            text_blocks: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    raise EventParseError("Claude assistant training block is malformed")
                block_type = block.get("type")
                if block_type in {"thinking", "redacted_thinking"}:
                    continue
                if block_type == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        text_blocks.append(text)
                    continue
                if block_type != "tool_use":
                    raise EventParseError("Claude training stream contains an unsupported block")
                raw_name = block.get("name")
                call_id = block.get("id")
                arguments = block.get("input")
                prefix = "mcp__verigym__"
                if (
                    not isinstance(raw_name, str)
                    or not raw_name.startswith(prefix)
                    or raw_name not in CLAUDE_TOOL_NAMES
                    or not isinstance(call_id, str)
                    or not isinstance(arguments, dict)
                ):
                    raise EventParseError("Claude training tool call is not canonical MCP")
                name = raw_name.removeprefix(prefix)
                envelope = json.loads(canonical_action_json(name, arguments))
                canonical_arguments = json.dumps(
                    envelope["arguments"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                calls.append(
                    MultiTurnSftMessage.model_validate(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": canonical_arguments,
                                    },
                                }
                            ],
                        }
                    )
                )
            if calls and text_blocks:
                raise EventParseError("Claude mixed prose with a training tool-call turn")
            if len(calls) > 1:
                raise EventParseError("Claude emitted multiple repository actions in one turn")
            if calls:
                # Claude-compatible gateways may emit successive assistant tool-call
                # events before returning the corresponding MCP results. Keep those
                # calls ordered until the broker-owned observations arrive instead of
                # treating the newest call as the only pending one.
                tool_calls = calls[0].tool_calls
                assert tool_calls is not None
                pending_calls.append(tool_calls[0])
            elif text_blocks:
                if broker_turn_index != len(broker_turns):
                    if mask_nonfinal_assistant_prose:
                        # Some compatible gateways surface short assistant narration as a
                        # separate text event even when the tool-call contract forbids it.
                        # It is deliberately omitted from SFT messages and never exported.
                        continue
                    raise EventParseError("Claude emitted non-final assistant prose")
                assistant_text_snapshots.append("\n".join(text_blocks))
        elif event_type == "user":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                raise EventParseError("Claude user training message is malformed")
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    raise EventParseError("Claude injected a non-tool user training message")
                call_id = block.get("tool_use_id")
                if not isinstance(call_id, str):
                    raise EventParseError("Claude tool result omits its call ID")
                _tool_result_text(block.get("content"))
                if not pending_calls:
                    raise TranscriptNormalizationInfrastructureError(
                        "Claude tool result has no preceding assistant call"
                    )
                pending_call = pending_calls.pop(0)
                name = pending_call.function.name
                if broker_turn_index >= len(broker_turns):
                    raise TranscriptNormalizationInfrastructureError(
                        "Claude tool result has no broker-owned observation"
                    )
                turn = broker_turns[broker_turn_index]
                arguments = pending_call.function.arguments
                if turn.tool_name != name or turn.arguments_json != arguments:
                    raise TranscriptNormalizationInfrastructureError(
                        "Claude tool event differs from the canonical broker turn: "
                        f"index={broker_turn_index} "
                        f"expected_tool={turn.tool_name} actual_tool={name} "
                        "expected_arguments="
                        f"{_safe_argument_fingerprint(turn.arguments_json)} "
                        "actual_arguments="
                        f"{_safe_argument_fingerprint(arguments)}"
                    )
                try:
                    messages.append(
                        MultiTurnSftMessage(
                            role="assistant",
                            content=None,
                            tool_calls=[pending_call],
                        )
                    )
                    messages.append(
                        MultiTurnSftMessage(
                            role="tool",
                            content=turn.observation_json,
                            # Some Claude-compatible gateways rewrite the provider-rendered
                            # tool-result ID. The assistant call ID is authoritative; ordered
                            # broker name/argument matching still fails closed on semantic drift.
                            tool_call_id=pending_call.id,
                            name=name,
                        )
                    )
                except ValueError as exc:
                    raise TranscriptNormalizationInfrastructureError(
                        "broker-owned observation is not canonical SFT JSON"
                    ) from exc
                broker_turn_index += 1
        elif event_type == "result":
            if terminal_seen:
                raise EventParseError("Claude training stream has multiple terminal results")
            terminal_seen = True
            result = event.get("result")
            if isinstance(result, str) and result.strip():
                terminal_text = result
    final_text = _canonical_final_text(assistant_text_snapshots, terminal_text)
    if final_text is None:
        raise EventParseError("Claude training stream has no final assistant content")
    if pending_calls:
        raise TranscriptNormalizationInfrastructureError(
            "Claude emitted tool calls without canonical broker results"
        )
    if broker_turn_index != len(broker_turns):
        raise TranscriptNormalizationInfrastructureError(
            "canonical broker turn count differs from Claude tool results"
        )
    messages.append(MultiTurnSftMessage(role="assistant", content=final_text))
    return messages


def _canonical_final_text(snapshots: list[str], terminal: str | None) -> str | None:
    """Deduplicate identical/cumulative final snapshots against the terminal result."""

    if terminal is None:
        if not snapshots:
            return None
        terminal = snapshots[-1]
    previous = ""
    for snapshot in snapshots:
        if not snapshot.startswith(previous) or not terminal.startswith(snapshot):
            raise EventParseError(
                "Claude final assistant snapshots differ from its terminal result"
            )
        previous = snapshot
    return terminal


def _safe_argument_fingerprint(arguments: str) -> str:
    """Describe canonical arguments without retaining or exposing their contents."""

    encoded = arguments.encode("utf-8")
    return f"bytes={len(encoded)} sha256={hashlib.sha256(encoded).hexdigest()}"


def _select_observed_model(values: list[str], requested: str) -> str | None:
    if not values:
        return None
    base = re.sub(r"\[1m\]$", "", requested)
    for value in values:
        if value not in {requested, base}:
            raise EventParseError("Claude observed an unexpected model identity")
    return base if base in values else requested


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _usage_int(payload: dict[str, Any], key: str) -> int | None:
    return _optional_nonnegative_int(payload.get(key))


def _usage_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _provider_token_snapshot(payload: dict[str, Any]) -> ProviderTokenSnapshot | None:
    values = (
        _usage_int(payload, "input_tokens"),
        _usage_int(payload, "output_tokens"),
        _usage_int(payload, "cache_creation_input_tokens"),
        _usage_int(payload, "cache_read_input_tokens"),
    )
    if all(value is None for value in values):
        return None
    return ProviderTokenSnapshot(*(value or 0 for value in values))


def _maximum_snapshot(
    left: ProviderTokenSnapshot | None,
    right: ProviderTokenSnapshot | None,
) -> ProviderTokenSnapshot:
    left = left or ProviderTokenSnapshot(0, 0, 0, 0)
    right = right or ProviderTokenSnapshot(0, 0, 0, 0)
    return ProviderTokenSnapshot(
        input_tokens=max(left.input_tokens, right.input_tokens),
        output_tokens=max(left.output_tokens, right.output_tokens),
        cache_creation_input_tokens=max(
            left.cache_creation_input_tokens,
            right.cache_creation_input_tokens,
        ),
        cache_read_input_tokens=max(left.cache_read_input_tokens, right.cache_read_input_tokens),
    )


def _tool_result_text(value: Any) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        text = value[0].get("text")
        if value[0].get("type") == "text" and isinstance(text, str) and text:
            return text
    raise EventParseError("Claude training tool result is not one public text observation")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


__all__ = [
    "EventParseError",
    "EventSummary",
    "ParsedEventStream",
    "ProviderTokenMonitor",
    "ProviderTokenSnapshot",
    "TranscriptNormalizationInfrastructureError",
    "normalize_training_messages",
    "parse_event_stream",
]
