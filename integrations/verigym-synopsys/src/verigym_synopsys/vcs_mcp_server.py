"""Restricted MCP stdio service for verifier-owned Synopsys VCS execution."""

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
    StrictModel,
    ToolContext,
    ToolResult,
    content_hash,
    hash_bytes,
)
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec

from .common import redact, safe_relative_path
from .vcs import VcsSimulationTool, probe_vcs
from .vcs_mcp_profile import (
    LIST_PROFILES_TOOL,
    RESOLVE_PROFILE_TOOL,
    SERVER_VERSION,
    SERVICE_PROTOCOL,
    SIMULATE_TOOL,
    VcsMcpServerProfile,
    load_vcs_server_profile,
)

_MCP_PROTOCOL_VERSION = "2024-11-05"
_MAX_MESSAGE_BYTES = 48 * 1024 * 1024
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_SOURCE_TOTAL_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


class McpVcsSource(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    sha256: str
    content_base64: str = Field(max_length=12 * 1024 * 1024)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = safe_relative_path(value)
        if Path(normalized).suffix.lower() not in {".v", ".sv"}:
            raise ValueError("VCS MCP sources must use Verilog filenames")
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
            raise VcsMcpRequestError("source content is not canonical base64") from exc
        if len(payload) > _MAX_SOURCE_BYTES or hash_bytes(payload) != self.sha256:
            raise VcsMcpRequestError("source content differs from its bounded identity")
        return payload


class VcsProfileIdentityRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=128)
    declared_profile_hash: str
    contract_hash: str
    expected_resolved_profile_hash: str | None = None

    @field_validator("declared_profile_hash", "contract_hash", "expected_resolved_profile_hash")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("VCS MCP identities must be lowercase SHA-256 values")
        return value


class VcsMcpSimulationRequest(VcsProfileIdentityRequest):
    task_id: str = Field(min_length=1, max_length=256)
    candidate_hash: str
    sources: list[McpVcsSource] = Field(min_length=1, max_length=64)
    testbench_mount_path: str = Field(min_length=1, max_length=4096)
    top: str = Field(min_length=1, max_length=256)
    pass_marker: str = Field(min_length=1, max_length=256)
    fail_marker: str = Field(min_length=1, max_length=256)

    @field_validator("testbench_mount_path")
    @classmethod
    def validate_testbench_mount_path(cls, value: str) -> str:
        return safe_relative_path(value)

    @field_validator("candidate_hash")
    @classmethod
    def validate_candidate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("candidate identity must be a lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_unique_sources(self) -> VcsMcpSimulationRequest:
        paths = [item.path for item in self.sources]
        if len(paths) != len(set(paths)):
            raise ValueError("VCS MCP source paths must be unique")
        return self


class VcsMcpRequestError(ValueError):
    """Caller-safe protocol or fixed-contract rejection."""


def _identity_schema(*, simulate: bool) -> dict[str, Any]:
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
    if simulate:
        properties.update(
            {
                "task_id": {"type": "string"},
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
                "testbench_mount_path": {"type": "string"},
                "top": {"type": "string"},
                "pass_marker": {"type": "string"},
                "fail_marker": {"type": "string"},
            }
        )
        required.extend(
            [
                "task_id",
                "candidate_hash",
                "sources",
                "testbench_mount_path",
                "top",
                "pass_marker",
                "fail_marker",
            ]
        )
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
            "description": "List sanitized identities for fixed verifier-only VCS profiles.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": RESOLVE_PROFILE_TOOL,
            "description": "Resolve one fixed VCS profile and exact tool identity.",
            "inputSchema": _identity_schema(simulate=False),
        },
        {
            "name": SIMULATE_TOOL,
            "description": (
                "Run candidate RTL against one server-owned hash-bound hidden testbench."
            ),
            "inputSchema": _identity_schema(simulate=True),
        },
    ]


class VcsMcpService:
    def __init__(self, profile_paths: Sequence[Path], work_root: Path) -> None:
        if not profile_paths:
            raise ConfigurationError("at least one VCS MCP profile is required")
        self._work_root = _prepare_work_root(work_root)
        self._profiles: dict[str, VcsMcpServerProfile] = {}
        self._plugin = VcsSimulationTool()
        for path in profile_paths:
            profile = load_vcs_server_profile(path)
            if profile.id in self._profiles:
                raise ConfigurationError(f"duplicate VCS MCP profile ID: {profile.id}")
            self._validate_testbench(profile)
            self._profiles[profile.id] = profile

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == LIST_PROFILES_TOOL:
            if arguments:
                raise VcsMcpRequestError("list_profiles accepts no arguments")
            return {
                "protocol": SERVICE_PROTOCOL,
                "profiles": [self._summary(item) for item in self._profiles.values()],
            }
        if name == RESOLVE_PROFILE_TOOL:
            request = _validate(VcsProfileIdentityRequest, arguments)
            profile, resolved = self._resolve(request)
            return {
                "protocol": SERVICE_PROTOCOL,
                "profile": self._summary(profile),
                "resolved_profile": resolved,
            }
        if name == SIMULATE_TOOL:
            request = _validate(VcsMcpSimulationRequest, arguments)
            return self._simulate(request)
        raise VcsMcpRequestError("unknown MCP tool")

    def _summary(self, profile: VcsMcpServerProfile) -> dict[str, Any]:
        return {
            **profile.contract_payload(),
            "declared_profile_hash": content_hash(profile),
            "contract_hash": profile.contract_hash,
        }

    def _resolve(
        self,
        request: VcsProfileIdentityRequest,
    ) -> tuple[VcsMcpServerProfile, dict[str, Any]]:
        profile = self._profiles.get(request.profile_id)
        if profile is None:
            raise VcsMcpRequestError("requested profile is not approved by this server")
        if content_hash(profile) != request.declared_profile_hash:
            raise VcsMcpRequestError("declared profile hash differs from the server profile")
        if profile.contract_hash != request.contract_hash:
            raise VcsMcpRequestError("public contract hash differs from the server profile")
        self._validate_testbench(profile)
        health = probe_vcs(profile.executable)
        if not health.healthy or health.version is None:
            raise VcsMcpRequestError("approved VCS executable failed its identity probe")
        if health.version != profile.accepted_tool_version:
            raise VcsMcpRequestError("VCS tool version differs from the approved exact version")
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
            raise VcsMcpRequestError("resolved profile differs from the expected replay identity")
        return profile, resolved

    def _simulate(self, request: VcsMcpSimulationRequest) -> dict[str, Any]:
        profile, resolved = self._resolve(request)
        if request.task_id != profile.task_id:
            raise VcsMcpRequestError("task differs from the fixed VCS profile")
        if [item.path for item in request.sources] != profile.sources:
            raise VcsMcpRequestError("source list differs from the fixed VCS profile")
        if (
            request.testbench_mount_path != profile.testbench_mount_path
            or request.top != profile.top
            or request.pass_marker != profile.pass_marker
            or request.fail_marker != profile.fail_marker
        ):
            raise VcsMcpRequestError("simulation request differs from the fixed VCS contract")
        payloads: list[tuple[str, bytes]] = []
        identities: dict[str, str] = {}
        total = 0
        for source in request.sources:
            payload = source.decode()
            total += len(payload)
            if total > _MAX_SOURCE_TOTAL_BYTES:
                raise VcsMcpRequestError("candidate sources exceed the aggregate byte bound")
            payloads.append((source.path, payload))
            identities[source.path] = source.sha256
        if request.candidate_hash != content_hash({"sources": identities}):
            raise VcsMcpRequestError("candidate hash differs from the submitted source identities")
        testbench_payload = self._testbench_bytes(profile)
        with tempfile.TemporaryDirectory(
            prefix="verigym-vcs-mcp-",
            dir=self._work_root,
        ) as temporary_value:
            staging = Path(temporary_value) / "source"
            staging.mkdir(mode=0o700)
            for relative, payload in payloads:
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            testbench_target = staging / profile.testbench_mount_path
            testbench_target.parent.mkdir(parents=True, exist_ok=True)
            testbench_target.write_bytes(testbench_payload)
            runtime = LocalRuntime()
            session = None
            try:
                session = runtime.create_session(
                    SessionSpec(
                        source_dir=str(staging),
                        label="vcs-mcp-verifier",
                        max_output_bytes=1_000_000,
                        environment=_profile_environment(profile),
                    )
                )
                result = self._plugin.execute(
                    {
                        "sources": profile.sources,
                        "testbench": profile.testbench_mount_path,
                        "top": profile.top,
                        "pass_marker": profile.pass_marker,
                        "fail_marker": profile.fail_marker,
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

    @staticmethod
    def _validate_testbench(profile: VcsMcpServerProfile) -> None:
        VcsMcpService._testbench_bytes(profile)

    @staticmethod
    def _testbench_bytes(profile: VcsMcpServerProfile) -> bytes:
        path = Path(profile.testbench)
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError("approved VCS testbench is unavailable")
        if path.stat().st_size > _MAX_SOURCE_BYTES:
            raise ConfigurationError("approved VCS testbench exceeds the byte bound")
        payload = path.read_bytes()
        if len(payload) > _MAX_SOURCE_BYTES or hash_bytes(payload) != profile.testbench_sha256:
            raise ConfigurationError("approved VCS testbench differs from its profile hash")
        return payload


def _validate(model: type[StrictModel], arguments: dict[str, Any]) -> Any:
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise VcsMcpRequestError("invalid MCP tool arguments") from exc


def _profile_environment(profile: VcsMcpServerProfile) -> dict[str, str]:
    missing = [name for name in profile.environment_allowlist if not os.environ.get(name)]
    if missing:
        raise VcsMcpRequestError("one or more approved VCS environment variables are unset")
    return {name: os.environ[name] for name in profile.environment_allowlist}


def _prepare_work_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError("VCS MCP work root cannot be a symlink")
    expanded.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = expanded.resolve(strict=True)
    if resolved == Path("/") or not resolved.is_dir():
        raise ConfigurationError("VCS MCP work root must be a dedicated directory")
    return resolved


def _sanitized_result(result: ToolResult) -> dict[str, Any]:
    messages = {
        "success": "VCS regression passed",
        "license_unavailable": "Synopsys VCS could not obtain a license",
        "compile_failed": "candidate RTL could not be compiled by VCS",
        "test_failed": "VCS simulation did not report the required passing sentinel",
        "timeout": "VCS compilation or simulation exceeded the command timeout",
        "out_of_memory": "VCS was killed by the runtime memory limit",
        "output_limit": "VCS command output exceeded the runtime limit",
        "tool_not_found": "the approved VCS executable was unavailable",
        "sandbox_error": "the VCS verifier runtime failed",
        "invalid_request": "the fixed VCS verifier request was invalid",
    }
    return ToolResult(
        tool="synopsys.vcs.mcp",
        success=result.success,
        category=result.category,
        message=messages.get(result.category.value, "VCS verifier failed"),
        exit_code=result.exit_code,
        duration_s=result.duration_s,
        output_truncated=result.output_truncated,
        metadata={"candidate_failure": result.metadata.get("candidate_failure") is True},
    ).model_dump(mode="json")


def _handle(request: Any, service: VcsMcpService) -> dict[str, Any] | None:
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
        except VcsMcpRequestError as exc:
            result = _tool_error(redact(str(exc)))
        except Exception as exc:
            result = _tool_error(f"server execution failed: {type(exc).__name__}")
        else:
            result = {
                "content": [{"type": "text", "text": "VCS verifier request completed"}],
                "structuredContent": structured,
                "isError": False,
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return _rpc_error(request_id, -32601, "method not found")


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
    parser = argparse.ArgumentParser(description="Serve fixed VCS profiles over MCP stdio.")
    parser.add_argument("--profile", type=Path, action="append", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    service = VcsMcpService(arguments.profile, arguments.work_root)
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
    "LIST_PROFILES_TOOL",
    "RESOLVE_PROFILE_TOOL",
    "SIMULATE_TOOL",
    "VcsMcpService",
    "main",
    "tool_definitions",
]
