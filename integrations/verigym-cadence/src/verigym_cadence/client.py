"""Verifier plugin reusing VeriGym's resolved-profile and offline-replay identities."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from verigym.plugin_api import (
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
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec

from .protocol import (
    MAX_TOTAL_BYTES,
    MCP_VERSION,
    PROTOCOL,
    SERVER_NAME,
    VERSION,
    Outcome,
    ServerProfile,
    Summary,
    VerifyRequest,
    VerifyResponse,
    bounded_read,
    unique_json,
)

PROFILE_ENV = "VERIGYM_JASPERGOLD_MCP_PROFILE"


class SecRequest(StrictModel):
    sources: list[str] = Field(min_length=1, max_length=64)
    top: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    timeout_s: int = Field(default=300, ge=1, le=3600)

    @field_validator("sources")
    @classmethod
    def valid_sources(cls, values: list[str]) -> list[str]:
        return ServerProfile.source_paths(values)


def identity_request(profile: VerifierToolProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.server_profile_id,
        "declared_profile_hash": profile.server_declared_profile_hash,
        "contract_hash": profile.server_contract_hash,
    }


def rpc(profile: VerifierToolProfile, name: str, arguments: dict[str, Any], timeout: int) -> Any:
    executable = Path(profile.transport_executable)
    if (
        not executable.is_absolute()
        or not os.access(executable, os.X_OK)
        or hash_bytes(bounded_read(executable)) != profile.transport_sha256
    ):
        raise ConfigurationError("SEC transport identity unavailable or mismatched")
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "verigym", "version": VERSION},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    ]
    environment = {}
    for key in profile.transport_environment:
        if key not in os.environ:
            raise ConfigurationError("SEC transport environment is unavailable")
        environment[key] = os.environ[key]
    with tempfile.TemporaryDirectory(prefix="jg-client-") as empty:
        with LocalRuntime().create_session(
            SessionSpec(
                source_dir=empty,
                label="jg-client",
                max_output_bytes=65536,
                environment=environment,
            )
        ) as session:
            completed = session.execute(
                CommandSpec(
                    argv=[str(executable)],
                    stdin="".join(json.dumps(m) + "\n" for m in messages),
                    timeout_s=timeout,
                )
            )
    if completed.timed_out:
        raise TimeoutError("SEC transport timed out; no automatic retry")
    if completed.error or completed.output_truncated or completed.exit_code != 0:
        raise ConfigurationError("SEC transport failed")
    lines = completed.stdout.splitlines()
    if len(lines) != 2:
        raise ConfigurationError("SEC response framing is invalid")
    init, response = (unique_json(line) for line in lines)
    if (
        not isinstance(init, dict)
        or not isinstance(response, dict)
        or init.get("id") != 1
        or response.get("id") != 2
        or init.get("jsonrpc") != "2.0"
        or response.get("jsonrpc") != "2.0"
        or "error" in init
        or "error" in response
    ):
        raise ConfigurationError("SEC response was rejected")
    initialized = init.get("result", {})
    if initialized.get("protocolVersion") != MCP_VERSION or initialized.get("serverInfo") != {
        "name": SERVER_NAME,
        "version": profile.server_version,
    }:
        raise ConfigurationError("SEC server identity mismatch")
    result = response.get("result", {})
    if (
        set(result) != {"content", "structuredContent", "isError"}
        or result["content"] != []
        or result["isError"] is not False
    ):
        raise ConfigurationError("SEC response violates the hidden-output contract")
    return result["structuredContent"]


def check_summary(profile: VerifierToolProfile, summary: Summary) -> None:
    if (
        summary.protocol != profile.service_protocol
        or summary.server_version != profile.server_version
        or summary.profile_id != profile.server_profile_id
        or summary.task_id != profile.task_id
        or summary.tool_version != profile.accepted_tool_version
        or summary.declared_profile_hash != profile.server_declared_profile_hash
        or summary.contract_hash != profile.server_contract_hash
    ):
        raise ConfigurationError("SEC resolved identity differs from the frozen profile")


def tool_result(outcome: Outcome) -> ToolResult:
    categories = {
        "proven": ErrorCategory.SUCCESS,
        "counterexample": ErrorCategory.TEST_FAILED,
        "inconclusive": ErrorCategory.TOOL_FAILED,
        "candidate_compile_failure": ErrorCategory.COMPILE_FAILED,
        "timeout": ErrorCategory.TIMEOUT,
        "license_unavailable": ErrorCategory.LICENSE_UNAVAILABLE,
        "tool_unavailable": ErrorCategory.TOOL_NOT_FOUND,
        "infrastructure_failure": ErrorCategory.SANDBOX_ERROR,
    }
    return ToolResult(
        tool=JasperGoldMcpTool.descriptor.name,
        success=outcome.status == "proven",
        category=categories[outcome.status],
        message=outcome.status,
        metadata={
            "candidate_failure": outcome.status in {"counterexample", "candidate_compile_failure"},
            "formal_status": outcome.status,
        },
    )


class JasperGoldMcpTool(VerifierBackendPlugin):
    descriptor = ToolDescriptor(
        name="cadence.jaspergold.sec.mcp",
        version=VERSION,
        provider="verigym-cadence",
        capabilities=[
            "formal",
            "remote_mcp",
            "fixed_profile",
            "licensed",
            "approved_fixtures_only",
        ],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        path = os.environ.get(PROFILE_ENV)
        if path is None:
            return HealthCheckResult(
                healthy=False, message=f"set {PROFILE_ENV}; not site-qualified"
            )
        try:
            resolved = self.resolve_verifier_profile(load_verifier_profile(path))
            return HealthCheckResult(
                healthy=True,
                version=resolved.tool_version,
                message="fixed profile and versions resolved; license and suite not qualified",
            )
        except Exception:
            return HealthCheckResult(
                healthy=False, message="SEC profile/transport/tool unavailable"
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
        ):
            raise ConfigurationError("profile selects a different SEC backend")
        summary = Summary.model_validate(
            rpc(profile, "resolve_profile", identity_request(profile), 30)
        )
        check_summary(profile, summary)
        values = {
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
            {**values, "resolved_profile_hash": content_hash(values)}
        )
        if expected is not None and resolved != expected:
            raise ConfigurationError("SEC profile differs from the replay identity")
        return resolved

    def validate_request(self, request: dict[str, Any]) -> SecRequest:
        return SecRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        raise ConfigurationError("SEC uses only its resolved model-invisible transport")

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        raise ConfigurationError("SEC requires a typed MCP result")

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            request = self.validate_request(raw_request)
            profile, resolved = context.verifier_profile, context.resolved_verifier_profile
            if profile is None or resolved is None or context.session is None:
                raise ConfigurationError("SEC requires a resolved verifier context")
            if (
                profile.target_plugin != self.descriptor.name
                or resolved.declared_profile_hash != content_hash(profile)
                or content_hash(resolved.identity_payload()) != resolved.resolved_profile_hash
            ):
                raise ConfigurationError("SEC context identity mismatch")
            sources = []
            total = 0
            for path in request.sources:
                payload = bounded_read(context.session.root / path)
                total += len(payload)
                if total > MAX_TOTAL_BYTES:
                    raise ConfigurationError("candidate exceeds aggregate bound")
                sources.append(
                    {
                        "path": path,
                        "sha256": hash_bytes(payload),
                        "content_base64": base64.b64encode(payload).decode("ascii"),
                    }
                )
            candidate_hash = content_hash({"sources": {s["path"]: s["sha256"] for s in sources}})
            args = {
                **identity_request(profile),
                "task_id": profile.task_id,
                "top": request.top,
                "expected_resolved_profile_hash": resolved.server_resolved_profile_hash,
                "candidate_hash": candidate_hash,
                "sources": sources,
            }
            VerifyRequest.model_validate(args).candidate()
            if context.dispatch_callback is not None:
                context.dispatch_callback()
            response = VerifyResponse.model_validate(
                rpc(profile, "verify", args, request.timeout_s + 30)
            )
            check_summary(profile, response.profile)
            if (
                response.candidate_hash != candidate_hash
                or response.profile.sources != request.sources
                or response.profile.top != request.top
                or response.profile.resolved_profile_hash != resolved.server_resolved_profile_hash
            ):
                raise ConfigurationError("SEC candidate or resolved identity mismatch")
            return tool_result(response.outcome)
        except TimeoutError:
            return tool_result(Outcome(status="timeout"))
        except Exception:
            return tool_result(Outcome(status="infrastructure_failure"))
