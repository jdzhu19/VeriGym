#!/usr/bin/env python3
"""Qualify and freeze the bounded CVA6 multi-turn SFT task pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verigym_hwe_bench.cva6_qualification import qualify_cva6_teacher_pool

from verigym.plugin_api import ConfigurationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qualify 13 explicit CVA6 F2P tasks.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--existing-split", type=Path, action="append", required=True)
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--official-dataset-revision")
    parser.add_argument("--official-source-commit")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        report = qualify_cva6_teacher_pool(
            dataset=arguments.dataset,
            output=arguments.output,
            existing_split_paths=arguments.existing_split,
            pull=arguments.pull,
            official_dataset_revision=arguments.official_dataset_revision,
            official_source_commit=arguments.official_source_commit,
        )
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
