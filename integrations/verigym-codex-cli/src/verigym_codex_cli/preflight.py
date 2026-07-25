"""Structured authentication preflight with no model or login flow."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .auth import CREDENTIAL_AUTH_MODES, INHERITED_CODEX_LOGIN, AuthModeResolution
from .process import (
    CodexCliProcessRunner,
    ExecutableIdentity,
    auth_identity_configuration,
    resolve_executable,
)

_CHATGPT_LOGIN_STATUS = "Logged in using ChatGPT"


@dataclass(frozen=True)
class AuthPreflightResult:
    """Secret-free result of checking an already-selected authentication mode."""

    schema_version: str
    status: Literal["pass", "external_prerequisite"]
    external_prerequisite_satisfied: bool
    requested_auth_mode: str
    resolved_auth_mode: str
    auth_semantic_id: str
    auth_alias_used: bool
    auth_resolution_message: str | None
    codex_login_status: str
    executable_name: str
    executable_sha256: str
    diagnostic_processes: int
    model_calls: int
    login_processes: int
    logout_processes: int
    account_switch_processes: int
    credential_contents_accessed_by_verigym: bool
    credential_files_copied: int

    def safe_dict(self) -> dict[str, str | bool | int | None]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "external_prerequisite_satisfied": self.external_prerequisite_satisfied,
            "requested_auth_mode": self.requested_auth_mode,
            "resolved_auth_mode": self.resolved_auth_mode,
            "auth_semantic_id": self.auth_semantic_id,
            "auth_alias_used": self.auth_alias_used,
            "auth_resolution_message": self.auth_resolution_message,
            "codex_login_status": self.codex_login_status,
            "executable_name": self.executable_name,
            "executable_sha256": self.executable_sha256,
            "diagnostic_processes": self.diagnostic_processes,
            "model_calls": self.model_calls,
            "login_processes": self.login_processes,
            "logout_processes": self.logout_processes,
            "account_switch_processes": self.account_switch_processes,
            "credential_contents_accessed_by_verigym": (
                self.credential_contents_accessed_by_verigym
            ),
            "credential_files_copied": self.credential_files_copied,
        }


def run_auth_preflight(
    executable: ExecutableIdentity | None = None,
) -> AuthPreflightResult:
    """Check existing auth availability without model, login, logout, or account changes."""

    resolution, credential_env = auth_identity_configuration()
    identity = executable or resolve_executable()
    if resolution.resolved_auth_mode == INHERITED_CODEX_LOGIN:
        satisfied, login_status = _inherited_session_status(identity, resolution)
        diagnostic_processes = 1
    elif resolution.resolved_auth_mode in CREDENTIAL_AUTH_MODES:
        satisfied = credential_env is not None and credential_env in os.environ
        login_status = "not_applicable"
        diagnostic_processes = 0
    else:  # pragma: no cover - centralized resolver makes this unreachable
        raise AssertionError("unreachable Codex authentication mode")
    return AuthPreflightResult(
        schema_version="1.0",
        status="pass" if satisfied else "external_prerequisite",
        external_prerequisite_satisfied=satisfied,
        requested_auth_mode=resolution.requested_auth_mode,
        resolved_auth_mode=resolution.resolved_auth_mode,
        auth_semantic_id=resolution.auth_semantic_id,
        auth_alias_used=resolution.auth_alias_used,
        auth_resolution_message=resolution.alias_resolution_message,
        codex_login_status=login_status,
        executable_name=identity.name,
        executable_sha256=identity.sha256,
        diagnostic_processes=diagnostic_processes,
        model_calls=0,
        login_processes=0,
        logout_processes=0,
        account_switch_processes=0,
        credential_contents_accessed_by_verigym=False,
        credential_files_copied=0,
    )


def _inherited_session_status(
    executable: ExecutableIdentity,
    resolution: AuthModeResolution,
) -> tuple[bool, str]:
    runner = CodexCliProcessRunner(
        executable,
        auth_mode=resolution.resolved_auth_mode,
        max_output_bytes=1024 * 1024,
    )
    with tempfile.TemporaryDirectory(prefix="verigym-codex-auth-preflight-") as temporary:
        result = runner.run(
            ["login", "status"],
            cwd=Path(temporary),
            timeout_s=15.0,
        )
    combined = f"{result.stdout}\n{result.stderr}"
    satisfied = (
        result.exit_code == 0
        and not result.timed_out
        and not result.stdout_truncated
        and not result.stderr_truncated
        and _CHATGPT_LOGIN_STATUS in combined
    )
    return satisfied, _CHATGPT_LOGIN_STATUS if satisfied else "unavailable"


__all__ = ["AuthPreflightResult", "run_auth_preflight"]
