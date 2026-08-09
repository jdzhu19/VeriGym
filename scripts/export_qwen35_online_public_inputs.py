#!/usr/bin/env python3
"""Export public inputs only for tasks explicitly assigned to a frozen training split."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from verigym_training_reference import build_public_input_record

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.splits import validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.registry.collections import build_registries
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.suite import SuiteSourceConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--task", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    split = TaskSplitManifest.model_validate_json(
        arguments.split.resolve(strict=True).read_text(encoding="utf-8")
    )
    validate_task_split(split)
    training = {entry.task_id: entry for entry in split.training}
    if len(arguments.task) != len(set(arguments.task)):
        raise ConfigurationError("online task IDs must be unique")
    source = SuiteSourceConfig(
        source_root=arguments.source_root.resolve(strict=True), variant=arguments.variant
    )
    suite = build_registries().suites.get(arguments.suite).with_source(source)
    references = {reference.id: reference for reference in suite.discover()}
    output = arguments.output.resolve()
    if output.exists() and (output.is_symlink() or not output.is_dir() or any(output.iterdir())):
        raise ConfigurationError("public input export must target a new or empty real directory")
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, str]] = []
    for task_id in arguments.task:
        expected = training.get(task_id)
        reference = references.get(task_id)
        if expected is None or reference is None:
            raise ConfigurationError("online task is not assigned to the frozen training split")
        task = suite.load_task(reference)
        if (
            content_hash(task) != expected.task_hash
            or task.source.content_hash != expected.source_hash
        ):
            raise ConfigurationError("online task identity differs from the frozen training split")
        assets = suite.resolve_assets(task)
        public = build_public_input_record(task, Path(assets.visible_root))
        native_id = str(task.metadata.get("native_task_id", reference.native_id))
        task_root = output / native_id
        task_root.mkdir()
        path = task_root / "public-input.json"
        atomic_dump_json(path, public)
        records.append(
            {
                "task_id": task.id,
                "record_hash": public["record_hash"],
                "storage_key": f"{native_id}/public-input.json",
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_online_training_public_inputs_v1",
        "split_manifest_hash": split.manifest_hash,
        "records": records,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
    }
    atomic_dump_json(output / "manifest.json", {**base, "manifest_hash": content_hash(base)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
