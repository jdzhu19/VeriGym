#!/usr/bin/env python3
"""Run the frozen pilot-gated, one-sample-per-task CVA6 HWE Codex campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.splits import validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.campaign import (
    HWE_ACTION_CONDITIONED_CAMPAIGN_FORMAT,
    HWE_CODEX_BASE_INSTRUCTION_POLICY,
    HWE_CODEX_PROMPT_CONTRACT_ID,
    HWE_CODEX_PROMPT_CONTRACT_VERSION,
    HWE_EXEC_LIFECYCLE_POLICY_ID,
    HWE_WORKSPACE_RUNTIME_IMAGE_ID,
    HWE_ZERO_CALL_STARTUP_RESTARTS,
    ActionConditionedAttemptStatus,
    AttemptStatus,
    HweActionConditionedCampaignAttempt,
    HweActionConditionedCampaignState,
    HweCampaignAttempt,
    HweCampaignState,
    build_action_conditioned_handoff,
    build_hpc_handoff,
)
from verigym.hwe.history_masking import (
    HweHistoryMaskingPolicy,
    build_hwe_action_conditioned_dataset_manifest,
    materialize_hwe_action_conditioned_examples,
    validate_hwe_action_conditioned_example,
)
from verigym.hwe.image_lock import HweAgentImageLock
from verigym.hwe.observation import TiktokenO200kCounter
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_TOOL_CONTRACT_V2_ID,
)
from verigym.hwe.trajectory import (
    build_hwe_dataset_manifest,
    materialize_hwe_sft_example,
    validate_hwe_teacher_transcript,
)
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig, DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_OPT_IN = "VERIGYM_RUN_CVA6_HWE_COLLECTION"
CampaignMode = Literal["primary", "action-conditioned"]
HistoryWindow = Literal[1, 2, 8, 10, 16]
HistoryPinnedLimit = Literal[1, 2, 4]
CampaignState = HweCampaignState | HweActionConditionedCampaignState


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument(
        "--campaign-mode",
        choices=("primary", "action-conditioned"),
        default="primary",
        help="keep the historical primary campaign or use experimental per-action M=16 records",
    )
    parser.add_argument(
        "--history-recent-observations",
        type=int,
        choices=(1, 2, 8, 10, 16),
        default=16,
        help="frozen recent-observation window for action-conditioned records",
    )
    parser.add_argument(
        "--history-max-pinned-observations",
        type=int,
        choices=(1, 2, 4),
        default=4,
        help="frozen current-epoch diagnostic pin limit",
    )
    return parser


def collect(
    *,
    qualification_root: Path,
    image_lock_dir: Path,
    output: Path,
    campaign_id: str,
    campaign_mode: CampaignMode = "primary",
    history_recent_observations: HistoryWindow = 16,
    history_max_pinned_observations: HistoryPinnedLimit = 4,
) -> dict[str, Any]:
    if os.environ.get(_OPT_IN) != "1":
        raise ConfigurationError(f"{_OPT_IN}=1 is required")
    qualification = qualification_root.resolve(strict=True)
    progress = _json(qualification / "qualification-progress.json")
    split = validate_task_split(
        TaskSplitManifest.model_validate(_json(qualification / "task-split.json"))
    )
    pool_values = progress.get("training_pool")
    if progress.get("status") != "completed" or not isinstance(pool_values, list):
        raise ConfigurationError("CVA6 HWE qualification is incomplete")
    source_by_task: dict[str, str] = {}
    for item in pool_values:
        if not isinstance(item, dict) or not isinstance(item.get("task_id"), str):
            raise ConfigurationError("CVA6 HWE training pool is malformed")
        if not isinstance(item.get("source"), str):
            raise ConfigurationError("CVA6 HWE source binding is malformed")
        source_by_task[item["task_id"]] = item["source"]
    locks = _image_locks(image_lock_dir, set(source_by_task))
    state: CampaignState
    if campaign_mode == "action-conditioned":
        state = HweActionConditionedCampaignState(
            tuple(source_by_task),
            campaign_id,
            tuple(sorted((task_id, lock.lock_hash) for task_id, lock in locks.items())),
            history_recent_observations=history_recent_observations,
            history_max_pinned_observations=history_max_pinned_observations,
        )
        counter = TiktokenO200kCounter()
        history_policy = HweHistoryMaskingPolicy(
            recent_observations=history_recent_observations,
            max_pinned_observations=history_max_pinned_observations,
        )
    else:
        if history_recent_observations != 16 or history_max_pinned_observations != 4:
            raise ConfigurationError(
                "history masking parameters require campaign-mode=action-conditioned"
            )
        state = HweCampaignState(tuple(source_by_task), campaign_id)
        counter = None
        history_policy = None
    root = _new_or_resume(output, state, split.manifest_hash, campaign_mode=campaign_mode)
    if (root / "campaign-progress.json").is_file():
        stored = _json(root / "campaign-progress.json")
        for raw in stored.get("attempts", []):
            if campaign_mode == "action-conditioned":
                assert isinstance(state, HweActionConditionedCampaignState)
                state.record(HweActionConditionedCampaignAttempt(**raw))
            else:
                assert isinstance(state, HweCampaignState)
                state.record(HweCampaignAttempt(**raw))
    startup_restarts = _load_startup_restarts(root)

    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "codex-cli-hwe-agent" not in registries.agents.names():
        from verigym_codex_cli import CodexCliHweAgentAdapter

        registries.agents.register(CodexCliHweAgentAdapter())
    service = VeriGym(registries)
    runs = root / "runs"
    runs.mkdir(exist_ok=True)

    while (task_id := state.next_task()) is not None:
        lock = locks[task_id]
        source_root = (qualification / source_by_task[task_id]).resolve(strict=True)
        if not source_root.is_relative_to(qualification):
            raise ConfigurationError("CVA6 HWE source escapes qualification root")
        source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
        suite, task, _assets = service.load_task(task_id, source)
        entry = next(item for item in split.training if item.task_id == task_id)
        snapshot = suite.source_snapshot()
        if (
            snapshot is None
            or content_hash(task) != entry.task_hash
            or task.source.content_hash != entry.source_hash
            or lock.task_hash != entry.task_hash
            or lock.source_hash != entry.source_hash
        ):
            raise ConfigurationError("CVA6 HWE task/source/image-lock identity changed")
        attempt_id = f"{campaign_id}-{task_id.rsplit('-', 1)[-1]}"
        config = RunConfig(
            task_id=task_id,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=entry.task_hash,
            expected_source_hash=entry.source_hash,
            mode=InteractionMode.AGENT,
            agent="codex-cli-hwe-agent",
            agent_options={
                "model_id": "gpt-5.4",
                "reasoning_effort": "xhigh",
                "max_process_time_s": 3600,
                "max_output_bytes": 32 * 1024 * 1024,
                "allow_proxy_environment": True,
                "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                "agent_image_lock_hash": lock.lock_hash,
                "expected_cli_version": "codex-cli 0.147.0",
                "expected_cli_executable_sha256": lock.host_codex_sha256,
                "expected_execution_backend": "docker_outer_runtime_delegated",
            },
            runtime="docker",
            docker_config=_docker_config(lock, runtime_user=state.runtime_user),
            seed=484,
            sample_index=0,
            output=runs,
            run_id=attempt_id,
            experiment_id=campaign_id,
            plan_item_id=attempt_id,
            system_id="codex-hwe-native-shell-v2",
            base_seed=484,
        )
        launch_count = 1 + sum(record.get("task_id") == task_id for record in startup_restarts)
        if launch_count > HWE_ZERO_CALL_STARTUP_RESTARTS + 1:
            raise ConfigurationError("HWE startup restart ledger exceeds its frozen limit")
        try:
            while True:
                launch_id = f"{attempt_id}-launch-{launch_count}"
                launch_config = config.model_copy(
                    update={"run_id": launch_id, "plan_item_id": launch_id}
                )
                result = service.run(launch_config)
                if not _zero_call_startup_restart_eligible(result):
                    break
                if launch_count > HWE_ZERO_CALL_STARTUP_RESTARTS:
                    break
                restart = _startup_restart_record(
                    task_id=task_id,
                    launch_id=launch_id,
                    launch_count=launch_count,
                    scorecard=result.scorecard,
                )
                startup_restarts.append(restart)
                _write_startup_restarts(root, startup_restarts)
                launch_count += 1
            model_action_rejection = _model_action_rejection(result.scorecard)
            infrastructure_valid = model_action_rejection is not None or not (
                _infrastructure_invalid(result.scorecard)
            )
            transcript_path = (
                Path(result.run_dir) / "artifacts/codex_cli/hwe_teacher_transcript.json"
            )
            transcript: dict[str, Any] | None = None
            if transcript_path.is_file() and not transcript_path.is_symlink():
                transcript = validate_hwe_teacher_transcript(_json(transcript_path))
            rejection_path = (
                Path(result.run_dir) / "artifacts/codex_cli/hwe_materialization_rejection.json"
            )
            materialization_rejection = _materialization_rejection(rejection_path, task_id=task_id)
            if transcript is not None and materialization_rejection is not None:
                raise ConfigurationError(
                    "HWE run cannot contain both a transcript and materialization rejection"
                )
            failure = result.scorecard.failure
            run_hash = content_hash(
                {"run_id": launch_id, "scorecard": result.scorecard.model_dump(mode="json")}
            )
            if campaign_mode == "action-conditioned":
                assert isinstance(state, HweActionConditionedCampaignState)
                assert counter is not None
                assert history_policy is not None
                action_examples: list[dict[str, Any]] = []
                action_status, reason = _action_conditioned_status(
                    result.scorecard.resolved,
                    infrastructure_valid,
                    transcript,
                    materialization_rejection=materialization_rejection,
                    model_action_rejection=model_action_rejection,
                )
                if not infrastructure_valid and failure is not None:
                    reason = failure.protocol_error_subcategory or failure.category
                if action_status == "action_conditioned_eligible_success":
                    assert transcript is not None
                    reproducibility = result.scorecard.reproducibility
                    binding = {
                        "sample_id": content_hash(
                            {"campaign_id": campaign_id, "task_id": task_id, "run_hash": run_hash}
                        ),
                        "task_hash": entry.task_hash,
                        "source_hash": entry.source_hash,
                        "candidate_hash": reproducibility.candidate_hash,
                        "verifier_hash": reproducibility.verifier_hash,
                        "run_hash": run_hash,
                    }
                    try:
                        action_examples = materialize_hwe_action_conditioned_examples(
                            transcript,
                            binding=binding,
                            counter=counter,
                            policy=history_policy,
                        )
                    except ValueError as exc:
                        action_status = "action_conditioned_ineligible"
                        reason = _action_materialization_rejection_reason(exc)
                action_records_hash: str | None = None
                max_action_tokens: int | None = None
                if action_examples:
                    max_action_tokens = max(int(item["token_count"]) for item in action_examples)
                    action_records_hash = content_hash(
                        [str(item["record_hash"]) for item in action_examples]
                    )
                    _write_action_trajectory_records(
                        root,
                        task_id=task_id,
                        run_hash=run_hash,
                        transcript=transcript,
                        examples=action_examples,
                        records_hash=action_records_hash,
                    )
                attempt: HweCampaignAttempt | HweActionConditionedCampaignAttempt = (
                    HweActionConditionedCampaignAttempt(
                        task_id=task_id,
                        status=action_status,
                        infrastructure_valid=infrastructure_valid,
                        verifier_pass=result.scorecard.resolved,
                        normalized_success=transcript is not None,
                        source_sft_bucket=(
                            transcript.get("sft_bucket") if transcript is not None else None
                        ),
                        action_conditioned_eligible=(
                            action_status == "action_conditioned_eligible_success"
                        ),
                        action_record_count=len(action_examples),
                        max_action_record_tokens=max_action_tokens,
                        source_transcript_hash=(
                            str(transcript["transcript_hash"]) if transcript is not None else None
                        ),
                        action_records_hash=action_records_hash,
                        run_hash=run_hash,
                        rejection_reason=reason,
                        external_model_call_count=(
                            result.scorecard.efficiency.external_model_call_count
                        ),
                        external_input_tokens=result.scorecard.efficiency.external_input_tokens,
                        external_output_tokens=result.scorecard.efficiency.external_output_tokens,
                        external_total_tokens=result.scorecard.efficiency.external_total_tokens,
                        protocol_error_subcategory=(
                            failure.protocol_error_subcategory if failure is not None else None
                        ),
                        launch_attempt_count=launch_count,
                    )
                )
            else:
                assert isinstance(state, HweCampaignState)
                status, reason = _status(
                    result.scorecard.resolved,
                    infrastructure_valid,
                    transcript,
                    materialization_rejection=materialization_rejection,
                    model_action_rejection=model_action_rejection,
                )
                if not infrastructure_valid and failure is not None:
                    reason = failure.protocol_error_subcategory or failure.category
                attempt = HweCampaignAttempt(
                    task_id=task_id,
                    status=status,
                    infrastructure_valid=infrastructure_valid,
                    verifier_pass=result.scorecard.resolved,
                    normalized_success=transcript is not None,
                    sft_bucket=transcript.get("sft_bucket") if transcript is not None else None,
                    run_hash=run_hash,
                    rejection_reason=reason,
                    external_model_call_count=(
                        result.scorecard.efficiency.external_model_call_count
                    ),
                    external_input_tokens=result.scorecard.efficiency.external_input_tokens,
                    external_output_tokens=result.scorecard.efficiency.external_output_tokens,
                    external_total_tokens=result.scorecard.efficiency.external_total_tokens,
                    protocol_error_subcategory=(
                        failure.protocol_error_subcategory if failure is not None else None
                    ),
                    launch_attempt_count=launch_count,
                )
            if (
                campaign_mode == "primary"
                and isinstance(attempt, HweCampaignAttempt)
                and attempt.status == "primary_eligible"
                and transcript is not None
            ):
                reproducibility = result.scorecard.reproducibility
                binding = {
                    "sample_id": content_hash(
                        {"campaign_id": campaign_id, "task_id": task_id, "run_hash": run_hash}
                    ),
                    "task_hash": entry.task_hash,
                    "source_hash": entry.source_hash,
                    "candidate_hash": reproducibility.candidate_hash,
                    "verifier_hash": reproducibility.verifier_hash,
                    "run_hash": run_hash,
                }
                example = materialize_hwe_sft_example(transcript, binding=binding)
                example_root = root / "eligible-examples"
                example_root.mkdir(exist_ok=True)
                atomic_dump_json(example_root / f"{task_id.rsplit('-', 1)[-1]}.json", example)
        except Exception as exc:
            if campaign_mode == "action-conditioned":
                assert isinstance(state, HweActionConditionedCampaignState)
                action_failed_attempt = HweActionConditionedCampaignAttempt(
                    task_id=task_id,
                    status="infrastructure_invalid",
                    infrastructure_valid=False,
                    verifier_pass=False,
                    normalized_success=False,
                    source_sft_bucket=None,
                    action_conditioned_eligible=False,
                    action_record_count=0,
                    max_action_record_tokens=None,
                    source_transcript_hash=None,
                    action_records_hash=None,
                    run_hash=content_hash(
                        {"attempt_id": attempt_id, "error_type": type(exc).__name__}
                    ),
                    rejection_reason=type(exc).__name__,
                    launch_attempt_count=launch_count,
                )
                state.record(action_failed_attempt)
            else:
                assert isinstance(state, HweCampaignState)
                primary_failed_attempt = HweCampaignAttempt(
                    task_id=task_id,
                    status="infrastructure_invalid",
                    infrastructure_valid=False,
                    verifier_pass=False,
                    normalized_success=False,
                    sft_bucket=None,
                    run_hash=content_hash(
                        {"attempt_id": attempt_id, "error_type": type(exc).__name__}
                    ),
                    rejection_reason=type(exc).__name__,
                    launch_attempt_count=launch_count,
                )
                state.record(primary_failed_attempt)
            atomic_dump_json(
                root / "campaign-progress.json", _progress_payload(state, split.manifest_hash)
            )
            atomic_dump_json(root / "campaign-report.json", state.report())
            raise ConfigurationError(
                f"CVA6 HWE campaign stopped on infrastructure-invalid {task_id}"
            ) from exc
        if campaign_mode == "action-conditioned":
            assert isinstance(state, HweActionConditionedCampaignState)
            assert isinstance(attempt, HweActionConditionedCampaignAttempt)
            state.record(attempt)
        else:
            assert isinstance(state, HweCampaignState)
            assert isinstance(attempt, HweCampaignAttempt)
            state.record(attempt)
        atomic_dump_json(
            root / "campaign-progress.json", _progress_payload(state, split.manifest_hash)
        )

    report = state.report()
    atomic_dump_json(root / "campaign-report.json", report)
    if state.status == "completed":
        if campaign_mode == "action-conditioned":
            assert isinstance(state, HweActionConditionedCampaignState)
            _write_action_conditioned_handoff(root, state, report)
        else:
            assert isinstance(state, HweCampaignState)
            _write_completed_handoff(root, state, report)
    return report


def _docker_config(lock: HweAgentImageLock, *, runtime_user: str) -> DockerRuntimeConfig:
    return DockerRuntimeConfig(
        # This source-free image is only the outer workspace transport. The HWE verifier
        # plugin remains bound to lock.verifier_base_image_id, while all model commands run
        # in the separately identified task-keyed agent image below.
        image=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        expected_image_id=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        pull_policy="never",
        network_mode="none",
        run_as_user=runtime_user,
        memory_bytes=16 * 1024**3,
        cpus=4,
        pids_limit=4096,
        max_command_time_s=900,
        external_agent=DockerExternalAgentRuntimeConfig(
            image=lock.derived_agent_image_id,
            expected_image_id=lock.derived_agent_image_id,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.147.0",
            expected_executable_sha256=lock.agent_codex_sha256,
            process_argv=[
                "/usr/local/bin/codex",
                "exec-server",
                "--listen",
                "stdio://",
            ],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels={
                "org.verigym.collection.profile": HWE_COLLECTION_PROFILE_V2_ID,
                "org.verigym.tool.contract": HWE_TOOL_CONTRACT_V2_ID,
                "org.verigym.codex.version": "0.147.0",
                "org.verigym.codex.binary.sha256": lock.agent_codex_sha256,
                "org.verigym.codex.rg.sha256": lock.agent_rg_sha256,
                "org.verigym.hwe.task_id": lock.task_id,
                "org.verigym.cva6.verifier_base_image_id": lock.verifier_base_image_id,
                "org.verigym.provider_credentials": "absent",
                "org.verigym.hidden_assets": "absent",
                "org.verigym.reference_patch": "absent",
                "org.verigym.verifier_payload": "absent",
            },
            run_as_user=runtime_user,
            memory_bytes=16 * 1024**3,
            cpus=4,
            pids_limit=4096,
            max_process_time_s=3600,
            max_output_bytes=32 * 1024 * 1024,
            logical_workspace_root="/workspace/repository",
        ),
    )


def _zero_call_startup_restart_eligible(result: Any) -> bool:
    scorecard = result.scorecard
    if (
        scorecard.efficiency.external_model_call_count != 0
        or not _infrastructure_invalid(scorecard)
        or scorecard.patch.changed_files
    ):
        return False
    failure = scorecard.failure
    reason = " ".join(
        str(value or "")
        for value in (
            getattr(failure, "category", None),
            getattr(failure, "protocol_error_subcategory", None),
            getattr(failure, "message", None),
        )
    ).casefold()
    if any(marker in reason for marker in ("security", "credential", "identity", "hash")):
        return False
    runtime_path = Path(result.run_dir) / "artifacts/codex_cli/runtime_process.json"
    if not runtime_path.is_file() or runtime_path.is_symlink():
        return False
    runtime = _json(runtime_path)
    return runtime.get("cleanup_complete") is True


def _startup_restart_record(
    *, task_id: str, launch_id: str, launch_count: int, scorecard: Any
) -> dict[str, Any]:
    failure = scorecard.failure
    base = {
        "task_id": task_id,
        "launch_id": launch_id,
        "launch_count": launch_count,
        "external_model_call_count": 0,
        "workspace_changed": False,
        "cleanup_complete": True,
        "failure_category": getattr(failure, "category", None),
        "protocol_error_subcategory": getattr(failure, "protocol_error_subcategory", None),
        "scorecard_hash": content_hash(scorecard.model_dump(mode="json")),
        "sample_consumed": False,
    }
    return {**base, "record_hash": content_hash(base)}


def _load_startup_restarts(root: Path) -> list[dict[str, Any]]:
    path = root / "startup-restarts.json"
    if not path.exists():
        return []
    value = _json(path)
    identity = dict(value)
    ledger_hash = identity.pop("ledger_hash", None)
    records = value.get("records")
    if (
        value.get("format_id") != "verigym_hwe_zero_call_startup_restarts_v1"
        or value.get("collection_profile_id") != HWE_COLLECTION_PROFILE_V2_ID
        or value.get("restart_limit") != HWE_ZERO_CALL_STARTUP_RESTARTS
        or not isinstance(ledger_hash, str)
        or content_hash(identity) != ledger_hash
        or not isinstance(records, list)
        or len(records) > 22
    ):
        raise ConfigurationError("HWE startup restart ledger is malformed")
    for record in records:
        if not isinstance(record, dict):
            raise ConfigurationError("HWE startup restart record is malformed")
        identity = dict(record)
        expected = identity.pop("record_hash", None)
        if not isinstance(expected, str) or content_hash(identity) != expected:
            raise ConfigurationError("HWE startup restart record identity changed")
        if (
            record.get("external_model_call_count") != 0
            or record.get("sample_consumed") is not False
        ):
            raise ConfigurationError("HWE startup restart consumed a model sample")
    return [dict(record) for record in records]


def _write_startup_restarts(root: Path, records: list[dict[str, Any]]) -> None:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_zero_call_startup_restarts_v1",
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "restart_limit": HWE_ZERO_CALL_STARTUP_RESTARTS,
        "records": records,
    }
    atomic_dump_json(root / "startup-restarts.json", {**base, "ledger_hash": content_hash(base)})


def _status(
    verifier_pass: bool,
    infrastructure_valid: bool,
    transcript: dict[str, Any] | None,
    *,
    materialization_rejection: str | None = None,
    model_action_rejection: str | None = None,
) -> tuple[AttemptStatus, str | None]:
    if model_action_rejection is not None:
        return "agent_policy_rejected", model_action_rejection
    if not infrastructure_valid:
        return "infrastructure_invalid", "scorecard_infrastructure_invalid"
    if not verifier_pass:
        return "verifier_rejected", "benchmark_verifier_rejected"
    if transcript is None:
        return (
            "normalized_failure",
            materialization_rejection or "successful_candidate_lacks_hwe_transcript",
        )
    bucket = transcript["sft_bucket"]
    if bucket == "primary":
        return "primary_eligible", None
    if bucket == "long_context_candidate":
        return "long_context_candidate", "sft_bucket_long_context_candidate"
    if bucket == "audit":
        return "audit_only", "sft_bucket_audit"
    raise ConfigurationError("HWE transcript has an unknown SFT bucket")


def _action_conditioned_status(
    verifier_pass: bool,
    infrastructure_valid: bool,
    transcript: dict[str, Any] | None,
    *,
    materialization_rejection: str | None = None,
    model_action_rejection: str | None = None,
) -> tuple[ActionConditionedAttemptStatus, str | None]:
    if model_action_rejection is not None:
        return "agent_policy_rejected", model_action_rejection
    if not infrastructure_valid:
        return "infrastructure_invalid", "scorecard_infrastructure_invalid"
    if not verifier_pass:
        return "verifier_rejected", "benchmark_verifier_rejected"
    if transcript is None:
        return (
            "normalized_failure",
            materialization_rejection or "successful_candidate_lacks_hwe_transcript",
        )
    return "action_conditioned_eligible_success", None


def _action_materialization_rejection_reason(error: ValueError) -> str:
    message = str(error)
    if "exceeds 32K" in message:
        return "action_conditioned_record_exceeds_32k"
    return "action_conditioned_materialization_validation_failed"


def _materialization_rejection(path: Path, *, task_id: str) -> str | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("HWE materialization rejection artifact is unsafe")
    value = _json(path)
    identity = dict(value)
    rejection_hash = identity.pop("rejection_hash", None)
    reasons = {
        "filesystem_mutation_without_patch_update",
        "patch_update_path_mismatch",
        "patch_update_without_observed_mutation",
    }
    if (
        value.get("format_id") != "verigym_hwe_materialization_rejection_v1"
        or value.get("collection_profile_id") != HWE_COLLECTION_PROFILE_V2_ID
        or value.get("task_id") != task_id
        or value.get("ordinary_verifier_resolved") is not True
        or value.get("terminal_event_seen") is not True
        or value.get("reason") not in reasons
        or not isinstance(value.get("protocol_record_count"), int)
        or value.get("protocol_record_count", 0) < 1
        or not isinstance(value.get("raw_layer_hash"), str)
        or len(value["raw_layer_hash"]) != 64
        or not isinstance(rejection_hash, str)
        or content_hash(identity) != rejection_hash
    ):
        raise ConfigurationError("HWE materialization rejection artifact is malformed")
    return f"hwe_materialization_{value['reason']}"


def _infrastructure_invalid(scorecard: Any) -> bool:
    failure = scorecard.failure
    return bool(
        scorecard.correctness.infrastructure_error
        or (failure is not None and failure.infrastructure)
        or (scorecard.status == "error" and (failure is None or failure.kind == "runtime"))
    )


def _model_action_rejection(scorecard: Any) -> str | None:
    """Separate sampled invalid model actions from collector/runtime infrastructure faults."""

    failure = scorecard.failure
    subcategory = getattr(failure, "protocol_error_subcategory", None)
    if (
        scorecard.efficiency.external_model_call_count < 1
        or failure is None
        or failure.kind != "model"
        or failure.category != "protocol_error"
        or not isinstance(subcategory, str)
    ):
        return None
    prefixes = (
        "hwe_protocol_shell_command_policy_violation:",
        "hwe_protocol_interactive_process_control_forbidden:",
        "hwe_protocol_process_signal_invalid",
        "hwe_protocol_duplicate_active_process_interrupt",
        "hwe_protocol_concurrent_process_start_forbidden",
    )
    return subcategory if subcategory.startswith(prefixes) else None


def _image_locks(root: Path, task_ids: set[str]) -> dict[str, HweAgentImageLock]:
    directory = root.resolve(strict=True)
    locks: dict[str, HweAgentImageLock] = {}
    for path in sorted(directory.glob("*.json")):
        lock = HweAgentImageLock.model_validate(_json(path))
        if (
            lock.format_id != "verigym_hwe_agent_image_lock_v2"
            or lock.collection_profile_id != HWE_COLLECTION_PROFILE_V2_ID
            or lock.tool_contract_id != HWE_TOOL_CONTRACT_V2_ID
        ):
            raise ConfigurationError("HWE campaign requires v2 task-keyed image locks")
        if lock.task_id in locks:
            raise ConfigurationError("duplicate HWE task image lock")
        locks[lock.task_id] = lock
    if set(locks) != task_ids:
        raise ConfigurationError("HWE image locks do not exactly cover the frozen task pool")
    if len({lock.derived_agent_image_id for lock in locks.values()}) != len(locks):
        raise ConfigurationError("HWE tasks must use independently derived agent images")
    return locks


def _new_or_resume(
    output: Path,
    state: CampaignState,
    split_hash: str,
    *,
    campaign_mode: CampaignMode = "primary",
) -> Path:
    path = output.expanduser()
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise ConfigurationError("HWE output is unsafe")
        root = path.resolve(strict=True)
        progress = _json(root / "campaign-progress.json")
        if (
            progress.get("campaign_id") != state.campaign_id
            or progress.get("frozen_task_pool") != list(state.frozen_task_pool)
            or progress.get("task_split_hash") != split_hash
            or progress.get("collection_profile_id") != HWE_COLLECTION_PROFILE_V2_ID
            or progress.get("prompt_contract_id") != HWE_CODEX_PROMPT_CONTRACT_ID
            or progress.get("prompt_contract_version") != HWE_CODEX_PROMPT_CONTRACT_VERSION
            or progress.get("base_instruction_policy") != HWE_CODEX_BASE_INSTRUCTION_POLICY
            or progress.get("exec_lifecycle_policy_id") != HWE_EXEC_LIFECYCLE_POLICY_ID
            or progress.get("model_id") != "gpt-5.4"
            or progress.get("reasoning_effort") != "xhigh"
            or progress.get("seed") != 484
            or progress.get("runtime_user") != state.runtime_user
        ):
            raise ConfigurationError("HWE resume identity differs from the frozen campaign")
        if campaign_mode == "action-conditioned":
            assert isinstance(state, HweActionConditionedCampaignState)
            policy = HweHistoryMaskingPolicy(
                recent_observations=state.history_recent_observations,
                max_pinned_observations=state.history_max_pinned_observations,
            )
            if (
                progress.get("format_id") != HWE_ACTION_CONDITIONED_CAMPAIGN_FORMAT
                or progress.get("history_policy_id") != policy.policy_id
                or progress.get("history_policy_hash") != policy.policy_hash
                or progress.get("history_recent_observations") != state.history_recent_observations
                or progress.get("history_max_pinned_observations")
                != state.history_max_pinned_observations
                or progress.get("training_eligibility") != "experimental_action_conditioned"
                or progress.get("existing_primary_reclassified") is not False
                or progress.get("agent_image_lock_hashes")
                != dict(state.frozen_agent_image_lock_hashes)
            ):
                raise ConfigurationError(
                    "HWE action-conditioned resume identity differs from the frozen campaign"
                )
        elif progress.get("format_id") != "verigym_hwe_cva6_codex_campaign_report_v2":
            raise ConfigurationError("HWE primary resume report format changed")
        return root
    path.mkdir(parents=True)
    root = path.resolve(strict=True)
    atomic_dump_json(
        root / "campaign-progress.json",
        _progress_payload(state, split_hash),
    )
    return root


def _progress_payload(state: CampaignState, split_hash: str) -> dict[str, Any]:
    return {**state.report(), "task_split_hash": split_hash}


def _write_action_trajectory_records(
    root: Path,
    *,
    task_id: str,
    run_hash: str,
    transcript: dict[str, Any] | None,
    examples: list[dict[str, Any]],
    records_hash: str,
) -> None:
    if transcript is None or not examples:
        raise ConfigurationError("action-conditioned records require a source transcript")
    directory = root / "action-conditioned-examples"
    directory.mkdir(exist_ok=True)
    suffix = task_id.rsplit("-", 1)[-1]
    records_path = directory / f"{suffix}.jsonl"
    records_text = "".join(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n" for value in examples
    )
    if records_path.exists():
        if (
            records_path.is_symlink()
            or not records_path.is_file()
            or records_path.read_text(encoding="utf-8") != records_text
        ):
            raise ConfigurationError("existing action-conditioned records changed")
    else:
        _atomic_dump_jsonl(records_path, examples)
    records_bytes = records_path.read_bytes()
    manifest_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_action_conditioned_trajectory_records_v1",
        "campaign_task_id": task_id,
        "source_transcript_hash": transcript["transcript_hash"],
        "source_sft_bucket": transcript["sft_bucket"],
        "run_hash": run_hash,
        "history_policy_hash": examples[0]["history_policy_hash"],
        "record_count": len(examples),
        "record_hashes": [value["record_hash"] for value in examples],
        "records_hash": records_hash,
        "max_action_record_tokens": max(int(value["token_count"]) for value in examples),
        "records_file": records_path.name,
        "records_file_bytes": len(records_bytes),
        "records_file_sha256": hashlib.sha256(records_bytes).hexdigest(),
        "primary_eligible": False,
        "training_eligibility": "experimental_action_conditioned",
        "counterfactual_next_action_validation": "not_run",
        "raw_observations_exported": False,
        "hpc_jobs_submitted": False,
    }
    manifest = {**manifest_base, "manifest_hash": content_hash(manifest_base)}
    manifest_path = directory / f"{suffix}.manifest.json"
    if manifest_path.exists() and _json(manifest_path) != manifest:
        raise ConfigurationError("existing action-conditioned trajectory manifest changed")
    atomic_dump_json(manifest_path, manifest)


def _load_action_trajectory_records(root: Path, task_id: str) -> list[dict[str, Any]]:
    suffix = task_id.rsplit("-", 1)[-1]
    directory = root / "action-conditioned-examples"
    manifest = _json(directory / f"{suffix}.manifest.json")
    path = directory / f"{suffix}.jsonl"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ConfigurationError("action-conditioned trajectory records are unsafe")
    raw = path.read_bytes()
    if (
        manifest.get("campaign_task_id") != task_id
        or manifest.get("records_file") != path.name
        or manifest.get("records_file_bytes") != len(raw)
        or manifest.get("records_file_sha256") != hashlib.sha256(raw).hexdigest()
    ):
        raise ConfigurationError("action-conditioned trajectory file identity changed")
    examples: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ConfigurationError("action-conditioned JSONL record is not an object")
        examples.append(validate_hwe_action_conditioned_example(value))
    record_hashes = [value["record_hash"] for value in examples]
    identity = dict(manifest)
    manifest_hash = identity.pop("manifest_hash", None)
    if (
        not examples
        or manifest.get("record_count") != len(examples)
        or manifest.get("record_hashes") != record_hashes
        or manifest.get("records_hash") != content_hash(record_hashes)
        or not isinstance(manifest_hash, str)
        or content_hash(identity) != manifest_hash
    ):
        raise ConfigurationError("action-conditioned trajectory manifest is inconsistent")
    return examples


def _write_action_conditioned_handoff(
    root: Path,
    state: HweActionConditionedCampaignState,
    report: dict[str, Any],
) -> None:
    examples: list[dict[str, Any]] = []
    bindings_records: list[dict[str, Any]] = []
    for attempt in state.attempts:
        if attempt.status != "action_conditioned_eligible_success":
            continue
        trajectory_examples = _load_action_trajectory_records(root, attempt.task_id)
        examples.extend(trajectory_examples)
        bindings_records.append(
            {
                "task_id": attempt.task_id,
                "run_hash": attempt.run_hash,
                "source_transcript_hash": attempt.source_transcript_hash,
                "action_records_hash": attempt.action_records_hash,
                "action_record_count": attempt.action_record_count,
            }
        )
    bindings_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_cva6_action_conditioned_bindings_v1",
        "trajectory_count": len(bindings_records),
        "record_count": len(examples),
        "bindings": bindings_records,
        "primary_eligible": False,
        "training_eligibility": "experimental_action_conditioned",
        "hpc_jobs_submitted": False,
    }
    bindings_hash = content_hash(bindings_base)
    bindings = {**bindings_base, "bindings_hash": bindings_hash}
    dataset_manifest = build_hwe_action_conditioned_dataset_manifest(
        examples,
        required_trajectory_count=8,
    )
    handoff = build_action_conditioned_handoff(
        campaign_report=report,
        dataset_manifest=dataset_manifest,
        bindings_hash=bindings_hash,
    )
    outputs = (
        root / "hwe-action-conditioned-sft.jsonl",
        root / "action-conditioned-bindings.json",
        root / "action-conditioned-dataset-manifest.json",
        root / "action-conditioned-handoff.json",
    )
    dataset_text = "".join(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n" for value in examples
    )
    if any(path.exists() for path in outputs):
        if (
            all(path.is_file() and not path.is_symlink() for path in outputs)
            and outputs[0].read_text(encoding="utf-8") == dataset_text
            and _json(outputs[1]) == bindings
            and _json(outputs[2]) == dataset_manifest
            and _json(outputs[3]) == handoff
        ):
            return
        raise ConfigurationError("existing action-conditioned handoff differs from campaign")
    _atomic_dump_jsonl(outputs[0], examples)
    atomic_dump_json(outputs[1], bindings)
    atomic_dump_json(outputs[2], dataset_manifest)
    atomic_dump_json(outputs[3], handoff)


def _write_completed_handoff(root: Path, state: HweCampaignState, report: dict[str, Any]) -> None:
    examples: list[dict[str, Any]] = []
    binding_records: list[dict[str, str]] = []
    for attempt in state.attempts:
        if attempt.status != "primary_eligible":
            continue
        example = _json(root / "eligible-examples" / f"{attempt.task_id.rsplit('-', 1)[-1]}.json")
        examples.append(example)
        binding_records.append(
            {
                "task_id": attempt.task_id,
                "run_hash": attempt.run_hash,
                "example_hash": str(example["example_hash"]),
                "transcript_hash": str(example["transcript_hash"]),
            }
        )
    bindings_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_cva6_primary_bindings_v2",
        "record_count": len(binding_records),
        "bindings": binding_records,
        "hpc_jobs_submitted": False,
    }
    bindings_hash = content_hash(bindings_base)
    bindings = {**bindings_base, "bindings_hash": bindings_hash}
    dataset_manifest = build_hwe_dataset_manifest(examples, profile_id=HWE_COLLECTION_PROFILE_V2_ID)
    handoff = build_hpc_handoff(
        campaign_report=report,
        dataset_manifest=dataset_manifest,
        bindings_hash=bindings_hash,
    )
    dataset_text = "".join(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n" for value in examples
    )
    outputs = (
        root / "hwe-primary-sft.jsonl",
        root / "successful-bindings.json",
        root / "dataset-manifest.json",
        root / "hpc-handoff.json",
    )
    if any(path.exists() for path in outputs):
        if (
            all(path.is_file() and not path.is_symlink() for path in outputs)
            and outputs[0].read_text(encoding="utf-8") == dataset_text
            and _json(outputs[1]) == bindings
            and _json(outputs[2]) == dataset_manifest
            and _json(outputs[3]) == handoff
        ):
            return
        raise ConfigurationError("existing HWE handoff differs from the completed campaign")
    _atomic_dump_jsonl(root / "hwe-primary-sft.jsonl", examples)
    atomic_dump_json(root / "successful-bindings.json", bindings)
    atomic_dump_json(root / "dataset-manifest.json", dataset_manifest)
    atomic_dump_json(root / "hpc-handoff.json", handoff)


def _atomic_dump_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or path.exists():
        raise ConfigurationError("HWE dataset output already exists")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for value in values:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ConfigurationError(f"unsafe HWE JSON artifact: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError(f"HWE JSON artifact is not an object: {path.name}")
    return value


def main() -> int:
    arguments = _parser().parse_args()
    report = collect(
        qualification_root=arguments.qualification_root,
        image_lock_dir=arguments.image_lock_dir,
        output=arguments.output,
        campaign_id=arguments.campaign_id,
        campaign_mode=arguments.campaign_mode,
        history_recent_observations=arguments.history_recent_observations,
        history_max_pinned_observations=arguments.history_max_pinned_observations,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
