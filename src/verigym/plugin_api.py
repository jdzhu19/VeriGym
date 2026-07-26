"""Stable MVP plugin-author imports."""

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.agents.external import ExternalAgentBridge
from verigym.core.episode import TerminationReason
from verigym.models.base import ModelClient, ModelClientError
from verigym.schemas.agent import AgentAction, EpisodeResult, FinalSubmissionAction, Observation
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import (
    AgentDescriptor,
    ErrorCategory,
    InteractionMode,
    ModelDescriptor,
    SuiteDescriptor,
    ToolDescriptor,
    ToolVisibility,
)
from verigym.schemas.external_agent import (
    ExternalAgentAccounting,
    ExternalAgentCallIdentity,
    ExternalProcessRequest,
    ExternalProcessResult,
)
from verigym.schemas.model import (
    ModelClientErrorInfo,
    ModelErrorCategory,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRunConfig,
    NormalizedModelUsage,
)
from verigym.schemas.options import JsonScalar, JsonValue, validate_plugin_options
from verigym.schemas.score import EpisodeFailure
from verigym.schemas.task import (
    ResolvedTaskAssets,
    TaskRef,
    ValidationReport,
    VeriTask,
)
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.suites.base import SuiteAdapter
from verigym.tools.base import ToolContext, ToolPlugin

__all__ = [
    "AgentAction",
    "AgentAdapter",
    "AgentContext",
    "AgentDescriptor",
    "AgentTerminationError",
    "CommandSpec",
    "CompletedCommand",
    "EpisodeResult",
    "ErrorCategory",
    "EpisodeFailure",
    "FinalSubmissionAction",
    "ExternalAgentAccounting",
    "ExternalAgentBridge",
    "ExternalAgentCallIdentity",
    "ExternalProcessRequest",
    "ExternalProcessResult",
    "HealthCheckResult",
    "Observation",
    "InteractionMode",
    "JsonScalar",
    "JsonValue",
    "ModelClient",
    "ModelClientError",
    "ModelClientErrorInfo",
    "ModelDescriptor",
    "ModelErrorCategory",
    "ModelFinishReason",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
    "ModelRunConfig",
    "NormalizedModelUsage",
    "PLUGIN_API_VERSION",
    "ResolvedTaskAssets",
    "SCHEMA_VERSION",
    "StrictModel",
    "SuiteAdapter",
    "SuiteDescriptor",
    "TaskRef",
    "ToolContext",
    "ToolDescriptor",
    "ToolPlugin",
    "ToolResult",
    "ToolVisibility",
    "TerminationReason",
    "ValidationReport",
    "VeriTask",
    "validate_plugin_options",
]
