"""Shared domain types and immutable plugin descriptors."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from verigym.schemas.base import SCHEMA_VERSION, StrictModel


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


class RuntimeDescriptor(PluginDescriptor):
    schema_version: str = SCHEMA_VERSION
    isolation_level: str
    deterministic: bool = True


class AssetRef(StrictModel):
    kind: Literal["directory", "file", "inline"]
    path: str | None = None
    content: str | None = None
    content_hash: str | None = None
    mount_path: str | None = None


class ArtifactDescriptor(StrictModel):
    name: str
    uri: str | None = None
    content_hash: str | None = None
    version: str | None = None
    license: str | None = None


class ToolRequirement(StrictModel):
    name: str
    version: str | None = None
    required: bool = True


class RuntimeRequirement(StrictModel):
    runtime: str
    minimum_version: str | None = None


class ToolchainProfile(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    version: str
    description: str
    tools: list[ToolRequirement] = Field(default_factory=list)
    runtime: RuntimeRequirement
    container_image: str | None = None
    container_digest: str | None = None
    pdk: ArtifactDescriptor | None = None
    libraries: list[ArtifactDescriptor] = Field(default_factory=list)
    constraints: list[AssetRef] = Field(default_factory=list)
    scripts: list[AssetRef] = Field(default_factory=list)
    environment_allowlist: list[str] = Field(default_factory=list)
    deterministic: bool = True
    reproducibility_scope: Literal["public", "site_specific", "private"] = "public"
    compatibility_status: str | None = None


class ToolchainProfileRef(StrictModel):
    id: str
    version: str
    content_hash: str


class Timestamped(StrictModel):
    created_at_utc: datetime
