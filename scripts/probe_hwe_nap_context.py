#!/usr/bin/env python3
"""Run one frozen HWE NAP comparison for bounded local-path diagnosis."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from verigym.hwe.local_models import (
    AdaptiveLocalQwenActionPredictor,
    LocalQwenActionPredictor,
    ParallelLocalQwenActionPredictor,
)
from verigym.hwe.nap import AnchorNapValidator
from verigym.hwe.training_ready import load_jsonl_records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--index", type=int, default=11, help="one-based historical row")
    parser.add_argument("--parallel", action="store_true")
    parser.add_argument("--adaptive", action="store_true")
    parser.add_argument(
        "--warmup-index",
        type=int,
        action="append",
        default=[],
        help="validate these earlier rows with the same predictor before the target row",
    )
    args = parser.parse_args()

    records = load_jsonl_records(args.source_root / "hwe-action-conditioned-sft.jsonl")
    if not 1 <= args.index <= len(records):
        raise ValueError("--index is outside the historical record set")
    record = records[args.index - 1]
    transcripts = {}
    for path in args.source_root.glob("runs/*/artifacts/codex_cli/hwe_teacher_transcript.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        transcripts[value["task_id"]] = value
    transcript = transcripts[record["task_id"]]
    target_index = record["history_ledger"]["target_message_index"]
    uncompressed = transcript["sft_messages"][:target_index]
    compressed = record["messages"][:-1]
    print(
        json.dumps(
            {
                "index": args.index,
                "task_id": record["task_id"],
                "target_sequence": record["target_sequence"],
                "uncompressed_messages": len(uncompressed),
                "compressed_messages": len(compressed),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    started = time.monotonic()
    predictor: (
        AdaptiveLocalQwenActionPredictor
        | LocalQwenActionPredictor
        | ParallelLocalQwenActionPredictor
    )
    batch_predictor: AdaptiveLocalQwenActionPredictor | ParallelLocalQwenActionPredictor | None = (
        None
    )
    if args.adaptive:
        devices = tuple(item.strip() for item in args.device.split(",") if item.strip())
        batch_predictor = AdaptiveLocalQwenActionPredictor(args.base_model, replica_devices=devices)
        predictor = batch_predictor
    elif args.parallel:
        devices = tuple(item.strip() for item in args.device.split(",") if item.strip())
        batch_predictor = ParallelLocalQwenActionPredictor(args.base_model, devices=devices)
        predictor = batch_predictor
    else:
        predictor = LocalQwenActionPredictor(args.base_model, device=args.device)
    print(f"model_ready_seconds={time.monotonic() - started:.2f}", flush=True)
    contexts = [uncompressed for _ in range(8)] + [compressed]
    temperatures = [0.7 for _ in range(8)] + [0.0]
    seeds = list(range(8)) + [0]
    if batch_predictor is not None:
        for warmup_index in args.warmup_index:
            if not 1 <= warmup_index <= len(records):
                raise ValueError("--warmup-index is outside the historical record set")
            warmup_record = records[warmup_index - 1]
            warmup_transcript = transcripts[warmup_record["task_id"]]
            warmup_target_index = warmup_record["history_ledger"]["target_message_index"]
            warmup_uncompressed = warmup_transcript["sft_messages"][:warmup_target_index]
            warmup_compressed = warmup_record["messages"][:-1]
            warmup_started = time.monotonic()
            warmup_result = AnchorNapValidator(batch_predictor).validate(
                warmup_uncompressed, warmup_compressed
            )
            print(
                json.dumps(
                    {
                        "warmup_index": warmup_index,
                        "target_sequence": warmup_record["target_sequence"],
                        "nap": warmup_result.as_dict(),
                        "seconds": round(time.monotonic() - warmup_started, 2),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        raw_outputs = batch_predictor.predict_actions(
            contexts, temperatures=temperatures, seeds=seeds
        )
    else:
        raw_outputs = [
            predictor.predict_action(context, temperature=temperature, seed=seed)
            for context, temperature, seed in zip(contexts, temperatures, seeds, strict=True)
        ]
    for output_index, raw_output in enumerate(raw_outputs):
        print(json.dumps({"output_index": output_index, "raw_output": raw_output}), flush=True)

    class StaticPredictor:
        def predict_actions(
            self,
            messages: Sequence[Sequence[Mapping[str, Any]]],
            *,
            temperatures: Sequence[float],
            seeds: Sequence[int],
        ) -> list[str]:
            del messages, temperatures, seeds
            return raw_outputs

    result = AnchorNapValidator(StaticPredictor()).validate(  # type: ignore[arg-type]
        uncompressed, compressed
    )
    print(json.dumps(result.as_dict(), sort_keys=True), flush=True)
    print(f"total_seconds={time.monotonic() - started:.2f}", flush=True)
    close = getattr(predictor, "close", None)
    if callable(close):
        close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
