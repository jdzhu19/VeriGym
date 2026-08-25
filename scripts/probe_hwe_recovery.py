#!/usr/bin/env python3
"""Run the frozen NAP gate across one historical row and its recovery policies."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from verigym.hwe.history_masking import (
    HweHistoryMaskingPolicy,
    derive_hwe_lossless_history_view,
    derive_hwe_masked_history_views,
)
from verigym.hwe.local_models import (
    AdaptiveLocalQwenActionPredictor,
    ParallelLocalQwenActionPredictor,
)
from verigym.hwe.nap import AnchorNapValidator
from verigym.hwe.observation import TiktokenO200kCounter
from verigym.hwe.training_ready import load_jsonl_records

RECOVERY_POLICIES = ((2, 1), (4, 2), (8, 4), (16, 4))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--devices", required=True)
    parser.add_argument("--index", type=int, required=True, help="one-based historical row")
    parser.add_argument(
        "--adaptive",
        action="store_true",
        help="use the seven-card adaptive replica/sharded predictor",
    )
    args = parser.parse_args()

    records = load_jsonl_records(args.source_root / "hwe-action-conditioned-sft.jsonl")
    record = records[args.index - 1]
    transcripts = {}
    for path in args.source_root.glob("runs/*/artifacts/codex_cli/hwe_teacher_transcript.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        transcripts[value["task_id"]] = value
    transcript = transcripts[record["task_id"]]
    target_index = record["history_ledger"]["target_message_index"]
    uncompressed = transcript["sft_messages"][:target_index]
    candidates: list[tuple[str, list[dict[str, object]], bool, int | None]] = [
        (
            "historical",
            record["messages"][:-1],
            int(record["history_ledger"]["total_tokens"]) <= 32_768,
            record["history_ledger"]["total_tokens"],
        )
    ]
    counter = TiktokenO200kCounter()
    lossless = derive_hwe_lossless_history_view(
        transcript["sft_messages"],
        step_outcomes=transcript["compaction_manifest"]["step_outcomes"],
        counter=counter,
        target_sequence=record["target_sequence"],
    )
    if lossless["within_32k"] is True:
        candidates.append(
            (
                "lossless_under_32k",
                lossless["messages"][:-1],
                True,
                lossless["history_ledger"]["total_tokens"],
            )
        )
    for recent, pinned in RECOVERY_POLICIES:
        policy = HweHistoryMaskingPolicy(recent_observations=recent, max_pinned_observations=pinned)
        views = derive_hwe_masked_history_views(
            transcript["sft_messages"],
            step_outcomes=transcript["compaction_manifest"]["step_outcomes"],
            counter=counter,
            policy=policy,
        )
        view = next(
            item
            for item in views
            if item["history_ledger"]["target_sequence"] == record["target_sequence"]
        )
        candidates.append(
            (
                f"recent={recent},pinned={pinned}",
                view["messages"][:-1],
                bool(view["within_32k"]),
                view["history_ledger"]["total_tokens"],
            )
        )

    devices = tuple(item.strip() for item in args.devices.split(",") if item.strip())
    predictor = (
        AdaptiveLocalQwenActionPredictor(args.base_model, replica_devices=devices)
        if args.adaptive
        else ParallelLocalQwenActionPredictor(args.base_model, devices=devices)
    )
    validator = AnchorNapValidator(predictor)
    for label, compressed, within_32k, token_count in candidates:
        started = time.monotonic()
        result = validator.validate(uncompressed, compressed)
        print(
            json.dumps(
                {
                    "label": label,
                    "within_32k": within_32k,
                    "token_count": token_count,
                    "nap": result.as_dict(),
                    "seconds": round(time.monotonic() - started, 2),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    predictor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
