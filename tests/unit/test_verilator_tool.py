from __future__ import annotations

from pathlib import Path

import pytest

from verigym.core.agent_feedback_assets import (
    compile_feedback_contract,
    materialize_agent_eval_workspace,
)
from verigym.public_test_launcher_v2 import execute_public_test
from verigym.runtimes.local import LocalRuntimeSession
from verigym.schemas.common import ErrorCategory
from verigym.schemas.runtime import SessionSpec
from verigym.tools.base import ToolContext
from verigym.tools.verilator import VerilatorCompileTool


def _session(tmp_path: Path, source: str) -> LocalRuntimeSession:
    root = tmp_path / "source"
    root.mkdir(parents=True)
    (root / "TopModule.sv").write_text(source, encoding="utf-8")
    return LocalRuntimeSession(SessionSpec(source_dir=str(root), label="verilator-unit"))


def test_verilator_compile_builds_fixed_lint_only_argv(tmp_path: Path) -> None:
    session = _session(tmp_path, "module TopModule; endmodule\n")
    tool = VerilatorCompileTool()
    request = tool.validate_request(
        {"sources": ["TopModule.sv"], "top": "TopModule", "language": "2012"}
    )
    command = tool.build_command(request, ToolContext(session=session))
    assert command.argv == [
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
        "TopModule.sv",
    ]
    assert not command.requires_shell
    session.close()


@pytest.mark.skipif(
    not VerilatorCompileTool().health_check().healthy,
    reason="Verilator is unavailable on this worker",
)
def test_verilator_compile_accepts_reference_and_rejects_syntax_mutant(tmp_path: Path) -> None:
    good = _session(tmp_path / "good", "module TopModule; endmodule\n")
    try:
        passed = VerilatorCompileTool().execute(
            {"sources": ["TopModule.sv"], "top": "TopModule"},
            ToolContext(session=good),
        )
    finally:
        good.close()
    bad = _session(tmp_path / "bad", "module TopModule( endmodule\n")
    try:
        rejected = VerilatorCompileTool().execute(
            {"sources": ["TopModule.sv"], "top": "TopModule"},
            ToolContext(session=bad),
        )
    finally:
        bad.close()
    assert passed.success
    assert rejected.category == ErrorCategory.COMPILE_FAILED
    assert rejected.diagnostics
    assert all(str(tmp_path) not in item for item in rejected.diagnostics)


@pytest.mark.skipif(
    not VerilatorCompileTool().health_check().healthy,
    reason="Verilator is unavailable on this worker",
)
def test_verilator_public_contract_runs_with_the_trusted_launcher() -> None:
    contract = compile_feedback_contract(
        source_paths=["rtl/TopModule.sv"],
        top_module="TopModule",
        language="2012",
        backend="verilator",
    )
    workspace = materialize_agent_eval_workspace(
        task_description="Implement TopModule.",
        repository_files={"rtl/TopModule.sv": "module TopModule; endmodule\n"},
        compile_contract=contract,
        ppa_available=False,
    )
    root = Path(workspace.temporary.name)
    exit_code, payload, _limit = execute_public_test(
        "compile",
        public_root=root / "public",
        workspace_root=workspace.visible_root,
    )
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["commands"][0]["executable"] == "verilator"


@pytest.mark.skipif(
    not VerilatorCompileTool().health_check().healthy,
    reason="Verilator is unavailable on this worker",
)
def test_local_runtime_selects_the_v2_launcher_for_verilator_contracts() -> None:
    contract = compile_feedback_contract(
        source_paths=["rtl/TopModule.sv"],
        top_module="TopModule",
        language="2012",
        backend="verilator",
    )
    workspace = materialize_agent_eval_workspace(
        task_description="Implement TopModule.",
        repository_files={"rtl/TopModule.sv": "module TopModule; endmodule\n"},
        compile_contract=contract,
        ppa_available=False,
    )
    assert workspace.read_only_mount is not None
    with LocalRuntimeSession(
        SessionSpec(
            source_dir=str(workspace.visible_root),
            label="verilator-public-v2",
            read_only_mounts=[workspace.read_only_mount],
        )
    ) as session:
        result = session.execute_public_test("compile")
    assert result.exit_code == 0
    assert result.runtime_role == "agent"
    assert '"executable": "verilator"' in result.stdout
