"""Verifier-side synthesis backend for a restricted remote Synopsys MCP service."""

from __future__ import annotations

import base64
import binascii
import json
import os
import platform
import re
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    ArtifactDescriptor,
    CommandSpec,
    CompletedCommand,
    ConfigurationError,
    ErrorCategory,
    HealthCheckResult,
    ProfileValidationResult,
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
    Runtime,
    StrictModel,
    SynthesisArtifactRef,
    SynthesisBackendPlugin,
    SynthesisMetrics,
    ToolchainProfile,
    ToolContext,
    ToolDescriptor,
    ToolResult,
    ToolVisibility,
    content_hash,
    hash_bytes,
)

from .agent_worker_protocol import (
    AgentWorkerIsolationContract,
    AgentWorkerReceipt,
    agent_worker_contract_identity_payload,
)
from .common import redact, resolve_executable, safe_executable
from .dc import (
    AREA_TIMING_FLOW_TEMPLATE_HASH,
    AREA_TIMING_FLOW_TEMPLATE_ID,
    FLOW_TEMPLATE_HASH,
    FLOW_TEMPLATE_ID,
    LEGACY_FLOW_TEMPLATE_HASH,
    LEGACY_FLOW_TEMPLATE_ID,
    MULTICLOCK_FLOW_TEMPLATE_HASH,
    MULTICLOCK_FLOW_TEMPLATE_ID,
    VECTORLESS_POWER_FLOW_TEMPLATE_HASH,
    VECTORLESS_POWER_FLOW_TEMPLATE_ID,
    _read_session_file,
    _safe_relative,
)
from .mcp_server import (
    RESOLVE_PROFILE_TOOL,
    SERVER_VERSION,
    SERVICE_PROTOCOL,
    SYNTHESIZE_TOOL,
)
from .worker_release import COMMERCIAL_WORKER_RELEASE_PROTOCOL

_MCP_PROTOCOL_VERSION = "2024-11-05"
_MCP_SERVER_NAME = "verigym-synopsys-verifier"
_MCP_TOOL_NAME = "synopsys-dc-mcp"
_MAX_TRANSPORT_EXECUTABLE_BYTES = 16 * 1024 * 1024
_MAX_DIRECT_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_SOURCE_TOTAL_BYTES = 32 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_ARTIFACT_TOTAL_BYTES = 32 * 1024 * 1024
_TRANSPORT_ENVIRONMENT = {"SSH_AUTH_SOCK", "KRB5CCNAME"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TEMPLATE_HASHES = {
    LEGACY_FLOW_TEMPLATE_ID: LEGACY_FLOW_TEMPLATE_HASH,
    AREA_TIMING_FLOW_TEMPLATE_ID: AREA_TIMING_FLOW_TEMPLATE_HASH,
    VECTORLESS_POWER_FLOW_TEMPLATE_ID: VECTORLESS_POWER_FLOW_TEMPLATE_HASH,
    FLOW_TEMPLATE_ID: FLOW_TEMPLATE_HASH,
    MULTICLOCK_FLOW_TEMPLATE_ID: MULTICLOCK_FLOW_TEMPLATE_HASH,
}
_MCP_TOOL_ERROR_SUBCATEGORIES = {
    "agent feedback requires a configured disposable worker": "agent_worker_configuration",
    "agent worker executable identity changed before execution": "agent_worker_identity",
    "agent worker timed out": "agent_worker_timeout",
    "agent worker could not be started": "agent_worker_start",
    "agent worker exited unsuccessfully": "agent_worker_execution",
    "agent worker response exceeds the service bound": "agent_worker_response",
    "agent worker returned malformed JSON": "agent_worker_response",
    "agent worker returned a non-object response": "agent_worker_response",
    "agent worker envelope failed schema validation": "agent_worker_response",
    "agent worker receipt differs from the dispatched request": "agent_worker_identity",
    "agent worker reported an infrastructure failure": "agent_worker_infrastructure",
    "agent worker infrastructure failure: scheduler": "agent_worker_scheduler",
    "agent worker infrastructure failure: worker": "agent_worker_execution",
    "agent worker infrastructure failure: response": "agent_worker_response",
    "agent worker returned an invalid synthesis protocol": "agent_worker_response",
    "agent worker returned forbidden report or diagnostic content": "agent_worker_response",
}


class McpDesignCompilerRequest(StrictModel):
    sources: list[str] = Field(min_length=1, max_length=64)
    top: str
    transport_executable: str
    transport_sha256: str
    transport_environment: list[str] = Field(default_factory=list, max_length=8)
    server_profile_id: str
    server_declared_profile_hash: str
    server_resolved_profile_hash: str
    server_version: str
    reference_candidate_hash: str
    client_resolved_profile_hash: str
    generated_script_hash: str
    library_sha256: str
    constraints_sha256: str
    area_unit: str
    timing_unit: str
    power_unit: str | None = None
    power_activity_mode: str | None = None
    run_label: Literal["candidate", "reference", "agent_feedback"]
    transport_execution_boundary: Literal["runtime_session", "host_verifier_control_plane"] = (
        "runtime_session"
    )
    agent_worker_contract_hash: str | None = None
    agent_worker_code_identity_hash: str | None = None
    agent_worker_isolation_profile_hash: str | None = None
    expected_release_hash: str | None = None
    timeout_s: int = Field(default=900, ge=1, le=7200)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        normalized = [_safe_relative(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("MCP synthesis sources must not contain duplicates")
        if any(Path(item).suffix.lower() not in {".v", ".sv"} for item in normalized):
            raise ValueError("MCP synthesis sources must use .v or .sv filenames")
        return normalized

    @field_validator("transport_executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        return safe_executable(value)

    @field_validator("transport_environment")
    @classmethod
    def validate_environment(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or not set(value).issubset(_TRANSPORT_ENVIRONMENT):
            raise ValueError("unsupported MCP transport environment allowlist")
        return sorted(value)

    @field_validator("server_profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        if _PROFILE_ID.fullmatch(value) is None:
            raise ValueError("invalid MCP server profile ID")
        return value

    @field_validator(
        "transport_sha256",
        "server_declared_profile_hash",
        "server_resolved_profile_hash",
        "reference_candidate_hash",
        "client_resolved_profile_hash",
        "generated_script_hash",
        "library_sha256",
        "constraints_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("MCP synthesis identities must be lowercase SHA-256 values")
        return value

    @field_validator(
        "agent_worker_contract_hash",
        "agent_worker_code_identity_hash",
        "agent_worker_isolation_profile_hash",
        "expected_release_hash",
    )
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("MCP worker identity must be a lowercase SHA-256 value")
        return value

    @model_validator(mode="after")
    def validate_worker_label(self) -> McpDesignCompilerRequest:
        worker_fields = (
            self.agent_worker_contract_hash,
            self.agent_worker_code_identity_hash,
            self.agent_worker_isolation_profile_hash,
        )
        if self.run_label == "agent_feedback" and any(value is None for value in worker_fields):
            raise ValueError("agent feedback run label lacks its worker identities")
        if self.run_label != "agent_feedback" and any(value is not None for value in worker_fields):
            raise ValueError("agent feedback run label differs from its worker contract")
        return self


class McpProfileSummary(StrictModel):
    profile_id: str
    profile_version: str
    declared_profile_hash: str
    flow_template_id: str
    top: str
    sources: list[str]
    metric_scope: str
    area_unit: str | None
    timing_unit: str | None
    power_unit: str | None
    accepted_dc_version: str | None
    reproducibility_scope: str
    agent_feedback_worker_enabled: bool = False


class McpResolvedProfileSummary(StrictModel):
    profile_id: str
    profile_version: str
    declared_profile_hash: str
    resolved_profile_hash: str
    flow_template_id: str
    generated_script_hash: str
    top: str
    sources: list[str]
    metric_scope: str
    area_unit: str
    timing_unit: str | None
    power_unit: str | None
    reference_candidate_hash: str | None
    tool_versions: dict[str, str]
    asset_hashes: dict[str, str]
    flow_settings: dict[str, Any]


class McpAgentWorkerSummary(StrictModel):
    contract_hash: str
    launcher_sha256: str
    contract: AgentWorkerIsolationContract
    release_protocol: Literal["commercial_worker_release.v1"] | None = None
    release_hash: str | None = None

    @field_validator("contract_hash", "launcher_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("MCP worker summary requires lowercase SHA-256 identities")
        return value

    @field_validator("release_hash")
    @classmethod
    def validate_release_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("MCP worker release identity must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_release_pair(self) -> McpAgentWorkerSummary:
        if (self.release_protocol is None) != (self.release_hash is None):
            raise ValueError("MCP worker release protocol and hash must be paired")
        if self.release_protocol not in {None, COMMERCIAL_WORKER_RELEASE_PROTOCOL}:
            raise ValueError("MCP worker release protocol is unsupported")
        if (
            self.contract.release_hash is not None
            and self.release_hash != self.contract.release_hash
        ):
            raise ValueError("MCP worker contract and release identities differ")
        return self


class McpResolveResponse(StrictModel):
    protocol: Literal["verigym.synopsys.dc.mcp.v1"]
    profile: McpProfileSummary
    resolved_profile: McpResolvedProfileSummary
    agent_feedback_worker: McpAgentWorkerSummary | None = None


class McpExportedArtifact(SynthesisArtifactRef):
    content_base64: str | None = Field(default=None, max_length=24 * 1024 * 1024)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _safe_relative(value)

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("MCP artifact identity must be a lowercase SHA-256 value")
        return value


class McpSynthesisResponse(StrictModel):
    protocol: Literal["verigym.synopsys.dc.mcp.v1"]
    profile: McpProfileSummary
    resolved_profile: McpResolvedProfileSummary
    tool_result: ToolResult
    artifacts: list[McpExportedArtifact]
    agent_feedback_execution: AgentWorkerReceipt | None = None


class McpProtocolError(ValueError):
    """One caller-safe remote transport or response-contract error."""


class McpToolRejection(McpProtocolError):
    """One remote tool rejection reduced to an allowlisted safe subcategory."""

    def __init__(self, safe_subcategory: str) -> None:
        self.safe_subcategory = safe_subcategory
        super().__init__(f"MCP service rejected the verifier request: {safe_subcategory}")


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="synopsys.dc.mcp",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-synopsys",
        capabilities=[
            "synthesis",
            "mapped_area",
            "static_timing",
            "power_estimation",
            "remote_mcp",
            "licensed",
            "structured_errors",
        ],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )


def _runtime_identity(runtime: Runtime) -> ResolvedRuntimeIdentity:
    descriptor = runtime.descriptor
    image = descriptor.image
    resources = descriptor.resources
    resource_contract = (
        {
            "memory_bytes": resources.memory_bytes,
            "memory_swap_bytes": resources.memory_swap_bytes,
            "swap_enforced": resources.swap_enforced,
            "cpus": resources.cpus,
            "pids_limit": resources.pids_limit,
            "tmpfs_bytes": resources.tmpfs_bytes,
            "stop_timeout_s": resources.stop_timeout_s,
            "max_command_time_s": resources.max_command_time_s,
            "max_artifact_file_bytes": resources.max_artifact_file_bytes,
            "max_artifact_bytes": resources.max_artifact_bytes,
        }
        if resources is not None
        else None
    )
    return ResolvedRuntimeIdentity(
        runtime_slug=descriptor.name,
        isolation_level=descriptor.isolation_level,
        deterministic=descriptor.deterministic,
        os=image.os if image is not None else platform.system().lower(),
        architecture=image.architecture if image is not None else platform.machine(),
        requested_image_reference=(image.requested_reference if image is not None else None),
        resolved_image_id=image.resolved_image_id if image is not None else None,
        configuration_fingerprint=descriptor.configuration_fingerprint,
        network_policy=(descriptor.security.network_mode if descriptor.security else None),
        resource_controls=resources is not None,
        security_hash=(content_hash(descriptor.security) if descriptor.security else None),
        resource_contract_hash=(
            content_hash(resource_contract) if resource_contract is not None else None
        ),
    )


def _transport_identity(executable: str, expected_hash: str) -> tuple[str, str]:
    resolved_value = resolve_executable(executable)
    resolved = Path(resolved_value)
    try:
        metadata = os.lstat(resolved)
    except OSError as exc:
        raise ConfigurationError("MCP transport executable was not found") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > _MAX_TRANSPORT_EXECUTABLE_BYTES
        or not os.access(resolved, os.X_OK)
    ):
        raise ConfigurationError("MCP transport must be a bounded executable regular file")
    payload = resolved.read_bytes()
    actual_hash = hash_bytes(payload)
    if actual_hash != expected_hash:
        raise ConfigurationError("MCP transport executable hash differs from the profile")
    return str(resolved.resolve(strict=True)), actual_hash


def _transport_environment(names: list[str]) -> dict[str, str]:
    if not set(names).issubset(_TRANSPORT_ENVIRONMENT):
        raise ConfigurationError("MCP profile requests unsupported transport environment names")
    environment: dict[str, str] = {}
    for name in names:
        value = os.environ.get(name)
        if value is None:
            raise ConfigurationError(
                f"required MCP transport environment variable {name!r} is unset"
            )
        if "\x00" in value:
            raise ConfigurationError("MCP transport environment contains an invalid value")
        environment[name] = value
    return environment


def _mcp_messages(tool_name: str, arguments: dict[str, Any]) -> str:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "verigym-synopsys", "version": "0.1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
    ]
    return "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in messages)


def _mcp_list_messages() -> str:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "verigym-synopsys", "version": "0.1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    return "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in messages)


def _run_stdio(
    executable: str,
    stdin: str,
    *,
    environment_names: list[str],
    timeout_s: int,
) -> CompletedCommand:
    started = time.monotonic()
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        **_transport_environment(environment_names),
    }
    exit_code: int | None = None
    timed_out = False
    error: str | None = None
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                [executable],
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                env=environment,
                shell=False,
                text=False,
                start_new_session=True,
            )
            try:
                process.communicate(input=stdin.encode("utf-8"), timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
            exit_code = process.returncode
        except FileNotFoundError:
            error = "MCP transport executable was not found"
        except OSError:
            error = "MCP transport execution failed"
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout_bytes = stdout_file.read(_MAX_DIRECT_RESPONSE_BYTES + 1)
        stderr_bytes = stderr_file.read(64_001)
    truncated = len(stdout_bytes) > _MAX_DIRECT_RESPONSE_BYTES or len(stderr_bytes) > 64_000
    stdout = stdout_bytes[:_MAX_DIRECT_RESPONSE_BYTES].decode("utf-8", errors="replace")
    stderr = stderr_bytes[:64_000].decode("utf-8", errors="replace")
    return CompletedCommand(
        argv=[executable],
        cwd=".",
        exit_code=exit_code,
        stdout=stdout,
        stderr=redact(stderr),
        duration_s=time.monotonic() - started,
        timed_out=timed_out,
        output_truncated=truncated,
        error=error,
    )


def _parse_rpc_responses(
    completed: CompletedCommand,
    *,
    expected_server_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if completed.error:
        raise McpProtocolError(completed.error)
    if completed.timed_out:
        raise McpProtocolError("MCP transport timed out")
    if completed.output_truncated:
        raise McpProtocolError("MCP response exceeded the verifier output bound")
    if completed.exit_code != 0:
        raise McpProtocolError("MCP transport exited unsuccessfully")
    lines = completed.stdout.splitlines()
    if len(lines) != 2:
        raise McpProtocolError("MCP transport returned invalid response framing")
    try:
        initialized, response = (json.loads(line) for line in lines)
    except json.JSONDecodeError as exc:
        raise McpProtocolError("MCP transport returned malformed JSON") from exc
    if not isinstance(initialized, dict) or not isinstance(response, dict):
        raise McpProtocolError("MCP transport returned non-object JSON-RPC responses")
    if initialized.get("jsonrpc") != "2.0" or response.get("jsonrpc") != "2.0":
        raise McpProtocolError("MCP transport returned an invalid JSON-RPC version")
    init_result = initialized.get("result")
    if initialized.get("id") != 1 or not isinstance(init_result, dict):
        raise McpProtocolError("MCP initialize response is invalid")
    server_info = init_result.get("serverInfo")
    if (
        init_result.get("protocolVersion") != _MCP_PROTOCOL_VERSION
        or not isinstance(server_info, dict)
        or server_info.get("name") != _MCP_SERVER_NAME
        or server_info.get("version") != expected_server_version
    ):
        raise McpProtocolError("MCP server identity differs from the client profile")
    if response.get("id") != 2:
        raise McpProtocolError("MCP tool response has an unexpected request identity")
    if "error" in response:
        raise McpProtocolError("MCP server returned a JSON-RPC error")
    return initialized, response


def _parse_tool_response(
    completed: CompletedCommand,
    *,
    expected_server_version: str,
) -> dict[str, Any]:
    _, response = _parse_rpc_responses(
        completed,
        expected_server_version=expected_server_version,
    )
    result = response.get("result")
    if not isinstance(result, dict):
        raise McpProtocolError("MCP tool call returned no result object")
    if result.get("isError") is True:
        structured = result.get("structuredContent")
        error = structured.get("error") if isinstance(structured, dict) else None
        subcategory = (
            _MCP_TOOL_ERROR_SUBCATEGORIES.get(error, "mcp_service_rejected")
            if isinstance(error, str)
            else "mcp_service_rejected"
        )
        raise McpToolRejection(subcategory)
    structured = result.get("structuredContent")
    if not isinstance(structured, dict) or structured.get("protocol") != SERVICE_PROTOCOL:
        raise McpProtocolError("MCP tool call returned an invalid structured result")
    return structured


def _profile_metadata_string(profile: ToolchainProfile, name: str) -> str:
    value = profile.metadata.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"MCP profile metadata requires {name}")
    return value


class McpDesignCompilerSynthesisTool(SynthesisBackendPlugin):
    descriptor = _descriptor()
    artifact_namespace = "synopsys_dc_mcp"

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        executable = os.environ.get("VERIGYM_DC_MCP_EXECUTABLE")
        expected_hash = os.environ.get("VERIGYM_DC_MCP_TRANSPORT_SHA256")
        if executable is None or expected_hash is None or _SHA256.fullmatch(expected_hash) is None:
            return HealthCheckResult(
                healthy=False,
                message=(
                    "set VERIGYM_DC_MCP_EXECUTABLE and "
                    "VERIGYM_DC_MCP_TRANSPORT_SHA256, or validate a site profile"
                ),
            )
        try:
            resolved, _ = _transport_identity(executable, expected_hash)
            environment_names = sorted(
                name for name in _TRANSPORT_ENVIRONMENT if os.environ.get(name)
            )
            completed = _run_stdio(
                resolved,
                _mcp_list_messages(),
                environment_names=environment_names,
                timeout_s=20,
            )
            _, response = _parse_rpc_responses(
                completed,
                expected_server_version=SERVER_VERSION,
            )
            result = response.get("result")
            tools = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(tools, list):
                raise McpProtocolError("MCP server returned an invalid tool list")
            names = {item.get("name") for item in tools if isinstance(item, dict)}
            if SYNTHESIZE_TOOL not in names:
                raise McpProtocolError("MCP server does not expose the synthesis tool")
        except Exception as exc:
            return HealthCheckResult(healthy=False, message=redact(str(exc)))
        return HealthCheckResult(
            healthy=True,
            message="available (verifier-only remote MCP)",
            version=SERVER_VERSION,
            executable=resolved,
        )

    def validate_profile_contract(self, profile: ToolchainProfile) -> ProfileValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        if profile.flow is None or profile.metrics is None or profile.reference is None:
            return ProfileValidationResult(
                valid=False,
                errors=["profile has no complete synthesis, metric, and reference contract"],
            )
        if profile.flow.backend_plugin != self.descriptor.name:
            errors.append("profile selects a different synthesis backend")
        expected_template_hash = _TEMPLATE_HASHES.get(profile.flow.template_id)
        if expected_template_hash is None:
            errors.append("profile selects an unsupported remote DC flow template")
        power_flow = profile.flow.template_id in {
            VECTORLESS_POWER_FLOW_TEMPLATE_ID,
            FLOW_TEMPLATE_ID,
            MULTICLOCK_FLOW_TEMPLATE_ID,
        }
        expected_scope = "synthesis_area_timing_power" if power_flow else "synthesis_area_timing"
        if profile.metrics.scope != expected_scope:
            errors.append(f"remote DC flow requires metric scope {expected_scope!r}")
        allowed_runtimes = profile.runtime.allowed_runtimes or [profile.runtime.runtime]
        if sorted(allowed_runtimes) not in (["docker"], ["local"]):
            errors.append("the MCP client backend requires exactly local or Docker runtime")
        if allowed_runtimes == ["docker"]:
            if (
                profile.runtime.minimum_isolation_level != "docker_standard"
                or not profile.runtime.immutable_image_required
                or profile.runtime.network_policy != "none"
                or not profile.runtime.resource_controls_required
            ):
                errors.append("Docker MCP profiles require all docker_standard controls")
            prepared_image_id = profile.metadata.get("prepared_image_id")
            if (
                not isinstance(prepared_image_id, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", prepared_image_id) is None
            ):
                errors.append("Docker MCP profiles require a prepared immutable image ID")
            if profile.metadata.get("mcp_transport_execution_boundary") != (
                "host_verifier_control_plane"
            ):
                errors.append("Docker MCP transport must use the host verifier control plane")
        if profile.container_image != profile.runtime.requested_image:
            errors.append("MCP container image and requested runtime image differ")
        if profile.reproducibility_scope == "public":
            errors.append("remote licensed-tool profiles cannot claim public reproducibility")
        tools = [item for item in profile.tools if item.name == _MCP_TOOL_NAME]
        if len(tools) != 1 or tools[0].executable is None:
            errors.append("profile requires one fixed Synopsys MCP transport executable")
        elif tools[0].accepted_version != f"=={SERVER_VERSION}":
            errors.append("profile MCP server version does not match this client")
        transport_hash = profile.metadata.get("mcp_transport_sha256")
        if not isinstance(transport_hash, str) or _SHA256.fullmatch(transport_hash) is None:
            errors.append("profile requires an MCP transport executable hash")
        elif tools and tools[0].executable is not None:
            try:
                _transport_identity(tools[0].executable, transport_hash)
            except ConfigurationError as exc:
                errors.append(str(exc))
        for name in (
            "mcp_server_profile_id",
            "mcp_server_declared_profile_hash",
            "mcp_service_protocol",
            "mcp_server_version",
            "remote_design_compiler_version",
        ):
            try:
                _profile_metadata_string(profile, name)
            except ConfigurationError as exc:
                errors.append(str(exc))
        server_profile_id = profile.metadata.get("mcp_server_profile_id")
        if (
            not isinstance(server_profile_id, str)
            or _PROFILE_ID.fullmatch(server_profile_id) is None
        ):
            errors.append("server profile ID is invalid")
        server_profile_hash = profile.metadata.get("mcp_server_declared_profile_hash")
        if (
            not isinstance(server_profile_hash, str)
            or _SHA256.fullmatch(server_profile_hash) is None
        ):
            errors.append("server declared profile identity must be a lowercase SHA-256")
        if profile.metadata.get("mcp_service_protocol") != SERVICE_PROTOCOL:
            errors.append("profile MCP service protocol is unsupported")
        if profile.metadata.get("mcp_server_version") != SERVER_VERSION:
            errors.append("profile MCP server version is unsupported")
        worker_fields = {
            "agent_feedback_worker_contract_hash": profile.metadata.get(
                "agent_feedback_worker_contract_hash"
            ),
            "agent_feedback_worker_protocol": profile.metadata.get(
                "agent_feedback_worker_protocol"
            ),
            "agent_feedback_worker_isolation_kind": profile.metadata.get(
                "agent_feedback_worker_isolation_kind"
            ),
        }
        release_hash = profile.metadata.get(
            "agent_feedback_worker_release_hash",
            profile.metadata.get("commercial_worker_release_hash"),
        )
        release_protocol = profile.metadata.get(
            "agent_feedback_worker_release_protocol",
            profile.metadata.get("commercial_worker_release_protocol"),
        )
        if any(value is not None for value in worker_fields.values()):
            if not all(value is not None for value in worker_fields.values()):
                errors.append("agent feedback worker metadata must be declared as one contract")
            if (
                not isinstance(worker_fields["agent_feedback_worker_contract_hash"], str)
                or _SHA256.fullmatch(str(worker_fields["agent_feedback_worker_contract_hash"]))
                is None
            ):
                errors.append("agent feedback worker contract hash is invalid")
            if (
                worker_fields["agent_feedback_worker_protocol"]
                != "verigym.synopsys.dc.agent_worker.v1"
            ):
                errors.append("agent feedback worker protocol is unsupported")
            if worker_fields["agent_feedback_worker_isolation_kind"] not in {
                "lsf_job",
                "container",
                "vm",
            }:
                errors.append("agent feedback worker isolation kind is unsupported")
            if (release_hash is None) != (release_protocol is None):
                errors.append("commercial worker release metadata must be declared as one identity")
            if release_hash is not None and (
                not isinstance(release_hash, str) or _SHA256.fullmatch(release_hash) is None
            ):
                errors.append("commercial worker release hash is invalid")
            if (
                release_protocol is not None
                and release_protocol != COMMERCIAL_WORKER_RELEASE_PROTOCOL
            ):
                errors.append("commercial worker release protocol is unsupported")
        elif release_hash is not None or release_protocol is not None:
            errors.append("commercial worker release requires an agent feedback worker contract")
        if not set(profile.environment_allowlist).issubset(_TRANSPORT_ENVIRONMENT):
            errors.append("profile contains unsupported MCP transport environment names")
        libraries = [
            item for item in profile.libraries if item.media_type == "application/x-synopsys-db"
        ]
        constraints = [
            item
            for item in profile.constraints
            if isinstance(item, ArtifactDescriptor) and item.media_type == "application/x-sdc"
        ]
        generated = [
            item
            for item in profile.scripts
            if isinstance(item, ArtifactDescriptor) and item.source_kind == "generated"
        ]
        if len(libraries) != 1 or len(constraints) != 1:
            errors.append("profile requires one remote DB identity and one remote SDC identity")
        for descriptor in [*libraries, *constraints]:
            if (
                descriptor.source_kind != "remote_service"
                or descriptor.uri is not None
                or descriptor.copy_permitted
                or descriptor.content_hash is None
            ):
                errors.append(
                    f"remote asset {descriptor.name!r} must be hash-only and non-copyable"
                )
        if len(libraries) == 1 and libraries[0].unit != profile.metrics.area.unit:
            errors.append("remote DB area unit differs from the metric contract")
        if len(constraints) == 1 and constraints[0].unit != profile.metrics.delay.unit:
            errors.append("remote SDC timing unit differs from the metric contract")
        if len(generated) != 1 or generated[0].content_hash != expected_template_hash:
            errors.append("profile generated-flow descriptor does not match the remote backend")
        timing_unit = profile.metrics.delay.unit
        if timing_unit != profile.metrics.worst_negative_slack.unit:
            errors.append("delay and worst-negative-slack units must match")
        if power_flow and not profile.metrics.power.enabled:
            errors.append("remote power flow requires an enabled power metric")
        if profile.flow.template_id in {
            FLOW_TEMPLATE_ID,
            MULTICLOCK_FLOW_TEMPLATE_ID,
        }:
            if profile.metadata.get("power_activity_mode") != "global_clock_relative":
                errors.append("remote DC v4 profile requires explicit clock-relative activity")
            for name in ("power_activity", "power_static_probability", "power_base_clock"):
                if name not in profile.metadata:
                    errors.append(f"remote DC v4 profile requires {name}")
        warnings.append(
            "remote commercial results are comparable only by the client and server resolved hashes"
        )
        return ProfileValidationResult(valid=not errors, errors=errors, warnings=warnings)

    def resolve_profile(
        self,
        profile: ToolchainProfile,
        runtime: Runtime,
        *,
        source_paths: list[str],
        top_module: str,
        reference_candidate_hash: str | None,
        expected: ResolvedToolchainProfile | None = None,
    ) -> ResolvedToolchainProfile:
        validation = self.validate_profile_contract(profile)
        if not validation.valid:
            raise ConfigurationError("; ".join(validation.errors))
        assert profile.flow is not None
        assert profile.metrics is not None
        assert profile.reference is not None
        descriptor = runtime.descriptor
        allowed_runtimes = profile.runtime.allowed_runtimes or [profile.runtime.runtime]
        if descriptor.name not in allowed_runtimes:
            raise ConfigurationError("the MCP client backend runtime differs from the profile")
        if descriptor.name == "docker":
            image = descriptor.image
            if (
                image is None
                or image.resolved_image_id != profile.metadata.get("prepared_image_id")
                or image.requested_reference != profile.runtime.requested_image
                or descriptor.isolation_level != "docker_standard"
                or descriptor.security is None
                or descriptor.security.network_mode != "none"
                or descriptor.resources is None
            ):
                raise ConfigurationError(
                    "Docker MCP runtime differs from the prepared immutable control contract"
                )
        if source_paths != profile.flow.default_sources or top_module != profile.flow.top_module:
            raise ConfigurationError("task sources/top differ from the remote DC profile")
        if reference_candidate_hash is None or _SHA256.fullmatch(reference_candidate_hash) is None:
            raise ConfigurationError("remote DC resolution requires a reference-candidate hash")
        requirement = next(item for item in profile.tools if item.name == _MCP_TOOL_NAME)
        assert requirement.executable is not None
        transport_hash = _profile_metadata_string(profile, "mcp_transport_sha256")
        executable, transport_hash = _transport_identity(
            requirement.executable,
            transport_hash,
        )
        server_profile_id = _profile_metadata_string(profile, "mcp_server_profile_id")
        server_declared_hash = _profile_metadata_string(
            profile,
            "mcp_server_declared_profile_hash",
        )
        expected_server_hash = None
        if expected is not None:
            raw_expected = expected.metadata.get("mcp_server_resolved_profile_hash")
            if isinstance(raw_expected, str):
                expected_server_hash = raw_expected
        expected_release_hash = None
        for key in (
            "agent_feedback_worker_release_hash",
            "commercial_worker_release_hash",
        ):
            raw_release = profile.metadata.get(key)
            if isinstance(raw_release, str):
                expected_release_hash = raw_release
                break
        arguments: dict[str, Any] = {
            "profile_id": server_profile_id,
            "declared_profile_hash": server_declared_hash,
            "reference_candidate_hash": reference_candidate_hash,
        }
        if expected_server_hash is not None:
            arguments["expected_resolved_profile_hash"] = expected_server_hash
        if expected_release_hash is not None:
            arguments["expected_release_hash"] = expected_release_hash
        completed = _run_stdio(
            executable,
            _mcp_messages(RESOLVE_PROFILE_TOOL, arguments),
            environment_names=profile.environment_allowlist,
            timeout_s=30,
        )
        try:
            response = McpResolveResponse.model_validate(
                _parse_tool_response(
                    completed,
                    expected_server_version=SERVER_VERSION,
                )
            )
            self._validate_remote_identity(profile, response.profile, response.resolved_profile)
            self._validate_agent_worker_identity(profile, response.agent_feedback_worker)
        except ValidationError as exc:
            raise ConfigurationError("MCP resolve response failed schema validation") from exc
        except (McpProtocolError, ValueError) as exc:
            raise ConfigurationError(redact(str(exc))) from exc
        remote = response.resolved_profile
        worker = response.agent_feedback_worker
        if remote.reference_candidate_hash != reference_candidate_hash:
            raise ConfigurationError(
                "MCP server reference-candidate identity differs from the requested profile"
            )
        descriptors: list[ArtifactDescriptor] = [*profile.libraries]
        descriptors.extend(
            item for item in profile.constraints if isinstance(item, ArtifactDescriptor)
        )
        descriptors.extend(item for item in profile.scripts if isinstance(item, ArtifactDescriptor))
        assets = [
            ResolvedArtifactIdentity(
                logical_id=item.name,
                media_type=item.media_type or "application/octet-stream",
                source_kind=item.source_kind or "remote_service",
                content_hash=cast(str, item.content_hash),
                license=item.license,
                attribution=item.attribution,
                redistributable=item.redistributable is True,
                unit=item.unit,
                semantics=item.semantics,
                copy_permitted=item.copy_permitted,
                replay_locator=None,
            )
            for item in descriptors
        ]
        tool_identity = ResolvedToolIdentity(
            logical_name=_MCP_TOOL_NAME,
            executable=executable,
            version=SERVER_VERSION,
            version_output=f"{_MCP_SERVER_NAME} {SERVER_VERSION}",
            executable_sha256=transport_hash,
            capabilities=["remote_mcp", "synthesis", "mapped_area", "static_timing"],
            identity_kind="local_executable",
        )
        library = next(item for item in assets if item.media_type == "application/x-synopsys-db")
        unresolved = ResolvedToolchainProfile(
            profile_id=profile.id,
            profile_version=profile.version,
            declared_profile_hash=content_hash(profile),
            resolved_profile_hash="",
            reproducibility_scope=profile.reproducibility_scope,
            deterministic=profile.deterministic,
            runtime_identity=_runtime_identity(runtime),
            tool_identities=[tool_identity],
            asset_identities=sorted(assets, key=lambda item: item.logical_id),
            flow_hash=content_hash(profile.flow),
            metric_contract_hash=content_hash(profile.metrics),
            reference_contract_hash=content_hash(profile.reference),
            flow_template_id=remote.flow_template_id,
            generated_script_hash=remote.generated_script_hash,
            top_module=top_module,
            source_paths=source_paths,
            metric_scope=profile.metrics.scope,
            area_unit=library.unit or remote.area_unit,
            timing_unit=profile.metrics.delay.unit,
            power_unit=(profile.metrics.power.unit if profile.metrics.power.enabled else None),
            reference_strategy=profile.reference.strategy,
            reference_candidate_hash=reference_candidate_hash,
            metadata={
                "mcp_service_protocol": SERVICE_PROTOCOL,
                "mcp_server_version": SERVER_VERSION,
                "mcp_server_profile_id": server_profile_id,
                "mcp_server_declared_profile_hash": server_declared_hash,
                "mcp_server_resolved_profile_hash": remote.resolved_profile_hash,
                "mcp_transport_sha256": transport_hash,
                "remote_tool_versions": remote.tool_versions,
                "remote_asset_hashes": remote.asset_hashes,
                "clock_period": profile.metadata.get("clock_period"),
                "power_activity_mode": profile.metadata.get("power_activity_mode"),
                "power_activity": profile.metadata.get("power_activity"),
                "power_static_probability": profile.metadata.get("power_static_probability"),
                "power_base_clock": profile.metadata.get("power_base_clock"),
                **(
                    {
                        "agent_feedback_worker_contract_hash": worker.contract_hash,
                        "agent_feedback_worker_contract": worker.contract.model_dump(mode="json"),
                        "agent_feedback_worker_isolation_kind": worker.contract.isolation_kind,
                        **(
                            {
                                "agent_feedback_worker_release_protocol": worker.release_protocol,
                                "agent_feedback_worker_release_hash": worker.release_hash,
                                "commercial_worker_release_protocol": worker.release_protocol,
                                "commercial_worker_release_hash": worker.release_hash,
                            }
                            if worker.release_hash is not None
                            else {}
                        ),
                    }
                    if worker is not None
                    and profile.metadata.get("agent_feedback_worker_contract_hash") is not None
                    else {}
                ),
            },
        )
        resolved = unresolved.model_copy(
            update={"resolved_profile_hash": content_hash(unresolved.identity_payload())}
        )
        if (
            expected is not None
            and resolved.resolved_profile_hash != expected.resolved_profile_hash
        ):
            raise ConfigurationError("resolved MCP profile differs from the exact replay identity")
        return resolved

    def _validate_remote_identity(
        self,
        profile: ToolchainProfile,
        summary: McpProfileSummary,
        resolved: McpResolvedProfileSummary,
    ) -> None:
        assert profile.flow is not None
        assert profile.metrics is not None
        server_profile_id = _profile_metadata_string(profile, "mcp_server_profile_id")
        server_hash = _profile_metadata_string(profile, "mcp_server_declared_profile_hash")
        expected = (
            summary.profile_id == server_profile_id,
            summary.declared_profile_hash == server_hash,
            summary.top == profile.flow.top_module,
            summary.sources == profile.flow.default_sources,
            summary.flow_template_id == profile.flow.template_id,
            summary.metric_scope == profile.metrics.scope,
            summary.area_unit == profile.metrics.area.unit,
            summary.timing_unit == profile.metrics.delay.unit,
            summary.power_unit
            == (profile.metrics.power.unit if profile.metrics.power.enabled else None),
            resolved.profile_id == server_profile_id,
            resolved.declared_profile_hash == server_hash,
            resolved.top == profile.flow.top_module,
            resolved.sources == profile.flow.default_sources,
            resolved.flow_template_id == profile.flow.template_id,
            resolved.metric_scope == profile.metrics.scope,
            resolved.area_unit == profile.metrics.area.unit,
            resolved.timing_unit == profile.metrics.delay.unit,
            resolved.power_unit
            == (profile.metrics.power.unit if profile.metrics.power.enabled else None),
        )
        if not all(expected):
            raise McpProtocolError("MCP server profile differs from the client contract")
        declared_assets = {
            item.name: item.content_hash
            for item in [
                *profile.libraries,
                *(item for item in profile.constraints if isinstance(item, ArtifactDescriptor)),
                *(item for item in profile.scripts if isinstance(item, ArtifactDescriptor)),
            ]
        }
        if resolved.asset_hashes != declared_assets:
            raise McpProtocolError("MCP server asset identities differ from the client profile")
        if resolved.reference_candidate_hash is None:
            raise McpProtocolError("MCP server omitted the reference-candidate identity")
        dc_version = resolved.tool_versions.get("design-compiler")
        accepted_dc_version = profile.metadata.get("remote_design_compiler_version")
        if dc_version is None:
            raise McpProtocolError("MCP server omitted the Design Compiler version")
        if (
            summary.accepted_dc_version != accepted_dc_version
            or accepted_dc_version != f"=={dc_version}"
        ):
            raise McpProtocolError("MCP server Design Compiler requirement differs from the client")
        expected_flow_settings = {
            name: profile.metadata[name]
            for name in (
                "clock_period",
                "power_activity_mode",
                "power_activity",
                "power_static_probability",
                "power_base_clock",
            )
            if name in profile.metadata
        }
        if resolved.flow_settings != expected_flow_settings:
            raise McpProtocolError("MCP server flow settings differ from the client profile")

    def _validate_agent_worker_identity(
        self,
        profile: ToolchainProfile,
        worker: McpAgentWorkerSummary | None,
    ) -> None:
        expected_hash = profile.metadata.get("agent_feedback_worker_contract_hash")
        if expected_hash is None:
            return
        if worker is None:
            raise McpProtocolError("MCP server omitted the required agent feedback worker")
        computed = content_hash(
            {
                "launcher_sha256": worker.launcher_sha256,
                "isolation_contract": agent_worker_contract_identity_payload(worker.contract),
            }
        )
        if computed != worker.contract_hash or worker.contract_hash != expected_hash:
            raise McpProtocolError("MCP agent feedback worker contract differs from the profile")
        if worker.contract.protocol != profile.metadata.get(
            "agent_feedback_worker_protocol"
        ) or worker.contract.isolation_kind != profile.metadata.get(
            "agent_feedback_worker_isolation_kind"
        ):
            raise McpProtocolError("MCP agent feedback worker isolation differs from the profile")
        expected_release_hash = profile.metadata.get(
            "agent_feedback_worker_release_hash",
            profile.metadata.get("commercial_worker_release_hash"),
        )
        expected_release_protocol = profile.metadata.get(
            "agent_feedback_worker_release_protocol",
            profile.metadata.get("commercial_worker_release_protocol"),
        )
        if expected_release_hash is not None:
            if (
                worker.release_protocol != expected_release_protocol
                or worker.release_hash != expected_release_hash
                or worker.contract.release_protocol != expected_release_protocol
                or worker.contract.release_hash != expected_release_hash
            ):
                raise McpProtocolError("MCP commercial worker release differs from the profile")

    def build_synthesis_request(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
        *,
        run_label: str,
    ) -> dict[str, Any]:
        if run_label not in {"candidate", "reference", "agent_feedback"}:
            raise ValueError("synthesis run label must be candidate, reference, or agent_feedback")
        if run_label == "agent_feedback" and not resolved.metadata.get(
            "agent_feedback_worker_contract_hash"
        ):
            raise ValueError("resolved MCP profile has no disposable agent feedback worker")
        transport = next(
            item for item in resolved.tool_identities if item.logical_name == _MCP_TOOL_NAME
        )
        library = next(
            item
            for item in resolved.asset_identities
            if item.media_type == "application/x-synopsys-db"
        )
        constraints = next(
            item for item in resolved.asset_identities if item.media_type == "application/x-sdc"
        )
        if transport.executable_sha256 is None or resolved.reference_candidate_hash is None:
            raise ValueError("resolved MCP profile lacks transport or reference identity")
        request = McpDesignCompilerRequest(
            sources=resolved.source_paths,
            top=resolved.top_module,
            transport_executable=transport.executable,
            transport_sha256=transport.executable_sha256,
            transport_environment=profile.environment_allowlist,
            server_profile_id=str(resolved.metadata["mcp_server_profile_id"]),
            server_declared_profile_hash=str(resolved.metadata["mcp_server_declared_profile_hash"]),
            server_resolved_profile_hash=str(resolved.metadata["mcp_server_resolved_profile_hash"]),
            server_version=str(resolved.metadata["mcp_server_version"]),
            reference_candidate_hash=resolved.reference_candidate_hash,
            client_resolved_profile_hash=resolved.resolved_profile_hash,
            generated_script_hash=resolved.generated_script_hash,
            library_sha256=library.content_hash,
            constraints_sha256=constraints.content_hash,
            area_unit=resolved.area_unit,
            timing_unit=resolved.timing_unit or "",
            power_unit=resolved.power_unit,
            power_activity_mode=cast(str | None, resolved.metadata.get("power_activity_mode")),
            run_label=run_label,  # type: ignore[arg-type]
            transport_execution_boundary=(
                "host_verifier_control_plane"
                if resolved.runtime_identity.runtime_slug == "docker"
                else "runtime_session"
            ),
            agent_worker_contract_hash=(
                cast(
                    str | None,
                    resolved.metadata.get("agent_feedback_worker_contract_hash"),
                )
                if run_label == "agent_feedback"
                else None
            ),
            agent_worker_code_identity_hash=(
                cast(
                    str,
                    resolved.metadata["agent_feedback_worker_contract"]["code_identity_hash"],
                )
                if run_label == "agent_feedback"
                else None
            ),
            agent_worker_isolation_profile_hash=(
                cast(
                    str,
                    resolved.metadata["agent_feedback_worker_contract"]["isolation_profile_hash"],
                )
                if run_label == "agent_feedback"
                else None
            ),
            expected_release_hash=(
                cast(
                    str | None,
                    resolved.metadata.get(
                        "agent_feedback_worker_release_hash",
                        resolved.metadata.get("commercial_worker_release_hash"),
                    ),
                )
                if run_label == "agent_feedback"
                else None
            ),
        )
        return request.model_dump(mode="json")

    def build_agent_feedback_request(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
    ) -> dict[str, Any]:
        return self.build_synthesis_request(profile, resolved, run_label="agent_feedback")

    def stage_profile_assets(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
        staging: Path,
    ) -> None:
        del staging
        if content_hash(profile) != resolved.declared_profile_hash:
            raise ConfigurationError("MCP client profile changed before synthesis staging")

    def validate_request(self, request: dict[str, Any]) -> McpDesignCompilerRequest:
        return McpDesignCompilerRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, McpDesignCompilerRequest)
        if context.session is None:
            raise ValueError("MCP synthesis requires a verifier runtime session")
        executable, _ = _transport_identity(
            request.transport_executable,
            request.transport_sha256,
        )
        total = 0
        sources: list[dict[str, str]] = []
        for relative in request.sources:
            payload = _read_session_file(context.session.root, relative, _MAX_SOURCE_BYTES)
            total += len(payload)
            if total > _MAX_SOURCE_TOTAL_BYTES:
                raise ValueError("MCP synthesis sources exceed the aggregate byte limit")
            sources.append(
                {
                    "path": relative,
                    "sha256": hash_bytes(payload),
                    "content_base64": base64.b64encode(payload).decode("ascii"),
                }
            )
        arguments = {
            "profile_id": request.server_profile_id,
            "declared_profile_hash": request.server_declared_profile_hash,
            "reference_candidate_hash": request.reference_candidate_hash,
            "expected_resolved_profile_hash": request.server_resolved_profile_hash,
            "top": request.top,
            "sources": sources,
            "run_label": request.run_label,
            "artifact_content_policy": (
                "none" if request.run_label == "agent_feedback" else "reports"
            ),
        }
        if request.expected_release_hash is not None:
            arguments["expected_release_hash"] = request.expected_release_hash
        return CommandSpec(
            argv=[executable],
            cwd=".",
            env=(
                _transport_environment(request.transport_environment)
                if request.transport_execution_boundary == "runtime_session"
                else {}
            ),
            timeout_s=request.timeout_s,
            stdin=_mcp_messages(SYNTHESIZE_TOOL, arguments),
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, McpDesignCompilerRequest)
        category: ErrorCategory | None = None
        message = ""
        if completed.error:
            category = (
                ErrorCategory.TOOL_NOT_FOUND
                if "not found" in completed.error.lower()
                else ErrorCategory.SANDBOX_ERROR
            )
            message = completed.error
        elif completed.timed_out:
            category = ErrorCategory.TIMEOUT
            message = "remote Design Compiler MCP transport timed out"
        elif completed.output_truncated:
            category = ErrorCategory.OUTPUT_LIMIT
            message = "remote Design Compiler MCP response exceeded the verifier output bound"
        elif completed.exit_code != 0:
            category = ErrorCategory.SANDBOX_ERROR
            message = "remote Design Compiler MCP transport exited unsuccessfully"
        if category is not None:
            return self._failure(request, completed, category, message)
        try:
            response = McpSynthesisResponse.model_validate(
                _parse_tool_response(
                    completed,
                    expected_server_version=request.server_version,
                )
            )
            self._validate_synthesis_response(request, response)
            server_metrics = SynthesisMetrics.model_validate(
                response.tool_result.metadata.get("synthesis")
            )
            artifacts = self._import_artifacts(request, response, context)
        except ValidationError:
            return self._failure(
                request,
                completed,
                ErrorCategory.PARSER_ERROR,
                "MCP synthesis response failed schema validation",
            )
        except McpToolRejection as exc:
            return self._failure(
                request,
                completed,
                ErrorCategory.PARSER_ERROR,
                str(exc),
                failure_category=exc.safe_subcategory,
            )
        except (McpProtocolError, ValueError, OSError) as exc:
            return self._failure(
                request,
                completed,
                ErrorCategory.PARSER_ERROR,
                redact(str(exc)),
            )
        tool_identity = {
            **server_metrics.tool_identity,
            "mcp_server_profile_hash": request.server_declared_profile_hash,
            "mcp_server_resolved_profile_hash": request.server_resolved_profile_hash,
            "mcp_server_version": request.server_version,
            "mcp_transport_sha256": request.transport_sha256,
        }
        metrics = server_metrics.model_copy(
            update={
                "resolved_profile_hash": request.client_resolved_profile_hash,
                "tool_identity": tool_identity,
                "artifacts": artifacts,
            }
        )
        metadata = dict(response.tool_result.metadata)
        metadata["synthesis"] = metrics.model_dump(mode="json")
        metadata["mcp_server_resolved_profile_hash"] = request.server_resolved_profile_hash
        if response.agent_feedback_execution is not None:
            metadata["agent_feedback_execution"] = response.agent_feedback_execution.model_dump(
                mode="json"
            )
        return ToolResult(
            tool=self.descriptor.name,
            success=response.tool_result.success,
            category=response.tool_result.category,
            message=response.tool_result.message,
            exit_code=response.tool_result.exit_code,
            duration_s=completed.duration_s,
            output_truncated=False,
            artifacts=[item.path for item in artifacts] if request.run_label == "candidate" else [],
            diagnostics=(
                response.tool_result.diagnostics if request.run_label == "candidate" else []
            ),
            metadata=metadata,
        )

    def _validate_synthesis_response(
        self,
        request: McpDesignCompilerRequest,
        response: McpSynthesisResponse,
    ) -> None:
        if response.tool_result.tool != "synopsys.dc.synth":
            raise McpProtocolError("MCP service returned a result from an unexpected backend")
        if (
            response.profile.profile_id != request.server_profile_id
            or response.profile.declared_profile_hash != request.server_declared_profile_hash
            or response.profile.top != request.top
            or response.profile.sources != request.sources
            or response.resolved_profile.resolved_profile_hash
            != request.server_resolved_profile_hash
            or response.resolved_profile.reference_candidate_hash
            != request.reference_candidate_hash
            or response.resolved_profile.generated_script_hash != request.generated_script_hash
        ):
            raise McpProtocolError("MCP synthesis response identity differs from the request")
        metrics = SynthesisMetrics.model_validate(response.tool_result.metadata.get("synthesis"))
        expected_role = "candidate" if request.run_label == "agent_feedback" else request.run_label
        if (
            metrics.role != expected_role
            or metrics.top != request.top
            or metrics.resolved_profile_hash != request.server_resolved_profile_hash
            or metrics.generated_script_hash != request.generated_script_hash
        ):
            raise McpProtocolError("MCP synthesis metrics identity differs from the request")
        if request.run_label == "agent_feedback":
            receipt = response.agent_feedback_execution
            if (
                receipt is None
                or receipt.contract_hash != request.agent_worker_contract_hash
                or receipt.code_identity_hash != request.agent_worker_code_identity_hash
                or receipt.isolation_profile_hash != request.agent_worker_isolation_profile_hash
                or receipt.release_hash != request.expected_release_hash
                or (
                    request.expected_release_hash is not None
                    and receipt.release_protocol != COMMERCIAL_WORKER_RELEASE_PROTOCOL
                )
                or not receipt.scheduler_dispatched
                or not receipt.worker_started
                or not receipt.worker_completed
                or not receipt.cleanup_complete
                or response.artifacts
                or response.tool_result.artifacts
                or response.tool_result.diagnostics
                or metrics.artifacts
            ):
                raise McpProtocolError("MCP agent feedback worker receipt is incomplete")
        elif response.agent_feedback_execution is not None:
            raise McpProtocolError("final synthesis unexpectedly returned an agent worker receipt")
        if metrics.mapped_area_raw is not None and (
            metrics.mapped_area_unit != request.area_unit
            or metrics.mapped_area_source_hash != request.library_sha256
        ):
            raise McpProtocolError("MCP area identity differs from the client profile")
        if metrics.critical_path_delay_raw is not None and (
            metrics.timing_unit != request.timing_unit
            or metrics.timing_constraints_hash != request.constraints_sha256
        ):
            raise McpProtocolError("MCP timing identity differs from the client profile")
        if metrics.total_power_raw is not None and (
            metrics.power_unit != request.power_unit
            or metrics.power_activity_mode != request.power_activity_mode
        ):
            raise McpProtocolError("MCP power identity differs from the client profile")
        refs = {item.path: item for item in metrics.artifacts}
        records = {item.path: item for item in response.artifacts}
        if len(refs) != len(metrics.artifacts) or len(records) != len(response.artifacts):
            raise McpProtocolError("MCP synthesis artifacts contain duplicate paths")
        if set(refs) != set(records):
            raise McpProtocolError("MCP synthesis artifact list differs from its metrics")
        for path, ref in refs.items():
            record = records[path]
            if record.model_dump(exclude={"content_base64"}) != ref.model_dump():
                raise McpProtocolError("MCP synthesis artifact identity is inconsistent")
            if request.run_label == "reference" and record.content_base64 is not None:
                raise McpProtocolError("MCP service exported reference artifact content")

    def _import_artifacts(
        self,
        request: McpDesignCompilerRequest,
        response: McpSynthesisResponse,
        context: ToolContext,
    ) -> list[SynthesisArtifactRef]:
        server_metrics = SynthesisMetrics.model_validate(
            response.tool_result.metadata.get("synthesis")
        )
        refs = {item.path: item for item in server_metrics.artifacts}
        if request.run_label in {"reference", "agent_feedback"}:
            return list(refs.values())
        imported: list[SynthesisArtifactRef] = []
        total = 0
        for record in response.artifacts:
            if record.content_base64 is None:
                continue
            try:
                payload = base64.b64decode(record.content_base64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise McpProtocolError("MCP artifact content is not canonical base64") from exc
            if len(payload) > _MAX_ARTIFACT_BYTES:
                raise McpProtocolError("one MCP artifact exceeds the client import bound")
            total += len(payload)
            if total > _MAX_ARTIFACT_TOTAL_BYTES:
                raise McpProtocolError("MCP artifacts exceed the client import bound")
            if len(payload) != record.size_bytes or hash_bytes(payload) != record.content_hash:
                raise McpProtocolError("MCP artifact content differs from its identity")
            if context.artifact_dir is not None:
                context.artifact_dir.mkdir(parents=True, exist_ok=True)
                target = context.artifact_dir / _safe_relative(record.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            imported.append(refs[record.path])
        flow = next((item for item in imported if item.role == "generated_script"), None)
        if flow is None or flow.content_hash != request.generated_script_hash:
            raise McpProtocolError("MCP candidate response omitted the generated script artifact")
        return imported

    def _failure(
        self,
        request: McpDesignCompilerRequest,
        completed: CompletedCommand,
        category: ErrorCategory,
        message: str,
        *,
        failure_category: str | None = None,
    ) -> ToolResult:
        sanitized = redact(message)
        metrics = SynthesisMetrics(
            status="error",
            synthesis_ok=False,
            role="candidate" if request.run_label == "agent_feedback" else request.run_label,
            top=request.top,
            tool_identity={
                "mcp_server_resolved_profile_hash": request.server_resolved_profile_hash,
                "mcp_transport_sha256": request.transport_sha256,
            },
            resolved_profile_hash=request.client_resolved_profile_hash,
            generated_script_hash=request.generated_script_hash,
            failure_category=failure_category or category.value,
            failure_message=sanitized,
        )
        return ToolResult(
            tool=self.descriptor.name,
            success=False,
            category=category,
            message=sanitized,
            exit_code=completed.exit_code,
            duration_s=completed.duration_s,
            output_truncated=completed.output_truncated,
            metadata={
                "candidate_failure": False,
                "synthesis": metrics.model_dump(mode="json"),
            },
        )

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        try:
            request = self.validate_request(raw_request)
            if request.transport_execution_boundary == "host_verifier_control_plane":
                command = self.build_command(request, context)
                if command.requires_shell or command.stdin is None:
                    raise ValueError("MCP control-plane transport command is malformed")
                if context.dispatch_callback is not None:
                    context.dispatch_callback()
                completed = _run_stdio(
                    command.argv[0],
                    command.stdin,
                    environment_names=request.transport_environment,
                    timeout_s=command.timeout_s,
                )
                return self.parse_result(request, completed, context)
            return super().execute(raw_request, context)
        except Exception as exc:
            message = redact(str(exc))
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=ErrorCategory.INVALID_REQUEST,
                message=message,
                duration_s=time.monotonic() - started,
                metadata={"candidate_failure": False},
            )


__all__ = [
    "McpDesignCompilerRequest",
    "McpDesignCompilerSynthesisTool",
]
