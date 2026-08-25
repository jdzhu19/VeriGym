"""Correctness-first scorecard and raw metric dimensions."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.synthesis import SynthesisMetrics
from verigym.schemas.verifier import VerifierResult


class CorrectnessMetrics(StrictModel):
    compile_status: str | None = None
    visible_regression_status: str | None = None
    hidden_regression_status: str | None = None
    formal_status: str | None = None
    equivalence_status: str | None = None
    tests_passed: int | None = None
    tests_total: int | None = None
    resolved: bool
    infrastructure_error: bool = False


class PPAMetrics(StrictModel):
    profile_id: str
    profile_version: str = ""
    resolved_profile_hash: str = ""
    scope: Literal[
        "synthesis_area_only",
        "synthesis_area_timing",
        "synthesis_area_timing_power",
    ] = "synthesis_area_only"
    eligible: bool
    ineligible_reasons: list[str] = Field(default_factory=list)
    area: float | None = None
    area_unit: str | None = None
    delay: float | None = None
    frequency: float | None = None
    power: float | None = None
    power_unit: str | None = None
    worst_negative_slack: float | None = None
    total_negative_slack: float | None = None
    timing_unit: str | None = None
    clock_period: float | None = None
    violations: dict[str, int] = Field(default_factory=dict)
    reference_area: float | None = None
    reference_delay: float | None = None
    reference_worst_negative_slack: float | None = None
    reference_power: float | None = None
    area_ratio: float | None = None
    delay_ratio: float | None = None
    worst_negative_slack_delta: float | None = None
    power_ratio: float | None = None

    @model_validator(mode="after")
    def validate_ranked_metrics(self) -> PPAMetrics:
        ranked = (self.area, self.reference_area, self.area_ratio)
        if self.eligible:
            if any(value is None for value in ranked) or self.area_unit is None:
                raise ValueError(
                    "eligible area ranking requires candidate, reference, ratio, and unit"
                )
            if self.ineligible_reasons:
                raise ValueError("eligible PPA metrics cannot have ineligibility reasons")
            if any(value is None or not math.isfinite(value) or value <= 0 for value in ranked):
                raise ValueError("ranked area values must be finite and positive")
        elif any(value is not None for value in ranked):
            raise ValueError("ineligible candidates cannot expose ranked area values")
        if self.frequency is not None or self.total_negative_slack is not None:
            raise ValueError("frequency and TNS are unavailable in synthesis profiles")
        power = (self.power, self.reference_power, self.power_ratio)
        if self.scope == "synthesis_area_timing_power":
            if self.eligible:
                if any(value is None for value in power) or self.power_unit is None:
                    raise ValueError(
                        "eligible area-timing-power metrics require candidate/reference power, "
                        "ratio, and unit"
                    )
                if any(value is None or not math.isfinite(value) or value <= 0 for value in power):
                    raise ValueError("ranked power values must be finite and positive")
            elif any(value is not None for value in power) or self.power_unit is not None:
                raise ValueError("ineligible candidates cannot expose ranked power values")
        elif any(value is not None for value in power) or self.power_unit is not None:
            raise ValueError("power is available only in area-timing-power profiles")
        timing = (
            self.delay,
            self.worst_negative_slack,
            self.reference_delay,
            self.reference_worst_negative_slack,
            self.delay_ratio,
            self.worst_negative_slack_delta,
            self.clock_period,
        )
        if self.scope == "synthesis_area_only":
            if any(value is not None for value in timing) or self.timing_unit is not None:
                raise ValueError("area-only profile timing fields must remain null")
            return self
        if self.eligible:
            if any(value is None for value in timing) or self.timing_unit is None:
                raise ValueError(
                    "eligible area-timing metrics require candidate and reference timing"
                )
            positive = (self.delay, self.reference_delay, self.delay_ratio, self.clock_period)
            if any(value is None or not math.isfinite(value) or value <= 0 for value in positive):
                raise ValueError("ranked delay values and clock period must be finite and positive")
            signed = (
                self.worst_negative_slack,
                self.reference_worst_negative_slack,
                self.worst_negative_slack_delta,
            )
            if any(value is None or not math.isfinite(value) for value in signed):
                raise ValueError("ranked slack values must be finite")
        elif any(value is not None for value in timing) or self.timing_unit is not None:
            raise ValueError("ineligible candidates cannot expose ranked timing values")
        return self


class QualityMetrics(StrictModel):
    ppa: PPAMetrics | None = None
    synthesis: SynthesisMetrics | None = None
    reference_synthesis: SynthesisMetrics | None = None


class EfficiencyMetrics(StrictModel):
    wall_time_s: float = 0.0
    agent_time_s: float = 0.0
    tool_time_s: float = 0.0
    verifier_time_s: float = 0.0
    model_input_tokens: int | None = 0
    model_output_tokens: int | None = 0
    total_tokens: int | None = 0
    model_calls: int = 0
    model_api_cost: float | None = Field(default=None, ge=0.0)
    model_api_cost_currency: str | None = None
    model_api_cost_unit: str | None = None
    turns: int = 0
    tool_calls: int = 0
    failed_tool_calls: int = 0
    peak_memory_bytes: int | None = None
    external_cli_process_wall_time_s: float = Field(default=0.0, ge=0.0)
    external_cli_event_count: int = Field(default=0, ge=0)
    external_model_call_count: int | None = Field(default=None, ge=0)
    external_tool_call_count: int | None = Field(default=None, ge=0)
    external_command_count: int | None = Field(default=None, ge=0)
    external_file_read_count: int | None = Field(default=None, ge=0)
    external_file_write_count: int | None = Field(default=None, ge=0)
    external_patch_count: int | None = Field(default=None, ge=0)
    external_input_tokens: int | None = Field(default=None, ge=0)
    external_output_tokens: int | None = Field(default=None, ge=0)
    external_total_tokens: int | None = Field(default=None, ge=0)
    external_cost: float | None = Field(default=None, ge=0.0)
    external_cost_currency: str | None = None

    @field_validator("model_api_cost_currency", "model_api_cost_unit")
    @classmethod
    def validate_cost_identity(cls, value: str | None) -> str | None:
        if value is not None and (
            not value
            or value != value.strip()
            or len(value) > 64
            or any(ord(character) < 33 or ord(character) > 126 for character in value)
        ):
            raise ValueError("cost currency/unit must be a short printable identifier")
        return value

    @model_validator(mode="after")
    def validate_cost_dimensions(self) -> EfficiencyMetrics:
        if self.model_api_cost_currency is not None and self.model_api_cost_unit is not None:
            raise ValueError("model cost cannot declare both a currency and provider unit")
        if self.model_api_cost is None and (
            self.model_api_cost_currency is not None or self.model_api_cost_unit is not None
        ):
            raise ValueError("model cost identity requires a model_api_cost value")
        if self.external_cost is None and self.external_cost_currency is not None:
            raise ValueError("external-agent cost currency requires a known cost")
        if (
            self.external_total_tokens is None
            and self.external_input_tokens is not None
            and self.external_output_tokens is not None
        ):
            self.external_total_tokens = self.external_input_tokens + self.external_output_tokens
        return self


class PatchMetrics(StrictModel):
    changed_files: list[str] = Field(default_factory=list)
    added_lines: int = 0
    deleted_lines: int = 0
    total_diff_lines: int = 0
    changes_outside_expected_files: list[str] = Field(default_factory=list)
    changed_file_precision: float | None = None
    edit_similarity: float | None = None


class ReproducibilityMetrics(StrictModel):
    task_hash: str
    candidate_hash: str
    verifier_hash: str
    run_config_hash: str
    toolchain_profile_ids: list[str] = Field(default_factory=list)
    resolved_toolchain_profile_hashes: list[str] = Field(default_factory=list)
    deterministic: bool
    isolation_level: str


class EpisodeFailure(StrictModel):
    kind: Literal["agent", "model", "policy", "runtime"]
    category: str
    message: str
    infrastructure: bool = False
    protocol_error_subcategory: str | None = None


class ScoreCard(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    task_id: str
    status: Literal["completed", "failed", "error", "cancelled"]
    resolved: bool
    correctness: CorrectnessMetrics
    quality: QualityMetrics
    efficiency: EfficiencyMetrics
    patch: PatchMetrics
    reproducibility: ReproducibilityMetrics
    verifier_results: list[VerifierResult]
    termination_reason: str
    failure: EpisodeFailure | None = None
    warnings: list[str] = Field(default_factory=list)
