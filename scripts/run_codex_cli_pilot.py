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
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunResult
from verigym.schemas.suite import SuiteSourceConfig
from verigym.suites.verilog_eval.schemas import IcarusCompatibility
from verigym.suites.verilog_eval.toolchain import detect_icarus

_EXPECTED_PACKAGE = "verigym-codex-cli"
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
    _required_environment("VERIGYM_CODEX_BINARY")
    _required_environment("VERIGYM_CODEX_AUTH_MODE")
    capability = _load_capability()
    toolchain_identity = _toolchain_identity()
    source_root = Path(_required_environment("VERIGYM_VERILOG_EVAL_ROOT"))
    registries = build_registries()
    _verify_plugin_origins(registries)
    service = VeriGym(registries)
    source_config, source_snapshot, task_records = _freeze_source(
        service,
        config,
        source_root,
    )
    plan = _build_plan(
        config,
        model_id=model_id,
        capability=capability,
        source_snapshot=source_snapshot,
        task_records=task_records,
        registries=registries,
        toolchain_identity=toolchain_identity,
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


def _toolchain_identity() -> dict[str, Any]:
    tools: dict[str, dict[str, Any]] = {}
    for name in ("iverilog", "vvp"):
        info = detect_icarus(name)
        executable_sha256 = None
        if info.executable is not None:
            executable_sha256 = hashlib.sha256(Path(info.executable).read_bytes()).hexdigest()
        tools[name] = {
            "executable": info.executable,
            "executable_sha256": executable_sha256,
            "version": info.version,
            "compatibility": info.compatibility.value,
        }
    return {
        "schema_version": "1.0",
        "profile": "verilog-eval-v2-icarus-v12",
        "tools": tools,
        "reference_compatible": all(
            tool["compatibility"] == IcarusCompatibility.REFERENCE_COMPATIBLE.value
            for tool in tools.values()
        ),
    }


def _require_reference_compatible_toolchain(identity: dict[str, Any]) -> None:
    if identity.get("reference_compatible") is not True:
        versions = ", ".join(
            f"{name}={details.get('version') or 'unavailable'}"
            for name, details in identity["tools"].items()
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
    workspace_policy = _load_optional_json(artifact_root / "workspace_policy.json")
    violations = workspace_policy.get("violations")
    return bool(
        workspace_policy.get("policy_passed") is False
        and isinstance(violations, list)
        and violations
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
        "proxy_value_scan_passed": not proxy_value_hits,
        "proxy_value_hits": sorted(set(proxy_value_hits)),
        "proxy_values_persisted_or_hashed": False,
        "all_passed": not any((secret_hits, hidden_hits, host_path_hits, proxy_value_hits)),
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
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "toolchain_identity": toolchain_identity,
        "task_records": task_records,
        "sampling": config["sampling"],
        "execution": config["execution"],
        "planned_run_count": len(items),
        "items": items,
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
) -> RunConfig:
    task = next(record for record in task_records if record["id"] == item["task_id"])
    common: dict[str, Any] = {
        "task_id": item["task_id"],
        "suite_source": source_config,
        "expected_suite_source_snapshot": source_snapshot,
        "expected_task_hash": task["task_hash"],
        "expected_source_hash": task["source_hash"],
        "runtime": "local",
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
    )
    original = {name: os.environ.get(name) for name in protected_names}
    removed_credential_names = [name for name in protected_names[3:] if name in os.environ]
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
                    "codex_cli_process_count": 0,
                    "model_call_count": 0,
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
            and record["credential_home_file_count"] == 0
            for record in replay_records
        ),
        "all_run_integrity_verified": integrity_verified == 30,
        "candidate_freeze_unchanged": candidate_freeze["all_unchanged"],
        "source_immutable": source_integrity["passed"],
        "plan_immutable": plan_unchanged,
        "security_scans_passed": security_scans["all_passed"],
        "reference_compatible_toolchain": plan["toolchain_identity"]["reference_compatible"],
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
    return {
        "integration_track": identity.integration_track,
        "requested_model_id": identity.requested_model_id or "",
        "observed_model_id": identity.observed_model_id or "",
        "cli_version": identity.executable_version,
        "capability_fingerprint": identity.capability_fingerprint,
        "auth_semantic_id": identity.auth_semantic_id,
        "tool_use_policy": identity.tool_use_policy,
        "sandbox_policy": identity.sandbox_policy,
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
