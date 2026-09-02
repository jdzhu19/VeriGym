#!/usr/bin/env python3
"""Qualify frozen RTLLM PPA3 or PPA47 OpenSTA and DC L3/L4 partitions."""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_smoke as smoke
from verigym_rtllm.adapter import (
    PPA47_TASK_IDENTITIES_SHA256,
    PPA47_VARIANT,
    PPA_DIAGNOSTIC3_TASK_IDENTITIES_SHA256,
    PPA_DIAGNOSTIC3_VARIANT,
)
from verigym_rtllm.manifest import PPA_DIAGNOSTIC3_TASK_NAMES, TASK_MANIFESTS
from verigym_rtllm.ppa import PPA47_BINDINGS_SHA256, PPA47_TASK_NAMES, PPA_TASK_BINDINGS

from verigym.core.agent_feedback import (
    AgentFeedbackController,
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.episode import BudgetTracker, TerminationReason
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.core.scoring import build_scorecard
from verigym.core.synthesis import execute_synthesis_quality
from verigym.core.synthesis_projection import resolve_synthesis_source_projection
from verigym.experiments.private_staging import PrivateQualificationStaging
from verigym.experiments.state import atomic_dump_json
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.schemas.common import ToolchainProfileRef
from verigym.schemas.runtime import SessionSpec, WorkspaceDiff
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.tool import CommandSpec
from verigym.schemas.verifier import VerifierResult, VerifierStatus
from verigym.tools.base import SynthesisBackendPlugin

_FORMAT_ID = "rtllm_ppa3_dual_backend_qualification_v1"
_EXPECTED_IMAGE_ID = "sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1"
_BACKENDS = {"open": "yosys.synth", "commercial": "synopsys.dc.mcp"}
_BATCH_RUNNER = r"""from __future__ import annotations

import json
import subprocess
from pathlib import Path

root = Path("/workspace")
records = json.loads((root / "qualification.json").read_text(encoding="utf-8"))
issues = []
counts = {"public": 0, "hidden": 0}
for record in records:
    case_root = root / record["relative_root"]
    for kind in ("public", "hidden"):
        counts[kind] += 1
        source = "public-smoke.sv" if kind == "public" else "hidden-testbench.v"
        top = "public_smoke" if kind == "public" else record["hidden_top"]
        executable = root / ".verigym_internal" / f"{record['case']}-{kind}.vvp"
        completed = subprocess.run(
            ["iverilog", "-g2012", "-s", top, "-o", str(executable), record["candidate"], source],
            cwd=case_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = completed.stdout + completed.stderr
        if completed.returncode == 0:
            executed = subprocess.run(
                ["vvp", str(executable)],
                cwd=case_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = executed.stdout + executed.stderr
            pass_marker = record["public_pass"] if kind == "public" else record["hidden_pass"]
            fail_marker = "VERIGYM_PUBLIC_FAIL" if kind == "public" else record["hidden_fail"]
            passed = (
                executed.returncode == 0
                and pass_marker in output
                and (not fail_marker or fail_marker not in output)
            )
        else:
            passed = False
        if passed != record["expected"]:
            issues.append({"case": record["case"], "kind": kind, "passed": passed})
if issues:
    print(json.dumps({"counts": counts, "issues": issues}, sort_keys=True))
    raise SystemExit(1)
print(f"RTLLM_PPA_FUNCTIONAL_PASS public={counts['public']} hidden={counts['hidden']}")
"""


@dataclass(frozen=True)
class QualificationCatalog:
    name: str
    variant: str
    task_names: tuple[str, ...]
    task_identities_sha256: str
    conformance_cases_per_task: int


_CATALOGS = {
    "ppa3": QualificationCatalog(
        name="ppa3",
        variant=PPA_DIAGNOSTIC3_VARIANT,
        task_names=PPA_DIAGNOSTIC3_TASK_NAMES,
        task_identities_sha256=PPA_DIAGNOSTIC3_TASK_IDENTITIES_SHA256,
        conformance_cases_per_task=5,
    ),
    "ppa47": QualificationCatalog(
        name="ppa47",
        variant=PPA47_VARIANT,
        task_names=PPA47_TASK_NAMES,
        task_identities_sha256=PPA47_TASK_IDENTITIES_SHA256,
        conformance_cases_per_task=13,
    ),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--image", default=smoke._IMAGE)
    parser.add_argument("--catalog", choices=sorted(_CATALOGS), default="ppa3")
    parser.add_argument(
        "--profile-root",
        type=Path,
        help="PPA47 profile root containing open/ and dc-client/ directories.",
    )
    parser.add_argument("--open-profile", action="append", default=[], metavar="TASK=PATH")
    parser.add_argument("--dc-profile", action="append", default=[], metavar="TASK=PATH")
    return parser


def _named_paths(
    values: list[str],
    label: str,
    task_names: tuple[str, ...] = PPA_DIAGNOSTIC3_TASK_NAMES,
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or name not in task_names or name in paths:
            raise ConfigurationError(f"{label} requires one unique TASK=PATH per selected task")
        path = Path(raw).expanduser().resolve(strict=True)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ConfigurationError(f"{label} must reference small regular profile files")
        paths[name] = path
    if set(paths) != set(task_names):
        raise ConfigurationError(f"{label} must cover exactly the selected PPA tasks")
    return paths


def _new_directory(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.is_absolute() or os.path.lexists(resolved):
        raise ConfigurationError(f"{label} must be a new absolute path")
    resolved.mkdir(mode=0o700, parents=False)
    os.chmod(resolved, 0o700)
    return resolved


def _new_output(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if os.path.lexists(resolved) or not resolved.parent.is_dir():
        raise ConfigurationError("output must be a new file under an existing directory")
    return resolved


def _profile_root_paths(
    root: Path, task_names: tuple[str, ...]
) -> tuple[dict[str, Path], dict[str, Path]]:
    resolved = root.expanduser().resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_dir():
        raise ConfigurationError("PPA47 profile root must be a real directory")
    open_paths = {
        name: (resolved / "open" / f"{name}.yaml").resolve(strict=True) for name in task_names
    }
    dc_paths = {
        name: (resolved / "dc-client" / f"{name}.yaml").resolve(strict=True) for name in task_names
    }
    paths = (*open_paths.values(), *dc_paths.values())
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ConfigurationError("PPA47 profile root does not contain every task profile")
    return open_paths, dc_paths


def _load_tasks(
    service: VeriGym, source: Path, catalog: QualificationCatalog
) -> dict[str, tuple[Any, Any, Any]]:
    config = SuiteSourceConfig(source_root=source, variant=catalog.variant)
    loaded: dict[str, tuple[Any, Any, Any]] = {}
    identities: dict[str, str] = {}
    for name in catalog.task_names:
        task_id = f"rtllm/{catalog.variant}/{name}"
        suite, task, assets = service.load_task(task_id, config)
        if (
            task.metadata.get("gym_qualification_level") != "L4_correctness_gated_final_ppa"
            or task.metadata.get("agent_eval", {}).get("ppa_supported") is not True
            or task.scoring.ppa_enabled is not True
            or task.metadata.get("diagnostic_only") is not True
            or task.metadata.get("benchmark_score_claimed") is not False
            or len(assets.read_only_mounts) != 1
        ):
            raise ConfigurationError(f"PPA task contract is invalid for {task_id}")
        loaded[name] = (suite, task, assets)
        identities[name] = content_hash(task)
    if content_hash(identities) != catalog.task_identities_sha256:
        raise ConfigurationError("PPA task identities differ from the frozen aggregate")
    return loaded


def _qualify_functional(
    loaded: dict[str, tuple[Any, Any, Any]],
    runtime: Any,
    staging: PrivateQualificationStaging,
    catalog: QualificationCatalog,
) -> dict[str, Any]:
    records: list[dict[str, object]] = []
    for name, (suite, _task, assets) in loaded.items():
        hidden = {asset.mount_path: asset.content for asset in assets.hidden_assets}
        cases = [case for case in suite.conformance_cases() if case.name.startswith(f"{name}-")]
        if len(cases) != catalog.conformance_cases_per_task:
            raise ConfigurationError(f"functional control matrix drifted for {name}")
        manifest = TASK_MANIFESTS[name]
        for case in cases:
            relative_root = Path("functional") / name / case.name.removeprefix(f"{name}-")
            staging.write_text(
                relative_root / f"{name}.v", case.candidate.files[f"repository/rtl/{name}.v"]
            )
            staging.write_text(relative_root / "public-smoke.sv", suite._public_smoke(name))
            staging.write_text(
                relative_root / "hidden-testbench.v", hidden["verifier/testbench.v"] or ""
            )
            for mount_path, content in hidden.items():
                if mount_path != "verifier/testbench.v":
                    staging.write_text(relative_root / mount_path, content or "")
            records.append(
                {
                    "case": case.name,
                    "relative_root": relative_root.as_posix(),
                    "candidate": f"{name}.v",
                    "hidden_top": manifest.testbench_top,
                    "hidden_pass": manifest.pass_marker,
                    "hidden_fail": manifest.fail_marker,
                    "public_pass": (
                        "PUBLIC_SMOKE_PASS"
                        if name in {"counter_12", "up_down_counter"}
                        else "VERIGYM_PUBLIC_PASS"
                    ),
                    "expected": case.expected_resolved,
                }
            )
    staging.write_json("qualification.json", records)
    staging.write_text("qualification.py", _BATCH_RUNNER)
    session = runtime.create_session(
        SessionSpec(source_dir=str(staging.root), label="verifier", max_output_bytes=1_000_000)
    )
    try:
        completed = session.execute(
            CommandSpec(argv=["python3", "qualification.py"], timeout_s=900)
        )
    finally:
        session.close()
    expected = len(catalog.task_names) * catalog.conformance_cases_per_task
    marker = f"RTLLM_PPA_FUNCTIONAL_PASS public={expected} hidden={expected}"
    if completed.exit_code != 0 or marker not in completed.stdout:
        raise ConfigurationError("PPA functional qualification failed")
    return {
        "passed": True,
        "public_cases": expected,
        "hidden_cases": expected,
        "model_calls": 0,
    }


def _resolve_profile(
    *, profile: Any, runtime: Any, suite: Any, task: Any, backend: SynthesisBackendPlugin
) -> Any:
    if profile.flow is None:
        raise ConfigurationError("PPA profile lacks a synthesis flow")
    projection = resolve_synthesis_source_projection(task)
    reference = suite.reference_solution(task)
    if reference is None:
        raise ConfigurationError("PPA qualification requires a reference solution")
    arguments = {
        "source_paths": projection.profile_sources,
        "top_module": profile.flow.top_module,
        "reference_candidate_hash": content_hash(reference),
        "backend": backend,
        "synthesis_source_projection_hash": projection.projection_hash,
    }
    first = resolve_toolchain_profile(profile, runtime, **arguments)
    return resolve_toolchain_profile(profile, runtime, expected=first, **arguments)


def _validate_metric_contract(metrics: Any) -> None:
    positive_finite = (
        metrics.mapped_area_raw,
        metrics.critical_path_delay_raw,
        metrics.total_power_raw,
    )
    if (
        metrics.num_cells is None
        or metrics.num_cells <= 0
        or any(value is None or not math.isfinite(value) or value <= 0 for value in positive_finite)
        or metrics.worst_negative_slack_raw is None
        or not math.isfinite(metrics.worst_negative_slack_raw)
    ):
        raise ConfigurationError("PPA metrics lack positive finite area/cells/delay/power or WNS")


def _metric_shape(metrics: Any) -> dict[str, Any]:
    return {
        "area_present": metrics.mapped_area_raw is not None,
        "area_unit": metrics.mapped_area_unit,
        "delay_present": metrics.critical_path_delay_raw is not None,
        "wns_present": metrics.worst_negative_slack_raw is not None,
        "timing_unit": metrics.timing_unit,
        "power_present": metrics.total_power_raw is not None,
        "power_unit": metrics.power_unit,
        "synthesis_ok": metrics.synthesis_ok,
    }


def _qualify_profile(
    *,
    suite: Any,
    task: Any,
    assets: Any,
    runtime: Any,
    profile: Any,
    backend: SynthesisBackendPlugin,
    resolved: Any,
    staging: PrivateQualificationStaging,
    label: str,
) -> dict[str, Any]:
    reference = suite.reference_solution(task)
    assert reference is not None
    rejected = execute_synthesis_quality(
        suite=suite,
        task=task,
        candidate_dir=staging.root,
        runtime=runtime,
        profile=profile,
        resolved=resolved,
        artifact_root=staging.root / "synthesis" / label / "rejected-artifacts",
        plugin=backend,
        correctness_passed=False,
    )
    if (
        [item.status for item in rejected.results]
        != [VerifierStatus.SKIPPED, VerifierStatus.SKIPPED, VerifierStatus.SKIPPED]
        or rejected.candidate.synthesis_ok
        or rejected.reference.synthesis_ok
    ):
        raise ConfigurationError(f"functional rejection did not skip PPA for {label}")
    contract = resolve_agent_feedback_contract(
        task=task,
        ppa_enabled=True,
        ppa_max_executions=1,
        resolved_profile=resolved,
        profile_backend=profile.flow.backend_plugin,
    )
    if contract is None:
        raise ConfigurationError("candidate-only PPA feedback contract is unavailable")
    controller = AgentFeedbackController(
        contract=contract,
        task=task_with_agent_feedback_contract(task, contract),
        runtime=runtime,
        profile=profile,
        resolved_profile=resolved,
        backend=backend,
    )
    session = runtime.create_session(
        SessionSpec(
            source_dir=assets.visible_root,
            label="agent",
            max_output_bytes=task.budget.max_output_bytes_per_tool,
            read_only_mounts=assets.read_only_mounts,
        )
    )
    try:
        for relative, content in sorted(reference.files.items()):
            session.write_file(relative, content.encode("utf-8"))
        compile_result = controller.execute("compile", session)
        ppa_result = controller.execute("ppa", session)
    finally:
        session.close()
    evaluations = controller.evaluations
    if (
        compile_result.exit_code != 0
        or ppa_result.exit_code != 0
        or [item.test_id for item in evaluations] != ["compile", "ppa"]
        or not all(item.passed for item in evaluations)
        or evaluations[1].metrics is None
        or not evaluations[1].synthesis_executed
    ):
        typed = [
            {
                "test_id": item.test_id,
                "category": item.category,
                "passed": item.passed,
                "synthesis_executed": item.synthesis_executed,
                "metrics_present": item.metrics is not None,
            }
            for item in evaluations
        ]
        raise ConfigurationError(
            f"L3 candidate-only qualification failed for {label}: "
            f"compile_exit={compile_result.exit_code} ppa_exit={ppa_result.exit_code} "
            f"evaluations={typed}"
        )

    candidate_root = Path("synthesis") / label / "candidate"
    for relative, content in sorted(reference.files.items()):
        staging.write_text(candidate_root / relative, content)
    synthesis = execute_synthesis_quality(
        suite=suite,
        task=task,
        candidate_dir=staging.root / candidate_root,
        runtime=runtime,
        profile=profile,
        resolved=resolved,
        artifact_root=staging.root / "synthesis" / label / "artifacts",
        plugin=backend,
        correctness_passed=True,
    )
    if (
        [item.status for item in synthesis.results]
        != [VerifierStatus.PASSED, VerifierStatus.PASSED, VerifierStatus.PASSED]
        or not synthesis.candidate.synthesis_ok
        or not synthesis.reference.synthesis_ok
    ):
        raise ConfigurationError(f"L4 final synthesis qualification failed for {label}")
    _validate_metric_contract(synthesis.candidate)
    _validate_metric_contract(synthesis.reference)
    functional = VerifierResult(
        node_id="functional_hidden",
        plugin="iverilog.run",
        status=VerifierStatus.PASSED,
    )
    card = build_scorecard(
        run_id=f"qualification-{label}",
        task=task,
        results=[functional, *synthesis.results],
        diff=WorkspaceDiff(),
        tracker=BudgetTracker(task.budget),
        termination_reason=TerminationReason.FINAL_SUBMISSION,
        task_hash=content_hash(task),
        candidate_hash=content_hash(reference),
        run_config_hash="0" * 64,
        profile_refs=[
            ToolchainProfileRef(
                id=profile.id, version=profile.version, content_hash=content_hash(profile)
            )
        ],
        isolation_level="docker_standard",
        resolved_profile=resolved,
        candidate_synthesis=synthesis.candidate,
        reference_synthesis=synthesis.reference,
    )
    ppa = card.quality.ppa
    if not card.resolved or ppa is None or not ppa.eligible or ppa.ineligible_reasons:
        raise ConfigurationError(f"L4 PPA projection is ineligible for {label}")
    feedback_metrics = evaluations[1].metrics
    if not all(
        isinstance(value, int | float) and math.isfinite(value) and value > 0
        for value in (
            feedback_metrics.area,
            feedback_metrics.maximum_path_delay,
            feedback_metrics.power,
        )
    ) or not (
        isinstance(feedback_metrics.worst_negative_slack, int | float)
        and math.isfinite(feedback_metrics.worst_negative_slack)
    ):
        raise ConfigurationError(f"L3 feedback metrics are incomplete for {label}")
    return {
        "task_id": task.id,
        "profile_id": profile.id,
        "profile_version": profile.version,
        "profile_hash": content_hash(profile),
        "resolved_profile_hash": resolved.resolved_profile_hash,
        "backend_plugin": profile.flow.backend_plugin,
        "functional_rejection": {
            "ppa_skipped": True,
            "synthesis_jobs": 0,
        },
        "l3_candidate_feedback": {
            "passed": True,
            "synthesis_executed": True,
            "area_present": feedback_metrics.area is not None,
            "delay_present": feedback_metrics.maximum_path_delay is not None,
            "wns_present": feedback_metrics.worst_negative_slack is not None,
            "power_present": feedback_metrics.power is not None,
        },
        "l4_final_projection": {
            "passed": True,
            "ppa_eligible": True,
            "candidate": _metric_shape(synthesis.candidate),
            "reference": _metric_shape(synthesis.reference),
        },
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    catalog = _CATALOGS[arguments.catalog]
    output = _new_output(arguments.output)
    site_work = _new_directory(arguments.site_work, "site work")
    source = arguments.rtllm_source.expanduser().resolve(strict=True)
    if arguments.profile_root is not None:
        if catalog.name != "ppa47" or arguments.open_profile or arguments.dc_profile:
            raise ConfigurationError("--profile-root is exclusive to the PPA47 catalog")
        open_paths, dc_paths = _profile_root_paths(arguments.profile_root, catalog.task_names)
    else:
        open_paths = _named_paths(arguments.open_profile, "open profiles", catalog.task_names)
        dc_paths = _named_paths(arguments.dc_profile, "DC profiles", catalog.task_names)
    image_id = smoke._docker_image_id(arguments.image)
    if image_id != _EXPECTED_IMAGE_ID:
        raise ConfigurationError("PPA qualification image differs from the frozen identity")

    registries = smoke._registries()
    service = VeriGym(registries)
    loaded = _load_tasks(service, source, catalog)
    runtime = registries.runtimes.get("docker").configure(
        smoke._docker_config(arguments.image, image_id)
    )
    staging = PrivateQualificationStaging(site_work / "qualification-private")
    receipt: dict[str, object] | None = None
    try:
        runtime.prepare("rtllm-ppa3-dual-backend-qualification")
        image = runtime.descriptor.image
        if image is None or image.resolved_image_id != _EXPECTED_IMAGE_ID:
            raise ConfigurationError("prepared runtime image identity is invalid")
        with staging:
            functional = _qualify_functional(loaded, runtime, staging, catalog)
            records: list[dict[str, Any]] = []
            loader = ToolchainProfileRegistry()
            for name, (suite, task, assets) in loaded.items():
                for partition, paths in (("open", open_paths), ("commercial", dc_paths)):
                    profile = loader.load_file(paths[name])
                    if profile.flow is None or profile.flow.backend_plugin != _BACKENDS[partition]:
                        raise ConfigurationError(
                            f"{partition} profile backend is invalid for {name}"
                        )
                    if (
                        profile.flow.default_sources
                        != [
                            PPA_TASK_BINDINGS[name].source_path
                            if catalog.name == "ppa47"
                            else f"rtl/{name}.v"
                        ]
                        or profile.flow.top_module != TASK_MANIFESTS[name].synthesis_top
                    ):
                        raise ConfigurationError(
                            f"{partition} profile is not task-bound for {name}"
                        )
                    if partition == "commercial":
                        smoke._require_commercial_worker_release(profile)
                    plugin = registries.tools.get(profile.flow.backend_plugin)
                    if not isinstance(plugin, SynthesisBackendPlugin):
                        raise ConfigurationError("configured PPA backend is unavailable")
                    resolved = _resolve_profile(
                        profile=profile,
                        runtime=runtime,
                        suite=suite,
                        task=task,
                        backend=plugin,
                    )
                    record = _qualify_profile(
                        suite=suite,
                        task=task,
                        assets=assets,
                        runtime=runtime,
                        profile=profile,
                        backend=plugin,
                        resolved=resolved,
                        staging=staging,
                        label=f"{name}-{partition}",
                    )
                    record["partition"] = partition
                    records.append(record)
            receipt = staging.cleanup()
        runtime.close()
        cleanup = runtime.descriptor.cleanup
        if cleanup is None or not cleanup.complete:
            raise ConfigurationError("PPA qualification runtime cleanup is incomplete")
        if receipt is None or receipt.get("cleanup_complete") is not True:
            raise ConfigurationError("private PPA qualification cleanup is incomplete")
        payload = {
            "format_id": (
                "rtllm_ppa47_dual_backend_qualification_v1"
                if catalog.name == "ppa47"
                else _FORMAT_ID
            ),
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "model_calls": 0,
            "variant": catalog.variant,
            "task_names": list(catalog.task_names),
            "task_identities_sha256": catalog.task_identities_sha256,
            "ppa_bindings_sha256": (PPA47_BINDINGS_SHA256 if catalog.name == "ppa47" else None),
            "backend_partitions_comparable": False,
            "functional": functional,
            "profiles": records,
            "summary": {
                "tasks": len(catalog.task_names),
                "profiles": len(records),
                "synthesis_jobs": len(records) * 3,
                "automatic_retries": 0,
                "functional_rejection_skips": sum(
                    item["functional_rejection"]["ppa_skipped"] for item in records
                ),
                "l3_passed": sum(item["l3_candidate_feedback"]["passed"] for item in records),
                "l4_passed": sum(item["l4_final_projection"]["passed"] for item in records),
            },
            "private_staging_cleanup": receipt,
            "runtime_cleanup_complete": True,
            "image_id": image_id,
        }
        atomic_dump_json(output, payload)
    finally:
        if runtime.descriptor.cleanup is None:
            runtime.close()
        if staging.root.exists() and receipt is None:
            staging.cleanup()
    marker = "RTLLM_PPA47" if catalog.name == "ppa47" else "RTLLM_PPA3"
    print(f"{marker}_DUAL_BACKEND_PASS output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
