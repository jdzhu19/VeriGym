"""Bounded, redacted artifact emission shared by both integration tracks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capabilities import CapabilityReport
from .events import ParsedEventStream, raw_event_records
from .process import CodexProcessResult
from .util import (
    atomic_json,
    atomic_jsonl,
    atomic_text,
    redact_text,
    redact_value,
    safe_regular_directory,
)


@dataclass
class CodexRunEvidence:
    capabilities: CapabilityReport
    invocation: dict[str, object]
    process: CodexProcessResult
    parsed: ParsedEventStream | None
    identity: Any
    accounting: Any
    summary: dict[str, Any]
    event_policy: dict[str, Any] | None = None
    roots_to_redact: tuple[Path, ...] = ()

    def write(self, root: Path, *, create: bool) -> None:
        destination = safe_regular_directory(root, create=create)
        atomic_json(destination / "capabilities.json", self.capabilities.safe_dict())
        atomic_json(
            destination / "invocation.json",
            redact_value(self.invocation, roots=self.roots_to_redact),
        )
        atomic_jsonl(
            destination / "raw_stdout.jsonl",
            raw_event_records(self.process.stdout, roots=self.roots_to_redact),
        )
        atomic_text(
            destination / "raw_stderr.log",
            redact_text(self.process.stderr, roots=self.roots_to_redact),
        )
        parsed_events = (
            [event.safe_dict() for event in self.parsed.events] if self.parsed is not None else []
        )
        atomic_jsonl(destination / "parsed_events.jsonl", parsed_events)
        atomic_json(
            destination / "identity.json",
            redact_value(_dump(self.identity), roots=self.roots_to_redact),
        )
        atomic_json(
            destination / "accounting.json",
            redact_value(_dump(self.accounting), roots=self.roots_to_redact),
        )
        if self.event_policy is not None:
            atomic_json(
                destination / "event_policy.json",
                redact_value(self.event_policy, roots=self.roots_to_redact),
            )
        process_summary = {
            "exit_code": self.process.exit_code,
            "timed_out": self.process.timed_out,
            "stdout_truncated": self.process.stdout_truncated,
            "stderr_truncated": self.process.stderr_truncated,
            "process_group_cleaned": self.process.process_group_cleaned,
            "duration_s": self.process.duration_s,
            "diagnostic_only": (
                self.parsed.diagnostic_only
                if self.parsed is not None
                else self.process.timed_out
                or self.process.stdout_truncated
                or self.process.stderr_truncated
            ),
            "canonical_stream_complete": (
                self.parsed.canonical_stream_complete if self.parsed is not None else False
            ),
        }
        atomic_json(
            destination / "summary.json",
            redact_value(
                {
                    "schema_version": "1.0",
                    **process_summary,
                    **self.summary,
                },
                roots=self.roots_to_redact,
            ),
        )


def update_summary(root: Path, updates: dict[str, Any]) -> None:
    path = root / "summary.json"
    current: dict[str, Any] = {}
    if path.is_file() and not path.is_symlink():
        import json

        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            current = loaded
    current.update(updates)
    atomic_json(path, redact_value(current, roots=()))


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


__all__ = ["CodexRunEvidence", "update_summary"]
