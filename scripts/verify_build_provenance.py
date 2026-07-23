"""Verify that reproducible archives are bound to the current clean commit."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from verigym.provenance import get_build_provenance
from verigym.schemas.provenance import BuildProvenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    arguments = parser.parse_args()
    raw = json.loads(arguments.report.read_text(encoding="utf-8"))
    embedded = BuildProvenance.model_validate(raw["embedded_provenance"])
    live = get_build_provenance()
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    errors = []
    if embedded.dirty is not False:
        errors.append("embedded package provenance is not clean")
    if live.dirty is not False:
        errors.append("live source provenance is not clean")
    if embedded.source_commit != commit or live.source_commit != commit:
        errors.append("package/live source commit does not match Git HEAD")
    if embedded.source_tree_hash != live.source_tree_hash:
        errors.append("package source-tree hash does not match the clean checkout")
    if embedded.build_source_date_epoch != arguments.source_date_epoch:
        errors.append("embedded SOURCE_DATE_EPOCH differs from the release input")
    if embedded.package_version != live.package_version:
        errors.append("package version differs between embedded and live provenance")
    if not embedded.build_backend:
        errors.append("embedded build backend is missing")
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "source_commit": commit,
                "source_tree_hash": embedded.source_tree_hash,
                "dirty": embedded.dirty,
                "package_version": embedded.package_version,
                "build_backend": embedded.build_backend,
                "source_date_epoch": embedded.build_source_date_epoch,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
