"""Strict persistent schemas for Milestone 9 experiments."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from verigym.profiles.base import ResolvedToolchainProfile
from verigym.schemas.agent import AgentDescriptor
from verigym.schemas.base import StrictModel
from verigym.schemas.common import (
    InteractionMode,
    ModelDescriptor,
    RuntimeDescriptor,
    ToolchainProfileRef,
)
from verigym.schemas.model import GenerationParameters, ModelRunConfig
from verigym.schemas.options import JsonValue, validate_plugin_options
from verigym.schemas.prompt import PromptPolicyDescriptor, ToolPolicySnapshot
from verigym.schemas.provenance import BuildProvenance
from verigym.schemas.repository import RepositoryPlanIdentity
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.task import BudgetSpec

_SYSTEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_SEED = 2**63 - 1
_MAX_SAMPLES = 1024
_MAX_WORKERS = 32
DEFAULT_MAX_PLAN_ITEMS = 10_000
HARD_MAX_PLAN_ITEMS = 100_000


class TaskSelection(StrictModel):
    include: list[str] = Field(default_factory=lambda: ["*"])
    exclude: list[str] = Field(default_factory=list)

    @field_validator("include", "exclude")
    @classmethod
    def validate_patterns(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("task-selection patterns must not be duplicated")
        for value in values:
            if not value or value != value.strip() or "\x00" in value:
                raise ValueError("task-selection patterns must be nonempty trimmed strings")
            if any(ord(character) < 32 for character in value):
                raise ValueError("task-selection patterns cannot contain control characters")
        return sorted(values)

    @model_validator(mode="after")
    def require_include(self) -> TaskSelection:
        if not self.include:
            raise ValueError("task selection requires at least one include entry")
        return self


class ExperimentSuiteConfig(StrictModel):
    id: str
    source: Path | None = None
    variant: str | None = None
    strict_compatibility: bool = True
    tasks: TaskSelection = Field(default_factory=TaskSelection)

    @model_validator(mode="after")
    def validate_source_variant(self) -> ExperimentSuiteConfig:
        if self.variant is not None and self.source is None:
            raise ValueError("a suite variant requires an explicit external source")
        return self


class ExperimentRunsConfig(StrictModel):
    mode: InteractionMode = InteractionMode.AGENT
    seeds: list[int] = Field(default_factory=lambda: [0], min_length=1)
    samples_per_task: int = Field(default=1, ge=1, le=_MAX_SAMPLES)
    pass_k: list[int] = Field(default_factory=lambda: [1], min_length=1)

    @field_validator("seeds")
    @classmethod
    def validate_seeds(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("base seeds must not be duplicated")
        if any(value < 0 or value > _MAX_SEED for value in values):
            raise ValueError(f"base seeds must be between 0 and {_MAX_SEED}")
        return sorted(values)

    @field_validator("pass_k")
    @classmethod
    def validate_pass_k_values(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("pass@k values must not be duplicated")
        if any(value < 1 for value in values):
            raise ValueError("pass@k values must be positive")
        return sorted(values)

    @model_validator(mode="after")
    def validate_k_bound(self) -> ExperimentRunsConfig:
        if any(value > self.samples_per_task for value in self.pass_k):
            raise ValueError("every pass@k value must be <= samples_per_task")
        return self


class ExperimentAgentConfig(StrictModel):
    id: str
    options: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("options", mode="before")
    @classmethod
    def validate_options(cls, value: object) -> dict[str, JsonValue]:
        return validate_plugin_options(value)


class ExperimentModelConfig(StrictModel):
    id: str
    options: ModelRunConfig = Field(default_factory=ModelRunConfig)

    @model_validator(mode="after")
    def sample_index_is_planner_owned(self) -> ExperimentModelConfig:
        if self.options.sample_index is not None:
            raise ValueError("model sample_index is assigned by the experiment planner")
        return self


class ExperimentSystemConfig(StrictModel):
    id: str
    agent: ExperimentAgentConfig
    model: ExperimentModelConfig | None = None
    max_invalid_actions: int = Field(default=3, ge=1, le=100)

    @field_validator("id")
    @classmethod
    def safe_system_id(cls, value: str) -> str:
        if not _SYSTEM_ID.fullmatch(value):
            raise ValueError("system IDs must be 1-64 characters from [A-Za-z0-9._-]")
        return value


class ExperimentRuntimeConfig(StrictModel):
    id: str = "local"
    docker: DockerRuntimeConfig | None = None

    @model_validator(mode="after")
    def validate_options(self) -> ExperimentRuntimeConfig:
        if self.id == "docker" and self.docker is None:
            raise ValueError("runtime 'docker' requires a docker configuration")
        if self.id != "docker" and self.docker is not None:
            raise ValueError("Docker options require runtime id 'docker'")
        return self


class ExperimentExecutionConfig(StrictModel):
    max_workers: int = Field(default=1, ge=1, le=_MAX_WORKERS)
    continue_on_infrastructure_error: bool = True
    max_plan_items: int = Field(
        default=DEFAULT_MAX_PLAN_ITEMS,
        ge=1,
        le=HARD_MAX_PLAN_ITEMS,
    )
    max_model_processes: int | None = Field(
        default=None,
        ge=1,
        le=HARD_MAX_PLAN_ITEMS,
    )
    resume_model_process_policy: Literal[
        "legacy_rerun_invalid",
        "never_rerun_after_authorization",
    ] = "legacy_rerun_invalid"
    max_consecutive_identical_shared_infrastructure_failures: int | None = Field(
        default=None,
        ge=1,
        le=HARD_MAX_PLAN_ITEMS,
    )
    max_total_infrastructure_failures: int | None = Field(
        default=None,
        ge=1,
        le=HARD_MAX_PLAN_ITEMS,
    )
    summary_checkpoint_interval: int | None = Field(
        default=None,
        ge=1,
        le=HARD_MAX_PLAN_ITEMS,
    )
    seal_plan_before_execution: bool = False
    plan_order_policy: Literal[
        "canonical",
        "counterbalanced_systems_v1",
    ] = "canonical"
    frozen_campaign_identity: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("frozen_campaign_identity", mode="before")
    @classmethod
    def validate_frozen_campaign_identity(
        cls,
        value: object,
    ) -> dict[str, JsonValue]:
        return validate_plugin_options(value)

    @model_validator(mode="after")
    def validate_scale_controls(self) -> ExperimentExecutionConfig:
        if (
            self.resume_model_process_policy == "never_rerun_after_authorization"
            and self.max_model_processes is None
        ):
            raise ValueError("strict model-process resume policy requires max_model_processes")
        if self.resume_model_process_policy == "never_rerun_after_authorization" and (
            not self.seal_plan_before_execution or not self.frozen_campaign_identity
        ):
            raise ValueError(
                "strict model-process resume requires plan sealing and frozen campaign identity"
            )
        if self.max_model_processes is not None and self.max_model_processes > self.max_plan_items:
            raise ValueError("max_model_processes cannot exceed max_plan_items")
        if (
            self.max_consecutive_identical_shared_infrastructure_failures is not None
            or self.max_total_infrastructure_failures is not None
        ) and self.max_workers != 1:
            raise ValueError("infrastructure circuit breakers require max_workers=1")
        return self


class ExperimentOutputConfig(StrictModel):
    root: Path

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: Path) -> Path:
        raw = value.as_posix()
        if not raw or any(ord(character) < 32 for character in raw) or ".." in value.parts:
            raise ValueError(
                "experiment output root must be a contained control-free path without '..'"
            )
        return value


class ExperimentConfig(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: str
    description: str | None = None
    suite: ExperimentSuiteConfig
    runs: ExperimentRunsConfig
    systems: list[ExperimentSystemConfig] = Field(min_length=1, max_length=128)
    runtime: ExperimentRuntimeConfig = Field(default_factory=ExperimentRuntimeConfig)
    profile: str | None = None
    execution: ExperimentExecutionConfig = Field(default_factory=ExperimentExecutionConfig)
    output: ExperimentOutputConfig

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value or value != value.strip() or len(value) > 128 or "\x00" in value:
            raise ValueError("experiment name must be a nonempty trimmed string up to 128 chars")
        if any(ord(character) < 32 for character in value):
            raise ValueError("experiment name cannot contain control characters")
        return value

    @model_validator(mode="after")
    def unique_systems(self) -> ExperimentConfig:
        ids = [system.id for system in self.systems]
        if len(ids) != len(set(ids)):
            raise ValueError("experiment system IDs must be unique")
        return self

    def identity_payload(self) -> dict[str, Any]:
        """Return a secret-free normalized config independent of its host output path."""

        payload = self.model_dump(mode="json")
        payload["systems"] = sorted(payload["systems"], key=lambda item: item["id"])
        payload["output"] = {"root": "."}
        # The original Milestone 9 hash contract had an implicit 10,000-item
        # bound. Omitting the additive default here preserves those hashes.
        if payload["execution"]["max_plan_items"] == DEFAULT_MAX_PLAN_ITEMS:
            del payload["execution"]["max_plan_items"]
        execution_defaults: dict[str, Any] = {
            "max_model_processes": None,
            "resume_model_process_policy": "legacy_rerun_invalid",
            "max_consecutive_identical_shared_infrastructure_failures": None,
            "max_total_infrastructure_failures": None,
            "summary_checkpoint_interval": None,
            "seal_plan_before_execution": False,
            "plan_order_policy": "canonical",
            "frozen_campaign_identity": {},
        }
        for key, default in execution_defaults.items():
            if payload["execution"].get(key) == default:
                payload["execution"].pop(key, None)
        for system in payload["systems"]:
            if not system["agent"].get("options"):
                system["agent"].pop("options", None)
            model = system.get("model")
            if model is not None and not model["options"].get("client_options"):
                model["options"].pop("client_options", None)
            if model is not None:
                for field, default in (
                    ("base_url_env", None),
                    ("provider_id", None),
                    ("max_response_bytes", 4 * 1024 * 1024),
                    ("require_exact_model_id", False),
                ):
                    if model["options"].get(field) == default:
                        model["options"].pop(field, None)
        return payload


class PlannedSystemIdentity(StrictModel):
    system_id: str
    agent_id: str
    agent_descriptor: AgentDescriptor
    agent_configuration_hash: str
    agent_options: dict[str, JsonValue] = Field(default_factory=dict)
    agent_requires_model: bool
    model_id: str | None = None
    model_descriptor: ModelDescriptor | None = None
    model_configuration_hash: str | None = None
    model_options: ModelRunConfig = Field(default_factory=ModelRunConfig)


class PlanItem(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_index: int = Field(ge=0)
    plan_item_id: str
    task_id: str
    task_hash: str
    source_hash: str
    source_identity_hash: str
    suite: str
    suite_version: str
    release_id: str | None = None
    suite_source: SuiteSourceConfig | None = None
    suite_source_snapshot: SuiteSourceSnapshot | None = None
    category: str | None = None
    difficulty: str | None = None
    interaction_mode: InteractionMode
    system: PlannedSystemIdentity
    prompt_policy: PromptPolicyDescriptor | None = None
    prompt_policy_hash: str | None = None
    tool_policy: ToolPolicySnapshot
    tool_policy_hash: str
    base_seed: int = Field(ge=0, le=_MAX_SEED)
    sample_index: int = Field(ge=0)
    child_seed: int = Field(ge=0, le=_MAX_SEED)
    runtime_id: str
    runtime_descriptor: RuntimeDescriptor
    runtime_identity_hash: str
    docker_config: DockerRuntimeConfig | None = None
    verifier_hash: str
    correctness_definition_hash: str
    budget: BudgetSpec
    generation: GenerationParameters | None = None
    max_invalid_actions: int = Field(ge=1)
    toolchain_profiles: list[ToolchainProfileRef] = Field(default_factory=list)
    requested_profile_id: str | None = None
    declared_profile_hash: str | None = None
    resolved_profile_hash: str | None = None
    resolved_profile: ResolvedToolchainProfile | None = None
    reference_candidate_hash: str | None = None
    repository_task_identity: RepositoryPlanIdentity | None = None
    evaluation_contract_hash: str

    @field_validator(
        "plan_item_id",
        "task_hash",
        "source_hash",
        "source_identity_hash",
        "tool_policy_hash",
        "runtime_identity_hash",
        "verifier_hash",
        "correctness_definition_hash",
        "evaluation_contract_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("plan identity fields must be lowercase SHA-256 values")
        return value


class ExperimentPlan(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str
    config_hash: str
    evaluation_config_hash: str
    task_set_hash: str
    source_identity_hash: str
    plan_hash: str
    verigym_version: str
    verigym_commit: str | None = None
    build_provenance: BuildProvenance | None = None
    config: ExperimentConfig
    items: list[PlanItem]

    @field_validator(
        "config_hash",
        "evaluation_config_hash",
        "task_set_hash",
        "source_identity_hash",
        "plan_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("experiment identity fields must be lowercase SHA-256 values")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> ExperimentPlan:
        indices = [item.plan_index for item in self.items]
        if indices != list(range(len(self.items))):
            raise ValueError("plan items must have contiguous ordered plan indices")
        ids = [item.plan_item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("plan item IDs must be unique")
        return self


ExperimentLifecycle = Literal[
    "planned",
    "running",
    "interrupted",
    "completed",
    "completed_with_infrastructure_errors",
    "failed_configuration",
    "failed_internal",
    "cancelled",
]


class ExperimentManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str
    created_at_utc: datetime
    config_hash: str
    evaluation_config_hash: str
    plan_hash: str
    task_set_hash: str
    source_identity_hash: str
    suite_id: str
    suite_versions: list[str]
    release_ids: list[str] = Field(default_factory=list)
    suite_source_snapshots: list[SuiteSourceSnapshot] = Field(default_factory=list)
    verigym_version: str
    verigym_commit: str | None = None
    build_provenance: BuildProvenance | None = None
    selected_task_count: int = Field(ge=1)
    planned_item_count: int = Field(ge=1)
    system_identities: list[PlannedSystemIdentity]
    runtime_identities: list[RuntimeDescriptor]
    resolved_profile_hashes: list[str] = Field(default_factory=list)
    sampling_policy: ExperimentRunsConfig
    execution_policy: ExperimentExecutionConfig
    artifact_locations: dict[str, str]
    status: ExperimentLifecycle = "planned"


class BatchEvent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    sequence: int = Field(ge=0)
    timestamp_utc: datetime
    event_type: Literal[
        "experiment_started",
        "model_process_authorized",
        "plan_item_scheduled",
        "plan_item_started",
        "plan_item_terminal",
        "plan_item_reused_on_resume",
        "plan_item_corrupt",
        "execution_checkpoint",
        "circuit_breaker_opened",
        "report_started",
        "report_completed",
        "experiment_interrupted",
        "experiment_completed",
    ]
    experiment_id: str
    plan_index: int | None = Field(default=None, ge=0)
    plan_item_id: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    detail: dict[str, Any] = Field(default_factory=dict)


ArtifactValidationStatus = Literal["valid", "partial", "corrupt", "incompatible", "missing"]


class RunIndexRecord(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_index: int = Field(ge=0)
    plan_item_id: str
    attempt: int = Field(ge=1)
    child_run_id: str | None = None
    relative_child_path: str | None = None
    terminal_status: str
    resolved: bool = False
    evaluable: bool = False
    infrastructure_error: bool = False
    child_exit_category: str
    artifact_validation_status: ArtifactValidationStatus
    child_manifest_hash: str | None = None
    scorecard_hash: str | None = None
    artifact_manifest_hash: str | None = None
    message: str | None = None

    @field_validator("relative_child_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or len(path.parts) != 2
            or path.parts[0] != "runs"
            or path.parts[1] in {"", ".", ".."}
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("child paths must name one direct child of the experiment runs path")
        return path.as_posix()


class ModelProcessLedgerRecord(StrictModel):
    """Append-only parent authorization for one model-bearing child process."""

    schema_version: Literal["1.0"] = "1.0"
    ordinal: int = Field(ge=1)
    timestamp_utc: datetime
    experiment_id: str
    plan_index: int = Field(ge=0)
    plan_item_id: str
    attempt: int = Field(ge=1)
    task_id: str
    system_id: str
    base_seed: int = Field(ge=0, le=_MAX_SEED)
    sample_index: int = Field(ge=0)
    authorization_state: Literal["launch_authorized"] = "launch_authorized"
    model_bearing_reason: Literal[
        "configured_model_client",
        "external_coding_agent",
    ]
    requested_model_id: str | None = None
    retry: Literal[False] = False
    resume: bool


class ExperimentState(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str
    config_hash: str
    plan_hash: str
    status: ExperimentLifecycle
    planned_count: int = Field(ge=1)
    scheduled_count: int = Field(default=0, ge=0)
    terminal_count: int = Field(default=0, ge=0)
    valid_terminal_count: int = Field(default=0, ge=0)
    infrastructure_error_count: int = Field(default=0, ge=0)
    corrupt_attempt_count: int = Field(default=0, ge=0)
    authorized_model_process_count: int = Field(default=0, ge=0)
    active_count: int = Field(default=0, ge=0)
    observed_max_concurrency: int = Field(default=0, ge=0)
    last_event_sequence: int = Field(default=-1, ge=-1)


class BatchResult(StrictModel):
    experiment_dir: Path
    manifest: ExperimentManifest
    state: ExperimentState
    infrastructure_failures: int = Field(ge=0)
    internal_failures: int = Field(ge=0)
    exit_code: int


__all__ = [
    "ArtifactValidationStatus",
    "BatchEvent",
    "BatchResult",
    "DEFAULT_MAX_PLAN_ITEMS",
    "ExperimentConfig",
    "ExperimentExecutionConfig",
    "ExperimentLifecycle",
    "ExperimentManifest",
    "ExperimentPlan",
    "ExperimentRunsConfig",
    "HARD_MAX_PLAN_ITEMS",
    "ModelProcessLedgerRecord",
    "PlanItem",
    "PlannedSystemIdentity",
    "RunIndexRecord",
    "TaskSelection",
]
