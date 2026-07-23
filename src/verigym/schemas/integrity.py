"""Persistent artifact-integrity schemas."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel


class ArtifactEntry(StrictModel):
    relative_path: str
    role: str
    visibility: Literal["public", "private_summary"] = "public"
    size_bytes: int = Field(ge=0)
    sha256: str
    required: bool
    content_type: str

    @field_validator("relative_path")
    @classmethod
    def normalized_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or path.is_absolute()
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("artifact paths must be normalized, control-free relative paths")
        return value

    @field_validator("sha256")
    @classmethod
    def sha256_identity(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("artifact hash must be a lowercase SHA-256 value")
        return value


class ArtifactManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    scope: Literal["run", "experiment", "sample_set"]
    owner_id: str
    entries_hash: str
    entries: list[ArtifactEntry]

    @field_validator("entries_hash")
    @classmethod
    def sha256_identity(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("entries hash must be a lowercase SHA-256 value")
        return value


class IntegrityValidation(StrictModel):
    schema_version: str = SCHEMA_VERSION
    status: Literal["verified", "legacy_unverified"]
    manifest_hash: str | None = None
    verified_entry_count: int = Field(default=0, ge=0)
    verified_byte_count: int = Field(default=0, ge=0)


__all__ = ["ArtifactEntry", "ArtifactManifest", "IntegrityValidation"]
