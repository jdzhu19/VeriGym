"""Bounded dry-planning diagnostic for the 10,000-item MVP limit."""

from __future__ import annotations

import argparse
import json
import resource
import tempfile
import time
from pathlib import Path

from verigym.core.orchestrator import VeriGym
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.schemas import ExperimentConfig
from verigym.registry.collections import build_registries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="verigym-plan-smoke-") as temporary:
        planned_output = Path(temporary) / "must-not-be-created"
        systems = [
            {"id": f"scripted-{index:02d}", "agent": {"id": "scripted"}} for index in range(10)
        ]
        config = ExperimentConfig.model_validate(
            {
                "schema_version": "1.0",
                "name": "bounded-plan-smoke",
                "suite": {
                    "id": "toy-rtl",
                    "tasks": {
                        "include": ["and-gate-basic", "counter-basic"],
                        "exclude": [],
                    },
                },
                "runs": {
                    "mode": "agent",
                    "seeds": list(range(10)),
                    "samples_per_task": 50,
                    "pass_k": [1],
                },
                "systems": systems,
                "runtime": {"id": "local"},
                "execution": {"max_workers": 1, "max_plan_items": 10_000},
                "output": {"root": planned_output},
            }
        )
        service = VeriGym(build_registries(discover_external=False))
        planner = ExperimentPlanner(service)
        started = time.perf_counter()
        first = planner.build(config)
        first_elapsed = time.perf_counter() - started
        started = time.perf_counter()
        second = planner.build(config)
        second_elapsed = time.perf_counter() - started
        deterministic = first.plan_hash == second.plan_hash and [
            item.plan_item_id for item in first.items
        ] == [item.plan_item_id for item in second.items]
        result = {
            "schema_version": "1.0",
            "status": (
                "passed"
                if len(first.items) == 10_000 and deterministic and not planned_output.exists()
                else "failed"
            ),
            "plan_items": len(first.items),
            "configured_limit": config.execution.max_plan_items,
            "first_wall_time_s": first_elapsed,
            "second_wall_time_s": second_elapsed,
            "peak_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "deterministic": deterministic,
            "output_created": planned_output.exists(),
            "model_or_tool_calls": 0,
        }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
