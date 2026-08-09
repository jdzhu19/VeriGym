#!/usr/bin/env python3
"""Build a hash-bound, public-only task manifest for online rLLM training."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-input", action="append", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--verifier-image", required=True)
    parser.add_argument("--verifier-image-id", required=True)
    parser.add_argument("--input-policy-version", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _read_hashed(path: Path, field: str) -> dict[str, Any]:
    value = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    identity = dict(value)
    expected = identity.pop(field, None)
    if not isinstance(expected, str) or _canonical_hash(identity) != expected:
        raise SystemExit(f"input identity differs from {field}: {path.name}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    policy = _read_hashed(arguments.input_policy_version, "version_hash")
    task_ids: set[str] = set()
    bindings: list[dict[str, Any]] = []
    for path in arguments.public_input:
        public = _read_hashed(path, "record_hash")
        task_id = public.get("task_id")
        if (
            not isinstance(task_id, str)
            or task_id in task_ids
            or public.get("hidden_assets_included") is not False
        ):
            raise SystemExit("online public inputs must be unique and exclude hidden assets")
        task_ids.add(task_id)
        bindings.append(
            {
                "task_id": task_id,
                "public_input_hash": public["record_hash"],
                "public_record": public,
                "source_hash": public["source_hash"],
                "variant": arguments.variant,
                "verifier_image": arguments.verifier_image,
                "verifier_image_id": arguments.verifier_image_id,
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_online_tasks_v1",
        "input_policy_version_hash": policy["version_hash"],
        "input_policy_version_id": policy["policy_version_id"],
        "input_weight_version": policy["weight_version"],
        "tasks": bindings,
        "hidden_assets_exported_to_rollout": False,
        "reference_solutions_exported_to_rollout": False,
        "credential_values_included": False,
    }
    manifest = {**base, "manifest_hash": _canonical_hash(base)}
    _atomic_json(arguments.output, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
