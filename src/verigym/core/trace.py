"""Append-only trace writer and strict replay reader."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verigym.core.errors import ReplayError, SchemaCompatibilityError
from verigym.core.schema_compat import validate_schema_version
from verigym.schemas.trace import EpisodeEvent


class TraceWriter:
    """Append schema-validated JSON Lines events with contiguous sequence IDs."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.sequence = 0
        self._last_event_id: str | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        parent_event_id: str | None = None,
    ) -> EpisodeEvent:
        event = EpisodeEvent(
            event_id=str(uuid.uuid4()),
            run_id=self.run_id,
            sequence=self.sequence,
            timestamp_utc=datetime.now(UTC),
            event_type=event_type,
            payload=payload,
            parent_event_id=parent_event_id,
        )
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")
        self.sequence += 1
        self._last_event_id = event.event_id
        return event


def read_trace(path: Path, *, expected_run_id: str | None = None) -> list[EpisodeEvent]:
    """Load a complete trace and reject gaps, corrupt JSON, or mixed run IDs."""

    events: list[EpisodeEvent] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise ReplayError(f"blank trace line at {line_number}")
                payload = json.loads(line)
                validate_schema_version(
                    payload,
                    EpisodeEvent,
                    artifact=f"{path.name}:{line_number}",
                )
                event = EpisodeEvent.model_validate(payload)
                if event.sequence != len(events):
                    raise ReplayError(
                        f"trace sequence gap at line {line_number}: "
                        f"expected {len(events)}, got {event.sequence}"
                    )
                if expected_run_id is not None and event.run_id != expected_run_id:
                    raise ReplayError(
                        f"trace event {event.sequence} belongs to unexpected run {event.run_id}"
                    )
                events.append(event)
    except (ReplayError, SchemaCompatibilityError):
        raise
    except Exception as exc:
        raise ReplayError(f"cannot read trace {path}: {exc}") from exc
    return events
