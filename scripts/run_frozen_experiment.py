#!/usr/bin/env python3
"""Prepare, qualify, execute, replay, and report one generic frozen experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verigym.core.orchestrator import VeriGym
from verigym.core.replay import ReplaySummary, replay_run
from verigym.experiments.config import load_experiment_config
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.qualification import qualify_reference_candidates
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig, PlanItem
from verigym.experiments.state import atomic_dump_json, load_json_model
from verigym.registry.collections import build_registries
from verigym.reporting.loader import load_report_inputs
from verigym.reporting.service import ReportService


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)

    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--qualification-output", type=Path, required=True)
    prepare.add_argument("--expected-tasks", type=int)
    prepare.add_argument("--expected-items", type=int)

    execute = subcommands.add_parser("execute")
    execute.add_argument("--experiment", type=Path, required=True)
    execute.add_argument("--qualification", type=Path, required=True)
    execute.add_argument("--identity-preflight", type=Path, required=True)
    execute.add_argument("--expected-tasks", type=int)
    execute.add_argument("--expected-items", type=int)

    replay = subcommands.add_parser("replay")
    replay.add_argument("--experiment", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)

    report = subcommands.add_parser("report")
    report.add_argument("--experiment", type=Path, required=True)
    report.add_argument("--bootstrap-resamples", type=int, default=10_000)
    report.add_argument("--bootstrap-seed", type=int, default=548_219_773)

    arguments = parser.parse_args()
    service = VeriGym(build_registries())
    planner = ExperimentPlanner(service)
    runner = BatchRunner(
        planner=planner,
        service_factory=lambda: VeriGym(build_registries()),
    )
    if arguments.command == "prepare":
        config = load_experiment_config(arguments.config)
        plan = planner.build(config)
        _require_counts(
            plan.items,
            expected_tasks=arguments.expected_tasks,
            expected_items=arguments.expected_items,
        )
        root = runner.prepare(plan)
        qualification = qualify_reference_candidates(
            plan,
            arguments.qualification_output,
            planner=planner,
            service_factory=lambda: VeriGym(build_registries()),
        )
        print(
            json.dumps(
                {
                    "experiment": str(root),
                    "experiment_id": plan.experiment_id,
                    "plan_hash": plan.plan_hash,
                    "task_set_hash": plan.task_set_hash,
                    "planned_items": len(plan.items),
                    "qualified_tasks": qualification["passed_count"],
                    "model_process_count": 0,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if arguments.command == "execute":
        qualification = json.loads(arguments.qualification.read_text(encoding="utf-8"))
        inputs = load_report_inputs(arguments.experiment)
        config = load_json_model(
            arguments.experiment / "experiment_config.json",
            ExperimentConfig,
        )
        identity_preflight = json.loads(arguments.identity_preflight.read_text(encoding="utf-8"))
        _require_counts(
            inputs.plan_items,
            expected_tasks=arguments.expected_tasks,
            expected_items=arguments.expected_items,
        )
        if (
            qualification.get("all_passed") is not True
            or qualification.get("experiment_id") != inputs.experiment_id
            or qualification.get("plan_hash") != inputs.plan_hash
            or qualification.get("task_set_hash") != inputs.task_set_hash
            or qualification.get("passed_count")
            != len({item.task_id for item in inputs.plan_items})
            or qualification.get("model_process_count") != 0
        ):
            raise SystemExit("reference qualification is incomplete or not bound to this plan")
        if (
            identity_preflight.get("status") != "pass"
            or identity_preflight.get("model_process_count") != 0
            or identity_preflight.get("experiment_id") != inputs.experiment_id
            or identity_preflight.get("plan_hash") != inputs.plan_hash
            or identity_preflight.get("frozen_campaign_identity")
            != config.execution.frozen_campaign_identity
        ):
            raise SystemExit("zero-call identity preflight is incomplete or not plan-bound")
        result = runner.resume(arguments.experiment)
        print(result.model_dump_json(indent=2))
        return result.exit_code
    if arguments.command == "replay":
        inputs = load_report_inputs(arguments.experiment)
        records = []
        for run in sorted(
            inputs.valid_runs,
            key=lambda item: (item.plan_index, item.attempt),
        ):
            replay_result = replay_run(
                arguments.experiment / run.relative_path,
                verify=False,
            )
            records.append(
                {
                    "plan_index": run.plan_index,
                    "attempt": run.attempt,
                    "run_id": replay_result.manifest.run_id,
                    "artifact_integrity": _replay_integrity_status(replay_result),
                    "model_calls": 0,
                    "runtime_calls": 0,
                    "network_calls": 0,
                }
            )
        payload = {
            "schema_version": "1.0",
            "experiment_id": inputs.experiment_id,
            "plan_hash": inputs.plan_hash,
            "terminal_replay_count": len(records),
            "model_calls": 0,
            "runtime_calls": 0,
            "network_calls": 0,
            "records": records,
        }
        atomic_dump_json(arguments.output, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    reports = ReportService().generate_full_scale(
        arguments.experiment,
        bootstrap_resamples=arguments.bootstrap_resamples,
        bootstrap_seed=arguments.bootstrap_seed,
    )
    print(json.dumps(reports.hashes, indent=2, sort_keys=True))
    return 0


def _require_counts(
    items: list[PlanItem],
    *,
    expected_tasks: int | None,
    expected_items: int | None,
) -> None:
    task_count = len({item.task_id for item in items})
    if expected_tasks is not None and task_count != expected_tasks:
        raise SystemExit(f"expected {expected_tasks} tasks, observed {task_count}")
    if expected_items is not None and len(items) != expected_items:
        raise SystemExit(f"expected {expected_items} plan items, observed {len(items)}")


def _replay_integrity_status(summary: ReplaySummary) -> str:
    """Read the canonical nested integrity status from an offline replay summary."""

    return summary.integrity.status


if __name__ == "__main__":
    raise SystemExit(main())
