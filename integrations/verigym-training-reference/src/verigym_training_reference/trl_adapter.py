"""Dependency-free adapter for TRL's prompt dataset and custom reward interfaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from .schemas import OnlineRewardResult, TrainingReferenceBundleManifest


class RewardOracle(Protocol):
    manifest: TrainingReferenceBundleManifest

    def task_prompt(self, task_id: str) -> list[dict[str, str]]: ...

    def score(self, task_id: str, candidate: str) -> OnlineRewardResult: ...


def build_trl_dataset_rows(oracle: RewardOracle) -> list[dict[str, object]]:
    """Build rows accepted by `datasets.Dataset.from_list` and TRL GRPOTrainer."""

    return [
        {"prompt": oracle.task_prompt(task_id), "task_id": task_id}
        for task_id in oracle.manifest.training_task_ids
    ]


def _completion_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        content = value.get("content")
        if isinstance(content, str):
            return content
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
        return _completion_text(value[-1])
    raise ValueError("TRL completion must be text or a conversational message sequence")


class TrlRewardAdapter:
    """Callable matching TRL custom rewards; infrastructure-invalid samples return None."""

    def __init__(self, oracle: RewardOracle) -> None:
        self.oracle = oracle

    def __call__(
        self,
        completions: Sequence[object],
        task_id: Sequence[str],
        **_: object,
    ) -> list[float | None]:
        if len(completions) != len(task_id):
            raise ValueError("TRL completion and task-id batches must align")
        rewards: list[float | None] = []
        for completion, native_task_id in zip(completions, task_id, strict=True):
            result = self.oracle.score(native_task_id, _completion_text(completion))
            rewards.append(result.scalar_reward if result.infrastructure_valid else None)
        return rewards


__all__ = ["TrlRewardAdapter", "build_trl_dataset_rows"]
