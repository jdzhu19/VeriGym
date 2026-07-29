"""Trusted agent-visible interface for repository public tests."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ErrorCategory, ToolDescriptor, ToolVisibility
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.tools.base import ToolContext, ToolPlugin


class RepositoryPublicTestRequest(StrictModel):
    test_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RepositoryPublicTestTool(ToolPlugin):
    """Dispatch one predeclared test through the runtime-owned launcher."""

    descriptor = ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="repository.public_test",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "hash_bound_argv",
            "shell_free",
            "ephemeral_build",
            "bounded_feedback",
            "public_assets_read_only",
        ],
        visibility=ToolVisibility.AGENT_VISIBLE,
    )

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        return HealthCheckResult(
            healthy=True,
            message="runtime-managed; availability is checked when the task session is created",
        )

    def validate_request(self, request: dict[str, Any]) -> RepositoryPublicTestRequest:
        return RepositoryPublicTestRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, RepositoryPublicTestRequest)
        return CommandSpec(
            argv=["verigym-public-test", "run", request.test_id],
            cwd=".",
            timeout_s=60,
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, RepositoryPublicTestRequest)
        if completed.timed_out:
            category = ErrorCategory.TIMEOUT
        elif completed.oom_killed:
            category = ErrorCategory.OUT_OF_MEMORY
        elif completed.output_truncated:
            category = ErrorCategory.OUTPUT_LIMIT
        elif completed.error is not None:
            category = ErrorCategory.SANDBOX_ERROR
        else:
            category = ErrorCategory.SUCCESS
        payload: dict[str, Any] | None = None
        if completed.stdout:
            try:
                raw = json.loads(completed.stdout)
                payload = raw if isinstance(raw, dict) else None
            except json.JSONDecodeError:
                payload = None
        if category == ErrorCategory.SUCCESS and (
            completed.exit_code not in {0, 1}
            or payload is None
            or payload.get("schema_version") != "1.0"
            or payload.get("protocol") != "verigym_public_test_v1"
            or payload.get("test_id") != request.test_id
            or not isinstance(payload.get("passed"), bool)
        ):
            category = ErrorCategory.PARSER_ERROR
        passed = (
            category == ErrorCategory.SUCCESS
            and completed.exit_code == 0
            and payload is not None
            and payload.get("passed") is True
        )
        if category == ErrorCategory.SUCCESS and not passed:
            category = ErrorCategory.TEST_FAILED
        return ToolResult(
            tool=self.descriptor.name,
            success=passed,
            category=category,
            message=(
                "repository public test passed" if passed else "repository public test did not pass"
            ),
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=completed.duration_s,
            output_truncated=completed.output_truncated,
            metadata={
                "test_id": request.test_id,
                "launcher_protocol": "verigym_public_test_v1",
                "public_assets_read_only": bool(completed.metadata.get("public_assets_read_only")),
                "network_policy": completed.metadata.get("network_policy"),
                "result_category": payload.get("category") if payload is not None else None,
            },
        )

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate_request(raw_request)
        if context.session is None:
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=ErrorCategory.INTERNAL_ERROR,
                message="repository public test requires a runtime session",
            )
        completed = context.session.execute_public_test(request.test_id)
        return self.parse_result(request, completed, context)


def builtin_repository_tools() -> list[ToolPlugin]:
    return [RepositoryPublicTestTool()]


__all__ = ["RepositoryPublicTestRequest", "RepositoryPublicTestTool", "builtin_repository_tools"]
