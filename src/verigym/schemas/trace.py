"""Append-only episode event schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from verigym.schemas.base import SCHEMA_VERSION, StrictModel


class EpisodeEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    event_id: str
    run_id: str
    sequence: int
    timestamp_utc: datetime
    event_type: str
    payload: dict[str, Any]
    parent_event_id: str | None = None
