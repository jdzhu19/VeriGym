"""Strict persistent schemas for observable trajectories and Evolve-Context."""

from __future__ import annotations

import re
from typing import Literal, get_args

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.external_agent import (
    ExternalProcessIdentityPreview,
    ExternalProcessInvocationSpec,
    ExternalProcessPayloadBinding,
)
from verigym.schemas.options import JsonValue

_HASH = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

ContentClass = Literal[
    "public_task",
    "public_tool_output",
    "agent_generated",
    "workspace_metadata",
    "candidate_public",
    "score_summary",
    "sensitive_redacted",
]
TrajectoryEventType = Literal[
    "task_observation",
    "agent_message",
    "tool_invocation",
    "tool_result",
    "workspace_delta",
    "public_test",
    "candidate_freeze",
    "episode_outcome",
    "usage",
    "reward",
]
EpisodeOutcomeKind = Literal[
    "resolved_candidate",
    "incorrect_policy_compliant_candidate",
    "contained_workspace_policy_failure",
    "strict_output_failure",
    "infrastructure_invalid",
    "cancelled_or_interrupted",
]
RewardValue = int | float | None
MemoryBuilderFailureReason = Literal[
    "process_timeout",
    "process_output_limit",
    "process_nonzero_exit",
    "runtime_security_incomplete",
    "event_stream_parse_error",
    "terminal_stream_incomplete",
    "event_policy_rejected",
    "workspace_not_empty_before",
    "workspace_not_empty_after",
    "workspace_changed",
    "memory_policy_code_fence",
    "memory_policy_rtl_code",
    "memory_policy_task_id",
    "memory_policy_repository_path",
    "memory_policy_hash",
    "memory_policy_hidden_or_reference",
    "memory_policy_credential",
    "memory_policy_heldout_only",
    "memory_output_invalid",
]


def _hash(value: str) -> str:
    if not _HASH.fullmatch(value):
        raise ValueError("identity fields must be lowercase SHA-256 values")
    return value


def _safe_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("identifiers must use the stable printable identifier vocabulary")
    return value


def _safe_task_id(value: str) -> str:
    if not _SAFE_TASK_ID.fullmatch(value):
        raise ValueError("task IDs must be canonical '<suite>/<native-id>' identities")
    return value


class TrajectoryEligibility(StrictModel):
    schema_version: str = SCHEMA_VERSION
    eligible: bool
    reason: Literal[
        "eligible",
        "infrastructure_invalid",
        "cancelled_or_interrupted",
        "integrity_invalid",
        "content_policy_rejected",
    ]

    @model_validator(mode="after")
    def reason_matches_status(self) -> TrajectoryEligibility:
        if self.eligible != (self.reason == "eligible"):
            raise ValueError("trajectory eligibility and reason disagree")
        return self


class BoundedObservableText(StrictModel):
    schema_version: str = SCHEMA_VERSION
    text: str
    original_bytes: int = Field(ge=0)
    original_sha256: str
    truncated: bool

    @field_validator("original_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class TrajectoryEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    sequence: int = Field(ge=0)
    event_type: TrajectoryEventType
    content_class: ContentClass
    payload: dict[str, JsonValue]
    payload_sha256: str
    truncated: bool = False

    @field_validator("payload_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class ObservableAgentMessage(StrictModel):
    schema_version: str = SCHEMA_VERSION
    role: Literal["assistant"]
    message: BoundedObservableText
    source_event_sequence: int | None = Field(default=None, ge=0)


class ObservableToolInvocation(StrictModel):
    schema_version: str = SCHEMA_VERSION
    tool_name: str
    argument_names: list[str] = Field(default_factory=list, max_length=64)
    public_test_id: str | None = None
    source_event_sequence: int | None = Field(default=None, ge=0)

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        return _safe_id(value)


class ObservableToolResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    tool_name: str
    success: bool
    category: str
    bounded_public_output: BoundedObservableText | None = None
    source_event_sequence: int | None = Field(default=None, ge=0)

    @field_validator("tool_name", "category")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _safe_id(value)


class WorkspaceDeltaRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    changed_files: list[str] = Field(default_factory=list, max_length=256)
    added_lines: int = Field(ge=0)
    deleted_lines: int = Field(ge=0)
    outside_expected_files: list[str] = Field(default_factory=list, max_length=256)
    patch_sha256: str | None = None
    patch_reproducible: bool | None = None

    @field_validator("patch_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None


class PublicTestObservation(StrictModel):
    schema_version: str = SCHEMA_VERSION
    test_id: str
    passed: bool
    failure_category: str | None = None
    bounded_feedback: BoundedObservableText | None = None

    @field_validator("test_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)


class CandidateFreezeObservation(StrictModel):
    schema_version: str = SCHEMA_VERSION
    candidate_hash: str
    patch_hash: str | None = None
    final_repository_hash: str | None = None
    patch_reproducible: bool | None = None
    changed_file_count: int = Field(ge=0)

    @field_validator("candidate_hash", "patch_hash", "final_repository_hash")
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None


class EpisodeOutcomeObservation(StrictModel):
    schema_version: str = SCHEMA_VERSION
    outcome_kind: EpisodeOutcomeKind
    scorecard_status: str
    termination_reason: str
    resolved: bool
    infrastructure_error: bool
    policy_failure: bool
    compile_passed: bool | None = None
    hidden_regression_passed: bool | None = None


class RewardVector(StrictModel):
    schema_version: str = SCHEMA_VERSION
    outcome_kind: EpisodeOutcomeKind
    infrastructure_valid: Literal[0, 1]
    policy_compliance: Literal[0, 1] | None
    public_test_reached: Literal[0, 1] | None
    public_test_passed: Literal[0, 1] | None
    patch_reproducible: Literal[0, 1] | None
    candidate_compile_passed: Literal[0, 1] | None
    hidden_regression_passed: Literal[0, 1] | None
    task_resolved: Literal[0, 1] | None
    changed_file_count: int | None = Field(default=None, ge=0)
    added_lines: int | None = Field(default=None, ge=0)
    deleted_lines: int | None = Field(default=None, ge=0)
    public_tool_calls: int | None = Field(default=None, ge=0)
    wall_time_s: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def unavailable_channels_remain_null(self) -> RewardVector:
        correctness = (
            self.policy_compliance,
            self.public_test_reached,
            self.public_test_passed,
            self.patch_reproducible,
            self.candidate_compile_passed,
            self.hidden_regression_passed,
            self.task_resolved,
        )
        if not self.infrastructure_valid and any(value is not None for value in correctness):
            raise ValueError("infrastructure-invalid rewards must not coerce correctness to zero")
        return self


class RewardChannel(StrictModel):
    schema_version: str = SCHEMA_VERSION
    name: str
    value: RewardValue
    unit: Literal["binary", "count", "lines", "seconds", "tokens"]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _safe_id(value)


class RewardProfile(StrictModel):
    schema_version: str = SCHEMA_VERSION
    profile_id: str
    profile_version: str
    outcome_values: dict[EpisodeOutcomeKind, float | None]
    universal_benchmark_score: Literal[False] = False
    profile_hash: str

    @field_validator("profile_id", "profile_version")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("profile_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class RewardDerivationRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    reward_schema_id: Literal["repo_rtl_reward_vector_v1"] = "repo_rtl_reward_vector_v1"
    source_artifact_hashes: dict[str, str]
    reward: RewardVector
    reward_hash: str
    scalar_profile_id: str | None = None
    scalar_profile_hash: str | None = None
    scalar_reward: float | None = None
    offline_recomputed: Literal[True] = True
    external_calls: Literal[0] = 0

    @field_validator("run_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("source_artifact_hashes")
    @classmethod
    def validate_source_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: _hash(value) for key, value in sorted(values.items())}

    @field_validator("reward_hash", "scalar_profile_hash")
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None


class TaskSplitEntry(StrictModel):
    task_id: str
    source_hash: str
    task_hash: str
    license: str
    attribution: str

    @field_validator("task_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_task_id(value)

    @field_validator("source_hash", "task_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


class TaskSplitManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    split_id: str
    training: list[TaskSplitEntry]
    validation: list[TaskSplitEntry] = Field(default_factory=list)
    heldout: list[TaskSplitEntry]
    heldout_assets_loaded_after_version_hash: str | None = None
    manifest_hash: str

    @field_validator("split_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("heldout_assets_loaded_after_version_hash", "manifest_hash")
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @model_validator(mode="after")
    def splits_are_disjoint(self) -> TaskSplitManifest:
        groups = {
            "training": self.training,
            "validation": self.validation,
            "heldout": self.heldout,
        }
        seen_ids: dict[str, str] = {}
        seen_sources: dict[str, str] = {}
        for split, entries in groups.items():
            for entry in entries:
                if entry.task_id in seen_ids or entry.source_hash in seen_sources:
                    raise ValueError("task IDs and source hashes may appear in only one split")
                seen_ids[entry.task_id] = split
                seen_sources[entry.source_hash] = split
        return self


class ContaminationFinding(StrictModel):
    schema_version: str = SCHEMA_VERSION
    category: Literal[
        "task_id_overlap",
        "source_hash_overlap",
        "identical_file",
        "reference_fragment",
        "hidden_test_fragment",
        "issue_text_overlap",
        "memory_heldout_token",
    ]
    training_identity: str
    heldout_identity: str
    evidence_hash: str

    @field_validator("evidence_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class ContaminationScan(StrictModel):
    schema_version: str = SCHEMA_VERSION
    scan_id: str
    split_manifest_hash: str
    memory_pack_hash: str | None = None
    findings: list[ContaminationFinding]
    passed: bool
    train_file_count: int = Field(ge=0)
    heldout_file_count: int = Field(ge=0)
    hidden_assets_exported: Literal[False] = False
    reference_assets_exported: Literal[False] = False
    scan_hash: str

    @field_validator("scan_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("split_manifest_hash", "memory_pack_hash", "scan_hash")
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @model_validator(mode="after")
    def result_matches_findings(self) -> ContaminationScan:
        if self.passed != (not self.findings):
            raise ValueError("contamination result disagrees with findings")
        return self


ContaminationMatchClass = Literal[
    "task_identity_overlap",
    "source_identity_overlap",
    "exact_file_content",
    "issue_text_duplication",
    "source_code_sequence",
    "hidden_test_fragment",
    "reference_patch_fragment",
    "exact_task_id",
    "repository_path",
    "distinctive_identifier",
    "heldout_issue_phrase",
    "allowed_synthesis_vocabulary",
    "generic_vocabulary",
]
ContaminationSeverity = Literal["hard_contamination", "diagnostic_overlap"]


class ContaminationScanPolicy(StrictModel):
    schema_version: str = SCHEMA_VERSION
    policy_id: Literal["provenance_aware_contamination_v1"] = "provenance_aware_contamination_v1"
    tokenizer_id: Literal["ascii_casefold_lexical_v1"] = "ascii_casefold_lexical_v1"
    natural_language_min_tokens: int = Field(default=5, ge=3)
    natural_language_min_characters: int = Field(default=20, ge=20)
    code_sequence_min_tokens: int = Field(default=5, ge=3)
    source_fragment_min_lines: int = Field(default=5, ge=3)
    distinctive_identifier_min_characters: int = Field(default=5, ge=3)
    known_match_classes: list[ContaminationMatchClass]
    hidden_reference_output: Literal["hash_only"] = "hash_only"
    unknown_match_policy: Literal["fail_closed"] = "fail_closed"
    policy_hash: str

    @field_validator("policy_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def match_classes_are_complete(self) -> ContaminationScanPolicy:
        expected = set(get_args(ContaminationMatchClass))
        if set(self.known_match_classes) != expected or len(self.known_match_classes) != len(
            expected
        ):
            raise ValueError("contamination policy must bind every known match class exactly once")
        return self


class AllowedSynthesisSource(StrictModel):
    schema_version: str = SCHEMA_VERSION
    source_id: str
    source_class: Literal[
        "memory_builder_prompt_schema",
        "sanitized_training_summary",
        "training_public_assets",
        "reward_channel_names",
        "generic_policy_instructions",
    ]
    content_hash: str
    token_count: int = Field(ge=0)

    @field_validator("source_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class AllowedSynthesisCorpus(StrictModel):
    schema_version: str = SCHEMA_VERSION
    corpus_id: str
    policy_hash: str
    sources: list[AllowedSynthesisSource] = Field(min_length=1)
    normalized_tokens: list[str]
    normalized_phrase_hashes: list[str]
    heldout_assets_included: Literal[False] = False
    hidden_assets_included: Literal[False] = False
    reference_assets_included: Literal[False] = False
    corpus_hash: str

    @field_validator("corpus_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("policy_hash", "corpus_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @field_validator("normalized_phrase_hashes")
    @classmethod
    def validate_phrase_hashes(cls, values: list[str]) -> list[str]:
        return [_hash(value) for value in values]

    @model_validator(mode="after")
    def vocabulary_is_canonical(self) -> AllowedSynthesisCorpus:
        if self.normalized_tokens != sorted(set(self.normalized_tokens)):
            raise ValueError("allowed synthesis tokens must be sorted and unique")
        if self.normalized_phrase_hashes != sorted(set(self.normalized_phrase_hashes)):
            raise ValueError("allowed synthesis phrase hashes must be sorted and unique")
        source_ids = [source.source_id for source in self.sources]
        if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)):
            raise ValueError("allowed synthesis sources must be sorted and unique")
        return self


class AssetSignatureBucket(StrictModel):
    schema_version: str = SCHEMA_VERSION
    match_class: ContaminationMatchClass
    signature_count: int = Field(ge=0)
    signature_set_hash: str
    raw_private_content_exported: Literal[False] = False

    @field_validator("signature_set_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class AssetSignatureManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    manifest_id: str
    split_manifest_hash: str
    policy_hash: str
    allowed_synthesis_corpus_hash: str
    buckets: list[AssetSignatureBucket]
    training_file_count: int = Field(ge=0)
    heldout_file_count: int = Field(ge=0)
    hidden_assets_exported: Literal[False] = False
    reference_assets_exported: Literal[False] = False
    manifest_hash: str

    @field_validator("manifest_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "split_manifest_hash",
        "policy_hash",
        "allowed_synthesis_corpus_hash",
        "manifest_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def buckets_are_canonical(self) -> AssetSignatureManifest:
        classes = [bucket.match_class for bucket in self.buckets]
        if classes != sorted(classes) or len(classes) != len(set(classes)):
            raise ValueError("asset signature buckets must be sorted and unique")
        return self


class ContaminationMatch(StrictModel):
    schema_version: str = SCHEMA_VERSION
    stage: Literal["split_asset", "frozen_memory_to_heldout"]
    match_class: ContaminationMatchClass
    severity: ContaminationSeverity
    evidence_hash: str
    training_identity: str | None = None
    heldout_identity: str
    task_hash: str | None = None
    source_artifact_hash: str | None = None
    normalized_token_count: int = Field(ge=1)
    match_location_class: str
    public_excerpt: str | None = Field(default=None, max_length=160)
    raw_private_content_exported: Literal[False] = False

    @field_validator("evidence_hash", "task_hash", "source_artifact_hash")
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @model_validator(mode="after")
    def severity_and_privacy_match_class(self) -> ContaminationMatch:
        diagnostic = {"allowed_synthesis_vocabulary", "generic_vocabulary"}
        if (self.match_class in diagnostic) != (self.severity == "diagnostic_overlap"):
            raise ValueError("contamination severity disagrees with the typed match class")
        if self.match_class in {"hidden_test_fragment", "reference_patch_fragment"}:
            if self.public_excerpt is not None:
                raise ValueError("hidden and reference matches must remain hash-only")
        return self


class SplitAssetContaminationScan(StrictModel):
    schema_version: str = SCHEMA_VERSION
    scan_id: str
    split_manifest_hash: str
    policy_hash: str
    signature_manifest_hash: str
    matches: list[ContaminationMatch]
    hard_contamination_count: int = Field(ge=0)
    diagnostic_overlap_count: Literal[0] = 0
    passed: bool
    implementation_error: bool = False
    hidden_assets_exported: Literal[False] = False
    reference_assets_exported: Literal[False] = False
    scan_hash: str

    @field_validator("scan_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("split_manifest_hash", "policy_hash", "signature_manifest_hash", "scan_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def result_matches_findings(self) -> SplitAssetContaminationScan:
        hard_count = sum(match.severity == "hard_contamination" for match in self.matches)
        if hard_count != self.hard_contamination_count:
            raise ValueError("split contamination count disagrees with matches")
        if self.passed != (hard_count == 0 and not self.implementation_error):
            raise ValueError("split contamination result disagrees with matches")
        if any(match.stage != "split_asset" for match in self.matches):
            raise ValueError("split scan contains a match from another stage")
        return self


class FrozenMemoryContaminationScan(StrictModel):
    schema_version: str = SCHEMA_VERSION
    scan_id: str
    split_manifest_hash: str
    policy_hash: str
    allowed_synthesis_corpus_hash: str
    signature_manifest_hash: str
    memory_pack_hash: str
    matches: list[ContaminationMatch]
    hard_contamination_count: int = Field(ge=0)
    diagnostic_overlap_count: int = Field(ge=0)
    passed: bool
    implementation_error: bool = False
    hidden_assets_exported: Literal[False] = False
    reference_assets_exported: Literal[False] = False
    scan_hash: str

    @field_validator("scan_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "split_manifest_hash",
        "policy_hash",
        "allowed_synthesis_corpus_hash",
        "signature_manifest_hash",
        "memory_pack_hash",
        "scan_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def result_matches_findings(self) -> FrozenMemoryContaminationScan:
        hard_count = sum(match.severity == "hard_contamination" for match in self.matches)
        diagnostic_count = sum(match.severity == "diagnostic_overlap" for match in self.matches)
        if (
            hard_count != self.hard_contamination_count
            or diagnostic_count != self.diagnostic_overlap_count
        ):
            raise ValueError("memory contamination counts disagree with matches")
        if self.passed != (hard_count == 0 and not self.implementation_error):
            raise ValueError("memory contamination result disagrees with matches")
        if any(match.stage != "frozen_memory_to_heldout" for match in self.matches):
            raise ValueError("memory scan contains a match from another stage")
        return self


class ContaminationScanReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    report_id: str
    split_asset_scan: SplitAssetContaminationScan
    frozen_memory_scan: FrozenMemoryContaminationScan | None = None
    passed: bool
    hard_contamination_count: int = Field(ge=0)
    diagnostic_overlap_count: int = Field(ge=0)
    report_hash: str

    @field_validator("report_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("report_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def aggregate_matches_stages(self) -> ContaminationScanReport:
        hard_count = self.split_asset_scan.hard_contamination_count
        diagnostic_count = 0
        stage_passed = self.split_asset_scan.passed
        if self.frozen_memory_scan is not None:
            hard_count += self.frozen_memory_scan.hard_contamination_count
            diagnostic_count = self.frozen_memory_scan.diagnostic_overlap_count
            stage_passed = stage_passed and self.frozen_memory_scan.passed
        if (
            hard_count != self.hard_contamination_count
            or diagnostic_count != self.diagnostic_overlap_count
            or self.passed != stage_passed
        ):
            raise ValueError("contamination report disagrees with stage results")
        return self


class MemoryPackSection(StrictModel):
    schema_version: str = SCHEMA_VERSION
    section: Literal[
        "principles",
        "public_test_strategy",
        "workspace_policy_reminders",
        "debugging_checklist",
        "patch_discipline",
    ]
    items: list[str] = Field(min_length=1, max_length=12)


class MemoryPack(StrictModel):
    schema_version: str = SCHEMA_VERSION
    memory_pack_id: str
    policy_id: Literal["task_independent_code_free_memory_v1"] = (
        "task_independent_code_free_memory_v1"
    )
    sections: list[MemoryPackSection] = Field(min_length=5, max_length=5)
    total_utf8_bytes: int = Field(ge=1, le=16_384)
    content_hash: str
    task_independent: Literal[True] = True
    code_free: Literal[True] = True

    @field_validator("memory_pack_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def sections_are_complete(self) -> MemoryPack:
        names = [section.section for section in self.sections]
        expected = {
            "principles",
            "public_test_strategy",
            "workspace_policy_reminders",
            "debugging_checklist",
            "patch_discipline",
        }
        if set(names) != expected or len(names) != len(set(names)):
            raise ValueError("memory packs require each bounded section exactly once")
        return self


class AgentVersionManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    agent_version_id: str
    status: Literal["frozen"]
    parent_version_hash: str | None = None
    update_type: Literal["none", "context_memory", "external_checkpoint", "external_adapter"]
    executable_in_m10b: bool
    base_agent_id: str
    agent_descriptor_hash: str
    model_id: str
    reasoning_effort: str
    auth_semantic_id: str
    runtime_identity_hash: str
    tool_policy_hash: str
    prompt_contract_hash: str
    source_commit: str
    package_hashes: dict[str, str]
    image_hashes: dict[str, str]
    training_dataset_hash: str | None = None
    reward_schema_hash: str | None = None
    reward_profile_hash: str | None = None
    memory_builder_identity_hash: str | None = None
    memory_synthesis_plan_hash: str | None = None
    invocation_spec_hash: str | None = None
    payload_binding_hash: str | None = None
    memory_pack_hash: str | None = None
    version_hash: str
    model_weights_modified: Literal[False] = False

    @field_validator(
        "agent_version_id",
        "base_agent_id",
        "model_id",
        "reasoning_effort",
        "auth_semantic_id",
    )
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "parent_version_hash",
        "agent_descriptor_hash",
        "runtime_identity_hash",
        "tool_policy_hash",
        "prompt_contract_hash",
        "training_dataset_hash",
        "reward_schema_hash",
        "reward_profile_hash",
        "memory_builder_identity_hash",
        "memory_synthesis_plan_hash",
        "invocation_spec_hash",
        "payload_binding_hash",
        "memory_pack_hash",
        "version_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @field_validator("package_hashes", "image_hashes")
    @classmethod
    def validate_hash_maps(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: _hash(value) for key, value in sorted(values.items())}

    @model_validator(mode="after")
    def validate_update_contract(self) -> AgentVersionManifest:
        lifecycle = (
            self.memory_synthesis_plan_hash,
            self.invocation_spec_hash,
            self.payload_binding_hash,
        )
        if any(value is not None for value in lifecycle) and not all(
            value is not None for value in lifecycle
        ):
            raise ValueError("agent version lifecycle identities are all-or-none")
        if self.update_type == "none":
            if self.parent_version_hash is not None or self.memory_pack_hash is not None:
                raise ValueError("base agent version cannot bind a parent or memory pack")
        elif self.update_type == "context_memory":
            required = (
                self.parent_version_hash,
                self.training_dataset_hash,
                self.reward_schema_hash,
                self.memory_builder_identity_hash,
                self.memory_pack_hash,
            )
            if any(value is None for value in required) or not self.executable_in_m10b:
                raise ValueError("context-memory versions require complete executable lineage")
        elif self.executable_in_m10b:
            raise ValueError("M10B executes only none and context_memory agent versions")
        return self


class AgentUpdateManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    update_id: str
    update_type: Literal["context_memory"]
    parent_version_hash: str
    result_version_hash: str
    training_summary_hash: str
    memory_builder_input_hash: str
    memory_builder_output_hash: str
    memory_synthesis_plan_hash: str | None = None
    invocation_spec_hash: str | None = None
    payload_binding_hash: str | None = None
    memory_pack_hash: str
    process_ledger_hash: str
    heldout_assets_loaded: Literal[False] = False
    model_weights_modified: Literal[False] = False
    update_hash: str

    @field_validator("update_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "parent_version_hash",
        "result_version_hash",
        "training_summary_hash",
        "memory_builder_input_hash",
        "memory_builder_output_hash",
        "memory_synthesis_plan_hash",
        "invocation_spec_hash",
        "payload_binding_hash",
        "memory_pack_hash",
        "process_ledger_hash",
        "update_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @model_validator(mode="after")
    def lifecycle_is_all_or_none(self) -> AgentUpdateManifest:
        lifecycle = (
            self.memory_synthesis_plan_hash,
            self.invocation_spec_hash,
            self.payload_binding_hash,
        )
        if any(value is not None for value in lifecycle) and not all(
            value is not None for value in lifecycle
        ):
            raise ValueError("agent update lifecycle identities are all-or-none")
        return self


class AgentLineage(StrictModel):
    schema_version: str = SCHEMA_VERSION
    lineage_id: str
    versions: list[AgentVersionManifest] = Field(min_length=1)
    updates: list[AgentUpdateManifest] = Field(default_factory=list)
    lineage_hash: str

    @field_validator("lineage_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("lineage_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class AgentVersionSetManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    versions: list[AgentVersionManifest] = Field(min_length=1)
    version_set_hash: str

    @field_validator("version_set_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def unique_versions(self) -> AgentVersionSetManifest:
        ids = [version.agent_version_id for version in self.versions]
        hashes = [version.version_hash for version in self.versions]
        if len(ids) != len(set(ids)) or len(hashes) != len(set(hashes)):
            raise ValueError("agent version sets cannot repeat identities")
        return self


class RunAgentVersionAssignment(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    agent_version_id: str
    agent_version_hash: str

    @field_validator("run_id", "agent_version_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("agent_version_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class RunAgentVersionAssignments(StrictModel):
    schema_version: str = SCHEMA_VERSION
    assignments: list[RunAgentVersionAssignment] = Field(min_length=1)
    manifest_hash: str

    @field_validator("manifest_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def assignments_are_unique(self) -> RunAgentVersionAssignments:
        run_ids = [item.run_id for item in self.assignments]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("run/version assignments cannot repeat run IDs")
        return self


class EpisodeTrajectory(StrictModel):
    schema_version: str = SCHEMA_VERSION
    trajectory_id: str
    run_id: str
    experiment_id: str | None = None
    plan_item_id: str | None = None
    task_id: str
    task_hash: str
    source_hash: str
    base_repository_hash: str | None = None
    split_id: str
    split: Literal["training", "validation", "heldout"]
    agent_version_id: str
    agent_version_hash: str
    model_identity_hash: str
    codex_identity_hash: str
    auth_semantic_id: str
    prompt_hash: str
    memory_pack_hash: str | None = None
    runtime_identity_hash: str
    image_identity_hash: str | None = None
    verifier_identity_hash: str
    toolchain_identity_hash: str
    base_seed: int = Field(ge=0)
    sample_index: int = Field(ge=0)
    events: list[TrajectoryEvent]
    event_count: int = Field(ge=0)
    events_hash: str
    run_manifest_hash: str
    scorecard_hash: str
    artifact_manifest_hash: str
    export_policy_id: Literal["observable_repo_trajectory_v1"] = "observable_repo_trajectory_v1"
    eligibility: TrajectoryEligibility
    reward: RewardVector
    reward_hash: str
    private_reasoning_exported: Literal[False] = False
    hidden_assets_exported: Literal[False] = False
    reference_solution_exported: Literal[False] = False
    credential_values_exported: Literal[False] = False
    raw_host_paths_exported: Literal[False] = False
    total_bytes: int = Field(ge=0)
    trajectory_hash: str

    @field_validator(
        "trajectory_id",
        "run_id",
        "split_id",
        "agent_version_id",
        "auth_semantic_id",
    )
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        return _safe_task_id(value)

    @field_validator(
        "task_hash",
        "source_hash",
        "base_repository_hash",
        "agent_version_hash",
        "model_identity_hash",
        "codex_identity_hash",
        "prompt_hash",
        "memory_pack_hash",
        "runtime_identity_hash",
        "image_identity_hash",
        "verifier_identity_hash",
        "toolchain_identity_hash",
        "events_hash",
        "run_manifest_hash",
        "scorecard_hash",
        "artifact_manifest_hash",
        "reward_hash",
        "trajectory_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @model_validator(mode="after")
    def event_contract(self) -> EpisodeTrajectory:
        if self.event_count != len(self.events):
            raise ValueError("trajectory event count disagrees with events")
        if [event.sequence for event in self.events] != list(range(len(self.events))):
            raise ValueError("trajectory events must be contiguous and ordered")
        return self


class TrajectoryIndexRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    trajectory_id: str
    run_id: str
    task_id: str
    split: Literal["training", "validation", "heldout"]
    agent_version_id: str
    eligible: bool
    outcome_kind: EpisodeOutcomeKind
    trajectory_hash: str

    @field_validator("trajectory_id", "run_id", "agent_version_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        return _safe_task_id(value)

    @field_validator("trajectory_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class TrajectoryDatasetStatistics(StrictModel):
    schema_version: str = SCHEMA_VERSION
    record_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    outcome_counts: dict[EpisodeOutcomeKind, int]
    split_counts: dict[Literal["training", "validation", "heldout"], int]
    agent_version_counts: dict[str, int]
    statistics_hash: str

    @field_validator("statistics_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value)


class TrajectoryDatasetManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    dataset_id: str
    source_experiment_ids: list[str]
    input_set_hash: str
    split_manifest_hash: str
    agent_version_manifest_hash: str
    export_policy_id: Literal["observable_repo_trajectory_v1"] = "observable_repo_trajectory_v1"
    export_policy_hash: str
    reward_profile_hash: str | None = None
    included_run_ids: list[str]
    excluded_runs: dict[str, str]
    record_count: int = Field(ge=0)
    eligible_record_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)
    licenses: list[str]
    attributions: list[str]
    source_commit: str
    package_identities: dict[str, str]
    no_network: Literal[True] = True
    no_model_calls: Literal[True] = True
    no_runtime_calls: Literal[True] = True
    no_verifier_calls: Literal[True] = True
    no_public_launcher_calls: Literal[True] = True
    dataset_hash: str

    @field_validator("dataset_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "input_set_hash",
        "split_manifest_hash",
        "agent_version_manifest_hash",
        "export_policy_hash",
        "reward_profile_hash",
        "dataset_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @field_validator("package_identities")
    @classmethod
    def validate_packages(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: _hash(value) for key, value in sorted(values.items())}


class TrajectoryDatasetReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    report_id: str
    dataset_hash: str
    record_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    ineligible_count: int = Field(ge=0)
    outcome_counts: dict[EpisodeOutcomeKind, int]
    split_counts: dict[str, int]
    agent_version_counts: dict[str, int]
    no_model_calls: Literal[True] = True
    no_runtime_calls: Literal[True] = True
    report_hash: str

    @field_validator("report_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("dataset_hash", "report_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


class RewardChannelStatistics(StrictModel):
    schema_version: str = SCHEMA_VERSION
    channel: str
    unit: Literal["binary", "count", "lines", "seconds", "tokens"]
    available: int = Field(ge=0)
    missing: int = Field(ge=0)
    minimum: float | None = None
    mean: float | None = None
    maximum: float | None = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        return _safe_id(value)


class RewardAnalysisReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    report_id: str
    dataset_hash: str
    reward_schema_id: Literal["repo_rtl_reward_vector_v1"] = "repo_rtl_reward_vector_v1"
    reward_profile_id: str | None = None
    reward_profile_hash: str | None = None
    vector_authoritative: Literal[True] = True
    universal_benchmark_score: Literal[False] = False
    record_count: int = Field(ge=0)
    outcome_counts: dict[EpisodeOutcomeKind, int]
    channels: list[RewardChannelStatistics]
    report_hash: str

    @field_validator("report_id", "reward_profile_id")
    @classmethod
    def validate_ids(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @field_validator("dataset_hash", "reward_profile_hash", "report_hash")
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None


class MemoryPackAudit(StrictModel):
    schema_version: str = SCHEMA_VERSION
    memory_pack_id: str
    memory_pack_hash: str
    policy_id: Literal["task_independent_code_free_memory_v1"]
    section_count: Literal[5] = 5
    item_count: int = Field(ge=5, le=60)
    total_utf8_bytes: int = Field(ge=1, le=16_384)
    content_policy_passed: Literal[True] = True
    task_independent: Literal[True] = True
    code_free: Literal[True] = True
    hidden_assets_included: Literal[False] = False
    references_included: Literal[False] = False
    credentials_included: Literal[False] = False
    heldout_content_included: Literal[False] = False
    audit_hash: str

    @field_validator("memory_pack_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("memory_pack_hash", "audit_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


class SanitizedTrainingEpisode(StrictModel):
    schema_version: str = SCHEMA_VERSION
    public_task_category: str
    observable_action_summary: list[str] = Field(max_length=64)
    public_test_outcomes: list[bool] = Field(max_length=64)
    patch_metrics: dict[str, int]
    outcome_kind: EpisodeOutcomeKind
    reward: RewardVector
    compile_passed: bool | None = None
    hidden_regression_passed: bool | None = None
    generalized_failure_labels: list[str] = Field(max_length=32)


class SanitizedTrainingSummary(StrictModel):
    schema_version: str = SCHEMA_VERSION
    summary_id: str
    split_manifest_hash: str
    trajectory_dataset_hash: str
    episodes: list[SanitizedTrainingEpisode] = Field(min_length=1, max_length=128)
    hidden_assets_included: Literal[False] = False
    references_included: Literal[False] = False
    private_reasoning_included: Literal[False] = False
    heldout_assets_included: Literal[False] = False
    summary_hash: str

    @field_validator("summary_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("split_manifest_hash", "trajectory_dataset_hash", "summary_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


class MemoryBuilderInput(StrictModel):
    schema_version: str = SCHEMA_VERSION
    build_id: str
    training_summary: SanitizedTrainingSummary
    prompt_contract_hash: str
    output_schema_hash: str
    model_identity_hash: str
    codex_identity_hash: str
    auth_semantic_id: str
    runtime_identity_hash: str
    image_identity_hash: str
    requested_model_id: str
    reasoning_effort: str
    timeout_s: int = Field(ge=1, le=300)
    max_output_bytes: int = Field(ge=1, le=262_144)
    heldout_assets_available: Literal[False] = False
    private_reasoning_requested: Literal[False] = False
    input_hash: str

    @field_validator(
        "build_id",
        "auth_semantic_id",
        "requested_model_id",
        "reasoning_effort",
    )
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "prompt_contract_hash",
        "output_schema_hash",
        "model_identity_hash",
        "codex_identity_hash",
        "runtime_identity_hash",
        "image_identity_hash",
        "input_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


class MemorySynthesisPlan(StrictModel):
    """Frozen two-phase identity for one payload-bound memory-builder process."""

    schema_version: str = SCHEMA_VERSION
    plan_id: str
    build_id: str
    invocation_spec: ExternalProcessInvocationSpec
    identity_preview: ExternalProcessIdentityPreview
    payload_binding: ExternalProcessPayloadBinding
    training_dataset_hash: str
    training_run_ids: list[str] = Field(min_length=1, max_length=128)
    training_source_identities: dict[str, str]
    reward_profile_hash: str
    reward_vector_schema_hash: str
    sanitized_summary_hash: str
    builder_input_hash: str
    prompt_contract_id: str
    prompt_contract_hash: str
    prompt_template_hash: str
    rendered_prompt_hash: str
    rendered_prompt_utf8_bytes: int = Field(ge=1, le=2 * 1024 * 1024)
    output_schema_hash: str
    model_identity_hash: str
    codex_identity_hash: str
    auth_semantic_id: str
    runtime_identity_hash: str
    image_identity_hash: str
    requested_model_id: str
    reasoning_effort: str
    timeout_s: int = Field(ge=1, le=300)
    max_output_bytes: int = Field(ge=1024, le=262_144)
    payload_state: Literal["bound"] = "bound"
    sealed_before_authorization: Literal[True] = True
    plan_hash: str

    @field_validator(
        "plan_id",
        "build_id",
        "prompt_contract_id",
        "auth_semantic_id",
        "requested_model_id",
        "reasoning_effort",
    )
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("training_run_ids")
    @classmethod
    def validate_run_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("memory synthesis training run IDs must be unique")
        return [_safe_id(value) for value in values]

    @field_validator(
        "training_dataset_hash",
        "reward_profile_hash",
        "reward_vector_schema_hash",
        "sanitized_summary_hash",
        "builder_input_hash",
        "prompt_contract_hash",
        "prompt_template_hash",
        "rendered_prompt_hash",
        "output_schema_hash",
        "model_identity_hash",
        "codex_identity_hash",
        "runtime_identity_hash",
        "image_identity_hash",
        "plan_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @field_validator("training_source_identities")
    @classmethod
    def validate_source_identities(cls, values: dict[str, str]) -> dict[str, str]:
        if not values:
            raise ValueError("memory synthesis requires training source identities")
        return {key: _hash(value) for key, value in sorted(values.items())}

    @model_validator(mode="after")
    def validate_linkage(self) -> MemorySynthesisPlan:
        if (
            self.identity_preview.invocation_spec_hash != self.invocation_spec.invocation_spec_hash
            or self.payload_binding.invocation_spec_hash
            != self.invocation_spec.invocation_spec_hash
            or self.payload_binding.prompt_contract_id != self.prompt_contract_id
            or self.payload_binding.template_hash != self.prompt_template_hash
            or self.payload_binding.input_dataset_hash != self.training_dataset_hash
            or self.payload_binding.rendered_prompt_hash != self.rendered_prompt_hash
            or self.payload_binding.stdin_utf8_bytes != self.rendered_prompt_utf8_bytes
            or self.invocation_spec.prompt_contract_id != self.prompt_contract_id
            or self.invocation_spec.expected_output_schema_hash != self.output_schema_hash
        ):
            raise ValueError("memory synthesis plan lifecycle identities disagree")
        return self


class MemoryBuilderResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    build_id: str
    status: Literal["success", "parser_error", "content_policy_rejected", "process_failure"]
    input_hash: str
    process_identity_hash: str
    process_ledger_record_hash: str
    redacted_output_hash: str
    memory_pack: MemoryPack | None = None
    failure_reason: MemoryBuilderFailureReason | None = None
    wall_time_s: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    model_processes_started: Literal[1] = 1
    heldout_assets_available: Literal[False] = False
    private_reasoning_exported: Literal[False] = False
    credentials_exported: Literal[False] = False
    output_hash: str
    memory_synthesis_plan_hash: str | None = None
    invocation_spec_hash: str | None = None
    payload_binding_hash: str | None = None

    @field_validator("build_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "input_hash",
        "process_identity_hash",
        "process_ledger_record_hash",
        "redacted_output_hash",
        "output_hash",
        "memory_synthesis_plan_hash",
        "invocation_spec_hash",
        "payload_binding_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def result_matches_status(self) -> MemoryBuilderResult:
        if (self.memory_pack is not None) != (self.status == "success"):
            raise ValueError("only successful memory synthesis may contain a memory pack")
        if self.status == "success" and self.failure_reason is not None:
            raise ValueError("successful memory synthesis cannot have a failure reason")
        process_reasons = {
            "process_timeout",
            "process_output_limit",
            "process_nonzero_exit",
            "runtime_security_incomplete",
        }
        parser_reasons = {
            "event_stream_parse_error",
            "terminal_stream_incomplete",
            "memory_output_invalid",
        }
        if self.failure_reason is not None:
            expected_status = (
                "process_failure"
                if self.failure_reason in process_reasons
                else "parser_error"
                if self.failure_reason in parser_reasons
                else "content_policy_rejected"
            )
            if self.status != expected_status:
                raise ValueError("memory-builder failure reason disagrees with status")
        lifecycle = (
            self.memory_synthesis_plan_hash,
            self.invocation_spec_hash,
            self.payload_binding_hash,
        )
        if any(value is not None for value in lifecycle) and not all(
            value is not None for value in lifecycle
        ):
            raise ValueError("memory-builder result lifecycle identities are all-or-none")
        return self


class HistoricalTrainingEpisodeImportEligibility(StrictModel):
    """Per-run all-or-none import decision without rewriting historical evidence."""

    schema_version: str = SCHEMA_VERSION
    run_id: str
    task_id: str
    outcome_kind: str
    eligible: bool
    checks: dict[str, bool]
    ineligible_reasons: list[str] = Field(default_factory=list)
    original_run_manifest_hash: str
    original_artifact_manifest_hash: str
    original_source_commit: str
    exporter_source_commit: str
    trajectory_hash: str
    reward_hash: str
    record_hash: str

    @field_validator("run_id", "outcome_kind")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        return _safe_task_id(value)

    @field_validator(
        "original_run_manifest_hash",
        "original_artifact_manifest_hash",
        "trajectory_hash",
        "reward_hash",
        "record_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @field_validator("original_source_commit", "exporter_source_commit")
    @classmethod
    def validate_commits(cls, value: str) -> str:
        if not _GIT_SHA.fullmatch(value):
            raise ValueError("training import source commits must be full Git SHA-1 identities")
        return value

    @model_validator(mode="after")
    def decision_matches_checks(self) -> HistoricalTrainingEpisodeImportEligibility:
        passed = all(self.checks.values()) and not self.ineligible_reasons
        if self.eligible != passed:
            raise ValueError("historical training import decision disagrees with checks")
        return self


class HistoricalTrainingImportManifest(StrictModel):
    """Campaign-wide all-or-none decision for one immutable training triplet."""

    schema_version: str = SCHEMA_VERSION
    import_id: str
    source_bundle_sha256sums_hash: str
    exporter_source_commit: str
    episodes: list[HistoricalTrainingEpisodeImportEligibility] = Field(min_length=3, max_length=3)
    all_or_none_policy: Literal[True] = True
    import_all: bool
    rerun_all: bool
    mixed_sources: Literal[False] = False
    manifest_hash: str

    @field_validator("import_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "source_bundle_sha256sums_hash",
        "manifest_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @field_validator("exporter_source_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if not _GIT_SHA.fullmatch(value):
            raise ValueError("training import source commit must be a full Git SHA-1 identity")
        return value

    @model_validator(mode="after")
    def validate_all_or_none(self) -> HistoricalTrainingImportManifest:
        eligible = all(episode.eligible for episode in self.episodes)
        if self.import_all != eligible or self.rerun_all == self.import_all:
            raise ValueError("historical training triplet must be imported all or rerun all")
        return self


class EvolutionProcessLedgerRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    ordinal: int = Field(ge=1, le=24)
    record_phase: Literal["authorized", "terminal"]
    process_kind: Literal[
        "implementation_probe",
        "training_episode",
        "memory_synthesis",
        "heldout",
    ]
    authorization_id: str
    run_or_build_id: str
    task_identity_hash: str | None = None
    agent_version_hash: str | None = None
    invocation_spec_hash: str | None = None
    payload_binding_hash: str | None = None
    memory_synthesis_plan_hash: str | None = None
    requested_model_id: str
    reasoning_effort: str
    model_process_started: bool
    retry: Literal[False] = False
    resume: Literal[False] = False
    terminal: bool
    terminal_outcome: str | None = None
    source_ledger_record_hash: str | None = None
    record_hash: str

    @field_validator(
        "authorization_id",
        "run_or_build_id",
        "requested_model_id",
        "reasoning_effort",
        "terminal_outcome",
    )
    @classmethod
    def validate_ids(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @field_validator(
        "task_identity_hash",
        "agent_version_hash",
        "invocation_spec_hash",
        "payload_binding_hash",
        "memory_synthesis_plan_hash",
        "source_ledger_record_hash",
        "record_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None

    @model_validator(mode="after")
    def validate_append_phase(self) -> EvolutionProcessLedgerRecord:
        if self.record_phase == "authorized":
            if self.model_process_started or self.terminal:
                raise ValueError("authorization records precede process launch")
            if self.terminal_outcome is not None or self.source_ledger_record_hash is not None:
                raise ValueError("authorization records cannot contain terminal provenance")
        else:
            if not self.model_process_started or not self.terminal:
                raise ValueError("terminal records require a started terminal process")
            if self.terminal_outcome is None or self.source_ledger_record_hash is None:
                raise ValueError("terminal records require outcome and authorization provenance")
        return self


class EvolutionProcessLedgerManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    authorization_id: str
    records: list[EvolutionProcessLedgerRecord] = Field(max_length=48)
    authorized_processes: int = Field(ge=0, le=24)
    started_processes: int = Field(ge=0, le=24)
    terminal_processes: int = Field(ge=0, le=24)
    process_kind_counts: dict[str, int]
    maximum_processes: int = Field(default=24, ge=1, le=24)
    complete: bool
    manifest_hash: str

    @field_validator("authorization_id")
    @classmethod
    def validate_authorization_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("manifest_hash")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        return _hash(value)


class ExternalTrainerExportManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    bridge_id: Literal["observable_trajectory_external_trainer_v1"]
    trajectory_dataset_hash: str
    split_manifest_hash: str
    reward_schema_hash: str
    reward_profile_hash: str | None = None
    executable_artifacts_included: Literal[False] = False
    secrets_included: Literal[False] = False
    manifest_hash: str

    @field_validator(
        "trajectory_dataset_hash",
        "split_manifest_hash",
        "reward_schema_hash",
        "reward_profile_hash",
        "manifest_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        return _hash(value) if value is not None else None


class ExternalAgentVersionImportManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    import_id: str
    update_type: Literal["context_memory", "external_checkpoint", "external_adapter"]
    parent_version_hash: str
    trainer_identity_hash: str
    training_dataset_hash: str
    artifact_hash: str
    compatible_runtime_hash: str
    license: str
    provenance: str
    loading_configuration: dict[str, JsonValue]
    executable_in_m10b: bool
    manifest_hash: str

    @field_validator("import_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator(
        "parent_version_hash",
        "trainer_identity_hash",
        "training_dataset_hash",
        "artifact_hash",
        "compatible_runtime_hash",
        "manifest_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)

    @model_validator(mode="after")
    def only_context_is_executable(self) -> ExternalAgentVersionImportManifest:
        if self.executable_in_m10b != (self.update_type == "context_memory"):
            raise ValueError("only context_memory imports are executable in M10B")
        return self


class VersionMetricSummary(StrictModel):
    schema_version: str = SCHEMA_VERSION
    agent_version_id: str
    planned: int = Field(ge=0)
    launched: int = Field(ge=0)
    terminal: int = Field(ge=0)
    evaluable: int = Field(ge=0)
    resolved: int = Field(ge=0)
    candidate_failures: int = Field(ge=0)
    contained_policy_failures: int = Field(ge=0)
    infrastructure_failures: int = Field(ge=0)
    public_test_reached: int = Field(ge=0)
    hidden_verifier_reached: int = Field(ge=0)
    patch_reproducible: int = Field(ge=0)
    macro_pass_at_1: float | None = Field(default=None, ge=0, le=1)
    macro_pass_at_2: float | None = Field(default=None, ge=0, le=1)
    macro_pass_at_3: float | None = Field(default=None, ge=0, le=1)
    policy_failure_rate: float | None = Field(default=None, ge=0, le=1)
    mean_public_tool_calls: float | None = None
    mean_changed_files: float | None = None
    mean_patch_lines: float | None = None
    mean_input_tokens: float | None = None
    mean_output_tokens: float | None = None
    mean_tokens: float | None = None
    mean_wall_time_s: float | None = None
    missing_usage_count: int = Field(ge=0)
    mean_tokens_per_resolved: float | None = None
    mean_wall_time_per_resolved_s: float | None = None

    @field_validator("agent_version_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)


class TaskVersionMetric(StrictModel):
    schema_version: str = SCHEMA_VERSION
    task_id: str
    agent_version_id: str
    planned: int = Field(ge=0)
    terminal: int = Field(ge=0)
    evaluable: int = Field(ge=0)
    resolved: int = Field(ge=0)
    contained_policy_failures: int = Field(ge=0)
    infrastructure_failures: int = Field(ge=0)
    pass_at_1: float | None = Field(default=None, ge=0, le=1)
    pass_at_2: float | None = Field(default=None, ge=0, le=1)
    pass_at_3: float | None = Field(default=None, ge=0, le=1)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        return _safe_task_id(value)

    @field_validator("agent_version_id")
    @classmethod
    def validate_version_id(cls, value: str) -> str:
        return _safe_id(value)


class PairedVersionDifference(StrictModel):
    schema_version: str = SCHEMA_VERSION
    baseline_version_id: str
    evolved_version_id: str
    macro_pass_at_1_delta: float | None = None
    macro_pass_at_2_delta: float | None = None
    macro_pass_at_3_delta: float | None = None
    policy_failure_rate_delta: float | None = None
    mean_tokens_delta: float | None = None
    mean_wall_time_s_delta: float | None = None


class EvolvingEvaluationReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    report_id: str
    split_manifest_hash: str
    heldout_plan_hash: str
    version_metrics: list[VersionMetricSummary]
    task_version_metrics: list[TaskVersionMetric]
    paired_difference: PairedVersionDifference
    heldout_task_count: int = Field(ge=0)
    samples_per_task_version: int = Field(ge=1)
    no_weight_update: Literal[True] = True
    establishes_general_improvement: Literal[False] = False
    required_interpretation: Literal[
        "The before/after result is a bounded first-party Evolve-Context pilot and "
        "does not establish general performance improvement."
    ] = (
        "The before/after result is a bounded first-party Evolve-Context pilot and "
        "does not establish general performance improvement."
    )
    report_hash: str

    @field_validator("report_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("split_manifest_hash", "heldout_plan_hash", "report_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value)


__all__ = [
    "AgentLineage",
    "AgentUpdateManifest",
    "AgentVersionManifest",
    "AgentVersionSetManifest",
    "BoundedObservableText",
    "CandidateFreezeObservation",
    "AllowedSynthesisCorpus",
    "AllowedSynthesisSource",
    "AssetSignatureBucket",
    "AssetSignatureManifest",
    "ContaminationFinding",
    "ContaminationMatch",
    "ContaminationScan",
    "ContaminationScanPolicy",
    "ContaminationScanReport",
    "EvolvingEvaluationReport",
    "EvolutionProcessLedgerManifest",
    "EvolutionProcessLedgerRecord",
    "EpisodeOutcomeObservation",
    "EpisodeTrajectory",
    "ExternalAgentVersionImportManifest",
    "ExternalTrainerExportManifest",
    "FrozenMemoryContaminationScan",
    "HistoricalTrainingEpisodeImportEligibility",
    "HistoricalTrainingImportManifest",
    "MemoryBuilderInput",
    "MemoryBuilderFailureReason",
    "MemoryBuilderResult",
    "MemorySynthesisPlan",
    "MemoryPack",
    "MemoryPackAudit",
    "MemoryPackSection",
    "ObservableAgentMessage",
    "ObservableToolInvocation",
    "ObservableToolResult",
    "PublicTestObservation",
    "RewardChannel",
    "RewardChannelStatistics",
    "RewardAnalysisReport",
    "RewardDerivationRecord",
    "RewardProfile",
    "RewardVector",
    "RunAgentVersionAssignment",
    "RunAgentVersionAssignments",
    "SanitizedTrainingEpisode",
    "SanitizedTrainingSummary",
    "SplitAssetContaminationScan",
    "TaskSplitEntry",
    "TaskSplitManifest",
    "TaskVersionMetric",
    "TrajectoryDatasetManifest",
    "TrajectoryDatasetReport",
    "TrajectoryDatasetStatistics",
    "TrajectoryEligibility",
    "TrajectoryEvent",
    "TrajectoryIndexRecord",
    "VersionMetricSummary",
    "WorkspaceDeltaRecord",
]
