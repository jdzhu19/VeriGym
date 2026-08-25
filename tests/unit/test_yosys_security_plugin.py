from __future__ import annotations

import os
from pathlib import Path

import pytest

from verigym.core.hashing import hash_bytes
from verigym.core.workspace import normalize_relative_path
from verigym.runtimes.base import RuntimeSession
from verigym.schemas.common import ErrorCategory
from verigym.schemas.runtime import WorkspaceDiff
from verigym.schemas.tool import CommandSpec, CompletedCommand
from verigym.tools.base import ToolContext
from verigym.tools.yosys.plugin import YosysSynthesisTool
from verigym.tools.yosys.script_builder import generated_script_hash


class RecordingSession(RuntimeSession):
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self.executed: list[CommandSpec] = []

    @property
    def root(self) -> Path:
        return self._root

    def execute(self, command: CommandSpec) -> CompletedCommand:
        self.executed.append(command)
        return CompletedCommand(argv=command.argv, cwd=command.cwd, exit_code=0)

    def read_file(self, path: str) -> bytes:
        return (self._root / normalize_relative_path(path)).read_bytes()

    def write_file(self, path: str, data: bytes) -> None:
        destination = self._root / normalize_relative_path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    def snapshot_diff(self) -> WorkspaceDiff:
        return WorkspaceDiff()

    def close(self) -> None:
        return None


def _stage(
    tmp_path: Path, source_name: str = "rtl/counter.v"
) -> tuple[RecordingSession, dict[str, object]]:
    root = tmp_path / "session"
    source = root / source_name
    source.parent.mkdir(parents=True)
    source.write_text(
        "module counter(input clk, output reg q); always @(posedge clk) q<=~q; endmodule\n"
    )
    liberty_source = Path("src/verigym/profiles/builtins/assets/toy_cells.lib")
    liberty = liberty_source.read_bytes()
    liberty_path = root / ".verigym_profile" / "cells.lib"
    liberty_path.parent.mkdir(parents=True)
    liberty_path.write_bytes(liberty)
    return RecordingSession(root), {
        "sources": [source_name],
        "top": "counter",
        "liberty_asset_id": "verigym-toy-cells-v1",
        "liberty_path": ".verigym_profile/cells.lib",
        "liberty_sha256": hash_bytes(liberty),
        "area_unit": "toy_area_unit",
        "require_mapped_area": True,
        "expected_yosys_version": "0.67",
    }


def test_hostile_source_filename_is_safe_staged_and_command_is_argument_array(
    tmp_path: Path,
) -> None:
    hostile = "rtl/name with ; ' quotes [x]\n.v"
    session, raw = _stage(tmp_path, hostile)
    tool = YosysSynthesisTool()
    request = tool.validate_request(raw)
    command = tool.build_command(request, ToolContext(session=session))
    assert not command.requires_shell
    assert command.argv[-4:] == ["-l", "out/yosys.log", "-s", "flow.ys"]
    flow = (session.root / ".verigym_internal/yosys/candidate/flow.ys").read_text()
    assert hostile not in flow
    assert "src/0000.v" in flow
    assert (session.root / ".verigym_internal/yosys/candidate/src/0000.v").is_file()


@pytest.mark.parametrize("bad_source", ["../escape.v", "/host/escape.v"])
def test_source_traversal_is_invalid_before_transport(tmp_path: Path, bad_source: str) -> None:
    session, raw = _stage(tmp_path)
    raw["sources"] = [bad_source]
    result = YosysSynthesisTool().execute(raw, ToolContext(session=session))
    assert result.category == ErrorCategory.INVALID_REQUEST
    assert not session.executed


def test_symlinked_source_and_liberty_are_rejected(tmp_path: Path) -> None:
    session, raw = _stage(tmp_path)
    source = session.root / "rtl/counter.v"
    source.unlink()
    source.symlink_to(session.root / ".verigym_profile/cells.lib")
    result = YosysSynthesisTool().execute(raw, ToolContext(session=session))
    assert result.category == ErrorCategory.INVALID_REQUEST
    assert "regular file" in result.message

    session, raw = _stage(tmp_path / "liberty")
    liberty = session.root / ".verigym_profile/cells.lib"
    payload = liberty.read_bytes()
    liberty.unlink()
    target = session.root / "outside.lib"
    target.write_bytes(payload)
    liberty.symlink_to(target)
    result = YosysSynthesisTool().execute(raw, ToolContext(session=session))
    assert result.category == ErrorCategory.INVALID_REQUEST
    assert "regular file" in result.message


def test_hard_linked_source_is_rejected_before_yosys(tmp_path: Path) -> None:
    session, raw = _stage(tmp_path)
    os.link(session.root / "rtl/counter.v", session.root / "rtl/alias.v")
    result = YosysSynthesisTool().execute(raw, ToolContext(session=session))
    assert result.category == ErrorCategory.INVALID_REQUEST
    assert "hard-link alias" in result.message
    assert not session.executed


def test_liberty_hash_mismatch_is_rejected_before_yosys(tmp_path: Path) -> None:
    session, raw = _stage(tmp_path)
    raw["liberty_sha256"] = "0" * 64
    result = YosysSynthesisTool().execute(raw, ToolContext(session=session))
    assert result.category == ErrorCategory.INVALID_REQUEST
    assert "hash mismatch" in result.message
    assert not session.executed


def test_opensta_command_is_argument_array_and_sdc_is_hash_bound(tmp_path: Path) -> None:
    session, raw = _stage(tmp_path)
    opensta = tmp_path / "sta"
    opensta.write_bytes(b"trusted-opensta-test-executable")
    constraints = b"create_clock -name clk -period 10 [get_ports clk]\n"
    constraints_path = session.root / ".verigym_profile/constraints.sdc"
    constraints_path.write_bytes(constraints)
    raw.update(
        {
            "flow_template_id": "verigym-yosys-opensta-atp-v2",
            "constraints_path": ".verigym_profile/constraints.sdc",
            "constraints_sha256": hash_bytes(constraints),
            "timing_unit": "ns",
            "power_unit": "uW",
            "clock_name": "clk",
            "clock_period": 10.0,
            "wire_load_model": "5K_hvratio_1_1",
            "power_activity_mode": "global_clock_relative",
            "power_activity": 0.1,
            "power_duty": 0.5,
            "opensta_executable": str(opensta),
            "opensta_executable_sha256": hash_bytes(opensta.read_bytes()),
            "expected_opensta_version": "3.1.0",
        }
    )
    tool = YosysSynthesisTool()
    request = tool.validate_request(raw)
    raw["expected_flow_script_hash"] = generated_script_hash(request)
    request = tool.validate_request(raw)
    command = tool.build_command(request, ToolContext(session=session))
    assert command.requires_shell is False
    assert command.argv == [
        str(opensta),
        "-no_init",
        "-no_splash",
        "-exit",
        "flow.tcl",
    ]
    stage = session.root / ".verigym_internal/yosys/candidate"
    assert stage.joinpath("synthesis.ys").is_file()
    assert stage.joinpath("flow.tcl").is_file()
    assert stage.joinpath("profile/constraints.sdc").read_bytes() == constraints
    assert any(path.endswith("/out/units.rpt") for path in command.artifact_globs)
    assert any(path.endswith("/out/activity_annotation.rpt") for path in command.artifact_globs)

    raw["constraints_sha256"] = "0" * 64
    raw["expected_flow_script_hash"] = None
    mismatched_request = tool.validate_request(raw)
    raw["expected_flow_script_hash"] = generated_script_hash(mismatched_request)
    result = tool.execute(raw, ToolContext(session=session))
    assert result.category == ErrorCategory.INVALID_REQUEST
    assert "SDC asset hash mismatch" in result.message


def test_candidate_failure_missing_abc_parser_and_resource_errors_are_distinct(
    tmp_path: Path,
) -> None:
    session, raw = _stage(tmp_path)
    tool = YosysSynthesisTool()
    request = tool.validate_request(raw)
    tool.build_command(request, ToolContext(session=session))
    log = session.root / ".verigym_internal/yosys/candidate/out/yosys.log"
    log.write_text("ERROR: syntax error in candidate source\n", encoding="utf-8")
    candidate = tool.parse_result(
        request,
        CompletedCommand(argv=["yosys"], cwd=".", exit_code=1),
        ToolContext(session=session, artifact_dir=tmp_path / "candidate-artifacts"),
    )
    assert candidate.category == ErrorCategory.COMPILE_FAILED
    assert candidate.metadata["candidate_failure"] is True

    log.write_text("ERROR: Can't find ABC executable\n", encoding="utf-8")
    missing_abc = tool.parse_result(
        request,
        CompletedCommand(argv=["yosys"], cwd=".", exit_code=1),
        ToolContext(session=session),
    )
    assert missing_abc.category == ErrorCategory.TOOL_NOT_FOUND
    assert missing_abc.metadata["candidate_failure"] is False

    stat_path = session.root / ".verigym_internal/yosys/candidate/out/stat.json"
    stat_path.write_bytes(b'{"creator":')
    malformed = tool.parse_result(
        request,
        CompletedCommand(argv=["yosys"], cwd=".", exit_code=0),
        ToolContext(session=session),
    )
    assert malformed.category == ErrorCategory.PARSER_ERROR

    timeout = tool.parse_result(
        request,
        CompletedCommand(
            argv=["yosys"],
            cwd=".",
            exit_code=137,
            timed_out=True,
            failure_origin="candidate_process",
        ),
        ToolContext(session=session),
    )
    assert timeout.category == ErrorCategory.TIMEOUT
    assert timeout.metadata["candidate_failure"] is True

    oom = tool.parse_result(
        request,
        CompletedCommand(
            argv=["yosys"],
            cwd=".",
            exit_code=137,
            oom_killed=True,
            failure_origin="candidate_process",
        ),
        ToolContext(session=session),
    )
    assert oom.category == ErrorCategory.OUT_OF_MEMORY


def test_success_keeps_stat_and_netlist_distinct_and_hashes_artifacts(tmp_path: Path) -> None:
    session, raw = _stage(tmp_path)
    tool = YosysSynthesisTool("yosys.stat")
    request = tool.validate_request(raw)
    tool.build_command(request, ToolContext(session=session))
    out = session.root / ".verigym_internal/yosys/candidate/out"
    out.joinpath("yosys.log").write_text("Warning: bounded example\n", encoding="utf-8")
    out.joinpath("stat.json").write_bytes(
        Path("tests/fixtures/yosys/stat_format_compatible_067.json").read_bytes()
    )
    out.joinpath("netlist.json").write_text('{"modules": {}}\n', encoding="utf-8")
    out.joinpath("netlist.v").write_text("module counter; endmodule\n", encoding="utf-8")
    result = tool.parse_result(
        request,
        CompletedCommand(argv=["yosys"], cwd=".", exit_code=0),
        ToolContext(session=session, artifact_dir=tmp_path / "artifacts"),
    )
    assert result.success
    metrics = result.metadata["synthesis"]
    assert metrics["mapped_area_raw"] == 87.0
    roles = {artifact["role"] for artifact in metrics["artifacts"]}
    assert "statistics" in roles
    assert "netlist_json" in roles
    assert (tmp_path / "artifacts/stat.json").is_file()
    assert (tmp_path / "artifacts/netlist.json").is_file()
