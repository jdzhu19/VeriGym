from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError, InteractionMode, SuiteSourceConfig

from verigym_rtl_repo import RtlRepoSuite
from verigym_rtl_repo.dataset import AGENT_EVAL_VARIANT, VARIANT, build_official_prompt


def configured(source: Path) -> RtlRepoSuite:
    return RtlRepoSuite().with_source(SuiteSourceConfig(source_root=source, variant=VARIANT))


def configured_agent_eval(source: Path) -> RtlRepoSuite:
    return RtlRepoSuite().with_source(
        SuiteSourceConfig(source_root=source, variant=AGENT_EVAL_VARIANT)
    )


def test_external_source_is_required() -> None:
    assert not RtlRepoSuite().validate_source().valid


def test_discovers_and_normalizes_official_parquet_shape(synthetic_source: Path) -> None:
    suite = configured(synthetic_source)
    report = suite.validate_source()
    refs = list(suite.discover())
    test_ref = next(ref for ref in refs if ref.native_id == "test-000000")
    task = suite.load_task(test_ref)
    snapshot = suite.source_snapshot()

    expected_prompt = build_official_prompt(
        repo_name="verigym/synthetic-rtl",
        file_path="rtl/test_10.v",
        cropped_code="module demo(input a, input b, output y);\n",
        context=[{"path": "rtl/helper.v", "snippet": "module helper;\nendmodule\n"}],
    )
    assert report.valid
    assert len(refs) == 3
    assert task.description == expected_prompt
    assert task.task_type.value == "completion"
    assert task.interaction.supported_modes == [InteractionMode.CHAT, InteractionMode.AGENT]
    assert "agent_eval" in suite.descriptor.capabilities
    assert task.interaction.allowed_tools == []
    assert task.interaction.final_submission.kind == "line"
    assert task.budget.max_output_tokens == 50
    assert "assign y = a & b;" not in task.model_dump_json()
    assert snapshot is not None
    assert snapshot.synthetic_fixture
    assert snapshot.license_id == "Apache-2.0"

    assets = suite.resolve_assets(task)
    assert len(assets.hidden_assets) == 1
    assert assets.hidden_assets[0].content == "assign y = a & b;"


def test_reference_and_known_bad_conformance_are_separate(synthetic_source: Path) -> None:
    suite = configured(synthetic_source)
    cases = list(suite.conformance_cases())

    assert [case.expected_resolved for case in cases] == [True, False]
    assert cases[0].candidate.files["completion.txt"] == "assign y = a & b;"


def test_agent_eval_is_an_official_context_projection_without_target_leaks(
    synthetic_source: Path,
) -> None:
    suite = configured_agent_eval(synthetic_source)
    ref = next(ref for ref in suite.discover() if ref.native_id == "test-000000")
    task = suite.load_task(ref)
    assets = suite.resolve_assets(task)
    visible = Path(assets.visible_root)
    visible_files = {
        path.relative_to(visible).as_posix(): path.read_text(encoding="utf-8")
        for path in visible.rglob("*")
        if path.is_file()
    }

    assert task.id.startswith(f"rtl-repo/{AGENT_EVAL_VARIANT}/")
    assert task.description.startswith("Complete exactly the next line")
    assert task.workspace.editable_globs == ["repository/completion.txt"]
    assert task.metadata["projection_kind"] == "official-context projection"
    assert "repository/context/index.json" in visible_files
    assert "repository/target/cropped_target.sv" in visible_files
    assert "assign y = a & b;" not in "\n".join(visible_files.values())
    assert "all_code" not in "\n".join(visible_files.values())
    assert assets.hidden_assets[0].content == "assign y = a & b;"


def test_source_mutation_is_detected_after_task_freeze(synthetic_source: Path) -> None:
    suite = configured(synthetic_source)
    ref = next(ref for ref in suite.discover() if ref.native_id == "test-000000")
    task = suite.load_task(ref)
    shard = synthetic_source / "data" / "test-demo.parquet"
    shard.write_bytes(shard.read_bytes() + b"changed")

    with pytest.raises(ConfigurationError, match="differs from the frozen source snapshot"):
        suite.resolve_assets(task)


def test_linked_data_directory_is_rejected(synthetic_source: Path, tmp_path: Path) -> None:
    linked_root = tmp_path / "linked-source"
    linked_root.mkdir()
    (linked_root / "data").symlink_to(synthetic_source / "data", target_is_directory=True)

    report = configured(linked_root).validate_source()

    assert not report.valid
    assert "must not be a symlink" in report.errors[0]


def test_plugin_implementation_uses_only_the_stable_verigym_surface() -> None:
    package = Path(__file__).parents[1] / "src" / "verigym_rtl_repo"
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
def test_official_snapshot_first_test_row_smoke() -> None:
    raw_root = os.environ.get("VERIGYM_RTL_REPO_ROOT")
    if not raw_root:
        pytest.skip("set VERIGYM_RTL_REPO_ROOT for official snapshot validation")
    suite = configured(Path(raw_root))
    report = suite.validate_source()
    refs = list(suite.discover())
    test_ref = next(ref for ref in refs if ref.native_id == "test-000000")
    task = suite.load_task(test_ref)

    assert report.valid
    assert len(refs) == 4_098
    assert task.metadata["benchmark_split"] == "test"
    assert task.description.startswith("// Repo Name: ")
    assert suite.resolve_assets(task).hidden_assets[0].content is not None
