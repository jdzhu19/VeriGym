#!/usr/bin/env python3
"""Freeze, and only when explicitly budgeted execute, the 30-run Codex CLI pilot."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
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
from verigym.core.sampling import classify_sample_outcome, compute_pass_at_k
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl
from verigym.provenance import get_build_provenance
from verigym.registry.collections import build_registries
from verigym.reporting.service import ReportService
from verigym.schemas.common import InteractionMode
from verigym.schemas.model import ModelRunConfig
from verigym.schemas.run import RunConfig, RunResult
from verigym.schemas.suite import SuiteSourceConfig

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
    infrastructure_failures = 0
    process_attempts = 0
    for item in plan["items"]:
        if (
            time.monotonic() - started >= budget["max_total_wall_time_s"]
            or (
                infrastructure_failures > 0
                and infrastructure_failures >= budget["max_failed_infrastructure_runs"]
            )
            or process_attempts >= budget["max_codex_processes"]
        ):
            execution_records.append(
                {
                    "plan_index": item["plan_index"],
                    "run_id": item["run_id"],
                    "terminal": False,
                    "error_category": "pilot_budget_exhausted",
                }
            )
            continue
        process_attempts += 1
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
        try:
            result = service.run(run_config)
            results.append(result)
            infrastructure = _is_infrastructure(result)
            infrastructure_failures += int(infrastructure)
            execution_records.append(
                {
                    "plan_index": item["plan_index"],
                    "run_id": result.manifest.run_id,
                    "run_dir": result.run_dir.relative_to(output).as_posix(),
                    "terminal": True,
                    "status": result.scorecard.status,
                    "resolved": result.scorecard.resolved,
                    "infrastructure_error": infrastructure,
                    "failure": (
                        result.scorecard.failure.model_dump(mode="json")
                        if result.scorecard.failure is not None
                        else None
                    ),
                }
            )
        except Exception as exc:
            infrastructure_failures += 1
            execution_records.append(
                {
                    "plan_index": item["plan_index"],
                    "run_id": item["run_id"],
                    "terminal": False,
                    "error_category": type(exc).__name__,
                    "message": str(exc)[:1024],
                }
            )
    atomic_dump_jsonl(evidence_root / "execution_results.jsonl", execution_records)
    if plan_path.read_bytes() != plan_bytes:
        raise RuntimeError("frozen pilot plan changed during execution")

    replay_records = _replay_without_codex(results)
    atomic_dump_jsonl(evidence_root / "replay_results.jsonl", replay_records)
    reports = ReportService().generate_all(
        runs_root,
        output_dir=reports_root,
        group_by=(
            "task_id",
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
        report_coverage=reports.aggregate.coverage.model_dump(mode="json"),
    )
    atomic_dump_json(evidence_root / "pilot_results.json", pilot_report)
    print(json.dumps(pilot_report, indent=2, sort_keys=True))
    return 0 if pilot_report["execution_complete"] else 1


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
        "codex_cli_model_proxy",
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
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for track in config["tracks"]:
        for task in task_records:
            native = task["id"].rsplit("/", 1)[1]
            for sample_index in config["sampling"]["sample_indices"]:
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
        "verigym_version": "0.1.0",
        "verigym_commit": provenance.source_commit,
        "verigym_source_tree_hash": provenance.source_tree_hash,
        "plugin_origins": {
            "model": registries.models.origin("codex-cli-exec-model").__dict__,
            "agent": registries.agents.origin("codex-cli-agent").__dict__,
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
    if item["track"] == "codex_cli_model_proxy":
        return RunConfig(
            **common,
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model="codex-cli-exec-model",
            model_options=ModelRunConfig(
                model_id=model_id,
                sample_index=item["sample_index"],
                request_timeout_s=max_process_time_s,
                client_options={
                    "sandbox": "most-restrictive-supported",
                    "approval_policy": "non-interactive",
                    "reject_tool_use": True,
                    "max_process_time_s": max_process_time_s,
                },
            ),
        )
    return RunConfig(
        **common,
        mode=InteractionMode.AGENT,
        agent="codex-cli-agent",
        agent_options={
            "model_id": model_id,
            "sandbox": "workspace-write",
            "approval_policy": "non-interactive",
            "max_process_time_s": max_process_time_s,
        },
    )


def _replay_without_codex(results: list[RunResult]) -> list[dict[str, Any]]:
    original = os.environ.get("VERIGYM_CODEX_BINARY")
    os.environ["VERIGYM_CODEX_BINARY"] = "/codex-must-not-run-during-replay"
    records: list[dict[str, Any]] = []
    try:
        for result in results:
            try:
                replay = replay_run(result.run_dir, verify=True)
                records.append(
                    {
                        "run_id": result.manifest.run_id,
                        "success": True,
                        "reverified_resolved": replay.reverified_resolved,
                        "codex_available": False,
                    }
                )
            except Exception as exc:
                records.append(
                    {
                        "run_id": result.manifest.run_id,
                        "success": False,
                        "error_category": type(exc).__name__,
                        "message": str(exc)[:1024],
                        "codex_available": False,
                    }
                )
    finally:
        if original is None:
            os.environ.pop("VERIGYM_CODEX_BINARY", None)
        else:
            os.environ["VERIGYM_CODEX_BINARY"] = original
    return records


def _pilot_report(
    plan: dict[str, Any],
    results: list[RunResult],
    execution_records: list[dict[str, Any]],
    replay_records: list[dict[str, Any]],
    *,
    elapsed_s: float,
    report_coverage: dict[str, Any],
) -> dict[str, Any]:
    grouped: dict[tuple[str, ...], list[RunResult]] = defaultdict(list)
    tool_violations = 0
    external_commands = 0
    external_tools = 0
    secret_hits: list[str] = []
    hidden_hits: list[str] = []
    for result in results:
        identity = _result_identity(result)
        key = (
            result.manifest.task_id,
            identity["integration_track"],
            identity["requested_model_id"],
            identity["observed_model_id"],
            identity["cli_version"],
            identity["capability_fingerprint"],
            str(result.manifest.base_seed),
        )
        grouped[key].append(result)
        if identity["integration_track"] == "codex_cli_model_proxy":
            summary = json.loads(
                (result.run_dir / "artifacts" / "codex_cli" / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            tool_violations += int(summary.get("tool_use_event_count") or 0)
        else:
            external_commands += int(result.scorecard.efficiency.external_command_count or 0)
            external_tools += int(result.scorecard.efficiency.external_tool_call_count or 0)
        for visible in (
            result.run_dir / "candidate",
            result.run_dir / "artifacts" / "codex_cli",
            result.run_dir / "trace.jsonl",
        ):
            paths = [visible] if visible.is_file() else list(visible.rglob("*"))
            for path in paths:
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                relative = path.relative_to(result.run_dir).as_posix()
                if _SECRET_PATTERN.search(text):
                    secret_hits.append(f"{result.manifest.run_id}/{relative}")
                if "RefModule" in text or "Mismatches:" in text:
                    hidden_hits.append(f"{result.manifest.run_id}/{relative}")
    pass_at_k = []
    for key, children in sorted(grouped.items()):
        evaluable = all(not _is_infrastructure(child) for child in children)
        canonical = len(children) == 3 and evaluable
        resolved = sum(child.scorecard.resolved for child in children)
        pass_at_k.append(
            {
                "task_id": key[0],
                "integration_track": key[1],
                "requested_model_id": key[2],
                "observed_model_id": key[3] or None,
                "cli_version": key[4],
                "capability_fingerprint": key[5],
                "base_seed": int(key[6]),
                "sample_count": len(children),
                "resolved_count": resolved,
                "canonical_valid": canonical,
                "values": {
                    str(k): compute_pass_at_k(3, resolved, k) if canonical else None
                    for k in (1, 2, 3)
                },
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
    return {
        "schema_version": "1.0",
        "study_label": "integration_study_not_direct_api_benchmark",
        "no_universal_score": True,
        "planned_runs": plan["planned_run_count"],
        "terminal_runs": terminal,
        "resolved_runs": sum(result.scorecard.resolved for result in results),
        "evaluable_runs": sum(not _is_infrastructure(result) for result in results),
        "infrastructure_failures": infrastructure,
        "execution_complete": terminal == 30 and infrastructure == 0 and policy_failures == 0,
        "policy_failure_count": policy_failures,
        "elapsed_s": elapsed_s,
        "known_total_tokens": sum(
            result.scorecard.efficiency.total_tokens or 0 for result in results
        ),
        "missing_token_run_count": sum(
            result.scorecard.efficiency.total_tokens is None for result in results
        ),
        "track_a_tool_use_violations": tool_violations,
        "track_b_external_command_count": external_commands,
        "track_b_external_tool_count": external_tools,
        "candidate_changed_files": sum(
            len(result.scorecard.patch.changed_files) for result in results
        ),
        "candidate_diff_lines": sum(result.scorecard.patch.total_diff_lines for result in results),
        "pass_at_k_partitions": pass_at_k,
        "replay_success_count": sum(record["success"] for record in replay_records),
        "hidden_asset_scan_passed": not hidden_hits,
        "hidden_asset_hits": sorted(set(hidden_hits)),
        "secret_scan_passed": not secret_hits,
        "secret_hits": sorted(set(secret_hits)),
        "integrity_verified_count": sum(
            verify_artifact_manifest(result.run_dir, expected_scope="run").status == "verified"
            for result in results
        ),
        "ppa_non_null_count": sum(result.scorecard.quality.ppa is not None for result in results),
        "report_coverage": report_coverage,
    }


def _result_identity(result: RunResult) -> dict[str, str]:
    manifest = result.manifest
    if manifest.external_agent_observations:
        identity = manifest.external_agent_observations[-1]
        return {
            "integration_track": "codex_cli_external_agent",
            "requested_model_id": identity.requested_model_id or "",
            "observed_model_id": identity.observed_model_id or "",
            "cli_version": identity.executable_version,
            "capability_fingerprint": identity.capability_fingerprint,
        }
    assert manifest.model is not None
    configuration = manifest.model.configuration
    observed = (
        manifest.model_observations[-1].observed_provider_model_id
        if manifest.model_observations
        else None
    )
    return {
        "integration_track": "codex_cli_model_proxy",
        "requested_model_id": manifest.model.model_id,
        "observed_model_id": observed or "",
        "cli_version": str(configuration.get("cli_version") or ""),
        "capability_fingerprint": str(configuration.get("capability_fingerprint") or ""),
    }


def _is_infrastructure(result: RunResult) -> bool:
    score = result.scorecard
    outcome, _verdict = classify_sample_outcome(score)
    return (
        score.status == "error"
        or score.correctness.infrastructure_error
        or bool(score.failure and score.failure.infrastructure)
        or outcome.value in {"infrastructure_error", "cancelled_truncated"}
    )


def _verify_plugin_origins(registries: Any) -> None:
    for registry, name in (
        (registries.models, "codex-cli-exec-model"),
        (registries.agents, "codex-cli-agent"),
    ):
        origin = registry.origin(name)
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
