#!/usr/bin/env python3
"""Run one frozen OpenHands positive trajectory qualification on CVA6 PR-2944."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import time
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_positive_qualification import (
    OPENHANDS_POSITIVE_QUALIFICATION_AGENT_VERSION_ID,
    OPENHANDS_POSITIVE_QUALIFICATION_API_KEY_ENV,
    OPENHANDS_POSITIVE_QUALIFICATION_BASE_URL_ENV,
    OPENHANDS_POSITIVE_QUALIFICATION_CAMPAIGN_ID,
    OPENHANDS_POSITIVE_QUALIFICATION_FORMAT,
    OPENHANDS_POSITIVE_QUALIFICATION_LITELLM_VERSION,
    OPENHANDS_POSITIVE_QUALIFICATION_MAX_CONTEXT_TOKENS,
    OPENHANDS_POSITIVE_QUALIFICATION_MAX_ITERATIONS,
    OPENHANDS_POSITIVE_QUALIFICATION_MAX_OUTPUT_TOKENS,
    OPENHANDS_POSITIVE_QUALIFICATION_MODEL,
    OPENHANDS_POSITIVE_QUALIFICATION_MODEL_IDENTITY,
    OPENHANDS_POSITIVE_QUALIFICATION_OPT_IN_ENV,
    OPENHANDS_POSITIVE_QUALIFICATION_REPORT_FORMAT,
    OPENHANDS_POSITIVE_QUALIFICATION_SDK_VERSION,
    OPENHANDS_POSITIVE_QUALIFICATION_SEED,
    OPENHANDS_POSITIVE_QUALIFICATION_TASK,
    OPENHANDS_POSITIVE_QUALIFICATION_TIKTOKEN_VERSION,
    build_positive_qualification_agent_version,
    classify_positive_qualification,
    seal_positive_qualification_report,
)
from verigym_openhands.hwe_responses_recovery_diagnostic import (
    OPENHANDS_RESPONSES_RECOVERY_POLICY,
)
from verigym_openhands.trajectory import (
    OPENHANDS_MASKED_RECOVERY_TRAJECTORY_FORMAT,
    OPENHANDS_RECOVERY_TRAJECTORY_FORMAT,
    OPENHANDS_TRAJECTORY_FORMAT,
    validate_openhands_training_trajectory,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweAgentImageLock
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_recovery_runner = importlib.import_module(
    "scripts.run_cva6_hwe_openhands_recovery_diagnostic"
    if __package__
    else "run_cva6_hwe_openhands_recovery_diagnostic"
)
_clean_source_commit = _recovery_runner._clean_source_commit
_docker_config = _recovery_runner._docker_config
_infrastructure_invalid = _recovery_runner._infrastructure_invalid
_json = _recovery_runner._json
_new_output = _recovery_runner._new_output
_optional_json = _recovery_runner._optional_json
_qualified_sources = _recovery_runner._qualified_sources
_validated_split = _recovery_runner._validated_split

_PRIOR_POSITIVE_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-pr2944-training-v1"
_PRIOR_POSITIVE_STATUS = "verifier_pass"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--agent-image-lock", type=Path, required=True)
    parser.add_argument("--prior-positive-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--campaign-id",
        default=OPENHANDS_POSITIVE_QUALIFICATION_CAMPAIGN_ID,
    )
    return parser


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute exactly one no-retry model episode and seal verifier-gated evidence."""

    if os.environ.get(OPENHANDS_POSITIVE_QUALIFICATION_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_POSITIVE_QUALIFICATION_OPT_IN_ENV}=1 is required")
    if arguments.campaign_id != OPENHANDS_POSITIVE_QUALIFICATION_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands positive qualification campaign identity changed")
    if not os.environ.get(OPENHANDS_POSITIVE_QUALIFICATION_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_POSITIVE_QUALIFICATION_API_KEY_ENV
    ):
        raise ConfigurationError(
            "OpenHands positive qualification provider environment is incomplete"
        )
    _validate_package_versions()

    source_commit = _clean_source_commit()
    qualification = arguments.qualification_root.resolve(strict=True)
    split = _validated_split(qualification)
    training = {entry.task_id: entry for entry in split.training}
    if OPENHANDS_POSITIVE_QUALIFICATION_TASK not in training or any(
        entry.task_id == OPENHANDS_POSITIVE_QUALIFICATION_TASK
        for entry in (*split.validation, *split.heldout)
    ):
        raise ConfigurationError("OpenHands positive qualification task split binding changed")
    progress = _json(qualification / "qualification-progress.json")
    if (
        progress.get("status") != "completed"
        or progress.get("task_split_hash") != split.manifest_hash
    ):
        raise ConfigurationError("CVA6 qualification is incomplete or changed")
    source_by_task = _qualified_sources(progress)
    source_root = (qualification / source_by_task[OPENHANDS_POSITIVE_QUALIFICATION_TASK]).resolve(
        strict=True
    )
    if not source_root.is_relative_to(qualification):
        raise ConfigurationError("OpenHands positive qualification source escaped its root")
    lock = HweAgentImageLock.model_validate(_json(arguments.agent_image_lock.resolve(strict=True)))
    entry = training[OPENHANDS_POSITIVE_QUALIFICATION_TASK]
    if (
        lock.task_id != OPENHANDS_POSITIVE_QUALIFICATION_TASK
        or lock.task_hash != entry.task_hash
        or lock.source_hash != entry.source_hash
    ):
        raise ConfigurationError("OpenHands positive qualification task/image binding changed")
    prior = _prior_positive(arguments.prior_positive_report)
    if prior["task_hash"] != entry.task_hash or prior["source_hash"] != entry.source_hash:
        raise ConfigurationError("prior positive task/source binding changed")

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
        runtime.prepare("openhands-positive-qualification-v1-pr2944")
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
    suite, task, _assets = service.load_task(OPENHANDS_POSITIVE_QUALIFICATION_TASK, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != entry.task_hash
        or task.source.content_hash != entry.source_hash
    ):
        raise ConfigurationError("OpenHands positive qualification source changed")

    version = build_positive_qualification_agent_version(
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
        "format_id": OPENHANDS_POSITIVE_QUALIFICATION_FORMAT,
        "status": "execution_started",
        "qualification_only": True,
        "campaign_id": arguments.campaign_id,
        "task_id": OPENHANDS_POSITIVE_QUALIFICATION_TASK,
        "task_hash": entry.task_hash,
        "source_hash": entry.source_hash,
        "source_commit": source_commit,
        "image_lock_hash": lock.lock_hash,
        "prior_positive_report_hash": prior["report_hash"],
        "prior_positive_agent_version_hash": prior["agent_version_hash"],
        "prior_positive_trajectory_sha256": prior["trajectory_sha256"],
        "model_transport_id": OPENHANDS_POSITIVE_QUALIFICATION_MODEL,
        "model_identity": OPENHANDS_POSITIVE_QUALIFICATION_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_POSITIVE_QUALIFICATION_AGENT_VERSION_ID,
        "agent_version_hash": version.version_hash,
        "openhands_sdk_version": OPENHANDS_POSITIVE_QUALIFICATION_SDK_VERSION,
        "litellm_version": OPENHANDS_POSITIVE_QUALIFICATION_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_POSITIVE_QUALIFICATION_TIKTOKEN_VERSION,
        "seed": OPENHANDS_POSITIVE_QUALIFICATION_SEED,
        "temperature": 0,
        "top_p": 1,
        "max_iterations": OPENHANDS_POSITIVE_QUALIFICATION_MAX_ITERATIONS,
        "max_output_tokens": OPENHANDS_POSITIVE_QUALIFICATION_MAX_OUTPUT_TOKENS,
        "max_context_tokens": OPENHANDS_POSITIVE_QUALIFICATION_MAX_CONTEXT_TOKENS,
        "tool_choice_policy": OPENHANDS_RESPONSES_RECOVERY_POLICY,
        "format_recovery_budget": 1,
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
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "new_hpc_jobs_submitted": False,
        "gpu_seconds": 0,
    }
    atomic_dump_json(
        root / "preregistration.json",
        seal_positive_qualification_report(preregistration),
    )

    run_id = f"{arguments.campaign_id}-pr2944-s484"
    started = time.monotonic()
    try:
        result = service.run(
            RunConfig(
                task_id=OPENHANDS_POSITIVE_QUALIFICATION_TASK,
                suite_source=source,
                expected_suite_source_snapshot=snapshot,
                expected_task_hash=entry.task_hash,
                expected_source_hash=entry.source_hash,
                mode=InteractionMode.AGENT,
                agent=agent.descriptor.name,
                agent_options={
                    "model_id": OPENHANDS_POSITIVE_QUALIFICATION_MODEL,
                    "base_url_env": OPENHANDS_POSITIVE_QUALIFICATION_BASE_URL_ENV,
                    "api_key_env": OPENHANDS_POSITIVE_QUALIFICATION_API_KEY_ENV,
                    "max_iterations": OPENHANDS_POSITIVE_QUALIFICATION_MAX_ITERATIONS,
                    "max_process_time_s": 3_600,
                    "max_output_tokens": OPENHANDS_POSITIVE_QUALIFICATION_MAX_OUTPUT_TOKENS,
                    "max_context_tokens": OPENHANDS_POSITIVE_QUALIFICATION_MAX_CONTEXT_TOKENS,
                    "seed": OPENHANDS_POSITIVE_QUALIFICATION_SEED,
                    "temperature": 0,
                    "top_p": 1,
                    "whole_episode_retries": 0,
                    "expected_sdk_version": OPENHANDS_POSITIVE_QUALIFICATION_SDK_VERSION,
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
                seed=OPENHANDS_POSITIVE_QUALIFICATION_SEED,
                sample_index=0,
                output=runs,
                run_id=run_id,
                experiment_id=arguments.campaign_id,
                plan_item_id=run_id,
                system_id="openhands-deepseek-v4-flash-hwe-positive-qualification-v1",
                base_seed=OPENHANDS_POSITIVE_QUALIFICATION_SEED,
            )
        )
    except Exception as exc:
        report = seal_positive_qualification_report(
            {
                **preregistration,
                "format_id": OPENHANDS_POSITIVE_QUALIFICATION_REPORT_FORMAT,
                "status": "run_boundary_exception",
                "qualification_passed": False,
                "exception_type": type(exc).__name__,
                "wall_seconds": time.monotonic() - started,
            }
        )
        atomic_dump_json(root / "qualification-report.json", report)
        _assert_provider_values_absent(root)
        raise ConfigurationError("OpenHands positive qualification failed at run boundary") from exc

    wall_seconds = time.monotonic() - started
    run_directory = Path(result.run_dir).resolve(strict=True)
    evidence_root = run_directory / "artifacts" / "openhands_sdk"
    broker = _optional_json(evidence_root / "broker.json")
    summary = _optional_json(evidence_root / "summary.json")
    accounting = _optional_json(evidence_root / "accounting.json")
    recovery_count = _bounded_counter(summary, "format_recovery_count", maximum=1)
    forced_count = _bounded_counter(summary, "recovery_forced_request_count", maximum=1)
    validated_finish_count = _bounded_counter(summary, "recovery_validated_finish_count", maximum=1)
    validated_tool_count = _bounded_counter(summary, "recovery_validated_tool_count", maximum=1)
    coalesced_count = _bounded_counter(summary, "recovery_coalesced_output_count", maximum=512)
    event_type_counts = summary.get("event_type_counts") if summary else None
    interrupt_free = (
        isinstance(event_type_counts, dict) and event_type_counts.get("InterruptEvent", 0) == 0
    )
    tool_choice_bound = (
        summary is not None
        and summary.get("tool_choice_policy") == OPENHANDS_RESPONSES_RECOVERY_POLICY
    )
    counters_valid = all(
        value is not None
        for value in (
            recovery_count,
            forced_count,
            validated_finish_count,
            validated_tool_count,
            coalesced_count,
        )
    )
    if counters_valid:
        assert forced_count is not None
        assert validated_finish_count is not None
        assert validated_tool_count is not None
        counters_valid = validated_finish_count + validated_tool_count <= forced_count
    evidence_complete = (
        broker is not None
        and summary is not None
        and accounting is not None
        and counters_valid
        and interrupt_free
        and tool_choice_bound
    )
    infrastructure_valid = not _infrastructure_invalid(result.scorecard) and evidence_complete
    typed_finish = broker is not None and broker.get("finished") is True
    failure = result.scorecard.failure
    trajectory_paths = sorted(evidence_root.glob("training-trajectory.json"))
    trajectory_summary = _trajectory_summary(
        trajectory_paths,
        verifier_resolved=result.scorecard.resolved,
    )
    status, qualification_passed = classify_positive_qualification(
        infrastructure_valid=infrastructure_valid,
        evidence_complete=evidence_complete,
        tool_choice_bound=tool_choice_bound,
        typed_finish_observed=typed_finish,
        ordinary_verifier_resolved=result.scorecard.resolved,
        trajectory_exported=trajectory_summary["exported"] is True,
    )
    credential_scan = _assert_provider_values_absent(root)
    report = seal_positive_qualification_report(
        {
            **preregistration,
            "format_id": OPENHANDS_POSITIVE_QUALIFICATION_REPORT_FORMAT,
            "status": status,
            "qualification_passed": qualification_passed,
            "infrastructure_valid": infrastructure_valid,
            "evidence_complete": evidence_complete,
            "tool_choice_bound": tool_choice_bound,
            "ordinary_verifier_resolved": result.scorecard.resolved,
            "scorecard_status": result.scorecard.status,
            "scorecard_failure_kind": failure.kind if failure is not None else None,
            "scorecard_failure_category": failure.category if failure is not None else None,
            "typed_finish_observed": typed_finish,
            "format_recovery_count": recovery_count,
            "recovery_forced_request_count": forced_count,
            "recovery_validated_finish_count": validated_finish_count,
            "recovery_validated_tool_count": validated_tool_count,
            "recovery_coalesced_output_count": coalesced_count,
            "interrupt_free": interrupt_free,
            "model_call_count": accounting.get("model_call_count") if accounting else None,
            "tool_call_count": broker.get("tool_calls") if broker else None,
            "patch_call_count": broker.get("patches") if broker else None,
            "wall_seconds": wall_seconds,
            "trajectory": trajectory_summary,
            "credential_scan": credential_scan,
        }
    )
    atomic_dump_json(root / "qualification-report.json", report)
    return report


def _validate_package_versions() -> None:
    expected = {
        "openhands-sdk": OPENHANDS_POSITIVE_QUALIFICATION_SDK_VERSION,
        "litellm": OPENHANDS_POSITIVE_QUALIFICATION_LITELLM_VERSION,
        "tiktoken": OPENHANDS_POSITIVE_QUALIFICATION_TIKTOKEN_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"{package} differs from the frozen positive qualification")


def _prior_positive(path: Path) -> dict[str, str]:
    report_path = path.resolve(strict=True)
    report = _json(report_path)
    observed = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    trajectory = report.get("trajectory")
    if (
        not isinstance(observed, str)
        or content_hash(base) != observed
        or report.get("status") != _PRIOR_POSITIVE_STATUS
        or report.get("task_id") != OPENHANDS_POSITIVE_QUALIFICATION_TASK
        or report.get("infrastructure_valid") is not True
        or report.get("ordinary_verifier_resolved") is not True
        or not isinstance(trajectory, dict)
        or trajectory.get("sft_eligible") is not True
    ):
        raise ConfigurationError("prior positive OpenHands report changed")
    relative = trajectory.get("path")
    expected_sha256 = trajectory.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected_sha256, str):
        raise ConfigurationError("prior positive trajectory binding is absent")
    candidate = report_path.parent / relative
    trajectory_path = candidate.resolve(strict=True)
    if (
        not trajectory_path.is_relative_to(report_path.parent)
        or candidate.is_symlink()
        or hash_bytes(trajectory_path.read_bytes()) != expected_sha256
    ):
        raise ConfigurationError("prior positive trajectory changed")
    version = _json(report_path.parent / "agent-version.json")
    agent_version_hash = report.get("agent_version_hash")
    if (
        version.get("agent_version_id") != _PRIOR_POSITIVE_AGENT_VERSION_ID
        or not isinstance(agent_version_hash, str)
        or version.get("version_hash") != agent_version_hash
    ):
        raise ConfigurationError("prior positive agent version changed")
    preregistration = _json(report_path.parent / "preregistration.json")
    task_hash = preregistration.get("task_hash")
    source_hash = preregistration.get("source_hash")
    if not isinstance(task_hash, str) or not isinstance(source_hash, str):
        raise ConfigurationError("prior positive task/source hashes are absent")
    return {
        "report_hash": observed,
        "agent_version_hash": agent_version_hash,
        "trajectory_sha256": expected_sha256,
        "task_hash": task_hash,
        "source_hash": source_hash,
    }


def _bounded_counter(summary: dict[str, Any] | None, name: str, *, maximum: int) -> int | None:
    value = summary.get(name, 0) if summary else None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        return None
    return value


def _trajectory_summary(paths: list[Path], *, verifier_resolved: bool) -> dict[str, Any]:
    if verifier_resolved:
        if len(paths) != 1:
            raise ConfigurationError("verifier-pass qualification lacks exactly one trajectory")
        path = paths[0]
        trajectory = validate_openhands_training_trajectory(_json(path))
        if (
            trajectory.get("format_id")
            not in {
                OPENHANDS_TRAJECTORY_FORMAT,
                OPENHANDS_RECOVERY_TRAJECTORY_FORMAT,
                OPENHANDS_MASKED_RECOVERY_TRAJECTORY_FORMAT,
            }
            or trajectory.get("task_id") != OPENHANDS_POSITIVE_QUALIFICATION_TASK
            or trajectory.get("model_id") != OPENHANDS_POSITIVE_QUALIFICATION_MODEL
            or trajectory.get("client_name") != "openhands-sdk"
            or trajectory.get("client_version") != OPENHANDS_POSITIVE_QUALIFICATION_SDK_VERSION
            or trajectory.get("typed_finish_observed") is not True
            or trajectory.get("verifier_resolved") is not True
            or trajectory.get("sft_eligible") is not True
        ):
            raise ConfigurationError("positive qualification trajectory is not eligible")
        return {
            "exported": True,
            "format_id": trajectory["format_id"],
            "transcript_hash": trajectory["transcript_hash"],
            "file_sha256": hash_bytes(path.read_bytes()),
            "assistant_decision_count": trajectory["assistant_decision_count"],
            "supervised_decision_count": trajectory.get(
                "supervised_decision_count", trajectory["assistant_decision_count"]
            ),
            "masked_policy_error_decision_count": trajectory.get(
                "masked_policy_error_decision_count", 0
            ),
            "format_recovery_count": trajectory.get("format_recovery_count", 0),
            "dataset_admitted": False,
        }
    if paths:
        raise ConfigurationError("verifier-rejected qualification exported a positive trajectory")
    return {
        "exported": False,
        "format_id": None,
        "transcript_hash": None,
        "file_sha256": None,
        "assistant_decision_count": 0,
        "supervised_decision_count": 0,
        "masked_policy_error_decision_count": 0,
        "format_recovery_count": 0,
        "dataset_admitted": False,
    }


def _assert_provider_values_absent(root: Path) -> dict[str, Any]:
    values = [
        os.environ[OPENHANDS_POSITIVE_QUALIFICATION_BASE_URL_ENV].encode(),
        os.environ[OPENHANDS_POSITIVE_QUALIFICATION_API_KEY_ENV].encode(),
    ]
    file_count = 0
    byte_count = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("OpenHands qualification artifact contains a symlink")
        if not path.is_file():
            continue
        data = path.read_bytes()
        file_count += 1
        byte_count += len(data)
        if any(value in data for value in values):
            raise ConfigurationError("provider value reached OpenHands qualification artifacts")
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
                "qualification_passed": report["qualification_passed"],
                "typed_finish_observed": report["typed_finish_observed"],
                "ordinary_verifier_resolved": report["ordinary_verifier_resolved"],
                "trajectory_exported": report["trajectory"]["exported"],
                "trajectory_format": report["trajectory"]["format_id"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["qualification_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
