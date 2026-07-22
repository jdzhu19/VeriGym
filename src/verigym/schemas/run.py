"""Run configuration, immutable manifest, and API return value."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from verigym.profiles.base import ResolvedToolchainProfile
from verigym.schemas.agent import AgentDescriptor
from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import (
    InteractionMode,
    ModelDescriptor,
    RuntimeDescriptor,
    ToolchainProfileRef,
)
from verigym.schemas.model import GenerationParameters, ModelRunConfig
from verigym.schemas.prompt import PromptPolicyDescriptor, ToolPolicySnapshot
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.task import BudgetSpec


class RunConfig(StrictModel):
    schema_version: str = SCHEMA_VERSION
    task_id: str
    mode: InteractionMode = InteractionMode.AGENT
    agent: str = "scripted"
    model: str | None = None
    model_options: ModelRunConfig = Field(default_factory=ModelRunConfig)
    max_invalid_actions: int = Field(default=3, ge=1)
    suite_source: SuiteSourceConfig | None = None
    sample_index: int | None = Field(default=None, ge=0)
    runtime: str = "local"
    docker_config: DockerRuntimeConfig | None = None
    toolchain_profile: str | None = None
    seed: int = 0
    output: Path = Path("runs")
    run_id: str | None = None
    experiment_id: str | None = None
    plan_item_id: str | None = None
    system_id: str | None = None
    base_seed: int | None = Field(default=None, ge=0)
    expected_task_hash: str | None = None
    expected_source_hash: str | None = None
    expected_suite_source_snapshot: SuiteSourceSnapshot | None = None
    expected_runtime: RuntimeDescriptor | None = None
    expected_resolved_profile: ResolvedToolchainProfile | None = None

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not value
            or value != value.strip()
            or len(value) > 200
            or "/" in value
            or "\\" in value
            or value in {".", ".."}
            or "\x00" in value
        ):
            raise ValueError("explicit run IDs must be safe single path components")
        return value

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> RunConfig:
        if self.docker_config is not None and self.runtime != "docker":
            raise ValueError("Docker configuration requires runtime='docker'")
        if self.expected_runtime is not None and self.expected_runtime.name != self.runtime:
            raise ValueError("expected runtime identity does not match runtime selection")
        if self.expected_resolved_profile is not None and self.toolchain_profile is None:
            raise ValueError("an expected resolved profile requires toolchain_profile")
        experiment_fields = (
            self.experiment_id,
            self.plan_item_id,
            self.system_id,
            self.base_seed,
        )
        if any(value is not None for value in experiment_fields) and not all(
            value is not None for value in experiment_fields
        ):
            raise ValueError("experiment child binding fields must be supplied together")
        frozen_input_fields = (
            self.expected_task_hash,
            self.expected_source_hash,
        )
        if any(value is not None for value in frozen_input_fields) and not all(
            value is not None for value in frozen_input_fields
        ):
            raise ValueError("expected task and source hashes must be supplied together")
        return self


class RunManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    created_at_utc: datetime
    verigym_version: str
    verigym_commit: str | None = None
    task_id: str
    task_hash: str
    source_hash: str
    candidate_hash: str | None = None
    verifier_hash: str
    run_config_hash: str
    suite: str
    suite_version: str
    release_id: str | None = None
    interaction_mode: str
    seed: int
    sample_index: int | None = None
    model: ModelDescriptor | None = None
    agent: AgentDescriptor
    agent_harness: AgentDescriptor | None = None
    prompt_policy: PromptPolicyDescriptor | None = None
    tool_policy: ToolPolicySnapshot | None = None
    generation: GenerationParameters | None = None
    suite_source: SuiteSourceSnapshot | None = None
    runtime: RuntimeDescriptor
    toolchain_profiles: list[ToolchainProfileRef] = Field(default_factory=list)
    requested_toolchain_profile_id: str | None = None
    requested_toolchain_profile_version: str | None = None
    declared_profile_hash: str | None = None
    resolved_profile_hash: str | None = None
    resolved_toolchain_profile: ResolvedToolchainProfile | None = None
    synthesis_flow_script_hash: str | None = None
    reference_summary_hash: str | None = None
    reference_strategy: str | None = None
    reference_candidate_hash: str | None = None
    budget: BudgetSpec
    prompt_policy_hash: str | None = None
    experiment_id: str | None = None
    plan_item_id: str | None = None
    system_id: str | None = None
    base_seed: int | None = None
    environment_summary: dict[str, Any] = Field(default_factory=dict)


class RunResult(StrictModel):
    run_dir: Path
    manifest: RunManifest
    scorecard: ScoreCard
