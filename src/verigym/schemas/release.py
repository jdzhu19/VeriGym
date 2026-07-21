"""Immutable benchmark-release manifest schema (designed now, built later)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from verigym.schemas.base import SCHEMA_VERSION, StrictModel


class SuiteReleaseRef(StrictModel):
    suite: str
    version: str
    task_count: int
    content_hash: str


class ReleaseManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    release_id: str
    created_at_utc: datetime
    suites: list[SuiteReleaseRef]
    task_count: int
    source_cutoff: datetime | None = None
    split_policy: str
    licenses: list[str]
    checksums: dict[str, str]
    changelog: list[str]
    retired_tasks: list[str] = Field(default_factory=list)
