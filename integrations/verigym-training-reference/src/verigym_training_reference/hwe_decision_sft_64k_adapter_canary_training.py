"""Resolved veRL configs for the hash-bound adapter-retention canary."""

from __future__ import annotations

from typing import Any

from verigym.hwe.deepseek_harness_adapter_canary import (
    HweDecisionSft64kAdapterCanaryAuthorization,
)
from verigym.schemas.hwe_training import HweDecisionSft64kDevelopmentTrainingPreregistration

from .hwe_decision_sft_64k_development_training import (
    DevelopmentCanaryBranch,
    _merge,
    _nested_value,
    _plain_mapping,
    development_training_overrides,
)


def prepare_adapter_canary_branch_config(
    qualification_config: Any,
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    authorization: HweDecisionSft64kAdapterCanaryAuthorization,
    *,
    branch: DevelopmentCanaryBranch,
    checkpoint_root: str,
) -> dict[str, Any]:
    """Keep the v1 training mathematics while allowing a model-only step-32 save."""

    resolved = _merge(
        _plain_mapping(qualification_config),
        development_training_overrides(preregistration),
    )
    checkpoint = resolved["checkpoint"]
    trainer = resolved["trainer"]
    metadata = resolved["verigym_development_training"]
    checkpoint.update({"async_save": False, "strict": True})
    trainer.update(
        {
            "default_local_dir": checkpoint_root,
            "default_hdfs_dir": None,
            "max_ckpt_to_keep": 2,
        }
    )
    if branch == "producer":
        start_step, end_step = 1, 16
        checkpoint["save_contents"] = list(authorization.step_16_checkpoint_contents)
        checkpoint["load_contents"] = []
        trainer["resume_mode"] = "disable"
        trainer["resume_from_path"] = None
    elif branch == "resume":
        start_step, end_step = 17, 32
        checkpoint["save_contents"] = list(authorization.step_32_checkpoint_contents)
        checkpoint["load_contents"] = list(authorization.step_16_checkpoint_contents)
        trainer["resume_mode"] = "resume_path"
        trainer["resume_from_path"] = f"{checkpoint_root}/global_step_16"
    else:
        raise ValueError("adapter canary branch changed")
    metadata.update(
        {
            "execution_authorized": True,
            "authorization_hash": authorization.authorization_hash,
            "optimizer_steps_authorized": 32,
            "checkpoint_resume_branch": branch,
            "start_step": start_step,
            "end_step": end_step,
            "checkpoint_global_step": 16,
            "post_clip_global_norm_acceptance_lte": 1.015625,
            "adapter_retention_canary": True,
        }
    )
    assert_adapter_canary_branch_config(
        resolved,
        preregistration=preregistration,
        authorization=authorization,
        branch=branch,
        checkpoint_root=checkpoint_root,
    )
    return resolved


def assert_adapter_canary_branch_config(
    config: Any,
    *,
    preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
    authorization: HweDecisionSft64kAdapterCanaryAuthorization,
    branch: DevelopmentCanaryBranch,
    checkpoint_root: str,
) -> None:
    """Fail closed on any field that could change training or artifact scope."""

    resolved = _plain_mapping(config)
    expected_base = development_training_overrides(preregistration)
    immutable_paths = (
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
        "optim.total_training_steps",
        "optim.clip_grad",
        "optim.lr_scheduler_type",
        "trainer.total_training_steps",
        "trainer.seed",
        "trainer.nnodes",
        "trainer.n_gpus_per_node",
        "verigym_development_training.recipe_hash",
        "verigym_development_training.split_hash",
        "verigym_development_training.schedule_hash",
        "verigym_development_training.sample_indices",
        "verigym_development_training.sample_record_hashes",
        "verigym_development_training.heldout_indices",
    )
    for path in immutable_paths:
        if _nested_value(resolved, path) != _nested_value(expected_base, path):
            raise ValueError(f"adapter canary resolved config {path} changed")
    if authorization.recipe_hash != preregistration.recipe_hash:
        raise ValueError("adapter canary recipe binding changed")
    if authorization.schedule_hash != preregistration.canary.schedule_hash:
        raise ValueError("adapter canary schedule binding changed")
    if branch == "producer":
        save, load, mode, resume, start, end = (
            ["model", "optimizer", "extra"],
            [],
            "disable",
            None,
            1,
            16,
        )
    elif branch == "resume":
        save, load, mode, resume, start, end = (
            ["model"],
            ["model", "optimizer", "extra"],
            "resume_path",
            f"{checkpoint_root}/global_step_16",
            17,
            32,
        )
    else:
        raise ValueError("adapter canary branch changed")
    expected = {
        "checkpoint.save_contents": save,
        "checkpoint.load_contents": load,
        "checkpoint.async_save": False,
        "checkpoint.strict": True,
        "trainer.default_local_dir": checkpoint_root,
        "trainer.default_hdfs_dir": None,
        "trainer.max_ckpt_to_keep": 2,
        "trainer.resume_mode": mode,
        "trainer.resume_from_path": resume,
        "verigym_development_training.execution_authorized": True,
        "verigym_development_training.authorization_hash": authorization.authorization_hash,
        "verigym_development_training.optimizer_steps_authorized": 32,
        "verigym_development_training.checkpoint_resume_branch": branch,
        "verigym_development_training.start_step": start,
        "verigym_development_training.end_step": end,
        "verigym_development_training.checkpoint_global_step": 16,
        "verigym_development_training.post_clip_global_norm_acceptance_lte": 1.015625,
        "verigym_development_training.adapter_retention_canary": True,
    }
    for path, value in expected.items():
        if _nested_value(resolved, path) != value:
            raise ValueError(f"adapter canary resolved config {path} changed")


__all__ = [
    "assert_adapter_canary_branch_config",
    "prepare_adapter_canary_branch_config",
]
