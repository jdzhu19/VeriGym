#!/usr/bin/env python3
"""Freeze public-only inputs and a formal task split for Qwen3.5 evaluation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from verigym_training_reference.heldout import freeze_heldout_evaluation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--training-public-input", action="append", type=Path, default=[])
    parser.add_argument("--frozen-after-policy", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    manifest = freeze_heldout_evaluation(
        split_id=config["split_id"],
        suite_id=config["suite_id"],
        source_root=arguments.source,
        variant=config["variant"],
        task_ids=config["task_ids"],
        training_public_inputs=arguments.training_public_input,
        output=arguments.output,
        frozen_after_policy_hash=arguments.frozen_after_policy,
    )
    print(json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
