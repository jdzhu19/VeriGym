"""Strict internal and persistent schemas for VerilogEval V2 compatibility."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.task import ValidationIssue


class VerilogEvalVariant(StrEnum):
    V2_SPEC_TO_RTL = "v2-spec-to-rtl"
    V2_SPEC_TO_RTL_AGENT_EVAL_V1 = "v2-spec-to-rtl-agent-eval-v1"
    V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V1 = "v2-spec-to-rtl-agent-eval-functional-v1"
    V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2 = "v2-spec-to-rtl-agent-eval-functional-v2"
    V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3 = "v2-spec-to-rtl-agent-eval-functional-v3"
    V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4 = "v2-spec-to-rtl-agent-eval-functional-v4"


class IcarusCompatibility(StrEnum):
    REFERENCE_COMPATIBLE = "canonical_or_reference_compatible"
    UNVERIFIED = "unverified_tool_version"
    INCOMPATIBLE = "incompatible_tool_version"


class VerilogEvalDiagnosticCode(StrEnum):
    COMPILE_TOP_MODULE_CONTRACT = "compile.top_module_contract"
    COMPILE_RESERVED_MODULE = "compile.reserved_module_collision"
    COMPILE_SYNTAX_ERROR = "compile.syntax_error"
    COMPILE_EXPLICIT_CAST_REQUIRED = "compile.explicit_cast_required"
    COMPILE_ZERO_WIDTH_CONSTANT = "compile.zero_width_constant"
    COMPILE_MISSING_SENSITIVITY = "compile.missing_sensitivity"
    COMPILE_WIRE_ASSIGNMENT = "compile.wire_assignment"
    COMPILE_UNKNOWN_MODULE = "compile.unknown_module"
    COMPILE_PORT_BINDING = "compile.port_binding"
    COMPILE_OTHER = "compile.other"
    SIMULATION_PROCESS_TIMEOUT = "simulation.process_timeout"
    SIMULATION_NATIVE_TIMEOUT = "simulation.native_timeout"
    SIMULATION_NONZERO_EXIT = "simulation.nonzero_exit"
    SIMULATION_MISSING_SUMMARY = "simulation.missing_summary"
    VERIFICATION_MISMATCH = "verification.mismatch"


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
    diagnostic_code: VerilogEvalDiagnosticCode | None = None


__all__ = [
    "IcarusCompatibility",
    "NativeRegressionResult",
    "VerilogEvalCatalog",
    "VerilogEvalDiagnosticCode",
    "VerilogEvalLayout",
    "VerilogEvalProblem",
    "VerilogEvalVariant",
]
