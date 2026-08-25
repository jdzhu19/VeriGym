"""Persistent, tool-neutral synthesis result schemas."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel


class SynthesisDiagnostic(StrictModel):
    severity: Literal["warning", "error", "info"]
    code: str
    message: str


class SynthesisArtifactRef(StrictModel):
    path: str
    content_hash: str
    size_bytes: int = Field(ge=0)
    role: Literal["generated_script", "tool_log", "statistics", "netlist_json", "netlist_verilog"]
    visibility: Literal["public", "verifier_private", "summary_only"]


class SynthesisMetrics(StrictModel):
    schema_version: str = SCHEMA_VERSION
    status: Literal["passed", "failed", "error", "skipped"]
    synthesis_ok: bool
    role: Literal["candidate", "reference"]
    top: str
    num_wires: int | None = Field(default=None, ge=0)
    num_wire_bits: int | None = Field(default=None, ge=0)
    num_memories: int | None = Field(default=None, ge=0)
    num_memory_bits: int | None = Field(default=None, ge=0)
    num_processes: int | None = Field(default=None, ge=0)
    num_cells: int | None = Field(default=None, ge=0)
    cells_by_type: dict[str, int] = Field(default_factory=dict)
    mapped_area_raw: float | None = None
    mapped_area_unit: str | None = None
    mapped_area_source_hash: str | None = None
    critical_path_delay_raw: float | None = None
    worst_negative_slack_raw: float | None = None
    timing_unit: str | None = None
    clock_period: float | None = None
    timing_constraints_hash: str | None = None
    total_power_raw: float | None = None
    power_unit: str | None = None
    power_activity_mode: str | None = None
    warnings: list[SynthesisDiagnostic] = Field(default_factory=list)
    unsupported_constructs: list[SynthesisDiagnostic] = Field(default_factory=list)
    tool_identity: dict[str, Any] = Field(default_factory=dict)
    resolved_profile_hash: str | None = None
    generated_script_hash: str | None = None
    artifacts: list[SynthesisArtifactRef] = Field(default_factory=list)
    failure_category: str | None = None
    failure_message: str | None = None

    @field_validator("cells_by_type")
    @classmethod
    def validate_cell_histogram(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not key or count < 0 for key, count in value.items()):
            raise ValueError("cell histogram entries require names and nonnegative counts")
        return dict(sorted(value.items()))

    @field_validator("mapped_area_raw")
    @classmethod
    def validate_mapped_area(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("mapped area must be finite and positive")
        return value

    @field_validator("critical_path_delay_raw", "clock_period")
    @classmethod
    def validate_positive_timing(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("delay and clock period must be finite and positive")
        return value

    @field_validator("worst_negative_slack_raw")
    @classmethod
    def validate_slack(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("worst-negative slack must be finite")
        return value

    @field_validator("total_power_raw")
    @classmethod
    def validate_total_power(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("total power must be finite and positive")
        return value

    @model_validator(mode="after")
    def validate_timing_identity(self) -> SynthesisMetrics:
        values = (
            self.critical_path_delay_raw,
            self.worst_negative_slack_raw,
            self.clock_period,
        )
        if any(value is not None for value in values):
            if not self.timing_unit or not self.timing_constraints_hash:
                raise ValueError("timing metrics require a unit and constraints hash")
        if self.total_power_raw is not None:
            if not self.power_unit or not self.power_activity_mode:
                raise ValueError("power metrics require a unit and activity mode")
        elif self.power_unit is not None or self.power_activity_mode is not None:
            raise ValueError("power identity cannot be present without total power")
        return self


__all__ = ["SynthesisArtifactRef", "SynthesisDiagnostic", "SynthesisMetrics"]
