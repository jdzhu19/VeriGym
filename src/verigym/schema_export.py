"""Deterministic JSON Schema export for persistent MVP artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from verigym.campaign.schemas import CampaignConfig, CampaignReport
from verigym.experiments.schemas import (
    BatchEvent,
    ExperimentConfig,
    ExperimentManifest,
    ExperimentPlan,
    ExperimentState,
    ModelProcessLedgerRecord,
    PlanItem,
    RunIndexRecord,
)
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.reporting.schemas import AggregateReport
from verigym.schemas.action_protocol import (
    CanonicalRepositoryAction,
    ProviderNativeToolCall,
    RepositoryActionProtocolDescriptor,
    RepositoryActionProtocolSpec,
    RepositoryActionTurnRecord,
)
from verigym.schemas.agent import AgentAction, Observation
from verigym.schemas.audit import AuditManifest, EvidenceEntry
from verigym.schemas.common import (
    AgentDescriptor,
    ModelDescriptor,
    RuntimeDescriptor,
    SuiteDescriptor,
    ToolchainProfile,
    ToolDescriptor,
)
from verigym.schemas.evolution import (
    AgentLineage,
    AgentUpdateManifest,
    AgentVersionManifest,
    AgentVersionSetManifest,
    AllowedSynthesisCorpus,
    AssetSignatureManifest,
    ContaminationScan,
    ContaminationScanPolicy,
    ContaminationScanReport,
    EpisodeTrajectory,
    EvolutionProcessLedgerManifest,
    EvolutionProcessLedgerRecord,
    EvolvingEvaluationReport,
    ExternalAgentVersionImportManifest,
    ExternalTrainerExportManifest,
    FrozenMemoryContaminationScan,
    HistoricalTrainingEpisodeImportEligibility,
    HistoricalTrainingImportManifest,
    MemoryBuilderInput,
    MemoryBuilderResult,
    MemoryPack,
    MemoryPackAudit,
    MemorySynthesisPlan,
    RewardAnalysisReport,
    RewardChannel,
    RewardChannelStatistics,
    RewardDerivationRecord,
    RewardProfile,
    RewardVector,
    RunAgentVersionAssignment,
    RunAgentVersionAssignments,
    SanitizedTrainingSummary,
    SplitAssetContaminationScan,
    TaskSplitManifest,
    TrajectoryDatasetManifest,
    TrajectoryDatasetReport,
    TrajectoryDatasetStatistics,
    TrajectoryEvent,
    TrajectoryIndexRecord,
)
from verigym.schemas.external_agent import (
    ExternalAgentAccounting,
    ExternalAgentCallIdentity,
    ExternalProcessIdentityPreview,
    ExternalProcessInvocationSpec,
    ExternalProcessPayloadBinding,
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalProcessRuntimeIdentity,
    ExternalProcessSecurityEvidence,
)
from verigym.schemas.hwe import (
    HweActionConditionedSftDatasetManifest,
    HweActionConditionedSftExample,
    HweDeepSeekHarnessActionSftDatasetManifest,
    HweDeepSeekHarnessActionSftExample,
    HweDeepSeekHarnessDecisionSftDatasetManifestV3,
    HweDeepSeekHarnessDecisionSftDatasetManifestV4,
    HweDeepSeekHarnessDecisionSftExampleV3,
    HweDeepSeekHarnessDecisionSftExampleV4,
    HweObservationMaskingAnalysis,
)
from verigym.schemas.hwe_training import (
    HweCoactDatasetManifest,
    HweCoactExample,
    HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
    HweDecisionSft64kDevelopmentTrainingPreregistration,
    HweDecisionSft64kDevelopmentTrainingPreregistrationReceipt,
    HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization,
    HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
    HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerFullSmokeReplayAuthorization,
    HweDecisionSft64kOptimizerSmokeExecutionAuthorization,
    HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization,
    HweDecisionSft64kOptimizerSmokePreregistration,
    HweTrainingReadyActionConditionedExample,
    HweTrainingReadyActionConditionedManifest,
)
from verigym.schemas.integrity import ArtifactManifest, IntegrityValidation
from verigym.schemas.model import (
    ModelCallIdentity,
    ModelRequest,
    ModelResponse,
    ProviderRequestIdentity,
)
from verigym.schemas.prompt import (
    AgentPromptPolicySpec,
    PromptPolicyDescriptor,
    ToolPolicySnapshot,
)
from verigym.schemas.provenance import BuildProvenance
from verigym.schemas.release import ReleaseManifest
from verigym.schemas.replay import ReplayEvidence
from verigym.schemas.repository import (
    RepositoryCandidateRecord,
    RepositoryPatchSummary,
    RepositoryPlanIdentity,
    RepositoryPublicTestContract,
    RepositoryPublicTestOutcome,
    RepositorySnapshot,
    RepositoryTaskManifest,
    RepositoryWorkspaceContract,
)
from verigym.schemas.run import RunConfig, RunManifest
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.sampling import PassAtKReport, SampleRunRef, SampleSetManifest
from verigym.schemas.score import ScoreCard
from verigym.schemas.security_scan import (
    ArtifactSecurityScan,
    SecurityFinding,
    SecurityScanPolicy,
    SecurityScanReport,
)
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.synthesis import SynthesisMetrics
from verigym.schemas.task import VeriTask
from verigym.schemas.tool import ToolResult
from verigym.schemas.trace import EpisodeEvent
from verigym.schemas.verifier import VerifierGraph, VerifierResult
from verigym.suites.verilog_eval.schemas import NativeRegressionResult

SchemaFactory = Callable[[], dict[str, Any]]


def _model(model: type[BaseModel]) -> SchemaFactory:
    return lambda: model.model_json_schema(mode="serialization")


_SCHEMAS: dict[str, SchemaFactory] = {
    "action": lambda: TypeAdapter(AgentAction).json_schema(mode="serialization"),
    "agent-descriptor": _model(AgentDescriptor),
    "canonical-repository-action": _model(CanonicalRepositoryAction),
    "agent-prompt-policy-spec": _model(AgentPromptPolicySpec),
    "agent-lineage": _model(AgentLineage),
    "agent-update-manifest": _model(AgentUpdateManifest),
    "agent-version-manifest": _model(AgentVersionManifest),
    "agent-version-set-manifest": _model(AgentVersionSetManifest),
    "allowed-synthesis-corpus": _model(AllowedSynthesisCorpus),
    "aggregate-report": _model(AggregateReport),
    "audit-manifest": _model(AuditManifest),
    "artifact-manifest": _model(ArtifactManifest),
    "artifact-security-scan": _model(ArtifactSecurityScan),
    "asset-signature-manifest": _model(AssetSignatureManifest),
    "batch-event": _model(BatchEvent),
    "build-provenance": _model(BuildProvenance),
    "campaign-config": _model(CampaignConfig),
    "campaign-report": _model(CampaignReport),
    "contamination-scan": _model(ContaminationScan),
    "contamination-scan-policy": _model(ContaminationScanPolicy),
    "contamination-scan-report": _model(ContaminationScanReport),
    "docker-runtime-config": _model(DockerRuntimeConfig),
    "episode-event": _model(EpisodeEvent),
    "episode-trajectory": _model(EpisodeTrajectory),
    "evidence-entry": _model(EvidenceEntry),
    "evolving-evaluation-report": _model(EvolvingEvaluationReport),
    "evolution-process-ledger-manifest": _model(EvolutionProcessLedgerManifest),
    "evolution-process-ledger-record": _model(EvolutionProcessLedgerRecord),
    "experiment-config": _model(ExperimentConfig),
    "experiment-manifest": _model(ExperimentManifest),
    "experiment-plan": _model(ExperimentPlan),
    "experiment-state": _model(ExperimentState),
    "external-agent-accounting": _model(ExternalAgentAccounting),
    "external-agent-call-identity": _model(ExternalAgentCallIdentity),
    "external-process-identity-preview": _model(ExternalProcessIdentityPreview),
    "external-process-invocation-spec": _model(ExternalProcessInvocationSpec),
    "external-process-payload-binding": _model(ExternalProcessPayloadBinding),
    "external-process-request": _model(ExternalProcessRequest),
    "external-process-result": _model(ExternalProcessResult),
    "external-process-runtime-identity": _model(ExternalProcessRuntimeIdentity),
    "external-process-security-evidence": _model(ExternalProcessSecurityEvidence),
    "external-agent-version-import-manifest": _model(ExternalAgentVersionImportManifest),
    "external-trainer-export-manifest": _model(ExternalTrainerExportManifest),
    "frozen-memory-contamination-scan": _model(FrozenMemoryContaminationScan),
    "integrity-validation": _model(IntegrityValidation),
    "model-call-identity": _model(ModelCallIdentity),
    "model-descriptor": _model(ModelDescriptor),
    "model-process-ledger-record": _model(ModelProcessLedgerRecord),
    "model-request": _model(ModelRequest),
    "model-response": _model(ModelResponse),
    "provider-request-identity": _model(ProviderRequestIdentity),
    "provider-native-tool-call": _model(ProviderNativeToolCall),
    "memory-pack": _model(MemoryPack),
    "memory-pack-audit": _model(MemoryPackAudit),
    "memory-builder-input": _model(MemoryBuilderInput),
    "memory-builder-result": _model(MemoryBuilderResult),
    "memory-synthesis-plan": _model(MemorySynthesisPlan),
    "historical-training-episode-import-eligibility": _model(
        HistoricalTrainingEpisodeImportEligibility
    ),
    "historical-training-import-manifest": _model(HistoricalTrainingImportManifest),
    "hwe-action-conditioned-sft": _model(HweActionConditionedSftExample),
    "hwe-action-conditioned-sft-dataset": _model(HweActionConditionedSftDatasetManifest),
    "hwe-deepseek-harness-action-sft": _model(HweDeepSeekHarnessActionSftExample),
    "hwe-deepseek-harness-action-sft-dataset": _model(HweDeepSeekHarnessActionSftDatasetManifest),
    "hwe-deepseek-harness-decision-sft-v3": _model(HweDeepSeekHarnessDecisionSftExampleV3),
    "hwe-deepseek-harness-decision-sft-dataset-v3": _model(
        HweDeepSeekHarnessDecisionSftDatasetManifestV3
    ),
    "hwe-deepseek-harness-decision-sft-64k-v4": _model(HweDeepSeekHarnessDecisionSftExampleV4),
    "hwe-deepseek-harness-decision-sft-dataset-64k-v4": _model(
        HweDeepSeekHarnessDecisionSftDatasetManifestV4
    ),
    "hwe-observation-masking-analysis": _model(HweObservationMaskingAnalysis),
    "hwe-coact-multiturn-sft": _model(HweCoactExample),
    "hwe-coact-multiturn-sft-dataset": _model(HweCoactDatasetManifest),
    "hwe-decision-sft-64k-optimizer-smoke-preregistration": _model(
        HweDecisionSft64kOptimizerSmokePreregistration
    ),
    "hwe-decision-sft-64k-optimizer-smoke-execution-authorization": _model(
        HweDecisionSft64kOptimizerSmokeExecutionAuthorization
    ),
    "hwe-decision-sft-64k-optimizer-smoke-execution-retry-authorization": _model(
        HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization
    ),
    "hwe-decision-sft-64k-optimizer-diagnostic-replay-authorization": _model(
        HweDecisionSft64kOptimizerDiagnosticReplayAuthorization
    ),
    "hwe-decision-sft-64k-optimizer-bf16-tolerance-replay-authorization": _model(
        HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization
    ),
    "hwe-decision-sft-64k-optimizer-authorized-schedule-replay-authorization": _model(
        HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization
    ),
    "hwe-decision-sft-64k-optimizer-full-smoke-replay-authorization": _model(
        HweDecisionSft64kOptimizerFullSmokeReplayAuthorization
    ),
    "hwe-decision-sft-64k-optimizer-full-smoke-bf16-tolerance-replay-authorization": _model(
        HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization
    ),
    "hwe-decision-sft-64k-checkpoint-resume-qualification-authorization": _model(
        HweDecisionSft64kCheckpointResumeQualificationAuthorization
    ),
    "hwe-decision-sft-64k-development-training-v1": _model(
        HweDecisionSft64kDevelopmentTrainingPreregistration
    ),
    "hwe-decision-sft-64k-development-training-execution-authorization": _model(
        HweDecisionSft64kDevelopmentTrainingExecutionAuthorization
    ),
    "hwe-decision-sft-64k-development-training-preregistration-receipt": _model(
        HweDecisionSft64kDevelopmentTrainingPreregistrationReceipt
    ),
    "hwe-training-ready-action-conditioned-sft": _model(HweTrainingReadyActionConditionedExample),
    "hwe-training-ready-action-conditioned-sft-dataset": _model(
        HweTrainingReadyActionConditionedManifest
    ),
    "native-regression-result": _model(NativeRegressionResult),
    "observation": _model(Observation),
    "pass-at-k-report": _model(PassAtKReport),
    "plan-item": _model(PlanItem),
    "prompt-policy-descriptor": _model(PromptPolicyDescriptor),
    "release-manifest": _model(ReleaseManifest),
    "replay-evidence": _model(ReplayEvidence),
    "repository-candidate-record": _model(RepositoryCandidateRecord),
    "repository-action-protocol-descriptor": _model(RepositoryActionProtocolDescriptor),
    "repository-action-protocol-spec": _model(RepositoryActionProtocolSpec),
    "repository-action-turn-record": _model(RepositoryActionTurnRecord),
    "repository-patch-summary": _model(RepositoryPatchSummary),
    "repository-plan-identity": _model(RepositoryPlanIdentity),
    "repository-public-test-contract": _model(RepositoryPublicTestContract),
    "repository-public-test-outcome": _model(RepositoryPublicTestOutcome),
    "repository-snapshot": _model(RepositorySnapshot),
    "repository-task-manifest": _model(RepositoryTaskManifest),
    "repository-workspace-contract": _model(RepositoryWorkspaceContract),
    "reward-derivation-record": _model(RewardDerivationRecord),
    "reward-channel": _model(RewardChannel),
    "reward-channel-statistics": _model(RewardChannelStatistics),
    "reward-analysis-report": _model(RewardAnalysisReport),
    "reward-profile": _model(RewardProfile),
    "reward-vector": _model(RewardVector),
    "run-agent-version-assignment": _model(RunAgentVersionAssignment),
    "run-agent-version-assignments": _model(RunAgentVersionAssignments),
    "resolved-toolchain-profile": _model(ResolvedToolchainProfile),
    "run-config": _model(RunConfig),
    "run-index-record": _model(RunIndexRecord),
    "run-manifest": _model(RunManifest),
    "runtime-descriptor": _model(RuntimeDescriptor),
    "sample-run-ref": _model(SampleRunRef),
    "sample-set-manifest": _model(SampleSetManifest),
    "sanitized-training-summary": _model(SanitizedTrainingSummary),
    "scorecard": _model(ScoreCard),
    "security-finding": _model(SecurityFinding),
    "security-scan-policy": _model(SecurityScanPolicy),
    "security-scan-report": _model(SecurityScanReport),
    "suite-descriptor": _model(SuiteDescriptor),
    "suite-source-config": _model(SuiteSourceConfig),
    "suite-source-snapshot": _model(SuiteSourceSnapshot),
    "synthesis-metrics": _model(SynthesisMetrics),
    "split-asset-contamination-scan": _model(SplitAssetContaminationScan),
    "task-split-manifest": _model(TaskSplitManifest),
    "task": _model(VeriTask),
    "tool-descriptor": _model(ToolDescriptor),
    "tool-policy-snapshot": _model(ToolPolicySnapshot),
    "tool-result": _model(ToolResult),
    "toolchain-profile": _model(ToolchainProfile),
    "trajectory-dataset-manifest": _model(TrajectoryDatasetManifest),
    "trajectory-dataset-report": _model(TrajectoryDatasetReport),
    "trajectory-dataset-statistics": _model(TrajectoryDatasetStatistics),
    "trajectory-event": _model(TrajectoryEvent),
    "trajectory-index-record": _model(TrajectoryIndexRecord),
    "verifier-graph": _model(VerifierGraph),
    "verifier-result": _model(VerifierResult),
}


def rendered_schemas() -> dict[str, str]:
    rendered: dict[str, str] = {}
    for name, factory in sorted(_SCHEMAS.items()):
        schema = factory()
        schema["$id"] = f"https://verigym.dev/schemas/1.0/{name}.schema.json"
        rendered[f"{name}.schema.json"] = (
            json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
    return rendered


def export_schemas(output: Path, *, check: bool = False) -> list[str]:
    """Write schemas, or return drift paths without modifying files in check mode."""

    expected = rendered_schemas()
    drift: list[str] = []
    existing = {path.name for path in output.glob("*.schema.json")} if output.is_dir() else set()
    for name, payload in expected.items():
        path = output / name
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != payload:
            drift.append(name)
            if not check:
                output.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding="utf-8")
    extras = sorted(existing - set(expected))
    drift.extend(extras)
    if not check:
        for name in extras:
            (output / name).unlink()
    return sorted(drift)


__all__ = ["export_schemas", "rendered_schemas"]
