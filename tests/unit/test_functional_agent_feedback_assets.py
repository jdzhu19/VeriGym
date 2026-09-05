from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.agent_feedback_assets import (
    compile_feedback_contract,
    compile_smoke_feedback_contract,
    materialize_agent_eval_workspace,
)

_SMOKE = """module public_smoke;
  wire y;
  TopModule dut(.y(y));
  initial begin
    if (y !== 1'b1) $fatal(1, "bad output");
    $finish;
  end
endmodule
"""


def test_functional_contract_is_distinct_and_materializes_only_public_assets() -> None:
    compile_only = compile_feedback_contract(
        source_paths=["rtl/TopModule.sv"], top_module="TopModule", language="2012"
    )
    functional = compile_smoke_feedback_contract(
        source_paths=["rtl/TopModule.sv"],
        top_module="TopModule",
        language="2012",
        public_testbench=_SMOKE,
    )
    assert functional["public_assets_hash"] != compile_only["public_assets_hash"]
    tests = functional["tests"]
    assert isinstance(tests, list)
    assert [command["argv"][0] for command in tests[0]["commands"]] == ["iverilog", "vvp"]

    workspace = materialize_agent_eval_workspace(
        task_description="Implement TopModule.",
        repository_files={"rtl/TopModule.sv": "module TopModule; endmodule\n"},
        compile_contract=functional,
        ppa_available=False,
        public_asset_files={"assets/public-smoke.sv": _SMOKE},
    )
    root = Path(workspace.temporary.name)
    assert workspace.read_only_mount is not None
    contract = json.loads((root / "public" / "test-contract.json").read_text())
    assert contract == functional
    assert (root / "public" / "assets" / "public-smoke.sv").read_text() == _SMOKE
    visible = "\n".join(
        path.relative_to(workspace.visible_root).as_posix()
        for path in workspace.visible_root.rglob("*")
        if path.is_file()
    )
    assert "public-smoke" not in visible
    assert "hidden" not in visible


def test_verilator_compile_contract_is_fixed_and_distinct_from_icarus() -> None:
    icarus = compile_feedback_contract(
        source_paths=["rtl/TopModule.sv"], top_module="TopModule", language="2012"
    )
    verilator = compile_feedback_contract(
        source_paths=["rtl/TopModule.sv"],
        top_module="TopModule",
        language="2012",
        backend="verilator",
    )
    commands = verilator["tests"]
    assert isinstance(commands, list)
    assert commands[0]["commands"][0]["argv"] == [
        "verilator",
        "--lint-only",
        "--timing",
        "-Wno-fatal",
        "-Wno-BLKANDNBLK",
        "--bbox-unsup",
        "--language",
        "1800-2012",
        "--top-module",
        "TopModule",
        "{repository}/rtl/TopModule.sv",
    ]
    assert verilator != icarus


def test_compile_contract_rejects_an_unknown_backend() -> None:
    with pytest.raises(ValueError, match="unsupported open-tool backend"):
        compile_feedback_contract(
            source_paths=["rtl/TopModule.sv"],
            top_module="TopModule",
            language="2012",
            backend="unknown",  # type: ignore[arg-type]
        )
