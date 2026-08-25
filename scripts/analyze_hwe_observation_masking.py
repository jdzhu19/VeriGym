#!/usr/bin/env python3
"""Analyze deterministic rolling observation masking on sealed HWE transcripts."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any, Literal, cast

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.history_masking import (
    HWE_MASKING_ANALYSIS_FORMAT,
    HweHistoryMaskingPolicy,
    derive_hwe_masked_history_views,
    summarize_hwe_masking_views,
)
from verigym.hwe.observation import TiktokenO200kCounter
from verigym.hwe.trajectory import validate_hwe_teacher_transcript
from verigym.schemas.hwe import HweObservationMaskingAnalysis

_MAX_TRANSCRIPT_BYTES = 32 * 1024 * 1024
_MAX_JSON_DEPTH = 128


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", action="append", type=Path, required=True)
    parser.add_argument(
        "--windows",
        nargs="+",
        type=int,
        default=[8, 10, 16],
        help="rolling observation windows to compare (supported: 8, 10, 16)",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze_transcripts(args.transcript, windows=args.windows)
    atomic_dump_json(args.output, report)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


def analyze_transcripts(transcript_paths: list[Path], *, windows: list[int]) -> dict[str, Any]:
    if not transcript_paths:
        raise ValueError("masking analysis requires HWE transcripts")
    if not windows or len(windows) != len(set(windows)):
        raise ValueError("masking analysis windows must be non-empty and unique")
    policies = [_policy(window) for window in windows]
    counter = TiktokenO200kCounter()
    trajectories: list[dict[str, Any]] = []
    seen_transcripts: set[str] = set()
    for path in transcript_paths:
        transcript = validate_hwe_teacher_transcript(_read_json_object(path))
        transcript_hash = transcript["transcript_hash"]
        if transcript_hash in seen_transcripts:
            raise ValueError("masking analysis received a duplicate transcript")
        seen_transcripts.add(transcript_hash)
        manifest = transcript.get("compaction_manifest")
        messages = transcript.get("sft_messages")
        if not isinstance(manifest, dict) or not isinstance(messages, list):
            raise ValueError("masking analysis source omits compact layers")
        outcomes = manifest.get("step_outcomes")
        if not isinstance(outcomes, list):
            raise ValueError("masking analysis requires HWE v2 step outcomes")
        analyses: list[dict[str, Any]] = []
        for policy in policies:
            views = derive_hwe_masked_history_views(
                messages,
                step_outcomes=outcomes,
                counter=counter,
                policy=policy,
            )
            analyses.append(
                {
                    "recent_observations": policy.recent_observations,
                    "history_policy_hash": policy.policy_hash,
                    **summarize_hwe_masking_views(views),
                }
            )
        metrics = transcript.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError("masking analysis source omits metrics")
        trajectories.append(
            {
                "task_id": transcript["task_id"],
                "source_transcript_hash": transcript_hash,
                "source_sft_tokens": metrics["sft_total_tokens"],
                "source_sft_bucket": transcript["sft_bucket"],
                "source_primary_eligible": transcript["primary_eligible"],
                "window_analyses": analyses,
            }
        )
    trajectories.sort(key=lambda item: item["task_id"])
    summary_by_window: list[dict[str, Any]] = []
    for policy in policies:
        results = [
            next(
                analysis
                for analysis in trajectory["window_analyses"]
                if analysis["recent_observations"] == policy.recent_observations
            )
            for trajectory in trajectories
        ]
        summary_by_window.append(
            {
                "recent_observations": policy.recent_observations,
                "history_policy_hash": policy.policy_hash,
                "max_input_tokens": max(result["max_input_tokens"] for result in results),
                "max_total_tokens": max(result["max_total_tokens"] for result in results),
                "all_trajectories_within_32k": all(
                    result["all_within_32k"] is True for result in results
                ),
                "trajectory_count": len(results),
            }
        )
    safe_windows = [
        result["recent_observations"]
        for result in summary_by_window
        if result["all_trajectories_within_32k"] is True
    ]
    selected_window = max(safe_windows) if safe_windows else None
    base = {
        "schema_version": "1.0",
        "format_id": HWE_MASKING_ANALYSIS_FORMAT,
        "analysis_scope": "sealed_successful_hwe_pilot_transcripts",
        "trajectory_count": len(trajectories),
        "tested_windows": windows,
        "selection_rule": "largest_tested_window_with_all_target_contexts_at_or_below_32768",
        "selected_window": selected_window,
        "tokenizer_id": counter.tokenizer_id,
        "tokenizer_hash": counter.tokenizer_hash,
        "trajectories": trajectories,
        "summary_by_window": summary_by_window,
        "structural_action_preservation": "passed",
        "counterfactual_next_action_validation": "not_run",
        "live_rollout_masking_applied": False,
        "derivation_only": True,
        "source_transcripts_modified": False,
        "existing_primary_reclassified": False,
        "pilot_is_benchmark_score": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "hpc_jobs_submitted": False,
    }
    sealed = {**base, "analysis_hash": content_hash(base)}
    return HweObservationMaskingAnalysis.model_validate(sealed).model_dump(mode="json")


def _read_json_object(path: Path) -> dict[str, Any]:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("masking analysis transcript must be a regular file")
    if metadata.st_size > _MAX_TRANSCRIPT_BYTES:
        raise ValueError("masking analysis transcript is oversized")
    raw = path.read_bytes()
    if len(raw) != metadata.st_size:
        raise ValueError("masking analysis transcript changed while reading")
    payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    _check_depth(payload)
    if not isinstance(payload, dict):
        raise ValueError("masking analysis transcript must be a JSON object")
    return payload


def _policy(window: int) -> HweHistoryMaskingPolicy:
    if window not in {8, 10, 16}:
        raise ValueError("masking analysis supports only M=8, M=10, or M=16")
    return HweHistoryMaskingPolicy(recent_observations=cast(Literal[8, 10, 16], window))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("masking analysis transcript contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"masking analysis transcript contains invalid JSON constant {value}")


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("masking analysis transcript exceeds its nesting-depth bound")
    if isinstance(value, dict):
        for item in value.values():
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1)


if __name__ == "__main__":
    main()
