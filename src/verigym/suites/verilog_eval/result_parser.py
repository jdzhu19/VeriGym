"""Strict parser for the native VerilogEval V2 mismatch protocol."""

from __future__ import annotations

import re

from verigym.schemas.tool import CompletedCommand
from verigym.suites.verilog_eval.schemas import (
    IcarusCompatibility,
    NativeRegressionResult,
)

_SUMMARY = re.compile(r"(?m)^\s*Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples\s*$")
_TIMEOUT = re.compile(r"(?m)^\s*TIMEOUT\s*$")


def parse_native_result(
    completed: CompletedCommand,
    *,
    tool_version: str | None,
    compatibility: IcarusCompatibility,
) -> NativeRegressionResult:
    matches = list(_SUMMARY.finditer(completed.stdout))
    mismatch_count: int | None = None
    sample_count: int | None = None
    if matches:
        mismatch_count = int(matches[-1].group(1))
        sample_count = int(matches[-1].group(2))
    native_timeout = _TIMEOUT.search(completed.stdout) is not None
    simulation_ok = (
        completed.error is None
        and not completed.timed_out
        and completed.exit_code == 0
        and not completed.output_truncated
    )
    resolved = bool(
        simulation_ok
        and matches
        and mismatch_count == 0
        and sample_count is not None
        and sample_count > 0
        and not native_timeout
    )
    return NativeRegressionResult(
        compile_ok=True,
        simulation_ok=simulation_ok,
        samples_checked=sample_count,
        mismatches=mismatch_count,
        resolved=resolved,
        native_result_marker_found=bool(matches),
        native_timeout=native_timeout,
        process_timed_out=completed.timed_out,
        tool_version=tool_version,
        compatibility_status=compatibility,
    )


__all__ = ["parse_native_result"]
