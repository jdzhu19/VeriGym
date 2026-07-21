"""Typed configuration and provenance for externally supplied suite sources."""

from __future__ import annotations

from pathlib import Path

from verigym.schemas.base import SCHEMA_VERSION, StrictModel


class SuiteSourceConfig(StrictModel):
    schema_version: str = SCHEMA_VERSION
    source_root: Path
    variant: str | None = None
    strict_compatibility: bool = True


class SuiteSourceSnapshot(StrictModel):
    schema_version: str = SCHEMA_VERSION
    source_root: str
    dataset_root: str
    variant: str
    native_layout: str
    strict_compatibility: bool
    configuration_fingerprint: str
    dataset_content_hash: str
    license_id: str | None = None
    license_file_hash: str | None = None
    git_commit: str | None = None
    git_remote: str | None = None
    git_metadata_available: bool = False
    synthetic_fixture: bool = False


__all__ = ["SuiteSourceConfig", "SuiteSourceSnapshot"]
