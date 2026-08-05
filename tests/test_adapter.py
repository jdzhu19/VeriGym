from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError, SuiteSourceConfig

from verigym_verilog_eval_codecomplete import VerilogEvalCodeCompleteSuite
from verigym_verilog_eval_codecomplete.layout import VARIANT


def configured(source: Path) -> VerilogEvalCodeCompleteSuite:
    return VerilogEvalCodeCompleteSuite().with_source(
        SuiteSourceConfig(source_root=source, variant=VARIANT)
    )


def test_discovers_and_normalizes_external_tasks(synthetic_source: Path) -> None:
    suite = configured(synthetic_source)
    report = suite.validate_source()
    refs = list(suite.discover())
    task = suite.load_task(refs[0])
    snapshot = suite.source_snapshot()

    assert report.valid
    assert [ref.native_id for ref in refs] == ["Demo001_and", "Demo002_or"]
    assert task.task_type.value == "completion"
    assert task.source.license == "MIT"
    assert task.interaction.supported_modes == ["chat", "agent"]
    assert snapshot is not None
    assert snapshot.synthetic_fixture
    assert snapshot.variant == VARIANT
    assert "assign y" not in task.model_dump_json()

    assets = suite.resolve_assets(task)
    assert len(assets.hidden_assets) == 2
    assert all(asset.content for asset in assets.hidden_assets)


def test_reference_and_known_bad_conformance_are_separate(synthetic_source: Path) -> None:
    suite = configured(synthetic_source)
    task = suite.load_task(next(iter(suite.discover())))
    reference = suite.reference_solution(task)
    cases = list(suite.conformance_cases())

    assert reference is not None
    assert "module TopModule" in reference.files["rtl/TopModule.sv"]
    assert [case.expected_resolved for case in cases] == [True, False]


def test_source_mutation_is_detected_after_task_freeze(synthetic_source: Path) -> None:
    suite = configured(synthetic_source)
    task = suite.load_task(next(iter(suite.discover())))
    prompt = synthetic_source / "dataset_code-complete-iccad2023" / "Demo001_and_prompt.txt"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="differs from the frozen task snapshot"):
        suite.resolve_assets(task)


def test_incomplete_and_linked_sources_fail_closed(synthetic_source: Path) -> None:
    dataset = synthetic_source / "dataset_code-complete-iccad2023"
    (dataset / "Demo002_or_ifc.txt").unlink()
    target = dataset / "Demo001_and_prompt.txt"
    (dataset / "linked_prompt.txt").symlink_to(target)

    report = configured(synthetic_source).validate_source()

    assert not report.valid
    assert {issue.code for issue in report.issues} >= {"incomplete_task", "symlink"}


def test_plugin_implementation_uses_only_the_stable_verigym_surface() -> None:
    package = Path(__file__).parents[1] / "src" / "verigym_verilog_eval_codecomplete"
    imported_verigym_modules: set[str] = set()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("verigym")
            ):
                imported_verigym_modules.add(node.module)
            if isinstance(node, ast.Import):
                imported_verigym_modules.update(
                    alias.name for alias in node.names if alias.name.startswith("verigym")
                )
    assert imported_verigym_modules == {"verigym.plugin_api"}


@pytest.mark.external_benchmark
def test_official_checkout_contract() -> None:
    raw_root = os.environ.get("VERIGYM_VERILOG_EVAL_CODE_COMPLETE_ROOT")
    if not raw_root:
        pytest.skip("set VERIGYM_VERILOG_EVAL_CODE_COMPLETE_ROOT for official checkout validation")
    suite = configured(Path(raw_root))
    report = suite.validate_source()
    refs = list(suite.discover())
    snapshot = suite.source_snapshot()

    assert report.valid
    assert len(refs) >= 150
    assert refs[0].native_id == "Prob001_zero"
    assert snapshot is not None
    assert snapshot.license_id == "MIT"
    assert snapshot.git_metadata_available
