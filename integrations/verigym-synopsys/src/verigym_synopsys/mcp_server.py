"""Restricted MCP stdio service for verifier-owned Design Compiler execution."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from verigym.plugin_api import (
    ConfigurationError,
    ResolvedToolchainProfile,
    StrictModel,
    SynthesisArtifactRef,
    ToolContext,
    ToolResult,
    content_hash,
    hash_bytes,
)
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.common import ToolchainProfile
from verigym.schemas.runtime import SessionSpec

from .common import redact
from .dc import DesignCompilerSynthesisTool, _safe_relative

_PROTOCOL_VERSION = "2024-11-05"
SERVER_VERSION = "0.1.0"
SERVICE_PROTOCOL = "verigym.synopsys.dc.mcp.v1"
_MAX_MESSAGE_BYTES = 48 * 1024 * 1024
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_SOURCE_TOTAL_BYTES = 32 * 1024 * 1024
_MAX_EXPORTED_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_EXPORTED_ARTIFACT_TOTAL_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

LIST_PROFILES_TOOL = "verigym.synopsys.dc.list_profiles"
RESOLVE_PROFILE_TOOL = "verigym.synopsys.dc.resolve_profile"
SYNTHESIZE_TOOL = "verigym.synopsys.dc.synthesize"


class McpSource(StrictModel):
    """One hash-bound RTL source transported to the private MCP service."""

    path: str = Field(min_length=1, max_length=4096)
    sha256: str
    content_base64: str = Field(max_length=12 * 1024 * 1024)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = _safe_relative(value)
        if Path(normalized).suffix.lower() not in {".v", ".sv"}:
            raise ValueError("MCP synthesis sources must use .v or .sv filenames")
        return normalized

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("source identity must be a lowercase SHA-256 value")
        return value

    def decode(self) -> bytes:
        try:
            payload = base64.b64decode(self.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise McpRequestError("source content is not canonical base64") from exc
        if len(payload) > _MAX_SOURCE_BYTES:
            raise McpRequestError("one source exceeds the 8 MiB service bound")
        if hash_bytes(payload) != self.sha256:
            raise McpRequestError(f"source hash mismatch: {self.path}")
        return payload


class ProfileIdentityRequest(StrictModel):
    """Identity needed to resolve a server-owned synthesis profile."""

    profile_id: str
    declared_profile_hash: str
    reference_candidate_hash: str
    expected_resolved_profile_hash: str | None = None

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        if _PROFILE_ID.fullmatch(value) is None:
            raise ValueError("invalid profile ID")
        return value

    @field_validator(
        "declared_profile_hash",
        "reference_candidate_hash",
        "expected_resolved_profile_hash",
    )
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("profile identities must be lowercase SHA-256 values")
        return value


class McpSynthesisRequest(ProfileIdentityRequest):
    """Complete bounded request for the server-generated DC flow."""

    top: str = Field(min_length=1, max_length=256)
    sources: list[McpSource] = Field(min_length=1, max_length=64)
    run_label: Literal["candidate", "reference"]
    artifact_content_policy: Literal["all", "reports"] = "all"

    @model_validator(mode="after")
    def validate_unique_sources(self) -> McpSynthesisRequest:
        paths = [item.path for item in self.sources]
        if len(paths) != len(set(paths)):
            raise ValueError("MCP synthesis sources must not contain duplicates")
        return self


class McpRequestError(ValueError):
    """A bounded, caller-safe MCP request failure."""


def _profile_input_schema(*, synthesis: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "profile_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"},
        "declared_profile_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "reference_candidate_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "expected_resolved_profile_hash": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
    }
    required = ["profile_id", "declared_profile_hash", "reference_candidate_hash"]
    if synthesis:
        properties.update(
            {
                "top": {"type": "string", "minLength": 1, "maxLength": 256},
                "sources": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                            "content_base64": {
                                "type": "string",
                                "maxLength": 12 * 1024 * 1024,
                            },
                        },
                        "required": ["path", "sha256", "content_base64"],
                        "additionalProperties": False,
                    },
                },
                "run_label": {"type": "string", "enum": ["candidate", "reference"]},
                "artifact_content_policy": {
                    "type": "string",
                    "enum": ["all", "reports"],
                    "default": "all",
                },
            }
        )
        required.extend(["top", "sources", "run_label"])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_definitions() -> list[dict[str, Any]]:
    """Return the fixed verifier-only MCP surface."""

    return [
        {
            "name": LIST_PROFILES_TOOL,
            "description": (
                "List sanitized identities for server-approved Design Compiler profiles. "
                "This verifier-only tool exposes no PDK paths, license values, or Tcl."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": RESOLVE_PROFILE_TOOL,
            "description": (
                "Probe the server-owned DC executable and resolve one exact profile identity "
                "without running synthesis."
            ),
            "inputSchema": _profile_input_schema(synthesis=False),
        },
        {
            "name": SYNTHESIZE_TOOL,
            "description": (
                "Run compile_ultra and structured area/timing/power extraction for hash-bound "
                "RTL under a fixed server-owned profile. Arbitrary Tcl and commands are forbidden."
            ),
            "inputSchema": _profile_input_schema(synthesis=True),
        },
    ]


class DesignCompilerMcpService:
    """Site-controlled service facade around the existing local DC backend."""

    def __init__(self, profile_paths: Sequence[Path], work_root: Path) -> None:
        if not profile_paths:
            raise ConfigurationError("at least one Design Compiler profile is required")
        self._work_root = _prepare_work_root(work_root)
        self._registry = ToolchainProfileRegistry()
        self._plugin = DesignCompilerSynthesisTool()
        for path in profile_paths:
            profile = self._registry.load_file(path)
            validation = self._plugin.validate_profile_contract(profile)
            if not validation.valid:
                raise ConfigurationError(
                    f"profile {profile.id!r} is not serviceable: {'; '.join(validation.errors)}"
                )

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == LIST_PROFILES_TOOL:
            if arguments:
                raise McpRequestError("list_profiles accepts no arguments")
            profiles = [self._profile_summary(profile) for _, profile in self._registry.items()]
            return {"protocol": SERVICE_PROTOCOL, "profiles": profiles}
        if name == RESOLVE_PROFILE_TOOL:
            request = _validate_model(ProfileIdentityRequest, arguments)
            profile, resolved = self._resolve(request)
            return {
                "protocol": SERVICE_PROTOCOL,
                "profile": self._profile_summary(profile),
                "resolved_profile": _sanitized_resolved_profile(resolved),
            }
        if name == SYNTHESIZE_TOOL:
            request = _validate_model(McpSynthesisRequest, arguments)
            return self._synthesize(request)
        raise McpRequestError("unknown MCP tool")

    def _profile_summary(self, profile: ToolchainProfile) -> dict[str, Any]:
        assert profile.flow is not None
        assert profile.metrics is not None
        requirement = next(item for item in profile.tools if item.name == "design-compiler")
        return {
            "profile_id": profile.id,
            "profile_version": profile.version,
            "declared_profile_hash": content_hash(profile),
            "flow_template_id": profile.flow.template_id,
            "top": profile.flow.top_module,
            "sources": profile.flow.default_sources,
            "metric_scope": profile.metrics.scope,
            "area_unit": profile.metrics.area.unit,
            "timing_unit": profile.metrics.delay.unit,
            "power_unit": profile.metrics.power.unit if profile.metrics.power.enabled else None,
            "accepted_dc_version": requirement.accepted_version,
            "reproducibility_scope": profile.reproducibility_scope,
        }

    def _resolve(
        self,
        request: ProfileIdentityRequest,
    ) -> tuple[ToolchainProfile, ResolvedToolchainProfile]:
        try:
            profile = self._registry.get(request.profile_id)
        except Exception as exc:
            raise McpRequestError("requested profile is not approved by this server") from exc
        if content_hash(profile) != request.declared_profile_hash:
            raise McpRequestError("declared profile hash differs from the server profile")
        assert profile.flow is not None
        runtime = LocalRuntime()
        try:
            resolved = self._plugin.resolve_profile(
                profile,
                runtime,
                source_paths=profile.flow.default_sources,
                top_module=profile.flow.top_module,
                reference_candidate_hash=request.reference_candidate_hash,
            )
        except ConfigurationError as exc:
            raise McpRequestError(redact(str(exc))) from exc
        finally:
            runtime.close()
        if (
            request.expected_resolved_profile_hash is not None
            and resolved.resolved_profile_hash != request.expected_resolved_profile_hash
        ):
            raise McpRequestError("resolved profile hash differs from the expected replay identity")
        return profile, resolved

    def _synthesize(self, request: McpSynthesisRequest) -> dict[str, Any]:
        profile, resolved = self._resolve(request)
        assert profile.flow is not None
        if request.top != profile.flow.top_module:
            raise McpRequestError("request top differs from the fixed server profile")
        if [item.path for item in request.sources] != profile.flow.default_sources:
            raise McpRequestError("request source list differs from the fixed server profile")
        payloads: list[tuple[str, bytes]] = []
        total = 0
        for source in request.sources:
            payload = source.decode()
            total += len(payload)
            if total > _MAX_SOURCE_TOTAL_BYTES:
                raise McpRequestError("sources exceed the 32 MiB aggregate service bound")
            payloads.append((source.path, payload))
        with tempfile.TemporaryDirectory(
            prefix="verigym-synopsys-mcp-", dir=self._work_root
        ) as temporary_value:
            temporary = Path(temporary_value)
            staging = temporary / "source"
            artifacts = temporary / "artifacts"
            staging.mkdir(mode=0o700)
            for relative, payload in payloads:
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            self._plugin.stage_profile_assets(profile, resolved, staging)
            runtime = LocalRuntime()
            session = None
            try:
                session = runtime.create_session(
                    SessionSpec(
                        source_dir=str(staging),
                        label="synopsys-mcp-verifier",
                        max_output_bytes=1_000_000,
                        environment=_profile_environment(profile),
                    )
                )
                tool_result = self._plugin.execute(
                    self._plugin.build_synthesis_request(
                        profile,
                        resolved,
                        run_label=request.run_label,
                    ),
                    ToolContext(
                        session=session,
                        max_output_bytes=1_000_000,
                        artifact_dir=artifacts,
                    ),
                )
                exported = _export_artifacts(
                    tool_result,
                    artifacts,
                    include_content=request.run_label == "candidate",
                    content_policy=request.artifact_content_policy,
                )
            finally:
                if session is not None:
                    session.close()
                runtime.close()
        return {
            "protocol": SERVICE_PROTOCOL,
            "profile": self._profile_summary(profile),
            "resolved_profile": _sanitized_resolved_profile(resolved),
            "tool_result": _sanitized_tool_result(tool_result, request.run_label),
            "artifacts": exported,
        }


def _validate_model(model: type[ProfileIdentityRequest], arguments: dict[str, Any]) -> Any:
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise McpRequestError("invalid MCP tool arguments") from exc


def _profile_environment(profile: ToolchainProfile) -> dict[str, str]:
    missing = [name for name in profile.environment_allowlist if not os.environ.get(name)]
    if missing:
        raise McpRequestError("one or more profile-approved license variables are unset")
    return {name: os.environ[name] for name in profile.environment_allowlist}


def _prepare_work_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError("MCP work root cannot be a symlink")
    expanded.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = expanded.resolve(strict=True)
    if resolved == Path("/") or not resolved.is_dir():
        raise ConfigurationError("MCP work root must be a dedicated directory")
    return resolved


def _sanitized_resolved_profile(resolved: ResolvedToolchainProfile) -> dict[str, Any]:
    flow_settings = {
        name: resolved.metadata[name]
        for name in (
            "clock_period",
            "power_activity_mode",
            "power_activity",
            "power_static_probability",
            "power_base_clock",
        )
        if name in resolved.metadata
    }
    return {
        "profile_id": resolved.profile_id,
        "profile_version": resolved.profile_version,
        "declared_profile_hash": resolved.declared_profile_hash,
        "resolved_profile_hash": resolved.resolved_profile_hash,
        "flow_template_id": resolved.flow_template_id,
        "generated_script_hash": resolved.generated_script_hash,
        "top": resolved.top_module,
        "sources": resolved.source_paths,
        "metric_scope": resolved.metric_scope,
        "area_unit": resolved.area_unit,
        "timing_unit": resolved.timing_unit,
        "power_unit": resolved.power_unit,
        "reference_candidate_hash": resolved.reference_candidate_hash,
        "tool_versions": {item.logical_name: item.version for item in resolved.tool_identities},
        "asset_hashes": {item.logical_id: item.content_hash for item in resolved.asset_identities},
        "flow_settings": flow_settings,
    }


def _sanitized_tool_result(result: ToolResult, run_label: str) -> dict[str, Any]:
    payload = result.model_dump(mode="json")
    payload["stdout"] = ""
    payload["stderr"] = ""
    if run_label == "reference":
        payload["artifacts"] = []
        payload["diagnostics"] = []
    return payload


def _export_artifacts(
    result: ToolResult,
    artifact_dir: Path,
    *,
    include_content: bool,
    content_policy: Literal["all", "reports"],
) -> list[dict[str, Any]]:
    raw_refs = result.metadata.get("synthesis", {}).get("artifacts", [])
    if not isinstance(raw_refs, list):
        raise McpRequestError("synthesis backend returned invalid artifact metadata")
    exported: list[dict[str, Any]] = []
    total = 0
    for raw_ref in raw_refs:
        try:
            ref = SynthesisArtifactRef.model_validate(raw_ref)
        except ValidationError as exc:
            raise McpRequestError("synthesis backend returned invalid artifact metadata") from exc
        record = ref.model_dump(mode="json")
        record["content_base64"] = None
        content_allowed = content_policy == "all" or ref.path in {
            "flow.tcl",
            "metrics.kv",
            "area.rpt",
            "timing.rpt",
            "power.rpt",
            "qor.rpt",
        }
        if include_content and content_allowed:
            relative = _safe_relative(ref.path)
            path = artifact_dir / relative
            if path.is_symlink():
                raise McpRequestError("synthesis backend emitted a symlink artifact")
            resolved = path.resolve(strict=True)
            inside_artifacts = resolved.is_relative_to(artifact_dir.resolve(strict=True))
            if not inside_artifacts or not resolved.is_file():
                raise McpRequestError("synthesis backend artifact escaped its directory")
            if resolved.stat().st_size > _MAX_EXPORTED_ARTIFACT_BYTES:
                raise McpRequestError("one synthesis artifact exceeds the export bound")
            payload = resolved.read_bytes()
            total += len(payload)
            if total > _MAX_EXPORTED_ARTIFACT_TOTAL_BYTES:
                raise McpRequestError("synthesis artifacts exceed the aggregate export bound")
            if len(payload) != ref.size_bytes or hash_bytes(payload) != ref.content_hash:
                raise McpRequestError("synthesis artifact identity changed before export")
            record["content_base64"] = base64.b64encode(payload).decode("ascii")
        exported.append(record)
    return exported


def _handle(request: Any, service: DesignCompilerMcpService) -> dict[str, Any] | None:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _rpc_error(None, -32600, "invalid JSON-RPC request")
    request_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "verigym-synopsys-verifier",
                    "version": SERVER_VERSION,
                },
            },
        }
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tool_definitions()},
        }
    if method == "tools/call":
        params = request.get("params")
        if not isinstance(params, dict):
            return _rpc_error(request_id, -32602, "tool parameters must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _rpc_error(request_id, -32602, "invalid tool call")
        try:
            structured = service.call(name, arguments)
        except McpRequestError as exc:
            result = _tool_error(redact(str(exc)))
        except Exception as exc:
            result = _tool_error(f"server execution failed: {type(exc).__name__}")
        else:
            summary = _summary_text(name, structured)
            result = {
                "content": [{"type": "text", "text": summary}],
                "structuredContent": structured,
                "isError": False,
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return _rpc_error(request_id, -32601, "method not found")


def _summary_text(name: str, structured: dict[str, Any]) -> str:
    if name == LIST_PROFILES_TOOL:
        return f"{len(structured['profiles'])} approved Design Compiler profile(s)"
    if name == RESOLVE_PROFILE_TOOL:
        identity = structured["resolved_profile"]["resolved_profile_hash"]
        return f"resolved Design Compiler profile {identity}"
    result = structured["tool_result"]
    return str(result.get("message", "Design Compiler synthesis completed"))


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": {"error": message},
        "isError": True,
    }


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve approved Design Compiler profiles over verifier-only MCP stdio."
    )
    parser.add_argument(
        "--profile",
        type=Path,
        action="append",
        required=True,
        help="Server-local site profile; repeat to approve more than one profile.",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        required=True,
        help="Dedicated server-local directory for ephemeral synthesis staging.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    service = DesignCompilerMcpService(arguments.profile, arguments.work_root)
    while True:
        raw = sys.stdin.buffer.readline(_MAX_MESSAGE_BYTES + 1)
        if not raw:
            return 0
        if len(raw) > _MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
            return 2
        response: dict[str, Any] | None
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            response = _rpc_error(None, -32700, "parse error")
        except Exception as exc:
            response = _rpc_error(None, -32603, f"MCP adapter error: {type(exc).__name__}")
        else:
            try:
                response = _handle(request, service)
            except Exception as exc:
                response = _rpc_error(None, -32603, f"MCP adapter error: {type(exc).__name__}")
        if response is not None:
            encoded = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
            if len(encoded.encode("utf-8")) > _MAX_MESSAGE_BYTES:
                response = _rpc_error(None, -32603, "MCP response exceeds the service bound")
                encoded = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DesignCompilerMcpService",
    "LIST_PROFILES_TOOL",
    "McpSource",
    "McpSynthesisRequest",
    "ProfileIdentityRequest",
    "RESOLVE_PROFILE_TOOL",
    "SERVER_VERSION",
    "SERVICE_PROTOCOL",
    "SYNTHESIZE_TOOL",
    "main",
    "tool_definitions",
]
