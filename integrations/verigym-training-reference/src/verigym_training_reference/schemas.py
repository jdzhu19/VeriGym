"""Strict artifacts owned by the external training reference integration."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator
from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.evolution import RewardVector
from verigym.schemas.options import JsonValue

_HASH = re.compile(r"^[0-9a-f]{64}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_PORTABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_CONFIGURATION_KEY = re.compile(
    r"(?:token|key|secret|password|credential|authorization|cookie|proxy)",
    re.IGNORECASE,
)


def _hash(value: str) -> str:
    if not _HASH.fullmatch(value):
        raise ValueError("identity fields must be lowercase SHA-256 values")
    return value


def _safe_text(value: str) -> str:
    if not value or value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError("identity text must be non-empty printable text")
    return value


def _configuration_entries(value: JsonValue, prefix: str = "") -> list[tuple[str, JsonValue]]:
    entries: list[tuple[str, JsonValue]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            nested = f"{prefix}.{key}" if prefix else key
            entries.append((nested, item))
            entries.extend(_configuration_entries(item, nested))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            entries.extend(_configuration_entries(item, f"{prefix}[{index}]"))
    return entries


class TrainingReferenceConfig(StrictModel):
    """Trainer-owned configuration without paths or credential values."""

    schema_version: str = SCHEMA_VERSION
    framework: Literal["trl", "verl", "openrlhf", "custom"]
    algorithm: Literal["sft", "dpo", "grpo", "ppo", "custom"]
    model_id: str
    model_root_env: str = "VERIGYM_TRAINING_MODEL_ROOT"
    trainer_output_root_env: str = "VERIGYM_TRAINING_OUTPUT_ROOT"
    adapter_type: Literal["full", "lora", "qlora"] = "lora"
    reward_profile_id: Literal["repo_rtl_sparse_v1"] = "repo_rtl_sparse_v1"
    hyperparameters: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        value = _safe_text(value)
        if len(value) > 256 or "\\" in value or value.startswith("/"):
            raise ValueError("model_id must be a portable model identity, not a host path")
        return value

    @field_validator("model_root_env", "trainer_output_root_env")
    @classmethod
    def validate_environment_name(cls, value: str) -> str:
        if not _ENV_NAME.fullmatch(value):
            raise ValueError("environment variable names must use upper snake case")
        return value

    @model_validator(mode="after")
    def configuration_is_secret_free(self) -> TrainingReferenceConfig:
        forbidden = sorted(
            key for key in self.hyperparameters if _FORBIDDEN_CONFIGURATION_KEY.search(key)
        )
        if forbidden:
            raise ValueError("trainer hyperparameters contain credential-like keys")
        return self


class ModelSnapshotIdentity(StrictModel):
    """Metadata-bound local model identity; weight contents are deliberately not copied."""

    schema_version: str = SCHEMA_VERSION
    model_id: str
    architectures: list[str] = Field(min_length=1)
    model_type: str
    transformers_version: str | None = None
    metadata_file_hashes: dict[str, str]
    weight_files: dict[str, int]
    declared_weight_bytes: int | None = Field(default=None, ge=0)
    actual_weight_bytes: int = Field(ge=1)
    weights_content_hashed: Literal[False] = False
    raw_host_path_exported: Literal[False] = False
    snapshot_hash: str

    @field_validator("model_id", "model_type")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("metadata_file_hashes")
    @classmethod
    def validate_metadata_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: _hash(value) for key, value in sorted(values.items())}

    @field_validator("snapshot_hash")
    @classmethod
    def validate_snapshot_hash(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def model_files_are_canonical(self) -> ModelSnapshotIdentity:
        if list(self.weight_files) != sorted(self.weight_files):
            raise ValueError("model weight files must be sorted")
        if any("/" in name or "\\" in name or name in {".", ".."} for name in self.weight_files):
            raise ValueError("model weight identities must be basenames")
        if any(size <= 0 for size in self.weight_files.values()):
            raise ValueError("model weight files must be non-empty")
        if self.actual_weight_bytes != sum(self.weight_files.values()):
            raise ValueError("model weight byte count differs from the file inventory")
        return self


class TrainingReferenceBundleManifest(StrictModel):
    """Immutable handoff from VeriGym artifacts to an external trainer."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_external_training_reference_v1"] = (
        "verigym_external_training_reference_v1"
    )
    trajectory_dataset_hash: str
    split_manifest_hash: str
    trainer_export_manifest_hash: str
    trainer_config_hash: str
    trainer_identity_hash: str
    model_snapshot: ModelSnapshotIdentity
    record_count: int = Field(ge=1)
    trajectory_hashes: list[str] = Field(min_length=1)
    reward_hashes: list[str] = Field(min_length=1)
    training_task_ids: list[str] = Field(min_length=1)
    excluded_records: dict[str, str]
    file_hashes: dict[str, str]
    only_training_split: Literal[True] = True
    infrastructure_invalid_excluded: Literal[True] = True
    hidden_assets_exported: Literal[False] = False
    reference_solutions_exported: Literal[False] = False
    private_reasoning_exported: Literal[False] = False
    credential_values_exported: Literal[False] = False
    raw_host_paths_exported: Literal[False] = False
    manifest_hash: str

    @field_validator(
        "trajectory_dataset_hash",
        "split_manifest_hash",
        "trainer_export_manifest_hash",
        "trainer_config_hash",
        "trainer_identity_hash",
        "manifest_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @field_validator("trajectory_hashes", "reward_hashes")
    @classmethod
    def validate_hash_lists(cls, values: list[str]) -> list[str]:
        return [_hash(value) for value in values]

    @field_validator("file_hashes")
    @classmethod
    def validate_file_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: _hash(value) for key, value in sorted(values.items())}

    @model_validator(mode="after")
    def records_are_canonical(self) -> TrainingReferenceBundleManifest:
        if len(self.trajectory_hashes) != self.record_count:
            raise ValueError("trajectory count differs from record_count")
        if len(self.reward_hashes) != self.record_count:
            raise ValueError("reward count differs from record_count")
        if self.training_task_ids != sorted(set(self.training_task_ids)):
            raise ValueError("training task IDs must be sorted and unique")
        return self


class OnlineRewardResult(StrictModel):
    """Minimal trainer-visible result from one isolated VeriGym candidate evaluation."""

    schema_version: str = SCHEMA_VERSION
    interface_id: Literal["verigym_online_reward_oracle_v1"] = "verigym_online_reward_oracle_v1"
    run_id: str
    task_id: str
    candidate_hash: str
    outcome_kind: str
    reward: RewardVector
    reward_hash: str
    scalar_profile_id: Literal["repo_rtl_sparse_v1"] = "repo_rtl_sparse_v1"
    scalar_reward: float | None
    infrastructure_valid: bool
    hidden_assets_exported: Literal[False] = False
    reference_solution_exported: Literal[False] = False
    result_hash: str

    @field_validator("candidate_hash", "reward_hash", "result_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


class SftMessage(StrictModel):
    """One portable chat-template message."""

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class VerifiedSftExample(StrictModel):
    """Verifier-filtered solution-distillation example."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_verified_solution_sft_v1"] = "verigym_verified_solution_sft_v1"
    sample_id: str
    task_id: str
    official_task_id: str
    task_hash: str
    source_hash: str
    verifier_hash: str
    candidate_path: str
    candidate_sha256: str
    verigym_candidate_hash: str
    source_model_id: str
    source_reasoning_effort: Literal["xhigh", "max"]
    model_call_hash: str
    public_input_hash: str
    messages: list[SftMessage] = Field(min_length=2)
    verifier_resolved: Literal[True] = True
    infrastructure_valid: Literal[True] = True
    hidden_assets_exported: Literal[False] = False
    reference_solution_exported: Literal[False] = False
    private_reasoning_exported: Literal[False] = False
    example_hash: str

    @field_validator(
        "sample_id",
        "task_hash",
        "source_hash",
        "verifier_hash",
        "candidate_sha256",
        "verigym_candidate_hash",
        "model_call_hash",
        "public_input_hash",
        "example_hash",
    )
    @classmethod
    def validate_sft_hashes(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def messages_end_in_assistant(self) -> VerifiedSftExample:
        if self.messages[-1].role != "assistant":
            raise ValueError("SFT examples must end with an assistant message")
        if not any(message.role == "user" for message in self.messages[:-1]):
            raise ValueError("SFT examples require a user message")
        return self


class VerifiedSftDatasetManifest(StrictModel):
    """Sealed manifest for verifier-filtered solution SFT data."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_verified_solution_sft_dataset_v1"] = (
        "verigym_verified_solution_sft_dataset_v1"
    )
    record_count: int = Field(ge=1)
    task_ids: list[str] = Field(min_length=1)
    source_model_ids: list[str] = Field(min_length=1)
    source_reasoning_efforts: list[Literal["xhigh", "max"]] = Field(min_length=1)
    example_hashes: list[str] = Field(min_length=1)
    file_hashes: dict[str, str]
    only_resolved_samples: Literal[True] = True
    infrastructure_invalid_excluded: Literal[True] = True
    hidden_assets_exported: Literal[False] = False
    reference_solutions_exported: Literal[False] = False
    private_reasoning_exported: Literal[False] = False
    raw_host_paths_exported: Literal[False] = False
    credential_values_exported: Literal[False] = False
    manifest_hash: str

    @field_validator("example_hashes")
    @classmethod
    def validate_example_hashes(cls, values: list[str]) -> list[str]:
        return [_hash(value) for value in values]

    @field_validator("file_hashes")
    @classmethod
    def validate_sft_file_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: _hash(value) for key, value in sorted(values.items())}

    @field_validator("manifest_hash")
    @classmethod
    def validate_sft_manifest_hash(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def dataset_is_canonical(self) -> VerifiedSftDatasetManifest:
        if len(self.example_hashes) != self.record_count:
            raise ValueError("SFT example count differs from record_count")
        if self.task_ids != sorted(set(self.task_ids)):
            raise ValueError("SFT task IDs must be sorted and unique")
        if self.source_model_ids != sorted(set(self.source_model_ids)):
            raise ValueError("SFT source model IDs must be sorted and unique")
        if self.source_reasoning_efforts != sorted(set(self.source_reasoning_efforts)):
            raise ValueError("SFT reasoning efforts must be sorted and unique")
        return self


class TrainingPolicyVersionManifest(StrictModel):
    """Executable external-policy identity with exact training lineage."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_training_policy_version_v1"] = "verigym_training_policy_version_v1"
    policy_version_id: str
    weight_version: int | None = Field(default=None, ge=0)
    parent_version_hash: str | None = None
    update_type: Literal["base", "verified_sft", "verigym_grpo"]
    model_id: str
    base_model_snapshot_hash: str
    artifact_kind: Literal["model_snapshot", "lora_adapter"]
    artifact_hash: str
    training_data_hash: str | None = None
    reward_manifest_hash: str | None = None
    trainer_report_hash: str | None = None
    trainer_identity_hash: str | None = None
    source_commit: str
    framework_commits: dict[str, str] = Field(default_factory=dict)
    loading_configuration: dict[str, JsonValue]
    executable: Literal[True] = True
    hidden_assets_loaded: Literal[False] = False
    reference_solution_loaded: Literal[False] = False
    credential_values_included: Literal[False] = False
    raw_host_paths_included: Literal[False] = False
    version_hash: str

    @field_validator("policy_version_id")
    @classmethod
    def validate_policy_version_id(cls, value: str) -> str:
        if not _PORTABLE_ID.fullmatch(value):
            raise ValueError("policy version IDs must be short portable identifiers")
        return value

    @field_validator("model_id")
    @classmethod
    def validate_policy_model_id(cls, value: str) -> str:
        value = _safe_text(value)
        if len(value) > 256 or "\\" in value or value.startswith("/"):
            raise ValueError("model_id must be portable")
        return value

    @field_validator(
        "parent_version_hash",
        "base_model_snapshot_hash",
        "artifact_hash",
        "training_data_hash",
        "reward_manifest_hash",
        "trainer_report_hash",
        "trainer_identity_hash",
        "version_hash",
    )
    @classmethod
    def validate_policy_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @field_validator("source_commit")
    @classmethod
    def validate_source_commit(cls, value: str) -> str:
        if not _GIT_COMMIT.fullmatch(value):
            raise ValueError("source_commit must be a lowercase full Git commit")
        return value

    @field_validator("framework_commits")
    @classmethod
    def validate_framework_commits(cls, values: dict[str, str]) -> dict[str, str]:
        for name, value in values.items():
            if not _PORTABLE_ID.fullmatch(name) or not _GIT_COMMIT.fullmatch(value):
                raise ValueError("framework commits require portable names and full Git commits")
        return dict(sorted(values.items()))

    @model_validator(mode="after")
    def validate_policy_lineage(self) -> TrainingPolicyVersionManifest:
        entries = _configuration_entries(self.loading_configuration)
        forbidden = sorted(key for key, _ in entries if _FORBIDDEN_CONFIGURATION_KEY.search(key))
        if forbidden:
            raise ValueError("loading configuration contains credential-like keys")
        if any(
            isinstance(value, str) and (value.startswith(("/", "\\")) or ":\\" in value)
            for _, value in entries
        ):
            raise ValueError("loading configuration contains a raw host path")
        if self.update_type == "base":
            if (
                self.weight_version is not None
                or self.parent_version_hash is not None
                or self.artifact_kind != "model_snapshot"
                or any(
                    value is not None
                    for value in (
                        self.training_data_hash,
                        self.reward_manifest_hash,
                        self.trainer_report_hash,
                        self.trainer_identity_hash,
                    )
                )
            ):
                raise ValueError("base policy versions cannot contain training lineage")
        elif self.update_type == "verified_sft":
            if (
                self.weight_version != 0
                or self.parent_version_hash is None
                or self.artifact_kind != "lora_adapter"
                or self.training_data_hash is None
                or self.trainer_report_hash is None
                or self.trainer_identity_hash is None
                or self.reward_manifest_hash is not None
            ):
                raise ValueError("verified SFT versions require complete SFT lineage")
        elif (
            self.weight_version is None
            or self.parent_version_hash is None
            or self.artifact_kind != "lora_adapter"
            or self.training_data_hash is None
            or self.reward_manifest_hash is None
            or self.trainer_report_hash is None
            or self.trainer_identity_hash is None
        ):
            raise ValueError("GRPO versions require complete reward and trainer lineage")
        return self


__all__ = [
    "ModelSnapshotIdentity",
    "OnlineRewardResult",
    "SftMessage",
    "TrainingReferenceBundleManifest",
    "TrainingReferenceConfig",
    "TrainingPolicyVersionManifest",
    "VerifiedSftDatasetManifest",
    "VerifiedSftExample",
]
