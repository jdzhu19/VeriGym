#!/usr/bin/env python3
"""Run the bounded 32K Qwen3.5 AgentSFTTrainer mainline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verigym_training_reference.multiturn_sft_training import run_frozen_multiturn_sft_v2

from verigym.core.errors import ConfigurationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run six fixed veRL optimizer steps on eight bounded verified trajectories."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rllm-source", type=Path, required=True)
    return parser


def main() -> int:
    try:
        report = run_frozen_multiturn_sft_v2(**vars(_parser().parse_args()))
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
