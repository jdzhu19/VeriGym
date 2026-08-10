"""Compatibility glue for rLLM trajectory grouping in verl GRPO batches."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

_PATCH_MARKER = "__verigym_grpo_group_compatibility__"


def bind_grpo_groups_to_trajectory_ids(batch: Any) -> Any:
    """Use stable task-and-role trajectory IDs instead of per-rollout UUIDs."""

    non_tensor_batch = getattr(batch, "non_tensor_batch", None)
    if not isinstance(non_tensor_batch, dict):
        raise RuntimeError("rLLM batch omits non-tensor trajectory metadata")
    trajectory_ids = non_tensor_batch.get("trajectory_ids")
    step_ids = non_tensor_batch.get("step_ids")
    if trajectory_ids is None or step_ids is None or len(trajectory_ids) != len(step_ids):
        raise RuntimeError("rLLM trajectory and step grouping metadata is inconsistent")
    original_group_count = len({str(value) for value in step_ids})
    stable_group_count = len({str(value) for value in trajectory_ids})
    non_tensor_batch["step_ids"] = trajectory_ids.copy()
    print(
        "VeriGym GRPO group bridge active: "
        f"rows={len(step_ids)} original_groups={original_group_count} "
        f"stable_groups={stable_group_count}",
        flush=True,
    )
    return batch


def activate_rllm_verl_grpo_group_compatibility() -> bool:
    """Patch the rLLM-to-verl transform at its narrow batch boundary."""

    try:
        from rllm.engine.agent_workflow_engine import (  # type: ignore[import-not-found]
            AgentWorkflowEngine,
        )
    except ImportError:
        return False
    current = AgentWorkflowEngine.transform_results_for_verl
    if getattr(current, _PATCH_MARKER, False):
        return True
    original: Callable[..., Any] = current

    @wraps(original)
    def transform_results_for_verl(self: Any, episodes: Any, task_ids: Any) -> Any:
        batch = original(self, episodes, task_ids)
        return bind_grpo_groups_to_trajectory_ids(batch)

    setattr(transform_results_for_verl, _PATCH_MARKER, True)
    AgentWorkflowEngine.transform_results_for_verl = transform_results_for_verl
    return True


RLLM_VERL_GRPO_GROUP_COMPATIBILITY_ACTIVE = activate_rllm_verl_grpo_group_compatibility()


__all__ = [
    "RLLM_VERL_GRPO_GROUP_COMPATIBILITY_ACTIVE",
    "activate_rllm_verl_grpo_group_compatibility",
    "bind_grpo_groups_to_trajectory_ids",
]
