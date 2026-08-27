#!/usr/bin/env python3
"""Run one frozen OpenHands Responses-recovery diagnostic on CVA6 PR-2032."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_responses_recovery_diagnostic import (
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_AGENT_VERSION_ID,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_API_KEY_ENV,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_BASE_URL_ENV,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_CAMPAIGN_ID,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_FORMAT,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_LITELLM_VERSION,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_CONTEXT_TOKENS,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_ITERATIONS,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MODEL,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MODEL_IDENTITY,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_OPT_IN_ENV,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_REPORT_FORMAT,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SDK_VERSION,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SEED,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK,
    OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TIKTOKEN_VERSION,
    OPENHANDS_RESPONSES_RECOVERY_POLICY,
    build_responses_recovery_diagnostic_agent_version,
    classify_responses_recovery_diagnostic,
    seal_responses_recovery_diagnostic_report,
)
from verigym_openhands.trajectory import (
    OPENHANDS_MASKED_RECOVERY_TRAJECTORY_FORMAT,
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
_infrastructure_invalid = _recovery_runner._infrastructure_invalid
_json = _recovery_runner._json
_new_output = _recovery_runner._new_output
_optional_json = _recovery_runner._optional_json
_qualified_sources = _recovery_runner._qualified_sources
_validated_split = _recovery_runner._validated_split

_PRIOR_V9_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-responses-recovery-finish-diagnostic-v9"
)
_PRIOR_V9_STATUS = "infrastructure_invalid"
_PRIOR_V9_FAILURE_CATEGORY = "hwe_broker_unavailable"
_PRIOR_V10_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-responses-recovery-finish-diagnostic-v10"
)
_PRIOR_V10_STATUS = "infrastructure_invalid"
_PRIOR_V10_FAILURE_CATEGORY = "openhands_hwe_sdk_episode"
_PRIOR_V11_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-responses-recovery-finish-diagnostic-v11"
)
_PRIOR_V11_STATUS = "responses_recovery_finish_response_rejected"
_PRIOR_V11_FAILURE_CATEGORY = "openhands_hwe_recovery_tool_choice_violation"
_PRIOR_V12_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-responses-recovery-finish-diagnostic-v12"
)
_PRIOR_V12_STATUS = "infrastructure_invalid"
_PRIOR_V12_FAILURE_CATEGORY = "openhands_hwe_action_policy"


@dataclass(frozen=True)
class _PriorV9ImageLock:
    task_id: str
    task_hash: str
    source_hash: str
    verifier_base_image_id: str
    derived_agent_image_id: str
    agent_codex_sha256: str
    agent_rg_sha256: str
    lock_hash: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--prior-v9-report", type=Path, required=True)
    parser.add_argument("--prior-v10-report", type=Path, required=True)
    parser.add_argument("--prior-v11-report", type=Path, required=True)
    parser.add_argument("--prior-v12-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--campaign-id",
        default=OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_CAMPAIGN_ID,
    )
    return parser


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute one no-retry recovery-forced-finish episode and seal its evidence."""

    if os.environ.get(OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_OPT_IN_ENV) != "1":
        raise ConfigurationError(
            f"{OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_OPT_IN_ENV}=1 is required"
        )
    if arguments.campaign_id != OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands tool-choice diagnostic campaign identity changed")
    if not os.environ.get(
        OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_BASE_URL_ENV
    ) or not os.environ.get(OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_API_KEY_ENV):
        raise ConfigurationError("OpenHands tool-choice provider environment is incomplete")
    _validate_package_versions()

    source_commit = _clean_source_commit()
    qualification = arguments.qualification_root.resolve(strict=True)
    split = _validated_split(qualification)
    training = {entry.task_id: entry for entry in split.training}
    if OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK not in training or any(
        entry.task_id == OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK
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
    source_root = (
        qualification / source_by_task[OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK]
    ).resolve(strict=True)
    if not source_root.is_relative_to(qualification):
        raise ConfigurationError("OpenHands tool-choice source escaped qualification root")

    prior = _prior_v9_failure(arguments.prior_v9_report)
    prior_v10 = _prior_v10_failure(arguments.prior_v10_report)
    prior_v11 = _prior_v11_failure(arguments.prior_v11_report)
    prior_v12 = _prior_v12_failure(arguments.prior_v12_report)
    entry = training[OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK]
    lock = _prior_v9_image_lock(prior)
    if lock.task_hash != entry.task_hash or lock.source_hash != entry.source_hash:
        raise ConfigurationError("OpenHands tool-choice task/source/image identity changed")
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
        runtime.prepare("openhands-finish-trajectory-v13-pr2032")
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
    suite, task, _assets = service.load_task(OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != entry.task_hash
        or task.source.content_hash != entry.source_hash
    ):
        raise ConfigurationError("OpenHands tool-choice qualified source changed")

    version = build_responses_recovery_diagnostic_agent_version(
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
        "format_id": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_FORMAT,
        "status": "execution_started",
        "diagnostic_only": True,
        "campaign_id": arguments.campaign_id,
        "task_id": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK,
        "task_hash": entry.task_hash,
        "source_hash": entry.source_hash,
        "source_commit": source_commit,
        "image_lock_hash": lock.lock_hash,
        "prior_v9_report_hash": prior["report_hash"],
        "prior_v9_agent_version_hash": prior["agent_version_hash"],
        "prior_v9_trace_sha256": prior["trace_sha256"],
        "prior_v9_failure_category": _PRIOR_V9_FAILURE_CATEGORY,
        "prior_v10_report_hash": prior_v10["report_hash"],
        "prior_v10_agent_version_hash": prior_v10["agent_version_hash"],
        "prior_v10_trace_sha256": prior_v10["trace_sha256"],
        "prior_v10_failure_category": _PRIOR_V10_FAILURE_CATEGORY,
        "prior_v11_report_hash": prior_v11["report_hash"],
        "prior_v11_agent_version_hash": prior_v11["agent_version_hash"],
        "prior_v11_trace_sha256": prior_v11["trace_sha256"],
        "prior_v11_failure_category": _PRIOR_V11_FAILURE_CATEGORY,
        "prior_v12_report_hash": prior_v12["report_hash"],
        "prior_v12_agent_version_hash": prior_v12["agent_version_hash"],
        "prior_v12_trace_sha256": prior_v12["trace_sha256"],
        "prior_v12_failure_category": _PRIOR_V12_FAILURE_CATEGORY,
        "model_transport_id": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MODEL,
        "model_identity": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_AGENT_VERSION_ID,
        "agent_version_hash": version.version_hash,
        "openhands_sdk_version": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SDK_VERSION,
        "litellm_version": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TIKTOKEN_VERSION,
        "seed": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SEED,
        "temperature": 0,
        "top_p": 1,
        "max_iterations": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_ITERATIONS,
        "max_output_tokens": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
        "max_context_tokens": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_CONTEXT_TOKENS,
        "tool_choice_policy": OPENHANDS_RESPONSES_RECOVERY_POLICY,
        "recovery_transport": "responses_api",
        "format_recovery_budget": 1,
        "acceptance_requires_recovery_count": None,
        "acceptance_requires_typed_finish": True,
        "acceptance_requires_verifier_pass": True,
        "acceptance_requires_eligible_trajectory": True,
        "recoverable_policy_rejections": ["invalid_arguments"],
        "failed_decisions_retained_as_context": True,
        "failed_decisions_supervised": False,
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
        seal_responses_recovery_diagnostic_report(preregistration),
    )

    run_id = f"{arguments.campaign_id}-pr2032"
    started = time.monotonic()
    try:
        result = service.run(
            RunConfig(
                task_id=OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TASK,
                suite_source=source,
                expected_suite_source_snapshot=snapshot,
                expected_task_hash=entry.task_hash,
                expected_source_hash=entry.source_hash,
                mode=InteractionMode.AGENT,
                agent=agent.descriptor.name,
                agent_options={
                    "model_id": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MODEL,
                    "base_url_env": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_BASE_URL_ENV,
                    "api_key_env": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_API_KEY_ENV,
                    "max_iterations": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_ITERATIONS,
                    "max_process_time_s": 3_600,
                    "max_output_tokens": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_OUTPUT_TOKENS,
                    "max_context_tokens": (
                        OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_MAX_CONTEXT_TOKENS
                    ),
                    "seed": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SEED,
                    "temperature": 0,
                    "top_p": 1,
                    "whole_episode_retries": 0,
                    "expected_sdk_version": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SDK_VERSION,
                    "campaign_role": "training",
                    "capture_training_transcript": True,
                    "agent_version_id": version.agent_version_id,
                    "agent_version_hash": version.version_hash,
                    "agent_version_manifest_json": manifest_json,
                    "collection_profile_id": "hwe_production_native_shell_v2",
                    "tool_choice_policy": OPENHANDS_RESPONSES_RECOVERY_POLICY,
                },
                runtime="docker",
                docker_config=runtime_config,
                seed=OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SEED,
                sample_index=0,
                output=runs,
                run_id=run_id,
                experiment_id=arguments.campaign_id,
                plan_item_id=run_id,
                system_id="openhands-deepseek-v4-flash-hwe-finish-trajectory-v13",
                base_seed=OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SEED,
            )
        )
    except Exception as exc:
        report = seal_responses_recovery_diagnostic_report(
            {
                **preregistration,
                "format_id": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_REPORT_FORMAT,
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
    raw_forced_count = summary.get("recovery_forced_request_count", 0) if summary else 0
    forced_count_valid = (
        isinstance(raw_forced_count, int)
        and not isinstance(raw_forced_count, bool)
        and raw_forced_count in {0, 1}
    )
    forced_count = raw_forced_count if forced_count_valid else 0
    raw_validated_count = summary.get("recovery_validated_finish_count", 0) if summary else 0
    validated_count_valid = (
        isinstance(raw_validated_count, int)
        and not isinstance(raw_validated_count, bool)
        and raw_validated_count in {0, 1}
    )
    validated_count = raw_validated_count if validated_count_valid else 0
    raw_coalesced_count = summary.get("recovery_coalesced_output_count", 0) if summary else 0
    coalesced_count_valid = (
        isinstance(raw_coalesced_count, int)
        and not isinstance(raw_coalesced_count, bool)
        and 0 <= raw_coalesced_count <= 512
    )
    coalesced_count = raw_coalesced_count if coalesced_count_valid else 0
    response_shape = summary.get("recovery_response_shape") if summary else None
    response_shape_required = forced_count == 1
    response_shape_valid = (
        _valid_response_shape(response_shape)
        if response_shape_required
        else response_shape in (None, {})
    )
    event_type_counts = summary.get("event_type_counts") if summary else None
    interrupt_free = (
        isinstance(event_type_counts, dict) and event_type_counts.get("InterruptEvent", 0) == 0
    )
    tool_choice_bound = (
        summary is not None
        and summary.get("tool_choice_policy") == OPENHANDS_RESPONSES_RECOVERY_POLICY
    )
    evidence_complete = (
        broker is not None
        and summary is not None
        and accounting is not None
        and recovery_count_valid
        and forced_count_valid
        and validated_count_valid
        and coalesced_count_valid
        and response_shape_valid
        and validated_count <= forced_count
        and interrupt_free
        and tool_choice_bound
    )
    infrastructure_valid = not _infrastructure_invalid(result.scorecard) and evidence_complete
    typed_finish = broker is not None and broker.get("finished") is True
    failure = result.scorecard.failure
    failure_category = failure.category if failure is not None else None
    trajectory_paths = sorted(evidence_root.glob("training-trajectory.json"))
    trajectory_summary: dict[str, Any]
    if result.scorecard.resolved:
        if len(trajectory_paths) != 1:
            raise ConfigurationError("verifier-pass tool-choice diagnostic lacks one trajectory")
        trajectory_path = trajectory_paths[0]
        trajectory = validate_openhands_training_trajectory(_json(trajectory_path))
        if (
            trajectory.get("format_id")
            not in {
                OPENHANDS_RECOVERY_TRAJECTORY_FORMAT,
                OPENHANDS_MASKED_RECOVERY_TRAJECTORY_FORMAT,
            }
            or trajectory.get("verifier_resolved") is not True
            or trajectory.get("sft_eligible") is not True
            or trajectory.get("format_recovery_count") not in {0, 1}
        ):
            raise ConfigurationError("finish qualification trajectory is not eligible v2/v3 data")
        trajectory_summary = {
            "exported": True,
            "format_id": trajectory["format_id"],
            "transcript_hash": trajectory["transcript_hash"],
            "file_sha256": hash_bytes(trajectory_path.read_bytes()),
            "assistant_decision_count": trajectory["assistant_decision_count"],
            "supervised_decision_count": trajectory.get(
                "supervised_decision_count", trajectory["assistant_decision_count"]
            ),
            "masked_policy_error_decision_count": trajectory.get(
                "masked_policy_error_decision_count", 0
            ),
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
            "supervised_decision_count": 0,
            "masked_policy_error_decision_count": 0,
            "recovery_count": recovery_count,
            "dataset_admitted": False,
        }

    status, diagnostic_passed = classify_responses_recovery_diagnostic(
        infrastructure_valid=infrastructure_valid,
        typed_finish_observed=typed_finish,
        recovery_count=recovery_count,
        forced_request_count=forced_count,
        validated_finish_count=validated_count,
        coalesced_output_count=coalesced_count,
        failure_category=failure_category,
        ordinary_verifier_resolved=result.scorecard.resolved,
        trajectory_exported=trajectory_summary["exported"] is True,
    )

    credential_scan = _assert_provider_values_absent(root)
    report = seal_responses_recovery_diagnostic_report(
        {
            **preregistration,
            "format_id": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_REPORT_FORMAT,
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
            "recovery_forced_request_count": forced_count,
            "recovery_validated_finish_count": validated_count,
            "recovery_coalesced_output_count": coalesced_count,
            "recovery_response_shape": response_shape if response_shape_valid else None,
            "recovery_response_shape_required": response_shape_required,
            "interrupt_free": interrupt_free,
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
        "openhands-sdk": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_SDK_VERSION,
        "litellm": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_LITELLM_VERSION,
        "tiktoken": OPENHANDS_RESPONSES_RECOVERY_DIAGNOSTIC_TIKTOKEN_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"{package} differs from the frozen tool-choice diagnostic")


def _prior_v9_failure(path: Path) -> dict[str, str]:
    report_path = path.resolve(strict=True)
    report = _json(report_path)
    observed = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    trajectory = report.get("trajectory")
    if (
        not isinstance(observed, str)
        or content_hash(base) != observed
        or report.get("agent_version_id") != _PRIOR_V9_AGENT_VERSION_ID
        or report.get("status") != _PRIOR_V9_STATUS
        or report.get("scorecard_failure_category") != _PRIOR_V9_FAILURE_CATEGORY
        or report.get("infrastructure_valid") is not False
        or report.get("evidence_complete") is not False
        or report.get("tool_choice_bound") is not False
        or report.get("typed_finish_observed") is not False
        or report.get("format_recovery_count") != 0
        or report.get("recovery_forced_request_count") != 0
        or report.get("recovery_validated_finish_count") != 0
        or report.get("model_call_count") is not None
        or report.get("tool_call_count") is not None
        or report.get("patch_call_count") is not None
        or report.get("interrupt_free") is not False
        or not isinstance(trajectory, dict)
        or trajectory.get("exported") is not False
    ):
        raise ConfigurationError("prior OpenHands v9 zero-call failure changed")
    version_hash = report.get("agent_version_hash")
    if not isinstance(version_hash, str) or len(version_hash) != 64:
        raise ConfigurationError("prior OpenHands v9 agent version hash is absent")
    version = _json(report_path.parent / "agent-version.json")
    image_hashes = version.get("image_hashes")
    task_agent_hash = image_hashes.get("task-agent") if isinstance(image_hashes, dict) else None
    task_verifier_hash = (
        image_hashes.get("task-verifier") if isinstance(image_hashes, dict) else None
    )
    if (
        version.get("agent_version_id") != _PRIOR_V9_AGENT_VERSION_ID
        or version.get("version_hash") != version_hash
        or version.get("source_commit") != report.get("source_commit")
        or not isinstance(task_agent_hash, str)
        or len(task_agent_hash) != 64
        or not isinstance(task_verifier_hash, str)
        or len(task_verifier_hash) != 64
    ):
        raise ConfigurationError("prior OpenHands v9 agent-version identity changed")
    runs = sorted((report_path.parent / "runs").iterdir())
    if len(runs) != 1:
        raise ConfigurationError("prior OpenHands v9 run inventory changed")
    trace_path = (runs[0] / "trace.jsonl").resolve(strict=True)
    terminations = [
        event for event in _json_lines(trace_path) if event.get("event_type") == "agent_terminated"
    ]
    prompt_bindings = [
        event
        for event in _json_lines(trace_path)
        if event.get("event_type") == "openhands_sdk_hwe_prompt_policy_bound"
    ]
    if (
        len(terminations) != 1
        or terminations[0].get("payload", {}).get("failure", {}).get("category")
        != _PRIOR_V9_FAILURE_CATEGORY
        or terminations[0].get("payload", {}).get("failure", {}).get("infrastructure") is not True
        or len(prompt_bindings) != 1
        or prompt_bindings[0].get("payload", {}).get("model_call_count") != 0
    ):
        raise ConfigurationError("prior OpenHands v9 zero-call trace evidence changed")
    return {
        "report_hash": observed,
        "agent_version_hash": version_hash,
        "trace_sha256": hash_bytes(trace_path.read_bytes()),
        "task_id": str(report["task_id"]),
        "task_hash": str(report["task_hash"]),
        "source_hash": str(report["source_hash"]),
        "image_lock_hash": str(report["image_lock_hash"]),
        "task_agent_hash": task_agent_hash,
        "task_verifier_hash": task_verifier_hash,
    }


def _prior_v9_image_lock(prior: dict[str, str]) -> _PriorV9ImageLock:
    agent_image = "sha256:" + prior["task_agent_hash"]
    verifier_image = "sha256:" + prior["task_verifier_hash"]
    inspection = subprocess.run(
        ["docker", "image", "inspect", agent_image],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    values = json.loads(inspection.stdout)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ConfigurationError("prior OpenHands v9 agent image inspection is malformed")
    config = values[0].get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    codex_hash = labels.get("org.verigym.codex.binary.sha256") if isinstance(labels, dict) else None
    rg_hash = labels.get("org.verigym.codex.rg.sha256") if isinstance(labels, dict) else None
    expected_labels = {
        "org.verigym.collection.profile": "hwe_standard_v2",
        "org.verigym.tool.contract": "hwe_native_shell_v2",
        "org.verigym.hwe.task_id": prior["task_id"],
        "org.verigym.cva6.verifier_base_image_id": verifier_image,
    }
    if (
        not isinstance(labels, dict)
        or any(labels.get(name) != value for name, value in expected_labels.items())
        or not isinstance(codex_hash, str)
        or len(codex_hash) != 64
        or not isinstance(rg_hash, str)
        or len(rg_hash) != 64
        or len(prior["image_lock_hash"]) != 64
    ):
        raise ConfigurationError("prior OpenHands v9 agent image identity changed")
    return _PriorV9ImageLock(
        task_id=prior["task_id"],
        task_hash=prior["task_hash"],
        source_hash=prior["source_hash"],
        verifier_base_image_id=verifier_image,
        derived_agent_image_id=agent_image,
        agent_codex_sha256=codex_hash,
        agent_rg_sha256=rg_hash,
        lock_hash=prior["image_lock_hash"],
    )


def _prior_v10_failure(path: Path) -> dict[str, str]:
    """Bind the full-history Responses 400 that motivated output coalescing."""

    report_path = path.resolve(strict=True)
    report = _json(report_path)
    observed = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    trajectory = report.get("trajectory")
    if (
        not isinstance(observed, str)
        or content_hash(base) != observed
        or report.get("agent_version_id") != _PRIOR_V10_AGENT_VERSION_ID
        or report.get("status") != _PRIOR_V10_STATUS
        or report.get("scorecard_failure_category") != _PRIOR_V10_FAILURE_CATEGORY
        or report.get("scorecard_failure_kind") != "runtime"
        or report.get("infrastructure_valid") is not False
        or report.get("evidence_complete") is not False
        or report.get("typed_finish_observed") is not False
        or report.get("ordinary_verifier_resolved") is not False
        or report.get("recovery_validated_finish_count") != 0
        or not isinstance(trajectory, dict)
        or trajectory.get("exported") is not False
    ):
        raise ConfigurationError("prior OpenHands v10 Responses failure changed")
    version_hash = report.get("agent_version_hash")
    if not isinstance(version_hash, str) or len(version_hash) != 64:
        raise ConfigurationError("prior OpenHands v10 agent version hash is absent")
    version = _json(report_path.parent / "agent-version.json")
    if (
        version.get("agent_version_id") != _PRIOR_V10_AGENT_VERSION_ID
        or version.get("version_hash") != version_hash
        or version.get("source_commit") != report.get("source_commit")
    ):
        raise ConfigurationError("prior OpenHands v10 agent-version identity changed")
    runs = sorted((report_path.parent / "runs").iterdir())
    if len(runs) != 1:
        raise ConfigurationError("prior OpenHands v10 run inventory changed")
    trace_path = (runs[0] / "trace.jsonl").resolve(strict=True)
    failures = [
        event
        for event in _json_lines(trace_path)
        if event.get("event_type") == "openhands_sdk_hwe_episode_failed"
    ]
    terminations = [
        event for event in _json_lines(trace_path) if event.get("event_type") == "agent_terminated"
    ]
    failure_payload = failures[0].get("payload", {}) if len(failures) == 1 else {}
    termination_failure = (
        terminations[0].get("payload", {}).get("failure", {}) if len(terminations) == 1 else {}
    )
    if (
        failure_payload.get("root_exception_type") != "BadRequestError"
        or failure_payload.get("failure_stage") != "agent_loop"
        or failure_payload.get("recovery_forced_request_count") != 1
        or failure_payload.get("recovery_validated_finish_count") != 0
        or failure_payload.get("raw_exception_message_persisted") is not False
        or failure_payload.get("raw_model_content_persisted") is not False
        or termination_failure.get("category") != _PRIOR_V10_FAILURE_CATEGORY
        or termination_failure.get("infrastructure") is not True
    ):
        raise ConfigurationError("prior OpenHands v10 Responses trace evidence changed")
    return {
        "report_hash": observed,
        "agent_version_hash": version_hash,
        "trace_sha256": hash_bytes(trace_path.read_bytes()),
    }


def _prior_v11_failure(path: Path) -> dict[str, str]:
    """Bind the infrastructure-valid non-finish response after v11 coalescing."""

    report_path = path.resolve(strict=True)
    report = _json(report_path)
    observed = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    trajectory = report.get("trajectory")
    if (
        not isinstance(observed, str)
        or content_hash(base) != observed
        or report.get("agent_version_id") != _PRIOR_V11_AGENT_VERSION_ID
        or report.get("status") != _PRIOR_V11_STATUS
        or report.get("scorecard_failure_category") != _PRIOR_V11_FAILURE_CATEGORY
        or report.get("scorecard_failure_kind") != "model"
        or report.get("infrastructure_valid") is not True
        or report.get("evidence_complete") is not True
        or report.get("tool_choice_bound") is not True
        or report.get("typed_finish_observed") is not False
        or report.get("format_recovery_count") != 1
        or report.get("recovery_forced_request_count") != 1
        or report.get("recovery_validated_finish_count") != 0
        or report.get("recovery_coalesced_output_count") != 14
        or report.get("model_call_count") != 14
        or report.get("tool_call_count") != 14
        or report.get("patch_call_count") != 0
        or not isinstance(trajectory, dict)
        or trajectory.get("exported") is not False
    ):
        raise ConfigurationError("prior OpenHands v11 response rejection changed")
    version_hash = report.get("agent_version_hash")
    if not isinstance(version_hash, str) or len(version_hash) != 64:
        raise ConfigurationError("prior OpenHands v11 agent version hash is absent")
    version = _json(report_path.parent / "agent-version.json")
    if (
        version.get("agent_version_id") != _PRIOR_V11_AGENT_VERSION_ID
        or version.get("version_hash") != version_hash
        or version.get("source_commit") != report.get("source_commit")
    ):
        raise ConfigurationError("prior OpenHands v11 agent-version identity changed")
    runs = sorted((report_path.parent / "runs").iterdir())
    if len(runs) != 1:
        raise ConfigurationError("prior OpenHands v11 run inventory changed")
    trace_path = (runs[0] / "trace.jsonl").resolve(strict=True)
    failures = [
        event
        for event in _json_lines(trace_path)
        if event.get("event_type") == "openhands_sdk_hwe_episode_failed"
    ]
    failure_payload = failures[0].get("payload", {}) if len(failures) == 1 else {}
    if (
        failure_payload.get("root_exception_type") != "RecoveryToolChoiceViolation"
        or failure_payload.get("recovery_forced_request_count") != 1
        or failure_payload.get("recovery_validated_finish_count") != 0
        or failure_payload.get("recovery_coalesced_output_count") != 14
        or failure_payload.get("raw_exception_message_persisted") is not False
        or failure_payload.get("raw_model_content_persisted") is not False
    ):
        raise ConfigurationError("prior OpenHands v11 response trace evidence changed")
    return {
        "report_hash": observed,
        "agent_version_hash": version_hash,
        "trace_sha256": hash_bytes(trace_path.read_bytes()),
    }


def _prior_v12_failure(path: Path) -> dict[str, str]:
    """Bind the verifier-passing candidate rejected only for invalid arguments."""

    report_path = path.resolve(strict=True)
    report = _json(report_path)
    observed = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    trajectory = report.get("trajectory")
    if (
        not isinstance(observed, str)
        or content_hash(base) != observed
        or report.get("agent_version_id") != _PRIOR_V12_AGENT_VERSION_ID
        or report.get("status") != _PRIOR_V12_STATUS
        or report.get("scorecard_failure_category") != _PRIOR_V12_FAILURE_CATEGORY
        or report.get("scorecard_failure_kind") != "model"
        or report.get("infrastructure_valid") is not False
        or report.get("evidence_complete") is not False
        or report.get("tool_choice_bound") is not True
        or report.get("typed_finish_observed") is not True
        or report.get("format_recovery_count") != 0
        or report.get("recovery_forced_request_count") != 0
        or report.get("recovery_validated_finish_count") != 0
        or report.get("recovery_coalesced_output_count") != 0
        or report.get("model_call_count") != 48
        or report.get("tool_call_count") != 49
        or report.get("patch_call_count") != 4
        or not isinstance(trajectory, dict)
        or trajectory.get("exported") is not False
    ):
        raise ConfigurationError("prior OpenHands v12 policy rejection changed")
    version_hash = report.get("agent_version_hash")
    if not isinstance(version_hash, str) or len(version_hash) != 64:
        raise ConfigurationError("prior OpenHands v12 agent version hash is absent")
    version = _json(report_path.parent / "agent-version.json")
    if (
        version.get("agent_version_id") != _PRIOR_V12_AGENT_VERSION_ID
        or version.get("version_hash") != version_hash
        or version.get("source_commit") != report.get("source_commit")
    ):
        raise ConfigurationError("prior OpenHands v12 agent-version identity changed")
    runs = sorted((report_path.parent / "runs").iterdir())
    if len(runs) != 1:
        raise ConfigurationError("prior OpenHands v12 run inventory changed")
    run = runs[0]
    trace_path = (run / "trace.jsonl").resolve(strict=True)
    scorecard = _json(run / "scorecard.json")
    broker = _json(run / "artifacts" / "openhands_sdk" / "broker.json")
    correctness = scorecard.get("correctness")
    if (
        scorecard.get("resolved") is not False
        or scorecard.get("termination_reason") != "policy_violation"
        or not isinstance(correctness, dict)
        or correctness.get("hidden_regression_status") != "passed"
        or correctness.get("tests_passed") != 2
        or correctness.get("tests_total") != 2
        or broker.get("finished") is not True
        or broker.get("policy_failure") != "HweShellCommandPolicyError"
        or broker.get("rejected_calls") != 2
        or broker.get("rejection_codes") != ["invalid_arguments", "invalid_arguments"]
    ):
        raise ConfigurationError("prior OpenHands v12 verifier/policy evidence changed")
    return {
        "report_hash": observed,
        "agent_version_hash": version_hash,
        "trace_sha256": hash_bytes(trace_path.read_bytes()),
    }


def _valid_response_shape(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "raw_output_count",
        "raw_output_types",
        "raw_function_names",
        "converted_tool_call_count",
        "converted_tool_names",
        "converted_text_part_count",
    }:
        return False
    for name in (
        "raw_output_count",
        "converted_tool_call_count",
        "converted_text_part_count",
    ):
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 64:
            return False
    for name in ("raw_output_types", "raw_function_names", "converted_tool_names"):
        items = value.get(name)
        if (
            not isinstance(items, list)
            or len(items) > 16
            or any(not isinstance(item, str) or len(item) > 96 for item in items)
        ):
            return False
    return True


def _json_lines(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ConfigurationError("OpenHands diagnostic trace row is not an object")
        values.append(value)
    return values


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
                "recovery_coalesced_output_count": report["recovery_coalesced_output_count"],
                "recovery_response_shape": report["recovery_response_shape"],
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
