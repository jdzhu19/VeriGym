"""Strict internal and persistent schemas for VerilogEval V2 compatibility."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.task import ValidationIssue


class VerilogEvalVariant(StrEnum):
    V2_SPEC_TO_RTL = "v2-spec-to-rtl"


class IcarusCompatibility(StrEnum):
    REFERENCE_COMPATIBLE = "canonical_or_reference_compatible"
    UNVERIFIED = "unverified_tool_version"
    INCOMPATIBLE = "incompatible_tool_version"


class VerilogEvalLayout(StrictModel):
    source_root: Path
    dataset_root: Path
    variant: VerilogEvalVariant
    native_layout: str = "dataset_spec-to-rtl-triplets-v2"


class VerilogEvalProblem(StrictModel):
    native_id: str
    prompt_path: Path
    reference_path: Path
    testbench_path: Path
    prompt: str
    reference: str
    testbench: str
    content_hash: str
    testbench_top: str = "tb"


class VerilogEvalCatalog(StrictModel):
    layout: VerilogEvalLayout
    problems: list[VerilogEvalProblem] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    dataset_content_hash: str


class NativeRegressionResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    compile_ok: bool
    simulation_ok: bool
    samples_checked: int | None = None
    mismatches: int | None = None
    resolved: bool
    native_result_marker_found: bool
    native_timeout: bool = False
    process_timed_out: bool = False
    tool_version: str | None = None
    compatibility_status: IcarusCompatibility


__all__ = [
    "IcarusCompatibility",
    "NativeRegressionResult",
    "VerilogEvalCatalog",
    "VerilogEvalLayout",
    "VerilogEvalProblem",
    "VerilogEvalVariant",
]
