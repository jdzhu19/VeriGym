"""Versioned parsing of line-oriented Codex exec machine events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .util import redact_value

_MAX_LINE_BYTES = 1024 * 1024
_MAX_DEPTH = 32
_MAX_EVENTS = 10_000
_TOOL_CATEGORIES = {
    "plan_update",
    "file_read",
    "file_write",
    "patch_applied",
    "command_started",
    "command_completed",
    "tool_call",
}


class EventParseError(RuntimeError):
    """Machine-readable CLI output is malformed or ambiguous."""


@dataclass(frozen=True)
class NormalizedEvent:
    sequence: int
    category: str
    upstream_type: str
    payload: dict[str, Any]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "sequence": self.sequence,
            "category": self.category,
            "upstream_type": self.upstream_type,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ParsedEventStream:
    events: tuple[NormalizedEvent, ...]
    final_messages: tuple[str, ...]
    session_id: str | None
    observed_model_id: str | None
    system_fingerprint: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    terminal_event_seen: bool
    error_messages: tuple[str, ...]
    diagnostic_only: bool
    canonical_stream_complete: bool

    @property
    def tool_use_events(self) -> tuple[NormalizedEvent, ...]:
        return tuple(event for event in self.events if event.category in _TOOL_CATEGORIES)

    @property
    def command_count(self) -> int:
        return sum(event.category == "command_started" for event in self.events)

    @property
    def file_read_count(self) -> int:
        return sum(event.category == "file_read" for event in self.events)

    @property
    def file_write_count(self) -> int:
        return sum(event.category == "file_write" for event in self.events)

    @property
    def patch_count(self) -> int:
        return sum(event.category == "patch_applied" for event in self.events)

    @property
    def external_tool_count(self) -> int:
        return sum(event.category == "tool_call" for event in self.events)


def parse_event_stream(
    stdout: str,
    *,
    roots: tuple[Path, ...] = (),
) -> ParsedEventStream:
    lines = stdout.splitlines()
    if not lines:
        raise EventParseError("Codex CLI emitted no machine-readable events")
    if len(lines) > _MAX_EVENTS:
        raise EventParseError("Codex CLI event stream exceeds the event-count bound")
    events: list[NormalizedEvent] = []
    final_messages: list[str] = []
    errors: list[str] = []
    session_id: str | None = None
    observed_model: str | None = None
    system_fingerprint: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    terminal = False
    for line_number, line in enumerate(lines, start=1):
        if len(line.encode("utf-8")) > _MAX_LINE_BYTES:
            raise EventParseError(f"Codex JSONL line {line_number} exceeds the size bound")
        if not line.strip():
            raise EventParseError(f"Codex JSONL contains a blank line at {line_number}")
        try:
            raw = json.loads(line, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EventParseError(f"Codex JSONL line {line_number} is malformed") from exc
        if not isinstance(raw, dict):
            raise EventParseError(f"Codex JSONL line {line_number} is not an object")
        _check_depth(raw)
        safe_raw = _discard_reasoning(redact_value(raw, roots=roots))
        upstream = str(raw.get("type", "unknown"))
        category, payload = _normalize(raw, safe_raw, completed=upstream.endswith("completed"))
        event = NormalizedEvent(
            sequence=len(events),
            category=category,
            upstream_type=upstream[:256],
            payload=payload,
        )
        events.append(event)
        if category == "message_completed":
            text = payload.get("text")
            if isinstance(text, str) and text.strip():
                final_messages.append(text)
        if category in {"turn_completed", "session_completed"}:
            terminal = True
        if category == "error":
            message = payload.get("message")
            if isinstance(message, str):
                errors.append(message)
        session_id = session_id or _first_string(
            raw,
            ("thread_id", "session_id", "response_id", "id"),
        )
        observed_model = observed_model or _first_string(
            raw,
            ("model", "model_id", "provider_model_id"),
        )
        system_fingerprint = system_fingerprint or _first_string(
            raw,
            ("system_fingerprint",),
        )
        usage = _usage_mapping(raw)
        if usage is not None:
            input_tokens = _integer_field(
                usage,
                ("input_tokens", "prompt_tokens", "input_token_count"),
                fallback=input_tokens,
            )
            output_tokens = _integer_field(
                usage,
                ("output_tokens", "completion_tokens", "output_token_count"),
                fallback=output_tokens,
            )
            total_tokens = _integer_field(
                usage,
                ("total_tokens", "total_token_count"),
                fallback=total_tokens,
            )
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return ParsedEventStream(
        events=tuple(events),
        final_messages=tuple(final_messages),
        session_id=session_id,
        observed_model_id=observed_model,
        system_fingerprint=system_fingerprint,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        terminal_event_seen=terminal,
        error_messages=tuple(errors),
        diagnostic_only=False,
        canonical_stream_complete=True,
    )


def parse_partial_event_stream(
    stdout: str,
    *,
    roots: tuple[Path, ...] = (),
) -> ParsedEventStream:
    """Safely retain a valid event prefix without inferring canonical results."""

    events: list[NormalizedEvent] = []
    errors: list[str] = []
    for line in stdout.splitlines()[:_MAX_EVENTS]:
        try:
            parsed_line = parse_event_stream(line, roots=roots)
        except EventParseError:
            break
        event = parsed_line.events[0]
        events.append(
            NormalizedEvent(
                sequence=len(events),
                category=event.category,
                upstream_type=event.upstream_type,
                payload=event.payload,
            )
        )
        errors.extend(parsed_line.error_messages)
    return ParsedEventStream(
        events=tuple(events),
        final_messages=(),
        session_id=None,
        observed_model_id=None,
        system_fingerprint=None,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        terminal_event_seen=False,
        error_messages=tuple(errors),
        diagnostic_only=True,
        canonical_stream_complete=False,
    )


def raw_event_records(
    stdout: str,
    *,
    roots: tuple[Path, ...] = (),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for sequence, line in enumerate(stdout.splitlines()):
        if len(records) >= _MAX_EVENTS:
            records.append(
                {
                    "sequence": sequence,
                    "truncated": True,
                    "reason": "event_count_bound",
                }
            )
            break
        try:
            value = json.loads(line, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, ValueError):
            value = {"malformed_raw_line": line[:_MAX_LINE_BYTES]}
        records.append(
            {
                "sequence": sequence,
                "raw": _discard_reasoning(redact_value(value, roots=roots)),
            }
        )
    return records


def _normalize(
    raw: dict[str, Any],
    safe_raw: dict[str, Any],
    *,
    completed: bool,
) -> tuple[str, dict[str, Any]]:
    upstream = str(raw.get("type", "unknown"))
    canonical = upstream.lower().replace(".", "_").replace("-", "_")
    direct = {
        "session_started": "session_started",
        "thread_started": "session_started",
        "turn_started": "turn_started",
        "message_delta": "message_delta",
        "message_completed": "message_completed",
        "agent_message": "message_completed",
        "file_read": "file_read",
        "file_write": "file_write",
        "patch_applied": "patch_applied",
        "command_started": "command_started",
        "command_completed": "command_completed",
        "tool_call": "tool_call",
        "plan_update": "plan_update",
        "update_plan": "plan_update",
        "usage": "usage",
        "turn_completed": "turn_completed",
        "session_completed": "session_completed",
        "response_completed": "session_completed",
        "error": "error",
    }
    if canonical in direct:
        category = direct[canonical]
        return category, _direct_payload(category, safe_raw)
    if canonical in {"item_started", "item_completed", "item_updated"}:
        item = raw.get("item")
        safe_item = safe_raw.get("item")
        if not isinstance(item, dict) or not isinstance(safe_item, dict):
            return "unknown", {"shape": "item_without_object"}
        item_type = str(item.get("type", "unknown")).lower().replace(".", "_")
        if item_type in {"agent_message", "message"}:
            if not completed and canonical != "item_completed":
                return "message_delta", {"text": _item_text(safe_item)}
            return "message_completed", {"text": _item_text(safe_item)}
        if item_type in {"reasoning", "reasoning_summary"}:
            return "reasoning_summary", {"retained": False}
        if item_type in {"command_execution", "command"}:
            category = "command_completed" if canonical == "item_completed" else "command_started"
            return category, {
                "command": _first_string(item, ("command", "cmd")) or "",
                "status": item.get("status"),
                "exit_code": item.get("exit_code"),
                "output_returned_to_model": bool(item.get("aggregated_output")),
            }
        if item_type in {"file_change", "patch", "patch_application"}:
            return "patch_applied", {
                "paths": _file_change_paths(item),
                "status": item.get("status"),
            }
        if item_type in {"file_read", "read_file"}:
            return "file_read", {"path": _first_string(item, ("path", "file"))}
        if item_type in {"file_write", "write_file"}:
            return "file_write", {"path": _first_string(item, ("path", "file"))}
        if item_type in {"mcp_tool_call", "tool_call", "web_search"}:
            return "tool_call", {
                "tool": _first_string(item, ("tool", "name")) or item_type,
                "status": item.get("status"),
            }
        if item_type in {"plan", "plan_update", "update_plan"}:
            return "plan_update", {"status": item.get("status")}
        return "unknown", {"item_type": item_type[:128]}
    if "error" in canonical or raw.get("error") is not None:
        return "error", {
            "message": _safe_error_message(safe_raw),
            "code": raw.get("code"),
        }
    return "unknown", {"shape": canonical[:128]}


def _direct_payload(category: str, safe: dict[str, Any]) -> dict[str, Any]:
    if category in {"message_completed", "message_delta"}:
        return {"text": _item_text(safe)}
    if category in {"file_read", "file_write"}:
        return {"path": _first_string(safe, ("path", "file"))}
    if category == "patch_applied":
        return {"paths": _file_change_paths(safe)}
    if category in {"command_started", "command_completed"}:
        return {
            "command": _first_string(safe, ("command", "cmd")) or "",
            "status": safe.get("status"),
            "exit_code": safe.get("exit_code"),
            "output_returned_to_model": bool(safe.get("aggregated_output")),
        }
    if category == "tool_call":
        return {"tool": _first_string(safe, ("tool", "name")) or "unknown"}
    if category == "error":
        return {"message": _safe_error_message(safe), "code": safe.get("code")}
    if category == "usage":
        usage = _usage_mapping(safe)
        return dict(usage) if usage is not None else {}
    return {
        key: value
        for key, value in safe.items()
        if key
        in {
            "thread_id",
            "session_id",
            "response_id",
            "status",
            "model",
            "model_id",
            "usage",
        }
    }


def _item_text(value: dict[str, Any]) -> str:
    for key in ("text", "content", "message", "output_text"):
        item = value.get(key)
        if isinstance(item, str):
            return item
    return ""


def _discard_reasoning(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    result = dict(value)
    item = result.get("item")
    if isinstance(item, dict) and str(item.get("type", "")).lower() in {
        "reasoning",
        "reasoning_summary",
    }:
        result["item"] = {
            key: ("<discarded-reasoning>" if key in {"text", "content", "summary"} else nested)
            for key, nested in item.items()
        }
    if str(result.get("type", "")).lower().replace(".", "_") in {
        "reasoning",
        "reasoning_summary",
    }:
        for key in ("text", "content", "summary"):
            if key in result:
                result[key] = "<discarded-reasoning>"
    return result


def _file_change_paths(value: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    direct = _first_string(value, ("path", "file"))
    if direct is not None:
        paths.append(direct)
    changes = value.get("changes")
    if isinstance(changes, list):
        for change in changes:
            if isinstance(change, dict):
                path = _first_string(change, ("path", "file"))
                if path is not None:
                    paths.append(path)
    raw_paths = value.get("paths")
    if isinstance(raw_paths, list):
        paths.extend(item for item in raw_paths if isinstance(item, str))
    return sorted(set(paths))


def _safe_error_message(value: dict[str, Any]) -> str:
    message = value.get("message")
    if isinstance(message, str):
        return message[:4096]
    error = value.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return str(error["message"])[:4096]
    if isinstance(error, str):
        return error[:4096]
    return "Codex CLI reported an unspecified error"


def _usage_mapping(value: dict[str, Any]) -> dict[str, Any] | None:
    usage = value.get("usage")
    if isinstance(usage, dict):
        return usage
    item = value.get("item")
    if isinstance(item, dict) and isinstance(item.get("usage"), dict):
        return cast(dict[str, Any], item["usage"])
    return None


def _integer_field(
    values: dict[str, Any],
    keys: tuple[str, ...],
    *,
    fallback: int | None,
) -> int | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return fallback


def _first_string(values: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value:
            return value[:4096]
    return None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        raise EventParseError("Codex JSONL exceeds the nesting-depth bound")
    if isinstance(value, dict):
        for item in value.values():
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1)


__all__ = [
    "EventParseError",
    "NormalizedEvent",
    "ParsedEventStream",
    "parse_event_stream",
    "parse_partial_event_stream",
    "raw_event_records",
]
