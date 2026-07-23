"""Fail unless the repository and live provenance identify a clean committed source."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from verigym.provenance import get_build_provenance


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    provenance = get_build_provenance()
    result = {
        "schema_version": "1.0",
        "status": "passed" if not status and provenance.dirty is False else "failed",
        "source_commit": _git(root, "rev-parse", "--verify", "HEAD^{commit}"),
        "source_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "source_tree_hash": provenance.source_tree_hash,
        "source_tree_file_count": provenance.source_tree_file_count,
        "package_version": provenance.package_version,
        "build_backend": provenance.build_backend,
        "dirty": provenance.dirty,
        "worktree_porcelain_empty": not status,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["status"] != "passed":
        print("release audit requires an empty Git worktree and dirty=false provenance")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
