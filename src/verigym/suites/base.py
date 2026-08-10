"""Benchmark adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from verigym.core.errors import ConfigurationError
from verigym.registry.base import PluginRegistry
from verigym.schemas.common import SuiteDescriptor, ToolchainProfile
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.task import (
    Candidate,
    ConformanceCase,
    ResolvedTaskAssets,
    TaskRef,
    ValidationReport,
    VeriTask,
)

if TYPE_CHECKING:
    from verigym.runtimes.base import Runtime
    from verigym.schemas.repository import RepositoryCandidateRecord
    from verigym.schemas.verifier import VerifierResult


class SuiteAdapter(ABC):
    descriptor: SuiteDescriptor

    @abstractmethod
    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        """Return lightweight deterministic task references."""

    @abstractmethod
    def load_task(self, ref: TaskRef) -> VeriTask:
        """Normalize one native task into the canonical IR."""

    @abstractmethod
    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        """Resolve visible and hidden assets without mixing their namespaces."""

    @abstractmethod
    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        """Validate source layout, checksums, and required files."""

    def reference_solution(self, task: VeriTask) -> Candidate | None:
        return None

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        return []

    def with_source(self, config: SuiteSourceConfig) -> SuiteAdapter:
        raise ConfigurationError(
            f"suite {self.descriptor.name!r} does not accept an external source"
        )

    def source_snapshot(self) -> SuiteSourceSnapshot | None:
        return None

    def toolchain_profile(
        self,
        runtime: Runtime,
        tools: PluginRegistry[Any],
    ) -> ToolchainProfile | None:
        return None

    def freeze_repository_candidate(
        self,
        *,
        task: VeriTask,
        candidate_dir: Path,
        run_root: Path,
        artifact_root: Path,
    ) -> RepositoryCandidateRecord | None:
        """Freeze suite-specific repository artifacts after the ordinary candidate handoff."""

        del task, candidate_dir, run_root, artifact_root
        return None

    def replay_repository_candidate(
        self,
        *,
        task: VeriTask,
        candidate_dir: Path,
        run_root: Path,
        record: RepositoryCandidateRecord,
    ) -> None:
        """Validate suite-specific repository artifacts without agent or verifier access."""

        del task, candidate_dir, run_root, record
        raise ConfigurationError("suite does not implement repository candidate replay")

    def verify_candidate(
        self,
        *,
        task: VeriTask,
        candidate_dir: Path,
        artifact_root: Path,
    ) -> list[VerifierResult] | None:
        """Optionally execute a suite-owned, trusted verifier implementation.

        Returning ``None`` selects VeriGym's ordinary verifier DAG executor. This hook is for
        external benchmarks whose immutable verification environment cannot be represented by a
        normal tool plugin and runtime session, such as one-container-per-instance benchmarks.
        """

        del task, candidate_dir, artifact_root
        return None
