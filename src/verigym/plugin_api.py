"""Stable MVP plugin-author imports."""

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.agents.external import ExternalAgentBridge
from verigym.core.agent_feedback_assets import (
    AgentEvalWorkspace,
    compile_feedback_contract,
    materialize_agent_eval_workspace,
)
from verigym.core.episode import TerminationReason
from verigym.core.errors import ConfigurationError, PathPolicyError
from verigym.core.external_process_identity import (
    bind_external_process_payload,
    build_external_process_request,
    preview_external_process_identity,
    resolve_external_process_invocation_spec,
    validate_external_process_request_identity,
)
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.repository_candidate import (
    build_repository_patch,
    freeze_repository_candidate,
    verify_frozen_repository_candidate,
)
from verigym.core.workspace import copy_tree_safely
from verigym.models.base import ModelClient, ModelClientError
from verigym.profiles.base import (
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
)
from verigym.profiles.validation import ProfileValidationResult
from verigym.prompts.policy import validate_prompt_text
from verigym.runtimes.base import Runtime, RuntimeSession
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    EpisodeResult,
    FinalSubmissionAction,
    Observation,
    ToolCallAction,
)
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import (
    AgentDescriptor,
    ArtifactDescriptor,
    AssetRef,
    ErrorCategory,
    InteractionMode,
    ModelDescriptor,
    RuntimeRequirement,
    SuiteDescriptor,
    TaskType,
    ToolchainProfile,
    ToolDescriptor,
    ToolRequirement,
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
    ProviderRequestIdentity,
)
from verigym.schemas.options import JsonScalar, JsonValue, validate_plugin_options
from verigym.schemas.prompt import AgentPromptPolicySpec, PromptPolicyDescriptor
from verigym.schemas.repository import RepositoryCandidateRecord, RepositoryWorkspaceContract
from verigym.schemas.score import EpisodeFailure
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.synthesis import SynthesisArtifactRef, SynthesisDiagnostic, SynthesisMetrics
from verigym.schemas.task import (
    BudgetSpec,
    Candidate,
    ConformanceCase,
    InteractionSpec,
    ObservationPolicy,
    ResolvedTaskAssets,
    ScoringSpec,
    SourceSpec,
    SubmissionPolicy,
    TaskRef,
    ValidationIssue,
    ValidationReport,
    VeriTask,
    WorkspaceSpec,
)
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.schemas.verifier import VerifierGraph, VerifierNode, VerifierResult, VerifierStatus
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile, VerifierToolProfile
from verigym.suites.base import SuiteAdapter
from verigym.tools.base import (
    SynthesisBackendPlugin,
    ToolContext,
    ToolPlugin,
    VerifierBackendPlugin,
)

__all__ = [
    "AgentAction",
    "AgentEvalWorkspace",
    "AgentAdapter",
    "AgentContext",
    "AgentDescriptor",
    "AgentPromptPolicySpec",
    "AgentTerminationError",
    "ApplyPatchAction",
    "AssetRef",
    "ArtifactDescriptor",
    "BudgetSpec",
    "Candidate",
    "CommandSpec",
    "CompletedCommand",
    "ConfigurationError",
    "ConformanceCase",
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
    "InteractionSpec",
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
    "ObservationPolicy",
    "PathPolicyError",
    "ProviderRequestIdentity",
    "PLUGIN_API_VERSION",
    "PromptPolicyDescriptor",
    "ProfileValidationResult",
    "ResolvedArtifactIdentity",
    "ResolvedRuntimeIdentity",
    "ResolvedTaskAssets",
    "RepositoryCandidateRecord",
    "RepositoryWorkspaceContract",
    "RuntimeRequirement",
    "ResolvedToolchainProfile",
    "ResolvedToolIdentity",
    "ResolvedVerifierToolProfile",
    "Runtime",
    "SCHEMA_VERSION",
    "ScoringSpec",
    "SourceSpec",
    "StrictModel",
    "SubmissionPolicy",
    "SuiteAdapter",
    "SuiteDescriptor",
    "SuiteSourceConfig",
    "SuiteSourceSnapshot",
    "SynthesisBackendPlugin",
    "SynthesisArtifactRef",
    "SynthesisDiagnostic",
    "SynthesisMetrics",
    "TaskRef",
    "TaskType",
    "ToolContext",
    "ToolDescriptor",
    "ToolPlugin",
    "ToolRequirement",
    "ToolResult",
    "ToolCallAction",
    "ToolchainProfile",
    "ToolVisibility",
    "RuntimeSession",
    "TerminationReason",
    "ValidationIssue",
    "ValidationReport",
    "VeriTask",
    "VerifierGraph",
    "VerifierBackendPlugin",
    "VerifierNode",
    "VerifierToolProfile",
    "VerifierResult",
    "VerifierStatus",
    "WorkspaceSpec",
    "validate_plugin_options",
    "validate_prompt_text",
    "build_repository_patch",
    "freeze_repository_candidate",
    "verify_frozen_repository_candidate",
    "bind_external_process_payload",
    "build_external_process_request",
    "content_hash",
    "compile_feedback_contract",
    "copy_tree_safely",
    "hash_bytes",
    "hash_directory",
    "materialize_agent_eval_workspace",
    "preview_external_process_identity",
    "resolve_external_process_invocation_spec",
    "validate_external_process_request_identity",
]
