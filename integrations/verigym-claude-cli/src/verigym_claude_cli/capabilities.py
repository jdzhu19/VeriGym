"""Zero-model-call Claude CLI capability discovery and sealing."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .process import (
    ClaudeCliProcessRunner,
    ExecutableIdentity,
    configured_broker_root,
    provider_environment,
    resolve_executable,
)
from .util import stable_hash

_CACHE: dict[str, CapabilityReport] = {}
_REQUIRED_FLAGS = (
    "--allowedtools",
    "--bare",
    "--disable-slash-commands",
    "--disallowedtools",
    "--effort",
    "--mcp-config",
    "--model",
    "--name",
    "--no-chrome",
    "--no-session-persistence",
    "--output-format",
    "--permission-mode",
    "--print",
    "--prompt-suggestions",
    "--strict-mcp-config",
    "--tools",
    "--verbose",
)


class CapabilityError(RuntimeError):
    """The installed CLI cannot support the constrained integration."""


@dataclass(frozen=True)
class CapabilityReport:
    schema_version: str
    executable_name: str
    executable_sha256: str
    version_output: str
    normalized_help: str
    required_flags: tuple[str, ...]
    event_protocol: str
    mcp_transport: str
    no_internal_turn_limit_configured: bool
    no_model_token_limit_configured: bool
    no_budget_limit_configured: bool
    capability_fingerprint: str
    diagnostic_process_count: int
    model_call_count: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "executable_name": self.executable_name,
            "executable_sha256": self.executable_sha256,
            "version_output": self.version_output,
            "normalized_help": self.normalized_help,
            "required_flags": list(self.required_flags),
            "event_protocol": self.event_protocol,
            "mcp_transport": self.mcp_transport,
            "no_internal_turn_limit_configured": self.no_internal_turn_limit_configured,
            "no_model_token_limit_configured": self.no_model_token_limit_configured,
            "no_budget_limit_configured": self.no_budget_limit_configured,
            "capability_fingerprint": self.capability_fingerprint,
            "diagnostic_process_count": self.diagnostic_process_count,
            "model_call_count": self.model_call_count,
        }


def discover_capabilities(
    executable: ExecutableIdentity | None = None,
    *,
    force: bool = False,
) -> tuple[ExecutableIdentity, CapabilityReport]:
    identity = executable or resolve_executable()
    if not force and identity.sha256 in _CACHE:
        return identity, _CACHE[identity.sha256]
    root = configured_broker_root()
    runner = ClaudeCliProcessRunner(identity, max_output_bytes=2 * 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix="cap-", dir=root) as raw_control:
        control = Path(raw_control)
        environment = provider_environment(
            control,
            allow_proxy_environment=False,
            include_auth=False,
        )
        version = runner.run(
            ["--version"],
            cwd=control,
            timeout_s=15.0,
            stdin_bytes=None,
            environment=environment,
        )
        help_result = runner.run(
            ["--help"],
            cwd=control,
            timeout_s=15.0,
            stdin_bytes=None,
            environment=environment,
        )
    for label, result in (("--version", version), ("--help", help_result)):
        if result.timed_out or result.exit_code != 0 or result.stdout_truncated:
            raise CapabilityError(f"Claude {label} diagnostic did not complete safely")
    version_output = _single_output(version.stdout, version.stderr)
    normalized_help = _normalize_help(help_result.stdout + "\n" + help_result.stderr)
    missing = [flag for flag in _REQUIRED_FLAGS if flag not in normalized_help]
    if missing:
        raise CapabilityError("Claude CLI lacks required flags: " + ", ".join(missing))
    if "stream-json" not in normalized_help or "dontask" not in normalized_help:
        raise CapabilityError("Claude CLI lacks the required event or permission mode")
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "executable_name": identity.name,
        "executable_sha256": identity.sha256,
        "version_output": version_output,
        "normalized_help": normalized_help,
        "required_flags": list(_REQUIRED_FLAGS),
        "event_protocol": "claude-print-stream-json-v1",
        "mcp_transport": "private-unix-socket-stdio-adapter-v1",
        "no_internal_turn_limit_configured": True,
        "no_model_token_limit_configured": True,
        "no_budget_limit_configured": True,
        "diagnostic_process_count": 2,
        "model_call_count": 0,
    }
    payload["capability_fingerprint"] = stable_hash(payload)
    report = CapabilityReport(
        schema_version="1.0",
        executable_name=identity.name,
        executable_sha256=identity.sha256,
        version_output=version_output,
        normalized_help=normalized_help,
        required_flags=_REQUIRED_FLAGS,
        event_protocol="claude-print-stream-json-v1",
        mcp_transport="private-unix-socket-stdio-adapter-v1",
        no_internal_turn_limit_configured=True,
        no_model_token_limit_configured=True,
        no_budget_limit_configured=True,
        capability_fingerprint=str(payload["capability_fingerprint"]),
        diagnostic_process_count=2,
        model_call_count=0,
    )
    _CACHE[identity.sha256] = report
    return identity, report


def runtime_capabilities() -> tuple[ExecutableIdentity, CapabilityReport]:
    return discover_capabilities(resolve_executable())


def _normalize_help(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _single_output(stdout: str, stderr: str) -> str:
    value = (stdout.strip() or stderr.strip()).splitlines()
    if len(value) != 1 or not value[0] or len(value[0]) > 512:
        raise CapabilityError("Claude version diagnostic is malformed")
    return value[0]


__all__ = [
    "CapabilityError",
    "CapabilityReport",
    "discover_capabilities",
    "runtime_capabilities",
]
