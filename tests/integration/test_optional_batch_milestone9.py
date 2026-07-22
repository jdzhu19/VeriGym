from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.milestone9_helpers import experiment_config
from verigym.core.orchestrator import VeriGym
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig
from verigym.reporting.aggregate import ReportBuilder
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig


@pytest.mark.integration
@pytest.mark.docker_batch
@pytest.mark.skipif(
    os.environ.get("VERIGYM_RUN_DOCKER_BATCH_TESTS") != "1",
    reason="set VERIGYM_RUN_DOCKER_BATCH_TESTS=1 to run the Docker batch smoke test",
)
def test_optional_docker_batch(tmp_path: Path) -> None:
    image = os.environ.get("VERIGYM_DOCKER_IMAGE", "verigym/rtl-iverilog:12.0")
    config = experiment_config(
        tmp_path / "docker-batch",
        tasks=["and-gate-basic"],
        systems=[
            {"id": "good", "agent": {"id": "scripted"}},
            {"id": "bad", "agent": {"id": "scripted-bad"}},
        ],
        seeds=[0],
    )
    config = config.model_copy(
        update={
            "runtime": config.runtime.model_copy(
                update={
                    "id": "docker",
                    "docker": DockerRuntimeConfig(image=image, pull_policy="never"),
                }
            )
        }
    )
    planner = ExperimentPlanner()
    result = BatchRunner().run(planner.build(config))
    aggregate = ReportBuilder().build(result.experiment_dir)
    assert result.exit_code == 0
    assert aggregate.coverage.valid_terminal_artifacts == 2
    assert aggregate.coverage.resolved_runs == 1


@pytest.mark.integration
@pytest.mark.yosys_batch
@pytest.mark.skipif(
    os.environ.get("VERIGYM_RUN_YOSYS_BATCH_TESTS") != "1",
    reason="set VERIGYM_RUN_YOSYS_BATCH_TESTS=1 to run the Yosys profile batch test",
)
def test_optional_yosys_area_batch(tmp_path: Path) -> None:
    image = os.environ.get(
        "VERIGYM_DOCKER_YOSYS_IMAGE",
        "verigym/open-rtl-tools:iverilog12-yosys067",
    )
    config = experiment_config(
        tmp_path / "yosys-batch",
        tasks=["counter-basic"],
        systems=[
            {"id": "good", "agent": {"id": "scripted"}},
            {"id": "bad", "agent": {"id": "scripted-bad"}},
        ],
        seeds=[0],
    )
    config = config.model_copy(
        update={
            "runtime": config.runtime.model_copy(
                update={
                    "id": "docker",
                    "docker": DockerRuntimeConfig(image=image, pull_policy="never"),
                }
            ),
            "profile": "open-yosys-toy-area-v1",
        }
    )
    planner = ExperimentPlanner()
    result = BatchRunner().run(planner.build(config))
    partitions = ReportBuilder().build(result.experiment_dir).quality_partitions
    assert result.exit_code == 0
    assert len(partitions) == 1
    assert partitions[0].eligible_run_count == 1
    assert partitions[0].ineligible_run_count == 1


@pytest.mark.integration
@pytest.mark.verilog_eval_batch
@pytest.mark.skipif(
    os.environ.get("VERIGYM_RUN_VERILOG_EVAL_BATCH_TESTS") != "1",
    reason=("set VERIGYM_RUN_VERILOG_EVAL_BATCH_TESTS=1 to run the external VerilogEval batch"),
)
def test_optional_external_verilog_eval_multi_task_batch(tmp_path: Path) -> None:
    source = Path(
        os.environ.get(
            "VERIGYM_VERILOG_EVAL_ROOT",
            str(Path(__file__).parents[1] / "fixtures" / "verilog_eval_v2_synthetic"),
        )
    )
    source_config = SuiteSourceConfig(
        source_root=source,
        variant="v2-spec-to-rtl",
        strict_compatibility=True,
    )
    adapter = VeriGym().registries.suites.get("verilog-eval").with_source(source_config)
    selected = sorted(reference.id for reference in adapter.discover())[:2]
    assert len(selected) == 2
    config = ExperimentConfig.model_validate(
        {
            "schema_version": "1.0",
            "name": "external-verilog-eval-batch",
            "suite": {
                "id": "verilog-eval",
                "source": source,
                "variant": "v2-spec-to-rtl",
                "strict_compatibility": True,
                "tasks": {"include": selected, "exclude": []},
            },
            "runs": {
                "mode": "chat",
                "seeds": [0],
                "samples_per_task": 1,
                "pass_k": [1],
            },
            "systems": [
                {
                    "id": "static",
                    "agent": {"id": "single-turn"},
                    "model": {"id": "static-verilog-eval-fixture-good"},
                }
            ],
            "runtime": {"id": "local"},
            "output": {"root": tmp_path / "verilog-eval-batch"},
        }
    )
    planner = ExperimentPlanner()
    result = BatchRunner().run(planner.build(config))
    aggregate = ReportBuilder().build(result.experiment_dir)
    assert result.exit_code == 0
    assert aggregate.coverage.planned_plan_items == 2
    assert aggregate.coverage.valid_terminal_artifacts == 2
    assert aggregate.coverage.evaluable_candidate_runs == 2
