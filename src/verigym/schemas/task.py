"""Canonical benchmark-independent task representation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import AssetRef, InteractionMode, SuiteDescriptor, TaskType


class SourceSpec(StrictModel):
    kind: Literal["benchmark", "repository", "synthetic", "manual"]
    uri: str | None = None
    revision: str | None = None
    commit: str | None = None
    license: str | None = None
    attribution: str | None = None
    content_hash: str | None = None


class WorkspaceSpec(StrictModel):
    base: AssetRef
    editable_globs: list[str]
    readonly_globs: list[str] = Field(default_factory=list)
    excluded_globs: list[str] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    visible_assets: list[AssetRef] = Field(default_factory=list)
    hidden_assets: list[AssetRef] = Field(default_factory=list)
    max_changed_files: int | None = None
    max_patch_lines: int | None = None


class ObservationPolicy(StrictModel):
    include_tree: bool = True
    include_readme: bool = True
    include_entrypoints: bool = False


class SubmissionPolicy(StrictModel):
    kind: Literal["workspace", "patch", "file"] = "workspace"
    path: str | None = None


class InteractionSpec(StrictModel):
    supported_modes: list[InteractionMode]
    default_mode: InteractionMode
    allowed_tools: list[str]
    denied_tools: list[str] = Field(default_factory=list)
    allow_general_shell: bool = False
    network_policy: Literal["none", "allowlist", "open"] = "none"
    initial_observation: ObservationPolicy = Field(default_factory=ObservationPolicy)
    final_submission: SubmissionPolicy = Field(default_factory=SubmissionPolicy)

    @model_validator(mode="after")
    def validate_default_mode(self) -> InteractionSpec:
        if self.default_mode not in self.supported_modes:
            raise ValueError("default_mode must be included in supported_modes")
        overlap = set(self.allowed_tools) & set(self.denied_tools)
        if overlap:
            raise ValueError(f"tools cannot be both allowed and denied: {sorted(overlap)}")
        return self


class BudgetSpec(StrictModel):
    max_turns: int = Field(default=1, ge=1)
    max_tool_calls: int = Field(default=0, ge=0)
    max_model_calls: int | None = Field(default=None, ge=0)
    max_wall_time_s: int = Field(default=300, ge=1)
    max_tool_time_s: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    max_total_tokens: int | None = Field(default=None, ge=0)
    max_output_bytes_per_tool: int = Field(default=1_000_000, ge=1)
    max_workspace_bytes: int | None = Field(default=None, ge=1)
    max_cpu_seconds: int | None = Field(default=None, ge=1)


class ScoringSpec(StrictModel):
    correctness_required_nodes: list[str]
    ppa_enabled: bool = False


class TaskRef(StrictModel):
    id: str
    suite: str
    native_id: str
    source_root: str | None = None


class ValidationIssue(StrictModel):
    level: Literal["error", "warning"]
    code: str
    message: str
    relative_path: str | None = None


class ValidationReport(StrictModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)


class Candidate(StrictModel):
    files: dict[str, str]
    label: str | None = None


class ConformanceCase(StrictModel):
    name: str
    candidate: Candidate
    expected_resolved: bool


class ResolvedTaskAssets(StrictModel):
    visible_root: str
    hidden_roots: list[str] = Field(default_factory=list)
    hidden_assets: list[AssetRef] = Field(default_factory=list)


# Imported after the supporting classes to avoid an import cycle in type checkers.
from verigym.schemas.verifier import VerifierGraph  # noqa: E402


class VeriTask(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    suite: str
    suite_version: str
    task_type: TaskType
    title: str
    description: str
    source: SourceSpec
    workspace: WorkspaceSpec
    interaction: InteractionSpec
    budget: BudgetSpec
    verifier: VerifierGraph
    scoring: ScoringSpec
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cross_references(self) -> VeriTask:
        node_ids = {node.id for node in self.verifier.nodes}
        missing = set(self.scoring.correctness_required_nodes) - node_ids
        if missing:
            raise ValueError(f"correctness nodes missing from verifier graph: {sorted(missing)}")
        return self


__all__ = [
    "BudgetSpec",
    "Candidate",
    "ConformanceCase",
    "InteractionSpec",
    "ResolvedTaskAssets",
    "ScoringSpec",
    "SourceSpec",
    "SuiteDescriptor",
    "TaskRef",
    "ValidationReport",
    "ValidationIssue",
    "VeriTask",
    "WorkspaceSpec",
]
