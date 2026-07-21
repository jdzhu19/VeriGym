"""Verifier DAG schemas and normalized node outcomes."""

from __future__ import annotations

from enum import StrEnum
from graphlib import CycleError, TopologicalSorter
from typing import Any, Literal

from pydantic import Field, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ErrorCategory, ToolVisibility


class VerifierStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class ConditionSpec(StrictModel):
    kind: Literal["always", "dependency_passed", "dependency_failed"] = "dependency_passed"
    node: str | None = None


class VerifierNode(StrictModel):
    id: str
    plugin: str
    depends_on: list[str] = Field(default_factory=list)
    gate: bool = False
    required: bool = True
    visibility: ToolVisibility
    request: dict[str, Any]
    timeout_s: int | None = Field(default=None, ge=1)
    run_if: ConditionSpec | None = None
    artifact_globs: list[str] = Field(default_factory=list)


class VerifierGraph(StrictModel):
    schema_version: str = SCHEMA_VERSION
    nodes: list[VerifierNode]

    @model_validator(mode="after")
    def validate_graph(self) -> VerifierGraph:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            duplicates = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
            raise ValueError(f"duplicate verifier node IDs: {duplicates}")
        known = set(ids)
        for node in self.nodes:
            missing = set(node.depends_on) - known
            if missing:
                raise ValueError(f"node {node.id!r} has unknown dependencies: {sorted(missing)}")
            if node.id in node.depends_on:
                raise ValueError(f"node {node.id!r} cannot depend on itself")
        try:
            tuple(
                TopologicalSorter(
                    {node.id: set(node.depends_on) for node in self.nodes}
                ).static_order()
            )
        except CycleError as exc:
            raise ValueError(f"verifier graph contains a cycle: {exc.args[1]}") from exc
        return self


class VerifierResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    node_id: str
    plugin: str
    status: VerifierStatus
    error_category: ErrorCategory = ErrorCategory.SUCCESS
    message: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    duration_s: float = Field(default=0.0, ge=0.0)
    exit_code: int | None = None
    tests_passed: int | None = None
    tests_total: int | None = None
    artifacts: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
