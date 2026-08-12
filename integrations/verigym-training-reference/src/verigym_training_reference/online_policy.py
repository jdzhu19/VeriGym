"""Export an online rLLM/verl checkpoint as a registered compact policy."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

from .policy_versions import register_training_policy_version
from .schemas import TrainingPolicyVersionManifest

_MAX_JSON_BYTES = 16 * 1024 * 1024
_CHECKPOINT_STEP = re.compile(r"^(?:0|[1-9][0-9]*)$")
_ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, hash_field: str, label: str) -> dict[str, Any]:
    candidate = path.expanduser()
    metadata = os.lstat(candidate)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not 0 < metadata.st_size <= _MAX_JSON_BYTES
    ):
        raise ConfigurationError(f"unsafe {label}: {candidate.name}")
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid {label}: {candidate.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a JSON object")
    identity = dict(value)
    expected = identity.pop(hash_field, None)
    if not isinstance(expected, str) or content_hash(identity) != expected:
        raise ConfigurationError(f"{label} identity differs from {hash_field}")
    return value


def _checkpoint_adapter(checkpoint_root: Path) -> tuple[int, Path]:
    root = checkpoint_root.expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ConfigurationError("checkpoint root must be a real directory")
    latest = root / "latest_checkpointed_iteration.txt"
    metadata = os.lstat(latest)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError("checkpoint iteration marker must be a regular file")
    raw_step = latest.read_text(encoding="utf-8").strip()
    if not _CHECKPOINT_STEP.fullmatch(raw_step):
        raise ConfigurationError("checkpoint iteration marker is invalid")
    step = int(raw_step)
    adapter = root / f"global_step_{step}" / "actor" / "lora_adapter"
    if adapter.is_symlink() or not adapter.is_dir():
        raise ConfigurationError("checkpoint does not contain a real LoRA adapter directory")
    for name in _ADAPTER_FILES:
        path = adapter / name
        file_metadata = os.lstat(path)
        if (
            stat.S_ISLNK(file_metadata.st_mode)
            or not stat.S_ISREG(file_metadata.st_mode)
            or file_metadata.st_size <= 0
        ):
            raise ConfigurationError(f"checkpoint adapter file is unsafe: {name}")
    return step, adapter


def _adapter_inventory(root: Path) -> list[dict[str, int | str]]:
    inventory: list[dict[str, int | str]] = [
        {
            "path": name,
            "size_bytes": (root / name).stat().st_size,
            "sha256": _sha256(root / name),
        }
        for name in _ADAPTER_FILES
    ]
    return sorted(inventory, key=lambda item: str(item["path"]))


def _inventory_hash(inventory: list[dict[str, int | str]]) -> str:
    encoded = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _contains_raw_path(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_raw_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_raw_path(item) for item in value)
    return isinstance(value, str) and (value.startswith(("/", "\\")) or ":\\" in value)


def _portable_adapter_config(path: Path, *, model_id: str) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("checkpoint adapter configuration is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("checkpoint adapter configuration must be an object")
    value["base_model_name_or_path"] = model_id
    if _contains_raw_path(value):
        raise ConfigurationError("checkpoint adapter configuration contains a raw host path")
    atomic_dump_json(path, value)


def _validate_online_inputs(
    *,
    completion: dict[str, Any],
    broker: dict[str, Any],
    tasks: dict[str, Any],
    parent: TrainingPolicyVersionManifest,
) -> None:
    if (
        completion.get("format_id") != "verigym_rllm_verl_online_smoke_report_v1"
        or completion.get("status") != "completed"
        or completion.get("effective_policy_update_verified") is not True
        or completion.get("full_ray_vllm_stack_qualified") is not True
        or completion.get("infrastructure_invalid_count") != 0
        or not isinstance(completion.get("adapter_changed_tensor_count"), int)
        or completion["adapter_changed_tensor_count"] <= 0
        or not isinstance(completion.get("adapter_max_abs_delta"), (float, int))
        or completion["adapter_max_abs_delta"] <= 0
    ):
        raise ConfigurationError("online completion report does not qualify a policy update")
    broker_format = broker.get("format_id")
    workflow_kind = completion.get("workflow_kind", "rtl")
    if broker_format == "verigym_online_verifier_broker_report_v1":
        broker_count = broker.get("request_count")
        broker_records = broker.get("requests")
        if workflow_kind != "rtl":
            raise ConfigurationError("online workflow differs from its verifier broker")
    elif broker_format == "verigym_online_repository_broker_report_v1":
        broker_count = broker.get("session_count")
        broker_records = broker.get("sessions")
        if workflow_kind != "repository":
            raise ConfigurationError("online workflow differs from its repository broker")
        if (
            broker.get("hidden_assets_exported_to_training_container") is not False
            or broker.get("source_root_exported_to_training_container") is not False
            or broker.get("docker_socket_exported_to_training_container") is not False
            or broker.get("credential_values_included") is not False
        ):
            raise ConfigurationError("repository broker violated the training isolation boundary")
    else:
        raise ConfigurationError("unsupported online broker report")
    if (
        not isinstance(broker_count, int)
        or broker_count < 1
        or not isinstance(broker_records, list)
        or len(broker_records) != broker_count
    ):
        raise ConfigurationError("online broker report has inconsistent rollout records")
    if tasks.get("format_id") != "verigym_online_tasks_v1":
        raise ConfigurationError("unsupported online task manifest")
    if completion.get("task_manifest_hash") != tasks.get("manifest_hash") or broker.get(
        "task_manifest_hash"
    ) != tasks.get("manifest_hash"):
        raise ConfigurationError("online reports differ from the task manifest")
    if (
        completion.get("rollout_count") != broker_count
        or completion.get("resolved_count") != broker.get("resolved_count")
        or broker.get("infrastructure_invalid_count") != 0
    ):
        raise ConfigurationError("online completion and verifier broker counts differ")
    if (
        completion.get("input_policy_version_hash") != parent.version_hash
        or completion.get("input_policy_version_id") != parent.policy_version_id
        or completion.get("input_weight_version") != parent.weight_version
        or tasks.get("input_policy_version_hash") != parent.version_hash
        or tasks.get("input_policy_version_id") != parent.policy_version_id
        or tasks.get("input_weight_version") != parent.weight_version
    ):
        raise ConfigurationError("online update does not descend from the registered parent")
    raw_tasks = tasks.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ConfigurationError("online task manifest omits task bindings")
    task_ids: list[str] = []
    for binding in raw_tasks:
        if not isinstance(binding, dict) or not isinstance(binding.get("task_id"), str):
            raise ConfigurationError("online task manifest contains an invalid task binding")
        task_ids.append(binding["task_id"])
    task_ids.sort()
    if task_ids != completion.get("task_ids") or len(task_ids) != len(raw_tasks):
        raise ConfigurationError("online completion task coverage differs from its manifest")
    task_id_set = set(task_ids)
    if any(
        not isinstance(record, dict)
        or record.get("task_id") not in task_id_set
        or record.get("infrastructure_valid") not in {True, False}
        or record.get("resolved") not in {True, False, None}
        for record in broker_records
    ):
        raise ConfigurationError("online broker contains an invalid rollout record")
    if broker["infrastructure_invalid_count"] != sum(
        record["infrastructure_valid"] is not True for record in broker_records
    ) or broker["resolved_count"] != sum(record["resolved"] is True for record in broker_records):
        raise ConfigurationError("online broker summary differs from its rollout records")
    rewards = completion.get("rewards_by_task")
    if not isinstance(rewards, dict) or set(rewards) != task_id_set:
        raise ConfigurationError("online completion reward coverage differs from its manifest")
    for task_id in task_ids:
        observed = rewards[task_id]
        expected = [
            float(record["resolved"] is True)
            for record in broker_records
            if record["task_id"] == task_id
        ]
        if (
            not isinstance(observed, list)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) not in {0.0, 1.0}
                for value in observed
            )
            or sorted(float(value) for value in observed) != sorted(expected)
        ):
            raise ConfigurationError("online completion rewards differ from broker outcomes")


def _broker_rollouts(broker: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    if broker["format_id"] == "verigym_online_repository_broker_report_v1":
        count = broker["session_count"]
        records = broker["sessions"]
    else:
        count = broker["request_count"]
        records = broker["requests"]
    return int(count), sorted(
        records,
        key=lambda item: (
            str(item.get("task_id")),
            str(item.get("request_hash", item.get("session_id"))),
        ),
    )


def export_online_policy_version(
    *,
    completion_report: Path,
    broker_report: Path,
    task_manifest: Path,
    checkpoint_root: Path,
    parent_manifest: Path,
    model_root: Path,
    output: Path,
    policy_version_id: str,
    learning_rate: float,
) -> TrainingPolicyVersionManifest:
    """Export the latest LoRA and register its exact online-training lineage."""

    completion = _read_json(
        completion_report, hash_field="report_hash", label="online completion report"
    )
    broker = _read_json(broker_report, hash_field="report_hash", label="verifier broker report")
    tasks = _read_json(task_manifest, hash_field="manifest_hash", label="online task manifest")
    parent_value = _read_json(
        parent_manifest, hash_field="version_hash", label="parent policy manifest"
    )
    parent = TrainingPolicyVersionManifest.model_validate(parent_value)
    _validate_online_inputs(completion=completion, broker=broker, tasks=tasks, parent=parent)
    if parent.weight_version is None or parent.artifact_kind != "lora_adapter":
        raise ConfigurationError("online GRPO parent must be a trained LoRA policy")
    if not learning_rate > 0:
        raise ConfigurationError("online policy learning rate must be positive")

    step, source_adapter = _checkpoint_adapter(checkpoint_root)
    destination_input = output.expanduser()
    if destination_input.exists() or destination_input.is_symlink():
        raise ConfigurationError("online policy output already exists")
    destination_input.parent.mkdir(parents=True, exist_ok=True)
    destination_parent = destination_input.parent.resolve(strict=True)
    destination = destination_parent / destination_input.name
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination_parent))
    try:
        adapter = temporary / "adapter"
        adapter.mkdir()
        for name in _ADAPTER_FILES:
            shutil.copyfile(source_adapter / name, adapter / name)
        _portable_adapter_config(adapter / "adapter_config.json", model_id=parent.model_id)
        inventory = _adapter_inventory(adapter)
        adapter_hash = _inventory_hash(inventory)

        rollout_count, rollout_records = _broker_rollouts(broker)
        reward_base = {
            "schema_version": "1.0",
            "format_id": "verigym_online_reward_manifest_v1",
            "task_manifest_hash": tasks["manifest_hash"],
            "input_policy_version_hash": parent.version_hash,
            "workflow_kind": completion.get("workflow_kind", "rtl"),
            "broker_format_id": broker["format_id"],
            "rollout_count": rollout_count,
            # Retained as compatibility aliases for existing reward-manifest readers.
            "request_count": rollout_count,
            "resolved_count": broker["resolved_count"],
            "infrastructure_invalid_count": broker["infrastructure_invalid_count"],
            "rewards_by_task": completion["rewards_by_task"],
            "rollout_records": rollout_records,
            "request_records": rollout_records,
            "broker_report_hash": broker["report_hash"],
            "hidden_assets_included": False,
            "reference_solutions_included": False,
            "credential_values_included": False,
            "raw_host_paths_included": False,
        }
        reward_manifest = {
            **reward_base,
            "manifest_hash": content_hash(reward_base),
        }
        reward_path = temporary / "reward-manifest.json"
        atomic_dump_json(reward_path, reward_manifest)

        parent_weights = parent.loading_configuration.get("adapter_weights_sha256")
        if not isinstance(parent_weights, str):
            raise ConfigurationError("parent policy omits its adapter weight identity")
        training_base = {
            "schema_version": "1.0",
            "format_id": "verigym_rllm_verl_online_policy_export_report_v1",
            "status": "completed",
            "training_kind": "rllm_verigym_verl_online_grpo_lora",
            "learning_rate": learning_rate,
            "world_size": completion["world_size"],
            "software": completion["software"],
            "rllm_commit": completion["rllm_commit"],
            "verl_commit": completion["verl_commit"],
            "input_policy_version_hash": parent.version_hash,
            "input_policy_version_id": parent.policy_version_id,
            "input_weight_version": parent.weight_version,
            "output_weight_version": parent.weight_version + 1,
            "parent_adapter_weights_sha256": parent_weights,
            "task_manifest_hash": tasks["manifest_hash"],
            "reward_manifest_hash": reward_manifest["manifest_hash"],
            "online_completion_report_hash": completion["report_hash"],
            "online_broker_report_hash": broker["report_hash"],
            "checkpoint_step": step,
            "rollout_count": completion["rollout_count"],
            "resolved_count": completion["resolved_count"],
            "reward_variance_group_count": completion["reward_variance_group_count"],
            "adapter_changed_tensor_count": completion["adapter_changed_tensor_count"],
            "adapter_max_abs_delta": completion["adapter_max_abs_delta"],
            "adapter_inventory": inventory,
            "adapter_artifact_hash": adapter_hash,
            "official_rllm_agent_trainer_used": True,
            "official_verl_ray_trainer_used": True,
            "full_ray_vllm_stack_qualified": True,
            "hidden_assets_loaded": False,
            "reference_solution_loaded": False,
            "credential_values_included": False,
            "raw_host_paths_included": False,
        }
        training_report = {
            **training_base,
            "report_hash": content_hash(training_base),
        }
        training_path = adapter / "training-report.json"
        atomic_dump_json(training_path, training_report)

        version = register_training_policy_version(
            output=temporary / "policy-version.json",
            policy_version_id=policy_version_id,
            weight_version=parent.weight_version + 1,
            update_type="verigym_grpo",
            model_id=parent.model_id,
            model_root=model_root,
            source_commit=str(completion["verigym_commit"]),
            loading_configuration={"format": "peft_lora_safetensors"},
            artifact=adapter,
            parent_manifest=parent_manifest,
            training_manifest=task_manifest,
            reward_manifest=reward_path,
            training_report=training_path,
        )
        os.replace(temporary, destination)
        return version
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


__all__ = ["export_online_policy_version"]
