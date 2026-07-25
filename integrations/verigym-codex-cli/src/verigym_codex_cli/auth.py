"""Typed authentication-label resolution without credential access."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, cast

from .util import clean_identifier

RequestedAuthMode = Literal[
    "chatgpt_cli_session",
    "inherited_codex_login",
    "api_key_env",
    "custom_provider_environment",
]
ResolvedAuthMode = Literal[
    "inherited_codex_login",
    "api_key_env",
    "custom_provider_environment",
]
AuthSemanticId = Literal[
    "codex.auth.inherited_chatgpt_session.v1",
    "codex.auth.api_key_environment.v1",
    "codex.auth.custom_provider_environment.v1",
]

CHATGPT_CLI_SESSION: Final[RequestedAuthMode] = "chatgpt_cli_session"
INHERITED_CODEX_LOGIN: Final[ResolvedAuthMode] = "inherited_codex_login"
API_KEY_ENV: Final[ResolvedAuthMode] = "api_key_env"
CUSTOM_PROVIDER_ENVIRONMENT: Final[ResolvedAuthMode] = "custom_provider_environment"

AUTH_MODE_ALIASES: Final[Mapping[RequestedAuthMode, ResolvedAuthMode]] = MappingProxyType(
    {
        CHATGPT_CLI_SESSION: INHERITED_CODEX_LOGIN,
        INHERITED_CODEX_LOGIN: INHERITED_CODEX_LOGIN,
        API_KEY_ENV: API_KEY_ENV,
        CUSTOM_PROVIDER_ENVIRONMENT: CUSTOM_PROVIDER_ENVIRONMENT,
    }
)
AUTH_SEMANTIC_IDS: Final[Mapping[ResolvedAuthMode, AuthSemanticId]] = MappingProxyType(
    {
        INHERITED_CODEX_LOGIN: "codex.auth.inherited_chatgpt_session.v1",
        API_KEY_ENV: "codex.auth.api_key_environment.v1",
        CUSTOM_PROVIDER_ENVIRONMENT: "codex.auth.custom_provider_environment.v1",
    }
)
RESOLVED_AUTH_MODES: Final[frozenset[ResolvedAuthMode]] = frozenset(AUTH_SEMANTIC_IDS)
CREDENTIAL_AUTH_MODES: Final[frozenset[ResolvedAuthMode]] = frozenset(
    {API_KEY_ENV, CUSTOM_PROVIDER_ENVIRONMENT}
)


class AuthModeError(ValueError):
    """A requested authentication label has no supported semantic resolution."""


@dataclass(frozen=True)
class AuthModeResolution:
    """Secret-free provenance and semantic identity for one requested label."""

    requested_auth_mode: RequestedAuthMode
    resolved_auth_mode: ResolvedAuthMode
    auth_semantic_id: AuthSemanticId
    auth_alias_used: bool

    @property
    def alias_resolution_message(self) -> str | None:
        if not self.auth_alias_used:
            return None
        return (
            "authentication mode alias resolved:\n"
            f"{self.requested_auth_mode} -> {self.resolved_auth_mode}"
        )

    def safe_dict(self) -> dict[str, str | bool]:
        return {
            "requested_auth_mode": self.requested_auth_mode,
            "resolved_auth_mode": self.resolved_auth_mode,
            "auth_semantic_id": self.auth_semantic_id,
            "auth_alias_used": self.auth_alias_used,
        }


def resolve_auth_mode(raw: str) -> AuthModeResolution:
    """Resolve one exact public label to its unchanged execution semantics."""

    try:
        clean = clean_identifier(
            raw,
            label="Codex authentication mode",
            max_length=64,
        )
    except ValueError as exc:
        raise AuthModeError("unsupported Codex authentication-mode label") from exc
    if clean not in AUTH_MODE_ALIASES:
        raise AuthModeError("unsupported Codex authentication-mode label")
    requested = cast(RequestedAuthMode, clean)
    resolved = AUTH_MODE_ALIASES[requested]
    return AuthModeResolution(
        requested_auth_mode=requested,
        resolved_auth_mode=resolved,
        auth_semantic_id=AUTH_SEMANTIC_IDS[resolved],
        auth_alias_used=requested != resolved,
    )


def is_resolved_auth_mode(value: str) -> bool:
    """Return whether a value is an execution mode rather than an alias."""

    return value in RESOLVED_AUTH_MODES


__all__ = [
    "API_KEY_ENV",
    "AUTH_MODE_ALIASES",
    "AUTH_SEMANTIC_IDS",
    "AuthModeError",
    "AuthModeResolution",
    "AuthSemanticId",
    "CHATGPT_CLI_SESSION",
    "CREDENTIAL_AUTH_MODES",
    "CUSTOM_PROVIDER_ENVIRONMENT",
    "INHERITED_CODEX_LOGIN",
    "RESOLVED_AUTH_MODES",
    "RequestedAuthMode",
    "ResolvedAuthMode",
    "is_resolved_auth_mode",
    "resolve_auth_mode",
]
