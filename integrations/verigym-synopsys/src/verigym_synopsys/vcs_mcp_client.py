"""Verifier backend for a fixed local or SSH-transported VCS MCP service."""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Literal

from pydantic import BaseModel
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    CommandSpec,
    CompletedCommand,
    ConfigurationError,
    ErrorCategory,
    HealthCheckResult,
    ResolvedVerifierToolProfile,
    StrictModel,
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

from .common import redact
from .mcp_client import (
    McpProtocolError,
    _mcp_messages,
    _parse_rpc_responses,
    _run_stdio,
    _transport_environment,
    _transport_identity,
)
from .vcs import VcsSimulationRequest, _bounded_file
from .vcs_mcp_profile import (
    RESOLVE_PROFILE_TOOL,
    SERVER_VERSION,
    SERVICE_PROTOCOL,
    SIMULATE_TOOL,
)

_MAX_SOURCE_TOTAL_BYTES = 32 * 1024 * 1024


class VcsProfileSummary(StrictModel):
    service_protocol: Literal["verigym.synopsys.vcs.mcp.v1"]
    server_version: str
    profile_id: str
    profile_version: str
    task_id: str
    accepted_tool_version: str
    sources: list[str]
    testbench_mount_path: str
    testbench_sha256: str
    top: str
    pass_marker: str
    fail_marker: str
    timeout_s: int
    declared_profile_hash: str
    contract_hash: str


class VcsResolvedProfileSummary(StrictModel):
    service_protocol: Literal["verigym.synopsys.vcs.mcp.v1"]
    server_version: str
    profile_id: str
    profile_version: str
    declared_profile_hash: str
    contract_hash: str
    tool_version: str
    resolved_profile_hash: str


class VcsResolveResponse(StrictModel):
    protocol: Literal["verigym.synopsys.vcs.mcp.v1"]
    profile: VcsProfileSummary
    resolved_profile: VcsResolvedProfileSummary


class VcsSimulationResponse(VcsResolveResponse):
    candidate_hash: str
    tool_result: ToolResult


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="synopsys.vcs.mcp",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-synopsys",
        capabilities=[
            "simulation",
            "systemverilog",
            "licensed",
            "remote_mcp",
            "fixed_profile",
            "structured_errors",
        ],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )


def _tool_response(completed: CompletedCommand, expected_server_version: str) -> dict[str, Any]:
    _, response = _parse_rpc_responses(
        completed,
        expected_server_version=expected_server_version,
    )
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        raise McpProtocolError("VCS MCP service rejected the fixed verifier request")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict) or structured.get("protocol") != SERVICE_PROTOCOL:
        raise McpProtocolError("VCS MCP service returned an invalid structured response")
    return structured


def _validate_remote_identity(
    profile: VerifierToolProfile,
    response: VcsResolveResponse,
) -> None:
    summary = response.profile
    resolved = response.resolved_profile
    if (
        response.protocol != profile.service_protocol
        or summary.service_protocol != profile.service_protocol
        or resolved.service_protocol != profile.service_protocol
        or summary.server_version != profile.server_version
        or resolved.server_version != profile.server_version
        or summary.profile_id != profile.server_profile_id
        or resolved.profile_id != profile.server_profile_id
        or summary.task_id != profile.task_id
        or summary.declared_profile_hash != profile.server_declared_profile_hash
        or resolved.declared_profile_hash != profile.server_declared_profile_hash
        or summary.contract_hash != profile.server_contract_hash
        or resolved.contract_hash != profile.server_contract_hash
        or summary.accepted_tool_version != profile.accepted_tool_version
        or resolved.tool_version != profile.accepted_tool_version
    ):
        raise ConfigurationError("VCS MCP remote identity differs from the verifier profile")


class McpVcsSimulationTool(VerifierBackendPlugin):
    descriptor = _descriptor()

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        path = os.environ.get("VERIGYM_VCS_MCP_PROFILE")
        if path is None:
            return HealthCheckResult(
                healthy=False,
                message="set VERIGYM_VCS_MCP_PROFILE to a fixed verifier profile",
            )
        try:
            profile = load_verifier_profile(path)
            resolved = self.resolve_verifier_profile(profile)
        except Exception as exc:
            return HealthCheckResult(healthy=False, message=redact(str(exc)))
        return HealthCheckResult(
            healthy=True,
            message="available (fixed verifier-only VCS MCP)",
            version=resolved.tool_version,
            executable=profile.transport_executable,
        )

    def resolve_verifier_profile(
        self,
        profile: VerifierToolProfile,
        *,
        expected: ResolvedVerifierToolProfile | None = None,
    ) -> ResolvedVerifierToolProfile:
        if profile.target_plugin != self.descriptor.name:
            raise ConfigurationError("verifier profile selects a different MCP backend")
        if profile.service_protocol != SERVICE_PROTOCOL or profile.server_version != SERVER_VERSION:
            raise ConfigurationError("unsupported VCS MCP service protocol or server version")
        executable, transport_hash = _transport_identity(
            profile.transport_executable,
            profile.transport_sha256,
        )
        arguments: dict[str, Any] = {
            "profile_id": profile.server_profile_id,
            "declared_profile_hash": profile.server_declared_profile_hash,
            "contract_hash": profile.server_contract_hash,
        }
        if expected is not None:
            arguments["expected_resolved_profile_hash"] = expected.server_resolved_profile_hash
        completed = _run_stdio(
            executable,
            _mcp_messages(RESOLVE_PROFILE_TOOL, arguments),
            environment_names=profile.transport_environment,
            timeout_s=30,
        )
        try:
            response = VcsResolveResponse.model_validate(
                _tool_response(completed, profile.server_version)
            )
        except Exception as exc:
            raise ConfigurationError(redact(str(exc))) from exc
        _validate_remote_identity(profile, response)
        payload: dict[str, Any] = {
            "profile_id": profile.id,
            "profile_version": profile.version,
            "declared_profile_hash": content_hash(profile),
            "task_id": profile.task_id,
            "source_plugin": profile.source_plugin,
            "target_plugin": profile.target_plugin,
            "runtime": profile.runtime,
            "transport_sha256": transport_hash,
            "service_protocol": profile.service_protocol,
            "server_version": profile.server_version,
            "server_profile_id": profile.server_profile_id,
            "server_declared_profile_hash": profile.server_declared_profile_hash,
            "server_resolved_profile_hash": (response.resolved_profile.resolved_profile_hash),
            "server_contract_hash": profile.server_contract_hash,
            "tool_version": response.resolved_profile.tool_version,
        }
        resolved = ResolvedVerifierToolProfile(
            **payload,
            resolved_profile_hash=content_hash(payload),
        )
        if expected is not None and resolved != expected:
            raise ConfigurationError("resolved VCS MCP identity differs from replay expectation")
        return resolved

    def validate_request(self, request: dict[str, Any]) -> VcsSimulationRequest:
        return VcsSimulationRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        raise RuntimeError("VCS MCP execution builds its transport command after source binding")

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        raise RuntimeError("VCS MCP execution validates its structured response directly")

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        completed_transport: CompletedCommand | None = None
        try:
            request = self.validate_request(raw_request)
            profile = context.verifier_profile
            resolved = context.resolved_verifier_profile
            if profile is None or resolved is None or context.session is None:
                raise ConfigurationError("VCS MCP execution lacks its resolved verifier context")
            if profile.target_plugin != self.descriptor.name:
                raise ConfigurationError("VCS MCP context selects a different backend")
            if request.executable != "vcs":
                raise ConfigurationError("VCS MCP verifier nodes cannot override the executable")
            if request.timeout_s > 3600:
                raise ConfigurationError("VCS MCP request timeout exceeds the service bound")
            total = 0
            sources: list[dict[str, str]] = []
            identities: dict[str, str] = {}
            for relative in request.sources:
                payload = _bounded_file(context.session.root, relative)
                total += len(payload)
                if total > _MAX_SOURCE_TOTAL_BYTES:
                    raise ConfigurationError("VCS MCP sources exceed the aggregate byte bound")
                digest = hash_bytes(payload)
                identities[relative] = digest
                sources.append(
                    {
                        "path": relative,
                        "sha256": digest,
                        "content_base64": base64.b64encode(payload).decode("ascii"),
                    }
                )
            testbench = _bounded_file(context.session.root, request.testbench)
            executable, _ = _transport_identity(
                profile.transport_executable,
                profile.transport_sha256,
            )
            candidate_hash = content_hash({"sources": identities})
            arguments = {
                "profile_id": profile.server_profile_id,
                "declared_profile_hash": profile.server_declared_profile_hash,
                "contract_hash": profile.server_contract_hash,
                "expected_resolved_profile_hash": resolved.server_resolved_profile_hash,
                "task_id": profile.task_id,
                "candidate_hash": candidate_hash,
                "sources": sources,
                "testbench_mount_path": request.testbench,
                "top": request.top,
                "pass_marker": request.pass_marker,
                "fail_marker": request.fail_marker,
            }
            command = CommandSpec(
                argv=[executable],
                cwd=".",
                env=_transport_environment(profile.transport_environment),
                timeout_s=request.timeout_s + 30,
                stdin=_mcp_messages(SIMULATE_TOOL, arguments),
            )
            completed_transport = context.session.execute(command)
            response = VcsSimulationResponse.model_validate(
                _tool_response(completed_transport, profile.server_version)
            )
            _validate_remote_identity(profile, response)
            if (
                response.resolved_profile.resolved_profile_hash
                != resolved.server_resolved_profile_hash
                or response.candidate_hash != candidate_hash
                or response.profile.testbench_sha256 != hash_bytes(testbench)
                or response.profile.sources != request.sources
                or response.profile.testbench_mount_path != request.testbench
                or response.profile.top != request.top
                or response.profile.pass_marker != request.pass_marker
                or response.profile.fail_marker != request.fail_marker
                or response.profile.timeout_s != request.timeout_s
            ):
                raise ConfigurationError("VCS MCP response differs from the fixed task contract")
            result = response.tool_result
            if (
                result.tool != self.descriptor.name
                or result.stdout
                or result.stderr
                or result.artifacts
                or result.diagnostics
                or set(result.metadata) != {"candidate_failure"}
                or not isinstance(result.metadata["candidate_failure"], bool)
            ):
                raise ConfigurationError("VCS MCP response exposed forbidden verifier details")
            return result.model_copy(update={"duration_s": time.monotonic() - started})
        except Exception as exc:
            message = redact(str(exc))
            category = ErrorCategory.INVALID_REQUEST
            if completed_transport is not None:
                if completed_transport.timed_out:
                    category = ErrorCategory.TIMEOUT
                elif completed_transport.output_truncated:
                    category = ErrorCategory.OUTPUT_LIMIT
                elif completed_transport.error is not None:
                    category = (
                        ErrorCategory.TOOL_NOT_FOUND
                        if "not found" in completed_transport.error.lower()
                        else ErrorCategory.SANDBOX_ERROR
                    )
                elif completed_transport.exit_code != 0:
                    category = ErrorCategory.SANDBOX_ERROR
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=category,
                message=message,
                duration_s=time.monotonic() - started,
                metadata={"candidate_failure": False},
            )


__all__ = ["McpVcsSimulationTool"]
