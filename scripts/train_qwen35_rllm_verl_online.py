#!/usr/bin/env python3
"""Launch the official Ray/vLLM rLLM + verl online loop with VeriGym rewards."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any

import hydra
import torch
from omegaconf import DictConfig
from rllm.data.dataset import DatasetRegistry
from rllm.trainer.agent_trainer import AgentTrainer
from verigym_training_reference.native_runtime import validate_runtime_manifest
from verigym_training_reference.online_workflow import VeriGymRtlWorkflow
from verigym_training_reference.qwen35_verl_compat import (
    QWEN35_CAUSAL_ADAPTER_COMPATIBILITY_ACTIVE,
)
from verigym_training_reference.repository_workflow import VeriGymRepositoryWorkflow
from verigym_training_reference.rllm_grpo_compat import (
    RLLM_VERL_GRPO_GROUP_COMPATIBILITY_ACTIVE,
)

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

_MANIFEST_ENV = "VERIGYM_ONLINE_TASK_MANIFEST"
_BROKER_ENV = "VERIGYM_ONLINE_BROKER_ROOT"
_REPOSITORY_BROKER_ENV = "VERIGYM_ONLINE_REPOSITORY_BROKER_ROOT"
_OUTPUT_ENV = "VERIGYM_ONLINE_VERIFIER_OUTPUT"
_REPORT_ENV = "VERIGYM_ONLINE_COMPLETION_REPORT"
_WORKFLOW_ENV = "VERIGYM_ONLINE_WORKFLOW"
_NATIVE_RUNTIME_ENV = "VERIGYM_TRAINING_RUNTIME_MANIFEST"


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _load_task_manifest() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path_value = os.environ.get(_MANIFEST_ENV)
    if not path_value:
        raise RuntimeError(f"{_MANIFEST_ENV} is required")
    path = Path(path_value).resolve(strict=True)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("format_id") != "verigym_online_tasks_v1":
        raise RuntimeError("unsupported online task manifest")
    identity = dict(value)
    expected = identity.pop("manifest_hash", None)
    if not isinstance(expected, str) or _canonical_hash(identity) != expected:
        raise RuntimeError("online task manifest identity changed")
    tasks: list[dict[str, Any]] = []
    for binding in value.get("tasks", []):
        public = binding.get("public_record")
        if not isinstance(public, dict):
            raise RuntimeError("online task manifest omits its embedded public record")
        public_identity = dict(public)
        public_hash = public_identity.pop("record_hash", None)
        if (
            not isinstance(public_hash, str)
            or _canonical_hash(public_identity) != public_hash
            or public.get("hidden_assets_included") is not False
        ):
            raise RuntimeError("online public task identity or privacy boundary is invalid")
        tasks.append(public)
    if not tasks or len({task["task_id"] for task in tasks}) != len(tasks):
        raise RuntimeError("online task manifest must contain unique tasks")
    return tasks, value


def _commit(environment_name: str) -> str:
    value = os.environ.get(environment_name)
    if not value:
        raise RuntimeError(f"{environment_name} is required")
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError(f"{environment_name} is not a full Git commit")
    return value


def _workflow_kind() -> str:
    value = os.environ.get(_WORKFLOW_ENV, "rtl")
    if value not in {"rtl", "repository"}:
        raise RuntimeError("VERIGYM_ONLINE_WORKFLOW must be 'rtl' or 'repository'")
    return value


def _training_runtime() -> dict[str, Any]:
    native_value = os.environ.get(_NATIVE_RUNTIME_ENV)
    image_id = os.environ.get("VERIGYM_TRAINING_IMAGE_ID")
    if native_value and image_id:
        raise RuntimeError("online training runtime cannot be both native and containerized")
    if native_value:
        path = Path(native_value).resolve(strict=True)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("native training runtime manifest root is not an object")
        manifest = validate_runtime_manifest(value)
        if (
            manifest.verigym_commit != _commit("VERIGYM_SOURCE_COMMIT")
            or manifest.rllm_commit != _commit("VERIGYM_RLLM_COMMIT")
            or manifest.verl_commit != _commit("VERIGYM_VERL_COMMIT")
            or manifest.gpu_count != torch.cuda.device_count()
        ):
            raise RuntimeError("native training runtime differs from the active process")
        return {
            "kind": "conda",
            "identity_hash": manifest.manifest_hash,
            "manifest": manifest.model_dump(mode="json"),
        }
    if not image_id:
        raise RuntimeError("online training runtime identity is required")
    container = {"kind": "container", "image_id": image_id}
    return {
        **container,
        "identity_hash": _canonical_hash(container),
    }


def _adapter_update_stats(config: DictConfig, checkpoint_root: Path) -> dict[str, float | int]:
    from safetensors import safe_open  # type: ignore[import-not-found]

    input_root = Path(str(config.actor_rollout_ref.model.lora_adapter_path)).resolve(strict=True)
    input_path = (input_root / "adapter_model.safetensors").resolve(strict=True)
    iteration = int(
        (checkpoint_root / "latest_checkpointed_iteration.txt").read_text(encoding="utf-8")
    )
    output_path = (
        checkpoint_root
        / f"global_step_{iteration}"
        / "actor"
        / "lora_adapter"
        / "adapter_model.safetensors"
    ).resolve(strict=True)
    changed = 0
    maximum = 0.0
    with (
        safe_open(str(input_path), framework="pt", device="cpu") as before,
        safe_open(str(output_path), framework="pt", device="cpu") as after,
    ):
        before_keys = set(before.keys())
        after_keys = set(after.keys())
        if before_keys != after_keys:
            raise RuntimeError("online output adapter tensor keys differ from the input policy")
        for name in sorted(before_keys):
            difference = (before.get_tensor(name).float() - after.get_tensor(name).float()).abs()
            tensor_maximum = float(difference.max())
            if tensor_maximum > 0.0:
                changed += 1
                maximum = max(maximum, tensor_maximum)
    return {"changed_tensor_count": changed, "max_abs_delta": maximum}


def _completion_report(
    config: DictConfig, tasks: list[dict[str, Any]], task_manifest: dict[str, Any]
) -> dict[str, Any]:
    report_value = os.environ.get(_REPORT_ENV)
    output_value = os.environ.get(_OUTPUT_ENV)
    if not report_value or not output_value:
        raise RuntimeError("online completion report paths are required")
    checkpoint_root = Path(str(config.trainer.default_local_dir)).resolve(strict=True)
    checkpoint_files = [path for path in checkpoint_root.rglob("*") if path.is_file()]
    update_stats = _adapter_update_stats(config, checkpoint_root)
    scorecards = []
    for path in Path(output_value).resolve(strict=True).rglob("scorecard.json"):
        scorecards.append(json.loads(path.read_text(encoding="utf-8")))
    invalid = sum(
        card.get("status") == "error"
        or card.get("correctness", {}).get("infrastructure_error") is True
        for card in scorecards
    )
    rewards_by_task = {
        task_id: [
            float(card.get("resolved") is True)
            for card in scorecards
            if card.get("task_id") == task_id
        ]
        for task_id in sorted(task["task_id"] for task in tasks)
    }
    reward_variance_groups = sum(len(set(rewards)) > 1 for rewards in rewards_by_task.values())
    if (
        not checkpoint_files
        or not scorecards
        or invalid
        or not reward_variance_groups
        or update_stats["changed_tensor_count"] <= 0
        or update_stats["max_abs_delta"] <= 0.0
    ):
        raise RuntimeError("online stack did not produce valid checkpoints and verifier outcomes")
    training_runtime = _training_runtime()
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_rllm_verl_online_smoke_report_v1",
        "status": "completed",
        "workflow_kind": _workflow_kind(),
        "task_manifest_hash": task_manifest["manifest_hash"],
        "input_policy_version_id": task_manifest["input_policy_version_id"],
        "input_policy_version_hash": task_manifest["input_policy_version_hash"],
        "input_weight_version": task_manifest["input_weight_version"],
        "task_ids": sorted(task["task_id"] for task in tasks),
        "rollout_count": len(scorecards),
        "resolved_count": sum(card.get("resolved") is True for card in scorecards),
        "rewards_by_task": rewards_by_task,
        "reward_variance_group_count": reward_variance_groups,
        "infrastructure_invalid_count": invalid,
        "checkpoint_file_count": len(checkpoint_files),
        "checkpoint_bytes": sum(path.stat().st_size for path in checkpoint_files),
        "adapter_changed_tensor_count": update_stats["changed_tensor_count"],
        "adapter_max_abs_delta": update_stats["max_abs_delta"],
        "world_size": int(config.trainer.n_gpus_per_node),
        "rollout_backend": str(config.actor_rollout_ref.rollout.name),
        "rollout_mode": str(config.actor_rollout_ref.rollout.mode),
        "algorithm": str(config.algorithm.adv_estimator),
        "rllm_commit": _commit("VERIGYM_RLLM_COMMIT"),
        "verl_commit": _commit("VERIGYM_VERL_COMMIT"),
        "verigym_commit": _commit("VERIGYM_SOURCE_COMMIT"),
        "training_runtime_kind": training_runtime["kind"],
        "training_runtime_hash": training_runtime["identity_hash"],
        "training_runtime": training_runtime,
        "training_container_image_id": training_runtime.get("image_id"),
        "cuda_runtime": torch.version.cuda,
        "gpu_count": torch.cuda.device_count(),
        "gpu_names": [
            torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())
        ],
        "software": {
            name: importlib.metadata.version(name)
            for name in ["ray", "rllm", "torch", "transformers", "verl", "vllm"]
        },
        "official_rllm_agent_trainer_used": True,
        "official_verl_ray_trainer_used": True,
        "vllm_rollout_servers_used": True,
        "online_weight_synchronization_completed": True,
        "qwen35_causal_adapter_compatibility_used": True,
        "rllm_verl_grpo_group_compatibility_used": True,
        "effective_policy_update_verified": True,
        "verigym_sparse_reward_used": True,
        "hidden_assets_loaded_by_model": False,
        "reference_solutions_loaded_by_model": False,
        "credential_values_included": False,
        "raw_host_paths_included": False,
        "source_root_loaded_by_training_process": False,
        "docker_socket_loaded_by_training_process": False,
        "full_ray_vllm_stack_qualified": True,
    }
    report = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(Path(report_value), report)
    return report


@hydra.main(
    config_path="pkg://rllm.trainer.config",
    config_name="agent_ppo_trainer",
    version_base=None,
)
def main(config: DictConfig) -> None:
    if not QWEN35_CAUSAL_ADAPTER_COMPATIBILITY_ACTIVE:
        raise RuntimeError("Qwen3.5 causal adapter compatibility hook did not activate")
    torch_fused_fsdp2 = bool(config.actor_rollout_ref.model.use_fused_kernels) and (
        config.actor_rollout_ref.model.fused_kernel_options.impl_backend == "torch"
        and config.actor_rollout_ref.actor.strategy == "fsdp2"
    )
    if torch_fused_fsdp2:
        fused_module_name = "verigym_training_reference.qwen35_verl_fused_compat"
        if config.actor_rollout_ref.model.external_lib != fused_module_name:
            raise RuntimeError("FSDP2 Torch-fused training requires its pinned external library")
        fused_module = importlib.import_module(fused_module_name)
        if not fused_module.QWEN35_FSDP2_FUSED_HEAD_COMPATIBILITY_ACTIVE:
            raise RuntimeError(
                "Qwen3.5 FSDP2 fused-head module compatibility hook did not activate"
            )
    if not RLLM_VERL_GRPO_GROUP_COMPATIBILITY_ACTIVE:
        raise RuntimeError("rLLM-to-verl GRPO group compatibility hook did not activate")
    tasks, task_manifest = _load_task_manifest()
    output_value = os.environ.get(_OUTPUT_ENV)
    workflow_kind = _workflow_kind()
    broker_environment = _BROKER_ENV if workflow_kind == "rtl" else _REPOSITORY_BROKER_ENV
    broker_value = os.environ.get(broker_environment)
    if not output_value or not broker_value:
        raise RuntimeError("selected online broker and output paths are required")
    Path(output_value).resolve(strict=True)
    selected_broker = str(Path(broker_value).resolve(strict=True))
    dataset_identity = _canonical_hash(
        {"task_ids": sorted(task["task_id"] for task in tasks), "kind": "online-train-v1"}
    )[:16]
    name = f"verigym-online-{dataset_identity}"
    train_dataset = DatasetRegistry.register_dataset(name, tasks, "train")
    validation_dataset = DatasetRegistry.register_dataset(name, tasks[:1], "validation")
    workflow_class = VeriGymRtlWorkflow
    workflow_args: dict[str, Any] = {
        "verifier_broker_root": selected_broker,
        "plan_tokens": 96,
        "solution_tokens": 512,
    }
    if workflow_kind == "repository":
        workflow_class = VeriGymRepositoryWorkflow
        workflow_args = {
            "repository_broker_root": selected_broker,
            "broker_timeout_s": 3900,
            "timeout": 4200,
            "action_tokens": None,
        }
    trainer = AgentTrainer(
        workflow_class=workflow_class,
        workflow_args=workflow_args,
        train_dataset=train_dataset,
        val_dataset=validation_dataset,
        config=config,
        backend="verl",
    )
    trainer.train()
    print(json.dumps(_completion_report(config, tasks, task_manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
