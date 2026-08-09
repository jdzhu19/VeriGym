#!/usr/bin/env python3
"""Export the public-only portion of one frozen VeriGym task for model sampling."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.experiments.state import atomic_dump_json
from verigym.registry.collections import build_registries
from verigym.schemas.suite import SuiteSourceConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export one public VeriGym task input.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    output = arguments.output.expanduser()
    if output.exists():
        raise SystemExit("public task output already exists")
    source = SuiteSourceConfig(
        source_root=arguments.source.expanduser().resolve(strict=True),
        variant=arguments.variant,
    )
    service = VeriGym(build_registries())
    suite, task, assets = service.load_task(arguments.task, source)
    snapshot = suite.source_snapshot()
    if snapshot is None or task.interaction.final_submission.kind != "file":
        raise SystemExit("public export requires a frozen single-file task")
    candidate_path = task.interaction.final_submission.path
    if candidate_path is None:
        raise SystemExit("task has no final candidate path")
    visible = Path(assets.visible_root).resolve(strict=True)
    candidate = (visible / candidate_path).resolve(strict=True)
    if not candidate.is_relative_to(visible) or candidate.is_symlink() or not candidate.is_file():
        raise SystemExit("task candidate path is not a safe visible file")
    readme_path = visible / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    base: dict[str, object] = {
        "schema_version": "1.0",
        "task_id": task.id,
        "task_hash": content_hash(task),
        "source_hash": task.source.content_hash or snapshot.content_hash,
        "candidate_path": candidate_path,
        "task_description": task.description,
        "public_readme": readme,
        "candidate_skeleton": candidate.read_text(encoding="utf-8"),
        "hidden_assets_included": False,
    }
    result = {**base, "record_hash": content_hash(base)}
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_dump_json(output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    _run(_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
