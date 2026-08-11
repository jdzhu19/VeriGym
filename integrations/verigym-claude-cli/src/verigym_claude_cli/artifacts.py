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


__all__ = ["update_summary", "write_evidence"]
