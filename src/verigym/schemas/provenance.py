"""Source and distribution build provenance."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel


class BuildProvenance(StrictModel):
    """Secret-free identity for the source state that produced this package."""

    schema_version: str = SCHEMA_VERSION
    package_name: str = "verigym"
    package_version: str
    source_commit: str | None = None
    source_tree_hash: str | None = None
    dirty: bool | None = None
    provenance_method: Literal[
        "git_live_editable",
        "embedded_build",
        "embedded_source_archive",
        "unknown",
    ]
    build_backend: str | None = None
    python_build_version: str | None = None
    build_source_date_epoch: int | None = Field(default=None, ge=0)
    source_archive_hash: str | None = None
    installed_distribution_metadata_hash: str | None = None
    source_tree_path_policy: str
    source_tree_file_count: int | None = Field(default=None, ge=0)
    unknown_reason: str | None = None

    @field_validator("source_commit")
    @classmethod
    def validate_commit(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) not in {40, 64}
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("source commit must be a lowercase Git object identity")
        return value

    @field_validator(
        "source_tree_hash", "source_archive_hash", "installed_distribution_metadata_hash"
    )
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("provenance hashes must be lowercase SHA-256 values")
        return value


__all__ = ["BuildProvenance"]
