"""Separate Codex CLI integration package for VeriGym."""

from ._version import __version__
from .agent import CodexCliAgentAdapter
from .auth import (
    AUTH_MODE_ALIASES,
    AUTH_SEMANTIC_IDS,
    AuthModeError,
    AuthModeResolution,
    AuthSemanticId,
    RequestedAuthMode,
    ResolvedAuthMode,
    resolve_auth_mode,
)
from .model import CodexExecModelClient
from .preflight import AuthPreflightResult, run_auth_preflight

__all__ = [
    "AUTH_MODE_ALIASES",
    "AUTH_SEMANTIC_IDS",
    "AuthModeError",
    "AuthModeResolution",
    "AuthPreflightResult",
    "AuthSemanticId",
    "CodexCliAgentAdapter",
    "CodexExecModelClient",
    "RequestedAuthMode",
    "ResolvedAuthMode",
    "__version__",
    "resolve_auth_mode",
    "run_auth_preflight",
]
