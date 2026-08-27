"""Canonical experiment identity helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from verigym.core.hashing import content_hash
from verigym.schemas.common import RuntimeDescriptor
from verigym.schemas.task import VeriTask

_MAX_SEED = 2**63 - 1


def normalized_runtime_descriptor(descriptor: RuntimeDescriptor) -> RuntimeDescriptor:
    """Discard lifecycle noise while preserving the effective runtime contract."""

    normalized = descriptor.model_copy(
        update={
            "sessions": [],
            "cleanup": None,
            # Effective descriptor fields carry the execution contract. This
            # fingerprint also includes request spelling such as a Docker tag
            # versus its resolved image ID.
            "configuration_fingerprint": None,
        },
        deep=True,
    )
    if normalized.image is not None:
        normalized.image = normalized.image.model_copy(
            update={"requested_reference": normalized.image.resolved_image_id}
        )
    if normalized.resources is not None:
        # A runtime accumulates the smallest per-session output allowance while
        # executing. The task budget is bound separately in each plan item.
        normalized.resources = normalized.resources.model_copy(update={"max_output_bytes": None})
    return normalized


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

    payload = normalized_plan_item_payload(item)
    payload.pop("plan_index", None)
    payload.pop("plan_item_id", None)
    return payload


def normalized_system_identity_payload(system: Any) -> dict[str, Any]:
    """Omit empty additive options while retaining every configured value."""

    raw = (
        system.model_dump(mode="json")
        if hasattr(system, "model_dump")
        else deepcopy(cast(dict[str, Any], system))
    )
    if not raw.get("agent_options"):
        raw.pop("agent_options", None)
    model_options = raw.get("model_options")
    if isinstance(model_options, dict) and not model_options.get("client_options"):
        model_options.pop("client_options", None)
    if isinstance(model_options, dict):
        for field, default in (
            ("base_url_env", None),
            ("provider_id", None),
            ("max_response_bytes", 4 * 1024 * 1024),
            ("require_exact_model_id", False),
        ):
            if model_options.get(field) == default:
                model_options.pop(field, None)
    return cast(dict[str, Any], raw)


def normalized_plan_item_payload(item: Any) -> dict[str, Any]:
    """Normalize only empty post-Milestone-9 fields for legacy hash stability."""

    raw = (
        item.model_dump(mode="json")
        if hasattr(item, "model_dump")
        else deepcopy(cast(dict[str, Any], item))
    )
    system = raw.get("system")
    if isinstance(system, dict) or hasattr(system, "model_dump"):
        raw["system"] = normalized_system_identity_payload(system)
    if raw.get("repository_task_identity") is None:
        raw.pop("repository_task_identity", None)
    if raw.get("action_protocol") is None:
        raw.pop("action_protocol", None)
    if raw.get("agent_feedback_contract") is None:
        raw.pop("agent_feedback_contract", None)
    return cast(dict[str, Any], raw)


def plan_items_hash_payload(items: list[Any]) -> list[dict[str, Any]]:
    return [normalized_plan_item_payload(item) for item in items]


__all__ = [
    "correctness_definition_hash",
    "derive_experiment_id",
    "derive_child_seed",
    "evaluation_config_payload",
    "normalized_plan_item_payload",
    "normalized_runtime_descriptor",
    "normalized_system_identity_payload",
    "plan_items_hash_payload",
    "plan_item_identity_payload",
    "runtime_identity_hash",
]
