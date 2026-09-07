"""Adapt fixed functional MCP results to the existing public-test controller."""

from __future__ import annotations

import base64
import os
from typing import Any

from pydantic import BaseModel
from verigym_cadence.client import SecRequest, identity_request, rpc
from verigym_cadence.protocol import MAX_TOTAL_BYTES, bounded_read

from verigym.plugin_api import (
    CommandSpec,
    CompletedCommand,
    ConfigurationError,
    ErrorCategory,
    HealthCheckResult,
    ResolvedVerifierToolProfile,
    ToolContext,
    ToolDescriptor,
    ToolResult,
    ToolVisibility,
    VerifierBackendPlugin,
    VerifierToolProfile,
    content_hash,
    hash_bytes,
)
from verigym.profiles.verifier_registry import load_verifier_profile

from .functional import (
    PROTOCOL,
    SERVER_NAME,
    VERSION,
    FunctionalOutcome,
    FunctionalRequest,
    FunctionalResponse,
    FunctionalSummary,
)

PROFILE_ENV = "VERIGYM_REALBENCH_PUBLIC_PROFILE"


class PublicRequest(SecRequest):
    test_id: str


def check_summary(profile: VerifierToolProfile, summary: FunctionalSummary) -> None:
    if (
        summary.profile_id != profile.server_profile_id
        or summary.task_id != profile.task_id
        or summary.protocol != profile.service_protocol
        or summary.server_version != profile.server_version
        or summary.tool_version != profile.accepted_tool_version
        or summary.declared_profile_hash != profile.server_declared_profile_hash
        or summary.contract_hash != profile.server_contract_hash
    ):
        raise ConfigurationError("functional resolved profile mismatch")


def tool_result(outcome: FunctionalOutcome) -> ToolResult:
    status = outcome.status if outcome.cleanup_complete else "infrastructure_failure"
    category = {
        "passed": ErrorCategory.SUCCESS,
        "compile_failed": ErrorCategory.COMPILE_FAILED,
        "function_failed": ErrorCategory.TEST_FAILED,
        "timeout": ErrorCategory.TIMEOUT,
        "infrastructure_failure": ErrorCategory.SANDBOX_ERROR,
    }[status]
    messages = {
        "passed": "syntax and functional checks passed",
        "compile_failed": "candidate syntax or slice RTL policy rejected",
        "function_failed": "syntax passed; functional mismatch",
        "timeout": "functional execution timed out",
        "infrastructure_failure": "functional infrastructure failure",
    }
    return ToolResult(
        tool=RealBenchPublicTool.descriptor.name,
        success=status == "passed",
        category=category,
        message=messages[status],
        metadata={"candidate_failure": status in {"compile_failed", "function_failed"}},
    )


class RealBenchPublicTool(VerifierBackendPlugin):
    descriptor = ToolDescriptor(
        name="realbench.verilator.public.mcp",
        version=VERSION,
        provider="verigym-realbench",
        capabilities=["compile", "functional", "remote_mcp", "fixed_profile", "docker_standard"],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        value = os.environ.get(PROFILE_ENV)
        if value is None:
            return HealthCheckResult(healthy=False, message=f"set {PROFILE_ENV}")
        try:
            resolved = self.resolve_verifier_profile(load_verifier_profile(value))
            return HealthCheckResult(
                healthy=True,
                version=resolved.tool_version,
                message="fixed functional toolchain resolved; not suite qualification",
            )
        except Exception:
            return HealthCheckResult(
                healthy=False, message="functional profile/toolchain unavailable"
            )

    def resolve_verifier_profile(
        self,
        profile: VerifierToolProfile,
        *,
        expected: ResolvedVerifierToolProfile | None = None,
    ) -> ResolvedVerifierToolProfile:
        if (
            profile.target_plugin != self.descriptor.name
            or profile.service_protocol != PROTOCOL
            or profile.server_version != VERSION
            or profile.transport_environment
        ):
            raise ConfigurationError("not a credential-free RealBench functional profile")
        summary = FunctionalSummary.model_validate(
            rpc(profile, "resolve_profile", identity_request(profile), 120, server_name=SERVER_NAME)
        )
        check_summary(profile, summary)
        payload = {
            "profile_id": profile.id,
            "profile_version": profile.version,
            "declared_profile_hash": content_hash(profile),
            "task_id": profile.task_id,
            "source_plugin": profile.source_plugin,
            "target_plugin": profile.target_plugin,
            "runtime": profile.runtime,
            "transport_sha256": profile.transport_sha256,
            "service_protocol": profile.service_protocol,
            "server_version": profile.server_version,
            "server_profile_id": profile.server_profile_id,
            "server_declared_profile_hash": summary.declared_profile_hash,
            "server_resolved_profile_hash": summary.resolved_profile_hash,
            "server_contract_hash": summary.contract_hash,
            "tool_version": summary.tool_version,
        }
        resolved = ResolvedVerifierToolProfile.model_validate(
            {**payload, "resolved_profile_hash": content_hash(payload)}
        )
        if expected is not None and expected != resolved:
            raise ConfigurationError("functional resolved identity drift")
        return resolved

    def validate_request(self, request: dict[str, Any]) -> PublicRequest:
        parsed = PublicRequest.model_validate(request)
        if parsed.test_id != "compile":
            raise ValueError("unknown functional test")
        return parsed

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        raise RuntimeError("functional commands are server-owned")

    def parse_result(
        self, request: BaseModel, completed: CompletedCommand, context: ToolContext
    ) -> ToolResult:
        raise RuntimeError("functional responses require identity validation")

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            request = self.validate_request(raw_request)
            profile, resolved = context.verifier_profile, context.resolved_verifier_profile
            if profile is None or resolved is None or context.session is None:
                raise ConfigurationError("functional execution needs a resolved context")
            if (
                profile.target_plugin != self.descriptor.name
                or profile.service_protocol != PROTOCOL
                or profile.transport_environment
                or resolved.declared_profile_hash != content_hash(profile)
                or content_hash(resolved.identity_payload()) != resolved.resolved_profile_hash
            ):
                raise ConfigurationError("functional context identity mismatch")
            sources = []
            total = 0
            for path in request.sources:
                absolute = context.session.root / path
                if absolute.stat().st_nlink != 1:
                    raise ValueError("candidate hard link is forbidden")
                data = bounded_read(absolute)
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("candidate aggregate bound exceeded")
                sources.append(
                    {
                        "path": path,
                        "sha256": hash_bytes(data),
                        "content_base64": base64.b64encode(data).decode("ascii"),
                    }
                )
            candidate_hash = content_hash({"sources": {s["path"]: s["sha256"] for s in sources}})
            arguments = {
                **identity_request(profile),
                "task_id": profile.task_id,
                "top": request.top,
                "test_id": request.test_id,
                "expected_resolved_profile_hash": resolved.server_resolved_profile_hash,
                "candidate_hash": candidate_hash,
                "sources": sources,
            }
            FunctionalRequest.model_validate(arguments).candidate()
            if context.dispatch_callback is not None:
                context.dispatch_callback()
            response = FunctionalResponse.model_validate(
                rpc(profile, "verify", arguments, 720, server_name=SERVER_NAME)
            )
            check_summary(profile, response.profile)
            if (
                response.candidate_hash != candidate_hash
                or response.profile.top != request.top
                or response.profile.sources != request.sources
                or response.profile.resolved_profile_hash != resolved.server_resolved_profile_hash
            ):
                raise ConfigurationError("functional candidate identity mismatch")
            return tool_result(response.outcome)
        except TimeoutError:
            # Killing the stdio transport does not prove Docker worker cleanup.
            return tool_result(FunctionalOutcome(status="timeout", cleanup_complete=False))
        except Exception:
            return tool_result(
                FunctionalOutcome(status="infrastructure_failure", cleanup_complete=False)
            )
