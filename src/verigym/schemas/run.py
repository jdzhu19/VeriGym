"""Run configuration, immutable manifest, and API return value."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

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

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> RunConfig:
        if self.docker_config is not None and self.runtime != "docker":
            raise ValueError("Docker configuration requires runtime='docker'")
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
    environment_summary: dict[str, Any] = Field(default_factory=dict)


class RunResult(StrictModel):
    run_dir: Path
    manifest: RunManifest
    scorecard: ScoreCard
