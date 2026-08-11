"""Bounded Claude stream-JSON parsing without persisting message or reasoning content."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .mcp_tools import CLAUDE_TOOL_NAMES

_MAX_LINE_BYTES = 2 * 1024 * 1024


class EventParseError(RuntimeError):
    """Claude emitted an unsafe or structurally invalid event stream."""


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
    context_window: int | None = None
    per_response_max: int | None = None
    num_turns: int | None = None
    final_hash: str | None = None
    thinking_count = 0
    failure_message: str | None = None
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
            if set(advertised) != set(CLAUDE_TOOL_NAMES):
                raise EventParseError("Claude init event exposed tools outside the MCP allowlist")
        elif event_type == "assistant":
            message = payload.get("message")
            if not isinstance(message, dict):
                raise EventParseError("Claude assistant event omits its message object")
            event_model = _optional_string(message.get("model"))
            if event_model is not None:
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
                else:
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
        context_window_tokens=context_window,
        per_response_max_output_tokens=per_response_max,
        num_turns=num_turns,
        final_result_sha256=final_hash,
        thinking_block_count=thinking_count,
        failure_message=failure_message,
    )


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


__all__ = ["EventParseError", "EventSummary", "ParsedEventStream", "parse_event_stream"]
