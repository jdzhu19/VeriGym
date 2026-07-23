"""Local MVP release-audit bundle schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.provenance import BuildProvenance

AuditStatus = Literal["passed", "failed", "blocked", "skipped"]


class EvidenceEntry(StrictModel):
    schema_version: str = SCHEMA_VERSION
    check_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    command_argv: list[str]
    started_at: datetime
    ended_at: datetime
    exit_code: int | None = None
    package_provenance: BuildProvenance
    identities: dict[str, Any] = Field(default_factory=dict)
    classification: AuditStatus
    output_paths: list[str] = Field(default_factory=list)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=2048)

    @field_validator("command_argv")
    @classmethod
    def command_is_bounded(cls, value: list[str]) -> list[str]:
        if not value or len(value) > 256 or any(len(item) > 4096 for item in value):
            raise ValueError("audit command must be a bounded non-empty argument array")
        return value

    @field_validator("output_paths")
    @classmethod
    def output_paths_are_relative(cls, value: list[str]) -> list[str]:
        from pathlib import PurePosixPath

        for raw in value:
            path = PurePosixPath(raw)
            if path.is_absolute() or ".." in path.parts or "\\" in raw:
                raise ValueError("audit output paths must be normalized and relative")
        return value

    @field_validator("artifact_hashes")
    @classmethod
    def hashes_are_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        for digest in value.values():
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("audit artifact hashes must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def status_is_consistent(self) -> EvidenceEntry:
        if self.ended_at < self.started_at:
            raise ValueError("audit evidence end time precedes start time")
        if self.classification == "passed" and self.exit_code != 0:
            raise ValueError("passed evidence must have exit code zero")
        if self.classification in {"blocked", "skipped"} and not self.reason:
            raise ValueError("blocked or skipped evidence requires a reason")
        return self


class AuditManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    audit_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    created_at: datetime
    package_name: str = "verigym"
    package_version: str
    package_provenance: BuildProvenance
    required_check_ids: list[str]
    gate_result: Literal["PASS", "FAIL"]
    gate_reasons: list[str]
    evidence_sha256: str
    hash_manifest_path: str = "hashes.sha256"
    bundle_hash_method: str = "sha256(hashes.sha256)"

    @field_validator("evidence_sha256")
    @classmethod
    def evidence_hash_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("evidence hash must be lowercase SHA-256")
        return value


__all__ = ["AuditManifest", "AuditStatus", "EvidenceEntry"]
