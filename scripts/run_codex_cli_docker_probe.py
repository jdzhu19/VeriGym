#!/usr/bin/env python3
"""Execute exactly one commit-bound Docker Track B transport/runtime probe."""

from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from verigym.core.hashing import content_hash, hash_directory
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.orchestrator import VeriGym
from verigym.experiments.state import atomic_dump_json
from verigym.provenance import get_build_provenance
from verigym.registry.collections import build_registries


def _pilot_runner() -> ModuleType:
    path = Path(__file__).with_name("run_codex_cli_pilot.py").resolve(strict=True)
    spec = importlib.util.spec_from_file_location("verigym_docker_probe_pilot_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("pilot helper module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if os.environ.get("VERIGYM_RUN_CODEX_DOCKER_PROBE") != "1":
        raise SystemExit("VERIGYM_RUN_CODEX_DOCKER_PROBE=1 is required")
    output_name = os.environ.get("VERIGYM_CODEX_DOCKER_PROBE_OUTPUT")
    if not output_name:
        raise SystemExit("VERIGYM_CODEX_DOCKER_PROBE_OUTPUT is required")
    output = Path(output_name).expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit(f"probe output already exists: {output}")
    output.mkdir(parents=True)
    runs_root = output / "runs"
    runs_root.mkdir()
    evidence_root = output / "evidence"
    evidence_root.mkdir()

    runner = _pilot_runner()
    config = runner._load_yaml(
        Path("examples/experiments/codex-cli-verilog-eval-pilot.yaml"),
        required_keys=runner._REQUIRED_CONFIG_KEYS,
    )
    runner._validate_static_config(config)
    model_id = runner._required_environment("VERIGYM_CODEX_MODEL")
    if model_id != runner._EXPECTED_MODEL:
        raise SystemExit("probe model differs from the authorized exact model")
    capability = runner._load_capability()
    runner._validate_capability_identity(capability)
    auth_identity = runner._authentication_preflight()
    package_identities = runner._package_identities()
    docker_config = runner._docker_runtime_config(max_process_time_s=300)
    registries = build_registries()
    runner._verify_plugin_origins(registries)
    service = VeriGym(registries)
    source_config, source_snapshot, task_records = runner._freeze_source(
        service,
        config,
        Path(runner._required_environment("VERIGYM_VERILOG_EVAL_ROOT")),
    )
    runtime_identity, toolchain_identity, references = runner._docker_preflight(
        service,
        docker_config=docker_config,
        source_config=source_config,
        task_records=task_records,
    )
    provenance = get_build_provenance()
    item = {
        "plan_index": 0,
        "plan_item_id": "codex-docker-track-b-probe-Prob014_andgate",
        "run_id": "codex-docker-track-b-probe-Prob014_andgate",
        "track": "codex_cli_external_agent",
        "task_id": task_records[0]["id"],
        "task_hash": task_records[0]["task_hash"],
        "source_hash": task_records[0]["source_hash"],
        "base_seed": 0,
        "sample_index": 0,
        "child_seed": 0,
        "retry_count": 0,
        "best_of_k": None,
    }
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "campaign_kind": "docker_track_b_single_probe",
        "experiment_id": f"codex-docker-probe-{content_hash(item)[:16]}",
        "created_from_clean_commit": provenance.source_commit,
        "verigym_commit": provenance.source_commit,
        "verigym_source_tree_hash": provenance.source_tree_hash,
        "verigym_source_dirty": provenance.dirty,
        "requested_model_id": model_id,
        "reasoning_effort": "xhigh",
        "timeout_s": 300,
        "retry_count": 0,
        "resume": False,
        "fallback": False,
        "api_key": False,
        "candidate_repair": False,
        "best_of_n": False,
        "capability_identity": capability,
        "authentication_identity": auth_identity,
        "package_identities": package_identities,
        "runtime_identity": runtime_identity,
        "proxy_identity": runner._proxy_identity(),
        "toolchain_identity": toolchain_identity,
        "reference_preflight": references,
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "item": item,
    }
    plan_path = output / "probe-plan.json"
    atomic_dump_json(plan_path, plan)
    plan_bytes = plan_path.read_bytes()
    runner._require_reference_compatible_toolchain(toolchain_identity)
    runner._require_clean_frozen_source(plan)
    if runner._proxy_identity() != plan["proxy_identity"]:
        raise SystemExit("proxy environment-name identity changed before the probe")

    launch = {
        "schema_version": "1.0",
        "authorized_process_ordinal": 1,
        "model_bearing_process_limit": 1,
        "item": item,
        "retry_count": 0,
        "resume": False,
    }
    atomic_dump_json(evidence_root / "process-authorization.json", launch)
    started = time.monotonic()
    result = None
    execution: dict[str, Any]
    try:
        result = service.run(
            runner._run_config(
                item,
                model_id=model_id,
                output=runs_root,
                source_config=source_config,
                source_snapshot=source_snapshot,
                task_records=task_records,
                experiment_id=plan["experiment_id"],
                max_process_time_s=300,
                docker_config=docker_config,
            )
        )
        execution = runner._terminal_execution_record(
            item,
            result,
            output=output,
            wall_time_s=time.monotonic() - started,
        )
    except Exception as exc:
        execution = {
            "plan_index": 0,
            "run_id": item["run_id"],
            "launched": True,
            "terminal": False,
            "evaluable": False,
            "infrastructure_error": True,
            "error_category": type(exc).__name__,
            "message": str(exc)[:1024],
            "wall_time_s": time.monotonic() - started,
        }
    atomic_dump_json(evidence_root / "execution.json", execution)

    if result is None:
        shared = str(execution.get("error_category", ""))
        status = "BLOCKED" if "auth" in shared.lower() or "docker" in shared.lower() else "FAIL"
        acceptance = {
            "schema_version": "1.0",
            "status": status,
            "checks": {"terminal": False},
            "execution": execution,
            "model_processes_launched": 1,
            "retries": 0,
        }
        atomic_dump_json(evidence_root / "probe-acceptance.json", acceptance)
        print(json.dumps(acceptance, indent=2, sort_keys=True))
        return 1

    candidate_before = hash_directory(result.run_dir / "candidate")
    replay = runner._replay_without_codex([result])[0]
    candidate_after = hash_directory(result.run_dir / "candidate")
    source_integrity = runner._source_integrity(plan)
    security = runner._security_scans(
        [result],
        output=output,
        source_root=Path(source_config.source_root),
    )
    integrity = verify_artifact_manifest(result.run_dir, expected_scope="run")
    identity = result.manifest.external_agent_observations[-1]
    checks = {
        "plan_immutable": plan_path.read_bytes() == plan_bytes,
        "one_terminal_process": execution.get("terminal") is True
        and identity.invocation_count == 1,
        "track_b": identity.integration_track == "codex_cli_external_agent",
        "docker_runtime_backend": execution.get("runtime_process_backend")
        == "docker_outer_runtime_delegated",
        "docker_security_complete": execution.get("runtime_security_complete") is True,
        "evaluable": execution.get("evaluable") is True,
        "candidate_frozen": candidate_before == candidate_after,
        "replay_zero_call": replay.get("success") is True
        and replay.get("codex_cli_process_count") == 0
        and replay.get("broker_process_count") == 0
        and replay.get("model_call_count") == 0,
        "security_scans": security["all_passed"],
        "source_immutable": source_integrity["passed"],
        "artifact_integrity": integrity.status == "verified",
        "references_5_of_5": references["passed_count"] == 5,
    }
    acceptance = {
        "schema_version": "1.0",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "candidate_correctness_required": False,
        "execution": execution,
        "replay": replay,
        "security_scans": security,
        "source_integrity": source_integrity,
        "artifact_integrity": integrity.model_dump(mode="json"),
        "model_processes_launched": 1,
        "retries": 0,
    }
    atomic_dump_json(evidence_root / "probe-acceptance.json", acceptance)
    print(json.dumps(acceptance, indent=2, sort_keys=True))
    return 0 if acceptance["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
