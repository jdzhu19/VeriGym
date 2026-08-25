"""Shared domain types and immutable plugin descriptors."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel


class InteractionMode(StrEnum):
    CHAT = "chat"
    AGENT = "agent"
    TRAIN = "train"


class TaskType(StrEnum):
    GENERATION = "generation"
    COMPLETION = "completion"
    REPAIR = "repair"
    REPO_REPAIR = "repo_repair"
    VERIFICATION = "verification"
    TESTBENCH_GENERATION = "testbench_generation"
    ASSERTION_GENERATION = "assertion_generation"
    OPTIMIZATION = "optimization"
    MIXED = "mixed"


class ToolVisibility(StrEnum):
    AGENT_VISIBLE = "agent_visible"
    VERIFIER_ONLY = "verifier_only"
    BOTH = "both"


class ErrorCategory(StrEnum):
    SUCCESS = "success"
    TOOL_FAILED = "tool_failed"
    COMPILE_FAILED = "compile_failed"
    TEST_FAILED = "test_failed"
    TIMEOUT = "timeout"
    OUT_OF_MEMORY = "out_of_memory"
    OUTPUT_LIMIT = "output_limit"
    INVALID_REQUEST = "invalid_request"
    TOOL_NOT_FOUND = "tool_not_found"
    LICENSE_UNAVAILABLE = "license_unavailable"
    UNSUPPORTED_VERSION = "unsupported_version"
    PARSER_ERROR = "parser_error"
    SANDBOX_ERROR = "sandbox_error"
    PERMISSION_DENIED = "permission_denied"
    POLICY_DENIED = "policy_denied"
    INTERNAL_ERROR = "internal_error"


class PluginDescriptor(StrictModel):
    name: str
    version: str
    api_version: str = "1.0"
    provider: str
    capabilities: list[str] = Field(default_factory=list)


class SuiteDescriptor(PluginDescriptor):
    schema_version: str = SCHEMA_VERSION
    title: str
    description: str
    suite_version: str
    license: str | None = None


class ToolDescriptor(PluginDescriptor):
    schema_version: str = SCHEMA_VERSION
    visibility: ToolVisibility


class AgentDescriptor(PluginDescriptor):
    schema_version: str = SCHEMA_VERSION


class ModelDescriptor(PluginDescriptor):
    schema_version: str = SCHEMA_VERSION
    model_id: str
    client_name: str | None = None
    client_version: str | None = None
    api_compatibility: str = "verigym.model.v1"
    configuration_fingerprint: str = ""
    configuration: dict[str, Any] = Field(default_factory=dict)


class RuntimeBackendInfo(StrictModel):
    backend_type: str
    client_version: str | None = None
    server_version: str | None = None
    api_version: str | None = None
    server_os: str | None = None
    server_architecture: str | None = None
    rootless: bool | None = None
    memory_limit_supported: bool | None = None
    swap_limit_supported: bool | None = None
    cpu_limit_supported: bool | None = None
    pids_limit_supported: bool | None = None


class RuntimeImageIdentity(StrictModel):
    requested_reference: str
    resolved_image_id: str
    repository_digests: list[str] | None = None
    created_at: str | None = None
    os: str
    architecture: str
    configured_image_user: str | None = None
    effective_user: str | None = None
    observed_uid: int | None = Field(default=None, ge=0)
    observed_gid: int | None = Field(default=None, ge=0)
    iverilog_version: str | None = None
    vvp_version: str | None = None
    compatibility_status: str | None = None


class RuntimeSecuritySummary(StrictModel):
    network_mode: str
    read_only_rootfs: bool
    configured_user: str | None = None
    observed_uid: int | None = Field(default=None, ge=0)
    observed_gid: int | None = Field(default=None, ge=0)
    privileged: bool = False
    cap_drop: list[str] = Field(default_factory=list)
    no_new_privileges: bool = False
    init: bool = False
    mount_destinations: list[str] = Field(default_factory=list)
    writable_destinations: list[str] = Field(default_factory=list)
    environment_names: list[str] = Field(default_factory=list)
    docker_socket_mounted: bool = False
    host_home_mounted: bool = False


class RuntimeResourceSummary(StrictModel):
    memory_bytes: int = Field(ge=1)
    memory_swap_bytes: int | None = Field(default=None, ge=1)
    swap_enforced: bool
    cpus: float = Field(gt=0.0)
    pids_limit: int = Field(ge=1)
    tmpfs_bytes: int = Field(ge=1)
    stop_timeout_s: int | None = Field(default=None, ge=1)
    max_command_time_s: int = Field(ge=1)
    max_output_bytes: int | None = Field(default=None, ge=1)
    max_artifact_file_bytes: int | None = Field(default=None, ge=1)
    max_artifact_bytes: int | None = Field(default=None, ge=1)


class RuntimeSessionRecord(StrictModel):
    session_id: str
    role: str
    resolved_image_id: str
    container_ids: list[str] = Field(default_factory=list)
    command_count: int = Field(default=0, ge=0)
    frozen: bool = False
    cleanup_complete: bool = False
    cleanup_warnings: list[str] = Field(default_factory=list)


class RuntimeCleanupSummary(StrictModel):
    complete: bool = False
    removed_container_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RuntimeDescriptor(PluginDescriptor):
    schema_version: str = SCHEMA_VERSION
    isolation_level: str
    deterministic: bool = True
    backend: RuntimeBackendInfo | None = None
    image: RuntimeImageIdentity | None = None
    security: RuntimeSecuritySummary | None = None
    resources: RuntimeResourceSummary | None = None
    sessions: list[RuntimeSessionRecord] = Field(default_factory=list)
    cleanup: RuntimeCleanupSummary | None = None
    configuration_fingerprint: str | None = None


class AssetRef(StrictModel):
    kind: Literal["directory", "file", "inline"]
    path: str | None = None
    content: str | None = None
    content_hash: str | None = None
    mount_path: str | None = None

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("asset content hash must be a lowercase SHA-256")
        return value


class ArtifactDescriptor(StrictModel):
    name: str
    uri: str | None = None
    content_hash: str | None = None
    version: str | None = None
    license: str | None = None
    media_type: str | None = None
    source_kind: Literal["package_resource", "user_path", "generated"] | None = None
    attribution: str | None = None
    redistributable: bool | None = None
    unit: str | None = None
    semantics: str | None = None
    copy_permitted: bool = False

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("artifact content hash must be a lowercase SHA-256")
        return value


class ToolRequirement(StrictModel):
    name: str
    version: str | None = None
    required: bool = True
    executable: str | None = None
    version_command: list[str] = Field(default_factory=list)
    accepted_version: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    abc_required: bool = False
    git_hash: str | None = None

    @field_validator("git_hash")
    @classmethod
    def validate_git_hash(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("tool git identity must be a full lowercase SHA-1")
        return value


class RuntimeRequirement(StrictModel):
    runtime: str
    minimum_version: str | None = None
    allowed_runtimes: list[str] = Field(default_factory=list)
    minimum_isolation_level: str | None = None
    requested_image: str | None = None
    immutable_image_required: bool = False
    supported_os: list[str] = Field(default_factory=list)
    supported_architectures: list[str] = Field(default_factory=list)
    network_policy: Literal["none", "allowlist", "open"] | None = None
    resource_controls_required: bool = False

    @model_validator(mode="after")
    def normalize_allowed_runtimes(self) -> RuntimeRequirement:
        if len(self.allowed_runtimes) != len(set(self.allowed_runtimes)):
            raise ValueError("allowed_runtimes must not contain duplicates")
        if self.allowed_runtimes and self.runtime not in self.allowed_runtimes:
            raise ValueError("runtime must be included in allowed_runtimes")
        return self


class SynthesisFlowSpec(StrictModel):
    frontend: Literal["verilog-2005", "systemverilog-subset"]
    source_policy: Literal["task_entrypoints"] = "task_entrypoints"
    default_sources: list[str] = Field(min_length=1)
    top_policy: Literal["profile_fixed"] = "profile_fixed"
    top_module: str
    hierarchy_check: bool = True
    flatten: bool = True
    backend_plugin: str = "yosys.synth"
    template_id: str
    abc_policy_id: str
    liberty_mapping: bool = True
    emit_netlist_verilog: bool = True
    emit_netlist_json: bool = True
    emit_stat_json: bool = True
    reference_normalization: Literal["suite_reference_solution", "none"] = (
        "suite_reference_solution"
    )

    @field_validator("backend_plugin")
    @classmethod
    def validate_backend_plugin(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
            raise ValueError("synthesis backend plugin must be a stable lowercase slug")
        return value


class MetricSpec(StrictModel):
    enabled: bool
    source: str | None = None
    unit: str | None = None
    semantics: str | None = None


class MetricContract(StrictModel):
    scope: Literal[
        "synthesis_area_only",
        "synthesis_area_timing",
        "synthesis_area_timing_power",
    ] = "synthesis_area_only"
    area: MetricSpec
    delay: MetricSpec = Field(default_factory=lambda: MetricSpec(enabled=False))
    frequency: MetricSpec = Field(default_factory=lambda: MetricSpec(enabled=False))
    power: MetricSpec = Field(default_factory=lambda: MetricSpec(enabled=False))
    worst_negative_slack: MetricSpec = Field(default_factory=lambda: MetricSpec(enabled=False))
    total_negative_slack: MetricSpec = Field(default_factory=lambda: MetricSpec(enabled=False))
    educational: bool = True
    signoff: bool = False

    @model_validator(mode="after")
    def enforce_metric_contract(self) -> MetricContract:
        if self.area.enabled and (not self.area.source or not self.area.unit):
            raise ValueError("enabled area requires an explicit source and unit")
        for name, metric in (
            ("delay", self.delay),
            ("frequency", self.frequency),
            ("power", self.power),
            ("worst_negative_slack", self.worst_negative_slack),
            ("total_negative_slack", self.total_negative_slack),
        ):
            if metric.enabled and (not metric.source or not metric.unit):
                raise ValueError(f"enabled {name} requires an explicit source and unit")
        if self.scope == "synthesis_area_only":
            unavailable = (
                self.delay,
                self.frequency,
                self.power,
                self.worst_negative_slack,
                self.total_negative_slack,
            )
            if any(metric.enabled for metric in unavailable):
                raise ValueError("area-only profiles cannot enable timing or power metrics")
        elif self.scope == "synthesis_area_timing":
            if not (self.area.enabled and self.delay.enabled and self.worst_negative_slack.enabled):
                raise ValueError(
                    "area-timing profiles require area, delay, and worst-negative slack"
                )
            if self.frequency.enabled or self.power.enabled or self.total_negative_slack.enabled:
                raise ValueError("the area-timing scope does not enable frequency, power, or TNS")
        else:
            if not (
                self.area.enabled
                and self.delay.enabled
                and self.power.enabled
                and self.worst_negative_slack.enabled
            ):
                raise ValueError(
                    "area-timing-power profiles require area, delay, power, and "
                    "worst-negative slack"
                )
            if self.frequency.enabled or self.total_negative_slack.enabled:
                raise ValueError("the area-timing-power scope does not enable frequency or TNS")
        if self.signoff:
            raise ValueError("VeriGym synthesis profiles cannot claim signoff")
        return self


class ReferenceMetricSpec(StrictModel):
    strategy: Literal["suite_reference_solution"]
    ratio: Literal["reference_area_over_candidate_area"] = "reference_area_over_candidate_area"
    required_for_ranking: bool = True


class ToolchainProfile(StrictModel):
    schema_version: str = SCHEMA_VERSION
    api_version: str = PLUGIN_API_VERSION
    id: str
    version: str
    description: str
    tools: list[ToolRequirement] = Field(default_factory=list)
    runtime: RuntimeRequirement
    container_image: str | None = None
    container_digest: str | None = None
    pdk: ArtifactDescriptor | None = None
    libraries: list[ArtifactDescriptor] = Field(default_factory=list)
    constraints: list[AssetRef | ArtifactDescriptor] = Field(default_factory=list)
    scripts: list[AssetRef | ArtifactDescriptor] = Field(default_factory=list)
    environment_allowlist: list[str] = Field(default_factory=list)
    deterministic: bool = True
    reproducibility_scope: Literal["public", "site_specific", "private"] = "public"
    compatibility_status: str | None = None
    flow: SynthesisFlowSpec | None = None
    metrics: MetricContract | None = None
    reference: ReferenceMetricSpec | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("environment_allowlist")
    @classmethod
    def validate_environment_allowlist(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("environment allowlist names must be unique")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in value):
            raise ValueError("environment allowlist entries must be variable names, not values")
        return sorted(value)

    @model_validator(mode="after")
    def validate_profile_contract(self) -> ToolchainProfile:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported toolchain-profile schema {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        if self.api_version != PLUGIN_API_VERSION:
            raise ValueError(
                f"unsupported toolchain-profile API {self.api_version!r}; "
                f"expected {PLUGIN_API_VERSION!r}"
            )
        if not self.id or not self.version:
            raise ValueError("profile id and version must be nonempty")
        tool_names = [tool.name for tool in self.tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("tool requirements must have unique names")
        library_names = [library.name for library in self.libraries]
        if len(library_names) != len(set(library_names)):
            raise ValueError("profile libraries must have unique logical names")
        synthesis_fields = (self.flow, self.metrics, self.reference)
        if any(field is not None for field in synthesis_fields) and not all(
            field is not None for field in synthesis_fields
        ):
            raise ValueError("synthesis profiles require flow, metrics, and reference contracts")
        if self.flow is not None and self.metrics is not None:
            if self.metrics.area.enabled and not self.flow.liberty_mapping:
                raise ValueError("mapped area requires Liberty mapping in the flow")
            if self.metrics.area.enabled and not self.libraries:
                raise ValueError("mapped area requires an identified library")
        return self


class ToolchainProfileRef(StrictModel):
    id: str
    version: str
    content_hash: str


class Timestamped(StrictModel):
    created_at_utc: datetime
