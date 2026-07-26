#!/usr/bin/env python3
"""Freeze, and only when explicitly budgeted execute, the 30-run Codex CLI pilot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from verigym.core.hashing import content_hash, hash_directory
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.core.sampling import compute_pass_at_k
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl, atomic_write_text
from verigym.provenance import get_build_provenance
from verigym.registry.collections import build_registries
from verigym.reporting.service import ReportService
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunResult
from verigym.schemas.runtime import (
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
)
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus

_EXPECTED_PACKAGE = "verigym-codex-cli"
_EXPECTED_MODEL = "gpt-5.4"
_EXPECTED_CODEX_VERSION = "codex-cli 0.144.6"
_EXPECTED_HOST_CODEX_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
_EXPECTED_AGENT_CODEX_SHA256 = "a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15"
_EXPECTED_AUTH_SEMANTIC_ID = "codex.auth.inherited_chatgpt_session.v1"
_PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
_REQUIRED_CONFIG_KEYS = {
    "schema_version",
    "name",
    "description",
    "suite",
    "tasks",
    "tracks",
    "sampling",
    "execution",
    "guard",
}
_REQUIRED_BUDGET_KEYS = {
    "schema_version",
    "max_planned_runs",
    "max_codex_processes",
    "max_total_wall_time_s",
    "max_failed_infrastructure_runs",
    "allow_retry",
    "allow_best_of_k_selection",
}
_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]{8,}|\bsk-[A-Za-z0-9_-]{12,}|"
    r"(token|secret|password|credential)[\"'=:\s]+[^\s,\"'}]+)"
)


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _unique_mapping(
    loader: _UniqueSafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError("pilot YAML mappings require string keys")
        if key in result:
            raise ValueError(f"duplicate pilot YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _unique_mapping,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("examples/experiments/codex-cli-verilog-eval-pilot.yaml"),
    )
    parser.add_argument("--plan-output", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    config = _load_yaml(arguments.config, required_keys=_REQUIRED_CONFIG_KEYS)
    _validate_static_config(config)
    model_id = _required_environment("VERIGYM_CODEX_MODEL")
    if model_id != _EXPECTED_MODEL:
        raise SystemExit(f"the Docker-backed pilot requires exact model {_EXPECTED_MODEL}")
    _required_environment("VERIGYM_CODEX_BINARY")
    _required_environment("VERIGYM_CODEX_AUTH_MODE")
    capability = _load_capability()
    _validate_capability_identity(capability)
    auth_identity = _authentication_preflight()
    package_identities = _package_identities()
    docker_config = _docker_runtime_config(
        max_process_time_s=config["execution"]["max_process_time_s"]
    )
    source_root = Path(_required_environment("VERIGYM_VERILOG_EVAL_ROOT"))
    registries = build_registries()
    _verify_plugin_origins(registries)
    service = VeriGym(registries)
    source_config, source_snapshot, task_records = _freeze_source(
        service,
        config,
        source_root,
    )
    runtime_identity, toolchain_identity, reference_preflight = _docker_preflight(
        service,
        docker_config=docker_config,
        source_config=source_config,
        task_records=task_records,
    )
    plan = _build_plan(
        config,
        model_id=model_id,
        capability=capability,
        source_snapshot=source_snapshot,
        task_records=task_records,
        registries=registries,
        toolchain_identity=toolchain_identity,
        auth_identity=auth_identity,
        package_identities=package_identities,
        runtime_identity=runtime_identity,
        reference_preflight=reference_preflight,
    )
    plan_path = arguments.plan_output.expanduser().resolve()
    if plan_path.exists() or plan_path.is_symlink():
        raise SystemExit(f"pilot plan output already exists: {plan_path}")
    atomic_dump_json(plan_path, plan)
    plan_bytes = plan_path.read_bytes()

    opted_in = os.environ.get("VERIGYM_RUN_CODEX_PILOT") == "1"
    budget_name = os.environ.get("VERIGYM_CODEX_PILOT_BUDGET")
    if not opted_in or not budget_name:
        print(
            json.dumps(
                {
                    "status": "plan_only",
                    "plan": str(plan_path),
                    "plan_hash": content_hash(plan),
                    "planned_runs": 30,
                    "model_calls": 0,
                    "run_directories_created": 0,
                    "reason": (
                        "pilot opt-in absent" if not opted_in else "explicit pilot budget absent"
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    budget = _load_budget(Path(budget_name), config)
    _require_reference_compatible_toolchain(toolchain_identity)
    _require_clean_frozen_source(plan)
    if arguments.output is None:
        raise SystemExit("--output is required when the pilot execution guard is complete")
    output = arguments.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit(f"pilot output already exists: {output}")
    output.mkdir(parents=True)
    runs_root = output / "runs"
    runs_root.mkdir()
    evidence_root = output / "evidence"
    evidence_root.mkdir()
    reports_root = output / "reports"

    started = time.monotonic()
    results: list[RunResult] = []
    execution_records: list[dict[str, Any]] = []
    launch_records: list[dict[str, Any]] = []
    process_attempts = 0
    stop_reason: str | None = None
    launch_ledger = evidence_root / "process_authorizations.jsonl"
    execution_ledger = evidence_root / "execution_results.jsonl"
    _create_append_only_ledger(launch_ledger)
    _create_append_only_ledger(execution_ledger)
    for item in plan["items"]:
        elapsed = time.monotonic() - started
        if stop_reason is None and _proxy_identity() != plan["proxy_identity"]:
            stop_reason = "identity_mutation:proxy_environment_names"
        if stop_reason is None and elapsed >= budget["max_total_wall_time_s"]:
            stop_reason = "global_wall_time_limit"
        if stop_reason is None and process_attempts >= budget["max_codex_processes"]:
            stop_reason = "global_process_limit"
        if stop_reason is not None:
            record = {
                "plan_index": item["plan_index"],
                "plan_item_id": item["plan_item_id"],
                "run_id": item["run_id"],
                "track": item["track"],
                "task_id": item["task_id"],
                "sample_index": item["sample_index"],
                "launched": False,
                "terminal": False,
                "infrastructure_error": True,
                "error_category": stop_reason,
            }
            execution_records.append(record)
            _append_jsonl_record(execution_ledger, record)
            continue
        process_attempts += 1
        authorization = {
            "schema_version": "1.0",
            "plan_index": item["plan_index"],
            "plan_item_id": item["plan_item_id"],
            "run_id": item["run_id"],
            "track": item["track"],
            "task_id": item["task_id"],
            "sample_index": item["sample_index"],
            "authorized_process_ordinal": process_attempts,
            "retry_count": 0,
            "resume": False,
            "model_id": model_id,
            "reasoning_effort": "xhigh",
            "effective_timeout_s": config["execution"]["max_process_time_s"],
        }
        launch_records.append(authorization)
        _append_jsonl_record(launch_ledger, authorization)
        run_config = _run_config(
            item,
            model_id=model_id,
            output=runs_root,
            source_config=source_config,
            source_snapshot=source_snapshot,
            task_records=task_records,
            experiment_id=plan["experiment_id"],
            max_process_time_s=config["execution"]["max_process_time_s"],
            docker_config=docker_config,
        )
        run_started = time.monotonic()
        try:
            result = service.run(run_config)
            results.append(result)
            record = _terminal_execution_record(
                item,
                result,
                output=output,
                wall_time_s=time.monotonic() - run_started,
            )
            execution_records.append(record)
            _append_jsonl_record(execution_ledger, record)
            shared_failure = _shared_external_prerequisite_failure(result)
            if shared_failure is not None:
                stop_reason = shared_failure
            elif _actual_security_breach(result):
                stop_reason = "actual_security_breach"
        except Exception as exc:
            record = {
                "plan_index": item["plan_index"],
                "plan_item_id": item["plan_item_id"],
                "run_id": item["run_id"],
                "track": item["track"],
                "task_id": item["task_id"],
                "sample_index": item["sample_index"],
                "launched": True,
                "terminal": False,
                "infrastructure_error": True,
                "error_category": type(exc).__name__,
                "message": str(exc)[:1024],
                "wall_time_s": time.monotonic() - run_started,
            }
            execution_records.append(record)
            _append_jsonl_record(execution_ledger, record)
    _validate_execution_ledgers(
        plan,
        launch_records=launch_records,
        execution_records=execution_records,
        max_processes=budget["max_codex_processes"],
    )
    plan_unchanged = plan_path.read_bytes() == plan_bytes
    candidate_hashes_before_replay = {
        result.manifest.run_id: hash_directory(result.run_dir / "candidate") for result in results
    }
    replay_records = _replay_without_codex(results)
    atomic_dump_jsonl(evidence_root / "replay_results.jsonl", replay_records)
    candidate_freeze = _candidate_freeze_evidence(results, candidate_hashes_before_replay)
    atomic_dump_json(evidence_root / "candidate_freeze.json", candidate_freeze)
    source_integrity = _source_integrity(plan)
    atomic_dump_json(evidence_root / "source_integrity.json", source_integrity)
    security_scans = _security_scans(results, output=output, source_root=source_root)
    atomic_dump_json(evidence_root / "security_scans.json", security_scans)
    reports = ReportService().generate_all(
        runs_root,
        output_dir=reports_root,
        group_by=(
            "task",
            "integration_track",
            "base_seed",
            "requested_model_id",
            "cli_version",
            "capability_fingerprint",
        ),
    )
    pilot_report = _pilot_report(
        plan,
        results,
        execution_records,
        replay_records,
        elapsed_s=time.monotonic() - started,
        global_wall_time_limit_s=budget["max_total_wall_time_s"],
        report_coverage=reports.aggregate.coverage.model_dump(mode="json"),
        process_attempts=process_attempts,
        plan_unchanged=plan_unchanged,
        candidate_freeze=candidate_freeze,
        source_integrity=source_integrity,
        security_scans=security_scans,
    )
    atomic_dump_json(evidence_root / "pilot_results.json", pilot_report)
    _write_pilot_reports(pilot_report, reports_root)
    print(json.dumps(pilot_report, indent=2, sort_keys=True))
    return 0 if pilot_report["experiment_execution_gate"]["status"] == "PASS" else 1


def _validate_capability_identity(capability: dict[str, Any]) -> None:
    if (
        capability.get("version_output") != _EXPECTED_CODEX_VERSION
        or capability.get("executable_sha256") != _EXPECTED_HOST_CODEX_SHA256
        or capability.get("model_call_count") != 0
    ):
        raise SystemExit("Codex capability identity differs from the authorized CLI 0.144.6")


def _authentication_preflight() -> dict[str, Any]:
    from verigym_codex_cli.preflight import run_auth_preflight

    _require_no_api_key_environment()
    result = run_auth_preflight()
    safe = result.safe_dict()
    if (
        result.status != "pass"
        or result.requested_auth_mode != "chatgpt_cli_session"
        or result.resolved_auth_mode != "inherited_codex_login"
        or result.auth_semantic_id != _EXPECTED_AUTH_SEMANTIC_ID
        or result.model_calls != 0
        or result.login_processes != 0
        or result.logout_processes != 0
        or result.account_switch_processes != 0
        or result.credential_contents_accessed_by_verigym
        or result.credential_files_copied != 0
    ):
        raise SystemExit("existing ChatGPT CLI authentication did not pass zero-call preflight")
    return safe


def _require_no_api_key_environment() -> None:
    forbidden = (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "VERIGYM_CODEX_CREDENTIAL_ENV",
    )
    present = [name for name in forbidden if name in os.environ]
    if present:
        raise SystemExit(
            "ChatGPT CLI-session execution forbids API-key environment configuration: "
            + ", ".join(present)
        )


def _package_identities() -> dict[str, Any]:
    identities: dict[str, Any] = {}
    for label, environment, expected_prefix in (
        ("core", "VERIGYM_CORE_WHEEL", "verigym-0.1.0-"),
        (
            "codex_cli_plugin",
            "VERIGYM_CODEX_PLUGIN_WHEEL",
            "verigym_codex_cli-0.1.0-",
        ),
    ):
        path = Path(_required_environment(environment)).expanduser().resolve(strict=True)
        metadata = os.lstat(path)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > 256 * 1024 * 1024
            or not path.name.startswith(expected_prefix)
            or path.suffix != ".whl"
        ):
            raise SystemExit(f"{environment} does not identify a safe expected wheel")
        identities[label] = {
            "filename": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": metadata.st_size,
        }
    return identities


def _docker_runtime_config(*, max_process_time_s: int) -> DockerRuntimeConfig:
    verifier_reference = _required_environment("VERIGYM_DOCKER_VERIFIER_IMAGE")
    verifier_image_id = _required_environment("VERIGYM_DOCKER_VERIFIER_IMAGE_ID")
    agent_reference = _required_environment("VERIGYM_CODEX_AGENT_IMAGE")
    agent_image_id = _required_environment("VERIGYM_CODEX_AGENT_IMAGE_ID")
    if os.getuid() == 0:
        raise SystemExit("Docker-backed Codex execution requires a non-root host identity")
    runtime_user = f"{os.getuid()}:{os.getgid()}"
    return DockerRuntimeConfig(
        image=verifier_reference,
        expected_image_id=verifier_image_id,
        pull_policy="never",
        network_mode="none",
        read_only_rootfs=True,
        memory_bytes=512 * 1024 * 1024,
        cpus=1.0,
        pids_limit=128,
        tmpfs_bytes=64 * 1024 * 1024,
        stop_timeout_s=3,
        max_command_time_s=max_process_time_s,
        max_artifact_file_bytes=16 * 1024 * 1024,
        max_artifact_bytes=64 * 1024 * 1024,
        environment_allowlist=[],
        external_agent=DockerExternalAgentRuntimeConfig(
            image=agent_reference,
            expected_image_id=agent_image_id,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version=_EXPECTED_CODEX_VERSION,
            expected_executable_sha256=_EXPECTED_AGENT_CODEX_SHA256,
            process_argv=[
                "/usr/local/bin/codex",
                "exec-server",
                "--listen",
                "stdio://",
            ],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels={
                "org.verigym.codex.version": "0.144.6",
                "org.verigym.codex.binary.sha256": _EXPECTED_AGENT_CODEX_SHA256,
                "org.verigym.credential_material": "absent",
                "org.verigym.provider_credentials": "absent",
                "org.verigym.external_agent.protocol": ("codex_app_server_remote_environment_v1"),
            },
            pull_policy="never",
            run_as_user=runtime_user,
            read_only_rootfs=True,
            network_mode="none",
            memory_bytes=512 * 1024 * 1024,
            cpus=1.0,
            pids_limit=128,
            tmpfs_bytes=64 * 1024 * 1024,
            stop_timeout_s=3,
            max_process_time_s=max_process_time_s,
            max_output_bytes=8 * 1024 * 1024,
        ),
    )


def _docker_preflight(
    service: VeriGym,
    *,
    docker_config: DockerRuntimeConfig,
    source_config: SuiteSourceConfig,
    task_records: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime = DockerRuntime(docker_config)
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="verigym-pilot-reference-preflight-") as temporary_name:
        temporary_root = Path(temporary_name)
        try:
            runtime.prepare("codex-docker-pilot-zero-call-preflight")
            descriptor = runtime.descriptor
            verifier_image = descriptor.image
            if verifier_image is None:
                raise SystemExit("Docker verifier image identity is unavailable")
            for task_record in task_records:
                suite, task, assets = service.load_task(task_record["id"], source_config)
                reference = suite.reference_solution(task)
                if reference is None:
                    raise SystemExit(f"official reference candidate is unavailable: {task.id}")
                native_id = task.id.rsplit("/", 1)[-1]
                candidate = temporary_root / native_id / "candidate"
                artifact_root = temporary_root / native_id / "verifier-artifacts"
                for relative, source in reference.files.items():
                    destination = candidate / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(source, encoding="utf-8")
                results = service._verify_candidate(
                    task=task,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate,
                    artifact_root=artifact_root,
                )
                passed = bool(results) and all(
                    result.status is VerifierStatus.PASSED for result in results
                )
                records.append(
                    {
                        "task_id": task.id,
                        "task_hash": task_record["task_hash"],
                        "reference_candidate_hash": hash_directory(candidate),
                        "passed": passed,
                        "verifier_results": [
                            {
                                "node_id": result.node_id,
                                "plugin": result.plugin,
                                "status": result.status.value,
                                "error_category": result.error_category.value,
                                "exit_code": result.exit_code,
                                "tests_passed": result.tests_passed,
                                "tests_total": result.tests_total,
                                "request": result.request,
                            }
                            for result in results
                        ],
                    }
                )
                if not passed:
                    raise SystemExit(f"official Docker reference candidate failed: {task.id}")
        finally:
            runtime.close()
    descriptor = runtime.descriptor
    verifier_image = descriptor.image
    if verifier_image is None:
        raise SystemExit("Docker verifier image identity disappeared after preflight")
    if not (
        verifier_image.iverilog_version
        and re.search(r"\bversion\s+12(?:\.|\b)", verifier_image.iverilog_version, re.I)
        and verifier_image.vvp_version
        and re.search(r"\bversion\s+12(?:\.|\b)", verifier_image.vvp_version, re.I)
    ):
        raise SystemExit("Docker verifier image is not the required Icarus major 12")
    environment = runtime.environment_summary()
    role_images = environment.get("docker_role_images")
    if not isinstance(role_images, dict) or not isinstance(role_images.get("external_agent"), dict):
        raise SystemExit("Docker external-agent role identity is unavailable")
    cleanup = descriptor.cleanup
    if cleanup is None or not cleanup.complete:
        raise SystemExit("Docker zero-call preflight did not clean up every container")
    toolchain_identity = {
        "schema_version": "1.0",
        "profile": "verilog-eval-v2-icarus-v12-docker",
        "verifier_image_id": verifier_image.resolved_image_id,
        "iverilog_version": verifier_image.iverilog_version,
        "vvp_version": verifier_image.vvp_version,
        "compatibility": verifier_image.compatibility_status,
        "network_mode": "none",
        "reference_compatible": True,
    }
    runtime_identity = {
        "schema_version": "1.0",
        "architecture_path": "A_external_tool_delegation",
        "external_agent_process_backend": "docker_outer_runtime_delegated",
        "inner_codex_sandbox": "outer_runtime_delegated",
        "model_auth_control_plane": "host_codex_app_server",
        "workspace_tool_plane": "network_none_docker_codex_exec_server",
        "provider_credentials_in_agent_container": False,
        "provider_credentials_in_workspace": False,
        "provider_credentials_available_to_model_tools": False,
        "provider_credentials_persisted": False,
        "agent_executable_identity": {
            "name": docker_config.external_agent.expected_executable_name,
            "path": docker_config.external_agent.expected_executable_path,
            "version": docker_config.external_agent.expected_executable_version,
            "sha256": docker_config.external_agent.expected_executable_sha256,
            "process_argv": docker_config.external_agent.process_argv,
        }
        if docker_config.external_agent is not None
        else None,
        "required_agent_image_labels": (
            docker_config.external_agent.required_image_labels
            if docker_config.external_agent is not None
            else None
        ),
        "environment": environment,
        "runtime_configuration_fingerprint": descriptor.configuration_fingerprint,
        "cleanup": cleanup.model_dump(mode="json"),
    }
    reference_preflight = {
        "schema_version": "1.0",
        "real_model_process_count": 0,
        "required_count": 5,
        "passed_count": sum(record["passed"] for record in records),
        "all_passed": len(records) == 5 and all(record["passed"] for record in records),
        "records": records,
    }
    return runtime_identity, toolchain_identity, reference_preflight


def _require_reference_compatible_toolchain(identity: dict[str, Any]) -> None:
    if identity.get("reference_compatible") is not True:
        versions = (
            f"iverilog={identity.get('iverilog_version') or 'unavailable'}, "
            f"vvp={identity.get('vvp_version') or 'unavailable'}"
        )
        raise SystemExit(
            "real pilot requires the upstream-reference-compatible Icarus v12 profile; " + versions
        )


def _require_clean_frozen_source(plan: dict[str, Any]) -> None:
    if plan.get("verigym_source_dirty") is not False:
        raise SystemExit("real pilot requires a clean committed VeriGym source revision")
    provenance = get_build_provenance()
    if (
        provenance.dirty
        or provenance.source_commit != plan["verigym_commit"]
        or provenance.source_tree_hash != plan["verigym_source_tree_hash"]
    ):
        raise SystemExit("VeriGym source identity changed before pilot execution")


def _create_append_only_ledger(path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_jsonl_record(path: Path, record: dict[str, Any]) -> None:
    payload = (
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _terminal_execution_record(
    item: dict[str, Any],
    result: RunResult,
    *,
    output: Path,
    wall_time_s: float,
) -> dict[str, Any]:
    score = result.scorecard
    identity = result.manifest.external_agent_observations[-1]
    artifact_root = result.run_dir / "artifacts" / "codex_cli"
    summary = _load_optional_json(artifact_root / "summary.json")
    event_policy = _load_optional_json(artifact_root / "event_policy.json")
    workspace_policy = _load_optional_json(artifact_root / "workspace_policy.json")
    runtime_process = _load_optional_json(artifact_root / "runtime_process.json")
    runtime_security = runtime_process.get("security")
    runtime_security = runtime_security if isinstance(runtime_security, dict) else {}
    runtime_identity = runtime_process.get("runtime_identity")
    runtime_identity = runtime_identity if isinstance(runtime_identity, dict) else {}
    if identity.integration_track == "codex_cli_readonly_single_turn_agent":
        typed_policy_passed = summary.get("tool_policy_passed") is True
    else:
        typed_policy_passed = (
            event_policy.get("policy_passed") is True
            and workspace_policy.get("policy_passed") is True
        )
    return {
        "plan_index": item["plan_index"],
        "plan_item_id": item["plan_item_id"],
        "run_id": result.manifest.run_id,
        "run_dir": result.run_dir.relative_to(output).as_posix(),
        "track": item["track"],
        "task_id": item["task_id"],
        "sample_index": item["sample_index"],
        "launched": True,
        "terminal": True,
        "status": score.status,
        "resolved": score.resolved,
        "evaluable": not _is_infrastructure(result),
        "infrastructure_error": _is_infrastructure(result),
        "compile_status": score.correctness.compile_status,
        "hidden_regression_status": score.correctness.hidden_regression_status,
        "termination_reason": score.termination_reason,
        "failure": (score.failure.model_dump(mode="json") if score.failure is not None else None),
        "candidate_hash": score.reproducibility.candidate_hash,
        "candidate_changed_files": list(score.patch.changed_files),
        "candidate_diff_lines": score.patch.total_diff_lines,
        "wall_time_s": wall_time_s,
        "external_cli_process_wall_time_s": score.efficiency.external_cli_process_wall_time_s,
        "external_total_tokens": score.efficiency.external_total_tokens,
        "typed_tool_policy_passed": typed_policy_passed,
        "tool_use_policy": identity.tool_use_policy,
        "workspace_before_hash": (
            workspace_policy.get("before", {}).get("workspace_hash")
            if isinstance(workspace_policy.get("before"), dict)
            else None
        ),
        "workspace_after_hash": (
            workspace_policy.get("after", {}).get("workspace_hash")
            if isinstance(workspace_policy.get("after"), dict)
            else None
        ),
        "runtime_process_backend": runtime_identity.get("execution_backend"),
        "verifier_image_id": runtime_identity.get("verifier_image_id"),
        "agent_image_id": runtime_identity.get("agent_image_id"),
        "runtime_container_id": runtime_identity.get("container_id"),
        "runtime_effective_controls_verified": runtime_security.get("effective_controls_verified"),
        "runtime_cleanup_verified": runtime_security.get("cleanup_verified"),
        "runtime_container_removed": runtime_security.get("container_removed"),
        "runtime_broker_stopped": runtime_security.get("broker_stopped"),
        "runtime_network_mode": runtime_security.get("network_mode"),
        "runtime_credential_environment_names": runtime_security.get(
            "credential_environment_names_in_container"
        ),
        "runtime_proxy_environment_names": runtime_security.get(
            "proxy_environment_names_in_container"
        ),
        "runtime_workspace_changed_paths": runtime_security.get("workspace_changed_paths"),
        "runtime_security_complete": _runtime_process_security_complete(runtime_process),
    }


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _shared_external_prerequisite_failure(result: RunResult) -> str | None:
    failure = result.scorecard.failure
    if failure is None or not failure.infrastructure:
        return None
    if failure.category in {
        "authentication",
        "rate_limit",
        "transport",
        "process_boundary",
        "sandbox_backend_unavailable",
    }:
        return f"shared_external_prerequisite:{failure.category}"
    return None


def _actual_security_breach(result: RunResult) -> bool:
    """Distinguish an observed boundary escape from a safely contained policy refusal."""

    run_dir = getattr(result, "run_dir", None)
    if not isinstance(run_dir, Path):
        return False
    artifact_root = run_dir / "artifacts" / "codex_cli"
    runtime_process = _load_optional_json(artifact_root / "runtime_process.json")
    if not runtime_process:
        return False
    return not _runtime_process_security_complete(runtime_process)


def _runtime_process_security_complete(runtime_process: dict[str, Any]) -> bool:
    identity = runtime_process.get("runtime_identity")
    security = runtime_process.get("security")
    if not isinstance(identity, dict) or not isinstance(security, dict):
        return False
    required_true = (
        "read_only_rootfs",
        "non_root",
        "no_new_privileges",
        "init",
        "private_pid_namespace",
        "private_ipc_namespace",
        "effective_controls_verified",
        "container_exit_inspected",
        "cleanup_verified",
        "container_removed",
        "broker_stopped",
        "process_group_cleaned",
        "user_config_metadata_unchanged",
    )
    required_false = (
        "host_home_mounted",
        "source_repository_mounted",
        "hidden_verifier_mounted",
        "docker_socket_mounted",
        "credential_files_mounted",
        "api_key_environment_forwarded",
        "credential_contents_accessed_by_verigym",
        "user_config_contents_accessed_by_verigym",
        "provider_network_in_container",
    )
    return bool(
        identity.get("execution_owner") == "verigym_runtime"
        and identity.get("execution_backend") == "docker_outer_runtime_delegated"
        and identity.get("agent_image_id") != identity.get("verifier_image_id")
        and security.get("boundary") == "docker_outer_runtime"
        and security.get("network_mode") == "none"
        and security.get("cap_drop") == ["ALL"]
        and security.get("mount_destinations") == ["/workspace"]
        and security.get("writable_destinations") == ["/workspace", "/tmp"]
        and security.get("credential_environment_names_in_container") == []
        and security.get("proxy_environment_names_in_container") == []
        and all(security.get(name) is True for name in required_true)
        and all(security.get(name) is False for name in required_false)
        and runtime_process.get("cleanup_complete") is True
    )


def _validate_execution_ledgers(
    plan: dict[str, Any],
    *,
    launch_records: list[dict[str, Any]],
    execution_records: list[dict[str, Any]],
    max_processes: int,
) -> None:
    expected_indices = list(range(plan["planned_run_count"]))
    if [record["plan_index"] for record in execution_records] != expected_indices:
        raise RuntimeError("execution ledger does not cover every frozen plan item exactly once")
    launched_indices = [record["plan_index"] for record in execution_records if record["launched"]]
    authorized_indices = [record["plan_index"] for record in launch_records]
    if launched_indices != authorized_indices:
        raise RuntimeError("process authorization and execution ledgers disagree")
    if len(launch_records) > max_processes:
        raise RuntimeError("pilot exceeded its global Codex process authorization")
    if [record["authorized_process_ordinal"] for record in launch_records] != list(
        range(1, len(launch_records) + 1)
    ):
        raise RuntimeError("process authorization ordinals are not contiguous")
    if any(
        record["retry_count"] != 0 or record["resume"] is not False for record in launch_records
    ):
        raise RuntimeError("pilot authorization ledger contains a retry or resume")


def _candidate_freeze_evidence(
    results: list[RunResult],
    before_replay: dict[str, str],
) -> dict[str, Any]:
    records = []
    for result in results:
        run_id = result.manifest.run_id
        after = hash_directory(result.run_dir / "candidate")
        records.append(
            {
                "run_id": run_id,
                "before_replay_hash": before_replay[run_id],
                "after_replay_hash": after,
                "unchanged": before_replay[run_id] == after,
                "candidate_modified_by_outer_agent": False,
            }
        )
    return {
        "schema_version": "1.0",
        "records": records,
        "verified_count": sum(record["unchanged"] for record in records),
        "all_unchanged": all(record["unchanged"] for record in records),
    }


def _source_integrity(plan: dict[str, Any]) -> dict[str, Any]:
    provenance = get_build_provenance()
    passed = (
        provenance.dirty is False
        and provenance.source_commit == plan["verigym_commit"]
        and provenance.source_tree_hash == plan["verigym_source_tree_hash"]
    )
    return {
        "schema_version": "1.0",
        "expected_commit": plan["verigym_commit"],
        "observed_commit": provenance.source_commit,
        "expected_tree_hash": plan["verigym_source_tree_hash"],
        "observed_tree_hash": provenance.source_tree_hash,
        "observed_dirty": provenance.dirty,
        "passed": passed,
    }


def _security_scans(
    results: list[RunResult],
    *,
    output: Path,
    source_root: Path,
) -> dict[str, Any]:
    secret_hits: list[str] = []
    hidden_hits: list[str] = []
    host_path_hits: list[str] = []
    auth_path_hits: list[str] = []
    proxy_value_hits: list[str] = []
    host_markers = {
        str(output.resolve()),
        str(source_root.resolve()),
        str(Path(__file__).resolve().parents[1]),
        str(Path.home()),
    }
    proxy_values = [
        os.environ[name]
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
        if name in os.environ and len(os.environ[name]) >= 8
    ]
    hidden_markers = {"tb_mismatch"}
    for result in results:
        native_id = result.manifest.task_id.rsplit("/", 1)[-1]
        hidden_markers.update({f"{native_id}_ref.sv", f"{native_id}_test.sv"})
    for result in results:
        surfaces = (
            result.run_dir / "candidate",
            result.run_dir / "artifacts" / "codex_cli",
            result.run_dir / "trace.jsonl",
        )
        for surface in surfaces:
            paths = [surface] if surface.is_file() else list(surface.rglob("*"))
            for path in paths:
                if not path.is_file() or path.is_symlink():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                relative = f"{result.manifest.run_id}/{path.relative_to(result.run_dir).as_posix()}"
                if _SECRET_PATTERN.search(text):
                    secret_hits.append(relative)
                if any(marker in text for marker in hidden_markers):
                    hidden_hits.append(relative)
                if any(marker and marker in text for marker in host_markers):
                    host_path_hits.append(relative)
                if any(
                    marker in text
                    for marker in (
                        "/.codex/",
                        "\\.codex\\",
                        "auth.json",
                        "credentials.json",
                        "/var/run/docker.sock",
                    )
                ):
                    auth_path_hits.append(relative)
                if any(value in text for value in proxy_values):
                    proxy_value_hits.append(relative)
    return {
        "schema_version": "1.0",
        "scope": [
            "candidate",
            "codex_cli_artifacts",
            "trace",
        ],
        "excluded_expected_identity_fields": [
            "suite_source_snapshot_paths",
            "frozen_plan_source_paths",
        ],
        "secret_scan_passed": not secret_hits,
        "secret_hits": sorted(set(secret_hits)),
        "hidden_asset_scan_passed": not hidden_hits,
        "hidden_asset_hits": sorted(set(hidden_hits)),
        "hidden_asset_markers_are_names_only": True,
        "reference_equivalent_candidate_is_not_inferred_as_a_leak": True,
        "host_path_scan_passed": not host_path_hits,
        "host_path_hits": sorted(set(host_path_hits)),
        "auth_path_scan_passed": not auth_path_hits,
        "auth_path_hits": sorted(set(auth_path_hits)),
        "proxy_value_scan_passed": not proxy_value_hits,
        "proxy_value_hits": sorted(set(proxy_value_hits)),
        "proxy_values_persisted_or_hashed": False,
        "all_passed": not any(
            (secret_hits, hidden_hits, host_path_hits, auth_path_hits, proxy_value_hits)
        ),
    }


def _write_pilot_reports(report: dict[str, Any], destination: Path) -> None:
    atomic_dump_json(destination / "acceptance.json", report["experiment_execution_gate"])
    atomic_dump_json(destination / "pass-at-k.json", {"partitions": report["pass_at_k_partitions"]})
    atomic_dump_json(
        destination / "comparison-partitions.json",
        {"partitions": report["comparison_partitions"]},
    )
    rows = report["per_run_outcomes"]
    columns = [
        "plan_index",
        "run_id",
        "track",
        "task_id",
        "sample_index",
        "launched",
        "terminal",
        "status",
        "resolved",
        "evaluable",
        "infrastructure_error",
        "compile_status",
        "hidden_regression_status",
        "termination_reason",
        "wall_time_s",
        "external_total_tokens",
        "typed_tool_policy_passed",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(destination / "per-run-outcomes.csv", stream.getvalue())
    gate = report["experiment_execution_gate"]
    markdown = "\n".join(
        [
            "# VeriGym Codex CLI VerilogEval V2 Pilot",
            "",
            f"Experiment-execution gate: **{gate['status']}**.",
            "",
            "This is a preliminary 30-process Codex CLI agent pilot, not a direct API "
            "benchmark or statistically definitive performance claim.",
            "",
            f"- Planned/launched/terminal: {report['planned_runs']}/"
            f"{report['launched_processes']}/{report['terminal_runs']}",
            f"- Evaluable/resolved: {report['evaluable_runs']}/{report['resolved_runs']}",
            f"- Infrastructure failures: {report['infrastructure_failures']}",
            f"- Contained policy failures: {report['policy_failure_count']}",
            f"- Replay successes: {report['replay_success_count']}",
            "",
            "Candidate correctness and contained model policy failures are performance "
            "outcomes; they are separate from the experiment-execution gate.",
            "",
        ]
    )
    atomic_write_text(destination / "pilot-report.md", markdown)


def _load_yaml(path: Path, *, required_keys: set[str]) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    metadata = os.lstat(resolved)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > 1024 * 1024
    ):
        raise SystemExit(f"unsafe YAML input: {resolved}")
    try:
        value = yaml.load(resolved.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    except Exception as exc:
        raise SystemExit(f"invalid YAML input {resolved.name}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != required_keys:
        raise SystemExit(f"{resolved.name} does not have the exact required top-level keys")
    return value


def _validate_static_config(config: dict[str, Any]) -> None:
    if config["schema_version"] != "1.0":
        raise SystemExit("pilot config schema_version must be 1.0")
    tasks = config["tasks"]
    tracks = config["tracks"]
    sampling = config["sampling"]
    execution = config["execution"]
    if not isinstance(tasks, list) or len(tasks) != 5:
        raise SystemExit("pilot config must freeze exactly five tasks")
    if not isinstance(tracks, list) or [item.get("id") for item in tracks] != [
        "codex_cli_readonly_single_turn_agent",
        "codex_cli_external_agent",
    ]:
        raise SystemExit("pilot config must preserve the two ordered integration tracks")
    if any(
        track.get("runtime") != "docker"
        or track.get("external_agent_process_backend") != "docker_outer_runtime_delegated"
        or track.get("inner_codex_sandbox") != "outer_runtime_delegated"
        or track.get("verifier_network") != "none"
        for track in tracks
    ):
        raise SystemExit("pilot tracks require the runtime-owned Docker external-agent backend")
    if sampling.get("base_seed") != 0 or sampling.get("sample_indices") != [0, 1, 2]:
        raise SystemExit("pilot config must define three independent samples")
    if (
        execution.get("planned_runs") != 30
        or execution.get("max_codex_processes") != 30
        or execution.get("allow_retry") is not False
        or execution.get("allow_best_of_k_selection") is not False
        or execution.get("allow_outer_agent_repair") is not False
    ):
        raise SystemExit("pilot execution policy is not the fixed 30-run policy")
    coverage = {item.get("coverage") for item in tasks if isinstance(item, dict)}
    required_coverage = {
        "simple combinational logic",
        "multiplexing or arithmetic",
        "counter/sequential logic",
        "shift/register logic",
        "FSM or control logic",
    }
    if coverage != required_coverage:
        raise SystemExit("pilot task coverage is incomplete")


def _load_capability() -> dict[str, Any]:
    path = Path(_required_environment("VERIGYM_CODEX_CAPABILITY_FILE"))
    from verigym_codex_cli.capabilities import load_capability_report
    from verigym_codex_cli.process import resolve_executable

    report = load_capability_report(path, resolve_executable())
    if report.model_call_count != 0:
        raise SystemExit("sealed capability discovery was not zero-call")
    return report.safe_dict()


def _freeze_source(
    service: VeriGym,
    config: dict[str, Any],
    source_root: Path,
) -> tuple[SuiteSourceConfig, Any, list[dict[str, Any]]]:
    suite_config = config["suite"]
    source = SuiteSourceConfig(
        source_root=source_root,
        variant=suite_config["variant"],
        strict_compatibility=True,
    )
    expected_tasks = {item["id"]: item for item in config["tasks"]}
    records: list[dict[str, Any]] = []
    snapshot = None
    for task_id, expected in expected_tasks.items():
        suite, task, assets = service.load_task(task_id, source)
        current_snapshot = suite.source_snapshot()
        if current_snapshot is None:
            raise SystemExit("VerilogEval source did not produce a provenance snapshot")
        if snapshot is None:
            snapshot = current_snapshot
        elif snapshot != current_snapshot:
            raise SystemExit("VerilogEval source identity changed during planning")
        task_hash = content_hash(task)
        source_hash = task.source.content_hash or hash_directory(Path(assets.visible_root))
        if task_hash != expected["task_hash"] or source_hash != expected["source_hash"]:
            raise SystemExit(f"frozen task identity mismatch: {task_id}")
        records.append(
            {
                **expected,
                "task_hash": task_hash,
                "source_hash": source_hash,
            }
        )
    assert snapshot is not None
    if (
        snapshot.git_commit != suite_config["expected_git_commit"]
        or snapshot.dataset_content_hash != suite_config["expected_dataset_content_hash"]
    ):
        raise SystemExit("VerilogEval source commit or dataset hash differs from the frozen pilot")
    return source, snapshot, records


def _build_plan(
    config: dict[str, Any],
    *,
    model_id: str,
    capability: dict[str, Any],
    source_snapshot: Any,
    task_records: list[dict[str, Any]],
    registries: Any,
    toolchain_identity: dict[str, Any],
    auth_identity: dict[str, Any] | None = None,
    package_identities: dict[str, Any] | None = None,
    runtime_identity: dict[str, Any] | None = None,
    reference_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for task in task_records:
        native = task["id"].rsplit("/", 1)[1]
        for sample_index in config["sampling"]["sample_indices"]:
            for track in config["tracks"]:
                items.append(
                    {
                        "plan_index": len(items),
                        "plan_item_id": (
                            f"codex-pilot-{track['id']}-{native}-sample-{sample_index}"
                        ),
                        "run_id": f"codex-pilot-{track['id']}-{native}-{sample_index}",
                        "track": track["id"],
                        "task_id": task["id"],
                        "task_hash": task["task_hash"],
                        "source_hash": task["source_hash"],
                        "base_seed": config["sampling"]["base_seed"],
                        "sample_index": sample_index,
                        "child_seed": config["sampling"]["base_seed"] + sample_index,
                        "retry_count": 0,
                        "best_of_k": None,
                    }
                )
    provenance = get_build_provenance()
    identity = {
        "name": config["name"],
        "requested_model_id": model_id,
        "source_commit": source_snapshot.git_commit,
        "dataset_hash": source_snapshot.dataset_content_hash,
        "capability_fingerprint": capability["capability_fingerprint"],
        "auth_semantic_id": (auth_identity or {}).get("auth_semantic_id"),
        "package_identities": package_identities,
        "runtime_configuration_fingerprint": (runtime_identity or {}).get(
            "runtime_configuration_fingerprint"
        ),
        "proxy_identity": _proxy_identity(),
        "items": items,
    }
    return {
        "schema_version": "1.0",
        "experiment_id": f"codex-cli-pilot-{content_hash(identity)[:16]}",
        "name": config["name"],
        "created_at_utc": datetime.now(UTC).isoformat(),
        "study_label": "integration_study_not_direct_api_benchmark",
        "direct_api_status": {
            "implemented": False,
            "executed": False,
            "reason": (
                "Both tracks use the Codex CLI agent harness; no direct provider "
                "credential or transport is implemented."
            ),
        },
        "verigym_version": "0.1.0",
        "verigym_commit": provenance.source_commit,
        "verigym_source_tree_hash": provenance.source_tree_hash,
        "verigym_source_dirty": provenance.dirty,
        "plugin_origins": {
            "readonly_agent": registries.agents.origin("codex-cli-readonly-agent").__dict__,
            "workspace_agent": registries.agents.origin("codex-cli-agent").__dict__,
        },
        "requested_model_id": model_id,
        "capability_identity": {
            key: capability[key]
            for key in (
                "executable_name",
                "executable_sha256",
                "version_output",
                "capability_fingerprint",
                "model_call_count",
            )
        },
        "authentication_identity": auth_identity,
        "package_identities": package_identities,
        "runtime_identity": runtime_identity,
        "proxy_identity": _proxy_identity(),
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "toolchain_identity": toolchain_identity,
        "reference_preflight": reference_preflight,
        "task_records": task_records,
        "sampling": config["sampling"],
        "execution": config["execution"],
        "planned_run_count": len(items),
        "items": items,
    }


def _proxy_identity() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "allow_proxy_environment": True,
        "allowlist": list(_PROXY_NAMES),
        "forwarded_present_names": [name for name in _PROXY_NAMES if name in os.environ],
        "proxy_values_read_for_identity": False,
        "proxy_values_persisted_or_hashed": False,
    }


def _load_budget(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    budget = _load_yaml(path, required_keys=_REQUIRED_BUDGET_KEYS)
    execution = config["execution"]
    if (
        budget["schema_version"] != "1.0"
        or budget["max_planned_runs"] != 30
        or budget["max_codex_processes"] != 30
        or not isinstance(budget["max_total_wall_time_s"], int)
        or not 0 < budget["max_total_wall_time_s"] <= execution["max_total_wall_time_s"]
        or not isinstance(budget["max_failed_infrastructure_runs"], int)
        or not 0 <= budget["max_failed_infrastructure_runs"] <= 3
        or budget["allow_retry"] is not False
        or budget["allow_best_of_k_selection"] is not False
    ):
        raise SystemExit("pilot budget does not satisfy the fixed safety bounds")
    return budget


def _run_config(
    item: dict[str, Any],
    *,
    model_id: str,
    output: Path,
    source_config: SuiteSourceConfig,
    source_snapshot: Any,
    task_records: list[dict[str, Any]],
    experiment_id: str,
    max_process_time_s: int,
    docker_config: DockerRuntimeConfig,
) -> RunConfig:
    task = next(record for record in task_records if record["id"] == item["task_id"])
    common: dict[str, Any] = {
        "task_id": item["task_id"],
        "suite_source": source_config,
        "expected_suite_source_snapshot": source_snapshot,
        "expected_task_hash": task["task_hash"],
        "expected_source_hash": task["source_hash"],
        "runtime": "docker",
        "docker_config": docker_config,
        "seed": item["child_seed"],
        "sample_index": item["sample_index"],
        "output": output,
        "run_id": item["run_id"],
        "experiment_id": experiment_id,
        "plan_item_id": item["plan_item_id"],
        "system_id": item["track"],
        "base_seed": item["base_seed"],
    }
    if item["track"] == "codex_cli_readonly_single_turn_agent":
        return RunConfig(
            **common,
            mode=InteractionMode.AGENT,
            agent="codex-cli-readonly-agent",
            agent_options={
                "model_id": model_id,
                "sandbox": "read-only",
                "approval_policy": "non-interactive",
                "reasoning_effort": "xhigh",
                "allow_proxy_environment": True,
                "max_process_time_s": max_process_time_s,
            },
        )
    return RunConfig(
        **common,
        mode=InteractionMode.AGENT,
        agent="codex-cli-agent",
        agent_options={
            "model_id": model_id,
            "sandbox": "workspace-write",
            "approval_policy": "non-interactive",
            "reasoning_effort": "xhigh",
            "allow_proxy_environment": True,
            "max_process_time_s": max_process_time_s,
        },
    )


def _replay_without_codex(results: list[RunResult]) -> list[dict[str, Any]]:
    protected_names = (
        "HOME",
        "CODEX_HOME",
        "VERIGYM_CODEX_BINARY",
        "VERIGYM_CODEX_AUTH_MODE",
        "VERIGYM_CODEX_CREDENTIAL_ENV",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    )
    original = {name: os.environ.get(name) for name in protected_names}
    removed_credential_names = [
        name
        for name in (
            "VERIGYM_CODEX_AUTH_MODE",
            "VERIGYM_CODEX_CREDENTIAL_ENV",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
        )
        if name in os.environ
    ]
    removed_proxy_names = [name for name in _PROXY_NAMES if name in os.environ]
    records: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="verigym-credentialless-replay-") as replay_home:
            os.environ["HOME"] = replay_home
            os.environ["CODEX_HOME"] = replay_home
            os.environ["VERIGYM_CODEX_BINARY"] = "/codex-must-not-run-during-replay"
            for name in protected_names[3:]:
                os.environ.pop(name, None)
            for result in results:
                common = {
                    "run_id": result.manifest.run_id,
                    "codex_available": False,
                    "credential_environment_available": False,
                    "credential_environment_names_removed": removed_credential_names,
                    "proxy_environment_names_removed": removed_proxy_names,
                    "codex_cli_process_count": 0,
                    "model_call_count": 0,
                    "broker_process_count": 0,
                    "proxy_environment_available": False,
                }
                try:
                    replay = replay_run(result.run_dir, verify=True)
                    record = {
                        **common,
                        "success": True,
                        "reverified_resolved": replay.reverified_resolved,
                    }
                except Exception as exc:
                    record = {
                        **common,
                        "success": False,
                        "error_category": type(exc).__name__,
                        "message": str(exc)[:1024],
                    }
                record["credential_home_file_count"] = sum(
                    path.is_file() for path in Path(replay_home).rglob("*")
                )
                records.append(record)
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return records


def _pilot_report(
    plan: dict[str, Any],
    results: list[RunResult],
    execution_records: list[dict[str, Any]],
    replay_records: list[dict[str, Any]],
    *,
    elapsed_s: float,
    global_wall_time_limit_s: int,
    report_coverage: dict[str, Any],
    process_attempts: int,
    plan_unchanged: bool,
    candidate_freeze: dict[str, Any],
    source_integrity: dict[str, Any],
    security_scans: dict[str, Any],
) -> dict[str, Any]:
    results_by_item = {
        result.manifest.plan_item_id: result
        for result in results
        if result.manifest.plan_item_id is not None
    }
    records_by_index = {record["plan_index"]: record for record in execution_records}
    partition_items: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in plan["items"]:
        partition_items[(item["task_id"], item["track"])].append(item)
    pass_at_k = []
    comparison_groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for result in results:
        identity = _result_identity(result)
        comparison_key = (
            identity["integration_track"],
            identity["requested_model_id"],
            identity["observed_model_id"],
            identity["cli_version"],
            identity["capability_fingerprint"],
            identity["auth_semantic_id"],
            identity["tool_use_policy"],
            identity["sandbox_policy"],
            identity["runtime_process_backend"],
            identity["agent_image_id"],
            identity["verifier_image_id"],
            identity["runtime_configuration_fingerprint"],
        )
        comparison_groups[comparison_key].append(result.manifest.run_id)
    for (task_id, track), items in sorted(partition_items.items()):
        items = sorted(items, key=lambda item: item["sample_index"])
        children = [
            results_by_item[item["plan_item_id"]]
            for item in items
            if item["plan_item_id"] in results_by_item
        ]
        terminal_count = sum(records_by_index[item["plan_index"]]["terminal"] for item in items)
        attempted_count = sum(records_by_index[item["plan_index"]]["launched"] for item in items)
        evaluable_count = sum(not _is_infrastructure(child) for child in children)
        resolved_count = sum(child.scorecard.resolved for child in children)
        identity_partition_count = len(
            {
                (
                    _result_identity(child)["requested_model_id"],
                    _result_identity(child)["cli_version"],
                    _result_identity(child)["capability_fingerprint"],
                    _result_identity(child)["auth_semantic_id"],
                    _result_identity(child)["tool_use_policy"],
                    _result_identity(child)["runtime_process_backend"],
                    _result_identity(child)["agent_image_id"],
                    _result_identity(child)["verifier_image_id"],
                    _result_identity(child)["runtime_configuration_fingerprint"],
                )
                for child in children
            }
        )
        canonical = (
            len(items) == 3
            and attempted_count == 3
            and terminal_count == 3
            and evaluable_count == 3
            and identity_partition_count == 1
            and [item["sample_index"] for item in items] == [0, 1, 2]
        )
        pass_at_k.append(
            {
                "task_id": task_id,
                "integration_track": track,
                "planned_count": len(items),
                "attempted_count": attempted_count,
                "terminal_count": terminal_count,
                "evaluable_count": evaluable_count,
                "non_evaluable_count": len(items) - evaluable_count,
                "unlaunched_count": len(items) - attempted_count,
                "resolved_count": resolved_count,
                "identity_partition_count": identity_partition_count,
                "canonical_valid": canonical,
                "values": _pass_at_k_values(resolved_count, canonical=canonical),
            }
        )
    terminal = sum(bool(record.get("terminal")) for record in execution_records)
    infrastructure = sum(
        bool(record.get("infrastructure_error")) or not record.get("terminal", False)
        for record in execution_records
    )
    policy_failures = sum(
        result.scorecard.failure is not None and result.scorecard.failure.kind == "policy"
        for result in results
    )
    integrity_records = [
        {
            "run_id": result.manifest.run_id,
            "status": verify_artifact_manifest(result.run_dir, expected_scope="run").status,
        }
        for result in results
    ]
    integrity_verified = sum(record["status"] == "verified" for record in integrity_records)
    replay_success = sum(record["success"] for record in replay_records)
    evaluable_runs = sum(not _is_infrastructure(result) for result in results)
    observed_model_processes = sum(
        identity.invocation_count
        for result in results
        for identity in result.manifest.external_agent_observations
    )
    gate_checks = {
        "planned_exactly_30": plan["planned_run_count"] == 30,
        "launched_exactly_30": process_attempts == 30,
        "observed_exactly_30_model_processes": observed_model_processes == 30,
        "terminal_exactly_30": terminal == 30,
        "all_outcomes_evaluable": evaluable_runs == 30,
        "zero_infrastructure_failures": infrastructure == 0,
        "all_replays_succeeded": replay_success == 30,
        "all_replays_zero_cli_model_calls": all(
            record["codex_cli_process_count"] == 0
            and record["model_call_count"] == 0
            and record["broker_process_count"] == 0
            and record["proxy_environment_available"] is False
            and record["credential_home_file_count"] == 0
            for record in replay_records
        ),
        "all_runtime_processes_docker_delegated": all(
            record.get("runtime_process_backend") == "docker_outer_runtime_delegated"
            for record in execution_records
            if record.get("terminal")
        )
        and terminal == 30,
        "all_runtime_security_controls_complete": all(
            record.get("runtime_security_complete") is True
            for record in execution_records
            if record.get("terminal")
        )
        and terminal == 30,
        "all_agent_verifier_images_separated": all(
            record.get("agent_image_id")
            and record.get("verifier_image_id")
            and record.get("agent_image_id") != record.get("verifier_image_id")
            for record in execution_records
            if record.get("terminal")
        )
        and terminal == 30,
        "all_run_integrity_verified": integrity_verified == 30,
        "candidate_freeze_unchanged": candidate_freeze["all_unchanged"],
        "source_immutable": source_integrity["passed"],
        "plan_immutable": plan_unchanged,
        "security_scans_passed": security_scans["all_passed"],
        "reference_compatible_toolchain": plan["toolchain_identity"]["reference_compatible"],
        "official_references_passed_5_of_5": (
            isinstance(plan.get("reference_preflight"), dict)
            and plan["reference_preflight"].get("all_passed") is True
            and plan["reference_preflight"].get("passed_count") == 5
            and plan["reference_preflight"].get("real_model_process_count") == 0
        ),
        "all_pass_at_k_partitions_canonical": all(
            partition["canonical_valid"] for partition in pass_at_k
        ),
        "within_global_wall_time": elapsed_s <= global_wall_time_limit_s,
    }
    if all(gate_checks.values()):
        gate_status = "PASS"
    elif any(
        str(record.get("error_category", "")).startswith("shared_external_prerequisite:")
        for record in execution_records
    ):
        gate_status = "BLOCKED"
    else:
        gate_status = "FAIL"
    comparison_partitions = [
        {
            "partition_id": content_hash(
                {
                    "integration_track": key[0],
                    "requested_model_id": key[1],
                    "observed_model_id": key[2],
                    "cli_version": key[3],
                    "capability_fingerprint": key[4],
                    "auth_semantic_id": key[5],
                    "tool_use_policy": key[6],
                    "sandbox_policy": key[7],
                    "runtime_process_backend": key[8],
                    "agent_image_id": key[9],
                    "verifier_image_id": key[10],
                    "runtime_configuration_fingerprint": key[11],
                }
            ),
            "integration_track": key[0],
            "requested_model_id": key[1],
            "observed_model_id": key[2] or None,
            "cli_version": key[3],
            "capability_fingerprint": key[4],
            "auth_semantic_id": key[5],
            "tool_use_policy": key[6],
            "sandbox_policy": key[7],
            "runtime_process_backend": key[8],
            "agent_image_id": key[9],
            "verifier_image_id": key[10],
            "runtime_configuration_fingerprint": key[11],
            "run_count": len(run_ids),
            "run_ids": sorted(run_ids),
        }
        for key, run_ids in sorted(comparison_groups.items())
    ]
    track_metrics = _track_metrics(execution_records, pass_at_k)
    return {
        "schema_version": "1.0",
        "study_label": "integration_study_not_direct_api_benchmark",
        "measurement_scope": "preliminary_benchmark_pilot_not_statistically_definitive",
        "no_universal_score": True,
        "planned_runs": plan["planned_run_count"],
        "launched_processes": process_attempts,
        "observed_model_processes": observed_model_processes,
        "terminal_runs": terminal,
        "resolved_runs": sum(result.scorecard.resolved for result in results),
        "evaluable_runs": evaluable_runs,
        "infrastructure_failures": infrastructure,
        "execution_complete": gate_status == "PASS",
        "experiment_execution_gate": {
            "status": gate_status,
            "checks": gate_checks,
            "candidate_performance_is_not_gate": True,
            "contained_policy_failures_are_evaluable": True,
        },
        "model_performance_metrics": track_metrics,
        "policy_failure_count": policy_failures,
        "elapsed_s": elapsed_s,
        "known_total_tokens": sum(
            result.scorecard.efficiency.external_total_tokens or 0 for result in results
        ),
        "missing_token_run_count": sum(
            result.scorecard.efficiency.external_total_tokens is None for result in results
        ),
        "candidate_changed_files": sum(
            len(result.scorecard.patch.changed_files) for result in results
        ),
        "candidate_diff_lines": sum(result.scorecard.patch.total_diff_lines for result in results),
        "per_run_outcomes": execution_records,
        "pass_at_k_partitions": pass_at_k,
        "comparison_partitions": comparison_partitions,
        "replay_success_count": replay_success,
        "replay_records": replay_records,
        "security_scans": security_scans,
        "candidate_freeze": candidate_freeze,
        "source_integrity": source_integrity,
        "integrity_verified_count": integrity_verified,
        "integrity_records": integrity_records,
        "ppa_non_null_count": sum(result.scorecard.quality.ppa is not None for result in results),
        "report_coverage": report_coverage,
    }


def _pass_at_k_values(resolved_count: int, *, canonical: bool) -> dict[str, float | None]:
    return {
        str(k): compute_pass_at_k(3, resolved_count, k) if canonical else None for k in (1, 2, 3)
    }


def _track_metrics(
    execution_records: list[dict[str, Any]],
    pass_at_k: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tracks = sorted({str(record["track"]) for record in execution_records})
    metrics = []
    for track in tracks:
        records = [record for record in execution_records if record["track"] == track]
        partitions = [
            partition for partition in pass_at_k if partition["integration_track"] == track
        ]
        wall_times = [
            float(record["wall_time_s"])
            for record in records
            if isinstance(record.get("wall_time_s"), (int, float))
        ]
        canonical_pass_1 = [
            float(partition["values"]["1"])
            for partition in partitions
            if partition["values"]["1"] is not None
        ]
        canonical_pass_2 = [
            float(partition["values"]["2"])
            for partition in partitions
            if partition["values"]["2"] is not None
        ]
        canonical_pass_3 = [
            float(partition["values"]["3"])
            for partition in partitions
            if partition["values"]["3"] is not None
        ]
        metrics.append(
            {
                "integration_track": track,
                "planned_count": len(records),
                "launched_count": sum(record["launched"] for record in records),
                "terminal_count": sum(record["terminal"] for record in records),
                "evaluable_count": sum(bool(record.get("evaluable")) for record in records),
                "resolved_count": sum(bool(record.get("resolved")) for record in records),
                "compile_pass_count": sum(
                    record.get("compile_status") == "passed" for record in records
                ),
                "hidden_test_pass_count": sum(
                    record.get("hidden_regression_status") == "passed" for record in records
                ),
                "infrastructure_failure_count": sum(
                    bool(record.get("infrastructure_error")) for record in records
                ),
                "infrastructure_failure_rate": (
                    sum(bool(record.get("infrastructure_error")) for record in records)
                    / len(records)
                    if records
                    else None
                ),
                "typed_tool_policy_failure_count": sum(
                    record.get("typed_tool_policy_passed") is False for record in records
                ),
                "known_usage_count": sum(
                    record.get("external_total_tokens") is not None for record in records
                ),
                "missing_usage_count": sum(
                    record.get("external_total_tokens") is None for record in records
                ),
                "wall_time_total_s": sum(wall_times),
                "wall_time_mean_s": sum(wall_times) / len(wall_times) if wall_times else None,
                "pass_at_1_macro": (
                    sum(canonical_pass_1) / len(canonical_pass_1)
                    if len(canonical_pass_1) == 5
                    else None
                ),
                "pass_at_2_macro": (
                    sum(canonical_pass_2) / len(canonical_pass_2)
                    if len(canonical_pass_2) == 5
                    else None
                ),
                "pass_at_3_macro": (
                    sum(canonical_pass_3) / len(canonical_pass_3)
                    if len(canonical_pass_3) == 5
                    else None
                ),
            }
        )
    return metrics


def _result_identity(result: RunResult) -> dict[str, str]:
    manifest = result.manifest
    if not manifest.external_agent_observations:
        raise RuntimeError("Codex CLI agent run did not record external-agent identity")
    identity = manifest.external_agent_observations[-1]
    runtime_process = _load_optional_json(
        result.run_dir / "artifacts" / "codex_cli" / "runtime_process.json"
    )
    runtime_identity = runtime_process.get("runtime_identity")
    runtime_identity = runtime_identity if isinstance(runtime_identity, dict) else {}
    return {
        "integration_track": identity.integration_track,
        "requested_model_id": identity.requested_model_id or "",
        "observed_model_id": identity.observed_model_id or "",
        "cli_version": identity.executable_version,
        "capability_fingerprint": identity.capability_fingerprint,
        "auth_semantic_id": identity.auth_semantic_id,
        "tool_use_policy": identity.tool_use_policy,
        "sandbox_policy": identity.sandbox_policy,
        "runtime_process_backend": str(runtime_identity.get("execution_backend") or ""),
        "agent_image_id": str(runtime_identity.get("agent_image_id") or ""),
        "verifier_image_id": str(runtime_identity.get("verifier_image_id") or ""),
        "runtime_configuration_fingerprint": str(
            runtime_identity.get("configuration_fingerprint") or ""
        ),
    }


def _is_infrastructure(result: RunResult) -> bool:
    score = result.scorecard
    return (
        score.status == "error"
        or score.correctness.infrastructure_error
        or bool(score.failure and score.failure.infrastructure)
        or _actual_security_breach(result)
    )


def _verify_plugin_origins(registries: Any) -> None:
    for name in ("codex-cli-readonly-agent", "codex-cli-agent"):
        origin = registries.agents.origin(name)
        if (
            origin.registration != "entry_point"
            or (origin.package or "").lower() != _EXPECTED_PACKAGE
        ):
            raise SystemExit(f"{name} must be discovered from installed {_EXPECTED_PACKAGE}")


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise SystemExit(f"{name} is required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
