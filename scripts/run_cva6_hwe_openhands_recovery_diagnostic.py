#!/usr/bin/env python3
"""Run one frozen OpenHands HWE stop-recovery diagnostic on CVA6 PR-2032."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, cast

from verigym_openhands.hwe_recovery_diagnostic import (
    OPENHANDS_RECOVERY_DIAGNOSTIC_AGENT_VERSION_ID,
    OPENHANDS_RECOVERY_DIAGNOSTIC_API_KEY_ENV,
    OPENHANDS_RECOVERY_DIAGNOSTIC_BASE_URL_ENV,
    OPENHANDS_RECOVERY_DIAGNOSTIC_CAMPAIGN_ID,
    OPENHANDS_RECOVERY_DIAGNOSTIC_FORMAT,
    OPENHANDS_RECOVERY_DIAGNOSTIC_LITELLM_VERSION,
    OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_CONTEXT_TOKENS,
    OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_ITERATIONS,
    OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
    OPENHANDS_RECOVERY_DIAGNOSTIC_MODEL,
    OPENHANDS_RECOVERY_DIAGNOSTIC_MODEL_IDENTITY,
    OPENHANDS_RECOVERY_DIAGNOSTIC_OPT_IN_ENV,
    OPENHANDS_RECOVERY_DIAGNOSTIC_REPORT_FORMAT,
    OPENHANDS_RECOVERY_DIAGNOSTIC_SDK_VERSION,
    OPENHANDS_RECOVERY_DIAGNOSTIC_SEED,
    OPENHANDS_RECOVERY_DIAGNOSTIC_TASK,
    build_recovery_diagnostic_agent_version,
    classify_recovery_diagnostic,
    seal_recovery_diagnostic_report,
)
from verigym_openhands.trajectory import (
    OPENHANDS_RECOVERY_TRAJECTORY_FORMAT,
    validate_openhands_training_trajectory,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.state import atomic_dump_json
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_docker_config = _collection._docker_config
_image_locks = _collection._image_locks
_infrastructure_invalid = _collection._infrastructure_invalid
_json = _collection._json
_qualified_sources = _collection._qualified_sources

_PRIOR_V1_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-five-task-pilot-v1"
_PRIOR_V1_FAILURE_CATEGORY = "openhands_hwe_missing_finish"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock-dir", type=Path, required=True)
    parser.add_argument("--prior-v1-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--campaign-id",
        default=OPENHANDS_RECOVERY_DIAGNOSTIC_CAMPAIGN_ID,
    )
    return parser


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute exactly one no-retry model episode and seal its recovery evidence."""

    if os.environ.get(OPENHANDS_RECOVERY_DIAGNOSTIC_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_RECOVERY_DIAGNOSTIC_OPT_IN_ENV}=1 is required")
    if arguments.campaign_id != OPENHANDS_RECOVERY_DIAGNOSTIC_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands recovery diagnostic campaign identity changed")
    if not os.environ.get(OPENHANDS_RECOVERY_DIAGNOSTIC_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_RECOVERY_DIAGNOSTIC_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands recovery diagnostic provider environment is incomplete")
    if importlib.metadata.version("openhands-sdk") != OPENHANDS_RECOVERY_DIAGNOSTIC_SDK_VERSION:
        raise ConfigurationError("OpenHands SDK differs from frozen version 1.42.1")
    if importlib.metadata.version("litellm") != OPENHANDS_RECOVERY_DIAGNOSTIC_LITELLM_VERSION:
        raise ConfigurationError("LiteLLM differs from frozen version 1.93.0")

    source_commit = _clean_source_commit()
    qualification = arguments.qualification_root.resolve(strict=True)
    split = _validated_split(qualification)
    training = {entry.task_id: entry for entry in split.training}
    if OPENHANDS_RECOVERY_DIAGNOSTIC_TASK not in training or any(
        entry.task_id == OPENHANDS_RECOVERY_DIAGNOSTIC_TASK
        for entry in (*split.validation, *split.heldout)
    ):
        raise ConfigurationError("OpenHands recovery diagnostic task split binding changed")
    progress = _json(qualification / "qualification-progress.json")
    if (
        progress.get("status") != "completed"
        or progress.get("task_split_hash") != split.manifest_hash
    ):
        raise ConfigurationError("CVA6 qualification is incomplete or changed")
    source_by_task = _qualified_sources(progress)
    source_root = (qualification / source_by_task[OPENHANDS_RECOVERY_DIAGNOSTIC_TASK]).resolve(
        strict=True
    )
    if not source_root.is_relative_to(qualification):
        raise ConfigurationError("OpenHands recovery diagnostic source escaped qualification root")

    locks = _image_locks(
        arguments.image_lock_dir,
        {OPENHANDS_RECOVERY_DIAGNOSTIC_TASK},
    )
    lock = locks[OPENHANDS_RECOVERY_DIAGNOSTIC_TASK]
    entry = training[OPENHANDS_RECOVERY_DIAGNOSTIC_TASK]
    if lock.task_hash != entry.task_hash or lock.source_hash != entry.source_hash:
        raise ConfigurationError("OpenHands recovery diagnostic task/source/image identity changed")
    prior = _prior_v1_failure(arguments.prior_v1_report)

    from verigym_openhands.hwe_agent import (
        OpenHandsHweAgentAdapter,
        _configured_control_root,
        _configured_mcp_pythonpath,
    )

    _configured_control_root()
    _configured_mcp_pythonpath()
    runtime_config = _docker_config(lock)
    runtime = DockerRuntime(runtime_config)
    try:
        runtime.prepare("openhands-recovery-diagnostic-v2-pr2032")
    finally:
        runtime.close()

    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    agent = OpenHandsHweAgentAdapter()
    if agent.descriptor.name not in registries.agents.names():
        registries.agents.register(agent)
    service = VeriGym(registries)
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(OPENHANDS_RECOVERY_DIAGNOSTIC_TASK, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != entry.task_hash
        or task.source.content_hash != entry.source_hash
    ):
        raise ConfigurationError("OpenHands recovery diagnostic qualified source changed")

    version = build_recovery_diagnostic_agent_version(
        source_commit=source_commit,
        image_lock=lock,
    )
    manifest_json = json.dumps(
        version.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    root = _new_output(arguments.output)
    runs = root / "runs"
    runs.mkdir(mode=0o700)
    atomic_dump_json(root / "agent-version.json", version)
    preregistration = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_RECOVERY_DIAGNOSTIC_FORMAT,
        "status": "execution_started",
        "diagnostic_only": True,
        "campaign_id": arguments.campaign_id,
        "task_id": OPENHANDS_RECOVERY_DIAGNOSTIC_TASK,
        "task_hash": entry.task_hash,
        "source_hash": entry.source_hash,
        "source_commit": source_commit,
        "image_lock_hash": lock.lock_hash,
        "prior_v1_report_hash": prior["report_hash"],
        "prior_v1_run_hash": prior["run_hash"],
        "prior_v1_failure_category": _PRIOR_V1_FAILURE_CATEGORY,
        "model_transport_id": OPENHANDS_RECOVERY_DIAGNOSTIC_MODEL,
        "model_identity": OPENHANDS_RECOVERY_DIAGNOSTIC_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_RECOVERY_DIAGNOSTIC_AGENT_VERSION_ID,
        "agent_version_hash": version.version_hash,
        "openhands_sdk_version": OPENHANDS_RECOVERY_DIAGNOSTIC_SDK_VERSION,
        "litellm_version": OPENHANDS_RECOVERY_DIAGNOSTIC_LITELLM_VERSION,
        "seed": OPENHANDS_RECOVERY_DIAGNOSTIC_SEED,
        "temperature": 0,
        "top_p": 1,
        "max_iterations": OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_ITERATIONS,
        "max_output_tokens": OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
        "max_context_tokens": OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_CONTEXT_TOKENS,
        "format_recovery_budget": 1,
        "same_session_recovery": True,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "ordinary_verifier_required": True,
        "trajectory_export_requires_verifier_pass": True,
        "dataset_admission": False,
        "benchmark_score_claimed": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "new_hpc_jobs_submitted": False,
        "gpu_seconds": 0,
    }
    atomic_dump_json(
        root / "preregistration.json", seal_recovery_diagnostic_report(preregistration)
    )

    run_id = f"{arguments.campaign_id}-pr2032"
    started = time.monotonic()
    try:
        result = service.run(
            RunConfig(
                task_id=OPENHANDS_RECOVERY_DIAGNOSTIC_TASK,
                suite_source=source,
                expected_suite_source_snapshot=snapshot,
                expected_task_hash=entry.task_hash,
                expected_source_hash=entry.source_hash,
                mode=InteractionMode.AGENT,
                agent=agent.descriptor.name,
                agent_options={
                    "model_id": OPENHANDS_RECOVERY_DIAGNOSTIC_MODEL,
                    "base_url_env": OPENHANDS_RECOVERY_DIAGNOSTIC_BASE_URL_ENV,
                    "api_key_env": OPENHANDS_RECOVERY_DIAGNOSTIC_API_KEY_ENV,
                    "max_iterations": OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_ITERATIONS,
                    "max_process_time_s": 3_600,
                    "max_output_tokens": OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
                    "max_context_tokens": OPENHANDS_RECOVERY_DIAGNOSTIC_MAX_CONTEXT_TOKENS,
                    "seed": OPENHANDS_RECOVERY_DIAGNOSTIC_SEED,
                    "temperature": 0,
                    "top_p": 1,
                    "whole_episode_retries": 0,
                    "expected_sdk_version": OPENHANDS_RECOVERY_DIAGNOSTIC_SDK_VERSION,
                    "campaign_role": "training",
                    "capture_training_transcript": True,
                    "agent_version_id": version.agent_version_id,
                    "agent_version_hash": version.version_hash,
                    "agent_version_manifest_json": manifest_json,
                    "collection_profile_id": "hwe_production_native_shell_v2",
                },
                runtime="docker",
                docker_config=runtime_config,
                seed=OPENHANDS_RECOVERY_DIAGNOSTIC_SEED,
                sample_index=0,
                output=runs,
                run_id=run_id,
                experiment_id=arguments.campaign_id,
                plan_item_id=run_id,
                system_id="openhands-deepseek-v4-flash-hwe-stop-recovery-diagnostic-v2",
                base_seed=OPENHANDS_RECOVERY_DIAGNOSTIC_SEED,
            )
        )
    except Exception as exc:
        report = seal_recovery_diagnostic_report(
            {
                **preregistration,
                "format_id": OPENHANDS_RECOVERY_DIAGNOSTIC_REPORT_FORMAT,
                "status": "run_boundary_exception",
                "diagnostic_passed": False,
                "exception_type": type(exc).__name__,
                "wall_seconds": time.monotonic() - started,
            }
        )
        atomic_dump_json(root / "diagnostic-report.json", report)
        _assert_provider_values_absent(root)
        raise ConfigurationError(
            "OpenHands recovery diagnostic failed at the run boundary"
        ) from exc

    wall_seconds = time.monotonic() - started
    run_directory = Path(result.run_dir).resolve(strict=True)
    evidence_root = run_directory / "artifacts" / "openhands_sdk"
    broker = _optional_json(evidence_root / "broker.json")
    summary = _optional_json(evidence_root / "summary.json")
    accounting = _optional_json(evidence_root / "accounting.json")
    raw_recovery_count = summary.get("format_recovery_count", 0) if summary else 0
    recovery_count_valid = (
        isinstance(raw_recovery_count, int)
        and not isinstance(raw_recovery_count, bool)
        and raw_recovery_count in {0, 1}
    )
    recovery_count = raw_recovery_count if recovery_count_valid else 0
    evidence_complete = (
        broker is not None
        and summary is not None
        and accounting is not None
        and recovery_count_valid
    )
    infrastructure_valid = not _infrastructure_invalid(result.scorecard) and evidence_complete
    typed_finish = broker is not None and broker.get("finished") is True
    failure = result.scorecard.failure
    failure_category = failure.category if failure is not None else None
    status, diagnostic_passed = classify_recovery_diagnostic(
        infrastructure_valid=infrastructure_valid,
        typed_finish_observed=typed_finish,
        recovery_count=recovery_count,
        failure_category=failure_category,
    )

    trajectory_paths = sorted(evidence_root.glob("training-trajectory.json"))
    trajectory_summary: dict[str, Any]
    if result.scorecard.resolved:
        if len(trajectory_paths) != 1:
            raise ConfigurationError("verifier-pass diagnostic lacks exactly one trajectory")
        trajectory_path = trajectory_paths[0]
        trajectory = validate_openhands_training_trajectory(_json(trajectory_path))
        if (
            trajectory.get("format_id") != OPENHANDS_RECOVERY_TRAJECTORY_FORMAT
            or trajectory.get("verifier_resolved") is not True
            or trajectory.get("sft_eligible") is not True
        ):
            raise ConfigurationError("recovery diagnostic trajectory is not eligible v2 data")
        trajectory_summary = {
            "exported": True,
            "format_id": trajectory["format_id"],
            "transcript_hash": trajectory["transcript_hash"],
            "file_sha256": hash_bytes(trajectory_path.read_bytes()),
            "assistant_decision_count": trajectory["assistant_decision_count"],
            "recovery_count": trajectory["recovery"]["recovery_count"],
            "dataset_admitted": False,
        }
    elif trajectory_paths:
        raise ConfigurationError("verifier-rejected diagnostic exported a positive trajectory")
    else:
        trajectory_summary = {
            "exported": False,
            "format_id": None,
            "transcript_hash": None,
            "file_sha256": None,
            "assistant_decision_count": 0,
            "recovery_count": recovery_count,
            "dataset_admitted": False,
        }

    credential_scan = _assert_provider_values_absent(root)
    report = seal_recovery_diagnostic_report(
        {
            **preregistration,
            "format_id": OPENHANDS_RECOVERY_DIAGNOSTIC_REPORT_FORMAT,
            "status": status,
            "diagnostic_passed": diagnostic_passed,
            "infrastructure_valid": infrastructure_valid,
            "evidence_complete": evidence_complete,
            "ordinary_verifier_resolved": result.scorecard.resolved,
            "scorecard_status": result.scorecard.status,
            "scorecard_failure_kind": failure.kind if failure is not None else None,
            "scorecard_failure_category": failure_category,
            "typed_finish_observed": typed_finish,
            "format_recovery_count": recovery_count,
            "recovery_path_exercised": recovery_count == 1,
            "model_call_count": accounting.get("model_call_count") if accounting else None,
            "tool_call_count": broker.get("tool_calls") if broker else None,
            "patch_call_count": broker.get("patches") if broker else None,
            "wall_seconds": wall_seconds,
            "trajectory": trajectory_summary,
            "credential_scan": credential_scan,
        }
    )
    atomic_dump_json(root / "diagnostic-report.json", report)
    return report


def _validated_split(root: Path) -> TaskSplitManifest:
    from verigym.evolution.splits import validate_task_split

    return validate_task_split(TaskSplitManifest.model_validate(_json(root / "task-split.json")))


def _prior_v1_failure(path: Path) -> dict[str, str]:
    report = _json(path.resolve(strict=True))
    observed = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    attempts = report.get("attempts")
    if (
        not isinstance(observed, str)
        or content_hash(base) != observed
        or report.get("agent_version_id") != _PRIOR_V1_AGENT_VERSION_ID
        or not isinstance(attempts, list)
    ):
        raise ConfigurationError("prior OpenHands v1 report identity changed")
    matches = [
        item
        for item in attempts
        if isinstance(item, dict)
        and item.get("task_id") == OPENHANDS_RECOVERY_DIAGNOSTIC_TASK
        and item.get("rejection_reason") == _PRIOR_V1_FAILURE_CATEGORY
        and item.get("whole_episode_retries") == 0
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("run_hash"), str):
        raise ConfigurationError("prior OpenHands v1 missing-finish failure changed")
    return {"report_hash": observed, "run_hash": str(matches[0]["run_hash"])}


def _clean_source_commit() -> str:
    root = Path(__file__).resolve().parents[1]
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        diff_result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if diff_result.returncode != 0:
            raise ConfigurationError("OpenHands recovery diagnostic requires a clean source commit")
    commit_result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = commit_result.stdout.strip()
    if len(commit) != 40:
        raise ConfigurationError("OpenHands recovery diagnostic could not resolve a full Git SHA")
    return commit


def _new_output(path: Path) -> Path:
    target = path.expanduser()
    if target.exists() or target.is_symlink():
        raise ConfigurationError("OpenHands recovery diagnostic output already exists")
    target.mkdir(parents=True, mode=0o700)
    return target.resolve(strict=True)


def _optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return cast(dict[str, Any], _json(path))


def _assert_provider_values_absent(root: Path) -> dict[str, Any]:
    values = [
        os.environ[OPENHANDS_RECOVERY_DIAGNOSTIC_BASE_URL_ENV].encode(),
        os.environ[OPENHANDS_RECOVERY_DIAGNOSTIC_API_KEY_ENV].encode(),
    ]
    file_count = 0
    byte_count = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("OpenHands recovery diagnostic artifact contains a symlink")
        if not path.is_file():
            continue
        data = path.read_bytes()
        file_count += 1
        byte_count += len(data)
        if any(value in data for value in values):
            raise ConfigurationError("provider value reached OpenHands diagnostic artifacts")
    return {
        "passed": True,
        "provider_value_count_scanned": len(values),
        "file_count_scanned": file_count,
        "byte_count_scanned": byte_count,
        "provider_value_hit_count": 0,
        "provider_values_persisted_or_hashed": False,
    }


def main() -> int:
    report = run(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_passed": report["diagnostic_passed"],
                "typed_finish_observed": report["typed_finish_observed"],
                "format_recovery_count": report["format_recovery_count"],
                "ordinary_verifier_resolved": report["ordinary_verifier_resolved"],
                "trajectory_exported": report["trajectory"]["exported"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["diagnostic_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
