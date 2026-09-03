"""Restricted MCP service for public compile-only Synopsys VCS feedback."""

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
from typing import Any

from pydantic import Field, ValidationError, field_validator, model_validator
from verigym.plugin_api import (
    ConfigurationError,
    ErrorCategory,
    StrictModel,
    ToolContext,
    ToolResult,
    content_hash,
    hash_bytes,
)
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec

from .common import redact, safe_relative_path
from .vcs import probe_vcs
from .vcs_public_compile import VcsPublicCompileTool
from .vcs_public_mcp_profile import (
    COMPILE_TOOL,
    LIST_PROFILES_TOOL,
    RESOLVE_PROFILE_TOOL,
    SERVER_VERSION,
    SERVICE_PROTOCOL,
    VcsPublicMcpServerProfile,
    load_vcs_public_server_profile,
)

_MCP_PROTOCOL_VERSION = "2024-11-05"
_MAX_MESSAGE_BYTES = 48 * 1024 * 1024
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_SOURCE_TOTAL_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


class McpVcsPublicSource(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    sha256: str
    content_base64: str = Field(max_length=12 * 1024 * 1024)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = safe_relative_path(value)
        if Path(normalized).suffix.lower() not in {".v", ".sv"}:
            raise ValueError("VCS public MCP sources must use Verilog filenames")
        return normalized

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("source identity must be a lowercase SHA-256")
        return value

    def decode(self) -> bytes:
        try:
            payload = base64.b64decode(self.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise VcsPublicMcpRequestError("source content is not canonical base64") from exc
        if len(payload) > _MAX_SOURCE_BYTES or hash_bytes(payload) != self.sha256:
            raise VcsPublicMcpRequestError("source content differs from its bounded identity")
        return payload


class VcsPublicProfileIdentityRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=128)
    declared_profile_hash: str
    contract_hash: str
    expected_resolved_profile_hash: str | None = None

    @field_validator("declared_profile_hash", "contract_hash", "expected_resolved_profile_hash")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("VCS public MCP identities must be lowercase SHA-256 values")
        return value


class VcsPublicMcpCompileRequest(VcsPublicProfileIdentityRequest):
    task_id: str = Field(min_length=1, max_length=256)
    test_id: str = Field(min_length=1, max_length=64)
    candidate_hash: str
    sources: list[McpVcsPublicSource] = Field(min_length=1, max_length=64)
    top: str = Field(min_length=1, max_length=256)

    @field_validator("candidate_hash")
    @classmethod
    def validate_candidate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("candidate identity must be a lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_unique_sources(self) -> VcsPublicMcpCompileRequest:
        paths = [item.path for item in self.sources]
        if len(paths) != len(set(paths)):
            raise ValueError("VCS public MCP source paths must be unique")
        return self


class VcsPublicMcpRequestError(ValueError):
    def __init__(self, message: str, *, reason_code: str = "invalid_request") -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _identity_schema(*, compile_request: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "profile_id": {"type": "string"},
        "declared_profile_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "contract_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "expected_resolved_profile_hash": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
    }
    required = ["profile_id", "declared_profile_hash", "contract_hash"]
    if compile_request:
        properties.update(
            {
                "task_id": {"type": "string"},
                "test_id": {"type": "string"},
                "candidate_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "sources": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                            "content_base64": {"type": "string"},
                        },
                        "required": ["path", "sha256", "content_base64"],
                        "additionalProperties": False,
                    },
                },
                "top": {"type": "string"},
            }
        )
        required.extend(["task_id", "test_id", "candidate_hash", "sources", "top"])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": LIST_PROFILES_TOOL,
            "description": "List sanitized identities for fixed public VCS compile profiles.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": RESOLVE_PROFILE_TOOL,
            "description": "Resolve one fixed public VCS compile profile.",
            "inputSchema": _identity_schema(compile_request=False),
        },
        {
            "name": COMPILE_TOOL,
            "description": "Compile bounded candidate RTL with a fixed public VCS contract.",
            "inputSchema": _identity_schema(compile_request=True),
        },
    ]


class VcsPublicMcpService:
    def __init__(self, profile_paths: Sequence[Path], work_root: Path) -> None:
        if not profile_paths:
            raise ConfigurationError("at least one VCS public MCP profile is required")
        self._work_root = _prepare_work_root(work_root)
        self._profiles: dict[str, VcsPublicMcpServerProfile] = {}
        self._plugin = VcsPublicCompileTool()
        for path in profile_paths:
            profile = load_vcs_public_server_profile(path)
            if profile.id in self._profiles:
                raise ConfigurationError(f"duplicate VCS public MCP profile ID: {profile.id}")
            self._profiles[profile.id] = profile

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == LIST_PROFILES_TOOL:
            if arguments:
                raise VcsPublicMcpRequestError("list_profiles accepts no arguments")
            return {
                "protocol": SERVICE_PROTOCOL,
                "profiles": [self._summary(item) for item in self._profiles.values()],
            }
        if name == RESOLVE_PROFILE_TOOL:
            request = _validate(VcsPublicProfileIdentityRequest, arguments)
            profile, resolved = self._resolve(request)
            return {
                "protocol": SERVICE_PROTOCOL,
                "profile": self._summary(profile),
                "resolved_profile": resolved,
            }
        if name == COMPILE_TOOL:
            return self._compile(_validate(VcsPublicMcpCompileRequest, arguments))
        raise VcsPublicMcpRequestError("unknown MCP tool")

    def _summary(self, profile: VcsPublicMcpServerProfile) -> dict[str, Any]:
        return {
            **profile.contract_payload(),
            "declared_profile_hash": content_hash(profile),
            "contract_hash": profile.contract_hash,
        }

    def _resolve(
        self,
        request: VcsPublicProfileIdentityRequest,
    ) -> tuple[VcsPublicMcpServerProfile, dict[str, Any]]:
        profile = self._profiles.get(request.profile_id)
        if profile is None:
            raise VcsPublicMcpRequestError(
                "requested profile is not approved by this server",
                reason_code="profile_not_approved",
            )
        if content_hash(profile) != request.declared_profile_hash:
            raise VcsPublicMcpRequestError(
                "declared profile hash differs from the server profile",
                reason_code="profile_identity_mismatch",
            )
        if profile.contract_hash != request.contract_hash:
            raise VcsPublicMcpRequestError(
                "public contract hash differs from the server profile",
                reason_code="profile_contract_mismatch",
            )
        health = probe_vcs(profile.executable)
        if not health.healthy or health.version is None:
            raise VcsPublicMcpRequestError("approved VCS executable failed its identity probe")
        if health.version != profile.accepted_tool_version:
            raise VcsPublicMcpRequestError(
                "VCS tool version differs from the approved exact version",
                reason_code="tool_identity_mismatch",
            )
        payload = {
            "service_protocol": SERVICE_PROTOCOL,
            "server_version": SERVER_VERSION,
            "profile_id": profile.id,
            "profile_version": profile.version,
            "declared_profile_hash": content_hash(profile),
            "contract_hash": profile.contract_hash,
            "tool_version": health.version,
        }
        resolved = {**payload, "resolved_profile_hash": content_hash(payload)}
        if (
            request.expected_resolved_profile_hash is not None
            and request.expected_resolved_profile_hash != resolved["resolved_profile_hash"]
        ):
            raise VcsPublicMcpRequestError(
                "resolved profile differs from the expected replay identity",
                reason_code="profile_resolved_identity_mismatch",
            )
        return profile, resolved

    def _compile(self, request: VcsPublicMcpCompileRequest) -> dict[str, Any]:
        profile, resolved = self._resolve(request)
        if (
            request.task_id != profile.task_id
            or request.test_id != profile.test_id
            or [item.path for item in request.sources] != profile.sources
            or request.top != profile.top
        ):
            raise VcsPublicMcpRequestError(
                "compile request differs from the fixed public VCS contract"
            )
        payloads: list[tuple[str, bytes]] = []
        identities: dict[str, str] = {}
        total = 0
        for source in request.sources:
            payload = source.decode()
            total += len(payload)
            if total > _MAX_SOURCE_TOTAL_BYTES:
                raise VcsPublicMcpRequestError("candidate sources exceed the aggregate byte bound")
            payloads.append((source.path, payload))
            identities[source.path] = source.sha256
        if request.candidate_hash != content_hash({"sources": identities}):
            raise VcsPublicMcpRequestError(
                "candidate hash differs from the submitted source identities"
            )
        with tempfile.TemporaryDirectory(
            prefix="verigym-vcs-public-mcp-",
            dir=self._work_root,
        ) as temporary_value:
            staging = Path(temporary_value) / "source"
            staging.mkdir(mode=0o700)
            for relative, payload in payloads:
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            runtime = LocalRuntime()
            session = None
            try:
                session = runtime.create_session(
                    SessionSpec(
                        source_dir=str(staging),
                        label="vcs-public-mcp-compile",
                        max_output_bytes=1_000_000,
                        environment=_profile_environment(profile),
                    )
                )
                result = self._plugin.execute(
                    {
                        "test_id": profile.test_id,
                        "sources": profile.sources,
                        "top": profile.top,
                        "executable": profile.executable,
                        "timeout_s": profile.timeout_s,
                    },
                    ToolContext(session=session, max_output_bytes=1_000_000),
                )
            finally:
                if session is not None:
                    session.close()
                runtime.close()
        return {
            "protocol": SERVICE_PROTOCOL,
            "profile": self._summary(profile),
            "resolved_profile": resolved,
            "candidate_hash": request.candidate_hash,
            "tool_result": _sanitized_result(result),
        }


def _validate(model: type[StrictModel], arguments: dict[str, Any]) -> Any:
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise VcsPublicMcpRequestError("invalid MCP tool arguments") from exc


def _profile_environment(profile: VcsPublicMcpServerProfile) -> dict[str, str]:
    missing = [name for name in profile.environment_allowlist if not os.environ.get(name)]
    if missing:
        raise VcsPublicMcpRequestError("one or more approved VCS environment variables are unset")
    return {name: os.environ[name] for name in profile.environment_allowlist}


def _prepare_work_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError("VCS public MCP work root cannot be a symlink")
    expanded.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = expanded.resolve(strict=True)
    if resolved == Path("/") or not resolved.is_dir():
        raise ConfigurationError("VCS public MCP work root must be a dedicated directory")
    return resolved


def _sanitized_result(result: ToolResult) -> dict[str, Any]:
    diagnostics = result.diagnostics[:32]
    if any(len(item) > 512 or item.startswith("/") for item in diagnostics):
        diagnostics = []
        result = result.model_copy(
            update={
                "success": False,
                "category": ErrorCategory.INVALID_REQUEST,
                "message": "VCS public diagnostic projection was invalid",
                "metadata": {"candidate_failure": False},
            }
        )
    messages = {
        "success": "VCS public compile passed",
        "license_unavailable": "Synopsys VCS could not obtain a license",
        "compile_failed": "candidate RTL could not be compiled by VCS",
        "timeout": "VCS public compilation exceeded its time bound",
        "out_of_memory": "VCS public compilation exceeded its memory bound",
        "output_limit": "VCS public compilation exceeded its output bound",
        "tool_not_found": "the approved VCS public compiler was unavailable",
        "sandbox_error": "the VCS public compiler runtime failed",
        "invalid_request": "the fixed VCS public compile request was invalid",
    }
    return ToolResult(
        tool="synopsys.vcs.public-compile.mcp",
        success=result.success,
        category=result.category,
        message=messages.get(result.category.value, "VCS public compile failed"),
        exit_code=result.exit_code,
        duration_s=result.duration_s,
        output_truncated=result.output_truncated,
        diagnostics=diagnostics,
        metadata={"candidate_failure": result.metadata.get("candidate_failure") is True},
    ).model_dump(mode="json")


def _handle(request: Any, service: VcsPublicMcpService) -> dict[str, Any] | None:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _rpc_error(None, -32600, "invalid JSON-RPC request")
    request_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "verigym-synopsys-verifier",
                    "version": SERVER_VERSION,
                },
            },
        }
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tool_definitions()}}
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
        except VcsPublicMcpRequestError as exc:
            result = _tool_error(redact(str(exc)), reason_code=exc.reason_code)
        except Exception as exc:
            result = _tool_error(f"server execution failed: {type(exc).__name__}")
        else:
            result = {
                "content": [{"type": "text", "text": "VCS public compile completed"}],
                "structuredContent": structured,
                "isError": False,
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return _rpc_error(request_id, -32601, "method not found")


def _tool_error(message: str, *, reason_code: str = "invalid_request") -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": {"error": message, "reason_code": reason_code},
        "isError": True,
    }


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve fixed public VCS profiles over MCP stdio.")
    parser.add_argument("--profile", type=Path, action="append", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    service = VcsPublicMcpService(arguments.profile, arguments.work_root)
    while True:
        raw = sys.stdin.buffer.readline(_MAX_MESSAGE_BYTES + 1)
        if not raw:
            return 0
        if len(raw) > _MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
            return 2
        try:
            request = json.loads(raw)
            response = _handle(request, service)
        except Exception as exc:
            response = _rpc_error(None, -32603, f"MCP adapter error: {type(exc).__name__}")
        if response is not None:
            encoded = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
            if len(encoded.encode("utf-8")) > _MAX_MESSAGE_BYTES:
                return 2
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COMPILE_TOOL",
    "RESOLVE_PROFILE_TOOL",
    "VcsPublicMcpRequestError",
    "VcsPublicMcpService",
    "main",
    "tool_definitions",
]
