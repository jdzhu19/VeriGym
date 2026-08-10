"""Command-line preparation and one-instance smoke verification."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from verigym.api import RunConfig, VeriGym, build_registries
from verigym.plugin_api import (
    ConfigurationError,
    SuiteSourceConfig,
    VerifierStatus,
    copy_tree_safely,
)

from .adapter import HweBenchSuite
from .agent import HweBenchProbeAgent
from .dataset import VARIANT
from .prepare import prepare_source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verigym-hwe-bench")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-source")
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--task", action="append", required=True)
    prepare.add_argument("--pull", action="store_true")
    prepare.add_argument("--official-source-commit")
    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--source", type=Path, required=True)
    smoke.add_argument("--output", type=Path, required=True)
    smoke.add_argument("--task")
    return parser


def _smoke(*, source: Path, output: Path, selected_task: str | None) -> dict[str, object]:
    if output.exists() or output.is_symlink():
        raise ConfigurationError("smoke output already exists")
    source_config = SuiteSourceConfig(source_root=source, variant=VARIANT)
    configured = HweBenchSuite().with_source(source_config)
    references = list(configured.discover())
    if selected_task is None:
        if len(references) != 1:
            raise ConfigurationError(
                "--task is required when the prepared source has multiple tasks"
            )
        task_id = references[0].id
    else:
        matches = [ref.id for ref in references if selected_task in {ref.id, ref.native_id}]
        if len(matches) != 1:
            raise ConfigurationError("selected smoke task is not unique in the prepared source")
        task_id = matches[0]
    registries = build_registries(discover_external=False)
    registries.suites.register(HweBenchSuite())
    registries.agents.register(HweBenchProbeAgent())
    service = VeriGym(registries)
    base = service.run(
        RunConfig(
            task_id=task_id,
            agent="hwe-bench-probe",
            suite_source=source_config,
            runtime="local",
            output=output / "base-probe",
        )
    )
    suite, task, assets = service.load_task(task_id, source_config)
    reference = suite.reference_solution(task)
    if reference is None:
        raise ConfigurationError("selected HWE-Bench task lacks its reference candidate")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="verigym-hwe-smoke-reference-", dir=output.parent
    ) as temporary:
        candidate = Path(temporary) / "candidate"
        copy_tree_safely(Path(assets.visible_root), candidate)
        for relative, content in reference.files.items():
            destination = candidate / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        results = suite.verify_candidate(
            task=task,
            candidate_dir=candidate,
            artifact_root=output / "reference-verifier",
        )
    if results is None:
        raise ConfigurationError("HWE-Bench suite did not claim its verifier")
    reference_passed = bool(results) and all(
        result.status == VerifierStatus.PASSED for result in results
    )
    report: dict[str, object] = {
        "schema_version": "1.0",
        "kind": "hwe_bench_single_instance_fail_to_pass_smoke",
        "task_id": task_id,
        "base_run_id": base.manifest.run_id,
        "base_resolved": base.scorecard.resolved,
        "base_infrastructure_error": base.scorecard.correctness.infrastructure_error,
        "reference_passed": reference_passed,
        "model_process_count": 0,
        "full_campaign": False,
        "verifier_results": [
            {
                "node_id": result.node_id,
                "status": result.status.value,
                "error_category": result.error_category.value,
                "tests_passed": result.tests_passed,
                "tests_total": result.tests_total,
            }
            for result in results
        ],
    }
    (output / "smoke-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if (
        base.scorecard.resolved
        or base.scorecard.correctness.infrastructure_error
        or not reference_passed
    ):
        raise ConfigurationError("HWE-Bench smoke did not reproduce base-FAIL/reference-PASS")
    return report


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare-source":
            result = prepare_source(
                dataset=args.dataset,
                output=args.output,
                selected_tasks=args.task,
                pull=args.pull,
                official_source_commit=args.official_source_commit,
            )
            print(result)
        elif args.command == "smoke":
            print(
                json.dumps(_smoke(source=args.source, output=args.output, selected_task=args.task))
            )
        else:  # pragma: no cover - argparse enforces the subcommand set
            raise ConfigurationError("unknown command")
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
