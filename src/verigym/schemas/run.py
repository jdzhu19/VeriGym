"""Run configuration, immutable manifest, and API return value."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from verigym.profiles.base import ResolvedToolchainProfile
from verigym.schemas.action_protocol import (
    RepositoryActionProtocolDescriptor,
    RepositoryActionTurnRecord,
)
from verigym.schemas.agent import AgentDescriptor
from verigym.schemas.agent_feedback import AgentFeedbackContract, AgentFeedbackEvaluation
from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import (
    InteractionMode,
    ModelDescriptor,
    RuntimeDescriptor,
    ToolchainProfileRef,
)
from verigym.schemas.external_agent import ExternalAgentCallIdentity
from verigym.schemas.model import GenerationParameters, ModelCallIdentity, ModelRunConfig
from verigym.schemas.options import JsonValue, validate_plugin_options
from verigym.schemas.prompt import PromptPolicyDescriptor, ToolPolicySnapshot
from verigym.schemas.provenance import BuildProvenance
from verigym.schemas.repository import (
    RepositoryCandidateRecord,
    RepositoryPlanIdentity,
    RepositoryPublicTestOutcome,
)
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.task import BudgetSpec
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile, VerifierToolProfile


class RunConfig(StrictModel):
    schema_version: str = SCHEMA_VERSION
    task_id: str
    mode: InteractionMode = InteractionMode.AGENT
    agent: str = "scripted"
    model: str | None = None
    model_options: ModelRunConfig = Field(default_factory=ModelRunConfig)
    agent_options: dict[str, JsonValue] = Field(default_factory=dict)
    max_invalid_actions: int = Field(default=3, ge=1)
    suite_source: SuiteSourceConfig | None = None
    sample_index: int | None = Field(default=None, ge=0)
    runtime: str = "local"
    docker_config: DockerRuntimeConfig | None = None
    toolchain_profile: str | None = None
    verifier_profile_id: str | None = None
    verifier_profile: VerifierToolProfile | None = None
    expected_resolved_verifier_profile: ResolvedVerifierToolProfile | None = None
    agent_ppa_feedback: bool = False
    agent_ppa_max_calls: int = Field(default=3, ge=1, le=8)
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
    expected_prompt_policy: PromptPolicyDescriptor | None = None
    expected_prompt_policy_hash: str | None = None
    resolved_prompt_policy: PromptPolicyDescriptor | None = None
    resolved_prompt_policy_hash: str | None = None
    expected_agent_configuration_hash: str | None = None
    resolved_agent_configuration_hash: str | None = None
    expected_action_protocol: RepositoryActionProtocolDescriptor | None = None
    resolved_action_protocol: RepositoryActionProtocolDescriptor | None = None
    expected_agent_feedback_contract: AgentFeedbackContract | None = None
    resolved_agent_feedback_contract: AgentFeedbackContract | None = None

    def identity_payload(self) -> dict[str, Any]:
        """Preserve pre-extension hashes while binding every nonempty option."""

        payload = self.model_dump(mode="json")
        if not payload.get("agent_options"):
            payload.pop("agent_options", None)
        if payload.get("agent_ppa_feedback") is False:
            payload.pop("agent_ppa_feedback", None)
        if payload.get("agent_ppa_max_calls") == 3:
            payload.pop("agent_ppa_max_calls", None)
        if all(
            payload.get(field) is None
            for field in (
                "verifier_profile_id",
                "verifier_profile",
                "expected_resolved_verifier_profile",
            )
        ):
            payload.pop("verifier_profile_id", None)
            payload.pop("verifier_profile", None)
            payload.pop("expected_resolved_verifier_profile", None)
        prompt_binding_fields = (
            "expected_prompt_policy",
            "expected_prompt_policy_hash",
            "resolved_prompt_policy",
            "resolved_prompt_policy_hash",
            "expected_agent_configuration_hash",
            "resolved_agent_configuration_hash",
            "expected_action_protocol",
            "resolved_action_protocol",
            "expected_agent_feedback_contract",
            "resolved_agent_feedback_contract",
        )
        if all(payload.get(field) is None for field in prompt_binding_fields):
            for field in prompt_binding_fields:
                payload.pop(field, None)
        model_options = payload.get("model_options")
        if isinstance(model_options, dict) and not model_options.get("client_options"):
            model_options.pop("client_options", None)
        if isinstance(model_options, dict):
            for field, default in (
                ("base_url_env", None),
                ("provider_id", None),
                ("max_response_bytes", 4 * 1024 * 1024),
                ("require_exact_model_id", False),
            ):
                if model_options.get(field) == default:
                    model_options.pop(field, None)
        return payload

    @field_validator("agent_options", mode="before")
    @classmethod
    def validate_agent_options(cls, value: object) -> dict[str, JsonValue]:
        return validate_plugin_options(value)

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
        if (self.verifier_profile_id is None) != (self.verifier_profile is None):
            raise ValueError("verifier profile ID and document must be supplied together")
        if (
            self.verifier_profile is not None
            and self.verifier_profile.id != self.verifier_profile_id
        ):
            raise ValueError("verifier profile ID differs from the loaded document")
        if self.expected_resolved_verifier_profile is not None and self.verifier_profile is None:
            raise ValueError("an expected resolved verifier profile requires a profile")
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
        if (self.expected_prompt_policy is None) != (self.expected_prompt_policy_hash is None):
            raise ValueError("expected prompt descriptor and hash must be supplied together")
        if (self.resolved_prompt_policy is None) != (self.resolved_prompt_policy_hash is None):
            raise ValueError("resolved prompt descriptor and hash must be supplied together")
        if (
            self.resolved_agent_configuration_hash is not None
            and self.expected_agent_configuration_hash is None
        ):
            raise ValueError("a resolved agent configuration requires a frozen expected hash")
        if self.resolved_action_protocol is not None and self.expected_action_protocol is None:
            raise ValueError("resolved repository action protocol requires a frozen expectation")
        if (
            self.resolved_agent_feedback_contract is not None
            and self.expected_agent_feedback_contract is None
        ):
            raise ValueError("resolved agent feedback requires a frozen expected contract")
        return self


class RunManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    created_at_utc: datetime
    verigym_version: str
    verigym_commit: str | None = None
    build_provenance: BuildProvenance | None = None
    task_id: str
    task_hash: str
    source_hash: str
    candidate_hash: str | None = None
    repository_candidate: RepositoryCandidateRecord | None = None
    repository_task_identity: RepositoryPlanIdentity | None = None
    repository_public_tests: list[RepositoryPublicTestOutcome] = Field(default_factory=list)
    repository_public_tool_invocation_count: int = Field(default=0, ge=0)
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
    model_observations: list[ModelCallIdentity] = Field(default_factory=list)
    external_agent_observations: list[ExternalAgentCallIdentity] = Field(default_factory=list)
    agent_configuration_fingerprint: str | None = None
    agent_configuration_hash: str | None = None
    suite_source: SuiteSourceSnapshot | None = None
    runtime: RuntimeDescriptor
    toolchain_profiles: list[ToolchainProfileRef] = Field(default_factory=list)
    requested_toolchain_profile_id: str | None = None
    requested_toolchain_profile_version: str | None = None
    declared_profile_hash: str | None = None
    resolved_profile_hash: str | None = None
    resolved_toolchain_profile: ResolvedToolchainProfile | None = None
    requested_verifier_profile_id: str | None = None
    requested_verifier_profile_version: str | None = None
    verifier_declared_profile_hash: str | None = None
    resolved_verifier_profile_hash: str | None = None
    resolved_verifier_profile: ResolvedVerifierToolProfile | None = None
    synthesis_flow_script_hash: str | None = None
    reference_summary_hash: str | None = None
    reference_strategy: str | None = None
    reference_candidate_hash: str | None = None
    budget: BudgetSpec
    prompt_policy_hash: str | None = None
    action_protocol: RepositoryActionProtocolDescriptor | None = None
    action_protocol_records: list[RepositoryActionTurnRecord] = Field(default_factory=list)
    agent_feedback_contract: AgentFeedbackContract | None = None
    agent_feedback_contract_hash: str | None = None
    agent_feedback_evaluations: list[AgentFeedbackEvaluation] = Field(default_factory=list)
    agent_feedback_evaluations_hash: str | None = None
    experiment_id: str | None = None
    plan_item_id: str | None = None
    system_id: str | None = None
    base_seed: int | None = None
    environment_summary: dict[str, Any] = Field(default_factory=dict)


class RunResult(StrictModel):
    run_dir: Path
    manifest: RunManifest
    scorecard: ScoreCard
