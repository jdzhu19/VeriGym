from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from verigym.core.hashing import content_hash


def _script() -> ModuleType:
    path = Path("scripts/merge_rllm_reward_groups.py").resolve(strict=True)
    spec = importlib.util.spec_from_file_location("verigym_merge_rllm_reward_groups_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reward_group(
    root: Path,
    *,
    task_id: str,
    group_id: str,
    policy_hash: str = "a" * 64,
    rewards: tuple[float, ...] = (0.0, 1.0),
) -> Path:
    root.mkdir()
    records = []
    for sample_index, reward in enumerate(rewards):
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_rllm_rollout_scored_v2",
            "group_id": group_id,
            "sample_index": sample_index,
            "task_id": task_id,
            "policy_version_hash": policy_hash,
            "weight_version": 2,
            "infrastructure_valid": True,
            "reward": reward,
            "episode": {
                "trajectories": [
                    {
                        "steps": [
                            {"weight_version": 2, "metadata": {}},
                            {"weight_version": 2, "metadata": {}},
                        ]
                    }
                ]
            },
        }
        records.append({**base, "record_hash": content_hash(base)})
    data = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records).encode()
    (root / "rollouts.scored.jsonl").write_bytes(data)
    base_manifest = {
        "schema_version": "1.0",
        "format_id": "verigym_rllm_rollout_dataset_scored_v2",
        "record_count": len(records),
        "record_hashes": [record["record_hash"] for record in records],
        "scored_file_sha256": hashlib.sha256(data).hexdigest(),
        "group_ids": [group_id],
        "task_ids": [task_id],
        "policy_version_hash": policy_hash,
        "policy_version_id": "policy-v2",
        "weight_version": 2,
        "rewards": list(rewards),
        "infrastructure_invalid_count": 0,
        "hidden_assets_exported_to_trainer": False,
        "reference_solution_exported_to_trainer": False,
    }
    (root / "reward-manifest.json").write_text(
        json.dumps({**base_manifest, "manifest_hash": content_hash(base_manifest)}),
        encoding="utf-8",
    )
    return root


def test_merge_verified_reward_groups_is_deterministic(tmp_path: Path) -> None:
    module = _script()
    second = _reward_group(tmp_path / "second", task_id="suite/task-b", group_id="group-b")
    first = _reward_group(tmp_path / "first", task_id="suite/task-a", group_id="group-a")
    output = tmp_path / "merged"

    assert (
        module.main(["--input", str(second), "--input", str(first), "--output", str(output)]) == 0
    )
    manifest = json.loads((output / "reward-manifest.json").read_text(encoding="utf-8"))
    identity = dict(manifest)
    expected = identity.pop("manifest_hash")

    assert content_hash(identity) == expected
    assert manifest["format_id"] == "verigym_rllm_rollout_dataset_scored_multi_v1"
    assert manifest["task_ids"] == ["suite/task-a", "suite/task-b"]
    assert manifest["group_ids"] == ["group-a", "group-b"]
    assert manifest["group_count"] == 2
    assert manifest["record_count"] == 4
    assert manifest["each_group_has_reward_variance"] is True
    assert str(tmp_path) not in json.dumps(manifest)


def test_merge_rejects_policy_mismatch(tmp_path: Path) -> None:
    module = _script()
    first = _reward_group(tmp_path / "first", task_id="suite/task-a", group_id="group-a")
    second = _reward_group(
        tmp_path / "second",
        task_id="suite/task-b",
        group_id="group-b",
        policy_hash="b" * 64,
    )

    with pytest.raises(SystemExit, match="one registered policy"):
        module.main(
            ["--input", str(first), "--input", str(second), "--output", str(tmp_path / "merged")]
        )


def test_merge_rejects_group_without_reward_variance(tmp_path: Path) -> None:
    module = _script()
    first = _reward_group(tmp_path / "first", task_id="suite/task-a", group_id="group-a")
    second = _reward_group(
        tmp_path / "second",
        task_id="suite/task-b",
        group_id="group-b",
        rewards=(0.0, 0.0),
    )

    with pytest.raises(SystemExit, match="reward variance"):
        module.main(
            ["--input", str(first), "--input", str(second), "--output", str(tmp_path / "merged")]
        )
