from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from verigym_training_reference.rllm_grpo_compat import (
    bind_grpo_groups_to_trajectory_ids,
)


class _CopyableIds(list[str]):
    def copy(self) -> _CopyableIds:
        return _CopyableIds(self)


@dataclass
class _Batch:
    non_tensor_batch: dict[str, Any]


def test_grpo_groups_repeated_rollouts_by_stable_trajectory_identity() -> None:
    trajectory_ids = _CopyableIds(["task-a:rtl", "task-a:rtl", "task-b:rtl", "task-b:rtl"])
    batch = _Batch(
        non_tensor_batch={
            "trajectory_ids": trajectory_ids,
            "step_ids": _CopyableIds(["rollout-1", "rollout-2", "rollout-3", "rollout-4"]),
        }
    )

    assert bind_grpo_groups_to_trajectory_ids(batch) is batch
    assert batch.non_tensor_batch["step_ids"] == trajectory_ids
    assert batch.non_tensor_batch["step_ids"] is not trajectory_ids


def test_grpo_group_bridge_rejects_misaligned_metadata() -> None:
    batch = _Batch(
        non_tensor_batch={
            "trajectory_ids": _CopyableIds(["task-a:rtl"]),
            "step_ids": _CopyableIds([]),
        }
    )

    with pytest.raises(RuntimeError, match="metadata is inconsistent"):
        bind_grpo_groups_to_trajectory_ids(batch)
