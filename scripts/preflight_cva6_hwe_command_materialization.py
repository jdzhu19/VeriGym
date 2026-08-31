#!/usr/bin/env python3
"""Seal the zero-provider filesystem gate for CVA6 command-image materialization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.hwe.materialization_preflight import (
    MaterializationHeadroomError,
    discover_docker_root,
    require_materialization_headroom,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output-parent", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def preflight(*, scratch_root: Path, output_parent: Path, receipt_path: Path) -> dict[str, object]:
    """Run and persist one new content-free headroom receipt."""

    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("HWE materialization headroom receipt must be a new path")
    docker_root = discover_docker_root()
    try:
        receipt = require_materialization_headroom(
            control_root=Path("/"),
            docker_root=docker_root,
            scratch_root=scratch_root,
            output_parent=output_parent,
        )
    except MaterializationHeadroomError as exc:
        atomic_dump_json(receipt_path, exc.receipt)
        raise
    atomic_dump_json(receipt_path, receipt)
    return receipt


def main() -> int:
    arguments = _parser().parse_args()
    receipt = preflight(
        scratch_root=arguments.scratch_root,
        output_parent=arguments.output_parent,
        receipt_path=arguments.receipt,
    )
    print(json.dumps({"status": receipt["status"], "preflight_hash": receipt["preflight_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
