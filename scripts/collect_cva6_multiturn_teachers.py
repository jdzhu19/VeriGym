#!/usr/bin/env python3
"""Collect eight verified multi-turn CVA6 teacher trajectories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from transformers import AutoTokenizer
from verigym_training_reference.cva6_teacher_collection import (
    collect_cva6_teacher_trajectories,
)

from verigym.core.errors import ConfigurationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen Claude-first teacher campaign.")
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--campaign-id",
        default="cva6-verified-multiturn-teachers-v1",
        help="Frozen public campaign identifier; use a new value after an invalidated batch.",
    )
    parser.add_argument("--max-process-time-s", type=int, default=1800)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    tokenizer = AutoTokenizer.from_pretrained(
        arguments.tokenizer.expanduser().resolve(strict=True), local_files_only=True
    )
    try:
        report = collect_cva6_teacher_trajectories(
            qualification_root=arguments.qualification_root,
            docker_config_path=arguments.docker_config,
            tokenizer=tokenizer,
            output=arguments.output,
            max_process_time_s=arguments.max_process_time_s,
            campaign_id=arguments.campaign_id,
        )
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
