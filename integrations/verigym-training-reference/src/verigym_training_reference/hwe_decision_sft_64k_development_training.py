"""Resolved-config boundary for the authorized 64K development canary."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Literal

from verigym.schemas.hwe_training import (
    HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
    HweDecisionSft64kDevelopmentTrainingPreregistration,
)

DevelopmentCanaryBranch = Literal["producer", "resume"]


def development_training_overrides(
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
) -> dict[str, Any]:
    """Translate the frozen recipe into veRL 0.8 FSDP2 settings."""

    optimizer = preregistration.optimizer
    profile = preregistration.profile
    return {
        "model": {
            "trust_remote_code": False,
            "enable_gradient_checkpointing": profile.gradient_checkpointing,
            "enable_activation_offload": profile.activation_offload,
            "use_remove_padding": profile.remove_padding,
            "lora_rank": profile.lora_rank,
            "lora_alpha": profile.lora_alpha,
            "target_modules": profile.lora_target_modules,
            "use_fused_kernels": profile.bounded_fused_vocabulary_head,
            "lora": {
                "rank": profile.lora_rank,
                "alpha": profile.lora_alpha,
                "dropout": profile.lora_dropout,
            },
        },
        "data": {
            "train_batch_size": profile.global_batch_size,
            "micro_batch_size_per_gpu": profile.micro_batch_size_per_gpu,
            "max_length": profile.max_length,
            "max_token_len_per_gpu": profile.max_token_len_per_gpu,
            "truncation": "error",
            "num_workers": profile.num_workers,
            "shuffle": False,
        },
        "engine": {
            "strategy": profile.strategy,
            "model_dtype": profile.precision,
            "dtype": "bfloat16",
            "seed": preregistration.determinism.seed,
            "param_offload": profile.parameter_offload,
            "optimizer_offload": profile.optimizer_offload,
            "ulysses_sequence_parallel_size": profile.ulysses_sequence_parallel_size,
            "use_torch_compile": profile.torch_compile,
        },
        "optim": {
            "optimizer": "AdamW",
            "optimizer_impl": "torch.optim",
            "lr": optimizer.learning_rate,
            "betas": list(optimizer.betas),
            "override_optimizer_config": {"eps": optimizer.epsilon},
            "weight_decay": optimizer.weight_decay,
            "lr_warmup_steps": optimizer.warmup_steps,
            "lr_warmup_steps_ratio": 0.0,
            "total_training_steps": preregistration.canary.optimizer_steps,
            "clip_grad": optimizer.max_grad_norm,
            "lr_scheduler_type": optimizer.scheduler,
        },
        "checkpoint": {"save_contents": [], "load_contents": []},
        "trainer": {
            "total_epochs": 1,
            "total_training_steps": preregistration.canary.optimizer_steps,
            "seed": preregistration.determinism.seed,
            "save_freq": -1,
            "test_freq": -1,
            "resume_mode": "disable",
            "resume_from_path": None,
            "nnodes": 1,
            "n_gpus_per_node": profile.world_size,
            "balance_batch": False,
        },
        "verigym_development_training": {
            "format_id": preregistration.format_id,
            "recipe_hash": preregistration.recipe_hash,
            "split_hash": preregistration.split.split_hash,
            "schedule_hash": preregistration.canary.schedule_hash,
            "sample_indices": list(preregistration.canary.schedule_indices),
            "sample_record_hashes": list(preregistration.canary.schedule_record_hashes),
            "heldout_indices": list(preregistration.split.heldout_record_indices),
            "execution_authorized": False,
        },
    }


def prepare_development_canary_branch_config(
    qualification_config: Any,
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    authorization: HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
    *,
    branch: DevelopmentCanaryBranch,
    checkpoint_root: str,
) -> dict[str, Any]:
    """Derive the producer or fresh-resume config from the frozen recipe."""

    resolved = _merge(
        _plain_mapping(qualification_config),
        development_training_overrides(preregistration),
    )
    checkpoint = resolved["checkpoint"]
    trainer = resolved["trainer"]
    metadata = resolved["verigym_development_training"]
    checkpoint["async_save"] = False
    checkpoint["strict"] = True
    trainer["default_local_dir"] = checkpoint_root
    trainer["default_hdfs_dir"] = None
    trainer["max_ckpt_to_keep"] = 1
    if branch == "producer":
        start_step, end_step = 1, 16
        checkpoint["save_contents"] = list(authorization.checkpoint_save_contents)
        checkpoint["load_contents"] = []
        trainer["resume_mode"] = "disable"
        trainer["resume_from_path"] = None
    elif branch == "resume":
        start_step, end_step = 17, 32
        checkpoint["save_contents"] = []
        checkpoint["load_contents"] = list(authorization.checkpoint_load_contents)
        trainer["resume_mode"] = "resume_path"
        trainer["resume_from_path"] = f"{checkpoint_root}/global_step_16"
    else:
        raise ValueError("development canary branch changed")
    metadata.update(
        {
            "execution_authorized": True,
            "authorization_hash": authorization.authorization_hash,
            "optimizer_steps_authorized": authorization.optimizer_steps_authorized,
            "checkpoint_resume_branch": branch,
            "start_step": start_step,
            "end_step": end_step,
            "checkpoint_global_step": authorization.checkpoint_global_step,
            "post_clip_global_norm_acceptance_lte": (
                authorization.post_clip_global_norm_acceptance_lte
            ),
        }
    )
    assert_development_canary_branch_config(
        resolved,
        preregistration=preregistration,
        authorization=authorization,
        branch=branch,
        checkpoint_root=checkpoint_root,
    )
    return resolved


def assert_development_canary_branch_config(
    config: Any,
    *,
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    authorization: HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
    branch: DevelopmentCanaryBranch,
    checkpoint_root: str,
) -> None:
    """Reject any resolved field that could change the canary mathematics or scope."""

    resolved = _plain_mapping(config)
    expected_base = development_training_overrides(preregistration)
    base_paths = (
        "model.trust_remote_code",
        "model.enable_gradient_checkpointing",
        "model.enable_activation_offload",
        "model.use_remove_padding",
        "model.lora_rank",
        "model.lora_alpha",
        "model.target_modules",
        "model.use_fused_kernels",
        "model.lora.rank",
        "model.lora.alpha",
        "model.lora.dropout",
        "data.train_batch_size",
        "data.micro_batch_size_per_gpu",
        "data.max_length",
        "data.max_token_len_per_gpu",
        "data.truncation",
        "data.num_workers",
        "data.shuffle",
        "engine.strategy",
        "engine.model_dtype",
        "engine.dtype",
        "engine.seed",
        "engine.param_offload",
        "engine.optimizer_offload",
        "engine.ulysses_sequence_parallel_size",
        "engine.use_torch_compile",
        "optim.optimizer",
        "optim.optimizer_impl",
        "optim.lr",
        "optim.betas",
        "optim.override_optimizer_config.eps",
        "optim.weight_decay",
        "optim.lr_warmup_steps",
        "optim.lr_warmup_steps_ratio",
        "optim.total_training_steps",
        "optim.clip_grad",
        "optim.lr_scheduler_type",
        "trainer.total_epochs",
        "trainer.total_training_steps",
        "trainer.seed",
        "trainer.save_freq",
        "trainer.test_freq",
        "trainer.nnodes",
        "trainer.n_gpus_per_node",
        "trainer.balance_batch",
        "verigym_development_training.format_id",
        "verigym_development_training.recipe_hash",
        "verigym_development_training.split_hash",
        "verigym_development_training.schedule_hash",
        "verigym_development_training.sample_indices",
        "verigym_development_training.sample_record_hashes",
        "verigym_development_training.heldout_indices",
    )
    for path in base_paths:
        if _nested_value(resolved, path) != _nested_value(expected_base, path):
            raise ValueError(f"development canary resolved config {path} changed")
    if authorization.recipe_hash != preregistration.recipe_hash:
        raise ValueError("development canary authorization recipe changed")
    if authorization.schedule_hash != preregistration.canary.schedule_hash:
        raise ValueError("development canary authorization schedule changed")
    if branch == "producer":
        expected_save = ["model", "optimizer", "extra"]
        expected_load: list[str] = []
        expected_mode = "disable"
        expected_resume = None
        start_step, end_step = 1, 16
    elif branch == "resume":
        expected_save = []
        expected_load = ["model", "optimizer", "extra"]
        expected_mode = "resume_path"
        expected_resume = f"{checkpoint_root}/global_step_16"
        start_step, end_step = 17, 32
    else:
        raise ValueError("development canary branch changed")
    expected_paths = {
        "checkpoint.save_contents": expected_save,
        "checkpoint.load_contents": expected_load,
        "checkpoint.async_save": False,
        "checkpoint.strict": True,
        "trainer.default_local_dir": checkpoint_root,
        "trainer.default_hdfs_dir": None,
        "trainer.max_ckpt_to_keep": 1,
        "trainer.resume_mode": expected_mode,
        "trainer.resume_from_path": expected_resume,
        "verigym_development_training.execution_authorized": True,
        "verigym_development_training.authorization_hash": authorization.authorization_hash,
        "verigym_development_training.optimizer_steps_authorized": 32,
        "verigym_development_training.checkpoint_resume_branch": branch,
        "verigym_development_training.start_step": start_step,
        "verigym_development_training.end_step": end_step,
        "verigym_development_training.checkpoint_global_step": 16,
        "verigym_development_training.post_clip_global_norm_acceptance_lte": 1.015625,
    }
    for path, expected in expected_paths.items():
        if _nested_value(resolved, path) != expected:
            raise ValueError(f"development canary resolved config {path} changed")


def _plain_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("development canary base config must be a mapping")
    return {str(key): _plain_value(item) for key, item in value.items()}


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    return copy.deepcopy(value)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge(current, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _nested_value(config: Any, path: str) -> Any:
    current = config
    for key in path.split("."):
        if isinstance(current, Mapping):
            if key not in current:
                raise ValueError(f"development canary config is missing {path}")
            current = current[key]
        else:
            if not hasattr(current, key):
                raise ValueError(f"development canary config is missing {path}")
            current = getattr(current, key)
    return current


__all__ = [
    "DevelopmentCanaryBranch",
    "assert_development_canary_branch_config",
    "development_training_overrides",
    "prepare_development_canary_branch_config",
]
