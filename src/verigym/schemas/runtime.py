"""Runtime session and workspace-diff schemas."""

from __future__ import annotations

from pydantic import Field

from verigym.schemas.base import StrictModel
from verigym.schemas.common import RuntimeDescriptor


class SessionSpec(StrictModel):
    source_dir: str
    label: str
    max_output_bytes: int = Field(default=1_000_000, ge=1)
    environment: dict[str, str] = Field(default_factory=dict)


class WorkspaceDiff(StrictModel):
    patch: str = ""
    changed_files: list[str] = Field(default_factory=list)
    added_lines: int = 0
    deleted_lines: int = 0
    changes_outside_expected_files: list[str] = Field(default_factory=list)


__all__ = ["RuntimeDescriptor", "SessionSpec", "WorkspaceDiff"]
