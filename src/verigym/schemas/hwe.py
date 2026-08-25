"""Schemas for experimental HWE action-conditioned masking artifacts."""

from __future__ import annotations

import re
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

HweAction = Literal["list_files", "read_file", "apply_patch", "shell", "inspect_diff", "finish"]
HweWindow = Literal[1, 2, 4, 8, 10, 16]
HwePinnedLimit = Literal[1, 2, 4]
HweHistoryPolicyId = Literal[
    "hwe_action_preserving_observation_masking_v1",
    "hwe_action_preserving_observation_masking_v1/lossless_under_32k",
]
HweMarkerRuleId = Literal[
    "hwe_action_preserving_observation_masking_v1/hash_marker_v1",
    "hwe_action_preserving_observation_masking_v1/lossless_under_32k/no_markers",
]

_HASH = re.compile(r"[0-9a-f]{64}")


def _sha256(value: str) -> str:
    if not _HASH.fullmatch(value):
        raise ValueError("HWE identity must be lowercase SHA-256")
    return value


class HweMaskedHistoryLedger(StrictModel):
    schema_version: str = SCHEMA_VERSION
    policy_id: HweHistoryPolicyId
    policy_hash: str
    marker_rule_id: HweMarkerRuleId
    recent_observations: HweWindow
    max_pinned_observations: HwePinnedLimit
    target_sequence: int = Field(ge=0)
    target_action: HweAction
    target_message_index: int = Field(ge=2)
    workspace_epoch: int = Field(ge=0)
    source_history_sha256: str
    masked_history_sha256: str
    target_action_sha256: str
    source_history_tokens: int = Field(ge=1)
    input_tokens: int = Field(ge=1, le=32_768)
    target_tokens: int = Field(ge=1, le=32_768)
    total_tokens: int = Field(ge=1, le=32_768)
    retained_observation_sequences: list[int]
    recent_observation_sequences: list[int]
    pinned_observation_sequences: list[int]
    masked_observation_sequences: list[int]
    masked_source_observation_tokens: int = Field(ge=0)
    mask_marker_tokens: int = Field(ge=0)
    all_prior_actions_preserved: Literal[True]
    target_action_preserved: Literal[True]
    structural_causal_validation: Literal["passed"]
    counterfactual_next_action_validation: Literal["not_run"]
    ledger_hash: str

    @field_validator(
        "policy_hash",
        "source_history_sha256",
        "masked_history_sha256",
        "target_action_sha256",
        "ledger_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator(
        "retained_observation_sequences",
        "recent_observation_sequences",
        "pinned_observation_sequences",
        "masked_observation_sequences",
    )
    @classmethod
    def validate_sequences(cls, values: list[int]) -> list[int]:
        if values != sorted(set(values)) or any(value < 0 for value in values):
            raise ValueError("HWE observation sequences must be sorted, unique, and non-negative")
        return values

    @model_validator(mode="after")
    def validate_ledger(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"ledger_hash"})
        if content_hash(identity) != self.ledger_hash:
            raise ValueError("HWE masked history ledger identity changed")
        retained = set(self.retained_observation_sequences)
        masked = set(self.masked_observation_sequences)
        if (
            retained & masked
            or retained | masked != set(range(self.target_sequence))
            or not set(self.recent_observation_sequences).issubset(retained)
            or not set(self.pinned_observation_sequences).issubset(retained)
            or len(self.pinned_observation_sequences) > self.max_pinned_observations
            or self.total_tokens < self.input_tokens
        ):
            raise ValueError("HWE masked history ledger sequence or token contract changed")
        return self


class HweActionConditionedSftExample(StrictModel):
    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_action_conditioned_sft_v1"]
    record_id: str
    trajectory_sample_id: str
    task_id: str
    task_hash: str
    source_hash: str
    candidate_hash: str
    verifier_hash: str
    source_transcript_hash: str
    source_sft_bucket: Literal["primary", "long_context_candidate", "audit"]
    source_primary_eligible: bool
    collection_profile_id: Literal["hwe_standard_v2"]
    observation_policy_id: Literal["hwe_repository_observation_v2"]
    tool_contract_id: Literal["hwe_native_shell_v2"]
    tool_contract_hash: str
    history_policy_id: HweHistoryPolicyId
    history_policy_hash: str
    tokenizer_id: Literal["tiktoken-0.7.0/o200k_base"]
    tokenizer_hash: str
    target_sequence: int = Field(ge=0)
    target_action: HweAction
    messages: list[dict[str, Any]] = Field(min_length=3)
    history_ledger: HweMaskedHistoryLedger
    input_token_count: int = Field(ge=1, le=32_768)
    target_token_count: int = Field(ge=1, le=32_768)
    token_count: int = Field(ge=1, le=32_768)
    max_length: Literal[32_768]
    truncation: Literal["error"]
    supervised_message_indices: list[int] = Field(min_length=1, max_length=1)
    prior_assistant_labels_masked: Literal[True]
    training_semantics: Literal["next_action_conditioned_on_exact_masked_history"]
    training_eligibility: Literal["experimental_action_conditioned"]
    primary_eligible: Literal[False]
    counterfactual_next_action_validation: Literal["not_run"]
    verifier_resolved: Literal[True]
    infrastructure_valid: Literal[True]
    raw_provider_events_exported: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    credential_values_exported: Literal[False]
    raw_host_paths_exported: Literal[False]
    record_hash: str

    @field_validator(
        "record_id",
        "trajectory_sample_id",
        "task_hash",
        "source_hash",
        "candidate_hash",
        "verifier_hash",
        "source_transcript_hash",
        "tool_contract_hash",
        "history_policy_hash",
        "tokenizer_hash",
        "record_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"record_hash"})
        if content_hash(identity) != self.record_hash:
            raise ValueError("HWE action-conditioned record identity changed")
        if (
            self.target_sequence != self.history_ledger.target_sequence
            or self.target_action != self.history_ledger.target_action
            or self.history_policy_hash != self.history_ledger.policy_hash
            or self.input_token_count != self.history_ledger.input_tokens
            or self.target_token_count != self.history_ledger.target_tokens
            or self.token_count != self.history_ledger.total_tokens
            or self.supervised_message_indices != [len(self.messages) - 1]
        ):
            raise ValueError("HWE action-conditioned record layers disagree")
        return self


class HweActionConditionedSftDatasetManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_action_conditioned_sft_dataset_v1"]
    record_count: int = Field(ge=1)
    trajectory_count: int = Field(ge=1)
    task_ids: list[str] = Field(min_length=1)
    source_transcript_hashes: list[str] = Field(min_length=1)
    record_hashes: list[str] = Field(min_length=1)
    history_policy_id: Literal[
        "hwe_action_preserving_observation_masking_v1",
        "hwe_action_preserving_observation_masking_v1/lossless_under_32k",
        "mixed",
    ]
    history_policy_hash: str
    max_length: Literal[32_768]
    truncation: Literal["error"]
    training_semantics: Literal["next_action_conditioned_on_exact_masked_history"]
    primary_eligible: Literal[False]
    experimental_action_conditioned: Literal[True]
    counterfactual_next_action_validation: Literal["not_run"]
    only_verifier_resolved: Literal[True]
    only_infrastructure_valid: Literal[True]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    hpc_jobs_submitted: Literal[False]
    dataset_hash: str

    @field_validator("history_policy_hash", "dataset_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator("source_transcript_hashes", "record_hashes")
    @classmethod
    def validate_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"dataset_hash"})
        if content_hash(identity) != self.dataset_hash:
            raise ValueError("HWE action-conditioned dataset identity changed")
        if (
            self.record_count != len(self.record_hashes)
            or self.trajectory_count != len(self.task_ids)
            or self.trajectory_count != len(self.source_transcript_hashes)
            or self.task_ids != sorted(set(self.task_ids))
            or self.source_transcript_hashes != sorted(set(self.source_transcript_hashes))
            or len(self.record_hashes) != len(set(self.record_hashes))
        ):
            raise ValueError("HWE action-conditioned dataset counts or identities disagree")
        return self


class HweMaskingWindowAnalysis(StrictModel):
    recent_observations: HweWindow
    history_policy_hash: str
    action_record_count: int = Field(ge=1)
    max_source_history_tokens: int = Field(ge=1)
    max_input_tokens: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    p50_total_tokens: int = Field(ge=1)
    p95_total_tokens: int = Field(ge=1)
    all_within_32k: bool
    max_masked_observations: int = Field(ge=0)
    max_retained_observations: int = Field(ge=0)
    max_pinned_observations: int = Field(ge=0, le=4)
    total_masked_source_observation_tokens: int = Field(ge=0)
    total_mask_marker_tokens: int = Field(ge=0)
    structural_action_preservation: Literal["passed"]
    counterfactual_next_action_validation: Literal["not_run"]

    @field_validator("history_policy_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)


class HweMaskingTrajectoryAnalysis(StrictModel):
    task_id: str
    source_transcript_hash: str
    source_sft_tokens: int = Field(ge=1)
    source_sft_bucket: Literal["primary", "long_context_candidate", "audit"]
    source_primary_eligible: bool
    window_analyses: list[HweMaskingWindowAnalysis] = Field(min_length=1)

    @field_validator("source_transcript_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)


class HweMaskingWindowSummary(StrictModel):
    recent_observations: HweWindow
    history_policy_hash: str
    max_input_tokens: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    all_trajectories_within_32k: bool
    trajectory_count: int = Field(ge=1)

    @field_validator("history_policy_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)


class HweObservationMaskingAnalysis(StrictModel):
    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_observation_masking_analysis_v1"]
    analysis_scope: Literal["sealed_successful_hwe_pilot_transcripts"]
    trajectory_count: int = Field(ge=1)
    tested_windows: list[HweWindow] = Field(min_length=1)
    selection_rule: Literal["largest_tested_window_with_all_target_contexts_at_or_below_32768"]
    selected_window: HweWindow | None
    tokenizer_id: Literal["tiktoken-0.7.0/o200k_base"]
    tokenizer_hash: str
    trajectories: list[HweMaskingTrajectoryAnalysis] = Field(min_length=1)
    summary_by_window: list[HweMaskingWindowSummary] = Field(min_length=1)
    structural_action_preservation: Literal["passed"]
    counterfactual_next_action_validation: Literal["not_run"]
    live_rollout_masking_applied: Literal[False]
    derivation_only: Literal[True]
    source_transcripts_modified: Literal[False]
    existing_primary_reclassified: Literal[False]
    pilot_is_benchmark_score: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    hpc_jobs_submitted: Literal[False]
    analysis_hash: str

    @field_validator("tokenizer_hash", "analysis_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_analysis(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"analysis_hash"})
        if content_hash(identity) != self.analysis_hash:
            raise ValueError("HWE observation masking analysis identity changed")
        if (
            self.trajectory_count != len(self.trajectories)
            or len(self.tested_windows) != len(set(self.tested_windows))
            or [item.recent_observations for item in self.summary_by_window] != self.tested_windows
            or any(
                item.trajectory_count != self.trajectory_count for item in self.summary_by_window
            )
        ):
            raise ValueError("HWE observation masking analysis counts disagree")
        return self


class HweDeepSeekHarnessActionSftExample(StrictModel):
    """One untruncated, final-action-only row derived from exact Harness context."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_deepseek_harness_action_sft_v1"]
    sample_id: str
    task_id: str
    task_hash: str
    source_hash: str
    candidate_hash: str
    verifier_hash: str
    transcript_hash: str
    action_index: int = Field(ge=0)
    call_id: str
    tools: list[dict[str, Any]] = Field(min_length=6, max_length=6)
    input_messages: list[dict[str, Any]] = Field(min_length=2)
    target_message: dict[str, Any]
    tokenizer_id: Literal["Qwen3.5-9B/local-frozen-chat-template"]
    tokenizer_hash: str
    chat_template_hash: str
    input_tokens: int = Field(ge=1)
    target_tokens: int = Field(ge=1)
    token_count: int = Field(ge=1)
    max_length: Literal[32_768]
    truncation: Literal["error"]
    eligible: bool
    supervised_roles: list[Literal["assistant"]] = Field(min_length=1, max_length=1)
    masked_roles: list[Literal["system", "user", "tool"]] = Field(min_length=3, max_length=3)
    exact_model_visible_context: Literal[True]
    context_transformed_after_collection: Literal[False]
    nap_required: Literal[False]
    verifier_resolved: Literal[True]
    infrastructure_valid: Literal[True]
    raw_provider_events_exported: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    credential_values_exported: Literal[False]
    raw_host_paths_exported: Literal[False]
    record_hash: str

    @field_validator(
        "sample_id",
        "task_hash",
        "source_hash",
        "candidate_hash",
        "verifier_hash",
        "transcript_hash",
        "tokenizer_hash",
        "chat_template_hash",
        "record_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"record_hash"})
        if content_hash(identity) != self.record_hash:
            raise ValueError("DeepSeek Harness action record identity changed")
        if (
            self.token_count != self.input_tokens + self.target_tokens
            or self.eligible != (self.token_count <= self.max_length)
            or [item.get("role") for item in self.input_messages[:2]] != ["system", "user"]
            or self.target_message.get("role") != "assistant"
            or self.target_message.get("content") not in {None, ""}
            or self.supervised_roles != ["assistant"]
            or self.masked_roles != ["system", "user", "tool"]
            or len(self.input_messages) != 2 + 2 * self.action_index
        ):
            raise ValueError("DeepSeek Harness action record structure or token counts changed")
        tool_names = tuple(item.get("function", {}).get("name") for item in self.tools)
        if tool_names != (
            "apply_patch",
            "finish",
            "inspect_diff",
            "list_files",
            "read_file",
            "shell",
        ):
            raise ValueError("DeepSeek Harness action record tool contract changed")
        if [item.get("role") for item in self.input_messages[2:]] != [
            role for _ in range(self.action_index) for role in ("assistant", "tool")
        ]:
            raise ValueError("DeepSeek Harness action record causal roles changed")
        target_calls = self.target_message.get("tool_calls")
        if (
            not isinstance(target_calls, list)
            or len(target_calls) != 1
            or target_calls[0].get("id") != self.call_id
        ):
            raise ValueError("DeepSeek Harness action record call identity changed")
        return self


class HweDeepSeekHarnessActionSftDatasetManifest(StrictModel):
    """Pilot-only dataset receipt; this schema can never assert production readiness."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_deepseek_harness_action_sft_dataset_v1"]
    record_count: int = Field(ge=0)
    record_hashes: list[str]
    pilot_task_ids: list[str] = Field(min_length=3, max_length=3)
    represented_task_ids: list[str]
    trajectory_count: int = Field(ge=0, le=3)
    max_length: Literal[32_768]
    truncation: Literal["error"]
    overlength_records: list[dict[str, Any]]
    loader_ready: bool
    production_training_ready: Literal[False]
    training_started: Literal[False]
    hpc_jobs_submitted: Literal[False]
    gpu_hours: Literal[0]
    raw_provider_events_exported: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    credential_values_exported: Literal[False]
    raw_host_paths_exported: Literal[False]
    dataset_hash: str

    @field_validator("dataset_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator("record_hashes")
    @classmethod
    def validate_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"dataset_hash"})
        if content_hash(identity) != self.dataset_hash:
            raise ValueError("DeepSeek Harness dataset identity changed")
        if (
            self.record_count != len(self.record_hashes)
            or len(self.record_hashes) != len(set(self.record_hashes))
            or self.pilot_task_ids != sorted(set(self.pilot_task_ids))
            or self.pilot_task_ids
            != [
                "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
                "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
                "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
            ]
            or self.represented_task_ids != sorted(set(self.represented_task_ids))
            or self.trajectory_count != len(self.represented_task_ids)
            or not set(self.represented_task_ids).issubset(self.pilot_task_ids)
            or self.loader_ready != (self.record_count > 0 and not self.overlength_records)
        ):
            raise ValueError("DeepSeek Harness dataset counts or gate changed")
        return self


class HweDeepSeekHarnessDecisionSftExampleV3(StrictModel):
    """One exact-context public assistant decision from the native Harness v3 route."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_deepseek_harness_decision_sft_v3"]
    sample_id: str
    task_id: str
    task_hash: str
    source_hash: str
    candidate_hash: str
    verifier_hash: str
    transcript_hash: str
    decision_index: int = Field(ge=0)
    target_message_index: int = Field(ge=2)
    call_ids: list[str] = Field(min_length=1)
    action_names: list[HweAction] = Field(min_length=1)
    tool_action_count: int = Field(ge=1)
    trajectory_assistant_decision_count: int = Field(ge=1)
    trajectory_accepted_tool_action_count: int = Field(ge=1)
    trajectory_masked_policy_error_decision_count: int = Field(ge=0)
    trajectory_masked_format_error_decision_count: int = Field(ge=0)
    trajectory_format_repair_count: int = Field(ge=0, le=1)
    tools: list[dict[str, Any]] = Field(min_length=6, max_length=6)
    input_messages: list[dict[str, Any]] = Field(min_length=2)
    target_message: dict[str, Any]
    tokenizer_id: Literal["Qwen3.5-9B/local-frozen-chat-template"]
    tokenizer_hash: str
    chat_template_hash: str
    input_tokens: int = Field(ge=1)
    target_tokens: int = Field(ge=1)
    token_count: int = Field(ge=1)
    max_length: Literal[32_768]
    truncation: Literal["error"]
    eligible: bool
    supervised_target_kind: Literal["complete_assistant_decision"]
    supervised_roles: list[Literal["assistant"]] = Field(min_length=1, max_length=1)
    input_loss_masked: Literal[True]
    failed_tool_decisions_loss_masked: Literal[True]
    format_error_decisions_loss_masked: Literal[True]
    exact_model_visible_context: Literal[True]
    context_transformed_after_collection: Literal[False]
    nap_required: Literal[False]
    verifier_resolved: Literal[True]
    infrastructure_valid: Literal[True]
    public_assistant_text_exported: bool
    raw_provider_events_exported: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    credential_values_exported: Literal[False]
    raw_host_paths_exported: Literal[False]
    record_hash: str

    @field_validator(
        "sample_id",
        "task_hash",
        "source_hash",
        "candidate_hash",
        "verifier_hash",
        "transcript_hash",
        "tokenizer_hash",
        "chat_template_hash",
        "record_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"record_hash"})
        calls = self.target_message.get("tool_calls")
        if (
            content_hash(identity) != self.record_hash
            or self.token_count != self.input_tokens + self.target_tokens
            or self.eligible != (self.token_count <= self.max_length)
            or [item.get("role") for item in self.input_messages[:2]] != ["system", "user"]
            or self.target_message.get("role") != "assistant"
            or self.target_message_index != len(self.input_messages)
            or self.tool_action_count != len(self.call_ids)
            or self.tool_action_count != len(self.action_names)
            or not isinstance(calls, list)
            or len(calls) != self.tool_action_count
            or [item.get("id") for item in calls] != self.call_ids
            or [item.get("function", {}).get("name") for item in calls] != self.action_names
            or self.supervised_roles != ["assistant"]
            or self.decision_index >= self.trajectory_assistant_decision_count
            or self.trajectory_accepted_tool_action_count < self.tool_action_count
        ):
            raise ValueError("DeepSeek Harness v3 decision structure or token counts changed")
        content = self.target_message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("DeepSeek Harness v3 public assistant text is malformed")
        if self.public_assistant_text_exported != bool(content):
            raise ValueError("DeepSeek Harness v3 public text receipt changed")
        tool_names = tuple(item.get("function", {}).get("name") for item in self.tools)
        if tool_names != (
            "apply_patch",
            "finish",
            "inspect_diff",
            "list_files",
            "read_file",
            "shell",
        ):
            raise ValueError("DeepSeek Harness v3 tool contract changed")
        return self


class HweDeepSeekHarnessDecisionSftDatasetManifestV3(StrictModel):
    """Pilot-only v3 decision dataset receipt; never a production-readiness claim."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_deepseek_harness_decision_sft_dataset_v3"]
    record_count: int = Field(ge=0)
    record_hashes: list[str]
    pilot_task_ids: list[str] = Field(min_length=3, max_length=3)
    represented_task_ids: list[str]
    trajectory_count: int = Field(ge=0, le=3)
    supervised_decision_count: int = Field(ge=0)
    supervised_tool_action_count: int = Field(ge=0)
    masked_policy_error_decision_count: int = Field(ge=0)
    masked_format_error_decision_count: int = Field(ge=0)
    format_repair_count: int = Field(ge=0, le=3)
    max_length: Literal[32_768]
    truncation: Literal["error"]
    overlength_records: list[dict[str, Any]]
    loader_ready: bool
    production_training_ready: Literal[False]
    training_started: Literal[False]
    hpc_jobs_submitted: Literal[False]
    gpu_hours: Literal[0]
    raw_provider_events_exported: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    credential_values_exported: Literal[False]
    raw_host_paths_exported: Literal[False]
    dataset_hash: str

    @field_validator("dataset_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator("record_hashes")
    @classmethod
    def validate_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"dataset_hash"})
        frozen_tasks = [
            "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
            "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
            "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
        ]
        if (
            content_hash(identity) != self.dataset_hash
            or self.record_count != len(self.record_hashes)
            or self.record_count != self.supervised_decision_count
            or len(self.record_hashes) != len(set(self.record_hashes))
            or self.pilot_task_ids != frozen_tasks
            or self.represented_task_ids != sorted(set(self.represented_task_ids))
            or self.trajectory_count != len(self.represented_task_ids)
            or not set(self.represented_task_ids).issubset(self.pilot_task_ids)
            or self.loader_ready != (self.record_count > 0 and not self.overlength_records)
        ):
            raise ValueError("DeepSeek Harness v3 dataset counts or gate changed")
        return self


class HweDeepSeekHarnessDecisionSftExampleV4(StrictModel):
    """One hash-bound 64K derivation of an unchanged native Harness v3 decision."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_deepseek_harness_decision_sft_64k_v4"]
    source_v3_format_id: Literal["verigym_hwe_deepseek_harness_decision_sft_v3"]
    source_v3_dataset_hash: Literal[
        "b362cc1df0969f1bad368c939110175502d8ff0d97aef62c93cccd18871e351a"
    ]
    source_v3_record_index: int = Field(ge=0, lt=83)
    source_v3_record_hash: str
    sample_id: str
    task_id: str
    task_hash: str
    source_hash: str
    candidate_hash: str
    verifier_hash: str
    transcript_hash: str
    decision_index: int = Field(ge=0)
    target_message_index: int = Field(ge=2)
    call_ids: list[str] = Field(min_length=1)
    action_names: list[HweAction] = Field(min_length=1)
    tool_action_count: int = Field(ge=1)
    trajectory_assistant_decision_count: int = Field(ge=1)
    trajectory_accepted_tool_action_count: int = Field(ge=1)
    trajectory_masked_policy_error_decision_count: int = Field(ge=0)
    trajectory_masked_format_error_decision_count: int = Field(ge=0)
    trajectory_format_repair_count: int = Field(ge=0, le=1)
    tools: list[dict[str, Any]] = Field(min_length=6, max_length=6)
    tool_schema_hash: str
    input_messages: list[dict[str, Any]] = Field(min_length=2)
    target_message: dict[str, Any]
    tokenizer_id: Literal["Qwen3.5-9B/local-frozen-chat-template"]
    tokenizer_hash: str
    chat_template_hash: str
    input_tokens: int = Field(ge=1)
    target_tokens: int = Field(ge=1)
    token_count: int = Field(ge=1, le=65_536)
    input_ids_sha256: str
    loss_mask_sha256: str
    input_ids_hash_format: Literal["sha256_u32be_v1"]
    loss_mask_hash_format: Literal["sha256_bytes_v1"]
    max_length: Literal[65_536]
    truncation: Literal["error"]
    eligible: Literal[True]
    supervised_target_kind: Literal["complete_assistant_decision"]
    supervised_roles: list[Literal["assistant"]] = Field(min_length=1, max_length=1)
    input_loss_masked: Literal[True]
    failed_tool_decisions_loss_masked: Literal[True]
    format_error_decisions_loss_masked: Literal[True]
    exact_model_visible_context: Literal[True]
    context_transformed_after_collection: Literal[False]
    nap_required: Literal[False]
    verifier_resolved: Literal[True]
    infrastructure_valid: Literal[True]
    public_assistant_text_exported: bool
    raw_provider_events_exported: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    credential_values_exported: Literal[False]
    raw_host_paths_exported: Literal[False]
    record_hash: str

    @field_validator(
        "source_v3_record_hash",
        "sample_id",
        "task_hash",
        "source_hash",
        "candidate_hash",
        "verifier_hash",
        "transcript_hash",
        "tool_schema_hash",
        "tokenizer_hash",
        "chat_template_hash",
        "input_ids_sha256",
        "loss_mask_sha256",
        "record_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"record_hash"})
        calls = self.target_message.get("tool_calls")
        content = self.target_message.get("content")
        if (
            content_hash(identity) != self.record_hash
            or self.token_count != self.input_tokens + self.target_tokens
            or [item.get("role") for item in self.input_messages[:2]] != ["system", "user"]
            or self.target_message.get("role") != "assistant"
            or self.target_message_index != len(self.input_messages)
            or self.tool_action_count != len(self.call_ids)
            or self.tool_action_count != len(self.action_names)
            or not isinstance(calls, list)
            or len(calls) != self.tool_action_count
            or [item.get("id") for item in calls] != self.call_ids
            or [item.get("function", {}).get("name") for item in calls] != self.action_names
            or self.supervised_roles != ["assistant"]
            or self.decision_index >= self.trajectory_assistant_decision_count
            or self.trajectory_accepted_tool_action_count < self.tool_action_count
            or self.public_assistant_text_exported != bool(content)
            or content is not None
            and not isinstance(content, str)
            or self.tool_schema_hash != content_hash(self.tools)
        ):
            raise ValueError("DeepSeek Harness v4 decision structure or exact receipt changed")
        tool_names = tuple(item.get("function", {}).get("name") for item in self.tools)
        if tool_names != (
            "apply_patch",
            "finish",
            "inspect_diff",
            "list_files",
            "read_file",
            "shell",
        ):
            raise ValueError("DeepSeek Harness v4 tool contract changed")
        return self


class HweDeepSeekHarnessDecisionSftDatasetManifestV4(StrictModel):
    """Exact-token 64K loader dataset derived without changing the frozen v3 pilot."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_deepseek_harness_decision_sft_dataset_64k_v4"]
    source_v3_format_id: Literal["verigym_hwe_deepseek_harness_decision_sft_dataset_v3"]
    source_v3_dataset_hash: Literal[
        "b362cc1df0969f1bad368c939110175502d8ff0d97aef62c93cccd18871e351a"
    ]
    source_v3_manifest_sha256: Literal[
        "a2605512edac128e66ac0afdf07a9245098f0bdd3b07ca485defc484b3b01c46"
    ]
    source_v3_train_jsonl_sha256: Literal[
        "1b7522c3bae396aeed4464486a3c8ba60b9b4f3fde8defa2d4903ff852618cec"
    ]
    source_v3_record_hashes: list[str] = Field(min_length=83, max_length=83)
    record_count: Literal[83]
    record_hashes: list[str] = Field(min_length=83, max_length=83)
    pilot_task_ids: list[str] = Field(min_length=3, max_length=3)
    represented_task_ids: list[str] = Field(min_length=2, max_length=2)
    trajectory_count: Literal[2]
    supervised_decision_count: Literal[83]
    supervised_tool_action_count: Literal[85]
    masked_policy_error_decision_count: Literal[0]
    masked_format_error_decision_count: Literal[1]
    format_repair_count: Literal[1]
    max_observed_token_count: Literal[50_117]
    max_length: Literal[65_536]
    truncation: Literal["error"]
    overlength_records: list[dict[str, Any]] = Field(max_length=0)
    exact_token_receipts: Literal[True]
    loader_ready: Literal[True]
    nap_required: Literal[False]
    production_training_ready: Literal[False]
    training_started: Literal[False]
    hpc_jobs_submitted: Literal[False]
    gpu_hours: Literal[0]
    raw_provider_events_exported: Literal[False]
    raw_observations_exported: Literal[False]
    private_reasoning_exported: Literal[False]
    hidden_assets_exported: Literal[False]
    reference_solutions_exported: Literal[False]
    credential_values_exported: Literal[False]
    raw_host_paths_exported: Literal[False]
    dataset_hash: str

    @field_validator("dataset_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator("source_v3_record_hashes", "record_hashes")
    @classmethod
    def validate_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"dataset_hash"})
        frozen_tasks = [
            "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
            "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
            "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
        ]
        if (
            content_hash(identity) != self.dataset_hash
            or len(set(self.source_v3_record_hashes)) != self.record_count
            or len(set(self.record_hashes)) != self.record_count
            or self.pilot_task_ids != frozen_tasks
            or self.represented_task_ids
            != [
                "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
                "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
            ]
        ):
            raise ValueError("DeepSeek Harness v4 dataset binding or counts changed")
        return self


__all__ = [
    "HweActionConditionedSftDatasetManifest",
    "HweActionConditionedSftExample",
    "HweDeepSeekHarnessActionSftDatasetManifest",
    "HweDeepSeekHarnessActionSftExample",
    "HweDeepSeekHarnessDecisionSftDatasetManifestV3",
    "HweDeepSeekHarnessDecisionSftDatasetManifestV4",
    "HweDeepSeekHarnessDecisionSftExampleV3",
    "HweDeepSeekHarnessDecisionSftExampleV4",
    "HweMaskedHistoryLedger",
    "HweMaskingTrajectoryAnalysis",
    "HweMaskingWindowAnalysis",
    "HweMaskingWindowSummary",
    "HweObservationMaskingAnalysis",
]
