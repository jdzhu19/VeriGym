"""Deterministic action-preserving history views for HWE training derivation.

The Codex app-server owns its live provider history, so this module does not claim to alter a
container-native rollout.  It derives the exact rolling view that an action-conditioned training
record would expose: all assistant actions remain byte-identical, recent observations remain
visible, a bounded set of HWE diagnostics may be pinned, and older observations become typed hash
markers.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from verigym.core.hashing import content_hash
from verigym.hwe.observation import TokenCounter
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    hwe_tool_contract_hash,
)
from verigym.hwe.trajectory import validate_hwe_teacher_transcript
from verigym.schemas.hwe import (
    HweActionConditionedSftDatasetManifest,
    HweActionConditionedSftExample,
)

HWE_HISTORY_MASKING_POLICY_ID = "hwe_action_preserving_observation_masking_v1"
HWE_HISTORY_MASKING_MARKER_RULE_ID = "hwe_action_preserving_observation_masking_v1/hash_marker_v1"
HWE_SELECTED_HISTORY_WINDOW: Literal[16] = 16
HWE_ACTION_CONDITIONED_SFT_FORMAT = "verigym_hwe_action_conditioned_sft_v1"
HWE_ACTION_CONDITIONED_DATASET_FORMAT = "verigym_hwe_action_conditioned_sft_dataset_v1"
HWE_MASKING_ANALYSIS_FORMAT = "verigym_hwe_observation_masking_analysis_v1"
HWE_LOSSLESS_HISTORY_POLICY_ID = "hwe_action_preserving_observation_masking_v1/lossless_under_32k"
HWE_LOSSLESS_HISTORY_MARKER_RULE_ID = f"{HWE_LOSSLESS_HISTORY_POLICY_ID}/no_markers"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MASKED_MARKER = re.compile(
    r"^\[verigym-hwe masked-observation "
    r"rule=hwe_action_preserving_observation_masking_v1/hash_marker_v1 "
    r"sequence=(?P<sequence>\d+) "
    r"action=(?P<action>list_files|read_file|apply_patch|shell|inspect_diff|finish) "
    r"workspace_epoch=\d+ content_bytes=\d+ content_sha256=[0-9a-f]{64} "
    r"content_tokens=\d+ reason=outside_recent_window\]$"
)
_COMPILE = re.compile(r"\b(?:make|verilator|iverilog|sbt|mill|compile|elaborat)\b", re.I)
_SIMULATION = re.compile(r"\b(?:simulat|regress|spike|vcs|questa|xrun)\b", re.I)


@dataclass(frozen=True)
class HweHistoryMaskingPolicy:
    """A frozen family of rollout-history analyses with an explicit rolling window."""

    policy_id: str = HWE_HISTORY_MASKING_POLICY_ID
    recent_observations: Literal[1, 2, 4, 8, 10, 16] = HWE_SELECTED_HISTORY_WINDOW
    max_pinned_observations: Literal[1, 2, 4] = 4
    max_tokens: int = 32_768
    preserve_all_actions: bool = True
    pin_current_epoch_diagnostics: bool = True
    marker_rule_id: str = HWE_HISTORY_MASKING_MARKER_RULE_ID

    def __post_init__(self) -> None:
        if self.policy_id != HWE_HISTORY_MASKING_POLICY_ID:
            raise ValueError("unsupported HWE history masking policy")
        if self.recent_observations not in {1, 2, 4, 8, 10, 16}:
            raise ValueError("HWE masking supports only M=1, M=2, M=4, M=8, M=10, or M=16")
        if (
            self.max_pinned_observations not in {1, 2, 4}
            or self.max_tokens != 32_768
            or self.preserve_all_actions is not True
            or self.pin_current_epoch_diagnostics is not True
            or self.marker_rule_id != HWE_HISTORY_MASKING_MARKER_RULE_ID
        ):
            raise ValueError("HWE history masking has unsupported fixed semantics")

    def identity(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def policy_hash(self) -> str:
        return content_hash(self.identity())


@dataclass(frozen=True)
class _ObservationTurn:
    sequence: int
    action: str
    assistant_index: int
    tool_index: int
    arguments: dict[str, Any]
    workspace_epoch_before: int
    workspace_epoch_after: int
    changed_paths: tuple[str, ...]
    exit_code: int | None
    compile_observed: bool
    simulation_observed: bool


def derive_hwe_masked_history_views(
    messages: Sequence[Mapping[str, Any]],
    *,
    step_outcomes: Sequence[Mapping[str, Any]],
    counter: TokenCounter,
    policy: HweHistoryMaskingPolicy | None = None,
) -> list[dict[str, Any]]:
    """Build one exact masked input view for every recorded assistant tool action."""

    selected_policy = policy or HweHistoryMaskingPolicy()
    source_messages = [dict(copy.deepcopy(message)) for message in messages]
    turns = _aligned_turns(source_messages, step_outcomes)
    views: list[dict[str, Any]] = []
    prior_observations: list[_ObservationTurn] = []
    for target in turns:
        source_history = [
            dict(copy.deepcopy(message)) for message in source_messages[: target.assistant_index]
        ]
        masked_history = [dict(copy.deepcopy(message)) for message in source_history]
        recent = {
            turn.sequence for turn in prior_observations[-selected_policy.recent_observations :]
        }
        pinned = _pinned_sequences(
            prior_observations,
            current_epoch=target.workspace_epoch_before,
            limit=selected_policy.max_pinned_observations,
        )
        retained = recent | pinned
        masked_sequences: list[int] = []
        masked_source_tokens = 0
        marker_tokens = 0
        for observation in prior_observations:
            if observation.sequence in retained:
                continue
            message = masked_history[observation.tool_index]
            content = message.get("content")
            if not isinstance(content, str):
                raise ValueError("HWE history masking requires textual tool observations")
            source_tokens = counter.count(content)
            marker = _mask_marker(observation, content, source_tokens)
            message["content"] = marker
            masked_sequences.append(observation.sequence)
            masked_source_tokens += source_tokens
            marker_tokens += counter.count(marker)
        if _action_projection(source_history) != _action_projection(masked_history):
            raise RuntimeError("HWE history masking changed an assistant action")
        target_message = dict(copy.deepcopy(source_messages[target.assistant_index]))
        training_messages = [*masked_history, target_message]
        source_history_tokens = _message_tokens(source_history, counter)
        input_tokens = _message_tokens(masked_history, counter)
        target_tokens = _message_tokens([target_message], counter)
        total_tokens = _message_tokens(training_messages, counter)
        ledger = {
            "schema_version": "1.0",
            "policy_id": selected_policy.policy_id,
            "policy_hash": selected_policy.policy_hash,
            "marker_rule_id": selected_policy.marker_rule_id,
            "recent_observations": selected_policy.recent_observations,
            "max_pinned_observations": selected_policy.max_pinned_observations,
            "target_sequence": target.sequence,
            "target_action": target.action,
            "target_message_index": target.assistant_index,
            "workspace_epoch": target.workspace_epoch_before,
            "source_history_sha256": content_hash(source_history),
            "masked_history_sha256": content_hash(masked_history),
            "target_action_sha256": content_hash(target_message),
            "source_history_tokens": source_history_tokens,
            "input_tokens": input_tokens,
            "target_tokens": target_tokens,
            "total_tokens": total_tokens,
            "retained_observation_sequences": sorted(retained),
            "recent_observation_sequences": sorted(recent),
            "pinned_observation_sequences": sorted(pinned),
            "masked_observation_sequences": masked_sequences,
            "masked_source_observation_tokens": masked_source_tokens,
            "mask_marker_tokens": marker_tokens,
            "all_prior_actions_preserved": True,
            "target_action_preserved": True,
            "structural_causal_validation": "passed",
            "counterfactual_next_action_validation": "not_run",
        }
        views.append(
            {
                "messages": training_messages,
                "history_ledger": {**ledger, "ledger_hash": content_hash(ledger)},
                "within_32k": total_tokens <= selected_policy.max_tokens,
            }
        )
        prior_observations.append(target)
    return views


def derive_hwe_lossless_history_view(
    messages: Sequence[Mapping[str, Any]],
    *,
    step_outcomes: Sequence[Mapping[str, Any]],
    counter: TokenCounter,
    target_sequence: int,
) -> dict[str, Any]:
    """Build a lossless target view when the complete history is within the 32K contract.

    This is an explicitly versioned recovery policy.  It is useful for early actions where the
    full history is short: masking a single old observation can change a base model's next-action
    choice even though no length pressure exists.  The view never truncates or rewrites a source
    message and is selected only after the historical masked view fails NAP.
    """

    source_messages = [dict(copy.deepcopy(message)) for message in messages]
    turns = _aligned_turns(source_messages, step_outcomes)
    target = next(
        (turn for turn in turns if turn.sequence == target_sequence),
        None,
    )
    if target is None:
        raise ValueError(f"missing target sequence {target_sequence} in HWE transcript")
    source_history = [
        dict(copy.deepcopy(message)) for message in source_messages[: target.assistant_index]
    ]
    target_message = dict(copy.deepcopy(source_messages[target.assistant_index]))
    source_history_tokens = _message_tokens(source_history, counter)
    target_tokens = _message_tokens([target_message], counter)
    total_tokens = source_history_tokens + target_tokens
    retained_sequences = [turn.sequence for turn in turns if turn.sequence < target_sequence]
    recent_observations = HWE_SELECTED_HISTORY_WINDOW
    recent_sequences = retained_sequences[-recent_observations:]
    policy_identity = {
        "policy_id": HWE_LOSSLESS_HISTORY_POLICY_ID,
        "marker_rule_id": HWE_LOSSLESS_HISTORY_MARKER_RULE_ID,
        "max_tokens": 32_768,
        "preserve_all_actions": True,
        "lossless": True,
        "recent_observations": HWE_SELECTED_HISTORY_WINDOW,
        "max_pinned_observations": 4,
    }
    policy_hash = content_hash(policy_identity)
    ledger = {
        "schema_version": "1.0",
        "policy_id": HWE_LOSSLESS_HISTORY_POLICY_ID,
        "policy_hash": policy_hash,
        "marker_rule_id": HWE_LOSSLESS_HISTORY_MARKER_RULE_ID,
        "recent_observations": recent_observations,
        "max_pinned_observations": 4,
        "target_sequence": target.sequence,
        "target_action": target.action,
        "target_message_index": target.assistant_index,
        "workspace_epoch": target.workspace_epoch_before,
        "source_history_sha256": content_hash(source_history),
        "masked_history_sha256": content_hash(source_history),
        "target_action_sha256": content_hash(target_message),
        "source_history_tokens": source_history_tokens,
        "input_tokens": source_history_tokens,
        "target_tokens": target_tokens,
        "total_tokens": total_tokens,
        "retained_observation_sequences": retained_sequences,
        "recent_observation_sequences": recent_sequences,
        "pinned_observation_sequences": [],
        "masked_observation_sequences": [],
        "masked_source_observation_tokens": 0,
        "mask_marker_tokens": 0,
        "all_prior_actions_preserved": True,
        "target_action_preserved": True,
        "structural_causal_validation": "passed",
        "counterfactual_next_action_validation": "not_run",
    }
    return {
        "messages": [*source_history, target_message],
        "history_ledger": {**ledger, "ledger_hash": content_hash(ledger)},
        "within_32k": total_tokens <= 32_768,
    }


def materialize_hwe_action_conditioned_examples(
    transcript: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    counter: TokenCounter,
    policy: HweHistoryMaskingPolicy | None = None,
) -> list[dict[str, Any]]:
    """Derive experimental next-action records without relabeling the current primary bucket."""

    validated = validate_hwe_teacher_transcript(transcript)
    if validated.get("collection_profile_id") != HWE_COLLECTION_PROFILE_V2_ID:
        raise ValueError("action-conditioned HWE SFT requires hwe_standard_v2 transcripts")
    _require_hash_bindings(
        binding,
        ("sample_id", "task_hash", "source_hash", "candidate_hash", "verifier_hash"),
    )
    manifest = validated.get("compaction_manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("HWE transcript omits its compaction manifest")
    outcomes = manifest.get("step_outcomes")
    messages = validated.get("sft_messages")
    if not isinstance(outcomes, list) or not isinstance(messages, list):
        raise ValueError("HWE transcript omits action-conditioned source layers")
    selected_policy = policy or HweHistoryMaskingPolicy()
    views = derive_hwe_masked_history_views(
        messages,
        step_outcomes=outcomes,
        counter=counter,
        policy=selected_policy,
    )
    examples: list[dict[str, Any]] = []
    for view in views:
        ledger = view["history_ledger"]
        if view["within_32k"] is not True:
            raise ValueError(
                f"masked HWE action context at sequence {ledger['target_sequence']} exceeds 32K"
            )
        record_id = content_hash(
            {
                "trajectory_sample_id": binding["sample_id"],
                "transcript_hash": validated["transcript_hash"],
                "policy_hash": selected_policy.policy_hash,
                "target_sequence": ledger["target_sequence"],
            }
        )
        base = {
            "schema_version": "1.0",
            "format_id": HWE_ACTION_CONDITIONED_SFT_FORMAT,
            "record_id": record_id,
            "trajectory_sample_id": binding["sample_id"],
            "task_id": validated["task_id"],
            "task_hash": binding["task_hash"],
            "source_hash": binding["source_hash"],
            "candidate_hash": binding["candidate_hash"],
            "verifier_hash": binding["verifier_hash"],
            "source_transcript_hash": validated["transcript_hash"],
            "source_sft_bucket": validated["sft_bucket"],
            "source_primary_eligible": validated["primary_eligible"],
            "collection_profile_id": validated["collection_profile_id"],
            "observation_policy_id": validated["observation_policy_id"],
            "tool_contract_id": validated["tool_contract_id"],
            "tool_contract_hash": hwe_tool_contract_hash(
                profile_id=validated["collection_profile_id"]
            ),
            "history_policy_id": selected_policy.policy_id,
            "history_policy_hash": selected_policy.policy_hash,
            "tokenizer_id": counter.tokenizer_id,
            "tokenizer_hash": counter.tokenizer_hash,
            "target_sequence": ledger["target_sequence"],
            "target_action": ledger["target_action"],
            "messages": view["messages"],
            "history_ledger": ledger,
            "input_token_count": ledger["input_tokens"],
            "target_token_count": ledger["target_tokens"],
            "token_count": ledger["total_tokens"],
            "max_length": 32_768,
            "truncation": "error",
            "supervised_message_indices": [len(view["messages"]) - 1],
            "prior_assistant_labels_masked": True,
            "training_semantics": "next_action_conditioned_on_exact_masked_history",
            "training_eligibility": "experimental_action_conditioned",
            "primary_eligible": False,
            "counterfactual_next_action_validation": "not_run",
            "verifier_resolved": True,
            "infrastructure_valid": True,
            "raw_provider_events_exported": False,
            "raw_observations_exported": False,
            "private_reasoning_exported": False,
            "hidden_assets_exported": False,
            "reference_solutions_exported": False,
            "credential_values_exported": False,
            "raw_host_paths_exported": False,
        }
        sealed = {**base, "record_hash": content_hash(base)}
        examples.append(
            HweActionConditionedSftExample.model_validate(sealed).model_dump(mode="json")
        )
    return examples


def validate_hwe_action_conditioned_example(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(value)
    expected = candidate.pop("record_hash", None)
    if not isinstance(expected, str) or content_hash(candidate) != expected:
        raise ValueError("HWE action-conditioned record identity changed")
    required = {
        "format_id": HWE_ACTION_CONDITIONED_SFT_FORMAT,
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "max_length": 32_768,
        "truncation": "error",
        "prior_assistant_labels_masked": True,
        "training_semantics": "next_action_conditioned_on_exact_masked_history",
        "training_eligibility": "experimental_action_conditioned",
        "primary_eligible": False,
        "counterfactual_next_action_validation": "not_run",
        "verifier_resolved": True,
        "infrastructure_valid": True,
    }
    if any(value.get(key) != expected_value for key, expected_value in required.items()):
        raise ValueError("HWE action-conditioned record contract changed")
    for key in (
        "raw_provider_events_exported",
        "raw_observations_exported",
        "private_reasoning_exported",
        "hidden_assets_exported",
        "reference_solutions_exported",
        "credential_values_exported",
        "raw_host_paths_exported",
    ):
        if value.get(key) is not False:
            raise ValueError(f"HWE action-conditioned record violates {key}")
    for key in (
        "record_id",
        "trajectory_sample_id",
        "task_hash",
        "source_hash",
        "candidate_hash",
        "verifier_hash",
        "source_transcript_hash",
        "tool_contract_hash",
        "history_policy_hash",
        "tokenizer_hash",
        "record_hash",
    ):
        _require_sha256(value.get(key), key)
    messages = value.get("messages")
    ledger = value.get("history_ledger")
    if not isinstance(messages, list) or not messages:
        raise ValueError("HWE action-conditioned record omits messages")
    if not isinstance(ledger, Mapping):
        raise ValueError("HWE action-conditioned record omits its history ledger")
    ledger_identity = dict(ledger)
    ledger_hash = ledger_identity.pop("ledger_hash", None)
    if not isinstance(ledger_hash, str) or content_hash(ledger_identity) != ledger_hash:
        raise ValueError("HWE masked history ledger identity changed")
    if (
        ledger.get("policy_id") != HWE_HISTORY_MASKING_POLICY_ID
        or ledger.get("policy_hash") != value.get("history_policy_hash")
        or ledger.get("masked_history_sha256") != content_hash(messages[:-1])
        or ledger.get("target_action_sha256") != content_hash(messages[-1])
        or ledger.get("target_sequence") != value.get("target_sequence")
        or ledger.get("target_action") != value.get("target_action")
        or ledger.get("all_prior_actions_preserved") is not True
        or ledger.get("target_action_preserved") is not True
        or ledger.get("structural_causal_validation") != "passed"
        or ledger.get("counterfactual_next_action_validation") != "not_run"
    ):
        raise ValueError("HWE masked history ledger is inconsistent")
    recent_observations = ledger.get("recent_observations")
    if isinstance(recent_observations, bool) or not isinstance(recent_observations, int):
        raise ValueError("HWE action-conditioned masking window is malformed")
    max_pinned = ledger.get("max_pinned_observations")
    if recent_observations not in {1, 2, 4, 8, 10, 16} or max_pinned not in {1, 2, 4}:
        raise ValueError("HWE action-conditioned masking parameters are malformed")
    expected_policy = HweHistoryMaskingPolicy(
        recent_observations=recent_observations,  # type: ignore[arg-type]
        max_pinned_observations=max_pinned,
    )
    if expected_policy.policy_hash != value.get("history_policy_hash"):
        raise ValueError("HWE action-conditioned masking policy identity changed")
    supervised = value.get("supervised_message_indices")
    if supervised != [len(messages) - 1]:
        raise ValueError("HWE action-conditioned supervision must target only the final action")
    target = messages[-1]
    calls = target.get("tool_calls") if isinstance(target, Mapping) else None
    if target.get("role") != "assistant" or not isinstance(calls, list) or len(calls) != 1:
        raise ValueError("HWE action-conditioned target is not one assistant tool action")
    function = calls[0].get("function") if isinstance(calls[0], Mapping) else None
    if not isinstance(function, Mapping) or function.get("name") != value.get("target_action"):
        raise ValueError("HWE action-conditioned target action changed")
    target_sequence = value.get("target_sequence")
    if isinstance(target_sequence, bool) or not isinstance(target_sequence, int):
        raise ValueError("HWE action-conditioned target sequence is malformed")
    prior_actions = _action_projection(messages[:-1])
    prior_tools = [message for message in messages[:-1] if message.get("role") == "tool"]
    if len(prior_actions) != target_sequence or len(prior_tools) != target_sequence:
        raise ValueError("HWE action-conditioned history omits a prior action or observation")
    masked_sequences: list[int] = []
    for message in prior_tools:
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("HWE action-conditioned history has a non-text observation")
        if content.startswith("[verigym-hwe masked-observation"):
            match = _MASKED_MARKER.fullmatch(content)
            if match is None:
                raise ValueError("HWE action-conditioned masking marker is malformed")
            masked_sequences.append(int(match.group("sequence")))
    retained = ledger.get("retained_observation_sequences")
    recent = ledger.get("recent_observation_sequences")
    pinned = ledger.get("pinned_observation_sequences")
    masked = ledger.get("masked_observation_sequences")
    if any(
        not isinstance(sequences, list)
        or any(isinstance(item, bool) or not isinstance(item, int) for item in sequences)
        for sequences in (retained, recent, pinned, masked)
    ):
        raise ValueError("HWE action-conditioned observation sequence ledger is malformed")
    assert isinstance(retained, list)
    assert isinstance(recent, list)
    assert isinstance(pinned, list)
    assert isinstance(masked, list)
    if (
        masked_sequences != masked
        or set(retained) & set(masked)
        or set(retained) | set(masked) != set(range(target_sequence))
        or not set(recent).issubset(retained)
        or not set(pinned).issubset(retained)
    ):
        raise ValueError("HWE action-conditioned observation sequence ledger is inconsistent")
    token_count = value.get("token_count")
    if (
        isinstance(token_count, bool)
        or not isinstance(token_count, int)
        or token_count < 1
        or token_count > 32_768
        or token_count != ledger.get("total_tokens")
        or value.get("input_token_count") != ledger.get("input_tokens")
        or value.get("target_token_count") != ledger.get("target_tokens")
    ):
        raise ValueError("HWE action-conditioned token accounting is inconsistent")
    return HweActionConditionedSftExample.model_validate(value).model_dump(mode="json")


def build_hwe_action_conditioned_dataset_manifest(
    examples: Sequence[Mapping[str, Any]],
    *,
    required_trajectory_count: int | None = None,
) -> dict[str, Any]:
    """Seal an experimental dataset separately from current primary HWE bindings."""

    if not examples:
        raise ValueError("HWE action-conditioned dataset requires records")
    validated = [validate_hwe_action_conditioned_example(example) for example in examples]
    record_hashes = [record["record_hash"] for record in validated]
    if len(record_hashes) != len(set(record_hashes)):
        raise ValueError("HWE action-conditioned dataset contains duplicate records")
    task_ids = sorted({record["task_id"] for record in validated})
    transcript_hashes = sorted({record["source_transcript_hash"] for record in validated})
    policy_hashes = {record["history_policy_hash"] for record in validated}
    if len(policy_hashes) != 1:
        raise ValueError("HWE action-conditioned dataset cannot mix masking policies")
    if len(task_ids) != len(transcript_hashes):
        raise ValueError("HWE action-conditioned dataset requires one trajectory per task")
    if required_trajectory_count is not None and len(task_ids) != required_trajectory_count:
        raise ValueError("HWE action-conditioned dataset trajectory count is incomplete")
    base = {
        "schema_version": "1.0",
        "format_id": HWE_ACTION_CONDITIONED_DATASET_FORMAT,
        "record_count": len(validated),
        "trajectory_count": len(task_ids),
        "task_ids": task_ids,
        "source_transcript_hashes": transcript_hashes,
        "record_hashes": record_hashes,
        "history_policy_id": HWE_HISTORY_MASKING_POLICY_ID,
        "history_policy_hash": next(iter(policy_hashes)),
        "max_length": 32_768,
        "truncation": "error",
        "training_semantics": "next_action_conditioned_on_exact_masked_history",
        "primary_eligible": False,
        "experimental_action_conditioned": True,
        "counterfactual_next_action_validation": "not_run",
        "only_verifier_resolved": True,
        "only_infrastructure_valid": True,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "hpc_jobs_submitted": False,
    }
    sealed = {**base, "dataset_hash": content_hash(base)}
    return HweActionConditionedSftDatasetManifest.model_validate(sealed).model_dump(mode="json")


def summarize_hwe_masking_views(views: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not views:
        raise ValueError("HWE masking analysis requires at least one action view")
    ledgers = [view.get("history_ledger") for view in views]
    if any(not isinstance(ledger, Mapping) for ledger in ledgers):
        raise ValueError("HWE masking view omits its history ledger")
    typed_ledgers = [dict(ledger) for ledger in ledgers if isinstance(ledger, Mapping)]
    total_tokens = sorted(int(ledger["total_tokens"]) for ledger in typed_ledgers)
    input_tokens = sorted(int(ledger["input_tokens"]) for ledger in typed_ledgers)
    source_tokens = sorted(int(ledger["source_history_tokens"]) for ledger in typed_ledgers)
    return {
        "action_record_count": len(typed_ledgers),
        "max_source_history_tokens": source_tokens[-1],
        "max_input_tokens": input_tokens[-1],
        "max_total_tokens": total_tokens[-1],
        "p50_total_tokens": _percentile(total_tokens, 50),
        "p95_total_tokens": _percentile(total_tokens, 95),
        "all_within_32k": all(view.get("within_32k") is True for view in views),
        "max_masked_observations": max(
            len(ledger["masked_observation_sequences"]) for ledger in typed_ledgers
        ),
        "max_retained_observations": max(
            len(ledger["retained_observation_sequences"]) for ledger in typed_ledgers
        ),
        "max_pinned_observations": max(
            len(ledger["pinned_observation_sequences"]) for ledger in typed_ledgers
        ),
        "total_masked_source_observation_tokens": sum(
            int(ledger["masked_source_observation_tokens"]) for ledger in typed_ledgers
        ),
        "total_mask_marker_tokens": sum(
            int(ledger["mask_marker_tokens"]) for ledger in typed_ledgers
        ),
        "structural_action_preservation": "passed",
        "counterfactual_next_action_validation": "not_run",
    }


def _aligned_turns(
    messages: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
) -> list[_ObservationTurn]:
    turns: list[_ObservationTurn] = []
    pending: tuple[int, str, dict[str, Any], int] | None = None
    for index, message in enumerate(messages):
        if message.get("role") == "assistant" and message.get("tool_calls"):
            calls = message["tool_calls"]
            if pending is not None or not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("HWE masking requires one ordered tool call per turn")
            call = calls[0]
            function = call.get("function") if isinstance(call, Mapping) else None
            if not isinstance(function, Mapping):
                raise ValueError("HWE masking encountered a malformed action")
            name = function.get("name")
            arguments = function.get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, str):
                raise ValueError("HWE masking action lacks canonical arguments")
            parsed = json.loads(arguments)
            if not isinstance(parsed, dict):
                raise ValueError("HWE masking action arguments are not an object")
            pending = (len(turns), name, parsed, index)
        elif message.get("role") == "tool":
            if pending is None:
                raise ValueError("HWE masking tool observation lacks its action")
            sequence, action, arguments, assistant_index = pending
            if sequence >= len(outcomes):
                raise ValueError("HWE masking outcomes do not cover the transcript")
            outcome = outcomes[sequence]
            if outcome.get("sequence") != sequence or outcome.get("action") != action:
                raise ValueError("HWE masking outcome order changed")
            changed_paths = outcome.get("changed_paths")
            if not isinstance(changed_paths, list) or any(
                not isinstance(path, str) for path in changed_paths
            ):
                raise ValueError("HWE masking outcome changed paths are malformed")
            command = arguments.get("command") if action == "shell" else None
            compile_observed = isinstance(command, str) and bool(_COMPILE.search(command))
            simulation_observed = isinstance(command, str) and bool(_SIMULATION.search(command))
            before = outcome.get("workspace_epoch_before")
            after = outcome.get("workspace_epoch_after")
            exit_code = outcome.get("exit_code")
            if (
                isinstance(before, bool)
                or not isinstance(before, int)
                or isinstance(after, bool)
                or not isinstance(after, int)
                or (
                    exit_code is not None
                    and (isinstance(exit_code, bool) or not isinstance(exit_code, int))
                )
            ):
                raise ValueError("HWE masking outcome state is malformed")
            turns.append(
                _ObservationTurn(
                    sequence=sequence,
                    action=action,
                    assistant_index=assistant_index,
                    tool_index=index,
                    arguments=arguments,
                    workspace_epoch_before=before,
                    workspace_epoch_after=after,
                    changed_paths=tuple(changed_paths),
                    exit_code=exit_code,
                    compile_observed=compile_observed,
                    simulation_observed=simulation_observed,
                )
            )
            pending = None
    if pending is not None or len(turns) != len(outcomes):
        raise ValueError("HWE masking transcript and step outcomes are not exactly aligned")
    return turns


def _pinned_sequences(
    observations: Sequence[_ObservationTurn],
    *,
    current_epoch: int,
    limit: int,
) -> set[int]:
    categories: dict[str, _ObservationTurn] = {}
    for observation in observations:
        if observation.workspace_epoch_after != current_epoch:
            continue
        if observation.changed_paths or observation.action == "apply_patch":
            categories["mutation"] = observation
        if observation.action == "inspect_diff":
            categories["diff"] = observation
        if observation.exit_code not in {None, 0}:
            categories["failure"] = observation
        if observation.compile_observed:
            categories["compile_success" if observation.exit_code == 0 else "compile_failure"] = (
                observation
            )
        if observation.simulation_observed:
            categories[
                "simulation_success" if observation.exit_code == 0 else "simulation_failure"
            ] = observation
    unique = {turn.sequence: turn for turn in categories.values()}
    selected = sorted(unique.values(), key=lambda item: item.sequence)[-limit:]
    return {turn.sequence for turn in selected}


def _mask_marker(observation: _ObservationTurn, content: str, content_tokens: int) -> str:
    encoded = content.encode("utf-8")
    return (
        f"[verigym-hwe masked-observation rule={HWE_HISTORY_MASKING_MARKER_RULE_ID} "
        f"sequence={observation.sequence} action={observation.action} "
        f"workspace_epoch={observation.workspace_epoch_after} content_bytes={len(encoded)} "
        f"content_sha256={hashlib.sha256(encoded).hexdigest()} content_tokens={content_tokens} "
        "reason=outside_recent_window]"
    )


def _action_projection(messages: Sequence[Mapping[str, Any]]) -> list[Any]:
    return [
        copy.deepcopy(message.get("tool_calls"))
        for message in messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    ]


def _message_tokens(messages: Sequence[Mapping[str, Any]], counter: TokenCounter) -> int:
    serialized = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return counter.count(serialized)


def _percentile(values: Sequence[int], percentile: int) -> int:
    index = max(0, min(len(values) - 1, (len(values) * percentile + 99) // 100 - 1))
    return values[index]


def _require_hash_bindings(value: Mapping[str, Any], names: Sequence[str]) -> None:
    for name in names:
        _require_sha256(value.get(name), name)


def _require_sha256(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"HWE action-conditioned {name} must be SHA-256")


__all__ = [
    "HWE_ACTION_CONDITIONED_DATASET_FORMAT",
    "HWE_ACTION_CONDITIONED_SFT_FORMAT",
    "HWE_LOSSLESS_HISTORY_MARKER_RULE_ID",
    "HWE_LOSSLESS_HISTORY_POLICY_ID",
    "HWE_HISTORY_MASKING_MARKER_RULE_ID",
    "HWE_HISTORY_MASKING_POLICY_ID",
    "HWE_SELECTED_HISTORY_WINDOW",
    "HWE_MASKING_ANALYSIS_FORMAT",
    "HweHistoryMaskingPolicy",
    "build_hwe_action_conditioned_dataset_manifest",
    "derive_hwe_masked_history_views",
    "derive_hwe_lossless_history_view",
    "materialize_hwe_action_conditioned_examples",
    "summarize_hwe_masking_views",
    "validate_hwe_action_conditioned_example",
]
