"""Strict persistent schemas for cross-mode evaluation campaigns."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.reporting.schemas import ExplicitRate
from verigym.schemas.base import StrictModel
from verigym.schemas.provenance import BuildProvenance

CampaignMode = Literal["chat", "agent", "evolving_agent"]
CampaignInputKind = Literal["experiment", "evolving_evaluation"]

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
QUALITY_COMPARISON_POLICY = (
    "Only rows with the same comparison_partition_id are comparable; profile, task, "
    "correctness, runtime, units, constraints, and reference identities remain partitioned. "
    "The campaign never ranks different partitions."
)


def _safe_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("campaign identifiers must use [A-Za-z0-9._-] and be at most 128 chars")
    return value


def _safe_path(value: Path) -> Path:
    raw = value.as_posix()
    if not raw or ".." in value.parts or any(ord(character) < 32 for character in raw):
        raise ValueError("campaign paths must be control-free and cannot contain '..'")
    return value


def _hash(value: str) -> str:
    if not _HASH.fullmatch(value):
        raise ValueError("campaign identity fields must be lowercase SHA-256 values")
    return value


class CampaignInputConfig(StrictModel):
    id: str
    kind: CampaignInputKind
    evaluation_mode: CampaignMode
    experiment_root: Path
    evolving_report: Path | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("experiment_root", "evolving_report")
    @classmethod
    def validate_paths(cls, value: Path | None) -> Path | None:
        return _safe_path(value) if value is not None else None

    @model_validator(mode="after")
    def validate_kind(self) -> CampaignInputConfig:
        if self.kind == "experiment":
            if self.evaluation_mode == "evolving_agent" or self.evolving_report is not None:
                raise ValueError("ordinary experiment inputs must use chat/agent and no report")
        elif self.evaluation_mode != "evolving_agent" or self.evolving_report is None:
            raise ValueError("evolving inputs require evolving_agent mode and evolving_report")
        return self


class CampaignOutputConfig(StrictModel):
    root: Path

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: Path) -> Path:
        return _safe_path(value)


class CampaignConfig(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: str
    description: str | None = None
    inputs: list[CampaignInputConfig] = Field(min_length=2, max_length=64)
    output: CampaignOutputConfig

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip() or len(value) > 192 or any(ord(character) < 32 for character in value):
            raise ValueError("campaign names must be nonempty bounded printable text")
        return value

    @model_validator(mode="after")
    def unique_inputs(self) -> CampaignConfig:
        identifiers = [item.id for item in self.inputs]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("campaign input IDs must be unique")
        return self


class CampaignModeCoverage(StrictModel):
    chat_inputs: int = Field(ge=0)
    agent_inputs: int = Field(ge=0)
    evolving_agent_inputs: int = Field(ge=0)
    complete_platform_matrix: bool

    @model_validator(mode="after")
    def validate_complete(self) -> CampaignModeCoverage:
        expected = bool(self.chat_inputs and self.agent_inputs and self.evolving_agent_inputs)
        if self.complete_platform_matrix != expected:
            raise ValueError("campaign mode-coverage completeness is inconsistent")
        return self


class CampaignEvaluationSummary(StrictModel):
    input_id: str
    evaluation_mode: CampaignMode
    source_kind: CampaignInputKind
    source_report_hash: str
    suite_id: str
    experiment_id: str
    plan_hash: str
    task_set_hash: str
    system_id: str
    agent_id: str
    model_id: str | None = None
    agent_version_id: str | None = None
    compatibility_partition_ids: list[str]
    planned_count: int = Field(ge=0)
    terminal_count: int = Field(ge=0)
    evaluable_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    infrastructure_failure_count: int = Field(ge=0)
    resolved_rate_evaluable: ExplicitRate
    macro_pass_at_1: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_total_tokens: float | None = Field(default=None, ge=0.0)
    mean_tool_calls: float | None = Field(default=None, ge=0.0)
    mean_wall_time_s: float | None = Field(default=None, ge=0.0)
    observed_model_api_calls: int | None = Field(default=None, ge=0)
    model_cost_sum: float | None = Field(default=None, ge=0.0)
    model_cost_unit: str | None = None
    license_unavailable_count: int | None = Field(default=None, ge=0)

    @field_validator("input_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "source_report_hash",
        "plan_hash",
        "task_set_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)

    @field_validator("compatibility_partition_ids")
    @classmethod
    def validate_partition_hashes(cls, values: list[str]) -> list[str]:
        return [_hash(value) for value in values]


class CampaignQualityPartition(StrictModel):
    input_id: str
    evaluation_mode: CampaignMode
    agent_version_id: str | None = None
    comparison_partition_id: str
    suite_source_identity: str
    task_id: str
    task_hash: str
    correctness_definition_hash: str
    declared_profile_id: str
    declared_profile_hash: str
    resolved_profile_hash: str
    runtime_identity_hash: str
    image_id: str | None = None
    metric_scope: str
    area_unit: str
    timing_unit: str | None = None
    clock_period: float | None = None
    reference_candidate_hash: str
    eligible_run_count: int = Field(ge=0)
    ineligible_run_count: int = Field(ge=0)
    area_ratio_median: float | None = None
    delay_ratio_median: float | None = None
    worst_negative_slack_delta_median: float | None = None

    @field_validator("input_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "comparison_partition_id",
        "suite_source_identity",
        "task_hash",
        "correctness_definition_hash",
        "declared_profile_hash",
        "resolved_profile_hash",
        "runtime_identity_hash",
        "reference_candidate_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


class CampaignReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    campaign_name: str
    campaign_config_hash: str
    input_set_hash: str
    build_provenance: BuildProvenance | None = None
    mode_coverage: CampaignModeCoverage
    evaluations: list[CampaignEvaluationSummary]
    quality_partitions: list[CampaignQualityPartition]
    quality_comparison_policy: Literal[
        "Only rows with the same comparison_partition_id are comparable; profile, task, "
        "correctness, runtime, units, constraints, and reference identities remain partitioned. "
        "The campaign never ranks different partitions."
    ] = (
        "Only rows with the same comparison_partition_id are comparable; profile, task, "
        "correctness, runtime, units, constraints, and reference identities remain partitioned. "
        "The campaign never ranks different partitions."
    )
    offline_only: Literal[True] = True
    model_calls_during_reporting: Literal[0] = 0
    tool_calls_during_reporting: Literal[0] = 0
    warnings: list[str] = Field(default_factory=list)
    report_hash: str

    @field_validator("campaign_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("campaign_config_hash", "input_set_hash", "report_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


__all__ = [
    "CampaignConfig",
    "CampaignEvaluationSummary",
    "CampaignInputConfig",
    "CampaignMode",
    "CampaignModeCoverage",
    "CampaignOutputConfig",
    "CampaignQualityPartition",
    "CampaignReport",
    "QUALITY_COMPARISON_POLICY",
]
