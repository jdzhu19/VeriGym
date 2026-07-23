"""Persistent, tool-neutral synthesis result schemas."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, field_validator

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


__all__ = ["SynthesisArtifactRef", "SynthesisDiagnostic", "SynthesisMetrics"]
