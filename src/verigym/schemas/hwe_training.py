"""Schemas for the independently versioned HWE training-ready experiment arms."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.hwe import (
    HweActionConditionedSftDatasetManifest,
    HweActionConditionedSftExample,
)

_HASH = re.compile(r"[0-9a-f]{64}")


def _sha256(value: str) -> str:
    if not _HASH.fullmatch(value):
        raise ValueError("HWE training identity must be lowercase SHA-256")
    return value


class HweTrainingReadyActionConditionedExample(HweActionConditionedSftExample):
    """One NAP-gated action-conditioned record; historical v1 rows remain untouched."""

    format_id: Literal["verigym_hwe_training_ready_action_conditioned_sft_v1"]  # type: ignore[assignment]
    training_eligibility: Literal["training_ready_action_conditioned"]  # type: ignore[assignment]
    counterfactual_next_action_validation: Literal["passed"]  # type: ignore[assignment]
    nap_validation: dict[str, Any]
    recovery: dict[str, Any]


class HweTrainingReadyActionConditionedManifest(HweActionConditionedSftDatasetManifest):
    """Manifest for the 419-record NAP-gated Complexity-Trap arm."""

    format_id: Literal["verigym_hwe_training_ready_action_conditioned_sft_dataset_v1"]  # type: ignore[assignment]
    canonical_action_hashes: list[str] = Field(min_length=419, max_length=419)
    old_dataset_hash: str
    old_record_hashes: list[str] = Field(min_length=419, max_length=419)
    nap_validation: dict[str, Any]
    counterfactual_next_action_validation: Literal["passed"]  # type: ignore[assignment]
    training_ready: Literal[True]

    @field_validator("canonical_action_hashes", "old_record_hashes")
    @classmethod
    def validate_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @field_validator("old_dataset_hash")
    @classmethod
    def validate_old_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_ready_manifest(self) -> Self:
        if self.record_count != 419 or len(self.canonical_action_hashes) != 419:
            raise ValueError("training-ready action-conditioned arm must contain 419 actions")
        if len(self.old_record_hashes) != len(set(self.old_record_hashes)):
            raise ValueError("historical action-conditioned record hashes must be unique")
        return self


class HweCoactExample(StrictModel):
    """One complete, unsplit CoACT trajectory."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_coact_multiturn_sft_v1"]
    example_hash: str
    sample_id: str
    task_id: str
    task_hash: str
    source_hash: str
    candidate_hash: str
    verifier_hash: str
    source_transcript_hash: str
    messages: list[dict[str, Any]] = Field(min_length=1)
    token_count: int = Field(ge=1, le=65_536)
    max_length: Literal[65_536]
    truncation: Literal["error"]
    supervised_roles: list[Literal["assistant"]]
    masked_roles: list[Literal["system", "user", "tool"]]
    canonical_action_hashes: list[str] = Field(min_length=1)
    compression_manifest: dict[str, Any]
    verifier_resolved: Literal[True]
    infrastructure_valid: Literal[True]
    primary_source_eligible: bool
    raw_provider_events_exported: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    credential_values_exported: Literal[False]
    raw_host_paths_exported: Literal[False]

    @field_validator(
        "example_hash",
        "sample_id",
        "task_hash",
        "source_hash",
        "candidate_hash",
        "verifier_hash",
        "source_transcript_hash",
    )
    @classmethod
    def validate_identity_hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator("canonical_action_hashes")
    @classmethod
    def validate_action_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @model_validator(mode="after")
    def validate_example(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"example_hash"})
        if content_hash(identity) != self.example_hash:
            raise ValueError("CoACT example identity changed")
        if self.supervised_roles != ["assistant"] or self.truncation != "error":
            raise ValueError("CoACT trainer supervision contract changed")
        if self.compression_manifest.get("causal_validation") != "passed":
            raise ValueError("CoACT example lacks causal compression proof")
        return self


class HweCoactDatasetManifest(StrictModel):
    """Dataset-level lock for the eight-trajectory CoACT arm."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_coact_multiturn_sft_dataset_v1"]
    trajectory_count: Literal[8]
    record_count: Literal[8]
    task_ids: list[str] = Field(min_length=8, max_length=8)
    example_hashes: list[str] = Field(min_length=8, max_length=8)
    canonical_action_hashes: list[str] = Field(min_length=419, max_length=419)
    total_action_count: Literal[419]
    max_token_count: int = Field(ge=1, le=65_536)
    max_length: Literal[65_536]
    truncation: Literal["error"]
    training_semantics: Literal["complete_multiturn_assistant_actions"]
    supervised_roles: list[Literal["assistant"]]
    observation_compression_format: Literal["hwe_coact_observation_entry_compression_v1"]
    only_verifier_resolved: Literal[True]
    only_infrastructure_valid: Literal[True]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    hpc_jobs_submitted: Literal[False]
    dataset_hash: str

    @field_validator("example_hashes", "canonical_action_hashes", "dataset_hash")
    @classmethod
    def validate_hashes(cls, values: list[str] | str) -> list[str] | str:
        if isinstance(values, str):
            return _sha256(values)
        return [_sha256(value) for value in values]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"dataset_hash"})
        if content_hash(identity) != self.dataset_hash:
            raise ValueError("CoACT dataset identity changed")
        if self.task_ids != sorted(set(self.task_ids)):
            raise ValueError("CoACT task IDs must be sorted and unique")
        if len(self.example_hashes) != len(set(self.example_hashes)):
            raise ValueError("CoACT example hashes must be unique")
        return self


class HweDecisionSft64kOptimizerSmokeStep(StrictModel):
    """One hash-bound optimizer-smoke step selected from the frozen 64K v4 rows."""

    step: int = Field(ge=1, le=8)
    source_v4_record_index: int = Field(ge=0, lt=83)
    source_v4_record_hash: str
    task_id: str = Field(min_length=1)
    token_count: int = Field(ge=1, le=65_536)
    action_names: list[
        Literal["apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell"]
    ] = Field(min_length=1)
    role: Literal["coverage", "longest_repeat"]

    @field_validator("source_v4_record_hash")
    @classmethod
    def validate_record_hash(cls, value: str) -> str:
        return _sha256(value)


class HweDecisionSft64kOptimizerSmokeOptimizer(StrictModel):
    """Frozen numerical settings for the bounded development optimizer smoke."""

    algorithm: Literal["adamw"]
    learning_rate: float
    betas: tuple[float, float]
    epsilon: float
    weight_decay: float
    scheduler: Literal["constant"]
    warmup_steps: Literal[0]
    max_grad_norm: float

    @model_validator(mode="after")
    def validate_numerics(self) -> Self:
        if (
            self.learning_rate != 0.0001
            or self.betas != (0.9, 0.999)
            or self.epsilon != 1e-8
            or self.weight_decay != 0.0
            or self.max_grad_norm != 1.0
        ):
            raise ValueError("64K optimizer smoke numerical settings changed")
        return self


class HweDecisionSft64kOptimizerSmokeProfile(StrictModel):
    """Frozen four-A30 runtime profile inherited from the successful qualification."""

    precision: Literal["bf16"]
    strategy: Literal["fsdp2"]
    lora_rank: Literal[8]
    lora_alpha: Literal[16]
    lora_dropout: float
    lora_target_modules: Literal["all-linear"]
    gradient_checkpointing: Literal[True]
    remove_padding: Literal[True]
    bounded_fused_vocabulary_head: Literal[True]
    global_batch_size: Literal[1]
    micro_batch_size_per_gpu: Literal[1]
    gradient_accumulation_steps: Literal[1]
    max_length: Literal[65_536]
    max_token_len_per_gpu: Literal[16_384]
    world_size: Literal[4]
    ulysses_sequence_parallel_size: Literal[4]
    num_workers: Literal[0]
    torch_compile: Literal[False]
    parameter_offload: Literal[False]
    optimizer_offload: Literal[False]
    activation_offload: Literal[False]

    @model_validator(mode="after")
    def validate_dropout(self) -> Self:
        if self.lora_dropout != 0.05:
            raise ValueError("64K optimizer smoke LoRA dropout changed")
        return self


class HweDecisionSft64kOptimizerSmokeAcceptance(StrictModel):
    """Fail-closed acceptance gates for the future eight-step execution."""

    actual_verl_loader_rows_before_step_one: Literal[83]
    exact_receipts_revalidated_before_step_one: Literal[True]
    optimizer_steps_required: Literal[8]
    finite_positive_loss_each_step: Literal[True]
    finite_nonzero_gradients_each_step: Literal[True]
    post_clip_global_norm_lte: float
    trainable_parameter_hash_must_change: Literal[True]
    optimizer_state_step_must_match_schedule: Literal[True]
    longest_repeat_steps: tuple[int, int]
    repeat_peak_reserved_delta_max_bytes: Literal[1_073_741_824]
    truncation_allowed: Literal[False]
    checkpoint_allowed: Literal[False]
    adapter_allowed: Literal[False]
    offload_fallback_allowed: Literal[False]
    infrastructure_invalid_is_terminal: Literal[True]
    benchmark_score_claim_allowed: Literal[False]
    production_training_ready: Literal[False]

    @model_validator(mode="after")
    def validate_longest_repeat(self) -> Self:
        if self.longest_repeat_steps != (4, 8) or self.post_clip_global_norm_lte != 1.0:
            raise ValueError("64K optimizer smoke must repeat the longest row at steps 4 and 8")
        return self


class HweDecisionSft64kOptimizerSmokePreregistration(StrictModel):
    """Sealed, not-yet-executed development optimizer-smoke contract."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_decision_sft_64k_optimizer_smoke_v1"]
    status: Literal["preregistered_not_started"]
    scope: Literal["development_optimizer_numerical_smoke_only"]
    source_v3_dataset_hash: Literal[
        "b362cc1df0969f1bad368c939110175502d8ff0d97aef62c93cccd18871e351a"
    ]
    source_v4_dataset_hash: Literal[
        "0acfe95a820d87310a87b6da104ba59e259ce754b19242f7c9b42937591c5139"
    ]
    source_v4_manifest_sha256: Literal[
        "60b1f2646c238efa2197d89c98875c1587a3be16e1c051f2227c3a22b8ae4fac"
    ]
    source_v4_train_jsonl_sha256: Literal[
        "cab55d3cc7752b971904c88d8c11e93645c0b215af9beec40dd648bcfe7f1aa1"
    ]
    qualification_summary_sha256: Literal[
        "da521f3859e4d188c9ebd5d4f560300f896f394905ca864346666f5b9ce1d384"
    ]
    gpu_qualification_sha256: Literal[
        "c44b7068284f4e02d6e0ec44a9e89f56e886debbbc32a06525a4312388d14a62"
    ]
    rllm_commit: Literal["1d1109a655e291b3001d8526d7c9ecc5b9328226"]
    verl_release: Literal["0.8.0"]
    verl_commit: Literal["7aed6b230776f963fa09509c10d9c3a767d1102c"]
    transformers_commit: Literal["e8ea728a3eeeb903e77c7d1bd29267c80a1be71f"]
    trust_remote_code: Literal[False]
    seed: Literal[484]
    step_count: Literal[8]
    schedule: list[HweDecisionSft64kOptimizerSmokeStep] = Field(min_length=8, max_length=8)
    schedule_hash: str
    optimizer: HweDecisionSft64kOptimizerSmokeOptimizer
    profile: HweDecisionSft64kOptimizerSmokeProfile
    acceptance: HweDecisionSft64kOptimizerSmokeAcceptance
    existing_lsf_job_id: Literal["466876"]
    planned_host: Literal["gpu03"]
    selected_gpu_indices: tuple[int, int, int, int]
    new_hpc_jobs_allowed: Literal[False]
    release_existing_allocation: Literal[False]
    checkpoint_resume_validation_deferred: Literal[True]
    training_started: Literal[False]
    optimizer_steps: Literal[0]
    checkpoint_written: Literal[False]
    adapter_written: Literal[False]
    production_training_ready: Literal[False]
    preregistration_hash: str

    @field_validator("schedule_hash", "preregistration_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_preregistration(self) -> Self:
        expected_indices = [62, 76, 20, 61, 41, 43, 53, 61]
        if [item.step for item in self.schedule] != list(range(1, 9)):
            raise ValueError("64K optimizer smoke schedule steps changed")
        if [item.source_v4_record_index for item in self.schedule] != expected_indices:
            raise ValueError("64K optimizer smoke record order changed")
        if [item.token_count for item in self.schedule] != [
            1_883,
            10_693,
            19_713,
            50_117,
            32_262,
            32_778,
            38_749,
            50_117,
        ]:
            raise ValueError("64K optimizer smoke token schedule changed")
        if [item.role for item in self.schedule] != [
            "coverage",
            "coverage",
            "coverage",
            "longest_repeat",
            "coverage",
            "coverage",
            "coverage",
            "longest_repeat",
        ]:
            raise ValueError("64K optimizer smoke repeat roles changed")
        if self.selected_gpu_indices != (0, 1, 2, 3):
            raise ValueError("64K optimizer smoke GPU selection changed")
        schedule_payload = [item.model_dump(mode="json") for item in self.schedule]
        if content_hash(schedule_payload) != self.schedule_hash:
            raise ValueError("64K optimizer smoke schedule hash changed")
        identity = self.model_dump(mode="json", exclude={"preregistration_hash"})
        if content_hash(identity) != self.preregistration_hash:
            raise ValueError("64K optimizer smoke preregistration identity changed")
        return self


class HweDecisionSft64kOptimizerSmokeExecutionAuthorization(StrictModel):
    """One-use authorization bound to the sealed eight-step smoke contract."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_decision_sft_64k_optimizer_smoke_execution_authorization_v1"]
    status: Literal["authorized_for_single_execution"]
    authorization_basis: Literal["explicit_user_instruction"]
    authorization_scope: Literal["single_preregistered_execution"]
    preregistration_hash: str
    preregistration_config_sha256: str
    preregistration_receipt_hash: str
    preregistration_receipt_sha256: str
    source_v4_dataset_hash: Literal[
        "0acfe95a820d87310a87b6da104ba59e259ce754b19242f7c9b42937591c5139"
    ]
    schedule_hash: str
    schedule_indices: tuple[int, int, int, int, int, int, int, int]
    optimizer_steps_authorized: Literal[8]
    execution_authorized: Literal[True]
    checkpoint_allowed: Literal[False]
    adapter_allowed: Literal[False]
    offload_fallback_allowed: Literal[False]
    new_hpc_jobs_allowed: Literal[False]
    release_existing_allocation: Literal[False]
    existing_lsf_job_id: Literal["466876"]
    planned_host: Literal["gpu03"]
    selected_gpu_indices: tuple[int, int, int, int]
    production_training_ready: Literal[False]
    authorization_hash: str

    @field_validator(
        "preregistration_hash",
        "preregistration_config_sha256",
        "preregistration_receipt_hash",
        "preregistration_receipt_sha256",
        "schedule_hash",
        "authorization_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.schedule_indices != (62, 76, 20, 61, 41, 43, 53, 61):
            raise ValueError("64K optimizer smoke execution schedule changed")
        if self.selected_gpu_indices != (0, 1, 2, 3):
            raise ValueError("64K optimizer smoke execution GPU selection changed")
        identity = self.model_dump(mode="json", exclude={"authorization_hash"})
        if content_hash(identity) != self.authorization_hash:
            raise ValueError("64K optimizer smoke execution authorization changed")
        return self


class HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization(
    HweDecisionSft64kOptimizerSmokeExecutionAuthorization
):
    """Replacement authorization allowed only after a proven zero-step implementation failure."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_retry_authorization_v1"
    ]
    status: Literal["authorized_zero_step_implementation_retry"]  # type: ignore[assignment]
    authorization_basis: Literal[  # type: ignore[assignment]
        "explicit_user_instruction_zero_step_implementation_retry"
    ]
    attempt: Literal[2]
    replaces_authorization_hash: str
    prior_failure_report_sha256: str
    prior_optimizer_steps_confirmed: Literal[0]
    replacement_reason: Literal["zero_optimizer_step_implementation_failure"]
    implementation_fix: Literal["replace_unsupported_tensor_maximum_inplace"]
    implementation_source_sha256: str

    @field_validator(
        "replaces_authorization_hash",
        "prior_failure_report_sha256",
        "implementation_source_sha256",
    )
    @classmethod
    def validate_retry_hash(cls, value: str) -> str:
        return _sha256(value)


class HweDecisionSft64kOptimizerDiagnosticReplayAuthorization(StrictModel):
    """One-use authorization for one instrumented replay of the first smoke step."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_decision_sft_64k_optimizer_diagnostic_replay_authorization_v1"]
    status: Literal["authorized_for_single_step_diagnostic_replay"]
    authorization_basis: Literal["explicit_user_instruction_single_step_diagnostic_replay"]
    authorization_scope: Literal["single_record_single_optimizer_step_diagnostic"]
    attempt: Literal[3]
    preregistration_hash: str
    preregistration_config_sha256: str
    preregistration_receipt_hash: str
    preregistration_receipt_sha256: str
    source_v4_dataset_hash: Literal[
        "0acfe95a820d87310a87b6da104ba59e259ce754b19242f7c9b42937591c5139"
    ]
    schedule_hash: str
    source_v4_record_index: Literal[62]
    source_v4_record_hash: Literal[
        "432d9069ef7793e90ec80e85b1d39e7c61dbdf2e751e5cb5948f58658fffcd03"
    ]
    task_id: Literal["hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"]
    token_count: Literal[1_883]
    optimizer_steps_authorized: Literal[1]
    execution_authorized: Literal[True]
    checkpoint_allowed: Literal[False]
    adapter_allowed: Literal[False]
    offload_fallback_allowed: Literal[False]
    new_hpc_jobs_allowed: Literal[False]
    release_existing_allocation: Literal[False]
    existing_lsf_job_id: Literal["466876"]
    planned_host: Literal["gpu03"]
    selected_gpu_indices: tuple[int, int, int, int]
    prior_authorization_hash: Literal[
        "e20d56f36cd847c3b5bba088016d09a651a689935c299c2f13f09796ff375be7"
    ]
    prior_failure_report_sha256: Literal[
        "138000280478730bcb39b43788565b464a637fe77cfce03c999194a4fc39832b"
    ]
    prior_retry_authorization_hash: Literal[
        "68246c680006aa392a45de4beafa1c2f11a53566bcc9ec9323130ead3874b34e"
    ]
    prior_retry_failure_report_sha256: Literal[
        "bb35899a191bb71b7f4d6fa67a6a6d8a92a69b92a66fd3a709d2ed122f5e1a1b"
    ]
    prior_retry_optimizer_steps_confirmed: Literal[1]
    diagnostic_instrumentation_source_sha256: str
    development_training_ready: Literal[False]
    production_training_ready: Literal[False]
    authorization_hash: str

    @field_validator(
        "preregistration_hash",
        "preregistration_config_sha256",
        "preregistration_receipt_hash",
        "preregistration_receipt_sha256",
        "schedule_hash",
        "diagnostic_instrumentation_source_sha256",
        "authorization_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.selected_gpu_indices != (0, 1, 2, 3):
            raise ValueError("64K optimizer diagnostic replay GPU selection changed")
        identity = self.model_dump(mode="json", exclude={"authorization_hash"})
        if content_hash(identity) != self.authorization_hash:
            raise ValueError("64K optimizer diagnostic replay authorization changed")
        return self


class HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization(
    HweDecisionSft64kOptimizerDiagnosticReplayAuthorization
):
    """One-use replay authorization with a preregistered BF16 clipping tolerance."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_hwe_decision_sft_64k_optimizer_bf16_tolerance_replay_authorization_v1"
    ]
    status: Literal[  # type: ignore[assignment]
        "authorized_for_single_step_bf16_tolerance_replay"
    ]
    authorization_basis: Literal[  # type: ignore[assignment]
        "explicit_user_instruction_execute_bf16_tolerance_replay"
    ]
    authorization_scope: Literal[  # type: ignore[assignment]
        "single_record_single_optimizer_step_bf16_tolerance"
    ]
    attempt: Literal[4]  # type: ignore[assignment]
    replaces_authorization_hash: Literal[
        "b7a9942c9226cc39f28d8e946aa70e796dc15e39c5d5b49d215617ce14cdbc22"
    ]
    prior_diagnostic_authorization_sha256: Literal[
        "5ec32ef199fd091d8aad1f52d62c3b797456e34b323052db5797b3dc4fcaf58c"
    ]
    prior_diagnostic_failure_report_sha256: Literal[
        "c50793fe6b724632784e533733a60181d2762ad02c25162391938fecf7c16fcb"
    ]
    prior_diagnostic_instrumentation_source_sha256: Literal[
        "242a910cfa104740ffa4e87eb2f332d96dbaace31cabe59046d3b2bfa207bea9"
    ]
    prior_diagnostic_optimizer_steps_confirmed: Literal[1]
    prior_failed_invariant: Literal["post_clip_global_norm_within_limit"]
    gradient_clip_target: float
    bfloat16_epsilon: float
    tolerance_multiplier: Literal[2]
    post_clip_global_norm_relative_tolerance: float
    post_clip_global_norm_acceptance_lte: float
    tolerance_basis: Literal["two_bfloat16_eps_relative_rounding_margin"]
    tolerance_tuned_to_observed_value: Literal[False]

    @model_validator(mode="after")
    def validate_bf16_tolerance(self) -> Self:
        if (
            self.gradient_clip_target != 1.0
            or self.bfloat16_epsilon != 0.0078125
            or self.post_clip_global_norm_relative_tolerance != 0.015625
            or self.post_clip_global_norm_acceptance_lte != 1.015625
        ):
            raise ValueError("64K optimizer BF16 clipping tolerance changed")
        return self


class HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization(
    HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization
):
    """One-use replay bound to the repaired one-step execution schedule."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_hwe_decision_sft_64k_optimizer_authorized_schedule_replay_authorization_v1"
    ]
    status: Literal[  # type: ignore[assignment]
        "authorized_for_single_step_authorized_schedule_replay"
    ]
    authorization_basis: Literal[  # type: ignore[assignment]
        "explicit_user_instruction_and_standing_same_scope_authorization"
    ]
    authorization_scope: Literal[  # type: ignore[assignment]
        "single_record_single_optimizer_step_authorized_schedule"
    ]
    attempt: Literal[5]  # type: ignore[assignment]
    replaces_authorization_hash: Literal[  # type: ignore[assignment]
        "82d5d82cfcfd5099551cf3ac38dade72ace01c88e55f92e358856bddfac88224"
    ]
    prior_bf16_tolerance_authorization_sha256: Literal[
        "213015d673eb8f5f226a6eeceba52fc583bfb23aa19fd77286ad43f82fe983fe"
    ]
    prior_bf16_tolerance_failure_report_sha256: Literal[
        "4647b7564caf1ea7f090c7c96b3f499c8d82e4f9cab247b8a445cd5c7b230392"
    ]
    prior_bf16_tolerance_optimizer_steps_confirmed: Literal[1]
    prior_bf16_post_step_invariants_all_passed: Literal[True]
    prior_second_optimizer_step_executed: Literal[False]
    prior_bf16_rank_diagnostic_sha256: tuple[str, str, str, str]
    implementation_fix: Literal["execution_loop_uses_authorized_schedule"]

    @field_validator("prior_bf16_rank_diagnostic_sha256")
    @classmethod
    def validate_rank_diagnostic_hashes(
        cls,
        values: tuple[str, str, str, str],
    ) -> tuple[str, str, str, str]:
        expected = (
            "8fe9add5ab125bc8866ff748eae36c3b91be8be12032ca07407d4346cd94d591",
            "bff676e9921fc7aa9f1d60dc289520581982ec115d38cd48a195b81bd314b4f0",
            "d55014ffbede6b8a92b93f25fda4f06c2bf278f2840a072c9b7bdb620712a3d1",
            "f204cfe5fe18babaf41d05796eeb242935a522f13c5e9fe6df6d1f348e57d7a7",
        )
        if tuple(_sha256(value) for value in values) != expected:
            raise ValueError("64K optimizer BF16 rank diagnostic identities changed")
        return values


class HweDecisionSft64kOptimizerFullSmokeReplayAuthorization(
    HweDecisionSft64kOptimizerSmokeExecutionAuthorization
):
    """One-use full eight-step smoke replay after the repaired single-step pass."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_hwe_decision_sft_64k_optimizer_full_smoke_replay_authorization_v1"
    ]
    status: Literal["authorized_for_full_eight_step_smoke_replay"]  # type: ignore[assignment]
    authorization_basis: Literal[  # type: ignore[assignment]
        "explicit_user_instruction_execute_full_eight_step_optimizer_smoke"
    ]
    authorization_scope: Literal[  # type: ignore[assignment]
        "single_preregistered_eight_step_optimizer_smoke"
    ]
    attempt: Literal[6]
    replaces_authorization_hash: Literal[
        "8ef0ae8e44cedb40f6967bc85475fd4483ebed860c6653e2ea0d2582bb26a7d2"
    ]
    prior_authorized_schedule_authorization_sha256: Literal[
        "acc637cd5326bbb3be4dff3a2227991bc4815fd58ba80dd69a317faec7a4b3e3"
    ]
    prior_authorized_schedule_pass_report_sha256: Literal[
        "c18ce989c41b68b2f3d93bba120857a4f488c0d0796e5aba7318847493299b71"
    ]
    prior_authorized_schedule_optimizer_steps_confirmed: Literal[1]
    prior_authorized_schedule_invariants_all_passed: Literal[True]
    prior_authorized_schedule_rank_diagnostic_sha256: tuple[str, str, str, str]
    implementation_fix: Literal["execution_loop_uses_authorized_schedule"]
    implementation_source_sha256: Literal[
        "f024e74dc3ba74f97c9132812b73a299fa3ca7be076e66b0eb0a177276e37c61"
    ]

    @field_validator("prior_authorized_schedule_rank_diagnostic_sha256")
    @classmethod
    def validate_rank_diagnostic_hashes(
        cls,
        values: tuple[str, str, str, str],
    ) -> tuple[str, str, str, str]:
        expected = (
            "d4fe830ba8bcaa389d18c15eb73f9ee811d0efb63b4d6ae8732e86d00dfa37ec",
            "d338b63d08f50fbe8ac9366bb7e0c895c0fc6033463c687fa1cc80d4cb2d8ea3",
            "3c0619e36b3a506d5f0f7e7f214f78727065bf38a68533d124f0427a9549d99c",
            "59acab82347d6111684fb1f4c7f8e39fbc821a6d940ce6800c3edc795725b242",
        )
        if tuple(_sha256(value) for value in values) != expected:
            raise ValueError("64K optimizer authorized-schedule rank identities changed")
        return values


class HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization(
    HweDecisionSft64kOptimizerFullSmokeReplayAuthorization
):
    """One-use eight-step retry with the already-qualified BF16 clipping margin."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_hwe_decision_sft_64k_optimizer_full_smoke_bf16_tolerance_replay_authorization_v1"
    ]
    status: Literal[  # type: ignore[assignment]
        "authorized_for_full_eight_step_bf16_tolerance_replay"
    ]
    authorization_basis: Literal[  # type: ignore[assignment]
        "explicit_user_instruction_authorize_attempt_7_and_standing_same_scope_authorization"
    ]
    authorization_scope: Literal[  # type: ignore[assignment]
        "single_preregistered_eight_step_optimizer_smoke_bf16_tolerance"
    ]
    attempt: Literal[7]  # type: ignore[assignment]
    replaces_authorization_hash: Literal[  # type: ignore[assignment]
        "0b443189d11c9943687d6f8dd249a203132aba003b49606493292268a6c5b705"
    ]
    prior_full_smoke_authorization_sha256: Literal[
        "53ffc48bc61aec314e8e1235d556d43ce677446ae9c346439c5973c7a9d11fe9"
    ]
    prior_full_smoke_failure_report_sha256: Literal[
        "1cf0b909b9adc9f945295dadf369c41add239e0e5f26acfeb7b643e8cedecf40"
    ]
    prior_full_smoke_optimizer_steps_confirmed: Literal[2]
    prior_full_smoke_failure_step: Literal[2]
    prior_full_smoke_failure_record_index: Literal[76]
    prior_full_smoke_failure_token_count: Literal[10693]
    prior_full_smoke_failed_invariant: Literal["post_clip_global_norm_within_limit"]
    prior_full_smoke_rank_diagnostic_sha256: tuple[
        str,
        str,
        str,
        str,
        str,
        str,
        str,
        str,
    ]
    gradient_clip_target: float
    bfloat16_epsilon: float
    tolerance_multiplier: Literal[2]
    post_clip_global_norm_relative_tolerance: float
    post_clip_global_norm_acceptance_lte: float
    tolerance_basis: Literal["two_bfloat16_eps_relative_rounding_margin"]
    tolerance_inherited_from_prior_authorized_schedule: Literal[True]
    tolerance_tuned_to_observed_value: Literal[False]
    implementation_fix: Literal[  # type: ignore[assignment]
        "full_smoke_inherits_validated_bf16_clip_tolerance"
    ]
    implementation_source_sha256: Literal[  # type: ignore[assignment]
        "638caef60503df8f31c550cecf046ec854a0af332230abad01e3a26f8de6ddee"
    ]

    @field_validator("prior_full_smoke_rank_diagnostic_sha256")
    @classmethod
    def validate_full_smoke_rank_diagnostic_hashes(
        cls,
        values: tuple[str, str, str, str, str, str, str, str],
    ) -> tuple[str, str, str, str, str, str, str, str]:
        expected = (
            "010f422e394ff78ea70e7c08852cd621f29d4ad6ca228fb5568386bf216dc999",
            "fff0e61babd2c713abd0dfcafbcf776258188c87be5988461fb0e9dd7d027d58",
            "adcf2d75933395eb132882c9c6a8f0d774df33a52f1decf7ed6aff28227f1aef",
            "be5861f1f01fd015a6f600e0d937f369dc853c1e3a34c98e70872e1517b74111",
            "4fd030805c52eb70736fa7a881460f560fe9c58a0f205fadf628b6def041cf1a",
            "1acf643479bb2590d4ce97bd4894f9be5af506e3697f9eaa76beae6a61cfe816",
            "5acf4d3eb47d40787dc5bb3c18db842ac432636a9977834c050c8ed1d31d7d2a",
            "ee2d3a7e920550d39f46f29d8a59b6192600b25d8d1981f7ca0b2385bab75c8d",
        )
        if tuple(_sha256(value) for value in values) != expected:
            raise ValueError("64K optimizer full-smoke rank identities changed")
        return values

    @model_validator(mode="after")
    def validate_full_smoke_bf16_tolerance(self) -> Self:
        if (
            self.gradient_clip_target != 1.0
            or self.bfloat16_epsilon != 0.0078125
            or self.post_clip_global_norm_relative_tolerance != 0.015625
            or self.post_clip_global_norm_acceptance_lte != 1.015625
        ):
            raise ValueError("64K full-smoke BF16 clipping tolerance changed")
        return self


class HweDecisionSft64kCheckpointResumeQualificationAuthorization(
    HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization
):
    """One-use authorization for a 4-step control versus 2+resume+2 qualification."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_hwe_decision_sft_64k_checkpoint_resume_qualification_authorization_v1"
    ]
    status: Literal[  # type: ignore[assignment]
        "authorized_for_single_checkpoint_resume_qualification"
    ]
    authorization_basis: Literal[  # type: ignore[assignment]
        "explicit_user_instruction_authorize_checkpoint_resume_qualification"
    ]
    authorization_scope: Literal[  # type: ignore[assignment]
        "single_four_step_control_vs_two_plus_resume_plus_two_qualification"
    ]
    attempt: Literal[8]  # type: ignore[assignment]
    replaces_authorization_hash: Literal[  # type: ignore[assignment]
        "a2329c519edd2010aa41bde88168b7f2c24e25714dafaf81e09bbcde3e4857c8"
    ]
    checkpoint_allowed: Literal[True]  # type: ignore[assignment]
    prior_attempt_7_authorization_sha256: Literal[
        "7c65340716337f174e86b7747818e6f00963848427077b1790ca6cd6457e16b8"
    ]
    prior_attempt_7_pass_report_sha256: Literal[
        "46cb4a151da1de3bf789024f2fe122528e1f5ef71984765ea477c31feae6af62"
    ]
    prior_attempt_7_summary_sha256: Literal[
        "f37d83e972055ce64aa75d81d715c53ff0399a6e655b86a18cd9d35da8ed1ca8"
    ]
    prior_attempt_7_optimizer_steps_confirmed: Literal[8]
    prior_attempt_7_invariants_all_passed: Literal[True]
    prior_attempt_7_rank_diagnostic_sha256: tuple[str, ...]
    control_optimizer_steps: Literal[4]
    checkpoint_producer_optimizer_steps: Literal[2]
    resumed_optimizer_steps: Literal[2]
    checkpoint_global_step: Literal[2]
    checkpoint_count_allowed: Literal[1]
    checkpoint_save_contents: tuple[Literal["model"], Literal["optimizer"], Literal["extra"]]
    checkpoint_load_contents: tuple[Literal["model"], Literal["optimizer"], Literal["extra"]]
    checkpoint_format: Literal["verl_fsdp2_sharded_v0_8"]
    dataloader_state_required: Literal[True]
    explicit_schedule_cursor_required: Literal[True]
    rng_state_required: Literal[True]
    lr_scheduler_state_required: Literal[True]
    exact_resume_equivalence_required: Literal[True]
    temporary_checkpoint_deletion_after_validation_allowed: Literal[True]
    checkpoint_resume_implementation: Literal[
        "three_fresh_torchrun_branches_with_hash_bound_fsdp2_checkpoint"
    ]
    checkpoint_resume_implementation_source_sha256: str

    @field_validator("checkpoint_resume_implementation_source_sha256")
    @classmethod
    def validate_checkpoint_resume_source_hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator("prior_attempt_7_rank_diagnostic_sha256")
    @classmethod
    def validate_attempt_7_rank_diagnostic_hashes(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        expected = (
            "8ee20388886eb9c67adb25aabf12791b2af928dbcea04be1713802e4bb9362e5",
            "621bc3a0271f01d77189cf2a1d8a5213dc32e96168cb7ff4bdc9807a127d7296",
            "5122310b6435b902029b547534201cdee18f7b6c58a1c268f2eb1e5779c4c822",
            "d8ada04dc2ed3150d5b527a2930d351eee42e5b0674a2b05e661a1b23da97052",
            "9765a06b62ffec4082357c864a92d451c38674daf4a36e9147bfafb7e88a0f83",
            "29581ad8e84b35fce477b6d324278c7bf80aa8ab3be4c69f50bc3a0172813d33",
            "4ef475741ba69e519564b7bab3de7bfb11f8b51c2fdfd3222f64e1b885b3498c",
            "f18803abcb9002b319f07d03d10e8b307dba91ac32bf9f2f465048acd48f416e",
            "c913ee65cc64653c72dd6d3a378c8bfb9cb6ae1a37695f7f17cea5554a735433",
            "7322774c4e91eaf2ce8be599dbb655cc55c802bfe9eabc7d9097aefde0e4b0e5",
            "8bc4947d9eba6e36dd914aeb958cf636c7ff5c5e0d93712884381d8da1e5493b",
            "b11672e46fbe8db84a5f5150652c41949e31de4f2e4b8c4c376dc592a0400c67",
            "2660dd5b6df128cc0e52169b258117328abc084033ba61d2e3d1a52dd4a430db",
            "ae6d27fe29258fb6dd33f52110aa8bd4074458007308b6004e14b89e9db482ac",
            "cdc7f971e7acf754e3d9e136ce5c628691f4c8380372c33f1888df61c9308776",
            "65bd351a261f6d5e81b68e2ac65b9fa23a9ed26910a2504bb3e688b29debe992",
            "c94c050b4a8945145cc530d0f9e0a808a76aa7cf6c93603757340daeb977fa10",
            "4703003c805e6d1999a699c6c7e6a85bd64039d0c3ed70b0fc935b707e351cb4",
            "c81359468bdeba2f7a5767a043921d535d8e9f6308a5775af185818aeaa2a8f3",
            "675e9966b79027fbbbc7509aff6b7fd869863d5d8a93d40a21fae3a15d2c9ca7",
            "5574c6a42844183343607e3c5eef19c1eb5ae2d7b2802489692532d7009b4972",
            "6a904dede03994ba47816831c35668996bdb573d631f61fdcb509c620caf05e7",
            "5704aa4e892565c8ccc7cc3b72ebd0070f4dced25d938e6dfb9f84f290be2048",
            "1a0a93e5b25dc54b15d866a6993639b02709a9c43ae06e024f4f5c1e4aeb78c5",
            "ebf75f4c7d6ae0136c66a61076d2f1cd8cb9783cf407229a0130dc9d5ef8b861",
            "b8e1fb8c06310c532e21e5b8c3d270d30807534389cf28801339167f0421ea6b",
            "c510f32871ce4c985e3c65b04a4a5d5df8e7c4709d31650c68a7f2264c7fe5cf",
            "eb6027f256956f7486cd5a64d2d5e2c41ce87e92a12d5e09794edc9fd5f33945",
            "e46f4199b13c63ce40080ab551b89f39d2bd88dba7eb97e560e660240d8ea73a",
            "923b71cbb065fa76dd859ac425fb7ce84507421716983aa5b7b732f423e33f64",
            "bfa604f43e9c9909b28e0b94bd9aea0806065f8a68b53e59637b52861bf4f92c",
            "cc568f8e08be5a37b92da15e0e4ace44a599ba59d16c121d74f070d84f0fd47e",
        )
        if tuple(_sha256(value) for value in values) != expected:
            raise ValueError("64K checkpoint/resume attempt-7 rank evidence changed")
        return values

    @model_validator(mode="after")
    def validate_checkpoint_resume_scope(self) -> Self:
        if (
            self.control_optimizer_steps
            + self.checkpoint_producer_optimizer_steps
            + self.resumed_optimizer_steps
            != self.optimizer_steps_authorized
        ):
            raise ValueError("64K checkpoint/resume optimizer-step budget changed")
        if self.checkpoint_save_contents != ("model", "optimizer", "extra"):
            raise ValueError("64K checkpoint/resume save contents changed")
        if self.checkpoint_load_contents != self.checkpoint_save_contents:
            raise ValueError("64K checkpoint/resume load contents changed")
        return self


class HweFrozenArtifactIdentity(StrictModel):
    """One regular file bound by repository-relative name, size, and SHA-256."""

    path: str = Field(min_length=1)
    size_bytes: int = Field(ge=1)
    sha256: str

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or str(path) != value:
            raise ValueError("frozen artifact path must be normalized and relative")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return _sha256(value)


class HweDecisionSft64kDevelopmentSplit(StrictModel):
    """Whole-trajectory train/held-out split for the two accepted v4 trajectories."""

    strategy: Literal["whole_trajectory_holdout_v1"]
    train_task_id: Literal["hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549"]
    heldout_task_id: Literal["hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"]
    train_sample_id: Literal["5f1410c944a31656e3979aa902bb31a7f34d47e8a7c2c6cff372cae8085f072d"]
    heldout_sample_id: Literal["29891240b7a231621aed5ef4d18f7868b08749e365b9d5d1160c968a2ba656eb"]
    train_transcript_hash: Literal[
        "85c4a84c942e94ad609358ecceb9c10664432eca03802ccdcb0131f445ceab1e"
    ]
    heldout_transcript_hash: Literal[
        "72e6dad7bfef85ce588f2e3f4b7bb8d88b28889ba4289c1580dee303ab8abc51"
    ]
    train_record_indices: list[int] = Field(min_length=62, max_length=62)
    heldout_record_indices: list[int] = Field(min_length=21, max_length=21)
    train_record_hashes_hash: str
    heldout_record_hashes_hash: str
    train_input_ids_hashes_hash: str
    heldout_input_ids_hashes_hash: str
    train_loss_mask_hashes_hash: str
    heldout_loss_mask_hashes_hash: str
    leakage_keys: tuple[
        Literal["task_id"],
        Literal["sample_id"],
        Literal["transcript_hash"],
    ]
    overlap_count: Literal[0]
    split_hash: str

    @field_validator(
        "train_sample_id",
        "heldout_sample_id",
        "train_transcript_hash",
        "heldout_transcript_hash",
        "train_record_hashes_hash",
        "heldout_record_hashes_hash",
        "train_input_ids_hashes_hash",
        "heldout_input_ids_hashes_hash",
        "train_loss_mask_hashes_hash",
        "heldout_loss_mask_hashes_hash",
        "split_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_split(self) -> Self:
        if self.train_record_indices != list(range(62)):
            raise ValueError("development train partition changed")
        if self.heldout_record_indices != list(range(62, 83)):
            raise ValueError("development held-out partition changed")
        if self.leakage_keys != ("task_id", "sample_id", "transcript_hash"):
            raise ValueError("development leakage boundary changed")
        identity = self.model_dump(mode="json", exclude={"split_hash"})
        if content_hash(identity) != self.split_hash:
            raise ValueError("development split identity changed")
        return self


class HweDecisionSft64kDevelopmentModel(StrictModel):
    """Frozen local Qwen3.5 model and tokenizer identity."""

    model_id: Literal["Qwen3.5-9B"]
    local_directory_name: Literal["Qwen3.5-9B"]
    causal_lm_class: Literal["Qwen3_5ForCausalLM"]
    tokenizer_id: Literal["Qwen3.5-9B/local-frozen-chat-template"]
    trust_remote_code: Literal[False]
    artifacts: list[HweFrozenArtifactIdentity] = Field(min_length=9, max_length=9)
    artifact_manifest_hash: str
    model_identity_hash: str

    @field_validator("artifact_manifest_hash", "model_identity_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_model_identity(self) -> Self:
        paths = [artifact.path for artifact in self.artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("development model artifacts must be sorted and unique")
        if content_hash([item.model_dump(mode="json") for item in self.artifacts]) != (
            self.artifact_manifest_hash
        ):
            raise ValueError("development model artifact manifest changed")
        identity = self.model_dump(mode="json", exclude={"model_identity_hash"})
        if content_hash(identity) != self.model_identity_hash:
            raise ValueError("development model identity changed")
        return self


class HweDecisionSft64kDevelopmentSources(StrictModel):
    """Frozen upstream revisions and adapter-layer source files."""

    rllm_commit: Literal["1d1109a655e291b3001d8526d7c9ecc5b9328226"]
    verl_release: Literal["0.8.0"]
    verl_commit: Literal["7aed6b230776f963fa09509c10d9c3a767d1102c"]
    transformers_commit: Literal["e8ea728a3eeeb903e77c7d1bd29267c80a1be71f"]
    artifacts: list[HweFrozenArtifactIdentity] = Field(min_length=10, max_length=10)
    artifact_manifest_hash: str
    source_identity_hash: str

    @field_validator("artifact_manifest_hash", "source_identity_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_source_identity(self) -> Self:
        paths = [artifact.path for artifact in self.artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("development source artifacts must be sorted and unique")
        if content_hash([item.model_dump(mode="json") for item in self.artifacts]) != (
            self.artifact_manifest_hash
        ):
            raise ValueError("development source artifact manifest changed")
        identity = self.model_dump(mode="json", exclude={"source_identity_hash"})
        if content_hash(identity) != self.source_identity_hash:
            raise ValueError("development source identity changed")
        return self


class HweDecisionSft64kDevelopmentDeterminism(StrictModel):
    """Deterministic-kernel and sample-order contract inherited from replay-v5."""

    seed: Literal[484]
    sample_order_algorithm: Literal["seeded_sha256_rank_longest_at_16_and_32_v1"]
    shuffle: Literal[False]
    flash_attention_deterministic: Literal[True]
    torch_deterministic_algorithms: Literal[True]
    cublas_workspace_config: Literal[":4096:8"]
    cudnn_deterministic: Literal[True]
    cudnn_benchmark: Literal[False]
    host_rng_step_boundary_normalized: Literal[True]
    cuda_rng_restored_without_boundary_reseeding: Literal[True]


class HweDecisionSft64kDevelopmentCanary(StrictModel):
    """Bounded 32-step train/checkpoint/fresh-resume canary plan."""

    optimizer_steps: Literal[32]
    producer_end_step: Literal[16]
    resumed_start_step: Literal[17]
    resumed_end_step: Literal[32]
    checkpoint_global_step: Literal[16]
    checkpoint_count: Literal[1]
    checkpoint_save_contents: tuple[Literal["model"], Literal["optimizer"], Literal["extra"]]
    checkpoint_load_contents: tuple[Literal["model"], Literal["optimizer"], Literal["extra"]]
    checkpoint_format: Literal["verl_fsdp2_sharded_v0_8"]
    resume_in_fresh_process: Literal[True]
    schedule_indices: list[int] = Field(min_length=32, max_length=32)
    schedule_record_hashes: list[str] = Field(min_length=32, max_length=32)
    schedule_token_counts: list[int] = Field(min_length=32, max_length=32)
    schedule_hash: str
    heldout_evaluation_steps: tuple[Literal[0], Literal[16], Literal[32]]
    heldout_evaluation_record_count: Literal[21]
    heldout_evaluation_forward_only: Literal[True]
    heldout_improvement_required: Literal[False]
    exact_resume_equivalence_required: Literal[True]
    finite_positive_loss_each_training_step: Literal[True]
    finite_nonzero_gradients_each_training_step: Literal[True]
    trainable_parameter_hash_must_change: Literal[True]
    optimizer_state_step_must_match_schedule: Literal[True]
    exact_receipts_revalidated_before_step_one: Literal[True]
    exact_receipts_revalidated_before_each_evaluation: Literal[True]
    truncation_allowed: Literal[False]
    offload_fallback_allowed: Literal[False]
    temporary_checkpoint_deletion_after_validation_allowed: Literal[True]
    adapter_retention_allowed: Literal[False]
    infrastructure_invalid_is_terminal: Literal[True]
    benchmark_score_claim_allowed: Literal[False]

    @field_validator("schedule_record_hashes")
    @classmethod
    def validate_record_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @field_validator("schedule_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_canary(self) -> Self:
        expected_indices = [
            21,
            54,
            46,
            35,
            39,
            22,
            27,
            56,
            13,
            58,
            15,
            6,
            19,
            3,
            11,
            61,
            17,
            16,
            37,
            2,
            40,
            9,
            52,
            24,
            7,
            41,
            38,
            10,
            32,
            12,
            4,
            61,
        ]
        if self.schedule_indices != expected_indices:
            raise ValueError("development canary sample order changed")
        if any(index >= 62 for index in self.schedule_indices if index != 61):
            raise ValueError("development canary schedule crossed into held-out records")
        if len(set(self.schedule_indices[:-1])) != 31:
            raise ValueError("development canary must only repeat the longest training record")
        if self.checkpoint_save_contents != ("model", "optimizer", "extra"):
            raise ValueError("development canary checkpoint contents changed")
        if self.checkpoint_load_contents != self.checkpoint_save_contents:
            raise ValueError("development canary checkpoint load contents changed")
        schedule = [
            {
                "step": step,
                "source_v4_record_index": index,
                "source_v4_record_hash": record_hash,
                "token_count": token_count,
            }
            for step, (index, record_hash, token_count) in enumerate(
                zip(
                    self.schedule_indices,
                    self.schedule_record_hashes,
                    self.schedule_token_counts,
                    strict=True,
                ),
                start=1,
            )
        ]
        if content_hash(schedule) != self.schedule_hash:
            raise ValueError("development canary schedule identity changed")
        return self


class HweDecisionSft64kDevelopmentTrainingPreregistration(StrictModel):
    """Hash-bound development recipe; validation does not authorize GPU training."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_decision_sft_64k_development_training_v1"]
    status: Literal["preregistered_not_authorized"]
    scope: Literal["development_training_32_step_canary_preregistration_only"]
    campaign_id: Literal["cva6-hwe-deepseek-harness-development-training-v1-canary-32step-s484"]
    source_v3_dataset_hash: Literal[
        "b362cc1df0969f1bad368c939110175502d8ff0d97aef62c93cccd18871e351a"
    ]
    source_v4_dataset_hash: Literal[
        "0acfe95a820d87310a87b6da104ba59e259ce754b19242f7c9b42937591c5139"
    ]
    source_v4_manifest_sha256: Literal[
        "60b1f2646c238efa2197d89c98875c1587a3be16e1c051f2227c3a22b8ae4fac"
    ]
    source_v4_train_jsonl_sha256: Literal[
        "cab55d3cc7752b971904c88d8c11e93645c0b215af9beec40dd648bcfe7f1aa1"
    ]
    qualification_artifacts: list[HweFrozenArtifactIdentity] = Field(
        min_length=3,
        max_length=3,
    )
    split: HweDecisionSft64kDevelopmentSplit
    model: HweDecisionSft64kDevelopmentModel
    sources: HweDecisionSft64kDevelopmentSources
    optimizer: HweDecisionSft64kOptimizerSmokeOptimizer
    profile: HweDecisionSft64kOptimizerSmokeProfile
    determinism: HweDecisionSft64kDevelopmentDeterminism
    canary: HweDecisionSft64kDevelopmentCanary
    existing_lsf_job_id: Literal["466876"]
    planned_host: Literal["gpu03"]
    selected_gpu_indices: tuple[int, int, int, int]
    new_hpc_jobs_allowed: Literal[False]
    release_existing_allocation: Literal[False]
    execution_authorized: Literal[False]
    training_started: Literal[False]
    optimizer_steps: Literal[0]
    checkpoint_written: Literal[False]
    adapter_written: Literal[False]
    production_training_ready: Literal[False]
    recipe_hash: str

    @field_validator("recipe_hash")
    @classmethod
    def validate_recipe_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_recipe(self) -> Self:
        paths = [artifact.path for artifact in self.qualification_artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("development qualification artifacts must be sorted and unique")
        if self.selected_gpu_indices != (0, 1, 2, 3):
            raise ValueError("development canary GPU selection changed")
        identity = self.model_dump(mode="json", exclude={"recipe_hash"})
        if content_hash(identity) != self.recipe_hash:
            raise ValueError("development recipe identity changed")
        return self


class HweDecisionSft64kDevelopmentTrainingPreregistrationReceipt(StrictModel):
    """Validation receipt proving that no development training was started."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal[
        "verigym_hwe_decision_sft_64k_development_training_preregistration_receipt_v1"
    ]
    status: Literal["preregistered_not_authorized"]
    campaign_id: Literal["cva6-hwe-deepseek-harness-development-training-v1-canary-32step-s484"]
    recipe_hash: str
    config_sha256: str
    source_v4_dataset_hash: str
    model_identity_hash: str
    source_identity_hash: str
    split_hash: str
    canary_schedule_hash: str
    train_record_count: Literal[62]
    heldout_record_count: Literal[21]
    whole_trajectory_leakage_check: Literal["passed"]
    qualification_evidence_check: Literal["passed"]
    model_artifact_check: Literal["passed"]
    source_artifact_check: Literal["passed"]
    canary_execution_authorized: Literal[False]
    training_started: Literal[False]
    optimizer_steps: Literal[0]
    checkpoint_written: Literal[False]
    adapter_written: Literal[False]
    production_training_ready: Literal[False]
    new_hpc_jobs_submitted: Literal[False]
    existing_allocation_modified: Literal[False]
    receipt_hash: str

    @field_validator(
        "recipe_hash",
        "config_sha256",
        "source_v4_dataset_hash",
        "model_identity_hash",
        "source_identity_hash",
        "split_hash",
        "canary_schedule_hash",
        "receipt_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"receipt_hash"})
        if content_hash(identity) != self.receipt_hash:
            raise ValueError("development preregistration receipt identity changed")
        return self


class HweDecisionSft64kDevelopmentTrainingExecutionAuthorization(StrictModel):
    """One-use authorization for the preregistered 32-step development canary."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal[
        "verigym_hwe_decision_sft_64k_development_training_execution_authorization_v1"
    ]
    status: Literal["authorized_for_single_32_step_canary"]
    authorization_basis: Literal["explicit_user_instruction_authorize_32_step_canary"]
    authorization_scope: Literal["single_preregistered_32_step_checkpoint_resume_canary"]
    recipe_hash: str
    preregistration_config_sha256: str
    preregistration_receipt_hash: str
    preregistration_receipt_sha256: str
    source_v4_dataset_hash: str
    model_identity_hash: str
    source_identity_hash: str
    split_hash: str
    schedule_hash: str
    execution_source_artifacts: list[HweFrozenArtifactIdentity] = Field(
        min_length=4,
        max_length=4,
    )
    execution_source_manifest_hash: str
    optimizer_steps_authorized: Literal[32]
    producer_optimizer_steps: Literal[16]
    resumed_optimizer_steps: Literal[16]
    checkpoint_allowed: Literal[True]
    checkpoint_global_step: Literal[16]
    checkpoint_count_allowed: Literal[1]
    checkpoint_save_contents: tuple[Literal["model"], Literal["optimizer"], Literal["extra"]]
    checkpoint_load_contents: tuple[Literal["model"], Literal["optimizer"], Literal["extra"]]
    heldout_evaluation_steps: tuple[Literal[0], Literal[16], Literal[32]]
    heldout_evaluation_record_count: Literal[21]
    heldout_evaluation_forward_only: Literal[True]
    gradient_clip_target: float
    post_clip_global_norm_relative_tolerance: float
    post_clip_global_norm_acceptance_lte: float
    tolerance_basis: Literal["qualified_two_bfloat16_eps_relative_rounding_margin"]
    temporary_checkpoint_deletion_required: Literal[True]
    adapter_allowed: Literal[False]
    offload_fallback_allowed: Literal[False]
    new_hpc_jobs_allowed: Literal[False]
    release_existing_allocation: Literal[False]
    existing_lsf_job_id: Literal["466876"]
    planned_host: Literal["gpu03"]
    selected_gpu_indices: tuple[int, int, int, int]
    production_training_ready: Literal[False]
    authorization_hash: str

    @field_validator(
        "recipe_hash",
        "preregistration_config_sha256",
        "preregistration_receipt_hash",
        "preregistration_receipt_sha256",
        "source_v4_dataset_hash",
        "model_identity_hash",
        "source_identity_hash",
        "split_hash",
        "schedule_hash",
        "execution_source_manifest_hash",
        "authorization_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        paths = [artifact.path for artifact in self.execution_source_artifacts]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("development execution sources must be sorted and unique")
        if (
            content_hash(
                [artifact.model_dump(mode="json") for artifact in self.execution_source_artifacts]
            )
            != self.execution_source_manifest_hash
        ):
            raise ValueError("development execution source manifest changed")
        if self.producer_optimizer_steps + self.resumed_optimizer_steps != 32:
            raise ValueError("development execution optimizer-step budget changed")
        if self.checkpoint_save_contents != ("model", "optimizer", "extra"):
            raise ValueError("development execution checkpoint contents changed")
        if self.checkpoint_load_contents != self.checkpoint_save_contents:
            raise ValueError("development execution checkpoint load contents changed")
        if self.selected_gpu_indices != (0, 1, 2, 3):
            raise ValueError("development execution GPU selection changed")
        if (
            self.gradient_clip_target != 1.0
            or self.post_clip_global_norm_relative_tolerance != 0.015625
            or self.post_clip_global_norm_acceptance_lte != 1.015625
        ):
            raise ValueError("development execution BF16 clipping tolerance changed")
        identity = self.model_dump(mode="json", exclude={"authorization_hash"})
        if content_hash(identity) != self.authorization_hash:
            raise ValueError("development execution authorization changed")
        return self


__all__ = [
    "HweCoactDatasetManifest",
    "HweCoactExample",
    "HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization",
    "HweDecisionSft64kCheckpointResumeQualificationAuthorization",
    "HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization",
    "HweDecisionSft64kOptimizerSmokeAcceptance",
    "HweDecisionSft64kOptimizerDiagnosticReplayAuthorization",
    "HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization",
    "HweDecisionSft64kOptimizerFullSmokeReplayAuthorization",
    "HweDecisionSft64kOptimizerSmokeExecutionAuthorization",
    "HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization",
    "HweDecisionSft64kOptimizerSmokeOptimizer",
    "HweDecisionSft64kOptimizerSmokePreregistration",
    "HweDecisionSft64kOptimizerSmokeProfile",
    "HweDecisionSft64kOptimizerSmokeStep",
    "HweDecisionSft64kDevelopmentCanary",
    "HweDecisionSft64kDevelopmentDeterminism",
    "HweDecisionSft64kDevelopmentModel",
    "HweDecisionSft64kDevelopmentSources",
    "HweDecisionSft64kDevelopmentSplit",
    "HweDecisionSft64kDevelopmentTrainingPreregistration",
    "HweDecisionSft64kDevelopmentTrainingPreregistrationReceipt",
    "HweDecisionSft64kDevelopmentTrainingExecutionAuthorization",
    "HweFrozenArtifactIdentity",
    "HweTrainingReadyActionConditionedExample",
    "HweTrainingReadyActionConditionedManifest",
]
