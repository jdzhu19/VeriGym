"""Persistent schemas for one-task independent sample sets and canonical pass@k."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.provenance import BuildProvenance


class SampleOutcome(StrEnum):
    RESOLVED = "resolved"
    CANDIDATE_FAILURE = "candidate_failure"
    MODEL_OUTPUT_FAILURE = "model_output_failure"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    CANCELLED_TRUNCATED = "cancelled_truncated"


class SampleRunRef(StrictModel):
    schema_version: str = SCHEMA_VERSION
    sample_index: int = Field(ge=0)
    seed: int
    run_id: str
    task_id: str
    relative_path: str
    outcome: SampleOutcome
    resolved: bool
    candidate_verdict: bool
    task_hash: str
    source_hash: str
    configuration_fingerprint: str

    @field_validator("relative_path")
    @classmethod
    def relative_child_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("sample child paths must be nonempty relative paths")
        return path.as_posix()


class SampleSetManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    sample_set_id: str
    created_at_utc: datetime
    task_id: str
    requested_sample_count: int = Field(ge=1)
    requested_k: list[int] = Field(min_length=1)
    base_seed: int
    build_provenance: BuildProvenance | None = None
    homogeneous_configuration_hash: str | None = None
    child_runs: list[SampleRunRef] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @field_validator("requested_k")
    @classmethod
    def positive_unique_k(cls, values: list[int]) -> list[int]:
        if any(value < 1 for value in values):
            raise ValueError("all requested k values must be positive")
        if len(values) != len(set(values)):
            raise ValueError("requested k values must be unique")
        return values

    @model_validator(mode="after")
    def consistent_children(self) -> SampleSetManifest:
        if len(self.child_runs) > self.requested_sample_count:
            raise ValueError("sample set has more children than requested")
        indices = [child.sample_index for child in self.child_runs]
        if len(indices) != len(set(indices)):
            raise ValueError("sample indices must be unique")
        run_ids = [child.run_id for child in self.child_runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("child run IDs must be unique")
        return self


class PassAtKEntry(StrictModel):
    schema_version: str = SCHEMA_VERSION
    k: int = Field(ge=1)
    n: int = Field(ge=0)
    c: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    valid: bool
    invalid_reason: str | None = None

    @model_validator(mode="after")
    def coherent_validity(self) -> PassAtKEntry:
        if self.c > self.n:
            raise ValueError("c cannot exceed n")
        if self.valid and (self.value is None or self.invalid_reason is not None):
            raise ValueError("valid pass@k entries require a value and no invalid reason")
        if not self.valid and (self.value is not None or not self.invalid_reason):
            raise ValueError("invalid pass@k entries require an invalid reason and no value")
        return self


class PassAtKReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    sample_set_id: str
    task_id: str
    requested_sample_count: int = Field(ge=1)
    valid_candidate_verdict_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    candidate_failure_count: int = Field(ge=0)
    model_output_failure_count: int = Field(ge=0)
    infrastructure_error_count: int = Field(ge=0)
    cancelled_truncated_count: int = Field(ge=0)
    missing_child_count: int = Field(ge=0)
    empirical_resolved_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    any_resolved: bool
    homogeneous: bool
    homogeneity_error: str | None = None
    canonical_valid: bool
    entries: list[PassAtKEntry]
    child_runs: list[SampleRunRef]

    @model_validator(mode="after")
    def coherent_counts(self) -> PassAtKReport:
        classified = (
            self.valid_candidate_verdict_count
            + self.infrastructure_error_count
            + self.cancelled_truncated_count
        )
        if classified != len(self.child_runs):
            raise ValueError("sample outcome counts do not match child runs")
        if len(self.child_runs) + self.missing_child_count != self.requested_sample_count:
            raise ValueError("child and missing counts do not match the requested sample count")
        verdicts = (
            self.resolved_count + self.candidate_failure_count + self.model_output_failure_count
        )
        if verdicts != self.valid_candidate_verdict_count:
            raise ValueError("candidate-verdict counts are inconsistent")
        if self.any_resolved != (self.resolved_count > 0):
            raise ValueError("any_resolved is inconsistent with resolved_count")
        return self


class SampleSetResult(StrictModel):
    group_dir: Path
    manifest: SampleSetManifest
    report: PassAtKReport


__all__ = [
    "PassAtKEntry",
    "PassAtKReport",
    "SampleOutcome",
    "SampleRunRef",
    "SampleSetManifest",
    "SampleSetResult",
]
