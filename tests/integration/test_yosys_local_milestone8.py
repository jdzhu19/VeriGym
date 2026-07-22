from __future__ import annotations

import os
from pathlib import Path

import pytest

from verigym.core.hashing import hash_bytes
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.common import ErrorCategory
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.synthesis import SynthesisMetrics
from verigym.tools.base import ToolContext
from verigym.tools.yosys.identity import local_abc_health, local_yosys_health
from verigym.tools.yosys.plugin import YosysSynthesisTool

pytestmark = pytest.mark.yosys


def _enabled() -> None:
    if os.environ.get("VERIGYM_RUN_YOSYS_TESTS") != "1":
        pytest.skip("set VERIGYM_RUN_YOSYS_TESTS=1 to run real local-Yosys tests")
    if not local_yosys_health().healthy or not local_abc_health().healthy:
        pytest.skip("local Yosys and its ABC executable are not both usable")


def _source_tree(root: Path, *, source: str) -> tuple[Path, dict[str, object]]:
    rtl = root / "rtl" / "counter.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(source, encoding="utf-8")
    liberty = Path("src/verigym/profiles/builtins/assets/toy_cells.lib").read_bytes()
    profile_asset = root / ".verigym_profile" / "cells.lib"
    profile_asset.parent.mkdir(parents=True)
    profile_asset.write_bytes(liberty)
    return root, {
        "sources": ["rtl/counter.v"],
        "top": "counter",
        "liberty_asset_id": "verigym-toy-cells-v1",
        "liberty_path": ".verigym_profile/cells.lib",
        "liberty_sha256": hash_bytes(liberty),
        "area_unit": "toy_area_unit",
        "require_mapped_area": True,
        "timeout_s": 60,
    }


def _run_once(source_root: Path, request: dict[str, object], artifacts: Path) -> SynthesisMetrics:
    session = LocalRuntime().create_session(
        SessionSpec(source_dir=str(source_root), label="verifier", max_output_bytes=1_000_000)
    )
    try:
        result = YosysSynthesisTool().execute(
            request,
            ToolContext(session=session, artifact_dir=artifacts),
        )
    finally:
        session.close()
    assert result.success, result.model_dump_json(indent=2)
    return SynthesisMetrics.model_validate(result.metadata["synthesis"])


def test_real_local_yosys_health_good_mapping_artifacts_and_determinism(
    tmp_path: Path,
) -> None:
    _enabled()
    source = Path(
        "src/verigym/suites/toy_rtl/assets/counter_basic/candidates/good/rtl/counter.v"
    ).read_text(encoding="utf-8")
    source_root, request = _source_tree(tmp_path / "source", source=source)
    first = _run_once(source_root, request, tmp_path / "first")
    second = _run_once(source_root, request, tmp_path / "second")
    assert first.synthesis_ok and first.mapped_area_raw is not None
    assert first.mapped_area_raw > 0
    assert first.cells_by_type == second.cells_by_type
    assert first.mapped_area_raw == second.mapped_area_raw
    assert first.num_cells == second.num_cells
    assert (tmp_path / "first/stat.json").is_file()
    assert (tmp_path / "first/netlist.json").is_file()
    assert (tmp_path / "first/netlist.v").is_file()
    assert (tmp_path / "first/flow.ys").is_file()


def test_real_local_yosys_candidate_failure_classification(tmp_path: Path) -> None:
    _enabled()
    source_root, request = _source_tree(
        tmp_path / "bad-source",
        source="module counter(input clk) this is not Verilog endmodule\n",
    )
    session = LocalRuntime().create_session(
        SessionSpec(source_dir=str(source_root), label="verifier", max_output_bytes=1_000_000)
    )
    try:
        result = YosysSynthesisTool().execute(request, ToolContext(session=session))
    finally:
        session.close()
    assert not result.success
    assert result.category == ErrorCategory.COMPILE_FAILED
    assert result.metadata["candidate_failure"] is True
