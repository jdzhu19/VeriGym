from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from verigym.cli.app import app
from verigym.core.hashing import hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.models.static import StaticModelClient
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[1] / "fixtures" / "verilog_eval_v2_synthetic"
VARIANT = "v2-spec-to-rtl"
TASK_ID = "verilog-eval/Prob900_fixture_and"
HAS_ICARUS = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
requires_icarus = pytest.mark.skipif(not HAS_ICARUS, reason="Icarus Verilog is not installed")

GOOD = """module TopModule(input logic a, input logic b, output logic y);
    assign y = a & b;
endmodule
"""
BAD = GOOD.replace("a & b", "a | b")


def source_config() -> SuiteSourceConfig:
    return SuiteSourceConfig(source_root=FIXTURE, variant=VARIANT)


def service(*models: StaticModelClient) -> VeriGym:
    registries = build_registries(discover_external=False)
    for model in models:
        registries.models.register(model)
    return VeriGym(registries)


def chat_run(tmp_path: Path, name: str, source: str) -> tuple[VeriGym, object]:
    model = StaticModelClient(name=name, responses=[source])
    vg = service(model)
    result = vg.run(
        RunConfig(
            task_id=TASK_ID,
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=name,
            suite_source=source_config(),
            output=tmp_path / name,
        )
    )
    return vg, result


@requires_icarus
def test_reference_candidate_passes_native_regression_and_replays(tmp_path: Path) -> None:
    before = hash_directory(FIXTURE)
    vg = service()
    suite, task, _assets = vg.load_task(TASK_ID, source_config())
    reference = suite.reference_solution(task)
    assert reference is not None
    model = StaticModelClient(
        name="m6-reference-derived",
        responses=[reference.files["rtl/TopModule.sv"]],
    )
    vg.registries.models.register(model)
    result = vg.run(
        RunConfig(
            task_id=TASK_ID,
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=model.descriptor.name,
            suite_source=source_config(),
            output=tmp_path / "reference",
        )
    )
    assert result.scorecard.resolved
    assert result.scorecard.correctness.tests_passed == 4
    assert result.scorecard.correctness.tests_total == 4
    assert result.scorecard.quality.ppa is None
    assert result.scorecard.quality.synthesis is None
    assert result.manifest.suite_source is not None
    assert result.manifest.suite_source.synthetic_fixture is True
    assert result.manifest.generation is not None
    assert result.manifest.generation.temperature == 0
    assert result.manifest.toolchain_profiles[0].id == "verilog-eval-v2-icarus"

    compile_result, run_result = result.scorecard.verifier_results
    assert compile_result.status == VerifierStatus.PASSED
    assert run_result.status == VerifierStatus.PASSED
    assert compile_result.metadata["command_argv"][-1] == "rtl/TopModule.sv"
    assert compile_result.metadata["candidate_last"] is True
    assert compile_result.metadata["tool_version"]
    assert run_result.metadata["tool_version"]
    assert compile_result.metadata["compatibility_status"] in {
        "canonical_or_reference_compatible",
        "unverified_tool_version",
        "incompatible_tool_version",
    }
    profile = json.loads(
        (result.run_dir / "artifacts" / "toolchain_profile.json").read_text(encoding="utf-8")
    )
    assert profile["compatibility_status"] == compile_result.metadata["compatibility_status"]
    assert all(tool["version"] for tool in profile["tools"])
    assert hash_directory(FIXTURE) == before

    replay = replay_run(result.run_dir, verify=True, service=vg)
    assert replay.reverified_resolved is True
    assert hash_directory(FIXTURE) == before


@requires_icarus
@pytest.mark.parametrize(
    ("name", "source", "category"),
    [
        ("m6-wrong", BAD, "test_failed"),
        ("m6-syntax", "module TopModule( endmodule\n", "compile_failed"),
        ("m6-missing-top", "module Other; endmodule\n", "compile_failed"),
        (
            "m6-early-finish",
            "module TopModule(input logic a,b,output logic y); "
            "assign y=a&b; initial $finish; endmodule\n",
            "test_failed",
        ),
        (
            "m6-reserved",
            "module TopModule; endmodule\nmodule RefModule; endmodule\n",
            "compile_failed",
        ),
        (
            "m6-reserved-tb",
            "module TopModule; endmodule\nmodule tb; endmodule\n",
            "compile_failed",
        ),
    ],
)
def test_bad_candidates_are_normal_candidate_failures(
    tmp_path: Path,
    name: str,
    source: str,
    category: str,
) -> None:
    _vg, result = chat_run(tmp_path, name, source)
    assert not result.scorecard.resolved
    assert result.scorecard.status == "completed"
    assert not result.scorecard.correctness.infrastructure_error
    failed = next(
        verifier
        for verifier in result.scorecard.verifier_results
        if verifier.status == VerifierStatus.FAILED
    )
    assert failed.error_category.value == category
    assert failed.metadata.get("candidate_failure") is True
    if name == "m6-wrong":
        assert failed.metadata["mismatches"] > 0
        assert failed.metadata["native_result_marker_found"] is True
    if name == "m6-early-finish":
        assert failed.metadata["native_result_marker_found"] is False


@requires_icarus
def test_hidden_sources_and_external_paths_never_enter_model_visible_artifacts(
    tmp_path: Path,
) -> None:
    vg, result = chat_run(tmp_path, "m6-leakage", GOOD)
    suite, task, assets = vg.load_task(TASK_ID, source_config())
    hidden_contents = [
        asset.content.encode("utf-8") for asset in assets.hidden_assets if asset.content is not None
    ]
    assert hidden_contents
    assert not (result.run_dir / "candidate" / "verifier").exists()
    candidate_files = {
        path.relative_to(result.run_dir / "candidate").as_posix()
        for path in (result.run_dir / "candidate").rglob("*")
        if path.is_file()
    }
    assert candidate_files == {"README.md", "rtl/TopModule.sv"}

    model_visible_paths = [
        result.run_dir / "trace.jsonl",
        result.run_dir / "logs" / "agent.log",
        result.run_dir / "workspace_diff.patch",
        *(path for path in (result.run_dir / "candidate").rglob("*") if path.is_file()),
    ]
    source_root = str(FIXTURE.resolve())
    for path in model_visible_paths:
        payload = path.read_bytes()
        assert source_root.encode() not in payload
        assert b"Prob900_fixture_and_ref.sv" not in payload
        assert b"Prob900_fixture_and_test.sv" not in payload
        assert all(hidden not in payload for hidden in hidden_contents)

    for path in result.run_dir.rglob("*"):
        if path.is_file():
            payload = path.read_bytes()
            assert all(hidden not in payload for hidden in hidden_contents)
    assert source_root not in task.model_dump_json()


def test_missing_icarus_is_an_infrastructure_error(monkeypatch, tmp_path: Path) -> None:
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))
    _vg, result = chat_run(tmp_path, "m6-no-icarus", GOOD)
    assert not result.scorecard.resolved
    assert result.scorecard.status == "error"
    assert result.scorecard.correctness.infrastructure_error
    compile_result = result.scorecard.verifier_results[0]
    assert compile_result.status == VerifierStatus.ERROR
    assert compile_result.error_category.value == "tool_not_found"


@requires_icarus
def test_suite_parser_exception_is_an_infrastructure_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def broken_parser(*_args, **_kwargs):
        raise RuntimeError("synthetic parser fault")

    monkeypatch.setattr(
        "verigym.suites.verilog_eval.verifier.parse_native_result",
        broken_parser,
    )
    _vg, result = chat_run(tmp_path, "m6-parser-error", GOOD)
    assert result.scorecard.status == "error"
    regression = result.scorecard.verifier_results[-1]
    assert regression.status == VerifierStatus.ERROR
    assert regression.error_category.value == "internal_error"


@requires_icarus
def test_literal_external_source_cli_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    validate = runner.invoke(
        app,
        [
            "suites",
            "validate",
            "--suite",
            "verilog-eval",
            "--source",
            str(FIXTURE),
            "--variant",
            VARIANT,
        ],
    )
    assert validate.exit_code == 0, validate.output
    assert '"valid": true' in validate.output

    listed = runner.invoke(
        app,
        [
            "tasks",
            "list",
            "--suite",
            "verilog-eval",
            "--source",
            str(FIXTURE),
            "--variant",
            VARIANT,
        ],
    )
    assert listed.exit_code == 0, listed.output
    assert "Prob900_fixture_and" in listed.output

    run = runner.invoke(
        app,
        [
            "run",
            "--suite",
            "verilog-eval",
            "--suite-source",
            str(FIXTURE),
            "--suite-variant",
            VARIANT,
            "--task",
            "Prob900_fixture_and",
            "--mode",
            "chat",
            "--agent",
            "single-turn",
            "--model",
            "static-verilog-eval-fixture-good",
            "--runtime",
            "local",
            "--output",
            str(tmp_path / "cli-runs"),
        ],
    )
    assert run.exit_code == 0, run.output
    assert "PASS verilog-eval/v2-spec-to-rtl/Prob900_fixture_and" in run.output


@pytest.mark.skipif(
    not os.environ.get("VERIGYM_VERILOG_EVAL_ROOT"),
    reason="VERIGYM_VERILOG_EVAL_ROOT is not configured",
)
@pytest.mark.external_benchmark
@requires_icarus
def test_optional_real_external_checkout_conformance(tmp_path: Path) -> None:
    root = Path(os.environ["VERIGYM_VERILOG_EVAL_ROOT"])
    config = SuiteSourceConfig(source_root=root, variant=VARIANT)
    before = hash_directory(
        root / "dataset_spec-to-rtl" if root.name != "dataset_spec-to-rtl" else root
    )
    vg = service()
    suite = vg.registries.suites.get("verilog-eval").with_source(config)
    references = list(suite.discover())
    assert references
    task = suite.load_task(references[0])
    reference = suite.reference_solution(task)
    assert reference is not None
    model = StaticModelClient(name="m6-real-reference", responses=list(reference.files.values()))
    vg.registries.models.register(model)
    result = vg.run(
        RunConfig(
            task_id=references[0].id,
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=model.descriptor.name,
            suite_source=config,
            output=tmp_path / "real",
        )
    )
    assert result.scorecard.resolved
    bad_model = StaticModelClient(
        name="m6-real-known-bad",
        responses=["module TopModule; endmodule\n"],
    )
    vg.registries.models.register(bad_model)
    bad_result = vg.run(
        RunConfig(
            task_id=references[0].id,
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=bad_model.descriptor.name,
            suite_source=config,
            output=tmp_path / "real-bad",
        )
    )
    assert not bad_result.scorecard.resolved
    assert not bad_result.scorecard.correctness.infrastructure_error
    assert not (result.run_dir / "candidate" / "verifier").exists()
    assert (
        hash_directory(root / "dataset_spec-to-rtl" if root.name != "dataset_spec-to-rtl" else root)
        == before
    )
