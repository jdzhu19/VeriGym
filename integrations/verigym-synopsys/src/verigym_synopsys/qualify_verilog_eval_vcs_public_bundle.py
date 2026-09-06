"""Zero-model qualification for VerilogEval public VCS/MCP compile profiles."""

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
from verigym.core.public_test_profiles import (
    PublicTestProfileController,
    resolve_public_test_profile,
)
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.registry.collections import build_registries
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.suite import SuiteSourceConfig
from verigym.suites.verilog_eval.adapter import VerilogEvalSuite
from verigym.suites.verilog_eval.schemas import VerilogEvalVariant

from .vcs_public_mcp_client import McpVcsPublicCompileTool

VARIANT = VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify every task in a VerilogEval public VCS/MCP profile bundle."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-only", action="store_true")
    parser.add_argument("--task", action="append", default=[])
    return parser


def _load_catalog(bundle_root: Path) -> dict[str, Any]:
    path = bundle_root / "catalog.json"
    if bundle_root.is_symlink() or path.is_symlink() or not path.is_file():
        raise ConfigurationError("VerilogEval public VCS/MCP bundle is unavailable")
    if (bundle_root / "INCOMPLETE").exists():
        raise ConfigurationError("VerilogEval public VCS/MCP bundle is incomplete")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("VerilogEval public VCS/MCP catalog is invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "verilog_eval_vcs_public_mcp_profile_bundle_v1"
        or payload.get("variant") != VARIANT
    ):
        raise ConfigurationError("unexpected VerilogEval public VCS/MCP bundle identity")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("task_count") != len(records):
        raise ConfigurationError("VerilogEval public VCS/MCP task count is invalid")
    identity = {
        "variant": payload.get("variant"),
        "dataset_content_hash": payload.get("dataset_content_hash"),
        "task_count": payload.get("task_count"),
        "accepted_vcs_version": payload.get("accepted_vcs_version"),
        "public_test_id": payload.get("public_test_id"),
        "profile_resolution_mode": payload.get("profile_resolution_mode"),
        "records": records,
    }
    if payload.get("bundle_identity_hash") != content_hash(identity):
        raise ConfigurationError("VerilogEval public VCS/MCP bundle identity changed")
    return payload


def _bundle_file(bundle_root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise ConfigurationError("public VCS/MCP bundle file reference must be a string")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ConfigurationError("public VCS/MCP bundle file reference is unsafe")
    path = bundle_root / relative
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("public VCS/MCP bundle file is unavailable")
    return path


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _run_compile(
    *,
    task: Any,
    controller: PublicTestProfileController,
    runtime: LocalRuntime,
    source: str,
    work_root: Path,
    label: str,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix=f"{label}-", dir=work_root) as temporary_value:
        staging = Path(temporary_value)
        path = staging / "repository/rtl/TopModule.sv"
        path.parent.mkdir(parents=True)
        path.write_text(source, encoding="utf-8")
        session = runtime.create_session(
            SessionSpec(
                source_dir=str(staging),
                label=f"public-vcs-qualification-{uuid.uuid4().hex[:12]}",
                max_output_bytes=1_000_000,
            )
        )
        try:
            completed = controller.execute("compile", session)
        finally:
            session.close()
    if completed.failure_origin == "control_plane":
        raise ConfigurationError("public VCS/MCP qualification hit infrastructure failure")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("public VCS/MCP qualification response is invalid") from exc
    category = payload.get("category") if isinstance(payload, dict) else None
    return completed.exit_code == 0, str(category)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
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
    suite = VerilogEvalSuite(
        SuiteSourceConfig(
            source_root=arguments.source_root,
            variant=VARIANT,
            strict_compatibility=True,
        )
    )
    snapshot = suite.source_snapshot()
    if snapshot is None or snapshot.dataset_content_hash != catalog["dataset_content_hash"]:
        raise ConfigurationError("VerilogEval source differs from the public VCS/MCP bundle")
    references = {reference.native_id: reference for reference in suite.discover()}
    records = catalog["records"]
    if not all(isinstance(record, dict) for record in records):
        raise ConfigurationError("public VCS/MCP bundle records are invalid")
    by_native = {str(record.get("native_id")): record for record in records}
    if set(references) != set(by_native):
        raise ConfigurationError("VerilogEval task set differs from the public bundle")
    selected = sorted(references)
    if arguments.task:
        if len(arguments.task) != len(set(arguments.task)) or not set(arguments.task).issubset(
            references
        ):
            raise ConfigurationError("qualification task selection is duplicate or unknown")
        selected = sorted(arguments.task)
    registries = build_registries(discover_external=False)
    plugin = McpVcsPublicCompileTool()
    registries.tools.register(plugin)
    runtime = LocalRuntime()
    runtime.prepare("verilog-eval-vcs-public-mcp-qualification-v1")
    verdicts: list[dict[str, object]] = []
    try:
        for native_id in selected:
            record = by_native[native_id]
            task = suite.load_task(references[native_id])
            if task.id != record.get("task_id") or content_hash(task) != record.get("task_hash"):
                raise ConfigurationError("VerilogEval task identity differs from the public bundle")
            profile = load_verifier_profile(_bundle_file(bundle_root, record.get("client_profile")))
            if content_hash(profile) != record.get("client_declared_profile_hash"):
                raise ConfigurationError("public VCS/MCP client profile identity changed")
            resolved = resolve_public_test_profile(
                task=task,
                profile=profile,
                tools=registries.tools,
            )
            if resolved.resolved_profile_hash != record.get(
                "client_resolved_profile_hash"
            ) or resolved.server_resolved_profile_hash != record.get(
                "server_resolved_profile_hash"
            ):
                raise ConfigurationError("public VCS/MCP resolved identity changed")
            controller = PublicTestProfileController(
                task=task,
                profile=profile,
                resolved_profile=resolved,
                backend=plugin,
            )
            reference = suite.reference_solution(task)
            if reference is None:
                raise ConfigurationError("VerilogEval reference candidate is unavailable")
            source = reference.files["repository/rtl/TopModule.sv"]
            reference_passed, reference_category = _run_compile(
                task=task,
                controller=controller,
                runtime=runtime,
                source=source,
                work_root=work_root,
                label=f"{native_id}-reference",
            )
            if not reference_passed:
                raise ConfigurationError(f"public VCS/MCP rejected reference {native_id}")
            verdict: dict[str, object] = {
                "native_id": native_id,
                "task_id": task.id,
                "task_hash": content_hash(task),
                "client_declared_profile_hash": content_hash(profile),
                "client_resolved_profile_hash": resolved.resolved_profile_hash,
                "server_resolved_profile_hash": resolved.server_resolved_profile_hash,
                "reference_passed": True,
                "reference_category": reference_category,
            }
            if not arguments.reference_only:
                bad_passed, bad_category = _run_compile(
                    task=task,
                    controller=controller,
                    runtime=runtime,
                    source="module TopModule( ; endmodule\n",
                    work_root=work_root,
                    label=f"{native_id}-known-bad",
                )
                if bad_passed or bad_category != "compile_failed":
                    raise ConfigurationError(f"public VCS/MCP accepted known-bad {native_id}")
                verdict.update({"known_bad_rejected": True, "known_bad_category": bad_category})
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
        "selection": {"kind": "explicit" if arguments.task else "all", "tasks": selected},
        "verdicts": verdicts,
    }
    receipt = {
        "schema_version": "1.0",
        "kind": "verilog_eval_vcs_public_mcp_qualification_v1",
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
