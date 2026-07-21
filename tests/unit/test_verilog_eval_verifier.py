from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from verigym.schemas.common import ErrorCategory
from verigym.schemas.tool import CompletedCommand
from verigym.suites.verilog_eval.result_parser import parse_native_result
from verigym.suites.verilog_eval.schemas import IcarusCompatibility
from verigym.suites.verilog_eval.toolchain import classify_icarus_version
from verigym.suites.verilog_eval.verifier import (
    VerilogEvalCompileRequest,
    VerilogEvalRegressionRequest,
    VerilogEvalRegressionTool,
)
from verigym.tools.base import ToolContext


def completed(
    stdout: str,
    *,
    exit_code: int | None = 0,
    timed_out: bool = False,
    output_truncated: bool = False,
    error: str | None = None,
) -> CompletedCommand:
    return CompletedCommand(
        argv=["vvp", "simv"],
        cwd=".",
        exit_code=exit_code,
        stdout=stdout,
        timed_out=timed_out,
        output_truncated=output_truncated,
        error=error,
    )


def parse(command: CompletedCommand):
    return parse_native_result(
        command,
        tool_version="Icarus Verilog runtime version 12.0",
        compatibility=IcarusCompatibility.REFERENCE_COMPATIBLE,
    )


def test_native_parser_zero_nonzero_and_final_occurrence() -> None:
    passed = parse(completed("Mismatches: 0 in 100 samples\n"))
    assert passed.resolved
    assert passed.mismatches == 0
    assert passed.samples_checked == 100

    failed = parse(completed("Mismatches: 0 in 2 samples\nMismatches: 3 in 10 samples\n"))
    assert not failed.resolved
    assert failed.mismatches == 3
    assert failed.samples_checked == 10


def test_native_parser_requires_exact_stdout_marker_and_rejects_timeouts() -> None:
    missing = parse(completed("simulation completed successfully\n"))
    assert not missing.resolved
    assert not missing.native_result_marker_found

    prefixed = parse(completed("candidate says Mismatches: 0 in 2 samples\n"))
    assert not prefixed.native_result_marker_found

    native_timeout = parse(completed("Mismatches: 0 in 2 samples\nTIMEOUT\n"))
    assert not native_timeout.resolved
    assert native_timeout.native_timeout

    process_timeout = parse(completed("", exit_code=-9, timed_out=True))
    assert not process_timeout.simulation_ok
    assert process_timeout.process_timed_out


def test_native_parser_does_not_accept_stderr_marker_or_zero_samples() -> None:
    stderr_only = completed("")
    stderr_only.stderr = "Mismatches: 0 in 10 samples\n"
    assert not parse(stderr_only).native_result_marker_found
    zero_samples = parse(completed("Mismatches: 0 in 0 samples\n"))
    assert zero_samples.native_result_marker_found
    assert not zero_samples.resolved


def test_compile_request_enforces_candidate_last_and_regression_requires_executable() -> None:
    valid = VerilogEvalCompileRequest(
        sources=["verifier/golden.sv", "verifier/testbench.sv", "rtl/TopModule.sv"]
    )
    assert valid.sources[-1] == valid.candidate
    with pytest.raises(ValidationError, match="candidate source must be last"):
        VerilogEvalCompileRequest(
            sources=["rtl/TopModule.sv", "verifier/golden.sv", "verifier/testbench.sv"]
        )
    with pytest.raises(ValidationError, match="either executable"):
        VerilogEvalRegressionRequest()


def test_regression_process_timeout_is_marked_as_candidate_failure(tmp_path: Path) -> None:
    request = VerilogEvalRegressionRequest(executable="simv")
    result = VerilogEvalRegressionTool().parse_result(
        request,
        completed("", exit_code=-9, timed_out=True),
        ToolContext(artifact_dir=tmp_path),
    )
    assert not result.success
    assert result.category == ErrorCategory.TIMEOUT
    assert result.metadata["candidate_failure"] is True
    assert result.metadata["process_timed_out"] is True


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (
            "Icarus Verilog version 12.0 (stable)",
            IcarusCompatibility.REFERENCE_COMPATIBLE,
        ),
        (
            "Icarus Verilog runtime version 13.0 (devel)",
            IcarusCompatibility.INCOMPATIBLE,
        ),
        ("Icarus Verilog version 11.0", IcarusCompatibility.UNVERIFIED),
        ("unknown", IcarusCompatibility.UNVERIFIED),
        (None, IcarusCompatibility.UNVERIFIED),
    ],
)
def test_icarus_compatibility_labels(
    version: str | None,
    expected: IcarusCompatibility,
) -> None:
    assert classify_icarus_version(version) == expected
