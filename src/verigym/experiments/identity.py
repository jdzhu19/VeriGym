"""Canonical experiment identity helpers."""

from __future__ import annotations

from typing import Any, cast

from verigym.core.hashing import content_hash
from verigym.schemas.common import RuntimeDescriptor
from verigym.schemas.task import VeriTask

_MAX_SEED = 2**63 - 1


def normalized_runtime_descriptor(descriptor: RuntimeDescriptor) -> RuntimeDescriptor:
    """Discard lifecycle noise while preserving the effective runtime contract."""

    return descriptor.model_copy(update={"sessions": [], "cleanup": None}, deep=True)


def runtime_identity_hash(descriptor: RuntimeDescriptor) -> str:
    return content_hash(normalized_runtime_descriptor(descriptor))


def correctness_definition_hash(task: VeriTask) -> str:
    return content_hash(
        {
            "verifier": task.verifier,
            "correctness_required_nodes": task.scoring.correctness_required_nodes,
        }
    )


def evaluation_config_payload(config: Any) -> dict[str, Any]:
    """Return result-affecting experiment config, excluding controller/storage policy."""

    payload = cast(dict[str, Any], config.identity_payload())
    payload.pop("name", None)
    payload.pop("description", None)
    payload.pop("execution", None)
    payload.pop("output", None)
    return payload


def derive_experiment_id(name: str, plan_hash: str) -> str:
    safe_name = (
        "".join(character.lower() if character.isalnum() else "-" for character in name).strip("-")[
            :40
        ]
        or "experiment"
    )
    return f"m9-{safe_name}-{plan_hash[:16]}"


def derive_child_seed(
    *,
    evaluation_config_hash: str,
    task_hash: str,
    system_identity_hash: str,
    base_seed: int,
    sample_index: int,
) -> int:
    """Derive a stable nonnegative signed-64-bit seed from evaluation identity."""

    digest = content_hash(
        {
            "algorithm": "verigym-child-seed-sha256-v1",
            "evaluation_config_hash": evaluation_config_hash,
            "task_hash": task_hash,
            "system_identity_hash": system_identity_hash,
            "base_seed": base_seed,
            "sample_index": sample_index,
        }
    )
    return int(digest[:16], 16) & _MAX_SEED


def plan_item_identity_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Return only evaluation-relevant plan state, excluding order and paths."""

    payload = dict(item)
    payload.pop("plan_index", None)
    payload.pop("plan_item_id", None)
    return payload


__all__ = [
    "correctness_definition_hash",
    "derive_experiment_id",
    "derive_child_seed",
    "evaluation_config_payload",
    "normalized_runtime_descriptor",
    "plan_item_identity_payload",
    "runtime_identity_hash",
]
