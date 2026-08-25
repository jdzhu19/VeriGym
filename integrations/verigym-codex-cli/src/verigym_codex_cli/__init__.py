"""Separate Codex CLI integration package for VeriGym."""

from ._version import __version__
from .agent import CodexCliAgentAdapter, CodexCliHweAgentAdapter
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
from .preflight import AuthPreflightResult, run_auth_preflight
from .readonly_agent import CodexCliReadonlyAgentAdapter
from .teacher_agent import CodexCliMcpTeacherAdapter

__all__ = [
    "AUTH_MODE_ALIASES",
    "AUTH_SEMANTIC_IDS",
    "AuthModeError",
    "AuthModeResolution",
    "AuthPreflightResult",
    "AuthSemanticId",
    "CodexCliAgentAdapter",
    "CodexCliHweAgentAdapter",
    "CodexCliReadonlyAgentAdapter",
    "CodexCliMcpTeacherAdapter",
    "RequestedAuthMode",
    "ResolvedAuthMode",
    "__version__",
    "resolve_auth_mode",
    "run_auth_preflight",
]
