from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError, InteractionMode, SuiteSourceConfig

from verigym_rtl_repo import (
    AGENT_EVAL_V2_SUITE_VERSION,
    AGENT_EVAL_V3_COMPLETION_CONTRACT,
    AGENT_EVAL_V3_SUITE_VERSION,
    RtlRepoSuite,
)
from verigym_rtl_repo.dataset import (
    AGENT_EVAL_V2_VARIANT,
    AGENT_EVAL_V3_VARIANT,
    AGENT_EVAL_VARIANT,
    CONTEXT_CLASSIFICATION_RULE,
    VARIANT,
    build_official_prompt,
    classify_context_path,
)


def configured(source: Path) -> RtlRepoSuite:
    return RtlRepoSuite().with_source(SuiteSourceConfig(source_root=source, variant=VARIANT))


def configured_agent_eval(source: Path) -> RtlRepoSuite:
    return RtlRepoSuite().with_source(
        SuiteSourceConfig(source_root=source, variant=AGENT_EVAL_VARIANT)
    )


def configured_agent_eval_v2(source: Path) -> RtlRepoSuite:
    return RtlRepoSuite().with_source(
        SuiteSourceConfig(source_root=source, variant=AGENT_EVAL_V2_VARIANT)
    )


def configured_agent_eval_v3(source: Path) -> RtlRepoSuite:
    return RtlRepoSuite().with_source(
        SuiteSourceConfig(source_root=source, variant=AGENT_EVAL_V3_VARIANT)
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


def test_agent_eval_v2_has_independent_identity_and_preserves_official_context(
    synthetic_source: Path,
) -> None:
    v1 = configured_agent_eval(synthetic_source)
    v2 = configured_agent_eval_v2(synthetic_source)
    v1_ref = next(ref for ref in v1.discover() if ref.native_id == "test-000000")
    v2_ref = next(ref for ref in v2.discover() if ref.native_id == "test-000000")
    v1_task = v1.load_task(v1_ref)
    v2_task = v2.load_task(v2_ref)
    v1_assets = v1.resolve_assets(v1_task)
    v2_assets = v2.resolve_assets(v2_task)
    v1_root = Path(v1_assets.visible_root) / "repository"
    v2_root = Path(v2_assets.visible_root) / "repository"
    v1_index = json.loads((v1_root / "context" / "index.json").read_text(encoding="utf-8"))
    v2_index = json.loads((v2_root / "context" / "index.json").read_text(encoding="utf-8"))
    v1_snapshot = v1.source_snapshot()
    v2_snapshot = v2.source_snapshot()

    assert v2_task.id.startswith(f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/")
    assert v2_task.suite_version == AGENT_EVAL_V2_SUITE_VERSION
    assert v2_task.source.revision == AGENT_EVAL_V2_SUITE_VERSION
    assert v2_task.source.content_hash != v1_task.source.content_hash
    assert v2_task.metadata["task_content_hash"] != v1_task.metadata["task_content_hash"]
    assert v1_snapshot is not None and v2_snapshot is not None
    assert v2_snapshot.configuration_fingerprint != v1_snapshot.configuration_fingerprint
    assert v2_task.description.startswith("Complete exactly the next line")
    assert "First read the tail" in v2_task.description
    assert "source-priority context" in v2_task.description
    assert "exact match" in v2_task.description
    assert v2_task.workspace.editable_globs == ["repository/completion.txt"]
    assert v1_index["items"] == [{"file": "0000.txt", "path": "rtl/helper.v"}]
    assert v2_index["context_classification_rule"] == CONTEXT_CLASSIFICATION_RULE
    assert v2_index["read_priority_order"] == ["source", "generated"]
    assert v2_index["source_utf8_bytes"] == len((v2_root / "context" / "0000.txt").read_bytes())
    assert v2_index["generated_utf8_bytes"] == 0
    assert v2_index["items"] == [
        {
            "classification": "source",
            "file": "0000.txt",
            "path": "rtl/helper.v",
            "read_priority": 0,
            "utf8_bytes": len((v2_root / "context" / "0000.txt").read_bytes()),
        }
    ]
    assert (v2_root / "context" / "0000.txt").read_bytes() == (
        v1_root / "context" / "0000.txt"
    ).read_bytes()
    assert (v2_root / "target" / "cropped_target.sv").read_bytes() == (
        v1_root / "target" / "cropped_target.sv"
    ).read_bytes()
    assert v2_assets.hidden_assets[0].content == v1_assets.hidden_assets[0].content
    visible = b"\n".join(path.read_bytes() for path in v2_root.rglob("*") if path.is_file())
    assert b"assign y = a & b;" not in visible


def test_agent_eval_v3_freezes_immediate_physical_line_contract_without_changing_v2(
    synthetic_source: Path,
) -> None:
    v2 = configured_agent_eval_v2(synthetic_source)
    v3 = configured_agent_eval_v3(synthetic_source)
    v2_ref = next(ref for ref in v2.discover() if ref.native_id == "test-000000")
    v3_ref = next(ref for ref in v3.discover() if ref.native_id == "test-000000")
    v2_task = v2.load_task(v2_ref)
    v3_task = v3.load_task(v3_ref)
    v2_assets = v2.resolve_assets(v2_task)
    v3_assets = v3.resolve_assets(v3_task)
    v2_root = Path(v2_assets.visible_root) / "repository"
    v3_root = Path(v3_assets.visible_root) / "repository"
    v2_index = json.loads((v2_root / "context" / "index.json").read_text(encoding="utf-8"))
    v3_index = json.loads((v3_root / "context" / "index.json").read_text(encoding="utf-8"))
    v2_snapshot = v2.source_snapshot()
    v3_snapshot = v3.source_snapshot()

    assert v3_task.id.startswith(f"rtl-repo/{AGENT_EVAL_V3_VARIANT}/")
    assert v3_task.suite_version == AGENT_EVAL_V3_SUITE_VERSION
    assert v3_task.source.revision == AGENT_EVAL_V3_SUITE_VERSION
    assert v3_task.source.content_hash != v2_task.source.content_hash
    assert v3_task.metadata["task_content_hash"] != v2_task.metadata["task_content_hash"]
    assert v3_task.metadata["projection_version"] == "v3"
    assert v3_task.metadata["completion_contract"] == AGENT_EVAL_V3_COMPLETION_CONTRACT
    assert v2_snapshot is not None and v3_snapshot is not None
    assert v3_snapshot.configuration_fingerprint != v2_snapshot.configuration_fingerprint
    assert "immediate next physical source-code line" in v3_task.description
    assert "Do not concatenate, flatten" in v3_task.description
    assert "one newline-terminated line" in v3_task.description
    assert v3_task.workspace.editable_globs == ["repository/completion.txt"]
    assert "completion_contract" not in v2_index
    assert v3_index["completion_contract"] == AGENT_EVAL_V3_COMPLETION_CONTRACT
    assert v3_index["items"] == v2_index["items"]
    assert (v3_root / "context" / "0000.txt").read_bytes() == (
        v2_root / "context" / "0000.txt"
    ).read_bytes()
    assert (v3_root / "target" / "cropped_target.sv").read_bytes() == (
        v2_root / "target" / "cropped_target.sv"
    ).read_bytes()
    assert v3_assets.hidden_assets[0].content == v2_assets.hidden_assets[0].content
    visible = b"\n".join(path.read_bytes() for path in v3_root.rglob("*") if path.is_file())
    assert b"assign y = a & b;" not in visible


@pytest.mark.parametrize(
    ("path", "classification"),
    [
        ("rtl/source.v", "source"),
        ("HW2.srcs/sim_1/new/tb_uart_rx.v", "source"),
        ("HW2.sim/sim_1/behav/xsim/glbl.v", "generated"),
        ("build/impl/func/result.v", "generated"),
        ("build/synth/func/result.v", "generated"),
        ("build/XSIM/result.v", "generated"),
        ("rtl/GLBL.sv", "generated"),
    ],
)
def test_agent_eval_v2_context_classification_is_path_only_and_stable(
    path: str,
    classification: str,
) -> None:
    assert classify_context_path(path) == classification


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
