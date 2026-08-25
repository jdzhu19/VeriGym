#!/usr/bin/env python3
"""Probe one-observation HWE masks against the frozen sharded NAP predictor."""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from verigym.hwe.history_masking import (
    _aligned_turns,
    _mask_marker,
    _message_tokens,
)
from verigym.hwe.local_models import SubprocessLocalQwenActionPredictor
from verigym.hwe.nap import AnchorNapValidator
from verigym.hwe.observation import TiktokenO200kCounter
from verigym.hwe.training_ready import load_jsonl_records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--index", type=int, required=True, help="one-based historical row")
    args = parser.parse_args()

    records = load_jsonl_records(args.source_root / "hwe-action-conditioned-sft.jsonl")
    record = records[args.index - 1]
    transcripts: dict[str, dict[str, Any]] = {}
    for path in args.source_root.glob("runs/*/artifacts/codex_cli/hwe_teacher_transcript.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        transcripts[value["task_id"]] = value
    transcript = transcripts[record["task_id"]]
    source_messages = transcript["sft_messages"]
    target_index = record["history_ledger"]["target_message_index"]
    source_history = [copy.deepcopy(message) for message in source_messages[:target_index]]
    target_message = copy.deepcopy(source_messages[target_index])
    turns = _aligned_turns(source_messages, transcript["compaction_manifest"]["step_outcomes"])
    prior_turns = [turn for turn in turns if turn.sequence < record["target_sequence"]]
    counter = TiktokenO200kCounter()

    candidates: list[tuple[int, int, list[dict[str, Any]], int]] = []
    for observation in prior_turns:
        messages = [copy.deepcopy(message) for message in source_history]
        content = messages[observation.tool_index].get("content")
        if not isinstance(content, str):
            raise ValueError("HWE observation content must be textual")
        source_tokens = counter.count(content)
        messages[observation.tool_index]["content"] = _mask_marker(
            observation, content, source_tokens
        )
        total_tokens = _message_tokens([*messages, target_message], counter)
        if total_tokens <= 32_768:
            marker_tokens = counter.count(messages[observation.tool_index]["content"])
            candidates.append(
                (observation.sequence, source_tokens - marker_tokens, messages, total_tokens)
            )
    candidates.sort(key=lambda item: (-item[1], item[0]))
    print(
        json.dumps(
            {
                "index": args.index,
                "task_id": record["task_id"],
                "target_sequence": record["target_sequence"],
                "source_total_tokens": _message_tokens([*source_history, target_message], counter),
                "eligible_single_observation_masks": len(candidates),
            },
            sort_keys=True,
        ),
        flush=True,
    )

    predictor = SubprocessLocalQwenActionPredictor(args.base_model, device=args.device)
    validator = AnchorNapValidator(predictor)
    started = time.monotonic()
    try:
        for sequence, savings, messages, total_tokens in candidates:
            result = validator.validate(source_history, messages)
            print(
                json.dumps(
                    {
                        "sequence": sequence,
                        "token_savings": savings,
                        "total_tokens": total_tokens,
                        "nap": result.as_dict(),
                        "elapsed_seconds": round(time.monotonic() - started, 2),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        predictor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
