from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from verigym.plugin_api import CompletedCommand, ErrorCategory, RuntimeSession, ToolContext
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec

from verigym_synopsys.dc import (
    DesignCompilerSynthesisTool,
    _generated_script_hash,
)
from verigym_synopsys.vcs import VcsSimulationTool


def _session(tmp_path: Path, files: dict[str, bytes]) -> tuple[LocalRuntime, RuntimeSession]:
    source = tmp_path / "source"
    source.mkdir()
    for relative, payload in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    runtime = LocalRuntime()
    session = runtime.create_session(SessionSpec(source_dir=str(source), label="verifier"))
    return runtime, session


def test_vcs_stages_testbench_first_and_redacts_license(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    license_value = "27000" + "@secret-license-host"
    monkeypatch.setenv("SNPSLMD_LICENSE_FILE", license_value)
    runtime, session = _session(
        tmp_path,
        {
            "rtl/dut.v": b"module dut; endmodule\n",
            "verifier/tb.v": b"module tb; endmodule\n",
        },
    )
    try:
        plugin = VcsSimulationTool()
        request = plugin.validate_request(
            {
                "sources": ["rtl/dut.v"],
                "testbench": "verifier/tb.v",
                "top": "tb",
                "pass_marker": "PASSED",
                "fail_marker": "FAILED",
            }
        )
        context = ToolContext(session=session, artifact_dir=tmp_path / "artifacts")
        command = plugin.build_command(request, context)
        assert command.requires_shell is False
        assert command.argv.index("input/000.v") < command.argv.index("input/001.v")
        assert "SNPSLMD_LICENSE_FILE" in command.env
        assert set(command.env) <= {"SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE", "VCS_HOME"}
        result = plugin.parse_result(
            request,
            CompletedCommand(
                argv=command.argv,
                cwd=command.cwd,
                exit_code=0,
                stdout=f"PASSED {license_value}",
            ),
            context,
        )
        assert result.success
        assert "secret-license-host" not in result.stdout
        assert "redacted-license" in result.stdout
    finally:
        session.close()
        runtime.close()


def test_vcs_classifies_license_failure(tmp_path: Path) -> None:
    runtime, session = _session(
        tmp_path,
        {
            "rtl/dut.v": b"module dut; endmodule\n",
            "verifier/tb.v": b"module tb; endmodule\n",
        },
    )
    try:
        plugin = VcsSimulationTool()
        request = plugin.validate_request(
            {
                "sources": ["rtl/dut.v"],
                "testbench": "verifier/tb.v",
            }
        )
        result = plugin.parse_result(
            request,
            CompletedCommand(
                argv=["vcs"],
                cwd=".",
                exit_code=1,
                stderr="License checkout failed",
            ),
            ToolContext(session=session),
        )
        assert result.category == ErrorCategory.LICENSE_UNAVAILABLE
        assert result.metadata["candidate_failure"] is False
    finally:
        session.close()
        runtime.close()


def test_dc_parses_bounded_area_and_timing_metrics(tmp_path: Path) -> None:
    source_payload = (
        b"module counter(input clk, output reg q); always @(posedge clk) q<=~q; endmodule\n"
    )
    db_payload = b"fake-db"
    sdc_payload = b"create_clock -period 10 [get_ports clk]\n"
    runtime, session = _session(
        tmp_path,
        {
            "rtl/counter.v": source_payload,
            ".verigym_profile/cells.db": db_payload,
            ".verigym_profile/constraints.sdc": sdc_payload,
        },
    )
    try:
        db_hash = hashlib.sha256(db_payload).hexdigest()
        sdc_hash = hashlib.sha256(sdc_payload).hexdigest()
        script_hash = _generated_script_hash(
            ["rtl/counter.v"], "counter", 10.0, "ns", sdc_hash, True
        )
        plugin = DesignCompilerSynthesisTool()
        request = plugin.validate_request(
            {
                "sources": ["rtl/counter.v"],
                "top": "counter",
                "executable": "/opt/synopsys/bin/dc_shell",
                "library_sha256": db_hash,
                "constraints_sha256": sdc_hash,
                "area_unit": "um^2",
                "timing_unit": "ns",
                "clock_period": 10.0,
                "expected_flow_script_hash": script_hash,
                "resolved_profile_hash": "a" * 64,
                "run_label": "candidate",
            }
        )
        context = ToolContext(session=session, artifact_dir=tmp_path / "artifacts")
        command = plugin.build_command(request, context)
        session.write_file(
            ".verigym_internal/dc/candidate/out/metrics.kv",
            (
                "VERIGYM_DC_METRICS_V1\n"
                "mapped_area=42.5\n"
                "critical_path_delay=3.25\n"
                "worst_negative_slack=-0.125\n"
                "clock_period=10\n"
                "timing_unit=ns\n"
                f"constraints_sha256={sdc_hash}\n"
            ).encode(),
        )
        result = plugin.parse_result(
            request,
            CompletedCommand(argv=command.argv, cwd=command.cwd, exit_code=0),
            context,
        )
        assert result.success
        synthesis = result.metadata["synthesis"]
        assert synthesis["mapped_area_raw"] == 42.5
        assert synthesis["critical_path_delay_raw"] == 3.25
        assert synthesis["worst_negative_slack_raw"] == -0.125
        assert synthesis["timing_constraints_hash"] == sdc_hash
    finally:
        session.close()
        runtime.close()
