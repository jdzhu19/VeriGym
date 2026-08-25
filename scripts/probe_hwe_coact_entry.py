#!/usr/bin/env python3
"""Run a bounded CoACT observation-entry compression probe for one HWE transcript.

The probe intentionally stops after one target observation.  It uses the production CoACT
candidate, evidence, and frozen NAP gates, but does not write a training example or start SFT.
Only hashes, gate decisions, and aggregate token counts are persisted.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.coact import (
    COACT_MAX_CANDIDATES,
    build_coact_checkpoint_lock,
    compress_hwe_trajectory,
)
from verigym.hwe.local_models import AdaptiveLocalQwenActionPredictor, LocalCoactGenerator
from verigym.hwe.nap import AnchorNapValidator
from verigym.hwe.observation import TiktokenO200kCounter
from verigym.hwe.trajectory import validate_hwe_teacher_transcript


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = _run(arguments)
    except KeyboardInterrupt:
        result = {
            "pilot_ready": False,
            "hpc_jobs_submitted": False,
            "error_type": "KeyboardInterrupt",
            "error": "bounded CoACT pilot interrupted",
        }
        _write_result(arguments.output, result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - exercised by real local-model failures
        result = {
            "pilot_ready": False,
            "hpc_jobs_submitted": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        _write_result(arguments.output, result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 2
    _write_result(arguments.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--coact-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--target-sequence", type=int, default=32)
    parser.add_argument("--coact-device", default="cuda:0")
    parser.add_argument(
        "--nap-devices",
        required=True,
        help="comma-separated CUDA devices reserved for the frozen Qwen NAP predictor",
    )
    return parser


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.target_sequence < 0:
        raise ValueError("target sequence must be non-negative")
    nap_devices = tuple(item.strip() for item in arguments.nap_devices.split(",") if item.strip())
    if len(nap_devices) < 2 or len(set(nap_devices)) != len(nap_devices):
        raise ValueError("CoACT pilot requires at least two distinct NAP devices")
    transcript = _load_transcript(arguments.source_root, arguments.task_id)
    prefix, prefix_end = _prefix_transcript(transcript, arguments.target_sequence)
    task_goal = _public_task_goal(transcript)
    counter = TiktokenO200kCounter()
    checkpoint_lock = build_coact_checkpoint_lock(arguments.coact_checkpoint)
    generator = LocalCoactGenerator(arguments.coact_checkpoint, device=arguments.coact_device)
    predictor = AdaptiveLocalQwenActionPredictor(
        arguments.base_model,
        replica_devices=nap_devices,
    )
    try:
        compressed, manifest = compress_hwe_trajectory(
            prefix,
            task_goal=task_goal,
            counter=counter,
            generator=generator,
            nap_validator=AnchorNapValidator(predictor),
            max_candidates=COACT_MAX_CANDIDATES,
        )
        result = _summarize(
            transcript=transcript,
            prefix=prefix,
            compressed=compressed,
            manifest=manifest,
            checkpoint_lock=checkpoint_lock,
            predictor=predictor,
            target_sequence=arguments.target_sequence,
            prefix_end=prefix_end,
            counter=counter,
            nap_devices=nap_devices,
            coact_device=arguments.coact_device,
        )
    finally:
        predictor.close()
    return result


def _load_transcript(source_root: Path, task_id: str) -> dict[str, Any]:
    matches: list[Path] = []
    for path in sorted(source_root.glob("runs/*/artifacts/codex_cli/hwe_teacher_transcript.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("task_id") == task_id:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one transcript for task {task_id!r}")
    value = validate_hwe_teacher_transcript(json.loads(matches[0].read_text(encoding="utf-8")))
    return dict(value)


def _prefix_transcript(
    transcript: Mapping[str, Any], target_sequence: int
) -> tuple[dict[str, Any], int]:
    messages = transcript.get("sft_messages")
    manifest = transcript.get("compaction_manifest")
    outcomes = manifest.get("step_outcomes") if isinstance(manifest, Mapping) else None
    if not isinstance(messages, list) or not isinstance(outcomes, list):
        raise ValueError("transcript lacks ordered SFT messages and step outcomes")
    tool_count = 0
    end_index: int | None = None
    for index, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        if tool_count == target_sequence:
            end_index = index
            break
        tool_count += 1
    if end_index is None:
        raise ValueError(f"target sequence {target_sequence} is not present")
    if len(outcomes) <= target_sequence:
        raise ValueError("target sequence has no matching normalized outcome")
    prefix = copy.deepcopy(dict(transcript))
    prefix["sft_messages"] = copy.deepcopy(messages[: end_index + 1])
    prefix["compaction_manifest"] = {
        **dict(manifest),
        "step_outcomes": copy.deepcopy(outcomes[: target_sequence + 1]),
    }
    return prefix, end_index


def _summarize(
    *,
    transcript: Mapping[str, Any],
    prefix: Mapping[str, Any],
    compressed: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    checkpoint_lock: Mapping[str, Any],
    predictor: AdaptiveLocalQwenActionPredictor,
    target_sequence: int,
    prefix_end: int,
    counter: TiktokenO200kCounter,
    nap_devices: Sequence[str],
    coact_device: str,
) -> dict[str, Any]:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("CoACT manifest has no entry audit list")
    target = next(
        (entry for entry in entries if entry.get("sequence") == target_sequence),
        None,
    )
    if not isinstance(target, Mapping):
        raise ValueError("CoACT manifest omitted the target entry")
    audits = target.get("candidate_audits")
    if not isinstance(audits, list):
        raise ValueError("target entry has no candidate audits")
    accepted = [audit for audit in audits if audit.get("accepted") is True]
    nap_passed = [
        audit
        for audit in accepted
        if isinstance(audit.get("nap"), Mapping) and audit["nap"].get("passed") is True
    ]
    reasons = Counter(str(audit.get("reason")) for audit in audits if isinstance(audit, Mapping))
    source_messages = prefix.get("sft_messages")
    if not isinstance(source_messages, list):
        raise ValueError("prefix transcript has no source messages")
    source_tokens = _message_tokens(source_messages, counter)
    compressed_tokens = _message_tokens(compressed, counter)
    entry_rows = [entry for entry in entries if isinstance(entry, Mapping)]
    changed_entries = [entry for entry in entry_rows if entry.get("changed") is True]
    changed_nap_failures = [
        entry
        for entry in changed_entries
        if any(
            audit.get("accepted") is not True
            or not isinstance(audit.get("nap"), Mapping)
            or audit["nap"].get("passed") is not True
            for audit in entry.get("candidate_audits", [])
            if isinstance(audit, Mapping)
            and audit.get("candidate_hash") == entry.get("selected_sha256")
        )
    ]
    result_base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_coact_entry_pilot_v1",
        "pilot_ready": True,
        "training_ready": False,
        "hpc_jobs_submitted": False,
        "task_id": transcript.get("task_id"),
        "target_sequence": target_sequence,
        "prefix_message_end_index": prefix_end,
        "prefix_observation_count": len(entry_rows),
        "source_transcript_hash": transcript.get("transcript_hash"),
        "source_prefix_tokens": source_tokens,
        "compressed_prefix_tokens": compressed_tokens,
        "token_delta": compressed_tokens - source_tokens,
        "within_64k_prefix": compressed_tokens <= 65_536,
        "truncation": "error",
        "target_entry": dict(target),
        "target_candidate_count": len(audits),
        "target_accepted_candidate_count": len(accepted),
        "target_nap_passed_candidate_count": len(nap_passed),
        "target_rejection_reasons": dict(sorted(reasons.items())),
        "changed_entry_count": len(changed_entries),
        "fallback_entry_count": sum(1 for entry in entry_rows if entry.get("fallback") is True),
        "changed_entry_nap_failures": len(changed_nap_failures),
        "causal_validation": manifest.get("causal_validation"),
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "coact_device": coact_device,
        "nap_devices": list(nap_devices),
        "nap_runtime": predictor.runtime_summary(),
        "coact_checkpoint_lock": dict(checkpoint_lock),
        "compression_manifest": dict(manifest),
    }
    result_base["result_hash"] = content_hash(result_base)
    return result_base


def _public_task_goal(transcript: Mapping[str, Any]) -> str:
    messages = transcript.get("sft_messages")
    if not isinstance(messages, list):
        raise ValueError("transcript lacks SFT messages")
    for message in messages:
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return str(message["content"])
    raise ValueError("transcript lacks public task goal")


def _message_tokens(messages: Sequence[Mapping[str, Any]], counter: TiktokenO200kCounter) -> int:
    serialized = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return counter.count(serialized)


def _write_result(output: Path, result: Mapping[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    atomic_dump_json(output / "pilot-result.json", dict(result))


if __name__ == "__main__":
    raise SystemExit(main())
