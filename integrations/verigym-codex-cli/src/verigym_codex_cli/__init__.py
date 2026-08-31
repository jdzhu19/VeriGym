"""Separate Codex CLI integration package for VeriGym."""

from ._version import __version__
from .agent import CodexCliAgentAdapter, CodexCliHweAgentAdapter
from .agenteval_agent import CodexCliAgentEvalAdapter
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
from .functional_agenteval_agent import CodexCliFunctionalAgentEvalAdapter
from .functional_v2_agenteval_agent import (
    CodexCliFunctionalV2HighAgentEvalAdapter,
    CodexCliFunctionalV2LowAgentEvalAdapter,
    CodexCliFunctionalV2MediumAgentEvalAdapter,
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
    "CodexCliAgentEvalAdapter",
    "CodexCliFunctionalAgentEvalAdapter",
    "CodexCliFunctionalV2HighAgentEvalAdapter",
    "CodexCliFunctionalV2LowAgentEvalAdapter",
    "CodexCliFunctionalV2MediumAgentEvalAdapter",
    "CodexCliHweAgentAdapter",
    "CodexCliReadonlyAgentAdapter",
    "CodexCliMcpTeacherAdapter",
    "RequestedAuthMode",
    "ResolvedAuthMode",
    "__version__",
    "resolve_auth_mode",
    "run_auth_preflight",
]
