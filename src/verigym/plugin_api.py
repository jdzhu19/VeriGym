"""Stable MVP plugin-author imports."""

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.agents.external import ExternalAgentBridge
from verigym.core.episode import TerminationReason
from verigym.core.external_process_identity import (
    bind_external_process_payload,
    build_external_process_request,
    preview_external_process_identity,
    resolve_external_process_invocation_spec,
    validate_external_process_request_identity,
)
from verigym.models.base import ModelClient, ModelClientError
from verigym.prompts.policy import validate_prompt_text
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
    ExternalProcessIdentityPreview,
    ExternalProcessInvocationSpec,
    ExternalProcessPayloadBinding,
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalReadOnlyMountIdentity,
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
from verigym.schemas.prompt import AgentPromptPolicySpec, PromptPolicyDescriptor
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
    "AgentPromptPolicySpec",
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
    "ExternalProcessIdentityPreview",
    "ExternalProcessInvocationSpec",
    "ExternalProcessPayloadBinding",
    "ExternalProcessRequest",
    "ExternalProcessResult",
    "ExternalReadOnlyMountIdentity",
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
    "PromptPolicyDescriptor",
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
    "validate_prompt_text",
    "bind_external_process_payload",
    "build_external_process_request",
    "preview_external_process_identity",
    "resolve_external_process_invocation_spec",
    "validate_external_process_request_identity",
]
