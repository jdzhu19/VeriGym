"""HWE event accounting, causal compaction, and independently versioned SFT formats."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from verigym.core.hashing import content_hash
from verigym.hwe.observation import TokenCounter, clean_terminal_noise, collapse_repeated_lines
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_ID,
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_TOKENIZER_ID,
    canonical_hwe_action_json,
    hwe_tool_contract_hash,
    resolve_hwe_collection_profile,
)

HWE_TEACHER_TRANSCRIPT_FORMAT = "verigym_hwe_teacher_multiturn_transcript_v2"
HWE_SFT_EXAMPLE_FORMAT = "verigym_hwe_verified_multiturn_sft_v2"
HWE_SFT_DATASET_FORMAT = "verigym_hwe_verified_multiturn_sft_dataset_v2"
HWE_COMPACTION_MANIFEST_FORMAT = "verigym_hwe_compaction_manifest_v1"
HWE_TEACHER_TRANSCRIPT_V3_FORMAT = "verigym_hwe_teacher_multiturn_transcript_v3"
HWE_SFT_EXAMPLE_V3_FORMAT = "verigym_hwe_verified_multiturn_sft_v3"
HWE_SFT_DATASET_V3_FORMAT = "verigym_hwe_verified_multiturn_sft_dataset_v3"
HWE_COMPACTION_MANIFEST_V2_FORMAT = "verigym_hwe_compaction_manifest_v2"

_PATCH_HEADER = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?([^\t\n]+)", re.MULTILINE)
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)
_COMPILE = re.compile(r"\b(?:make|verilator|iverilog|sbt|mill|compile|elaborat)\b", re.I)
_SIMULATION = re.compile(r"\b(?:simulat|regress|spike|vcs|questa|xrun)\b", re.I)


class HweLimitExceeded(RuntimeError):
    """A production episode crossed a hard decision or mutation boundary."""


@dataclass
class HweEpisodeBudget:
    """Track soft long-horizon marks and enforce hard limits during collection."""

    decision_steps: int = 0
    mutation_actions: int = 0
    long_horizon: bool = False
    termination_reason: str | None = None
    profile_id: str = HWE_COLLECTION_PROFILE_ID

    def observe(self, action: str, *, changed_paths: Sequence[str] = ()) -> None:
        if action != "finish":
            self.decision_steps += 1
        mutation = action == "apply_patch" or (action == "shell" and bool(changed_paths))
        if mutation:
            self.mutation_actions += 1
        profile = resolve_hwe_collection_profile(self.profile_id)
        self.long_horizon = self.long_horizon or (
            self.decision_steps > profile.decision_steps_soft
            or self.mutation_actions > profile.mutation_actions_soft
        )
        if self.decision_steps > profile.decision_steps_hard:
            self.termination_reason = "decision_steps_hard_limit"
            raise HweLimitExceeded(self.termination_reason)
        if self.mutation_actions > profile.mutation_actions_hard:
            self.termination_reason = "mutation_actions_hard_limit"
            raise HweLimitExceeded(self.termination_reason)


@dataclass(frozen=True)
class HweNormalizedEvent:
    sequence: int
    action: Literal["list_files", "read_file", "apply_patch", "shell", "inspect_diff", "finish"]
    arguments: dict[str, Any]
    workspace_epoch_before: int
    workspace_epoch_after: int
    changed_paths: tuple[str, ...] = ()
    raw_observation_sha256: str | None = None
    raw_observation_bytes: int = 0
    compact_observation_sha256: str | None = None
    compact_observation_tokens: int = 0
    observation_rule_id: str | None = None
    observation_omitted: bool = False
    exit_code: int | None = None
    duration_ms: int | None = None
    raw_stdout_bytes: int = 0
    raw_stderr_bytes: int = 0
    raw_stdout_sha256: str | None = None
    raw_stderr_sha256: str | None = None
    compile_observed: bool = False
    simulation_observed: bool = False
    event_mapping: str = ""


@dataclass
class HweMetricsAccumulator:
    """Accumulate fused-guideline metrics without storing private message content."""

    events: list[HweNormalizedEvent] = field(default_factory=list)
    api_input_tokens: int = 0
    api_output_tokens: int = 0
    profile_id: str = HWE_COLLECTION_PROFILE_ID

    def add(self, event: HweNormalizedEvent) -> None:
        self.events.append(event)

    def build(self, *, compact_total_tokens: int, sft_total_tokens: int) -> dict[str, Any]:
        profile = resolve_hwe_collection_profile(self.profile_id)
        decision_events = [event for event in self.events if event.action != "finish"]
        mutations = [
            event
            for event in self.events
            if event.action == "apply_patch" or (event.action == "shell" and event.changed_paths)
        ]
        unique_files = sorted({path for event in self.events for path in event.changed_paths})
        raw_bytes = sum(event.raw_observation_bytes for event in self.events)
        compact_observation_tokens = sum(event.compact_observation_tokens for event in self.events)
        observation_breakdown = Counter(
            event.action
            for event in self.events
            if event.compact_observation_tokens or event.raw_observation_bytes
        )
        observation_hashes = [
            event.compact_observation_sha256
            for event in self.events
            if event.compact_observation_sha256 is not None
        ]
        duplicates = len(observation_hashes) - len(set(observation_hashes))
        added, deleted = _patch_churn(self.events)
        api_total = self.api_input_tokens + self.api_output_tokens
        result = {
            "decision_steps": len(decision_events),
            "mutation_actions": len(mutations),
            "long_horizon": (
                len(decision_events) > profile.decision_steps_soft
                or len(mutations) > profile.mutation_actions_soft
            ),
            "api_input_tokens": self.api_input_tokens,
            "api_output_tokens": self.api_output_tokens,
            "api_total_tokens": api_total,
            "raw_observation_bytes": raw_bytes,
            "compact_observation_tokens": compact_observation_tokens,
            "compact_total_tokens": compact_total_tokens,
            "sft_total_tokens": sft_total_tokens,
            "observation_breakdown": dict(sorted(observation_breakdown.items())),
            "observation_duplicate_count": duplicates,
            "observation_duplicate_rate": (
                duplicates / len(observation_hashes) if observation_hashes else 0.0
            ),
            "compile_steps": sum(event.compile_observed for event in self.events),
            "simulation_steps": sum(event.simulation_observed for event in self.events),
            "unique_files": unique_files,
            "unique_file_count": len(unique_files),
            "patch_churn_added_lines": added,
            "patch_churn_deleted_lines": deleted,
            "raw_bytes_per_compact_token": (
                raw_bytes / compact_observation_tokens if compact_observation_tokens else 0.0
            ),
            "raw_to_sft_token_ratio": (api_total / sft_total_tokens if sft_total_tokens else 0.0),
        }
        if profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID:
            result.update(
                {
                    "command_exit_codes": [
                        event.exit_code for event in decision_events if event.exit_code is not None
                    ],
                    "command_duration_ms": sum(event.duration_ms or 0 for event in decision_events),
                    "raw_stdout_bytes": sum(event.raw_stdout_bytes for event in decision_events),
                    "raw_stderr_bytes": sum(event.raw_stderr_bytes for event in decision_events),
                }
            )
        return result


def build_hwe_teacher_transcript(
    *,
    task_id: str,
    model_id: str,
    client_version: str,
    client_sha256: str,
    agent_image_lock_hash: str,
    messages: list[dict[str, Any]],
    normalized_events: Sequence[HweNormalizedEvent],
    counter: TokenCounter,
    api_input_tokens: int,
    api_output_tokens: int,
    raw_layer_hash: str,
    model_visible_layer_hash: str | None = None,
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
    exit_reason: str = "agent_finish",
) -> dict[str, Any]:
    """Seal a successful HWE public transcript; raw data stays in private-audit."""

    profile = resolve_hwe_collection_profile(profile_id)
    _validate_message_sequence(messages, profile_id=profile_id)
    if model_id != "gpt-5.4":
        raise ValueError("the first HWE campaign freezes GPT-5.4")
    if not re.fullmatch(r"[0-9a-f]{64}", client_sha256):
        raise ValueError("Codex client identity must be SHA-256")
    compact_tokens = _message_tokens(messages, counter)
    sft_messages, transformations = secondary_sft_compaction(messages, normalized_events)
    _validate_message_sequence(sft_messages, profile_id=profile_id)
    sft_tokens = _message_tokens(sft_messages, counter)
    bucket = hwe_sft_bucket(sft_tokens, profile_id=profile_id)
    accumulator = HweMetricsAccumulator(
        list(normalized_events),
        api_input_tokens=api_input_tokens,
        api_output_tokens=api_output_tokens,
        profile_id=profile_id,
    )
    metrics = accumulator.build(compact_total_tokens=compact_tokens, sft_total_tokens=sft_tokens)
    model_hash = model_visible_layer_hash or content_hash(messages)
    sft_hash = content_hash(sft_messages)
    manifest = build_compaction_manifest(
        raw_layer_hash=raw_layer_hash,
        model_visible_layer_hash=model_hash,
        sft_layer_hash=sft_hash,
        raw_tokens=api_input_tokens + api_output_tokens,
        model_visible_tokens=compact_tokens,
        sft_tokens=sft_tokens,
        normalized_events=normalized_events,
        transformations=transformations,
        profile_id=profile_id,
    )
    is_v2 = profile_id == HWE_COLLECTION_PROFILE_V2_ID
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": (HWE_TEACHER_TRANSCRIPT_V3_FORMAT if is_v2 else HWE_TEACHER_TRANSCRIPT_FORMAT),
        "collection_profile_id": profile.profile_id,
        "observation_policy_id": profile.observation_policy_id,
        "tool_contract_id": profile.tool_contract_id,
        "tool_contract_hash": hwe_tool_contract_hash(profile_id=profile_id),
        "task_id": task_id,
        "provider": "openai",
        "model_id": model_id,
        "reasoning_effort": "xhigh",
        "client_kind": "cli",
        "client_name": "codex-cli",
        "client_version": client_version,
        "client_sha256": client_sha256,
        "agent_image_lock_hash": agent_image_lock_hash,
        "tokenizer_id": counter.tokenizer_id,
        "tokenizer_hash": counter.tokenizer_hash,
        "messages": messages,
        "sft_messages": sft_messages,
        "metrics": metrics,
        "sft_bucket": bucket,
        "primary_eligible": bucket == "primary",
        "long_context_enabled": profile.enable_long_context_bucket,
        "compaction_manifest": manifest,
        "verifier_resolved": True,
        "infrastructure_valid": True,
        "causal_validation": "passed",
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "private_reasoning_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    if is_v2:
        if exit_reason != "agent_finish":
            raise ValueError("successful HWE v2 transcripts require agent_finish")
        base.update(
            {
                "exit_reason": exit_reason,
                "episode_limits": {
                    "decision_steps_soft": profile.decision_steps_soft,
                    "decision_steps_hard": profile.decision_steps_hard,
                    "mutation_actions_soft": profile.mutation_actions_soft,
                    "mutation_actions_hard": profile.mutation_actions_hard,
                    "episode_wall_time_s": profile.episode_wall_time_s,
                    "raw_command_bytes": profile.raw_command_bytes,
                    "raw_episode_bytes": profile.raw_episode_bytes,
                },
                "container_read_scope": "isolated_agent_container",
                "candidate_write_scope": "/workspace/repository",
                "ephemeral_write_scope": "/tmp",
            }
        )
    return {**base, "transcript_hash": content_hash(base)}


def validate_hwe_teacher_transcript(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(value)
    expected = candidate.pop("transcript_hash", None)
    if not isinstance(expected, str) or content_hash(candidate) != expected:
        raise ValueError("HWE transcript identity changed")
    profile_id = value.get("collection_profile_id")
    profile = resolve_hwe_collection_profile(profile_id)
    expected_format = (
        HWE_TEACHER_TRANSCRIPT_V3_FORMAT
        if profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
        else HWE_TEACHER_TRANSCRIPT_FORMAT
    )
    required = {
        "format_id": expected_format,
        "collection_profile_id": profile.profile_id,
        "observation_policy_id": profile.observation_policy_id,
        "tool_contract_id": profile.tool_contract_id,
        "tool_contract_hash": hwe_tool_contract_hash(profile_id=profile.profile_id),
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "verifier_resolved": True,
        "infrastructure_valid": True,
        "causal_validation": "passed",
    }
    if any(value.get(key) != expected_value for key, expected_value in required.items()):
        raise ValueError("HWE transcript differs from the frozen collection contract")
    for key in (
        "raw_provider_events_exported",
        "raw_observations_exported",
        "hidden_assets_exported",
        "reference_solutions_exported",
        "private_reasoning_exported",
        "credential_values_exported",
        "raw_host_paths_exported",
    ):
        if value.get(key) is not False:
            raise ValueError(f"HWE transcript violates {key}")
    messages = value.get("messages")
    sft_messages = value.get("sft_messages")
    if not isinstance(messages, list) or not isinstance(sft_messages, list):
        raise ValueError("HWE transcript omits compact message layers")
    _validate_message_sequence(messages, profile_id=profile.profile_id)
    _validate_message_sequence(sft_messages, profile_id=profile.profile_id)
    manifest = value.get("compaction_manifest")
    if not isinstance(manifest, dict) or manifest.get("causal_validation") != "passed":
        raise ValueError("HWE transcript lacks causal compaction proof")
    expected_manifest_format = (
        HWE_COMPACTION_MANIFEST_V2_FORMAT
        if profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
        else HWE_COMPACTION_MANIFEST_FORMAT
    )
    if manifest.get("format_id") != expected_manifest_format or (
        profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
        and manifest.get("collection_profile_id") != profile.profile_id
    ):
        raise ValueError("HWE compaction manifest profile is inconsistent")
    manifest_identity = dict(manifest)
    manifest_hash = manifest_identity.pop("manifest_hash", None)
    if not isinstance(manifest_hash, str) or content_hash(manifest_identity) != manifest_hash:
        raise ValueError("HWE compaction manifest identity changed")
    if manifest.get("model_visible_sha256") != content_hash(messages):
        raise ValueError("HWE model-visible layer identity changed")
    if manifest.get("sft_sha256") != content_hash(sft_messages):
        raise ValueError("HWE SFT layer identity changed")
    metrics = value.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("HWE transcript omits collection metrics")
    compact_tokens = metrics.get("compact_total_tokens")
    sft_tokens = metrics.get("sft_total_tokens")
    api_tokens = metrics.get("api_total_tokens")
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in (
            compact_tokens,
            sft_tokens,
            api_tokens,
        )
    ):
        raise ValueError("HWE transcript token metrics are malformed")
    assert isinstance(compact_tokens, int)
    assert isinstance(sft_tokens, int)
    assert isinstance(api_tokens, int)
    bucket = hwe_sft_bucket(sft_tokens, profile_id=profile.profile_id)
    if (
        manifest.get("model_visible_tokens") != compact_tokens
        or manifest.get("sft_tokens") != sft_tokens
        or manifest.get("raw_tokens") != api_tokens
        or value.get("sft_bucket") != bucket
        or value.get("primary_eligible") is not (bucket == "primary")
        or value.get("long_context_enabled") is not False
    ):
        raise ValueError("HWE transcript bucket or token layers are inconsistent")
    if profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID:
        expected_limits = {
            "decision_steps_soft": profile.decision_steps_soft,
            "decision_steps_hard": profile.decision_steps_hard,
            "mutation_actions_soft": profile.mutation_actions_soft,
            "mutation_actions_hard": profile.mutation_actions_hard,
            "episode_wall_time_s": profile.episode_wall_time_s,
            "raw_command_bytes": profile.raw_command_bytes,
            "raw_episode_bytes": profile.raw_episode_bytes,
        }
        if (
            value.get("exit_reason") != "agent_finish"
            or value.get("episode_limits") != expected_limits
            or value.get("container_read_scope") != "isolated_agent_container"
            or value.get("candidate_write_scope") != "/workspace/repository"
            or value.get("ephemeral_write_scope") != "/tmp"
        ):
            raise ValueError("HWE v2 transcript execution boundary is inconsistent")
    expected_tokenizer_hash = hashlib.sha256(b"tiktoken==0.7.0\x00o200k_base").hexdigest()
    if (
        value.get("tokenizer_id") != HWE_TOKENIZER_ID
        or value.get("tokenizer_hash") != expected_tokenizer_hash
    ):
        raise ValueError("HWE transcript tokenizer identity changed")
    return dict(value)


def materialize_hwe_sft_example(
    transcript: Mapping[str, Any], *, binding: Mapping[str, Any]
) -> dict[str, Any]:
    """Create one 32K assistant-only record only from a primary eligible transcript."""

    validated = validate_hwe_teacher_transcript(transcript)
    if validated.get("sft_bucket") != "primary" or validated.get("primary_eligible") is not True:
        raise ValueError("only the HWE primary bucket may enter the current training binding")
    metrics = validated.get("metrics")
    if not isinstance(metrics, dict) or not isinstance(metrics.get("sft_total_tokens"), int):
        raise ValueError("HWE transcript omits exact SFT token metrics")
    profile = resolve_hwe_collection_profile(validated["collection_profile_id"])
    is_v2 = profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
    base = {
        "schema_version": "1.0",
        "format_id": HWE_SFT_EXAMPLE_V3_FORMAT if is_v2 else HWE_SFT_EXAMPLE_FORMAT,
        "sample_id": binding.get("sample_id"),
        "task_id": validated["task_id"],
        "task_hash": binding.get("task_hash"),
        "source_hash": binding.get("source_hash"),
        "candidate_hash": binding.get("candidate_hash"),
        "verifier_hash": binding.get("verifier_hash"),
        "transcript_hash": validated["transcript_hash"],
        "tool_contract_id": profile.tool_contract_id,
        "tool_contract_hash": hwe_tool_contract_hash(profile_id=profile.profile_id),
        "observation_policy_id": profile.observation_policy_id,
        "tokenizer_id": validated["tokenizer_id"],
        "tokenizer_hash": validated["tokenizer_hash"],
        "messages": validated["sft_messages"],
        "token_count": metrics["sft_total_tokens"],
        "max_length": 32_768,
        "truncation": "error",
        "supervised_roles": ["assistant"],
        "masked_roles": ["system", "user", "tool"],
        "verifier_resolved": True,
        "infrastructure_valid": True,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
    }
    if is_v2:
        base["collection_profile_id"] = profile.profile_id
    _require_hash_bindings(
        base,
        ("sample_id", "task_hash", "source_hash", "candidate_hash", "verifier_hash"),
    )
    return {**base, "example_hash": content_hash(base)}


def build_hwe_dataset_manifest(
    examples: Sequence[Mapping[str, Any]],
    *,
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
) -> dict[str, Any]:
    profile = resolve_hwe_collection_profile(profile_id)
    is_v2 = profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
    example_format = HWE_SFT_EXAMPLE_V3_FORMAT if is_v2 else HWE_SFT_EXAMPLE_FORMAT
    if len(examples) != 8:
        raise ValueError("the HWE handoff requires exactly eight primary examples")
    hashes: list[str] = []
    task_ids: set[str] = set()
    for example in examples:
        if example.get("format_id") != example_format or (
            is_v2 and example.get("collection_profile_id") != profile.profile_id
        ):
            raise ValueError("HWE dataset contains a foreign example format")
        if example.get("token_count", 32_769) > 32_768:
            raise ValueError("HWE dataset contains an overlength primary example")
        identity = dict(example)
        expected = identity.pop("example_hash", None)
        if not isinstance(expected, str) or content_hash(identity) != expected:
            raise ValueError("HWE example identity changed")
        task_id = example.get("task_id")
        if not isinstance(task_id, str) or task_id in task_ids:
            raise ValueError("HWE dataset requires eight distinct task bindings")
        task_ids.add(task_id)
        hashes.append(expected)
    base = {
        "schema_version": "1.0",
        "format_id": HWE_SFT_DATASET_V3_FORMAT if is_v2 else HWE_SFT_DATASET_FORMAT,
        "record_count": 8,
        "example_hashes": hashes,
        "task_ids": sorted(task_ids),
        "collection_profile_id": profile.profile_id,
        "observation_policy_id": profile.observation_policy_id,
        "tool_contract_id": profile.tool_contract_id,
        "tool_contract_hash": hwe_tool_contract_hash(profile_id=profile.profile_id),
        "max_length": 32_768,
        "truncation": "error",
        "supervised_roles": ["assistant"],
        "long_context_bucket_enabled": False,
        "hpc_jobs_submitted": False,
    }
    return {**base, "dataset_hash": content_hash(base)}


def hwe_sft_bucket(
    tokens: int,
    *,
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
) -> Literal["primary", "long_context_candidate", "audit"]:
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        raise ValueError("HWE token count must be a non-negative integer")
    profile = resolve_hwe_collection_profile(profile_id)
    if tokens <= profile.primary_token_limit:
        return "primary"
    if tokens <= profile.long_context_token_limit:
        return "long_context_candidate"
    return "audit"


def secondary_sft_compaction(
    messages: Sequence[Mapping[str, Any]],
    normalized_events: Sequence[HweNormalizedEvent],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply only ANSI/progress cleanup, repeat collapse, and same-epoch exact references."""

    result: list[dict[str, Any]] = [dict(copy.deepcopy(message)) for message in messages]
    transformations: list[dict[str, Any]] = []
    observations: dict[tuple[int, str], str] = {}
    event_index = 0
    pending_epoch: int | None = None
    for index, message in enumerate(result):
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            call = message["tool_calls"][0]
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = function.get("name") if isinstance(function, dict) else None
            if (
                event_index >= len(normalized_events)
                or name != normalized_events[event_index].action
            ):
                raise ValueError("HWE messages and normalized events are not causally aligned")
            pending_epoch = normalized_events[event_index].workspace_epoch_after
            event_index += 1
        if role != "tool" or not isinstance(message.get("content"), str):
            continue
        if pending_epoch is None:
            raise ValueError("HWE tool observation lacks a normalized workspace epoch")
        original = message["content"]
        cleaned = clean_terminal_noise(original)
        collapsed_lines, collapsed = collapse_repeated_lines(cleaned.splitlines())
        compact = "\n".join(collapsed_lines)
        digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()
        key = (pending_epoch, digest)
        if key in observations:
            compact = f"[verigym-hwe identical-observation sha256={digest} epoch={pending_epoch}]"
            operation = "same_epoch_hash_reference"
        else:
            observations[key] = digest
            operation = "ansi_progress_and_repeat_cleanup"
        message["content"] = compact
        transformations.append(
            {
                "message_index": index,
                "operation": operation,
                "workspace_epoch": pending_epoch,
                "input_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                "output_sha256": hashlib.sha256(compact.encode("utf-8")).hexdigest(),
                "collapsed_repeated_lines": collapsed,
            }
        )
        pending_epoch = None
    if event_index != len(normalized_events) or pending_epoch is not None:
        raise ValueError("HWE normalized events do not exactly cover the tool transcript")
    return result, transformations


def build_compaction_manifest(
    *,
    raw_layer_hash: str,
    model_visible_layer_hash: str,
    sft_layer_hash: str,
    raw_tokens: int,
    model_visible_tokens: int,
    sft_tokens: int,
    normalized_events: Sequence[HweNormalizedEvent],
    transformations: Sequence[Mapping[str, Any]],
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
) -> dict[str, Any]:
    profile = resolve_hwe_collection_profile(profile_id)
    for value in (raw_layer_hash, model_visible_layer_hash, sft_layer_hash):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("HWE compaction layers require SHA-256 identities")
    _validate_event_causality(normalized_events)
    base = {
        "schema_version": "1.0",
        "format_id": (
            HWE_COMPACTION_MANIFEST_V2_FORMAT
            if profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
            else HWE_COMPACTION_MANIFEST_FORMAT
        ),
        "raw_sha256": raw_layer_hash,
        "model_visible_sha256": model_visible_layer_hash,
        "sft_sha256": sft_layer_hash,
        "raw_tokens": raw_tokens,
        "model_visible_tokens": model_visible_tokens,
        "sft_tokens": sft_tokens,
        "omissions": [
            {
                "sequence": event.sequence,
                "raw_bytes": event.raw_observation_bytes,
                "raw_sha256": event.raw_observation_sha256,
                "compact_tokens": event.compact_observation_tokens,
                "rule_id": event.observation_rule_id,
            }
            for event in normalized_events
            if event.observation_omitted
        ],
        "event_mapping": [event.event_mapping for event in normalized_events],
        "transformations": list(transformations),
        "causal_validation": "passed",
    }
    if profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID:
        base["collection_profile_id"] = profile.profile_id
        base["step_outcomes"] = [
            {
                "sequence": event.sequence,
                "action": event.action,
                "exit_code": event.exit_code,
                "duration_ms": event.duration_ms,
                "raw_stdout_bytes": event.raw_stdout_bytes,
                "raw_stderr_bytes": event.raw_stderr_bytes,
                "raw_stdout_sha256": event.raw_stdout_sha256,
                "raw_stderr_sha256": event.raw_stderr_sha256,
                "workspace_epoch_before": event.workspace_epoch_before,
                "workspace_epoch_after": event.workspace_epoch_after,
                "changed_paths": list(event.changed_paths),
            }
            for event in normalized_events
        ]
    return {**base, "manifest_hash": content_hash(base)}


def _validate_message_sequence(
    messages: Sequence[Mapping[str, Any]],
    *,
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
) -> None:
    if len(messages) < 5 or [message.get("role") for message in messages[:2]] != [
        "system",
        "user",
    ]:
        raise ValueError("HWE transcript must begin with system and user")
    if messages[-1].get("role") != "assistant" or messages[-1].get("tool_calls"):
        raise ValueError("HWE transcript must end with a final assistant message")
    pending: tuple[str, str] | None = None
    saw_finish = False
    for index, message in enumerate(messages[2:], start=2):
        role = message.get("role")
        if role == "assistant":
            calls = message.get("tool_calls")
            if calls:
                if pending is not None or not isinstance(calls, list) or len(calls) != 1:
                    raise ValueError("HWE transcript permits one ordered tool call per turn")
                call = calls[0]
                function = call.get("function") if isinstance(call, dict) else None
                if not isinstance(function, dict) or not isinstance(call.get("id"), str):
                    raise ValueError("HWE assistant tool call is malformed")
                name = function.get("name")
                arguments = function.get("arguments")
                if not isinstance(name, str) or not isinstance(arguments, str):
                    raise ValueError("HWE assistant tool call lacks canonical arguments")
                parsed = json.loads(arguments)
                if canonical_hwe_action_json(name, parsed, profile_id=profile_id) != json.dumps(
                    {"protocol": "repository_action.v2", "action": name, "arguments": parsed},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ):
                    raise ValueError("HWE tool arguments are not canonical")
                pending = (call["id"], name)
                saw_finish = saw_finish or name == "finish"
            elif index != len(messages) - 1:
                raise ValueError("HWE final prose may occur only at the end")
        elif role == "tool":
            if pending is None or (message.get("tool_call_id"), message.get("name")) != pending:
                raise ValueError("HWE tool observation does not match its action")
            if not isinstance(message.get("content"), str):
                raise ValueError("HWE tool observation must be public text")
            pending = None
        else:
            raise ValueError("HWE transcript cannot inject new system/user messages")
    if pending is not None or not saw_finish:
        raise ValueError("HWE transcript must observe an explicit finish action")


def _validate_event_causality(events: Sequence[HweNormalizedEvent]) -> None:
    expected_sequence = 0
    epoch = 0
    saw_finish = False
    for event in events:
        if event.sequence != expected_sequence:
            raise ValueError("HWE normalized events are not contiguous")
        if event.workspace_epoch_before != epoch:
            raise ValueError("HWE event workspace epoch has a causal gap")
        changed = bool(event.changed_paths)
        expected_after = epoch + (1 if changed else 0)
        if event.workspace_epoch_after != expected_after:
            raise ValueError("HWE changed paths and workspace epoch disagree")
        if event.action == "apply_patch" and not changed:
            raise ValueError("HWE apply_patch must carry its observed changed paths")
        if saw_finish:
            raise ValueError("HWE events cannot follow finish")
        saw_finish = event.action == "finish"
        epoch = expected_after
        expected_sequence += 1
    if not saw_finish:
        raise ValueError("HWE normalized events omit synthetic finish")


def _message_tokens(messages: Sequence[Mapping[str, Any]], counter: TokenCounter) -> int:
    serialized = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return counter.count(serialized)


def _patch_churn(events: Sequence[HweNormalizedEvent]) -> tuple[int, int]:
    added = 0
    deleted = 0
    for event in events:
        if event.action != "apply_patch":
            continue
        patch = event.arguments.get("patch")
        if not isinstance(patch, str):
            continue
        for line in patch.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                deleted += 1
    return added, deleted


def command_classification(command: str) -> tuple[bool, bool]:
    return bool(_COMPILE.search(command)), bool(_SIMULATION.search(command))


def patch_changed_paths(patch: str) -> tuple[str, ...]:
    paths = {value for value in _PATCH_HEADER.findall(patch) if value != "/dev/null"}
    if patch and not _HUNK.search(patch):
        return ()
    return tuple(sorted(paths))


def _require_hash_bindings(value: Mapping[str, Any], names: Sequence[str]) -> None:
    for name in names:
        item = value.get(name)
        if not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item):
            raise ValueError(f"HWE binding {name} must be SHA-256")


__all__ = [
    "HWE_COMPACTION_MANIFEST_FORMAT",
    "HWE_COMPACTION_MANIFEST_V2_FORMAT",
    "HWE_SFT_DATASET_FORMAT",
    "HWE_SFT_DATASET_V3_FORMAT",
    "HWE_SFT_EXAMPLE_FORMAT",
    "HWE_SFT_EXAMPLE_V3_FORMAT",
    "HWE_TEACHER_TRANSCRIPT_FORMAT",
    "HWE_TEACHER_TRANSCRIPT_V3_FORMAT",
    "HweEpisodeBudget",
    "HweLimitExceeded",
    "HweMetricsAccumulator",
    "HweNormalizedEvent",
    "build_compaction_manifest",
    "build_hwe_dataset_manifest",
    "build_hwe_teacher_transcript",
    "command_classification",
    "hwe_sft_bucket",
    "materialize_hwe_sft_example",
    "patch_changed_paths",
    "secondary_sft_compaction",
    "validate_hwe_teacher_transcript",
]
