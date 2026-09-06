from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from verigym.public_test_launcher_v2 import execute_public_test
from verigym.schemas.suite import SuiteSourceConfig
from verigym.suites.verilog_eval.adapter import VerilogEvalSuite

try:
    from verigym_rtllm.adapter import VERILATOR_AGENT_EVAL_VARIANT, RTLLMSuite
except ImportError:  # pragma: no cover - the optional plugin is absent in core-only installs
    RTLLMSuite = None  # type: ignore[assignment,misc]
    VERILATOR_AGENT_EVAL_VARIANT = "v2-agent-eval-verilator-public-v1"


def _run_public_compile(suite: object, task: object, source: str) -> bool:
    assets = suite.resolve_assets(task)  # type: ignore[attr-defined]
    assert assets.read_only_mounts
    candidate_path = task.workspace.entrypoints[0]  # type: ignore[attr-defined]
    candidate = Path(assets.visible_root) / candidate_path
    candidate.write_text(source, encoding="utf-8")
    exit_code, payload, _limit = execute_public_test(
        "compile",
        public_root=Path(assets.read_only_mounts[0].source_dir),
        workspace_root=Path(assets.visible_root),
    )
    assert payload["commands"][0]["executable"] == "verilator"
    return exit_code == 0 and payload["passed"] is True


@pytest.mark.external_benchmark
@pytest.mark.skipif(
    not os.environ.get("VERIGYM_VERILOG_EVAL_SOURCE") or shutil.which("verilator") is None,
    reason="set VERIGYM_VERILOG_EVAL_SOURCE and install Verilator for qualification",
)
def test_all_verilog_eval_references_pass_and_syntax_mutants_fail_public_verilator() -> None:
    suite = VerilogEvalSuite(
        SuiteSourceConfig(
            source_root=Path(os.environ["VERIGYM_VERILOG_EVAL_SOURCE"]),
            variant="v2-spec-to-rtl-agent-eval-verilator-v1",
            strict_compatibility=True,
        )
    )
    refs = list(suite.discover())
    assert refs
    for ref in refs:
        task = suite.load_task(ref)
        reference = suite.reference_solution(task)
        assert reference is not None
        source = reference.files[task.workspace.entrypoints[0]]
        assert _run_public_compile(suite, task, source)
        assert not _run_public_compile(suite, task, "module TopModule( endmodule\n")


@pytest.mark.external_benchmark
@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE")
    or shutil.which("verilator") is None
    or RTLLMSuite is None,
    reason="set VERIGYM_RTLLM_SOURCE and install RTLLM plus Verilator for qualification",
)
def test_all_rtllm_references_pass_and_missing_modules_fail_public_verilator() -> None:
    assert RTLLMSuite is not None
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(
            source_root=Path(os.environ["VERIGYM_RTLLM_SOURCE"]),
            variant=VERILATOR_AGENT_EVAL_VARIANT,
            strict_compatibility=True,
        )
    )
    refs = list(suite.discover())
    assert len(refs) == 50
    for ref in refs:
        task = suite.load_task(ref)
        reference = suite.reference_solution(task)
        assert reference is not None
        source = reference.files[task.workspace.entrypoints[0]]
        assert _run_public_compile(suite, task, source)
        manifest = suite._manifest_for_task(task)
        assert not _run_public_compile(suite, task, suite._candidate_stub(manifest))
