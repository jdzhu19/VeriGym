#!/usr/bin/env python3
"""Summarize exact held-out scorecards for multiple registered policies."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from verigym_training_reference.heldout import summarize_heldout_results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--policy", action="append", required=True, metavar="ID=ROOT")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    policies: dict[str, Path] = {}
    for binding in arguments.policy:
        policy_id, separator, root = binding.partition("=")
        if not separator or not policy_id or not root or policy_id in policies:
            raise SystemExit("--policy must be a unique ID=ROOT binding")
        policies[policy_id] = Path(root)
    report = summarize_heldout_results(
        split=arguments.split,
        policy_roots=policies,
        output=arguments.output,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
