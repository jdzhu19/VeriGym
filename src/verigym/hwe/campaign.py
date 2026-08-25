"""Frozen CVA6 HWE pilot gate, one-sample rollout, and HPC handoff policy."""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from verigym.core.hashing import content_hash
from verigym.hwe.history_masking import (
    HWE_ACTION_CONDITIONED_DATASET_FORMAT,
    HWE_HISTORY_MASKING_POLICY_ID,
    HWE_SELECTED_HISTORY_WINDOW,
    HweHistoryMaskingPolicy,
)
from verigym.hwe.observation import HWE_TOKENIZER_HASH
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_OBSERVATION_POLICY_V2_ID,
    HWE_TOKENIZER_ID,
    HWE_TOOL_CONTRACT_V2_ID,
)

HWE_PILOT_TASKS = (
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
)
HWE_TARGET_PRIMARY = 8
HWE_TARGET_ACTION_CONDITIONED_TRAJECTORIES = 8
HWE_ACTION_CONDITIONED_CAMPAIGN_FORMAT = (
    "verigym_hwe_cva6_codex_action_conditioned_campaign_report_v3"
)
HWE_EXEC_LIFECYCLE_POLICY_ID = "hwe_exec_process_lifecycle_v2"
HWE_LEGACY_CODEX_PROMPT_CONTRACT_ID = "codex_cli_hwe_native_shell_context_v2"
HWE_LEGACY_CODEX_PROMPT_CONTRACT_VERSION = "2.0.0"
HWE_LEGACY_CODEX_BASE_INSTRUCTION_POLICY = "hwe_native_shell_base_instructions_v2"
HWE_CODEX_PROMPT_CONTRACT_ID = "codex_cli_hwe_native_shell_context_v9"
HWE_CODEX_PROMPT_CONTRACT_VERSION = "9.0.0"
HWE_CODEX_BASE_INSTRUCTION_POLICY = "hwe_native_shell_base_instructions_v9"
HWE_ZERO_CALL_STARTUP_RESTARTS = 2
HWE_WORKSPACE_RUNTIME_IMAGE_ID = (
    "sha256:5b95472e7fbfa80eb0cf173099254ef5285fcd78f7c3c78b42678ae9181dd96e"
)

AttemptStatus = Literal[
    "primary_eligible",
    "long_context_candidate",
    "audit_only",
    "verifier_rejected",
    "normalized_failure",
    "agent_policy_rejected",
    "infrastructure_invalid",
]


@dataclass(frozen=True)
class HweCampaignAttempt:
    task_id: str
    status: AttemptStatus
    infrastructure_valid: bool
    verifier_pass: bool
    normalized_success: bool
    sft_bucket: Literal["primary", "long_context_candidate", "audit"] | None
    run_hash: str
    rejection_reason: str | None = None
    external_model_call_count: int | None = None
    external_input_tokens: int | None = None
    external_output_tokens: int | None = None
    external_total_tokens: int | None = None
    protocol_error_subcategory: str | None = None
    launch_attempt_count: int = 1


@dataclass
class HweCampaignState:
    """Enforce pilot-first, one attempt/task, no retry/model substitution, and stop rules."""

    frozen_task_pool: tuple[str, ...]
    campaign_id: str
    attempts: list[HweCampaignAttempt] = field(default_factory=list)
    status: str = "pilot_running"
    stop_reason: str | None = None
    runtime_user: str = field(default_factory=lambda: f"{os.getuid()}:{os.getgid()}")

    def __post_init__(self) -> None:
        if len(self.frozen_task_pool) != 11 or len(set(self.frozen_task_pool)) != 11:
            raise ValueError("HWE campaign requires a frozen 11-task pool")
        if not set(HWE_PILOT_TASKS).issubset(self.frozen_task_pool):
            raise ValueError("HWE 11-task pool omits a required pilot task")
        if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", self.runtime_user):
            raise ValueError("HWE campaign requires an explicit non-root numeric runtime UID:GID")

    def next_task(self) -> str | None:
        if self.status.startswith("stopped") or self.status == "completed":
            return None
        attempted = {attempt.task_id for attempt in self.attempts}
        if self.status == "pilot_running":
            return next((task for task in HWE_PILOT_TASKS if task not in attempted), None)
        if self.primary_count >= HWE_TARGET_PRIMARY:
            self.status = "completed"
            return None
        task = next((task for task in self.frozen_task_pool if task not in attempted), None)
        if task is None:
            self.status = "stopped_pool_exhausted"
            self.stop_reason = "fewer_than_eight_primary_eligible"
        return task

    @property
    def primary_count(self) -> int:
        return sum(attempt.status == "primary_eligible" for attempt in self.attempts)

    def record(self, attempt: HweCampaignAttempt) -> None:
        expected = self.next_task()
        if expected is None or attempt.task_id != expected:
            raise ValueError("HWE attempt is out of frozen order or repeats a task")
        if attempt.run_hash == "" or len(attempt.run_hash) != 64:
            raise ValueError("HWE attempt lacks a frozen run identity")
        if attempt.launch_attempt_count < 1 or attempt.launch_attempt_count > (
            HWE_ZERO_CALL_STARTUP_RESTARTS + 1
        ):
            raise ValueError("HWE attempt launch count is outside the frozen startup policy")
        if attempt.status == "infrastructure_invalid" or not attempt.infrastructure_valid:
            self.attempts.append(attempt)
            self.status = "stopped_infrastructure_invalid"
            self.stop_reason = attempt.rejection_reason or "infrastructure_invalid"
            return
        self.attempts.append(attempt)
        pilot_attempts = [item for item in self.attempts if item.task_id in HWE_PILOT_TASKS]
        if self.status == "pilot_running" and len(pilot_attempts) == 3:
            verifier_passes = sum(item.verifier_pass for item in pilot_attempts)
            primary = sum(item.status == "primary_eligible" for item in pilot_attempts)
            if verifier_passes < 2 or primary < 1:
                self.status = "stopped_pilot_gate_failed"
                self.stop_reason = (
                    "pilot_requires_three_infrastructure_valid_two_verifier_pass_one_primary"
                )
                return
            self.status = "production_running"
        if self.primary_count >= HWE_TARGET_PRIMARY:
            self.status = "completed"

    def report(self) -> dict[str, Any]:
        categories = Counter(attempt.status for attempt in self.attempts)
        rejection_reasons = Counter(
            attempt.rejection_reason
            for attempt in self.attempts
            if attempt.rejection_reason is not None
        )
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_hwe_cva6_codex_campaign_report_v2",
            "campaign_id": self.campaign_id,
            "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
            "observation_policy_id": HWE_OBSERVATION_POLICY_V2_ID,
            "tool_contract_id": HWE_TOOL_CONTRACT_V2_ID,
            "exec_lifecycle_policy_id": HWE_EXEC_LIFECYCLE_POLICY_ID,
            "prompt_contract_id": HWE_CODEX_PROMPT_CONTRACT_ID,
            "prompt_contract_version": HWE_CODEX_PROMPT_CONTRACT_VERSION,
            "base_instruction_policy": HWE_CODEX_BASE_INSTRUCTION_POLICY,
            "model_id": "gpt-5.4",
            "reasoning_effort": "xhigh",
            "seed": 484,
            "workspace_runtime_image_id": HWE_WORKSPACE_RUNTIME_IMAGE_ID,
            "runtime_user": self.runtime_user,
            "samples_per_task": 1,
            "best_of_k": False,
            "automatic_retry": "zero_model_call_startup_only",
            "zero_call_startup_restart_limit": HWE_ZERO_CALL_STARTUP_RESTARTS,
            "model_substitution": False,
            "pilot_task_ids": list(HWE_PILOT_TASKS),
            "frozen_task_pool": list(self.frozen_task_pool),
            "status": self.status,
            "stop_reason": self.stop_reason,
            "attempt_count": len(self.attempts),
            "benchmark_verifier_pass": sum(item.verifier_pass for item in self.attempts),
            "normalized_success": sum(item.normalized_success for item in self.attempts),
            "primary_eligible": self.primary_count,
            "long_context_candidate": categories["long_context_candidate"],
            "agent_policy_rejected": categories["agent_policy_rejected"],
            "rejection_reasons": dict(sorted(rejection_reasons.items())),
            "pilot_is_benchmark_score": False,
            "hpc_jobs_submitted": False,
            "attempts": [attempt.__dict__ for attempt in self.attempts],
        }
        return {**base, "report_hash": content_hash(base)}


ActionConditionedAttemptStatus = Literal[
    "action_conditioned_eligible_success",
    "action_conditioned_ineligible",
    "verifier_rejected",
    "normalized_failure",
    "agent_policy_rejected",
    "infrastructure_invalid",
]


@dataclass(frozen=True)
class HweActionConditionedCampaignAttempt:
    """One fresh rollout and its deterministic post-rollout action-history derivation."""

    task_id: str
    status: ActionConditionedAttemptStatus
    infrastructure_valid: bool
    verifier_pass: bool
    normalized_success: bool
    source_sft_bucket: Literal["primary", "long_context_candidate", "audit"] | None
    action_conditioned_eligible: bool
    action_record_count: int
    max_action_record_tokens: int | None
    source_transcript_hash: str | None
    action_records_hash: str | None
    run_hash: str
    rejection_reason: str | None = None
    external_model_call_count: int | None = None
    external_input_tokens: int | None = None
    external_output_tokens: int | None = None
    external_total_tokens: int | None = None
    protocol_error_subcategory: str | None = None
    launch_attempt_count: int = 1


@dataclass
class HweActionConditionedCampaignState:
    """Pilot-gate fresh rollouts by one frozen action-conditioned masking policy."""

    frozen_task_pool: tuple[str, ...]
    campaign_id: str
    frozen_agent_image_lock_hashes: tuple[tuple[str, str], ...]
    history_recent_observations: Literal[1, 2, 8, 10, 16] = HWE_SELECTED_HISTORY_WINDOW
    history_max_pinned_observations: Literal[1, 2, 4] = 4
    attempts: list[HweActionConditionedCampaignAttempt] = field(default_factory=list)
    status: str = "pilot_running"
    stop_reason: str | None = None
    runtime_user: str = field(default_factory=lambda: f"{os.getuid()}:{os.getgid()}")

    def __post_init__(self) -> None:
        HweHistoryMaskingPolicy(
            recent_observations=self.history_recent_observations,
            max_pinned_observations=self.history_max_pinned_observations,
        )
        if len(self.frozen_task_pool) != 11 or len(set(self.frozen_task_pool)) != 11:
            raise ValueError("HWE action-conditioned campaign requires a frozen 11-task pool")
        if not set(HWE_PILOT_TASKS).issubset(self.frozen_task_pool):
            raise ValueError("HWE action-conditioned pool omits a required pilot task")
        if (
            len(self.frozen_agent_image_lock_hashes) != 11
            or tuple(sorted(self.frozen_agent_image_lock_hashes))
            != self.frozen_agent_image_lock_hashes
            or {task_id for task_id, _lock_hash in self.frozen_agent_image_lock_hashes}
            != set(self.frozen_task_pool)
            or any(
                len(lock_hash) != 64 for _task_id, lock_hash in self.frozen_agent_image_lock_hashes
            )
        ):
            raise ValueError("HWE action-conditioned campaign requires 11 frozen image lock hashes")
        if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", self.runtime_user):
            raise ValueError(
                "HWE action-conditioned campaign requires an explicit non-root numeric UID:GID"
            )

    @property
    def eligible_trajectory_count(self) -> int:
        return sum(
            attempt.status == "action_conditioned_eligible_success" for attempt in self.attempts
        )

    @property
    def action_record_count(self) -> int:
        return sum(attempt.action_record_count for attempt in self.attempts)

    def next_task(self) -> str | None:
        if self.status.startswith("stopped") or self.status == "completed":
            return None
        attempted = {attempt.task_id for attempt in self.attempts}
        if self.status == "pilot_running":
            return next((task for task in HWE_PILOT_TASKS if task not in attempted), None)
        if self.eligible_trajectory_count >= HWE_TARGET_ACTION_CONDITIONED_TRAJECTORIES:
            self.status = "completed"
            return None
        task = next((task for task in self.frozen_task_pool if task not in attempted), None)
        if task is None:
            self.status = "stopped_pool_exhausted"
            self.stop_reason = "fewer_than_eight_action_conditioned_eligible_successes"
        return task

    def record(self, attempt: HweActionConditionedCampaignAttempt) -> None:
        expected = self.next_task()
        if expected is None or attempt.task_id != expected:
            raise ValueError("HWE action-conditioned attempt is out of frozen order or repeated")
        if len(attempt.run_hash) != 64:
            raise ValueError("HWE action-conditioned attempt lacks a frozen run identity")
        if attempt.launch_attempt_count not in range(1, HWE_ZERO_CALL_STARTUP_RESTARTS + 2):
            raise ValueError("HWE action-conditioned launch count violates startup policy")
        if attempt.action_conditioned_eligible != (
            attempt.status == "action_conditioned_eligible_success"
        ):
            raise ValueError("HWE action-conditioned status and eligibility disagree")
        if attempt.action_conditioned_eligible and (
            not attempt.infrastructure_valid
            or not attempt.verifier_pass
            or not attempt.normalized_success
            or attempt.action_record_count < 1
            or attempt.max_action_record_tokens is None
            or attempt.max_action_record_tokens > 32_768
            or attempt.source_transcript_hash is None
            or attempt.action_records_hash is None
        ):
            raise ValueError("HWE action-conditioned success lacks required evidence")
        self.attempts.append(attempt)
        if attempt.status == "infrastructure_invalid" or not attempt.infrastructure_valid:
            self.status = "stopped_infrastructure_invalid"
            self.stop_reason = attempt.rejection_reason or "infrastructure_invalid"
            return
        pilot_attempts = [item for item in self.attempts if item.task_id in HWE_PILOT_TASKS]
        if self.status == "pilot_running" and len(pilot_attempts) == len(HWE_PILOT_TASKS):
            verifier_passes = sum(item.verifier_pass for item in pilot_attempts)
            verifier_passes_materialized = sum(
                item.action_conditioned_eligible for item in pilot_attempts if item.verifier_pass
            )
            if verifier_passes < 2 or verifier_passes_materialized != verifier_passes:
                self.status = "stopped_pilot_gate_failed"
                self.stop_reason = (
                    "pilot_requires_three_infrastructure_valid_two_verifier_passes_and_"
                    "all_passes_action_conditioned_within_32k"
                )
                return
            self.status = "production_running"
        if self.eligible_trajectory_count >= HWE_TARGET_ACTION_CONDITIONED_TRAJECTORIES:
            self.status = "completed"

    def report(self) -> dict[str, Any]:
        policy = HweHistoryMaskingPolicy(
            recent_observations=self.history_recent_observations,
            max_pinned_observations=self.history_max_pinned_observations,
        )
        categories = Counter(attempt.status for attempt in self.attempts)
        rejection_reasons = Counter(
            attempt.rejection_reason
            for attempt in self.attempts
            if attempt.rejection_reason is not None
        )
        base = {
            "schema_version": "1.0",
            "format_id": HWE_ACTION_CONDITIONED_CAMPAIGN_FORMAT,
            "campaign_id": self.campaign_id,
            "campaign_semantics": (
                "fresh_rollout_posthoc_action_conditioned_derivation_with_model_policy_rejection_v2"
            ),
            "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
            "observation_policy_id": HWE_OBSERVATION_POLICY_V2_ID,
            "tool_contract_id": HWE_TOOL_CONTRACT_V2_ID,
            "exec_lifecycle_policy_id": HWE_EXEC_LIFECYCLE_POLICY_ID,
            "prompt_contract_id": HWE_CODEX_PROMPT_CONTRACT_ID,
            "prompt_contract_version": HWE_CODEX_PROMPT_CONTRACT_VERSION,
            "base_instruction_policy": HWE_CODEX_BASE_INSTRUCTION_POLICY,
            "history_policy_id": HWE_HISTORY_MASKING_POLICY_ID,
            "history_policy_hash": policy.policy_hash,
            "history_recent_observations": self.history_recent_observations,
            "history_max_pinned_observations": self.history_max_pinned_observations,
            "tokenizer_id": HWE_TOKENIZER_ID,
            "tokenizer_hash": HWE_TOKENIZER_HASH,
            "action_record_format_id": "verigym_hwe_action_conditioned_sft_v1",
            "dataset_format_id": HWE_ACTION_CONDITIONED_DATASET_FORMAT,
            "training_eligibility": "experimental_action_conditioned",
            "counterfactual_next_action_validation": "not_run",
            "model_id": "gpt-5.4",
            "reasoning_effort": "xhigh",
            "seed": 484,
            "workspace_runtime_image_id": HWE_WORKSPACE_RUNTIME_IMAGE_ID,
            "runtime_user": self.runtime_user,
            "samples_per_task": 1,
            "best_of_k": False,
            "automatic_retry": "zero_model_call_startup_only",
            "zero_call_startup_restart_limit": HWE_ZERO_CALL_STARTUP_RESTARTS,
            "model_substitution": False,
            "pilot_task_ids": list(HWE_PILOT_TASKS),
            "frozen_task_pool": list(self.frozen_task_pool),
            "agent_image_lock_hashes": dict(self.frozen_agent_image_lock_hashes),
            "status": self.status,
            "stop_reason": self.stop_reason,
            "attempt_count": len(self.attempts),
            "benchmark_verifier_pass": sum(item.verifier_pass for item in self.attempts),
            "normalized_success": sum(item.normalized_success for item in self.attempts),
            "action_conditioned_eligible_success": self.eligible_trajectory_count,
            "action_record_count": self.action_record_count,
            "action_conditioned_ineligible": categories["action_conditioned_ineligible"],
            "agent_policy_rejected": categories["agent_policy_rejected"],
            "primary_eligible": 0,
            "existing_primary_reclassified": False,
            "pilot_is_benchmark_score": False,
            "rejection_reasons": dict(sorted(rejection_reasons.items())),
            "hpc_jobs_submitted": False,
            "attempts": [attempt.__dict__ for attempt in self.attempts],
        }
        return {**base, "report_hash": content_hash(base)}


def build_action_conditioned_handoff(
    *,
    campaign_report: dict[str, Any],
    dataset_manifest: dict[str, Any],
    bindings_hash: str,
) -> dict[str, Any]:
    """Build a disabled experimental handoff; this function never submits training."""

    if (
        campaign_report.get("status") != "completed"
        or campaign_report.get("action_conditioned_eligible_success")
        != HWE_TARGET_ACTION_CONDITIONED_TRAJECTORIES
    ):
        raise ValueError("action-conditioned handoff requires eight eligible trajectories")
    if dataset_manifest.get("trajectory_count") != HWE_TARGET_ACTION_CONDITIONED_TRAJECTORIES:
        raise ValueError("action-conditioned handoff dataset is incomplete")
    if dataset_manifest.get("primary_eligible") is not False:
        raise ValueError("action-conditioned handoff cannot relabel primary data")
    history_recent = campaign_report.get("history_recent_observations")
    history_pinned = campaign_report.get("history_max_pinned_observations")
    if not isinstance(history_recent, int) or not isinstance(history_pinned, int):
        raise ValueError("action-conditioned handoff history parameters are malformed")
    history_parameters = (history_recent, history_pinned)
    training_configs = {
        (16, 4): "configs/training/qwen35_hwe_action_conditioned_sft_v1.json",
        (1, 1): "configs/training/qwen35_hwe_action_conditioned_sft_v2.json",
    }
    training_config = training_configs.get(history_parameters)
    if training_config is None:
        raise ValueError("action-conditioned handoff has no matching disabled training config")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_cva6_action_conditioned_handoff_v1",
        "campaign_report_hash": campaign_report.get("report_hash"),
        "dataset_manifest_hash": dataset_manifest.get("dataset_hash"),
        "bindings_hash": bindings_hash,
        "training_config": training_config,
        "training_config_enabled": False,
        "requires_separate_quality_gate": True,
        "record_count": dataset_manifest.get("record_count"),
        "trajectory_count": HWE_TARGET_ACTION_CONDITIONED_TRAJECTORIES,
        "max_length": 32_768,
        "truncation": "error",
        "supervised_roles": ["final_assistant_action_only"],
        "hpc_jobs_submitted": False,
    }
    return {**base, "handoff_hash": content_hash(base)}


def build_hpc_handoff(
    *,
    campaign_report: dict[str, Any],
    dataset_manifest: dict[str, Any],
    bindings_hash: str,
) -> dict[str, Any]:
    if (
        campaign_report.get("status") != "completed"
        or campaign_report.get("primary_eligible") != HWE_TARGET_PRIMARY
    ):
        raise ValueError("HPC handoff requires eight accepted HWE primary trajectories")
    if dataset_manifest.get("record_count") != HWE_TARGET_PRIMARY:
        raise ValueError("HPC handoff dataset is incomplete")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_cva6_hpc_handoff_v2",
        "campaign_report_hash": campaign_report.get("report_hash"),
        "dataset_manifest_hash": dataset_manifest.get("dataset_hash"),
        "bindings_hash": bindings_hash,
        "training_config": "configs/training/qwen35_hwe_sft_v3.json",
        "record_count": HWE_TARGET_PRIMARY,
        "max_length": 32_768,
        "truncation": "error",
        "supervised_roles": ["assistant"],
        "hpc_jobs_submitted": False,
    }
    return {**base, "handoff_hash": content_hash(base)}


__all__ = [
    "ActionConditionedAttemptStatus",
    "HWE_ACTION_CONDITIONED_CAMPAIGN_FORMAT",
    "HWE_CODEX_BASE_INSTRUCTION_POLICY",
    "HWE_CODEX_PROMPT_CONTRACT_ID",
    "HWE_CODEX_PROMPT_CONTRACT_VERSION",
    "HWE_EXEC_LIFECYCLE_POLICY_ID",
    "HWE_PILOT_TASKS",
    "HWE_TARGET_PRIMARY",
    "HWE_TARGET_ACTION_CONDITIONED_TRAJECTORIES",
    "HWE_ZERO_CALL_STARTUP_RESTARTS",
    "HWE_WORKSPACE_RUNTIME_IMAGE_ID",
    "HweCampaignAttempt",
    "HweCampaignState",
    "HweActionConditionedCampaignAttempt",
    "HweActionConditionedCampaignState",
    "build_action_conditioned_handoff",
    "build_hpc_handoff",
]
