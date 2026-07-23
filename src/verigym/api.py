"""Documented, stable Python facade for the MVP."""

from verigym.core.orchestrator import VeriGym
from verigym.core.replay import ReplaySummary, replay_run
from verigym.experiments.config import load_experiment_config
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import (
    BatchResult,
    ExperimentConfig,
    ExperimentPlan,
)
from verigym.provenance import get_build_provenance
from verigym.registry import (
    PluginDiagnostic,
    PluginOrigin,
    PluginRegistry,
    Registries,
    build_registries,
)
from verigym.reporting.aggregate import ReportBuilder
from verigym.reporting.service import GeneratedReports, ReportService
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.sampling import PassAtKReport, SampleSetManifest, SampleSetResult
from verigym.schemas.score import ScoreCard
from verigym.version import __version__

__all__ = [
    "BatchResult",
    "BatchRunner",
    "ExperimentConfig",
    "ExperimentPlan",
    "ExperimentPlanner",
    "GeneratedReports",
    "PassAtKReport",
    "PluginDiagnostic",
    "PluginOrigin",
    "PluginRegistry",
    "Registries",
    "ReplaySummary",
    "ReportBuilder",
    "ReportService",
    "RunConfig",
    "RunManifest",
    "RunResult",
    "SampleSetManifest",
    "SampleSetResult",
    "ScoreCard",
    "VeriGym",
    "__version__",
    "build_registries",
    "get_build_provenance",
    "load_experiment_config",
    "replay_run",
]
