"""Merge complete, non-overlapping VerilogEval VCS/MCP qualification receipts."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from verigym.plugin_api import ConfigurationError, content_hash


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge a complete VerilogEval VCS/MCP qualification receipt set."
    )
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _load(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError("qualification receipt must be a regular non-symlink file")
    try:
        payload = json.loads(expanded.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("qualification receipt is invalid") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("qualification receipt must be a JSON object")
    identity = {
        "bundle_identity_hash": payload.get("bundle_identity_hash"),
        "dataset_content_hash": payload.get("dataset_content_hash"),
        "accepted_vcs_version": payload.get("accepted_vcs_version"),
        "corpus_task_count": payload.get("corpus_task_count"),
        "task_count": payload.get("task_count"),
        "jobs_per_task": payload.get("jobs_per_task"),
        "selection": payload.get("selection"),
        "verdicts": payload.get("verdicts"),
    }
    if (
        payload.get("kind") != "verilog_eval_vcs_mcp_qualification_v1"
        or payload.get("passed") is not True
        or payload.get("model_calls") != 0
        or payload.get("automatic_retries") != 0
        or payload.get("qualification_identity_hash") != content_hash(identity)
    ):
        raise ConfigurationError("qualification receipt identity or status is invalid")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    parent = path.parent.resolve(strict=True)
    output = parent / path.name
    temporary = parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if len(arguments.input) != len(set(arguments.input)):
        raise ConfigurationError("qualification receipt inputs must be unique")
    receipts = [_load(path) for path in arguments.input]
    first = receipts[0]
    fixed_fields = (
        "bundle_identity_hash",
        "dataset_content_hash",
        "accepted_vcs_version",
        "corpus_task_count",
        "jobs_per_task",
    )
    if any(
        any(receipt[field] != first[field] for field in fixed_fields) for receipt in receipts[1:]
    ):
        raise ConfigurationError("qualification receipts use different frozen contracts")

    selections = [receipt["selection"] for receipt in receipts]
    if len(receipts) == 1 and selections == [{"kind": "all"}]:
        pass
    else:
        if not all(isinstance(item, dict) and item.get("kind") == "shard" for item in selections):
            raise ConfigurationError("qualification receipt selection is not a complete shard set")
        shard_counts = {item.get("shard_count") for item in selections}
        shard_indexes = {item.get("shard_index") for item in selections}
        shard_count = next(iter(shard_counts)) if len(shard_counts) == 1 else None
        if (
            not isinstance(shard_count, int)
            or isinstance(shard_count, bool)
            or shard_count < 1
            or not all(
                isinstance(index, int) and not isinstance(index, bool) for index in shard_indexes
            )
            or shard_indexes != set(range(shard_count))
        ):
            raise ConfigurationError("qualification shard set is incomplete or inconsistent")

    verdicts = [verdict for receipt in receipts for verdict in receipt["verdicts"]]
    native_ids = [verdict["native_id"] for verdict in verdicts]
    if (
        len(native_ids) != len(set(native_ids))
        or len(verdicts) != first["corpus_task_count"]
        or any(verdict.get("reference_passed") is not True for verdict in verdicts)
        or (
            first["jobs_per_task"] == 2
            and any(verdict.get("known_bad_rejected") is not True for verdict in verdicts)
        )
    ):
        raise ConfigurationError("qualification verdict coverage is incomplete or overlapping")
    commercial_jobs = sum(int(receipt["commercial_jobs"]) for receipt in receipts)
    if commercial_jobs != len(verdicts) * first["jobs_per_task"]:
        raise ConfigurationError("qualification commercial-job count is inconsistent")

    identity = {
        "bundle_identity_hash": first["bundle_identity_hash"],
        "dataset_content_hash": first["dataset_content_hash"],
        "accepted_vcs_version": first["accepted_vcs_version"],
        "task_count": len(verdicts),
        "jobs_per_task": first["jobs_per_task"],
        "input_qualification_hashes": sorted(
            receipt["qualification_identity_hash"] for receipt in receipts
        ),
        "task_verdict_hash": content_hash(sorted(verdicts, key=lambda item: item["native_id"])),
    }
    merged = {
        "schema_version": "1.0",
        "kind": "verilog_eval_vcs_mcp_qualification_aggregate_v1",
        **identity,
        "qualification_identity_hash": content_hash(identity),
        "commercial_jobs": commercial_jobs,
        "reference_passes": len(verdicts),
        "known_bad_rejections": len(verdicts) if first["jobs_per_task"] == 2 else 0,
        "model_calls": 0,
        "automatic_retries": 0,
        "passed": True,
    }
    output = arguments.output.expanduser()
    if output.exists() or output.is_symlink():
        raise ConfigurationError("merged qualification output already exists")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _atomic_write_json(output, merged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
