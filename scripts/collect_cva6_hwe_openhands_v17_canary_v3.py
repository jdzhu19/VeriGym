#!/usr/bin/env python3
"""Run the frozen three-task OpenHands v17 collection canary without retries."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_v17_canary_v3 import (
    OPENHANDS_V17_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V17_CANARY_API_KEY_ENV,
    OPENHANDS_V17_CANARY_BASE_URL_ENV,
    OPENHANDS_V17_CANARY_CAMPAIGN_ID,
    OPENHANDS_V17_CANARY_GATE_FORMAT,
    OPENHANDS_V17_CANARY_LITELLM_VERSION,
    OPENHANDS_V17_CANARY_MODEL,
    OPENHANDS_V17_CANARY_MODEL_IDENTITY,
    OPENHANDS_V17_CANARY_OPT_IN_ENV,
    OPENHANDS_V17_CANARY_REPORT_FORMAT,
    OPENHANDS_V17_CANARY_SDK_VERSION,
    OPENHANDS_V17_CANARY_TASKS,
    OPENHANDS_V17_CANARY_TIKTOKEN_VERSION,
    OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY,
    build_v17_canary_agent_options,
    build_v17_canary_agent_version,
    derive_v17_v3_task_split,
    evaluate_v17_canary_gate,
    load_v17_canary_contract,
    seal_v17_canary_report,
    validate_v17_canary_source,
    validate_v17_runtime_evidence,
)
from verigym_openhands.trajectory import validate_openhands_training_trajectory

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.evolution.splits import validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweAgentImageLock
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import TaskSplitEntry, TaskSplitManifest
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_recovery = importlib.import_module(
    "scripts.run_cva6_hwe_openhands_recovery_diagnostic"
    if __package__
    else "run_cva6_hwe_openhands_recovery_diagnostic"
)
_docker_config = _collection._docker_config
_infrastructure_invalid = _collection._infrastructure_invalid
_clean_source_commit = _recovery._clean_source_commit
_json = _recovery._json
_new_output = _recovery._new_output

OPENHANDS_V17_CANARY_IMAGE_LOCK_RECEIPT_FORMAT = "verigym_openhands_hwe_v17_canary_image_locks_v3"
OPENHANDS_V17_CANARY_SECURITY_REPORT_PREFIX = "openhands-hwe-v17-canary-v3"
OPENHANDS_V17_CANARY_PREFLIGHT_PREFIX = "openhands-v17-canary-v3-preflight"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--training-image-lock-dir", type=Path, required=True)
    parser.add_argument("--validation-image-lock-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", default=OPENHANDS_V17_CANARY_CAMPAIGN_ID)
    return parser


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the frozen schedule and stop on invalid infrastructure or evidence."""

    _require_opt_in(arguments.campaign_id)
    source_commit = _clean_source_commit()
    contract = load_v17_canary_contract(arguments.contract.resolve(strict=True))
    qualification = arguments.qualification_root.resolve(strict=True)
    split = validate_task_split(
        TaskSplitManifest.model_validate(_json(qualification / "task-split.json"))
    )
    try:
        validate_v17_canary_source(
            contract,
            split=split,
            task_split_path=qualification / "task-split.json",
            qualification_progress_path=qualification / "qualification-progress.json",
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    progress = _json(qualification / "qualification-progress.json")
    if progress.get("status") != "completed" or progress.get("task_split_hash") != (
        split.manifest_hash
    ):
        raise ConfigurationError("OpenHands v17 canary qualification is incomplete or changed")
    derived_split = derive_v17_v3_task_split(split)
    source_by_task = _qualified_sources(progress)
    entries = {
        entry.task_id: entry
        for entry in (*derived_split.training, *derived_split.validation)
        if entry.task_id in OPENHANDS_V17_CANARY_TASKS
    }
    if set(entries) != set(OPENHANDS_V17_CANARY_TASKS):
        raise ConfigurationError("OpenHands v17 canary split lacks a scheduled task")
    locks = _load_locks(
        contract,
        training_dir=arguments.training_image_lock_dir.resolve(strict=True),
        validation_dir=arguments.validation_image_lock_dir.resolve(strict=True),
    )
    agent_version = build_v17_canary_agent_version(
        source_commit=source_commit,
        image_locks=locks,
    )

    root = _new_output(arguments.output)
    runs = root / "runs"
    scans = root / "security-scans"
    runs.mkdir(mode=0o700)
    scans.mkdir(mode=0o700)
    atomic_dump_json(root / "agent-version.json", agent_version)
    image_receipt = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_CANARY_IMAGE_LOCK_RECEIPT_FORMAT,
        "locks": {
            task_id: {
                "lock_hash": lock.lock_hash,
                "agent_image": lock.derived_agent_image_id,
                "verifier_image": lock.verifier_base_image_id,
            }
            for task_id, lock in locks.items()
        },
    }
    atomic_dump_json(
        root / "image-lock-receipt.json",
        {**image_receipt, "receipt_hash": content_hash(image_receipt)},
    )
    base_report = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_CANARY_REPORT_FORMAT,
        "campaign_id": arguments.campaign_id,
        "status": "canary_running",
        "contract_hash": contract["contract_hash"],
        "source_commit": source_commit,
        "source_task_split_hash": split.manifest_hash,
        "derived_task_split_id": derived_split.split_id,
        "task_split_hash": derived_split.manifest_hash,
        "schedule": contract["schedule"],
        "heldout_task_ids_loaded": [],
        "model_transport_id": OPENHANDS_V17_CANARY_MODEL,
        "model_identity": OPENHANDS_V17_CANARY_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_V17_CANARY_AGENT_VERSION_ID,
        "agent_version_hash": agent_version.version_hash,
        "openhands_sdk_version": OPENHANDS_V17_CANARY_SDK_VERSION,
        "litellm_version": OPENHANDS_V17_CANARY_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_V17_CANARY_TIKTOKEN_VERSION,
        "temperature": 0,
        "top_p": 1,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "tool_schema_count": 6,
        "tool_choice_policy": OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY,
        "attempts": [],
        "benchmark_score_claimed": False,
        "production_training_ready": False,
        "formal_collection_allowed": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "hpc_jobs_submitted": False,
        "gpu_seconds": 0,
    }
    atomic_dump_json(root / "preregistration.json", seal_v17_canary_report(base_report))
    atomic_dump_json(root / "canary-progress.json", seal_v17_canary_report(base_report))

    try:
        _zero_call_preflight(locks)
    except Exception as exc:
        _stop(root, base_report, [], f"zero_call_preflight:{type(exc).__name__}")
        raise ConfigurationError("OpenHands v17 canary Docker preflight failed") from exc

    service = _service()
    attempts: list[dict[str, Any]] = []
    for episode in contract["schedule"]:
        try:
            attempt = _run_episode(
                service=service,
                episode=episode,
                qualification=qualification,
                source_relative=source_by_task[str(episode["task_id"])],
                entry=entries[str(episode["task_id"])],
                lock=locks[str(episode["task_id"])],
                runs=runs,
                scans=scans,
                root=root,
                campaign_id=arguments.campaign_id,
                source_commit=source_commit,
                agent_version=agent_version,
                agent_options_builder=build_v17_canary_agent_options,
                runtime_evidence_validator=validate_v17_runtime_evidence,
                system_id=OPENHANDS_V17_CANARY_AGENT_VERSION_ID,
                security_report_prefix=OPENHANDS_V17_CANARY_SECURITY_REPORT_PREFIX,
            )
        except Exception as exc:
            reason = f"{episode['episode_id']}:{type(exc).__name__}"
            invalid_attempt = {
                "episode_id": episode["episode_id"],
                "role": episode["role"],
                "task_id": episode["task_id"],
                "seed": episode["seed"],
                "sample_index": episode["sample_index"],
                "status": "infrastructure_or_security_invalid",
                "infrastructure_valid": False,
                "runtime_evidence_valid": False,
                "security_scan_passed": False,
                "recovery_accounting_valid": False,
                "ordinary_verifier_resolved": False,
                "fresh_exact_trajectory": False,
                "truncation_applied": False,
                "failure_boundary": type(exc).__name__,
            }
            _stop(root, base_report, [*attempts, invalid_attempt], reason)
            if isinstance(exc, ConfigurationError):
                raise
            raise ConfigurationError(
                f"OpenHands v17 canary stopped on {episode['episode_id']}"
            ) from exc
        attempts.append(attempt)
        progress_report = {**base_report, "attempts": attempts, "status": "canary_running"}
        atomic_dump_json(root / "canary-progress.json", seal_v17_canary_report(progress_report))

    gate = evaluate_v17_canary_gate(attempts)
    gate_payload = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_CANARY_GATE_FORMAT,
        **asdict(gate),
        "attempt_count": len(attempts),
        "heldout_episodes_collected": 0,
        "benchmark_score_claimed": False,
        "production_training_ready": False,
    }
    atomic_dump_json(
        root / "canary-gate.json",
        {**gate_payload, "gate_hash": content_hash(gate_payload)},
    )
    final = seal_v17_canary_report(
        {
            **base_report,
            "status": (
                "canary_passed_formal_collection_allowed"
                if gate.formal_collection_allowed
                else "canary_completed_fail_closed"
            ),
            "attempts": attempts,
            "canary_passed": gate.canary_passed,
            "formal_collection_allowed": gate.formal_collection_allowed,
            "gate_failure_reason": gate.reason,
            "heldout_episodes_collected": 0,
        }
    )
    atomic_dump_json(root / "canary-progress.json", final)
    atomic_dump_json(root / "canary-report.json", final)
    return final


def _run_episode(
    *,
    service: VeriGym,
    episode: dict[str, Any],
    qualification: Path,
    source_relative: str,
    entry: TaskSplitEntry,
    lock: HweAgentImageLock,
    runs: Path,
    scans: Path,
    root: Path,
    campaign_id: str,
    source_commit: str,
    agent_version: Any,
    agent_options_builder: Any,
    runtime_evidence_validator: Any,
    system_id: str,
    security_report_prefix: str,
) -> dict[str, Any]:
    task_id = str(episode["task_id"])
    source_root = (qualification / source_relative).resolve(strict=True)
    if not source_root.is_relative_to(qualification):
        raise ConfigurationError("OpenHands v17 canary source escaped qualification root")
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(task_id, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != entry.task_hash
        or task.source.content_hash != entry.source_hash
    ):
        raise ConfigurationError("OpenHands v17 canary loaded source changed")
    seed = int(episode["seed"])
    sample_index = int(episode["sample_index"])
    run_id = str(episode["episode_id"])
    started = time.monotonic()
    result = service.run(
        RunConfig(
            task_id=task_id,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=entry.task_hash,
            expected_source_hash=entry.source_hash,
            mode=InteractionMode.AGENT,
            agent="openhands-hwe-agent",
            agent_options=agent_options_builder(
                seed=seed,
                agent_version=agent_version,
            ),
            runtime="docker",
            docker_config=_docker_config(lock),
            seed=seed,
            sample_index=sample_index,
            output=runs,
            run_id=run_id,
            experiment_id=campaign_id,
            plan_item_id=run_id,
            system_id=system_id,
            base_seed=seed,
        )
    )
    wall_seconds = time.monotonic() - started
    if _infrastructure_invalid(result.scorecard):
        raise ConfigurationError("OpenHands v17 canary scorecard is infrastructure-invalid")
    failure = result.scorecard.failure
    failure_category = failure.category if failure is not None else None
    if failure_category in {
        "openhands_hwe_action_policy",
        "openhands_hwe_provider_tool_arguments_policy",
        "openhands_hwe_recovery_tool_choice_violation",
        "openhands_hwe_training_causal_mismatch",
        "openhands_hwe_training_ineligible",
    }:
        raise ConfigurationError("OpenHands v17 canary schema/path/trajectory policy failed")
    run_directory = Path(result.run_dir).resolve(strict=True)
    if not run_directory.is_relative_to(runs) or run_directory.is_symlink():
        raise ConfigurationError("OpenHands v17 canary run directory is unsafe")
    evidence_root = run_directory / "artifacts" / "openhands_sdk"
    broker = _json(evidence_root / "broker.json")
    summary = _json(evidence_root / "summary.json")
    accounting = ExternalAgentAccounting.model_validate(_json(evidence_root / "accounting.json"))
    try:
        recovery_path = runtime_evidence_validator(
            broker,
            summary,
            accounting,
            verifier_resolved=result.scorecard.resolved,
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc

    trajectory_path = evidence_root / "training-trajectory.json"
    trajectory_summary = _trajectory_summary(
        trajectory_path,
        task_id=task_id,
        verifier_resolved=result.scorecard.resolved,
    )
    provider_scan = _scan_provider_values(root)
    scan = scan_artifact_roots(
        [evidence_root],
        report_id=f"{security_report_prefix}-{episode['episode_id']}",
        forbidden_host_roots=(str(qualification), str(Path.cwd().resolve())),
    )
    atomic_dump_json(scans / f"{episode['episode_id']}.json", scan)
    require_security_scan_pass(scan)
    return {
        "episode_id": episode["episode_id"],
        "role": episode["role"],
        "task_id": task_id,
        "seed": seed,
        "sample_index": sample_index,
        "run_id": run_id,
        "run_hash": content_hash(
            {"run_id": run_id, "scorecard": result.scorecard.model_dump(mode="json")}
        ),
        "source_commit": source_commit,
        "status": (
            "verifier_pass"
            if result.scorecard.resolved
            else "model_did_not_finish"
            if failure_category == "openhands_hwe_missing_finish"
            else "verifier_rejected"
        ),
        "infrastructure_valid": True,
        "runtime_evidence_valid": True,
        "security_scan_passed": True,
        "provider_value_scan": provider_scan,
        "recovery_accounting_valid": True,
        "recovery_path": recovery_path,
        "ordinary_verifier_resolved": result.scorecard.resolved,
        "scorecard_status": result.scorecard.status,
        "scorecard_failure_kind": failure.kind if failure is not None else None,
        "scorecard_failure_category": failure.category if failure is not None else None,
        "fresh_exact_trajectory": trajectory_summary["exported"],
        "trajectory": trajectory_summary,
        "truncation_applied": False,
        "model_call_count": accounting.model_call_count,
        "tool_call_count": accounting.external_tool_call_count,
        "input_tokens": accounting.input_tokens,
        "output_tokens": accounting.output_tokens,
        "total_tokens": accounting.total_tokens,
        "wall_seconds": wall_seconds,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _validate_runtime_evidence(
    broker: dict[str, Any],
    summary: dict[str, Any],
    accounting: ExternalAgentAccounting,
    *,
    verifier_resolved: bool,
) -> str:
    """Translate the shared frozen evidence validator into a runner configuration error."""

    try:
        return validate_v17_runtime_evidence(
            broker,
            summary,
            accounting,
            verifier_resolved=verifier_resolved,
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc


def _trajectory_summary(path: Path, *, task_id: str, verifier_resolved: bool) -> dict[str, Any]:
    if verifier_resolved:
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError("OpenHands v17 verifier pass lacks an exact trajectory")
        trajectory = validate_openhands_training_trajectory(_json(path))
        if (
            trajectory.get("task_id") != task_id
            or trajectory.get("verifier_resolved") is not True
            or trajectory.get("sft_eligible") is not True
            or trajectory.get("typed_finish_observed") is not True
            or trajectory.get("exact_model_visible_context") is not True
            or trajectory.get("raw_host_paths_exported") is not False
            or trajectory.get("credential_values_exported") is not False
        ):
            raise ConfigurationError("OpenHands v17 exact trajectory binding changed")
        return {
            "exported": True,
            "path": str(path.relative_to(path.parents[2])),
            "file_sha256": hash_bytes(path.read_bytes()),
            "format_id": trajectory["format_id"],
            "transcript_hash": trajectory["transcript_hash"],
            "assistant_decision_count": trajectory["assistant_decision_count"],
            "supervised_decision_count": trajectory.get(
                "supervised_decision_count", trajectory["assistant_decision_count"]
            ),
            "truncation_applied": False,
        }
    if path.exists() or path.is_symlink():
        raise ConfigurationError("OpenHands v17 verifier rejection exported a positive trajectory")
    return {
        "exported": False,
        "path": None,
        "file_sha256": None,
        "format_id": None,
        "transcript_hash": None,
        "assistant_decision_count": 0,
        "supervised_decision_count": 0,
        "truncation_applied": False,
    }


def _load_locks(
    contract: dict[str, Any], *, training_dir: Path, validation_dir: Path
) -> dict[str, HweAgentImageLock]:
    locks: dict[str, HweAgentImageLock] = {}
    for episode in contract["schedule"]:
        task_id = str(episode["task_id"])
        suffix = task_id.rsplit("-", 1)[-1]
        directory = training_dir if episode["role"] == "training" else validation_dir
        path = directory / f"pr-{suffix}.json"
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError("OpenHands v17 canary image lock is unsafe or absent")
        lock = HweAgentImageLock.model_validate(_json(path))
        binding = contract["task_bindings"][task_id]
        if (
            lock.task_id != task_id
            or lock.task_hash != binding["task_hash"]
            or lock.source_hash != binding["source_hash"]
            or lock.lock_hash != binding["image_lock_hash"]
            or lock.derived_agent_image_id != binding["agent_image"]
            or lock.verifier_base_image_id != binding["verifier_image"]
            or lock.runtime_network != "none"
            or lock.hidden_assets_present
            or lock.reference_patch_present
            or lock.provider_credentials_present
            or lock.verifier_payload_present
            or not lock.security_scan_passed
        ):
            raise ConfigurationError("OpenHands v17 canary image-lock binding changed")
        locks[task_id] = lock
    return locks


def _zero_call_preflight(locks: dict[str, HweAgentImageLock]) -> None:
    from verigym_openhands.hwe_agent import _configured_control_root, _configured_mcp_pythonpath

    _configured_control_root()
    _configured_mcp_pythonpath()
    for task_id in OPENHANDS_V17_CANARY_TASKS:
        runtime = DockerRuntime(_docker_config(locks[task_id]))
        try:
            runtime.prepare(f"{OPENHANDS_V17_CANARY_PREFLIGHT_PREFIX}-{task_id.rsplit('-', 1)[-1]}")
        finally:
            runtime.close()


def _service() -> VeriGym:
    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "openhands-hwe-agent" not in registries.agents.names():
        from verigym_openhands.hwe_agent import OpenHandsHweAgentAdapter

        registries.agents.register(OpenHandsHweAgentAdapter())
    return VeriGym(registries)


def _qualified_sources(progress: dict[str, Any]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for key in ("training_pool", "development_validation"):
        pool = progress.get(key)
        if not isinstance(pool, list):
            raise ConfigurationError("OpenHands v17 canary qualification pool is malformed")
        for item in pool:
            if not isinstance(item, dict):
                raise ConfigurationError("OpenHands v17 canary qualification entry is malformed")
            task_id = item.get("task_id")
            source = item.get("source")
            if task_id in OPENHANDS_V17_CANARY_TASKS:
                if not isinstance(task_id, str) or not isinstance(source, str):
                    raise ConfigurationError("OpenHands v17 canary source mapping is malformed")
                sources[task_id] = source
    if set(sources) != set(OPENHANDS_V17_CANARY_TASKS):
        raise ConfigurationError("OpenHands v17 canary source mapping is incomplete")
    return sources


def _scan_provider_values(root: Path) -> dict[str, Any]:
    values = (
        os.environ[OPENHANDS_V17_CANARY_BASE_URL_ENV].encode(),
        os.environ[OPENHANDS_V17_CANARY_API_KEY_ENV].encode(),
    )
    files = 0
    byte_count = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("OpenHands v17 canary artifact contains a symlink")
        if not path.is_file():
            continue
        data = path.read_bytes()
        files += 1
        byte_count += len(data)
        if any(value in data for value in values):
            raise ConfigurationError("provider value reached OpenHands v17 canary artifacts")
    return {
        "passed": True,
        "provider_value_count_scanned": len(values),
        "file_count_scanned": files,
        "byte_count_scanned": byte_count,
        "provider_value_hit_count": 0,
        "provider_values_persisted_or_hashed": False,
    }


def _require_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPENHANDS_V17_CANARY_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V17_CANARY_OPT_IN_ENV}=1 is required")
    if campaign_id != OPENHANDS_V17_CANARY_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands v17 canary campaign identity changed")
    if not os.environ.get(OPENHANDS_V17_CANARY_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_V17_CANARY_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands v17 canary provider environment is incomplete")
    expected = {
        "openhands-sdk": OPENHANDS_V17_CANARY_SDK_VERSION,
        "litellm": OPENHANDS_V17_CANARY_LITELLM_VERSION,
        "tiktoken": OPENHANDS_V17_CANARY_TIKTOKEN_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"OpenHands v17 canary {package} version changed")


def _stop(
    root: Path,
    base_report: dict[str, Any],
    attempts: list[dict[str, Any]],
    reason: str,
) -> None:
    stopped = seal_v17_canary_report(
        {
            **base_report,
            "status": "stopped_infrastructure_or_security_invalid",
            "attempts": attempts,
            "stop_reason": reason,
            "canary_passed": False,
            "formal_collection_allowed": False,
        }
    )
    atomic_dump_json(root / "canary-progress.json", stopped)
    atomic_dump_json(root / "canary-report.json", stopped)


def main() -> int:
    report = collect(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "canary_passed": report["canary_passed"],
                "formal_collection_allowed": report["formal_collection_allowed"],
                "gate_failure_reason": report["gate_failure_reason"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["formal_collection_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
