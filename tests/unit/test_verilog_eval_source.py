from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.milestone9_helpers import experiment_config, offline_service
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.public_test_profiles import validate_required_public_test_profile
from verigym.experiments.planner import ExperimentPlanner
from verigym.registry.collections import build_registries
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.suites.verilog_eval.adapter import VerilogEvalSuite
from verigym.suites.verilog_eval.commercial import (
    VCS_MCP_EXCLUSIONS,
    combined_reference_testbench,
)
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


def test_verilator_agent_eval_variant_is_compile_only_and_hidden_isolated() -> None:
    variant = "v2-spec-to-rtl-agent-eval-verilator-v1"
    suite = adapter(variant=variant)
    reference = list(suite.discover())[0]
    task = suite.load_task(reference)
    assets = suite.resolve_assets(task)

    assert task.id == f"verilog-eval/{variant}/Prob900_fixture_and"
    assert task.suite_version == variant
    assert task.metadata["public_feedback_semantics"] == "compile_only_verilator_lint_v1"
    assert task.metadata["public_feedback_partition"] == (
        "verilog_eval_v2_public_verilator_compile_lint_v1"
    )
    assert task.metadata["public_feedback_backend"] == "verilator"
    assert task.metadata["diagnostic_only"] is True
    assert task.metadata["benchmark_score_claimed"] is False
    assert task.scoring.ppa_enabled is False
    assert [node.plugin for node in task.verifier.nodes] == [
        "verilog_eval.v2.compile",
        "verilog_eval.v2.regression",
    ]
    assert assets.read_only_mounts
    contract = json.loads(
        (Path(assets.read_only_mounts[0].source_dir) / "test-contract.json").read_text()
    )
    command = contract["tests"][0]["commands"][0]["argv"]
    assert command[:3] == ["verilator", "--lint-only", "--timing"]
    assert command[3:6] == ["-Wno-fatal", "-Wno-BLKANDNBLK", "--bbox-unsup"]
    assert "verifier" not in json.dumps(contract)

    runtime = SimpleNamespace(
        descriptor=SimpleNamespace(
            image=SimpleNamespace(
                iverilog_version="Icarus Verilog version 12.0",
                vvp_version="Icarus Verilog runtime version 12.0",
                verilator_version="Verilator 5.052 2026-08-30 rev v5.052",
                compatibility_status="canonical_or_reference_compatible",
                requested_reference="qualified-image",
                resolved_image_id="sha256:" + "1" * 64,
            ),
            name="docker",
        )
    )
    profile = suite.toolchain_profile(runtime, SimpleNamespace())
    assert profile is not None
    assert profile.id == "verilog-eval-v2-agent-eval-verilator-lint-icarus12-v1"
    assert [tool.name for tool in profile.tools] == ["iverilog", "vvp", "verilator"]


def test_vcs_mcp_agent_eval_variant_is_isolated_and_keeps_old_task_identities() -> None:
    commercial = adapter(variant="v2-spec-to-rtl-agent-eval-vcs-mcp-v1")
    references = list(commercial.discover())
    assert len(references) == 2

    task = commercial.load_task(references[0])
    assets = commercial.resolve_assets(task)
    visible = Path(assets.visible_root)
    node = task.verifier.nodes[0]

    assert task.id == ("verilog-eval/v2-spec-to-rtl-agent-eval-vcs-mcp-v1/Prob900_fixture_and")
    assert task.suite_version == "v2-spec-to-rtl-agent-eval-vcs-mcp-v1"
    assert task.interaction.supported_modes == ["agent"]
    assert "file.apply_codex_patch" in task.interaction.allowed_tools
    assert task.workspace.entrypoints == ["repository/rtl/TopModule.sv"]
    assert task.scoring.correctness_required_nodes == ["vcs_regression"]
    assert task.scoring.ppa_enabled is False
    assert node.id == "vcs_regression"
    assert node.plugin == "synopsys.vcs.simulate"
    assert node.visibility.value == "verifier_only"
    assert node.request == {
        "sources": ["repository/rtl/TopModule.sv"],
        "testbench": "verifier/testbench.sv",
        "top": "tb",
        "pass_marker": "Mismatches: 0 in",
        "fail_marker": "VERIGYM_VCS_EXPLICIT_FAIL",
        "executable": "vcs",
        "timeout_s": 180,
    }
    assert task.metadata["required_verifier_profile_target"] == "synopsys.vcs.mcp"
    assert task.metadata["verification_partition"] == "verilog_eval_v2_vcs_mcp_v1"
    assert task.metadata["verification_requires_final_submission"] is True
    assert task.metadata["diagnostic_only"] is True
    assert task.metadata["benchmark_score_claimed"] is False
    assert task.metadata["upstream_tool_compatible"] is False
    assert task.metadata["public_feedback_semantics"] == "compile_only_v1"
    assert task.metadata["agent_eval"]["ppa_supported"] is False

    assert len(task.workspace.hidden_assets) == 1
    assert task.workspace.hidden_assets[0].content is None
    assert task.workspace.hidden_assets[0].mount_path == "verifier/testbench.sv"
    assert len(assets.hidden_assets) == 1
    hidden = assets.hidden_assets[0]
    assert hidden.content is not None
    assert "module RefModule" in hidden.content
    assert "module tb" in hidden.content
    assert hidden.content_hash == task.workspace.hidden_assets[0].content_hash
    visible_text = "\n".join(
        path.read_text(encoding="utf-8") for path in visible.rglob("*") if path.is_file()
    )
    assert "module RefModule" not in visible_text
    assert "module tb" not in visible_text
    assert "module RefModule" not in task.model_dump_json()

    reference = commercial.reference_solution(task)
    assert reference is not None
    assert set(reference.files) == {"repository/rtl/TopModule.sv"}
    assert "module TopModule" in reference.files["repository/rtl/TopModule.sv"]

    base_task = adapter().load_task(list(adapter().discover())[0])
    agent_suite = adapter(variant="v2-spec-to-rtl-agent-eval-v1")
    agent_task = agent_suite.load_task(list(agent_suite.discover())[0])
    assert content_hash(base_task) == (
        "6544e7d5ad244cd5caeacacf6559a2a596c4657ebc2f876febd8f673d4f0f0f7"
    )
    assert content_hash(agent_task) == (
        "c6af36b522e08b55694938c514fd3aa7b12e5ea408a768525a8e41675f786398"
    )


def test_vcs_mcp_public_variant_freezes_two_separate_commercial_interfaces() -> None:
    suite = adapter(variant="v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1")
    references = list(suite.discover())
    assert len(references) == 2

    task = suite.load_task(references[0])
    assert task.id == (
        "verilog-eval/v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1/Prob900_fixture_and"
    )
    assert task.suite_version == "v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1"
    assert task.metadata["required_verifier_profile_target"] == "synopsys.vcs.mcp"
    assert task.metadata["required_public_test_profile_target"] == (
        "synopsys.vcs.public-compile.mcp"
    )
    assert task.metadata["public_test_profile_source_plugin"] == "repository.public_test"
    assert task.metadata["public_test_profile_test_id"] == "compile"
    assert task.metadata["public_test_profile_sources"] == ["repository/rtl/TopModule.sv"]
    assert task.metadata["public_test_profile_top"] == "TopModule"
    assert task.metadata["public_feedback_semantics"] == "compile_only_vcs_mcp_v1"
    assert task.metadata["public_feedback_partition"] == (
        "verilog_eval_v2_public_vcs_mcp_compile_v1"
    )
    assert task.metadata["verification_partition"] == ("verilog_eval_v2_vcs_mcp_public_v1")
    assert task.verifier.nodes[0].plugin == "synopsys.vcs.simulate"
    with pytest.raises(ConfigurationError, match="requires a public-test profile"):
        validate_required_public_test_profile(task, None)

    profile = suite.toolchain_profile(
        SimpleNamespace(descriptor=SimpleNamespace(image=None, name="local")),
        SimpleNamespace(),
    )
    assert profile is not None
    assert profile.id == "verilog-eval-v2-agent-eval-public-vcs-mcp-v1"
    assert profile.tools == []
    assert profile.reproducibility_scope == "site_specific"


def test_vcs_mcp_agent_eval_fails_before_run_without_required_profile(tmp_path: Path) -> None:
    service = VeriGym(build_registries(discover_external=False))
    source = SuiteSourceConfig(
        source_root=FIXTURE,
        variant="v2-spec-to-rtl-agent-eval-vcs-mcp-v1",
        strict_compatibility=True,
    )
    output = tmp_path / "runs"

    with pytest.raises(ConfigurationError, match="requires a verifier profile targeting"):
        service.run(
            RunConfig(
                task_id=("verilog-eval/v2-spec-to-rtl-agent-eval-vcs-mcp-v1/Prob900_fixture_and"),
                suite_source=source,
                output=output,
            )
        )

    assert not output.exists()


def test_vcs_mcp_experiment_fails_before_direct_vcs_health_lookup(tmp_path: Path) -> None:
    base = experiment_config(
        tmp_path / "experiment",
        tasks=["Prob900_fixture_and"],
        systems=[{"id": "scripted", "agent": {"id": "scripted"}}],
        seeds=[0],
    )
    payload = base.model_dump(mode="python")
    payload["suite"] = {
        "id": "verilog-eval",
        "source": FIXTURE,
        "variant": "v2-spec-to-rtl-agent-eval-vcs-mcp-v1",
        "strict_compatibility": True,
        "tasks": {"include": ["Prob900_fixture_and"], "exclude": []},
    }
    config = type(base).model_validate(payload)

    with pytest.raises(ConfigurationError, match="requires a verifier profile targeting"):
        ExperimentPlanner(offline_service()).build(config)


def test_vcs_combined_hidden_asset_copies_only_the_official_timescale_prelude() -> None:
    reference = "module RefModule; endmodule\n"
    testbench = "`timescale 1ns / 1ps\nmodule tb; endmodule\n"
    combined = combined_reference_testbench(reference, testbench)

    assert combined == f"`timescale 1ns / 1ps\n{reference}{testbench}"
    assert combined_reference_testbench(f"`timescale 1ps/1ps\n{reference}", testbench) == (
        f"`timescale 1ps/1ps\n{reference}{testbench}"
    )
    assert VCS_MCP_EXCLUSIONS == {"Prob099_m2014_q6c": "reference_testbench_port_contract_mismatch"}


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
