#!/usr/bin/env python3
"""Execute the fixed four-run Codex CLI conformance smoke exactly once."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash, hash_directory
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl
from verigym.provenance import get_build_provenance
from verigym.registry.collections import build_registries
from verigym.reporting.service import ReportService
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunResult

_TASKS = ("toy-rtl/and-gate-basic", "toy-rtl/counter-basic")
_TRACKS = (
    "codex_cli_readonly_single_turn_agent",
    "codex_cli_external_agent",
)
_EXPECTED_PACKAGE = "verigym-codex-cli"
_REASONING_EFFORT = "xhigh"
_REASONING_EFFORT_SOURCE = "verigym_explicit_cli_override"
_MAX_PROCESS_TIME_S = 300
_MAX_CAMPAIGN_OVERHEAD_S = 10 * 60
_MAX_TOTAL_WALL_TIME_S = len(_TASKS) * len(_TRACKS) * _MAX_PROCESS_TIME_S + _MAX_CAMPAIGN_OVERHEAD_S
_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]{8,}|\bsk-[A-Za-z0-9_-]{12,}|"
    r"(token|secret|password|credential)[\"'=:\s]+[^\s,\"'}]+)"
)
_HIDDEN_NAMES = ("tb_and_gate.sv", "tb_counter.sv", "check_result.py")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if os.environ.get("VERIGYM_RUN_CODEX_CLI_TESTS") != "1":
        raise SystemExit("VERIGYM_RUN_CODEX_CLI_TESTS=1 is required")
    model_id = _required_environment("VERIGYM_CODEX_MODEL")
    _required_environment("VERIGYM_CODEX_BINARY")
    auth_label = _required_environment("VERIGYM_CODEX_AUTH_MODE")
    from verigym_codex_cli import resolve_auth_mode

    auth_identity = resolve_auth_mode(auth_label).safe_dict()
    capability_path = Path(_required_environment("VERIGYM_CODEX_CAPABILITY_FILE"))
    if not capability_path.is_file() or capability_path.is_symlink():
        raise SystemExit("VERIGYM_CODEX_CAPABILITY_FILE must be a sealed regular file")
    root = arguments.output.expanduser().resolve()
    if root.exists():
        raise SystemExit(f"smoke output already exists: {root}")
    root.mkdir(parents=True)
    runs_root = root / "runs"
    runs_root.mkdir()
    reports_root = root / "reports"
    evidence_root = root / "evidence"
    evidence_root.mkdir()

    registries = build_registries()
    _verify_plugin_origins(registries)
    service = VeriGym(registries)
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    plan = _frozen_plan(service, model_id, capability, registries, auth_identity)
    atomic_dump_json(root / "smoke_plan.json", plan)
    plan_bytes = (root / "smoke_plan.json").read_bytes()
    plan_hash = content_hash(plan)

    started = time.monotonic()
    results: list[RunResult] = []
    execution_records: list[dict[str, Any]] = []
    for item in plan["items"]:
        if time.monotonic() - started >= _MAX_TOTAL_WALL_TIME_S:
            execution_records.append(
                {
                    "run_id": item["run_id"],
                    "terminal": False,
                    "error_category": "smoke_wall_time_limit",
                }
            )
            continue
        config = _run_config(item, model_id, runs_root)
        try:
            result = service.run(config)
            results.append(result)
            execution_records.append(
                {
                    "run_id": result.manifest.run_id,
                    "run_dir": result.run_dir.relative_to(root).as_posix(),
                    "terminal": True,
                    "status": result.scorecard.status,
                    "resolved": result.scorecard.resolved,
                    "infrastructure_error": (
                        result.scorecard.status == "error"
                        or result.scorecard.correctness.infrastructure_error
                        or bool(
                            result.scorecard.failure and result.scorecard.failure.infrastructure
                        )
                    ),
                    "failure": (
                        result.scorecard.failure.model_dump(mode="json")
                        if result.scorecard.failure is not None
                        else None
                    ),
                }
            )
        except Exception as exc:
            execution_records.append(
                {
                    "run_id": item["run_id"],
                    "terminal": False,
                    "error_category": type(exc).__name__,
                    "message": str(exc)[:1024],
                }
            )
    atomic_dump_jsonl(evidence_root / "execution_results.jsonl", execution_records)
    if (root / "smoke_plan.json").read_bytes() != plan_bytes:
        raise RuntimeError("frozen smoke plan changed during execution")

    replay_records = _replay_without_codex(results)
    atomic_dump_jsonl(evidence_root / "replay_results.jsonl", replay_records)
    reports = ReportService().generate_all(
        runs_root,
        output_dir=reports_root,
        group_by=(
            "integration_track",
            "requested_model_id",
            "cli_version",
            "capability_fingerprint",
            "requested_reasoning_effort",
            "effective_reasoning_effort",
            "reasoning_effort_source",
            "inherited_reasoning_effort_allowed",
            "execution_surface",
            "interaction_class",
            "harness_id",
            "tool_availability_policy",
            "tool_use_policy",
        ),
    )
    scans = _scan_evidence(root, results)
    atomic_dump_json(evidence_root / "scan_results.json", scans)
    acceptance = _acceptance(
        plan=plan,
        plan_hash=plan_hash,
        results=results,
        execution_records=execution_records,
        replay_records=replay_records,
        scans=scans,
        report_coverage=reports.aggregate.coverage.model_dump(mode="json"),
        elapsed_s=time.monotonic() - started,
    )
    atomic_dump_json(evidence_root / "smoke_acceptance.json", acceptance)
    print(json.dumps(acceptance, indent=2, sort_keys=True))
    return 0 if acceptance["gate"] == "PASS" else 1


def _frozen_plan(
    service: VeriGym,
    model_id: str,
    capability: dict[str, Any],
    registries: Any,
    auth_identity: dict[str, str | bool],
) -> dict[str, Any]:
    task_records = []
    for task_id in _TASKS:
        _suite, task, assets = service.load_task(task_id)
        task_records.append(
            {
                "task_id": task_id,
                "task_hash": content_hash(task),
                "source_hash": task.source.content_hash
                or hash_directory(Path(assets.visible_root)),
            }
        )
    items = []
    for track in _TRACKS:
        for task_id in _TASKS:
            suffix = task_id.rsplit("/", 1)[1]
            items.append(
                {
                    "index": len(items),
                    "track": track,
                    "task_id": task_id,
                    "run_id": f"codex-cli-smoke-{track}-{suffix}",
                    "model_id": model_id,
                    "reasoning_effort": _REASONING_EFFORT,
                    "seed": 0,
                    "sample_index": 0,
                    "retry_count": 0,
                    "best_of_k": None,
                }
            )
    provenance = get_build_provenance()
    return {
        "schema_version": "1.0",
        "name": "codex-cli-four-run-conformance-smoke",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "verigym_version": "0.1.0",
        "verigym_commit": provenance.source_commit,
        "verigym_source_tree_hash": provenance.source_tree_hash,
        "plugin_origins": {
            "readonly_agent": registries.agents.origin("codex-cli-readonly-agent").__dict__,
            "workspace_agent": registries.agents.origin("codex-cli-agent").__dict__,
        },
        "capability_identity": {
            "executable_name": capability["executable_name"],
            "executable_sha256": capability["executable_sha256"],
            "version_output": capability["version_output"],
            "capability_fingerprint": capability["capability_fingerprint"],
            "model_call_count": capability["model_call_count"],
        },
        "requested_model_id": model_id,
        "requested_reasoning_effort": _REASONING_EFFORT,
        "effective_reasoning_effort": _REASONING_EFFORT,
        "reasoning_effort_source": _REASONING_EFFORT_SOURCE,
        "inherited_reasoning_effort_allowed": False,
        "direct_llm_api_evaluation_implemented": False,
        "direct_llm_api_evaluation_executed": False,
        "direct_llm_api_evaluation_reason": (
            "no direct API credential/transport was authorized; Codex CLI is an agent harness"
        ),
        **auth_identity,
        "task_records": task_records,
        "planned_run_count": 4,
        "maximum_codex_model_processes": 4,
        "maximum_total_wall_time_s": _MAX_TOTAL_WALL_TIME_S,
        "allow_retry": False,
        "allow_best_of_k_selection": False,
        "allow_outer_agent_repair": False,
        "items": items,
    }


def _run_config(item: dict[str, Any], model_id: str, output: Path) -> RunConfig:
    common = {
        "task_id": item["task_id"],
        "runtime": "local",
        "seed": item["seed"],
        "sample_index": item["sample_index"],
        "output": output,
        "run_id": item["run_id"],
    }
    if item["track"] == "codex_cli_readonly_single_turn_agent":
        return RunConfig(
            **common,
            mode=InteractionMode.AGENT,
            agent="codex-cli-readonly-agent",
            agent_options={
                "model_id": model_id,
                "sandbox": "most-restrictive-supported",
                "approval_policy": "non-interactive",
                "reasoning_effort": _REASONING_EFFORT,
                "allow_proxy_environment": True,
                "max_process_time_s": _MAX_PROCESS_TIME_S,
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
            "reasoning_effort": _REASONING_EFFORT,
            "allow_proxy_environment": True,
            "max_process_time_s": _MAX_PROCESS_TIME_S,
        },
    )


def _replay_without_codex(results: list[RunResult]) -> list[dict[str, Any]]:
    protected_names = (
        "VERIGYM_CODEX_BINARY",
        "VERIGYM_CODEX_AUTH_MODE",
        "VERIGYM_CODEX_CREDENTIAL_ENV",
        "OPENAI_API_KEY",
    )
    original = {name: os.environ.get(name) for name in protected_names}
    os.environ["VERIGYM_CODEX_BINARY"] = "/codex-must-not-run-during-replay"
    for name in protected_names[1:]:
        os.environ.pop(name, None)
    records = []
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
                        "credential_environment_available": False,
                        "codex_cli_process_count": 0,
                        "model_call_count": 0,
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
                        "credential_environment_available": False,
                        "codex_cli_process_count": 0,
                        "model_call_count": 0,
                    }
                )
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return records


def _scan_evidence(root: Path, results: list[RunResult]) -> dict[str, Any]:
    home = str(Path.home())
    repository = str(Path.cwd().resolve())
    secret_hits: list[str] = []
    host_path_hits: list[str] = []
    hidden_hits: list[str] = []
    proxy_value_hits: list[str] = []
    proxy_values = tuple(
        value
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
        if (value := os.environ.get(name))
    )
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if (
            not path.is_file()
            or path.suffix in {".vvp", ".bin"}
            or relative.endswith("/compile_hidden/executable")
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        if _SECRET_PATTERN.search(text):
            secret_hits.append(relative)
        if home in text or repository in text or "/tmp/verigym-" in text:
            host_path_hits.append(relative)
        if any(value in text for value in proxy_values):
            proxy_value_hits.append(relative)
    for result in results:
        visible_paths = [
            result.run_dir / "candidate",
            result.run_dir / "artifacts" / "codex_cli",
            result.run_dir / "trace.jsonl",
            result.run_dir / "logs" / "agent.log",
        ]
        for visible in visible_paths:
            files = [visible] if visible.is_file() else list(visible.rglob("*"))
            for path in files:
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if any(name in text or name in path.name for name in _HIDDEN_NAMES):
                    hidden_hits.append(path.relative_to(root).as_posix())
    return {
        "secret_scan_passed": not secret_hits,
        "secret_hits": secret_hits,
        "host_path_scan_passed": not host_path_hits,
        "host_path_hits": host_path_hits,
        "hidden_asset_scan_passed": not hidden_hits,
        "hidden_asset_hits": hidden_hits,
        "proxy_value_scan_passed": not proxy_value_hits,
        "proxy_value_hits": proxy_value_hits,
        "proxy_values_persisted": False,
        "proxy_values_hashed": False,
    }


def _acceptance(
    *,
    plan: dict[str, Any],
    plan_hash: str,
    results: list[RunResult],
    execution_records: list[dict[str, Any]],
    replay_records: list[dict[str, Any]],
    scans: dict[str, Any],
    report_coverage: dict[str, Any],
    elapsed_s: float,
) -> dict[str, Any]:
    infrastructure_failures = sum(
        bool(record.get("infrastructure_error")) or not record.get("terminal", False)
        for record in execution_records
    )
    track_a = [
        result for result in results if result.manifest.agent.name == "codex-cli-readonly-agent"
    ]
    track_b = [result for result in results if result.manifest.agent.name == "codex-cli-agent"]
    identities = [_load_codex_identity(result) for result in results]
    checks = {
        "planned_runs_4": plan["planned_run_count"] == 4,
        "terminal_runs_4": len(results) == 4
        and all(record.get("terminal") for record in execution_records),
        "infrastructure_failures_0": infrastructure_failures == 0,
        "unique_run_ids_4": len({result.manifest.run_id for result in results}) == 4,
        "unique_run_workspaces_4": len({result.run_dir.resolve() for result in results}) == 4,
        "candidate_snapshots_4": all((result.run_dir / "candidate").is_dir() for result in results),
        "integrity_verified_4": all(
            verify_artifact_manifest(result.run_dir, expected_scope="run").status == "verified"
            for result in results
        ),
        "ordinary_candidate_submission_4": len(results) == 4
        and all(
            result.scorecard.termination_reason == "final_submission"
            and result.scorecard.failure is None
            and bool(result.scorecard.verifier_results)
            for result in results
        ),
        "identity_evidence_4": len(identities) == 4
        and all(
            identity is not None
            and identity.get("requested_model_id") == plan["requested_model_id"]
            and identity.get("executable_sha256")
            == plan["capability_identity"]["executable_sha256"]
            and identity.get("capability_fingerprint")
            == plan["capability_identity"]["capability_fingerprint"]
            and identity.get("requested_auth_mode") == plan["requested_auth_mode"]
            and identity.get("resolved_auth_mode") == plan["resolved_auth_mode"]
            and identity.get("auth_semantic_id") == plan["auth_semantic_id"]
            and identity.get("auth_alias_used") == plan["auth_alias_used"]
            and identity.get("requested_reasoning_effort") == plan["requested_reasoning_effort"]
            and identity.get("effective_reasoning_effort") == plan["effective_reasoning_effort"]
            and identity.get("reasoning_effort_source") == plan["reasoning_effort_source"]
            and identity.get("inherited_reasoning_effort_allowed")
            == plan["inherited_reasoning_effort_allowed"]
            and identity.get("invocation_count") == 1
            and identity.get("identity_confidence") in {"observed", "requested_only", "unknown"}
            and identity.get("execution_surface") == "codex_cli"
            and identity.get("model_client_kind") == "cli_agent_mediated"
            and identity.get("agent_harness_kind") == "codex_cli"
            and identity.get("chat_eval_compatible") is False
            and identity.get("pure_api_model_eval") is False
            and identity.get("direct_api_benchmark") is False
            for identity in identities
        ),
        "track_a_count_2": len(track_a) == 2,
        "track_a_semantic_identity": len(track_a) == 2
        and all(
            (identity := _load_codex_identity(result)) is not None
            and identity.get("integration_track") == "codex_cli_readonly_single_turn_agent"
            and identity.get("interaction_class") == "cli_agent_single_turn_readonly"
            and identity.get("tool_use_policy") == "typed_readonly_empty_workdir_v1"
            and (result.run_dir / "artifacts" / "codex_cli" / "event_policy.json").is_file()
            for result in track_a
        ),
        "track_a_complete_final_response_and_policy": len(track_a) == 2
        and all(
            (
                lambda summary: (
                    summary.get("complete_final_response") is True
                    and summary.get("candidate_parsed") is True
                    and summary.get("tool_policy_passed") is True
                    and summary.get("side_effecting_tool_event_count") == 0
                    and summary.get("external_network_tool_event_count") == 0
                    and summary.get("mcp_tool_event_count") == 0
                    and summary.get("workspace_write_count") == 0
                )
            )(
                json.loads(
                    (result.run_dir / "artifacts" / "codex_cli" / "summary.json").read_text(
                        encoding="utf-8"
                    )
                )
            )
            for result in track_a
        ),
        "track_b_count_2": len(track_b) == 2,
        "track_b_semantic_identity": len(track_b) == 2
        and all(
            (identity := _load_codex_identity(result)) is not None
            and identity.get("integration_track") == "codex_cli_external_agent"
            and identity.get("interaction_class") == "cli_agent_workspace_writing"
            and identity.get("tool_use_policy") == "visible_task_workspace_policy_v2"
            for result in track_b
        ),
        "track_b_identity_and_accounting": len(track_b) == 2
        and all(
            result.manifest.external_agent_observations
            and result.scorecard.efficiency.external_cli_event_count > 0
            for result in track_b
        ),
        "replay_4_without_codex": len(replay_records) == 4
        and all(
            record["success"]
            and not record["codex_available"]
            and not record["credential_environment_available"]
            and record["codex_cli_process_count"] == 0
            and record["model_call_count"] == 0
            for record in replay_records
        ),
        "reports_cover_4": report_coverage.get("planned_plan_items") == 4
        and report_coverage.get("terminal_child_runs") == 4,
        "ppa_null_without_profile": all(result.scorecard.quality.ppa is None for result in results),
        "secret_scan": scans["secret_scan_passed"],
        "host_path_scan": scans["host_path_scan_passed"],
        "hidden_asset_scan": scans["hidden_asset_scan_passed"],
        "proxy_value_scan": scans["proxy_value_scan_passed"],
        "direct_api_unimplemented_unexecuted": (
            plan["direct_llm_api_evaluation_implemented"] is False
            and plan["direct_llm_api_evaluation_executed"] is False
        ),
        "wall_time_within_declared_limit": elapsed_s <= _MAX_TOTAL_WALL_TIME_S,
    }
    return {
        "schema_version": "1.0",
        "gate": "PASS" if all(checks.values()) else "FAIL",
        "plan_hash": plan_hash,
        "checks": checks,
        "planned_runs": plan["planned_run_count"],
        "terminal_runs": len(results),
        "infrastructure_failures": infrastructure_failures,
        "elapsed_s": elapsed_s,
        "run_directories": [
            str(record["run_dir"])
            for record in execution_records
            if record.get("terminal") and record.get("run_dir")
        ],
    }


def _load_codex_identity(result: RunResult) -> dict[str, Any] | None:
    path = result.run_dir / "artifacts" / "codex_cli" / "identity.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _verify_plugin_origins(registries: Any) -> None:
    for registry, name in (
        (registries.agents, "codex-cli-readonly-agent"),
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
