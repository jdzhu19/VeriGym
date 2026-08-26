#!/usr/bin/env python3
"""Run one frozen OpenHands merged-recovery forced-finish diagnostic on CVA6 PR-2032."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import time
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_tool_choice_diagnostic import (
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_AGENT_VERSION_ID,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_API_KEY_ENV,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_BASE_URL_ENV,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_CAMPAIGN_ID,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_FORMAT,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_LITELLM_VERSION,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_CONTEXT_TOKENS,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_ITERATIONS,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL_IDENTITY,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_OPT_IN_ENV,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_REPORT_FORMAT,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SDK_VERSION,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SEED,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK,
    OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TIKTOKEN_VERSION,
    OPENHANDS_TOOL_CHOICE_POLICY,
    build_tool_choice_diagnostic_agent_version,
    classify_tool_choice_diagnostic,
    seal_tool_choice_diagnostic_report,
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
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_recovery_runner = importlib.import_module(
    "scripts.run_cva6_hwe_openhands_recovery_diagnostic"
    if __package__
    else "run_cva6_hwe_openhands_recovery_diagnostic"
)
_assert_provider_values_absent = _recovery_runner._assert_provider_values_absent
_clean_source_commit = _recovery_runner._clean_source_commit
_docker_config = _recovery_runner._docker_config
_image_locks = _recovery_runner._image_locks
_infrastructure_invalid = _recovery_runner._infrastructure_invalid
_json = _recovery_runner._json
_new_output = _recovery_runner._new_output
_optional_json = _recovery_runner._optional_json
_qualified_sources = _recovery_runner._qualified_sources
_validated_split = _recovery_runner._validated_split

_PRIOR_V4_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-recovery-forced-finish-diagnostic-v4"
_PRIOR_V4_STATUS = "recovery_forced_finish_regression_failed"
_PRIOR_V4_FAILURE_CATEGORY = "openhands_hwe_missing_finish"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock-dir", type=Path, required=True)
    parser.add_argument("--prior-v4-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--campaign-id",
        default=OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_CAMPAIGN_ID,
    )
    return parser


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute one no-retry recovery-forced-finish episode and seal its evidence."""

    if os.environ.get(OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_OPT_IN_ENV}=1 is required")
    if arguments.campaign_id != OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands tool-choice diagnostic campaign identity changed")
    if not os.environ.get(OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands tool-choice provider environment is incomplete")
    _validate_package_versions()

    source_commit = _clean_source_commit()
    qualification = arguments.qualification_root.resolve(strict=True)
    split = _validated_split(qualification)
    training = {entry.task_id: entry for entry in split.training}
    if OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK not in training or any(
        entry.task_id == OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK
        for entry in (*split.validation, *split.heldout)
    ):
        raise ConfigurationError("OpenHands tool-choice diagnostic task split binding changed")
    progress = _json(qualification / "qualification-progress.json")
    if (
        progress.get("status") != "completed"
        or progress.get("task_split_hash") != split.manifest_hash
    ):
        raise ConfigurationError("CVA6 qualification is incomplete or changed")
    source_by_task = _qualified_sources(progress)
    source_root = (qualification / source_by_task[OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK]).resolve(
        strict=True
    )
    if not source_root.is_relative_to(qualification):
        raise ConfigurationError("OpenHands tool-choice source escaped qualification root")

    locks = _image_locks(arguments.image_lock_dir, {OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK})
    lock = locks[OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK]
    entry = training[OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK]
    if lock.task_hash != entry.task_hash or lock.source_hash != entry.source_hash:
        raise ConfigurationError("OpenHands tool-choice task/source/image identity changed")
    prior = _prior_v4_failure(arguments.prior_v4_report)

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
        runtime.prepare("openhands-recovery-forced-finish-merged-v5-pr2032")
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
    suite, task, _assets = service.load_task(OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != entry.task_hash
        or task.source.content_hash != entry.source_hash
    ):
        raise ConfigurationError("OpenHands tool-choice qualified source changed")

    version = build_tool_choice_diagnostic_agent_version(
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
        "format_id": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_FORMAT,
        "status": "execution_started",
        "diagnostic_only": True,
        "campaign_id": arguments.campaign_id,
        "task_id": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK,
        "task_hash": entry.task_hash,
        "source_hash": entry.source_hash,
        "source_commit": source_commit,
        "image_lock_hash": lock.lock_hash,
        "prior_v4_report_hash": prior["report_hash"],
        "prior_v4_agent_version_hash": prior["agent_version_hash"],
        "prior_v4_failure_category": _PRIOR_V4_FAILURE_CATEGORY,
        "model_transport_id": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL,
        "model_identity": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_AGENT_VERSION_ID,
        "agent_version_hash": version.version_hash,
        "openhands_sdk_version": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SDK_VERSION,
        "litellm_version": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TIKTOKEN_VERSION,
        "seed": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SEED,
        "temperature": 0,
        "top_p": 1,
        "max_iterations": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_ITERATIONS,
        "max_output_tokens": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
        "max_context_tokens": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_CONTEXT_TOKENS,
        "tool_choice_policy": OPENHANDS_TOOL_CHOICE_POLICY,
        "format_recovery_budget": 1,
        "acceptance_requires_recovery_count": 1,
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
        root / "preregistration.json",
        seal_tool_choice_diagnostic_report(preregistration),
    )

    run_id = f"{arguments.campaign_id}-pr2032"
    started = time.monotonic()
    try:
        result = service.run(
            RunConfig(
                task_id=OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TASK,
                suite_source=source,
                expected_suite_source_snapshot=snapshot,
                expected_task_hash=entry.task_hash,
                expected_source_hash=entry.source_hash,
                mode=InteractionMode.AGENT,
                agent=agent.descriptor.name,
                agent_options={
                    "model_id": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MODEL,
                    "base_url_env": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_BASE_URL_ENV,
                    "api_key_env": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_API_KEY_ENV,
                    "max_iterations": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_ITERATIONS,
                    "max_process_time_s": 3_600,
                    "max_output_tokens": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
                    "max_context_tokens": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_MAX_CONTEXT_TOKENS,
                    "seed": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SEED,
                    "temperature": 0,
                    "top_p": 1,
                    "whole_episode_retries": 0,
                    "expected_sdk_version": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SDK_VERSION,
                    "campaign_role": "training",
                    "capture_training_transcript": True,
                    "agent_version_id": version.agent_version_id,
                    "agent_version_hash": version.version_hash,
                    "agent_version_manifest_json": manifest_json,
                    "collection_profile_id": "hwe_production_native_shell_v2",
                    "tool_choice_policy": OPENHANDS_TOOL_CHOICE_POLICY,
                },
                runtime="docker",
                docker_config=runtime_config,
                seed=OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SEED,
                sample_index=0,
                output=runs,
                run_id=run_id,
                experiment_id=arguments.campaign_id,
                plan_item_id=run_id,
                system_id="openhands-deepseek-v4-flash-hwe-recovery-forced-finish-merged-v5",
                base_seed=OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SEED,
            )
        )
    except Exception as exc:
        report = seal_tool_choice_diagnostic_report(
            {
                **preregistration,
                "format_id": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_REPORT_FORMAT,
                "status": "run_boundary_exception",
                "diagnostic_passed": False,
                "exception_type": type(exc).__name__,
                "wall_seconds": time.monotonic() - started,
            }
        )
        atomic_dump_json(root / "diagnostic-report.json", report)
        _assert_provider_values_absent(root)
        raise ConfigurationError("OpenHands tool-choice diagnostic failed at run boundary") from exc

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
    tool_choice_bound = (
        summary is not None and summary.get("tool_choice_policy") == OPENHANDS_TOOL_CHOICE_POLICY
    )
    evidence_complete = (
        broker is not None
        and summary is not None
        and accounting is not None
        and recovery_count_valid
        and tool_choice_bound
    )
    infrastructure_valid = not _infrastructure_invalid(result.scorecard) and evidence_complete
    typed_finish = broker is not None and broker.get("finished") is True
    failure = result.scorecard.failure
    failure_category = failure.category if failure is not None else None
    status, diagnostic_passed = classify_tool_choice_diagnostic(
        infrastructure_valid=infrastructure_valid,
        typed_finish_observed=typed_finish,
        recovery_count=recovery_count,
        failure_category=failure_category,
    )

    trajectory_paths = sorted(evidence_root.glob("training-trajectory.json"))
    trajectory_summary: dict[str, Any]
    if result.scorecard.resolved:
        if len(trajectory_paths) != 1:
            raise ConfigurationError("verifier-pass tool-choice diagnostic lacks one trajectory")
        trajectory_path = trajectory_paths[0]
        trajectory = validate_openhands_training_trajectory(_json(trajectory_path))
        if (
            trajectory.get("format_id") != OPENHANDS_RECOVERY_TRAJECTORY_FORMAT
            or trajectory.get("verifier_resolved") is not True
            or trajectory.get("sft_eligible") is not True
            or trajectory.get("format_recovery_count") != 1
        ):
            raise ConfigurationError("tool-choice diagnostic trajectory is not eligible v2 data")
        trajectory_summary = {
            "exported": True,
            "format_id": trajectory["format_id"],
            "transcript_hash": trajectory["transcript_hash"],
            "file_sha256": hash_bytes(trajectory_path.read_bytes()),
            "assistant_decision_count": trajectory["assistant_decision_count"],
            "recovery_count": trajectory["format_recovery_count"],
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
    report = seal_tool_choice_diagnostic_report(
        {
            **preregistration,
            "format_id": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_REPORT_FORMAT,
            "status": status,
            "diagnostic_passed": diagnostic_passed,
            "infrastructure_valid": infrastructure_valid,
            "evidence_complete": evidence_complete,
            "tool_choice_bound": tool_choice_bound,
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


def _validate_package_versions() -> None:
    expected = {
        "openhands-sdk": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_SDK_VERSION,
        "litellm": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_LITELLM_VERSION,
        "tiktoken": OPENHANDS_TOOL_CHOICE_DIAGNOSTIC_TIKTOKEN_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"{package} differs from the frozen tool-choice diagnostic")


def _prior_v4_failure(path: Path) -> dict[str, str]:
    report = _json(path.resolve(strict=True))
    observed = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    trajectory = report.get("trajectory")
    if (
        not isinstance(observed, str)
        or content_hash(base) != observed
        or report.get("agent_version_id") != _PRIOR_V4_AGENT_VERSION_ID
        or report.get("status") != _PRIOR_V4_STATUS
        or report.get("scorecard_failure_category") != _PRIOR_V4_FAILURE_CATEGORY
        or report.get("infrastructure_valid") is not True
        or report.get("tool_choice_bound") is not True
        or report.get("typed_finish_observed") is not False
        or report.get("format_recovery_count") != 1
        or report.get("model_call_count") != 13
        or report.get("tool_call_count") != 13
        or report.get("patch_call_count") != 0
        or not isinstance(trajectory, dict)
        or trajectory.get("exported") is not False
    ):
        raise ConfigurationError("prior OpenHands v4 forced-finish failure changed")
    version_hash = report.get("agent_version_hash")
    if not isinstance(version_hash, str) or len(version_hash) != 64:
        raise ConfigurationError("prior OpenHands v4 agent version hash is absent")
    return {"report_hash": observed, "agent_version_hash": version_hash}


def main() -> int:
    report = run(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_passed": report["diagnostic_passed"],
                "tool_choice_bound": report["tool_choice_bound"],
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
