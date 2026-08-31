from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import hash_directory
from verigym.registry.collections import build_registries
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.suites.verilog_eval.adapter import VerilogEvalSuite
from verigym.suites.verilog_eval.layout import MAX_TRIPLET_FILE_BYTES, natural_sort_key
from verigym.suites.verilog_eval.normalization import transform_reference_candidate

FIXTURE = Path(__file__).parents[1] / "fixtures" / "verilog_eval_v2_synthetic"
VARIANT = "v2-spec-to-rtl"


def adapter(root: Path = FIXTURE, *, variant: str | None = VARIANT) -> VerilogEvalSuite:
    return VerilogEvalSuite(
        SuiteSourceConfig(source_root=root, variant=variant, strict_compatibility=True)
    )


def copied_fixture(tmp_path: Path) -> Path:
    destination = tmp_path / "external-verilog-eval"
    shutil.copytree(FIXTURE, destination)
    return destination


def test_builtin_suite_and_repository_or_direct_dataset_discovery_are_stable() -> None:
    registries = build_registries(discover_external=False)
    assert "verilog-eval" in dict(registries.suites.items())

    repository = adapter()
    direct = adapter(FIXTURE / "dataset_spec-to-rtl", variant=None)
    expected = [
        "verilog-eval/v2-spec-to-rtl/Prob900_fixture_and",
        "verilog-eval/v2-spec-to-rtl/Prob901_fixture_counter",
    ]
    assert [reference.id for reference in repository.discover()] == expected
    assert [reference.id for reference in direct.discover()] == expected
    assert repository.source_snapshot() is not None
    assert direct.source_snapshot() is not None
    assert repository.source_snapshot().dataset_content_hash == (
        direct.source_snapshot().dataset_content_hash
    )


def test_natural_order_and_hashes_are_deterministic() -> None:
    values = ["Prob10_x", "Prob2_x", "Prob001_x", "Prob1_x"]
    assert sorted(values, key=natural_sort_key) == [
        "Prob001_x",
        "Prob1_x",
        "Prob2_x",
        "Prob10_x",
    ]
    first = adapter()
    second = adapter()
    first_tasks = [first.load_task(reference) for reference in first.discover()]
    second_tasks = [second.load_task(reference) for reference in second.discover()]
    assert [task.source.content_hash for task in first_tasks] == [
        task.source.content_hash for task in second_tasks
    ]
    assert first.source_snapshot().dataset_content_hash == (
        second.source_snapshot().dataset_content_hash
    )


def test_fixture_provenance_round_trips_and_is_explicitly_synthetic() -> None:
    snapshot = adapter().source_snapshot()
    assert snapshot is not None
    assert snapshot.license_id == "MIT"
    assert snapshot.license_file_hash
    assert snapshot.git_metadata_available is False
    assert snapshot.synthetic_fixture is True
    assert SuiteSourceSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_validation_is_read_only() -> None:
    before = hash_directory(FIXTURE)
    report = adapter().validate_source()
    assert report.valid, report.errors
    assert hash_directory(FIXTURE) == before


def test_missing_dataset_and_legacy_v1_have_actionable_diagnostics(tmp_path: Path) -> None:
    missing = tmp_path / "missing-dataset"
    missing.mkdir()
    report = adapter(missing).validate_source()
    assert not report.valid
    assert "missing required directory" in report.errors[0]

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "problems.jsonl").write_text("{}\n", encoding="utf-8")
    report = adapter(legacy, variant=None).validate_source()
    assert not report.valid
    assert "legacy VerilogEval V1" in report.errors[0]


def test_ambiguous_and_unsupported_variants_fail_structurally(tmp_path: Path) -> None:
    root = copied_fixture(tmp_path)
    (root / "dataset_code-complete-iccad2023").mkdir()
    report = adapter(root, variant=None).validate_source()
    assert not report.valid
    assert "ambiguous" in report.errors[0]

    report = adapter(root, variant="v2-code-complete-iccad2023").validate_source()
    assert not report.valid
    assert "unsupported VerilogEval variant" in report.errors[0]


def test_incomplete_case_colliding_empty_and_non_utf8_triplets_are_rejected(
    tmp_path: Path,
) -> None:
    incomplete_root = copied_fixture(tmp_path / "incomplete")
    (incomplete_root / "dataset_spec-to-rtl" / "Prob900_fixture_and_test.sv").unlink()
    report = adapter(incomplete_root).validate_source()
    assert not report.valid
    assert any(issue.code == "incomplete_triplet" for issue in report.issues)

    collision_root = copied_fixture(tmp_path / "collision")
    dataset = collision_root / "dataset_spec-to-rtl"
    for suffix in ("_prompt.txt", "_ref.sv", "_test.sv"):
        shutil.copyfile(
            dataset / f"Prob900_fixture_and{suffix}",
            dataset / f"prob900_fixture_and{suffix}",
        )
    report = adapter(collision_root).validate_source()
    assert not report.valid
    assert any(issue.code == "case_collision" for issue in report.issues)

    empty_root = copied_fixture(tmp_path / "empty")
    (empty_root / "dataset_spec-to-rtl" / "Prob900_fixture_and_prompt.txt").write_text(
        " \n", encoding="utf-8"
    )
    report = adapter(empty_root).validate_source()
    assert any(issue.code == "empty_prompt" for issue in report.issues)

    binary_root = copied_fixture(tmp_path / "binary")
    (binary_root / "dataset_spec-to-rtl" / "Prob900_fixture_and_prompt.txt").write_bytes(
        b"TopModule \xff"
    )
    report = adapter(binary_root).validate_source()
    assert any(issue.code == "non_utf8_prompt" for issue in report.issues)


def test_oversized_and_symlink_escape_files_are_rejected(tmp_path: Path) -> None:
    oversized_root = copied_fixture(tmp_path / "oversized")
    prompt = oversized_root / "dataset_spec-to-rtl" / "Prob900_fixture_and_prompt.txt"
    with prompt.open("wb") as stream:
        stream.truncate(MAX_TRIPLET_FILE_BYTES + 1)
    report = adapter(oversized_root).validate_source()
    assert any(issue.code == "oversized_file" for issue in report.issues)

    symlink_root = copied_fixture(tmp_path / "symlink")
    prompt = symlink_root / "dataset_spec-to-rtl" / "Prob900_fixture_and_prompt.txt"
    prompt.unlink()
    outside = tmp_path / "outside-prompt.txt"
    outside.write_text("TopModule secret", encoding="utf-8")
    prompt.symlink_to(outside)
    report = adapter(symlink_root).validate_source()
    assert not report.valid
    assert any(issue.code == "symlink_escape" for issue in report.issues)


def test_normalized_task_exposes_only_public_assets_and_logical_provenance() -> None:
    suite = adapter()
    reference = list(suite.discover())[0]
    task = suite.load_task(reference)
    assets = suite.resolve_assets(task)
    prompt = (FIXTURE / "dataset_spec-to-rtl" / "Prob900_fixture_and_prompt.txt").read_text(
        encoding="utf-8"
    )
    assert task.id == "verilog-eval/v2-spec-to-rtl/Prob900_fixture_and"
    assert task.description == prompt
    assert task.task_type.value == "generation"
    assert task.metadata["benchmark_variant"] == VARIANT
    assert task.metadata["native_task_id"] == "Prob900_fixture_and"
    assert task.workspace.entrypoints == ["rtl/TopModule.sv"]
    assert task.source.uri == "verilog-eval://v2-spec-to-rtl/Prob900_fixture_and"
    assert str(FIXTURE.resolve()) not in task.model_dump_json()

    visible = Path(assets.visible_root)
    assert sorted(
        path.relative_to(visible).as_posix() for path in visible.rglob("*") if path.is_file()
    ) == ["README.md", "rtl/TopModule.sv"]
    assert len(assets.hidden_assets) == 2
    assert all(asset.kind == "inline" and asset.content for asset in assets.hidden_assets)
    assert all(asset.content is None for asset in task.workspace.hidden_assets)
    assert "_ref.sv" not in assets.model_dump_json()
    assert "_test.sv" not in assets.model_dump_json()


def test_agent_eval_variant_materializes_public_compile_without_hidden_assets() -> None:
    suite = adapter(variant="v2-spec-to-rtl-agent-eval-v1")
    reference = list(suite.discover())[0]
    task = suite.load_task(reference)
    assets = suite.resolve_assets(task)
    visible = Path(assets.visible_root)

    assert "/v2-spec-to-rtl-agent-eval-v1/" in task.id
    assert task.interaction.supported_modes == ["agent"]
    assert task.workspace.entrypoints == ["repository/rtl/TopModule.sv"]
    assert task.metadata["agent_eval"]["ppa_supported"] is False
    assert [mount.label for mount in assets.read_only_mounts] == ["public_tests"]
    visible_text = "\n".join(
        path.read_text(encoding="utf-8") for path in visible.rglob("*") if path.is_file()
    )
    assert "module RefModule" not in visible_text
    assert "module tb" not in visible_text


def test_functional_v2_variant_has_independent_identity() -> None:
    from verigym.suites.verilog_eval.schemas import VerilogEvalVariant

    assert VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value == (
        "v2-spec-to-rtl-agent-eval-functional-v2"
    )
    smoke = (
        Path(__file__).parents[2]
        / "src/verigym/suites/verilog_eval/assets/public_smoke_v2"
        / "Prob150_review2015_fsmonehot.sv"
    ).read_text(encoding="utf-8")
    assert "state[8] & ~done_counting" in smoke
    assert "state[9] & ~ack" in smoke
    assert "state_index < 10" in smoke


def test_functional_v3_freezes_serial_recovery_smoke_without_mutating_v2() -> None:
    from verigym.suites.verilog_eval.schemas import VerilogEvalVariant

    v2_name = VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value
    v3_name = VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value
    v2 = adapter(variant=v2_name)
    v3 = adapter(variant=v3_name)

    v2_serial = v2._public_smoke("Prob137_fsm_serial")
    v3_serial = v3._public_smoke("Prob137_fsm_serial")
    assert v2_serial is not None and v3_serial is not None
    assert "resynchronization asserted done" not in v2_serial
    assert "resynchronization asserted done" in v3_serial
    assert "invalid stop accepted" in v3_serial
    assert v3._public_smoke("Prob150_review2015_fsmonehot") == v2._public_smoke(
        "Prob150_review2015_fsmonehot"
    )
    assert v2.source_snapshot().configuration_fingerprint != (
        v3.source_snapshot().configuration_fingerprint
    )


def test_functional_v4_adds_only_frozen_harder_unseen_smokes_and_inherits_v3() -> None:
    from verigym.suites.verilog_eval.schemas import VerilogEvalVariant

    v3 = adapter(variant=VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value)
    v4 = adapter(variant=VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value)
    added = {
        "Prob140_fsm_hdlc",
        "Prob144_conwaylife",
        "Prob153_gshare",
        "Prob155_lemmings4",
    }

    assert v4._functional_smoke_tasks() == v3._functional_smoke_tasks() | added
    assert v4._public_smoke("Prob137_fsm_serial") == v3._public_smoke("Prob137_fsm_serial")
    assert v4._public_smoke("Prob150_review2015_fsmonehot") == v3._public_smoke(
        "Prob150_review2015_fsmonehot"
    )
    for native_id in sorted(added):
        smoke = v4._public_smoke(native_id)
        assert smoke is not None
        assert "PUBLIC_SMOKE_PASS" in smoke
    assert v4.source_snapshot().configuration_fingerprint != (
        v3.source_snapshot().configuration_fingerprint
    )


def test_functional_v5_strengthens_only_lemmings_without_mutating_v4() -> None:
    from verigym.suites.verilog_eval.schemas import VerilogEvalVariant

    v4 = adapter(variant=VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value)
    v5 = adapter(variant=VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value)

    assert v5._functional_smoke_tasks() == v4._functional_smoke_tasks()
    for native_id in ("Prob140_fsm_hdlc", "Prob144_conwaylife", "Prob153_gshare"):
        assert v5._public_smoke(native_id) == v4._public_smoke(native_id)
    v4_lemmings = v4._public_smoke("Prob155_lemmings4")
    v5_lemmings = v5._public_smoke("Prob155_lemmings4")
    assert v4_lemmings is not None and v5_lemmings is not None
    assert v5_lemmings != v4_lemmings
    assert "for (i = 1; i < 20; i = i + 1)" in v5_lemmings
    assert v5.source_snapshot().configuration_fingerprint != (
        v4.source_snapshot().configuration_fingerprint
    )


def test_functional_v6_strengthens_only_gshare_without_mutating_v5() -> None:
    from verigym.suites.verilog_eval.schemas import VerilogEvalVariant

    v5 = adapter(variant=VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value)
    v6 = adapter(variant=VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value)

    assert v6._functional_smoke_tasks() == v5._functional_smoke_tasks()
    for native_id in ("Prob140_fsm_hdlc", "Prob144_conwaylife", "Prob155_lemmings4"):
        assert v6._public_smoke(native_id) == v5._public_smoke(native_id)
    v5_gshare = v5._public_smoke("Prob153_gshare")
    v6_gshare = v6._public_smoke("Prob153_gshare")
    assert v5_gshare is not None and v6_gshare is not None
    assert v6_gshare != v5_gshare
    assert "PHT reset was not weakly not-taken" in v6_gshare
    assert v6.source_snapshot().configuration_fingerprint != (
        v5.source_snapshot().configuration_fingerprint
    )


def test_functional_v7_strengthens_only_lemmings_without_mutating_v6() -> None:
    from verigym.suites.verilog_eval.schemas import VerilogEvalVariant

    v6 = adapter(variant=VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value)
    v7 = adapter(variant=VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value)

    assert v7._functional_smoke_tasks() == v6._functional_smoke_tasks()
    for native_id in ("Prob140_fsm_hdlc", "Prob144_conwaylife", "Prob153_gshare"):
        assert v7._public_smoke(native_id) == v6._public_smoke(native_id)
    v6_lemmings = v6._public_smoke("Prob155_lemmings4")
    v7_lemmings = v7._public_smoke("Prob155_lemmings4")
    assert v6_lemmings is not None and v7_lemmings is not None
    assert v7_lemmings != v6_lemmings
    assert "repeat (39) tick();" in v7_lemmings
    assert v7.source_snapshot().configuration_fingerprint != (
        v6.source_snapshot().configuration_fingerprint
    )


def test_multiple_adapter_roots_coexist_without_global_state(tmp_path: Path) -> None:
    other = copied_fixture(tmp_path)
    prompt = other / "dataset_spec-to-rtl" / "Prob900_fixture_and_prompt.txt"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nExtra public sentence.\n")
    first = adapter()
    second = adapter(other)
    first_task = first.load_task(list(first.discover())[0])
    second_task = second.load_task(list(second.discover())[0])
    assert first_task.source.content_hash != second_task.source.content_hash
    assert "Extra public sentence" not in first_task.description
    assert "Extra public sentence" in second_task.description


def test_source_mutation_after_task_load_is_detected(tmp_path: Path) -> None:
    root = copied_fixture(tmp_path)
    suite = adapter(root)
    task = suite.load_task(list(suite.discover())[0])
    golden = root / "dataset_spec-to-rtl" / "Prob900_fixture_and_ref.sv"
    golden.write_text(golden.read_text(encoding="utf-8") + "\n// mutated\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="differs from the frozen task snapshot"):
        suite.resolve_assets(task)


def test_reference_transform_renames_only_one_declaration_and_fails_ambiguity() -> None:
    source = """// RefModule remains in this comment
module RefModule(input logic a, output logic y);
  localparam string LABEL = "RefModule";
  assign y = a;
endmodule
"""
    transformed = transform_reference_candidate(source)
    assert "module TopModule" in transformed
    assert "// RefModule remains" in transformed
    assert 'LABEL = "RefModule"' in transformed
    with pytest.raises(ConfigurationError, match="exactly one"):
        transform_reference_candidate("module Other; endmodule\n")
    with pytest.raises(ConfigurationError, match="ambiguous"):
        transform_reference_candidate("module RefModule; endmodule\nmodule TopModule; endmodule\n")
