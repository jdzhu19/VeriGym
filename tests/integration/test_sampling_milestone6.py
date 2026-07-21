from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from verigym.cli.app import app
from verigym.core.errors import ConfigurationError
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.core.sampling import regenerate_sample_report
from verigym.models.base import ModelClientError
from verigym.models.static import StaticModelClient
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.model import (
    ModelClientErrorInfo,
    ModelErrorCategory,
    ModelRequest,
    ModelResponse,
    ModelRunConfig,
)
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("iverilog") is None or shutil.which("vvp") is None,
        reason="Icarus Verilog is not installed",
    ),
]

FIXTURE = Path(__file__).parents[1] / "fixtures" / "verilog_eval_v2_synthetic"
VARIANT = "v2-spec-to-rtl"
GOOD = "module TopModule(input logic a,b,output logic y); assign y=a&b; endmodule\n"
BAD = "module TopModule(input logic a,b,output logic y); assign y=a|b; endmodule\n"


class CountingSampleModel(StaticModelClient):
    def __init__(
        self,
        calls: list[str],
        *,
        selected_sample_index: int | None = None,
        infrastructure_sample: int | None = None,
    ) -> None:
        self.calls = calls
        self.infrastructure_sample = infrastructure_sample
        super().__init__(
            name=(
                "m6-counting-infrastructure"
                if infrastructure_sample is not None
                else "m6-counting-mixed"
            ),
            responses=[GOOD],
            sample_responses=[[GOOD], [BAD], [GOOD], ["not RTL"]],
            _selected_sample_index=selected_sample_index,
        )

    def clone_for_run(
        self,
        configuration: ModelRunConfig | None = None,
    ) -> CountingSampleModel:
        return CountingSampleModel(
            self.calls,
            selected_sample_index=(configuration.sample_index if configuration else 0),
            infrastructure_sample=self.infrastructure_sample,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request.request_id)
        if self._selected_sample_index == self.infrastructure_sample:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.TRANSPORT,
                    message="synthetic transport failure",
                    retryable=True,
                )
            )
        return super().generate(request)


def service(*models: StaticModelClient) -> VeriGym:
    registries = build_registries(discover_external=False)
    for model in models:
        registries.models.register(model)
    return VeriGym(registries)


def config(output: Path, model: str, *, variant: str = VARIANT) -> RunConfig:
    return RunConfig(
        task_id="verilog-eval/Prob900_fixture_and",
        mode=InteractionMode.CHAT,
        agent="single-turn",
        model=model,
        model_options=ModelRunConfig(temperature=0.7, top_p=0.9),
        suite_source=SuiteSourceConfig(source_root=FIXTURE, variant=variant),
        seed=7,
        output=output,
    )


def test_four_samples_are_independent_replayable_and_regenerable(tmp_path: Path) -> None:
    calls: list[str] = []
    model = CountingSampleModel(calls)
    vg = service(model)
    result = vg.run_samples(
        config(tmp_path / "samples", model.descriptor.name),
        samples=4,
        pass_k=[1, 2, 3],
    )
    report = result.report
    assert len(calls) == 4
    assert len(set(calls)) == 4
    assert report.task_id == "verilog-eval/v2-spec-to-rtl/Prob900_fixture_and"
    assert report.canonical_valid
    assert report.valid_candidate_verdict_count == 4
    assert report.resolved_count == 2
    assert report.candidate_failure_count == 1
    assert report.model_output_failure_count == 1
    assert report.infrastructure_error_count == 0
    assert [entry.value for entry in report.entries] == pytest.approx([0.5, 5 / 6, 1.0])

    children = result.manifest.child_runs
    assert [child.sample_index for child in children] == [0, 1, 2, 3]
    assert [child.seed for child in children] == [7, 8, 9, 10]
    assert len({child.run_id for child in children}) == 4
    assert len({child.configuration_fingerprint for child in children}) == 1
    assert all(not Path(child.relative_path).is_absolute() for child in children)
    assert all(child.relative_path.startswith("samples/") for child in children)

    ordinary_layout = {
        "run_manifest.json",
        "task_snapshot.json",
        "trace.jsonl",
        "scorecard.json",
        "workspace_diff.patch",
        "candidate",
        "logs",
        "artifacts",
    }
    for child in children:
        child_dir = result.group_dir / child.relative_path
        assert ordinary_layout <= {path.name for path in child_dir.iterdir()}
        assert (child_dir / "candidate" / "rtl" / "TopModule.sv").is_file()
        child_manifest = (child_dir / "run_manifest.json").read_text(encoding="utf-8")
        assert '"temperature": 0.7' in child_manifest
        assert '"top_p": 0.9' in child_manifest
    assert (result.group_dir / "sample_set_manifest.json").is_file()
    assert (result.group_dir / "pass_at_k.json").is_file()

    calls_before = list(calls)
    replayed = replay_run(
        result.group_dir / children[0].relative_path,
        verify=True,
        service=vg,
    )
    assert replayed.reverified_resolved is True
    assert calls == calls_before
    regenerated = regenerate_sample_report(result.group_dir)
    assert regenerated.report == result.report
    assert calls == calls_before


def test_fresh_static_clone_per_sample_prevents_response_cursor_leakage(tmp_path: Path) -> None:
    model = StaticModelClient(name="m6-one-response", responses=[GOOD])
    vg = service(model)
    result = vg.run_samples(
        config(tmp_path / "clones", model.descriptor.name),
        samples=3,
        pass_k=[1, 3],
    )
    assert result.report.resolved_count == 3
    assert result.report.canonical_valid
    assert [entry.value for entry in result.report.entries] == [1.0, 1.0]
    assert sum(child.candidate_verdict for child in result.report.child_runs) == 3


def test_model_transport_failure_invalidates_canonical_pass_at_k(tmp_path: Path) -> None:
    calls: list[str] = []
    model = CountingSampleModel(calls, infrastructure_sample=1)
    vg = service(model)
    result = vg.run_samples(
        config(tmp_path / "infrastructure", model.descriptor.name),
        samples=2,
        pass_k=[1],
    )
    assert len(calls) == 2
    assert not result.report.canonical_valid
    assert result.report.infrastructure_error_count == 1
    assert result.report.valid_candidate_verdict_count == 1
    assert result.report.entries[0].invalid_reason == "infrastructure_error"
    assert result.report.entries[0].value is None


@pytest.mark.parametrize(
    ("samples", "pass_k", "variant", "message"),
    [
        (0, [1], VARIANT, "sample count"),
        (1, [0], VARIANT, "positive"),
        (1, [1], "unsupported", "unsupported VerilogEval variant"),
    ],
)
def test_invalid_sample_configuration_fails_before_model_invocation(
    tmp_path: Path,
    samples: int,
    pass_k: list[int],
    variant: str,
    message: str,
) -> None:
    calls: list[str] = []
    model = CountingSampleModel(calls)
    vg = service(model)
    with pytest.raises(ConfigurationError, match=message):
        vg.run_samples(
            config(tmp_path / "invalid", model.descriptor.name, variant=variant),
            samples=samples,
            pass_k=pass_k,
        )
    assert calls == []


def test_literal_multi_sample_cli_prints_children_and_aggregate(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
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
            "static-verilog-eval-fixture-mixed",
            "--samples",
            "4",
            "--pass-k",
            "1",
            "--pass-k",
            "2",
            "--pass-k",
            "3",
            "--runtime",
            "local",
            "--output",
            str(tmp_path / "cli-samples"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "n=4, c=2" in result.output
    assert "pass@1=0.5" in result.output
    assert "pass@2=0.833333333333" in result.output
    assert "sample[0000]" in result.output
    assert "Aggregate report:" in result.output


def test_cli_rejects_zero_samples_during_option_parsing(tmp_path: Path) -> None:
    result = CliRunner().invoke(
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
            "--samples",
            "0",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "x>=1" in result.output
