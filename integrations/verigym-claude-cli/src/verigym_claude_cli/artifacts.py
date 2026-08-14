"""Bounded Claude evidence that excludes prompts, message text, and reasoning content."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from .broker import BrokerStats
from .capabilities import CapabilityReport
from .events import ParsedEventStream
from .process import ClaudeProcessResult
from .util import atomic_json, redact_value


def write_evidence(
    root: Path,
    *,
    capabilities: CapabilityReport,
    invocation: dict[str, Any],
    process: ClaudeProcessResult,
    parsed: ParsedEventStream | None,
    broker: BrokerStats,
    identity: Any,
    accounting: Any,
    summary: dict[str, Any],
    roots_to_redact: tuple[Path, ...],
) -> None:
    _safe_existing_directory(root)
    usage_complete = bool(
        parsed is not None and parsed.input_tokens is not None and parsed.output_tokens is not None
    )
    terminal_input = parsed.input_tokens if parsed is not None else None
    terminal_output = parsed.output_tokens if parsed is not None else None
    terminal_cache_creation = parsed.cache_creation_input_tokens if parsed is not None else None
    terminal_cache_read = parsed.cache_read_input_tokens if parsed is not None else None
    pairs = (
        (terminal_input, process.observed_provider_input_tokens),
        (terminal_output, process.observed_provider_output_tokens),
        (terminal_cache_creation, process.observed_provider_cache_creation_input_tokens),
        (terminal_cache_read, process.observed_provider_cache_read_input_tokens),
    )
    stream_observed_max_used = any(
        observed is not None and (terminal is None or observed > terminal)
        for terminal, observed in pairs
    )
    input_tokens = _maximum_observed_count(*pairs[0])
    output_tokens = _maximum_observed_count(*pairs[1])
    cache_creation_input_tokens = _maximum_observed_count(*pairs[2])
    cache_read_input_tokens = _maximum_observed_count(*pairs[3])
    usage_values = (
        input_tokens,
        output_tokens,
        cache_creation_input_tokens,
        cache_read_input_tokens,
    )
    billed_tokens_observed = (
        sum(value or 0 for value in usage_values)
        if any(value is not None for value in usage_values)
        else None
    )
    if process.observed_provider_billed_tokens is not None and (
        billed_tokens_observed is None
        or process.observed_provider_billed_tokens > billed_tokens_observed
    ):
        billed_tokens_observed = process.observed_provider_billed_tokens
        stream_observed_max_used = True
    atomic_json(root / "capabilities.json", capabilities.safe_dict())
    atomic_json(root / "invocation.json", redact_value(invocation, roots=roots_to_redact))
    atomic_json(
        root / "process.json",
        {
            "exit_code": process.exit_code,
            "duration_s": process.duration_s,
            "timed_out": process.timed_out,
            "stdout_truncated": process.stdout_truncated,
            "stderr_truncated": process.stderr_truncated,
            "process_group_cleaned": process.process_group_cleaned,
            "broker_cancelled": process.broker_cancelled,
            "provider_cancelled": process.provider_cancelled,
            "provider_limit_failure": process.provider_limit_failure,
            "observed_provider_billed_tokens": process.observed_provider_billed_tokens,
            "stream_monitor_failed": process.stream_monitor_failed,
            "raw_stdout_persisted": False,
            "prompt_persisted": False,
            "message_content_persisted": False,
            "reasoning_content_persisted": False,
            "stderr_utf8_bytes": len(process.stderr.encode("utf-8")),
            "stderr_sha256": hashlib.sha256(process.stderr.encode("utf-8")).hexdigest(),
            "stderr_content_persisted": False,
        },
    )
    atomic_json(
        root / "events.json",
        {
            "events": [event.safe_dict() for event in parsed.events] if parsed else [],
            "event_count": len(parsed.events) if parsed else 0,
            "thinking_block_count": parsed.thinking_block_count if parsed else 0,
            "thinking_content_persisted": False,
            "final_result_sha256": parsed.final_result_sha256 if parsed else None,
        },
    )
    atomic_json(root / "broker.json", broker.__dict__)
    atomic_json(root / "identity.json", _dump(identity))
    atomic_json(root / "accounting.json", _dump(accounting))
    atomic_json(
        root / "provider-usage.json",
        {
            "schema_version": "1.0",
            "usage_complete": usage_complete,
            "usage_missing": not usage_complete,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": (
                input_tokens + output_tokens
                if input_tokens is not None and output_tokens is not None
                else None
            ),
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "billed_tokens_observed": billed_tokens_observed,
            "cache_usage_reported": bool(
                cache_creation_input_tokens is not None or cache_read_input_tokens is not None
            ),
            "cost_usd": parsed.cost_usd if parsed else None,
            "currency": "USD" if parsed is not None and parsed.cost_usd is not None else None,
            "provider_report_scope": (
                "claude_cli_terminal_result_plus_stream_observed_max"
                if usage_complete and stream_observed_max_used
                else (
                    "claude_cli_terminal_result"
                    if usage_complete
                    else "claude_cli_stream_observed_lower_bound"
                )
            ),
            "provider_limit_failure": process.provider_limit_failure,
        },
    )
    atomic_json(root / "summary.json", redact_value(summary, roots=roots_to_redact))


def update_summary(root: Path, updates: dict[str, Any]) -> None:
    path = root / "summary.json"
    current: dict[str, Any] = {}
    if path.is_file() and not path.is_symlink():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            current = loaded
    current.update(updates)
    atomic_json(path, current)


def _safe_existing_directory(path: Path) -> None:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Claude artifact destination must be a real directory")


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _maximum_observed_count(terminal: int | None, observed: int | None) -> int | None:
    if terminal is None:
        return observed
    if observed is None:
        return terminal
    return max(terminal, observed)


__all__ = ["update_summary", "write_evidence"]
