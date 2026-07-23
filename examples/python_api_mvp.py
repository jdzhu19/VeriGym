"""Executable public-API smoke example for the complete MVP workflow."""

from __future__ import annotations

import tempfile
from pathlib import Path

from verigym.api import (
    BatchRunner,
    ExperimentConfig,
    ExperimentPlanner,
    ReportService,
    RunConfig,
    VeriGym,
    replay_run,
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="verigym-python-api-") as temporary:
        root = Path(temporary)
        service = VeriGym()

        run = service.run(
            RunConfig(
                task_id="toy-rtl/and-gate-basic",
                agent="scripted",
                output=root / "runs",
            )
        )
        assert run.scorecard.resolved
        assert replay_run(run.run_dir).scorecard.resolved

        samples = service.run_samples(
            RunConfig(
                task_id="toy-rtl/and-gate-basic",
                mode="chat",
                agent="single-turn",
                model="static-and-gate-mixed",
                output=root / "samples",
            ),
            samples=2,
            pass_k=[1, 2],
        )
        assert samples.report.entries[1].k == 2

        config = ExperimentConfig.model_validate(
            {
                "schema_version": "1.0",
                "name": "public-api-smoke",
                "suite": {
                    "id": "toy-rtl",
                    "tasks": {"include": ["and-gate-basic"], "exclude": []},
                },
                "runs": {
                    "mode": "agent",
                    "seeds": [0],
                    "samples_per_task": 1,
                    "pass_k": [1],
                },
                "systems": [{"id": "scripted", "agent": {"id": "scripted"}}],
                "runtime": {"id": "local"},
                "execution": {"max_workers": 1},
                "output": {"root": root / "experiment"},
            }
        )
        planner = ExperimentPlanner(service)
        batch = BatchRunner(planner=planner, service_factory=lambda: service).run(
            planner.build(config)
        )
        assert batch.exit_code == 0
        reports = ReportService().generate_all(batch.experiment_dir)
        assert reports.aggregate.coverage.resolved_runs == 1


if __name__ == "__main__":
    main()
