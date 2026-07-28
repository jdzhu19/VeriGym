"""Zero-model qualification of frozen official reference candidates."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.workspace import normalize_relative_path
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.schemas import ExperimentPlan, PlanItem
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.verifier import VerifierStatus


def qualify_reference_candidates(
    plan: ExperimentPlan,
    output: Path,
    *,
    planner: ExperimentPlanner | None = None,
    service_factory: Callable[[], VeriGym] = VeriGym,
) -> dict[str, object]:
    """Run each frozen task's official reference through its exact verifier runtime."""

    service = service_factory()
    verifier = planner or ExperimentPlanner(service)
    verifier.verify_frozen_inputs(plan)
    unique: dict[str, PlanItem] = {}
    for item in plan.items:
        incumbent = unique.setdefault(item.task_id, item)
        if (
            incumbent.task_hash != item.task_hash
            or incumbent.source_hash != item.source_hash
            or incumbent.verifier_hash != item.verifier_hash
            or incumbent.runtime_identity_hash != item.runtime_identity_hash
        ):
            raise ConfigurationError(
                f"plan contains incompatible qualification identities for {item.task_id}"
            )

    records: list[dict[str, object]] = []
    for task_id in sorted(unique):
        item = unique[task_id]
        suite, task, assets = service.load_task(item.task_id, item.suite_source)
        source_hash = task.source.content_hash or hash_directory(Path(assets.visible_root))
        if content_hash(task) != item.task_hash or source_hash != item.source_hash:
            raise ConfigurationError(f"reference qualification input changed for {item.task_id}")
        candidate = suite.reference_solution(task)
        if candidate is None:
            raise ConfigurationError(f"task {task.id} has no official reference candidate")
        runtime_plugin = service.registries.runtimes.get(item.runtime_id)
        runtime = runtime_plugin.configure_for_replay(item.runtime_descriptor)
        run_id = f"reference-{item.plan_item_id[:20]}"
        results = []
        try:
            runtime.prepare(run_id)
            with (
                tempfile.TemporaryDirectory(
                    prefix="verigym-reference-candidate-"
                ) as candidate_name,
                tempfile.TemporaryDirectory(prefix="verigym-reference-artifacts-") as artifact_name,
            ):
                candidate_root = Path(candidate_name)
                for raw_path, source in sorted(candidate.files.items()):
                    relative = normalize_relative_path(raw_path)
                    destination = candidate_root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(source, encoding="utf-8")
                results = service._verify_candidate(
                    task=task,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate_root,
                    artifact_root=Path(artifact_name),
                )
        finally:
            runtime.close()
        passed = bool(results) and all(result.status == VerifierStatus.PASSED for result in results)
        records.append(
            {
                "task_id": item.task_id,
                "task_hash": item.task_hash,
                "source_hash": item.source_hash,
                "verifier_hash": item.verifier_hash,
                "runtime_identity_hash": item.runtime_identity_hash,
                "reference_candidate_hash": content_hash(candidate),
                "passed": passed,
                "verifier_results": [
                    {
                        "node_id": result.node_id,
                        "status": result.status.value,
                        "error_category": result.error_category.value,
                        "exit_code": result.exit_code,
                    }
                    for result in results
                ],
            }
        )
    passed_count = sum(bool(record["passed"]) for record in records)
    report: dict[str, object] = {
        "schema_version": "1.0",
        "qualification_kind": "official_reference_candidate_exact_frozen_verifier",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": plan.experiment_id,
        "plan_hash": plan.plan_hash,
        "task_set_hash": plan.task_set_hash,
        "task_count": len(records),
        "passed_count": passed_count,
        "all_passed": passed_count == len(records),
        "model_process_count": 0,
        "records": records,
    }
    output = output.expanduser()
    if output.exists() or output.is_symlink():
        raise ConfigurationError("reference qualification output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_dump_json(output, report)
    mode = stat.S_IMODE(os.lstat(output).st_mode)
    os.chmod(output, mode & ~0o222)
    if not report["all_passed"]:
        raise ConfigurationError(
            f"official reference qualification passed {passed_count}/{len(records)}"
        )
    return report


def qualification_sha256(path: Path) -> str:
    """Return the sealed qualification report byte hash."""

    return hash_bytes(path.read_bytes())


__all__ = ["qualification_sha256", "qualify_reference_candidates"]
