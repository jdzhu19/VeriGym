"""Tiny external package used only to prove VeriGym's plugin contract."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentAdapter,
    AgentContext,
    AgentDescriptor,
    CommandSpec,
    CompletedCommand,
    EpisodeResult,
    ErrorCategory,
    FinalSubmissionAction,
    HealthCheckResult,
    Observation,
    ResolvedTaskAssets,
    StrictModel,
    SuiteAdapter,
    SuiteDescriptor,
    TaskRef,
    ToolContext,
    ToolDescriptor,
    ToolPlugin,
    ToolResult,
    ToolVisibility,
    ValidationReport,
    VeriTask,
)


class ConformanceSuite(SuiteAdapter):
    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="external-conformance",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-conformance-plugin",
        capabilities=["generation", "plugin_conformance"],
        title="External plugin conformance fixture",
        description="One redistributable task used only for installed entry-point tests.",
        suite_version="0.1.0",
        license="Apache-2.0",
    )

    def __init__(self) -> None:
        self._root = Path(__file__).parent / "assets"

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        if source_root is not None:
            return []
        return [
            TaskRef(
                id="external-conformance/tiny-and",
                suite="external-conformance",
                native_id="tiny-and",
            )
        ]

    def load_task(self, ref: TaskRef) -> VeriTask:
        if ref.id != "external-conformance/tiny-and":
            raise KeyError(ref.id)
        return VeriTask.model_validate_json((self._root / "task.json").read_text(encoding="utf-8"))

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        if task.id != "external-conformance/tiny-and":
            raise KeyError(task.id)
        return ResolvedTaskAssets(
            visible_root=str((self._root / "workspace").resolve()),
            hidden_roots=[str((self._root / "hidden").resolve())],
        )

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        if source_root is not None:
            return ValidationReport(valid=False, errors=["fixture accepts no external source"])
        required = [
            self._root / "task.json",
            self._root / "workspace" / "rtl" / "tiny_and.v",
            self._root / "hidden" / "tb_tiny_and.sv",
        ]
        missing = [path.name for path in required if not path.is_file()]
        return ValidationReport(
            valid=not missing,
            errors=[f"missing fixture asset: {name}" for name in missing],
        )


class EmptyRequest(StrictModel):
    pass


class ConformanceTool(ToolPlugin):
    descriptor = ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="external-conformance.health",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-conformance-plugin",
        capabilities=["health_only", "no_policy_bypass"],
        visibility=ToolVisibility.AGENT_VISIBLE,
    )

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        return HealthCheckResult(healthy=True, message="external conformance fixture loaded")

    def validate_request(self, request: dict[str, Any]) -> EmptyRequest:
        return EmptyRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        return CommandSpec(argv=["true"])

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        return ToolResult(
            tool=self.descriptor.name,
            success=completed.exit_code == 0,
            category=(
                ErrorCategory.SUCCESS if completed.exit_code == 0 else ErrorCategory.TOOL_FAILED
            ),
            exit_code=completed.exit_code,
        )


class ConformanceAgent(AgentAdapter):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="external-conformance-agent",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-conformance-plugin",
        capabilities=["final_submission", "plugin_conformance"],
    )

    def start(self, context: AgentContext) -> None:
        del context

    def act(self, observation: Observation) -> FinalSubmissionAction:
        del observation
        return FinalSubmissionAction(message="External conformance agent completed.")

    def finish(self, result: EpisodeResult) -> None:
        del result


__all__ = ["ConformanceAgent", "ConformanceSuite", "ConformanceTool"]
