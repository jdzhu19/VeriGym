"""Persistent verifier-only replay evidence."""

from __future__ import annotations

from datetime import datetime

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import RuntimeDescriptor
from verigym.schemas.provenance import BuildProvenance


class ReplayEvidence(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    created_at_utc: datetime
    verifier_reexecuted: bool
    stored_integrity_status: str
    original_artifact_manifest_hash: str | None = None
    reverified_result_hash: str | None = None
    runtime: RuntimeDescriptor | None = None
    build_provenance: BuildProvenance


__all__ = ["ReplayEvidence"]
