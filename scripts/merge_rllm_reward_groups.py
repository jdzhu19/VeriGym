#!/usr/bin/env python3
"""Merge independently verified rLLM reward groups for multi-group GRPO."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_MAX_DATASET_BYTES = 128 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge compatible scored rLLM reward groups.")
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_bytes(encoded.encode())


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise SystemExit(f"{label} cannot be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise SystemExit(f"{label} must be a directory")
    return resolved


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise SystemExit("merged reward output must be a new or empty real directory")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
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


def _atomic_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _read_group(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = root / "reward-manifest.json"
    data_path = root / "rollouts.scored.jsonl"
    if manifest_path.is_symlink() or data_path.is_symlink():
        raise SystemExit("reward group inputs cannot be symlinks")
    payload = data_path.read_bytes()
    if not 0 < len(payload) <= _MAX_DATASET_BYTES:
        raise SystemExit("reward group JSONL is empty or oversized")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = [json.loads(line) for line in payload.decode().splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("reward group contains invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise SystemExit("reward group manifest must be an object")
    identity = dict(manifest)
    expected_manifest_hash = identity.pop("manifest_hash", None)
    if (
        not isinstance(expected_manifest_hash, str)
        or _canonical_hash(identity) != expected_manifest_hash
        or manifest.get("format_id") != "verigym_rllm_rollout_dataset_scored_v2"
        or manifest.get("infrastructure_invalid_count") != 0
        or manifest.get("hidden_assets_exported_to_trainer") is not False
        or manifest.get("reference_solution_exported_to_trainer") is not False
        or _sha256_bytes(payload) != manifest.get("scored_file_sha256")
    ):
        raise SystemExit("reward group manifest is not merge-eligible")
    if len(records) != manifest.get("record_count") or len(manifest.get("group_ids", [])) != 1:
        raise SystemExit("each merge input must contain exactly one complete reward group")
    policy_hash = manifest.get("policy_version_hash")
    policy_id = manifest.get("policy_version_id")
    weight_version = manifest.get("weight_version")
    group_id = manifest["group_ids"][0]
    task_ids = manifest.get("task_ids")
    if (
        not isinstance(policy_hash, str)
        or not isinstance(policy_id, str)
        or not isinstance(weight_version, int)
        or not isinstance(group_id, str)
        or not isinstance(task_ids, list)
        or len(task_ids) != 1
        or not isinstance(task_ids[0], str)
    ):
        raise SystemExit("reward group omits its policy, group, or task identity")
    rewards: list[float] = []
    for record, expected in zip(records, manifest.get("record_hashes", []), strict=True):
        if not isinstance(record, dict):
            raise SystemExit("reward group records must be objects")
        record_identity = dict(record)
        record_hash = record_identity.pop("record_hash", None)
        episode = record.get("episode")
        trajectories = episode.get("trajectories") if isinstance(episode, dict) else None
        steps = (
            trajectories[0].get("steps")
            if isinstance(trajectories, list) and trajectories
            else None
        )
        if (
            record_hash != expected
            or _canonical_hash(record_identity) != expected
            or record.get("format_id") != "verigym_rllm_rollout_scored_v2"
            or record.get("infrastructure_valid") is not True
            or record.get("reward") not in {0.0, 1.0}
            or record.get("group_id") != group_id
            or record.get("task_id") != task_ids[0]
            or record.get("policy_version_hash") != policy_hash
            or record.get("weight_version") != weight_version
            or not isinstance(steps, list)
            or len(steps) < 2
            or any(step.get("weight_version") != weight_version for step in steps)
        ):
            raise SystemExit("reward group record identity or policy binding is invalid")
        rewards.append(float(record["reward"]))
    if len(set(rewards)) < 2:
        raise SystemExit("each merged reward group requires nonzero reward variance")
    return manifest, records


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    if len(arguments.input) < 2:
        raise SystemExit("multi-group merge requires at least two input groups")
    roots = [_safe_directory(path, "reward group") for path in arguments.input]
    if len(set(roots)) != len(roots):
        raise SystemExit("reward group inputs must be unique")
    groups = [_read_group(root) for root in roots]
    groups.sort(key=lambda item: (item[0]["task_ids"][0], item[0]["group_ids"][0]))
    policy_identities = {
        (
            manifest.get("policy_version_hash"),
            manifest.get("policy_version_id"),
            manifest.get("weight_version"),
        )
        for manifest, _ in groups
    }
    if len(policy_identities) != 1:
        raise SystemExit("merged groups must come from one registered policy version")
    group_ids = [manifest["group_ids"][0] for manifest, _ in groups]
    if len(set(group_ids)) != len(group_ids):
        raise SystemExit("merged reward group IDs must be unique")
    policy_hash, policy_id, weight_version = policy_identities.pop()
    records = [record for _, group_records in groups for record in group_records]
    output = _new_directory(arguments.output)
    data_path = output / "rollouts.scored.jsonl"
    _atomic_jsonl(data_path, records)
    group_summaries = [
        {
            "group_id": manifest["group_ids"][0],
            "task_id": manifest["task_ids"][0],
            "record_count": len(group_records),
            "record_hashes": [record["record_hash"] for record in group_records],
            "rewards": [float(record["reward"]) for record in group_records],
            "source_reward_manifest_hash": manifest["manifest_hash"],
        }
        for manifest, group_records in groups
    ]
    rewards = [float(record["reward"]) for record in records]
    task_groups: defaultdict[str, int] = defaultdict(int)
    for summary in group_summaries:
        task_groups[summary["task_id"]] += 1
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_rllm_rollout_dataset_scored_multi_v1",
        "record_count": len(records),
        "record_hashes": [record["record_hash"] for record in records],
        "scored_file_sha256": _sha256_bytes(data_path.read_bytes()),
        "group_count": len(group_summaries),
        "group_ids": group_ids,
        "group_summaries": group_summaries,
        "task_ids": sorted(task_groups),
        "task_group_counts": dict(sorted(task_groups.items())),
        "policy_version_hash": policy_hash,
        "policy_version_id": policy_id,
        "weight_version": weight_version,
        "rewards": rewards,
        "resolved_count": sum(reward == 1.0 for reward in rewards),
        "unresolved_count": sum(reward == 0.0 for reward in rewards),
        "infrastructure_invalid_count": 0,
        "source_reward_manifest_hashes": [manifest["manifest_hash"] for manifest, _ in groups],
        "each_group_has_reward_variance": True,
        "hidden_assets_exported_to_trainer": False,
        "reference_solution_exported_to_trainer": False,
        "credential_values_exported_to_trainer": False,
        "raw_host_paths_exported_to_trainer": False,
    }
    manifest = {**base, "manifest_hash": _canonical_hash(base)}
    _atomic_json(output / "reward-manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    _run(_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
