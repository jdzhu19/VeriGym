"""Training-ready gates for the existing Complexity-Trap/action-conditioned arm."""

from __future__ import annotations

import copy
import json
import os
import stat
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash, hash_bytes
from verigym.hwe.history_masking import (
    HweHistoryMaskingPolicy,
    derive_hwe_lossless_history_view,
    derive_hwe_masked_history_views,
    validate_hwe_action_conditioned_example,
)
from verigym.hwe.nap import AnchorNapValidator, canonical_action_hash
from verigym.hwe.observation import TokenCounter
from verigym.schemas.hwe_training import (
    HweTrainingReadyActionConditionedExample,
    HweTrainingReadyActionConditionedManifest,
)

READY_EXAMPLE_FORMAT = "verigym_hwe_training_ready_action_conditioned_sft_v1"
READY_DATASET_FORMAT = "verigym_hwe_training_ready_action_conditioned_sft_dataset_v1"
READY_ELIGIBILITY = "training_ready_action_conditioned"
RECOVERY_POLICIES = ((2, 1), (4, 2), (8, 4), (16, 4))


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    """Read a bounded JSONL file without following a symlink."""

    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("HWE JSONL input must be a regular file")
    if metadata.st_size > 512 * 1024 * 1024:
        raise ValueError("HWE JSONL input exceeds its safety bound")
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            raise ValueError("HWE JSONL input contains an empty line")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("HWE JSONL rows must be objects")
        records.append(value)
    return records


def old_action_conditioned_identity(
    records: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Freeze the historical v1 identity before producing any new version."""

    record_hashes = [record.get("record_hash") for record in records]
    expected_hashes = manifest.get("record_hashes")
    if not isinstance(expected_hashes, list) or record_hashes != expected_hashes:
        raise ValueError("historical action-conditioned record hashes changed")
    if manifest.get("record_count") != 419 or len(records) != 419:
        raise ValueError("historical action-conditioned arm must contain 419 records")
    return {
        "dataset_hash": manifest.get("dataset_hash"),
        "record_hashes": list(expected_hashes),
        "record_count": len(records),
        "jsonl_sha256": None,
    }


def build_training_ready_action_conditioned_examples(
    records: Sequence[Mapping[str, Any]],
    *,
    transcripts: Mapping[str, Mapping[str, Any]],
    nap_validator: AnchorNapValidator,
    counter: TokenCounter,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """NAP-gate all old rows and adaptively restore history only in the new version."""

    if len(records) != 419:
        raise ValueError("training-ready action-conditioned derivation requires 419 old records")
    validated_old = [validate_hwe_action_conditioned_example(record) for record in records]
    old_hashes = [record["record_hash"] for record in validated_old]
    if len(set(old_hashes)) != len(old_hashes):
        raise ValueError("historical action-conditioned records are not unique")
    output: list[dict[str, Any]] = []
    recovery_counts: Counter[str] = Counter()
    scores: list[float] = []
    for old in validated_old:
        task_id = old["task_id"]
        transcript = transcripts.get(task_id)
        if transcript is None:
            raise ValueError(f"missing source transcript for {task_id}")
        source_messages = transcript.get("sft_messages")
        if not isinstance(source_messages, list):
            raise ValueError("source transcript omits sft_messages")
        ledger = old["history_ledger"]
        target_index = ledger["target_message_index"]
        if not isinstance(target_index, int) or target_index < 2:
            raise ValueError("old action-conditioned target index is malformed")
        uncompressed = [copy.deepcopy(message) for message in source_messages[:target_index]]
        compressed = [copy.deepcopy(message) for message in old["messages"][:-1]]
        first = nap_validator.validate(uncompressed, compressed)
        selected = first
        selected_messages = compressed
        selected_ledger = ledger
        recovery = {
            "kind": "original_historical_m1_p1",
            "selected_recent_observations": ledger["recent_observations"],
            "selected_max_pinned_observations": ledger["max_pinned_observations"],
            "attempts": [{"policy": "historical", "nap": first.as_dict()}],
        }
        if not first.passed:
            recovery["kind"] = "adaptive_history_recovery"
            recovery["attempts"] = []
            lossless_view = derive_hwe_lossless_history_view(
                source_messages,
                step_outcomes=transcript["compaction_manifest"]["step_outcomes"],
                counter=counter,
                target_sequence=old["target_sequence"],
            )
            if lossless_view["within_32k"] is True:
                lossless_messages = lossless_view["messages"][:-1]
                lossless_nap = nap_validator.validate(uncompressed, lossless_messages)
                recovery["attempts"].append(
                    {
                        "policy": "lossless_under_32k",
                        "token_count": lossless_view["history_ledger"]["total_tokens"],
                        "nap": lossless_nap.as_dict(),
                    }
                )
                if lossless_nap.passed:
                    selected = lossless_nap
                    selected_messages = lossless_messages
                    selected_ledger = lossless_view["history_ledger"]
                    recovery["kind"] = "lossless_full_history_under_32k"
                    recovery["selected_recent_observations"] = selected_ledger[
                        "recent_observations"
                    ]
                    recovery["selected_max_pinned_observations"] = selected_ledger[
                        "max_pinned_observations"
                    ]
            for recent, pinned in RECOVERY_POLICIES:
                if selected.passed:
                    break
                policy = HweHistoryMaskingPolicy(
                    recent_observations=recent,  # type: ignore[arg-type]
                    max_pinned_observations=pinned,  # type: ignore[arg-type]
                )
                views = derive_hwe_masked_history_views(
                    source_messages,
                    step_outcomes=transcript["compaction_manifest"]["step_outcomes"],
                    counter=counter,
                    policy=policy,
                )
                view = next(
                    item
                    for item in views
                    if item["history_ledger"]["target_sequence"] == old["target_sequence"]
                )
                attempt_messages = view["messages"][:-1]
                attempt_nap = nap_validator.validate(uncompressed, attempt_messages)
                recovery["attempts"].append(
                    {
                        "recent_observations": recent,
                        "max_pinned_observations": pinned,
                        "token_count": view["history_ledger"]["total_tokens"],
                        "nap": attempt_nap.as_dict(),
                    }
                )
                if attempt_nap.passed and view["within_32k"] is True:
                    selected = attempt_nap
                    selected_messages = attempt_messages
                    selected_ledger = view["history_ledger"]
                    recovery["selected_recent_observations"] = recent
                    recovery["selected_max_pinned_observations"] = pinned
                    break
            if not selected.passed:
                raise ValueError(
                    f"NAP and 32K recovery failed for {task_id} sequence {old['target_sequence']}"
                )
        recovery_counts[str(recovery["kind"])] += 1
        scores.append(selected.top_k_score)
        base = dict(old)
        base.update(
            {
                "format_id": READY_EXAMPLE_FORMAT,
                "training_eligibility": READY_ELIGIBILITY,
                "counterfactual_next_action_validation": "passed",
                "messages": [*selected_messages, copy.deepcopy(source_messages[target_index])]
                if selected_messages[-1].get("role") != "assistant"
                else [*selected_messages],
                "history_policy_id": selected_ledger["policy_id"],
                "history_policy_hash": selected_ledger["policy_hash"],
                "history_ledger": selected_ledger,
                "input_token_count": selected_ledger["input_tokens"],
                "target_token_count": selected_ledger["target_tokens"],
                "token_count": selected_ledger["total_tokens"],
                "nap_validation": selected.as_dict(),
                "recovery": recovery,
            }
        )
        # The selected view already includes the target assistant message.  The branch above is
        # kept explicit so malformed custom test inputs cannot silently drop a target action.
        if base["messages"][-1] != source_messages[target_index]:
            raise ValueError("training-ready action-conditioned target action changed")
        layer_pairs = {
            "target_sequence": (base["target_sequence"], selected_ledger["target_sequence"]),
            "target_action": (base["target_action"], selected_ledger["target_action"]),
            "history_policy_hash": (
                base["history_policy_hash"],
                selected_ledger["policy_hash"],
            ),
            "input_token_count": (base["input_token_count"], selected_ledger["input_tokens"]),
            "target_token_count": (
                base["target_token_count"],
                selected_ledger["target_tokens"],
            ),
            "token_count": (base["token_count"], selected_ledger["total_tokens"]),
            "supervised_message_indices": (
                base["supervised_message_indices"],
                [len(base["messages"]) - 1],
            ),
        }
        mismatches = {name: pair for name, pair in layer_pairs.items() if pair[0] != pair[1]}
        if mismatches:
            raise ValueError(f"training-ready record layers disagree: {mismatches}")
        base.pop("record_hash", None)
        ready = HweTrainingReadyActionConditionedExample.model_validate(
            {**base, "record_hash": content_hash(base)}
        ).model_dump(mode="json")
        output.append(ready)
        if progress is not None:
            progress(len(output), len(records))
    if len(output) != 419 or not all(
        item["counterfactual_next_action_validation"] == "passed" for item in output
    ):
        raise ValueError("training-ready action-conditioned derivation is incomplete")
    summary = {
        "format_id": "verigym_hwe_training_ready_action_conditioned_quality_v1",
        "record_count": len(output),
        "passed_count": len(output),
        "recovery_counts": dict(sorted(recovery_counts.items())),
        "nap_score_min": min(scores),
        "nap_score_p50": _percentile(scores, 50),
        "nap_score_p95": _percentile(scores, 95),
        "nap_score_max": max(scores),
        "nap_threshold": 0.6,
        "all_tokens_within_32k": all(item["token_count"] <= 32_768 for item in output),
        "training_ready": True,
        "hpc_jobs_submitted": False,
    }
    return output, {**summary, "quality_hash": content_hash(summary)}


def build_training_ready_action_conditioned_manifest(
    examples: Sequence[Mapping[str, Any]],
    *,
    old_dataset_hash: str,
    old_record_hashes: Sequence[str],
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal the new arm while retaining an explicit pointer to the old frozen identity."""

    if len(examples) != 419 or len(old_record_hashes) != 419:
        raise ValueError("training-ready action-conditioned manifest requires 419 records")
    tasks = sorted({str(example["task_id"]) for example in examples})
    if len(tasks) != 8:
        raise ValueError("training-ready action-conditioned arm requires eight trajectories")
    record_hashes = [str(example["record_hash"]) for example in examples]
    action_hashes = [
        canonical_action_hash(
            {
                "name": example["target_action"],
                "arguments": example["messages"][-1]["tool_calls"][0]["function"]["arguments"],
            }
        )
        for example in examples
    ]
    base = {
        "schema_version": "1.0",
        "format_id": READY_DATASET_FORMAT,
        "record_count": 419,
        "trajectory_count": 8,
        "task_ids": tasks,
        "source_transcript_hashes": sorted(
            {str(item["source_transcript_hash"]) for item in examples}
        ),
        "record_hashes": record_hashes,
        "history_policy_id": _manifest_history_policy_id(examples),
        "history_policy_hash": content_hash(
            {
                "history_policy_hashes": sorted(
                    {str(item["history_policy_hash"]) for item in examples}
                )
            }
        ),
        "max_length": 32_768,
        "truncation": "error",
        "training_semantics": "next_action_conditioned_on_exact_masked_history",
        "primary_eligible": False,
        "experimental_action_conditioned": True,
        "counterfactual_next_action_validation": "passed",
        "only_verifier_resolved": True,
        "only_infrastructure_valid": True,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "hpc_jobs_submitted": False,
        "canonical_action_hashes": sorted(action_hashes),
        "old_dataset_hash": old_dataset_hash,
        "old_record_hashes": list(old_record_hashes),
        "nap_validation": dict(quality),
        "training_ready": True,
    }
    return HweTrainingReadyActionConditionedManifest.model_validate(
        {**base, "dataset_hash": content_hash(base)}
    ).model_dump(mode="json")


def freeze_old_jsonl_identity(records_path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Include the old JSONL byte hash in a quality report without editing the source."""

    identity = old_action_conditioned_identity(load_jsonl_records(records_path), manifest)
    identity["jsonl_sha256"] = hash_bytes(records_path.read_bytes())
    return identity


def _percentile(values: Sequence[float], percentile: int) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (len(ordered) * percentile + 99) // 100 - 1))
    return ordered[index]


def _manifest_history_policy_id(examples: Sequence[Mapping[str, Any]]) -> str:
    policy_ids = sorted({str(item["history_policy_id"]) for item in examples})
    if len(policy_ids) == 1:
        return policy_ids[0]
    return "mixed"


__all__ = [
    "READY_DATASET_FORMAT",
    "READY_ELIGIBILITY",
    "READY_EXAMPLE_FORMAT",
    "RECOVERY_POLICIES",
    "build_training_ready_action_conditioned_examples",
    "build_training_ready_action_conditioned_manifest",
    "freeze_old_jsonl_identity",
    "load_jsonl_records",
    "old_action_conditioned_identity",
]
