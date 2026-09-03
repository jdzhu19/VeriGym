"""Zero-model functional qualification for a private VerilogEval VCS/MCP bundle."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.core.verifier_dag import has_infrastructure_error
from verigym.core.verifier_profiles import resolve_verifier_profile, task_with_verifier_profile
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.registry.collections import build_registries
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.task import Candidate, VeriTask
from verigym.schemas.verifier import VerifierResult, VerifierStatus
from verigym.suites.verilog_eval.adapter import VerilogEvalSuite
from verigym.suites.verilog_eval.schemas import VerilogEvalVariant

from .vcs_mcp_client import McpVcsSimulationTool

VARIANT = VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_V1.value
SUPPORTED_VARIANTS = {
    VARIANT,
    VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify every task in a private VerilogEval VCS/MCP profile bundle."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reference-only",
        action="store_true",
        help="Skip the per-task known-bad rejection check.",
    )
    parser.add_argument("--task", action="append", default=[], help="Native task ID to qualify.")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int)
    return parser


def _load_catalog(bundle_root: Path) -> dict[str, Any]:
    path = bundle_root / "catalog.json"
    if bundle_root.is_symlink() or path.is_symlink() or not path.is_file():
        raise ConfigurationError("VerilogEval VCS/MCP bundle catalog is unavailable")
    if (bundle_root / "INCOMPLETE").exists():
        raise ConfigurationError("VerilogEval VCS/MCP bundle is incomplete")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("VerilogEval VCS/MCP bundle catalog is invalid") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("VerilogEval VCS/MCP bundle catalog must be an object")
    if payload.get("kind") != "verilog_eval_vcs_mcp_profile_bundle_v1":
        raise ConfigurationError("unexpected VerilogEval VCS/MCP bundle kind")
    if payload.get("variant") not in SUPPORTED_VARIANTS:
        raise ConfigurationError("unexpected VerilogEval VCS/MCP bundle variant")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("task_count") != len(records):
        raise ConfigurationError("VerilogEval VCS/MCP bundle task count is invalid")
    required_record_strings = {
        "native_id",
        "task_id",
        "task_hash",
        "client_profile",
        "client_declared_profile_hash",
        "client_resolved_profile_hash",
        "server_resolved_profile_hash",
    }
    if any(
        not isinstance(record, dict)
        or any(not isinstance(record.get(key), str) for key in required_record_strings)
        for record in records
    ):
        raise ConfigurationError("VerilogEval VCS/MCP bundle records are invalid")
    identity = {
        "variant": payload.get("variant"),
        "dataset_content_hash": payload.get("dataset_content_hash"),
        "task_count": payload.get("task_count"),
        "accepted_vcs_version": payload.get("accepted_vcs_version"),
        "excluded_tasks": payload.get("excluded_tasks"),
        "profile_resolution_mode": payload.get("profile_resolution_mode"),
        "records": records,
    }
    if payload.get("bundle_identity_hash") != content_hash(identity):
        raise ConfigurationError("VerilogEval VCS/MCP bundle identity changed")
    return payload


def _bundle_file(bundle_root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise ConfigurationError("VCS/MCP bundle file reference must be a string")
    relative = Path(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ConfigurationError("VCS/MCP bundle file reference is unsafe")
    requested = bundle_root / relative
    if requested.is_symlink() or not requested.is_file():
        raise ConfigurationError("VCS/MCP bundle file must be a regular non-symlink file")
    resolved = requested.resolve(strict=True)
    if not resolved.is_relative_to(bundle_root):
        raise ConfigurationError("VCS/MCP bundle file escapes its root")
    return resolved


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    parent = path.parent.resolve(strict=True)
    output = parent / path.name
    temporary = parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _materialize(candidate: Candidate, root: Path) -> None:
    for relative, source in candidate.files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def _passed(task: VeriTask, results: list[VerifierResult]) -> bool:
    if has_infrastructure_error(results):
        raise ConfigurationError("VCS/MCP qualification encountered an infrastructure failure")
    by_id = {result.node_id: result for result in results}
    return all(
        by_id.get(node_id) is not None and by_id[node_id].status == VerifierStatus.PASSED
        for node_id in task.scoring.correctness_required_nodes
    )


def _run_candidate(
    *,
    service: VeriGym,
    suite: VerilogEvalSuite,
    task: VeriTask,
    runtime: LocalRuntime,
    assets: Any,
    candidate: Candidate,
    profile: Any,
    resolved: Any,
    work_root: Path,
    label: str,
) -> tuple[bool, list[dict[str, str]]]:
    with tempfile.TemporaryDirectory(prefix=f"{label}-", dir=work_root) as temporary:
        root = Path(temporary)
        candidate_root = root / "candidate"
        candidate_root.mkdir()
        _materialize(candidate, candidate_root)
        results = service._verify_candidate(
            suite=suite,
            task=task,
            assets=assets,
            runtime=runtime,
            candidate_dir=candidate_root,
            artifact_root=root / "artifacts",
            verifier_profile=profile,
            resolved_verifier_profile=resolved,
        )
    summary = [
        {
            "node_id": result.node_id,
            "status": result.status.value,
            "error_category": result.error_category.value,
        }
        for result in results
    ]
    return _passed(task, results), summary


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if (arguments.shard_index is None) != (arguments.shard_count is None):
        raise ConfigurationError("--shard-index and --shard-count must be supplied together")
    if arguments.task and arguments.shard_count is not None:
        raise ConfigurationError("--task and shard selection are mutually exclusive")
    bundle_root = arguments.bundle_root.expanduser().resolve(strict=True)
    catalog = _load_catalog(bundle_root)
    work_root = arguments.work_root.expanduser()
    if work_root.is_symlink():
        raise ConfigurationError("qualification work root cannot be a symlink")
    work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    work_root = work_root.resolve(strict=True)
    output = arguments.output.expanduser()
    if output.exists() or output.is_symlink():
        raise ConfigurationError("qualification output already exists")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    source_config = SuiteSourceConfig(
        source_root=arguments.source_root,
        variant=str(catalog["variant"]),
        strict_compatibility=True,
    )
    suite = VerilogEvalSuite(source_config)
    snapshot = suite.source_snapshot()
    if snapshot is None or snapshot.dataset_content_hash != catalog["dataset_content_hash"]:
        raise ConfigurationError("VerilogEval dataset differs from the VCS/MCP bundle")
    references = {reference.native_id: reference for reference in suite.discover()}
    records_by_native = {record["native_id"]: record for record in catalog["records"]}
    if set(references) != set(records_by_native):
        raise ConfigurationError("VerilogEval task set differs from the VCS/MCP bundle")
    selected = sorted(references)
    selection: dict[str, object] = {"kind": "all"}
    if arguments.task:
        if len(arguments.task) != len(set(arguments.task)) or not set(arguments.task).issubset(
            references
        ):
            raise ConfigurationError("qualification task selection is duplicate or unknown")
        selected = sorted(arguments.task)
        selection = {"kind": "explicit", "task_ids": selected}
    elif arguments.shard_count is not None:
        assert arguments.shard_index is not None
        if arguments.shard_count < 1 or not 0 <= arguments.shard_index < arguments.shard_count:
            raise ConfigurationError("qualification shard selection is out of range")
        selected = [
            native_id
            for index, native_id in enumerate(selected)
            if index % arguments.shard_count == arguments.shard_index
        ]
        selection = {
            "kind": "shard",
            "shard_index": arguments.shard_index,
            "shard_count": arguments.shard_count,
        }

    registries = build_registries(discover_external=False)
    registries.tools.register(McpVcsSimulationTool())
    service = VeriGym(registries)
    runtime = LocalRuntime()
    runtime.prepare("verilog-eval-vcs-mcp-qualification-v1")
    verdicts: list[dict[str, object]] = []
    try:
        for native_id in selected:
            record = records_by_native[native_id]
            task = suite.load_task(references[native_id])
            if task.id != record["task_id"] or content_hash(task) != record["task_hash"]:
                raise ConfigurationError("VerilogEval task identity differs from the bundle")
            profile_path = _bundle_file(bundle_root, record["client_profile"])
            profile = load_verifier_profile(profile_path)
            if content_hash(profile) != record["client_declared_profile_hash"]:
                raise ConfigurationError("VCS/MCP client profile identity differs from the bundle")
            resolved = resolve_verifier_profile(
                task=task,
                profile=profile,
                tools=registries.tools,
            )
            if (
                resolved.resolved_profile_hash != record["client_resolved_profile_hash"]
                or resolved.server_resolved_profile_hash != record["server_resolved_profile_hash"]
            ):
                raise ConfigurationError("VCS/MCP resolved identity differs from the bundle")
            execution_task = task_with_verifier_profile(task, profile)
            assets = suite.resolve_assets(task)
            reference_candidate = suite.reference_solution(task)
            if reference_candidate is None:
                raise ConfigurationError("VerilogEval reference candidate is unavailable")
            reference_passed, reference_results = _run_candidate(
                service=service,
                suite=suite,
                task=execution_task,
                runtime=runtime,
                assets=assets,
                candidate=reference_candidate,
                profile=profile,
                resolved=resolved,
                work_root=work_root,
                label=f"{native_id}-reference",
            )
            if not reference_passed:
                raise ConfigurationError(
                    f"VCS/MCP rejected VerilogEval reference {native_id}: {reference_results}"
                )
            verdict: dict[str, object] = {
                "native_id": native_id,
                "task_id": task.id,
                "task_hash": content_hash(task),
                "client_declared_profile_hash": content_hash(profile),
                "client_resolved_profile_hash": resolved.resolved_profile_hash,
                "server_resolved_profile_hash": resolved.server_resolved_profile_hash,
                "reference_passed": True,
                "reference_results": reference_results,
            }
            if not arguments.reference_only:
                known_bad = Candidate(
                    files={"repository/rtl/TopModule.sv": "module TopModule; endmodule\n"},
                    label="known-bad-empty-interface",
                )
                bad_passed, bad_results = _run_candidate(
                    service=service,
                    suite=suite,
                    task=execution_task,
                    runtime=runtime,
                    assets=assets,
                    candidate=known_bad,
                    profile=profile,
                    resolved=resolved,
                    work_root=work_root,
                    label=f"{native_id}-known-bad",
                )
                if bad_passed:
                    raise ConfigurationError(
                        f"VCS/MCP accepted known-bad VerilogEval candidate {native_id}: "
                        f"{bad_results}"
                    )
                verdict.update({"known_bad_rejected": True, "known_bad_results": bad_results})
            verdicts.append(verdict)
    finally:
        runtime.close()

    jobs_per_task = 1 if arguments.reference_only else 2
    identity = {
        "bundle_identity_hash": catalog["bundle_identity_hash"],
        "dataset_content_hash": catalog["dataset_content_hash"],
        "accepted_vcs_version": catalog["accepted_vcs_version"],
        "corpus_task_count": len(references),
        "task_count": len(verdicts),
        "jobs_per_task": jobs_per_task,
        "selection": selection,
        "verdicts": verdicts,
    }
    receipt = {
        "schema_version": "1.0",
        "kind": "verilog_eval_vcs_mcp_qualification_v1",
        **identity,
        "qualification_identity_hash": content_hash(identity),
        "commercial_jobs": len(verdicts) * jobs_per_task,
        "model_calls": 0,
        "automatic_retries": 0,
        "passed": True,
    }
    _atomic_write_json(output, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
