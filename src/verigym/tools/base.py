"""Tool plugin contract and execution context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from verigym.core.repository_observation import (
    RawObservationCallback,
    RepositoryObservationPolicy,
)
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.runtimes.base import Runtime, RuntimeSession
from verigym.schemas.common import ToolchainProfile, ToolDescriptor
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile, VerifierToolProfile


@dataclass(frozen=True)
class ToolContext:
    session: RuntimeSession | None = None
    workspace_policy: Any | None = None
    max_output_bytes: int = 1_000_000
    artifact_dir: Path | None = None
    observation_policy: RepositoryObservationPolicy | None = None
    audit_callback: RawObservationCallback | None = None
    public_test_executor: Callable[[str, RuntimeSession], CompletedCommand] | None = None
    verifier_profile: VerifierToolProfile | None = None
    resolved_verifier_profile: ResolvedVerifierToolProfile | None = None


class ToolPlugin(ABC):
    descriptor: ToolDescriptor

    @abstractmethod
    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        """Check external dependencies and configuration."""

    @abstractmethod
    def validate_request(self, request: dict[str, Any]) -> BaseModel:
        """Validate an untrusted structured request."""

    @abstractmethod
    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        """Render a safe argument-array command."""

    @abstractmethod
    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        """Normalize command output into the stable error taxonomy."""

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate_request(raw_request)
        command = self.build_command(request, context)
        if command.requires_shell:
            raise ValueError(f"tool {self.descriptor.name} requested a shell unexpectedly")
        if context.session is None:
            raise ValueError(f"tool {self.descriptor.name} requires a runtime session")
        completed = context.session.execute(command)
        return self.parse_result(request, completed, context)


class SynthesisBackendPlugin(ToolPlugin):
    """Trusted extension point for profile-specific synthesis behavior."""

    artifact_namespace: str

    @abstractmethod
    def validate_profile_contract(self, profile: ToolchainProfile) -> Any:
        """Return a profile validation result without running synthesis."""

    @abstractmethod
    def resolve_profile(
        self,
        profile: ToolchainProfile,
        runtime: Runtime,
        *,
        source_paths: list[str],
        top_module: str,
        reference_candidate_hash: str | None,
        expected: ResolvedToolchainProfile | None = None,
    ) -> ResolvedToolchainProfile:
        """Bind the profile to exact tools, assets, runtime, and flow identity."""

    @abstractmethod
    def build_synthesis_request(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
        *,
        run_label: str,
    ) -> dict[str, Any]:
        """Build one strict candidate or reference request."""

    @abstractmethod
    def stage_profile_assets(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
        staging: Path,
    ) -> None:
        """Copy only profile-approved assets into verifier-private staging."""


class VerifierBackendPlugin(ToolPlugin):
    """Verifier-only backend whose external transport must resolve before model lookup."""

    @abstractmethod
    def resolve_verifier_profile(
        self,
        profile: VerifierToolProfile,
        *,
        expected: ResolvedVerifierToolProfile | None = None,
    ) -> ResolvedVerifierToolProfile:
        """Resolve transport and remote tool identity without evaluating a candidate."""


__all__ = ["SynthesisBackendPlugin", "ToolContext", "ToolPlugin", "VerifierBackendPlugin"]
