"""Strict machine-readable aggregate schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from verigym.schemas.base import StrictModel
from verigym.schemas.provenance import BuildProvenance
from verigym.schemas.sampling import PassAtKEntry


class ExplicitRate(StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_rate(self) -> ExplicitRate:
        expected = self.numerator / self.denominator if self.denominator else None
        if self.unavailable_reason is not None:
            if self.value is not None:
                raise ValueError("an unavailable rate must have a null value")
        elif self.value != expected:
            raise ValueError("rate value does not match its explicit numerator and denominator")
        return self


class CoverageCounts(StrictModel):
    planned_plan_items: int = Field(ge=0)
    started_plan_items: int = Field(ge=0)
    terminal_child_runs: int = Field(ge=0)
    valid_terminal_artifacts: int = Field(ge=0)
    evaluable_candidate_runs: int = Field(ge=0)
    resolved_runs: int = Field(ge=0)
    unresolved_evaluable_runs: int = Field(ge=0)
    infrastructure_error_runs: int = Field(ge=0)
    cancelled_interrupted_runs: int = Field(ge=0)
    corrupt_incompatible_artifacts: int = Field(ge=0)
    missing_plan_items: int = Field(ge=0)


class StageRate(StrictModel):
    stage: str
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0.0, le=1.0)
    missing_count: int = Field(ge=0)
    infrastructure_error_count: int = Field(ge=0)


class NumericSummary(StrictModel):
    population: str
    known_value_count: int = Field(ge=0)
    missing_value_count: int = Field(ge=0)
    mean: float | None = None
    median: float | None = None
    sum: float | None = None
    unit: str | None = None
    currency: str | None = None


class CostPartition(StrictModel):
    dimension: Literal["currency", "provider_unit"]
    identifier: str
    known_value_count: int = Field(ge=1)
    sum: float = Field(ge=0.0)


class CostAccounting(StrictModel):
    population: str
    observed_value_count: int = Field(ge=0)
    missing_value_count: int = Field(ge=0)
    unknown_unit_count: int = Field(ge=0)
    incompatible_unit_count: int = Field(ge=0)
    partitions: list[CostPartition] = Field(default_factory=list)


class FailureTaxonomy(StrictModel):
    candidate_outcomes: dict[str, int] = Field(default_factory=dict)
    model_infrastructure: dict[str, int] = Field(default_factory=dict)
    runtime_sandbox: dict[str, int] = Field(default_factory=dict)
    verifier_tool: dict[str, int] = Field(default_factory=dict)
    batch_artifact: dict[str, int] = Field(default_factory=dict)


class InvalidInput(StrictModel):
    relative_path: str
    category: str
    message: str
    plan_index: int | None = Field(default=None, ge=0)
    attempt: int | None = Field(default=None, ge=1)


class SampleGroupAggregate(StrictModel):
    group_id: str
    task_id: str
    system_id: str
    base_seed: int
    expected_n: int = Field(ge=1)
    observed_n: int = Field(ge=0)
    resolved_c: int = Field(ge=0)
    evaluable_count: int = Field(ge=0)
    infrastructure_error_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    canonical_valid: bool
    invalid_reason: str | None = None
    best_of_n_success: bool | None = None
    entries: list[PassAtKEntry]


class PassAtKMacro(StrictModel):
    k: int = Field(ge=1)
    valid_group_count: int = Field(ge=0)
    invalid_group_count: int = Field(ge=0)
    missing_group_count: int = Field(ge=0)
    macro_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_median: float | None = Field(default=None, ge=0.0, le=1.0)


class SamplingAggregate(StrictModel):
    groups: list[SampleGroupAggregate]
    macro: list[PassAtKMacro]


class QualityRunValue(StrictModel):
    plan_index: int = Field(ge=0)
    run_id: str
    task_id: str
    system_id: str
    eligible: bool
    ineligible_reasons: list[str] = Field(default_factory=list)
    area: float | None = None
    reference_area: float | None = None
    area_ratio: float | None = None


class QualityPartition(StrictModel):
    partition_id: str
    suite_source_identity: str
    task_id: str
    task_hash: str
    correctness_definition_hash: str
    declared_profile_id: str
    declared_profile_hash: str
    resolved_profile_hash: str
    runtime_identity_hash: str
    image_id: str | None = None
    area_unit: str
    reference_candidate_hash: str
    eligible_run_count: int = Field(ge=0)
    ineligible_run_count: int = Field(ge=0)
    ineligible_reasons: dict[str, int] = Field(default_factory=dict)
    task_system_coverage: dict[str, int] = Field(default_factory=dict)
    ratio_min: float | None = None
    ratio_median: float | None = None
    ratio_max: float | None = None
    runs: list[QualityRunValue]


class GroupAggregate(StrictModel):
    compatibility_partition_id: str
    dimensions: dict[str, str]
    planned_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    evaluable_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    resolved_rate_evaluable: ExplicitRate
    task_coverage_count: int = Field(ge=0)


class CompatibilityAggregate(StrictModel):
    partition_id: str
    suite_release_identity: str
    correctness_definition_hash: str
    planned_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    evaluable_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    resolved_rate_evaluable: ExplicitRate
    resolved_rate_planned: ExplicitRate
    correctness_stages: list[StageRate]
    task_coverage_count: int = Field(ge=0)
    system_coverage_count: int = Field(ge=0)


class AggregateReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str
    source_kind: Literal["experiment", "runs_root"]
    config_hash: str | None = None
    plan_hash: str | None = None
    task_set_hash: str | None = None
    input_set_hash: str
    build_provenance: BuildProvenance | None = None
    compatibility_partitions: dict[str, list[str]] = Field(default_factory=dict)
    compatibility_aggregates: list[CompatibilityAggregate] = Field(default_factory=list)
    coverage: CoverageCounts
    resolved_rate_evaluable: ExplicitRate
    resolved_rate_planned: ExplicitRate
    evaluation_completion_rate: ExplicitRate
    correctness_stages: list[StageRate]
    efficiency_resolved: dict[str, NumericSummary]
    cost_resolved: NumericSummary
    cost_accounting: CostAccounting | None = None
    failure_taxonomy: FailureTaxonomy
    sampling: SamplingAggregate
    quality_partitions: list[QualityPartition]
    grouped_aggregates: list[GroupAggregate]
    warnings: list[str] = Field(default_factory=list)
    invalid_inputs: list[InvalidInput] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AggregateReport",
    "CoverageCounts",
    "CompatibilityAggregate",
    "CostAccounting",
    "CostPartition",
    "ExplicitRate",
    "FailureTaxonomy",
    "GroupAggregate",
    "InvalidInput",
    "NumericSummary",
    "PassAtKMacro",
    "QualityPartition",
    "QualityRunValue",
    "SampleGroupAggregate",
    "SamplingAggregate",
    "StageRate",
]
