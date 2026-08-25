"""Resolved-config boundary for the preregistered 64K optimizer smoke."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Literal, NoReturn

from verigym.schemas.hwe_training import (
    HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization,
    HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
    HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerSmokeExecutionAuthorization,
    HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization,
    HweDecisionSft64kOptimizerSmokePreregistration,
)

OptimizerSmokeExecutionAuthorization = (
    HweDecisionSft64kOptimizerSmokeExecutionAuthorization
    | HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization
    | HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization
    | HweDecisionSft64kCheckpointResumeQualificationAuthorization
)

OptimizerDiagnosticReplayAuthorization = (
    HweDecisionSft64kOptimizerDiagnosticReplayAuthorization
    | HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization
    | HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization
)


def optimizer_smoke_overrides(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
) -> dict[str, Any]:
    """Translate the sealed recipe into veRL 0.8 FSDP2 config fields."""

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
            "seed": preregistration.seed,
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
            "total_training_steps": preregistration.step_count,
            "clip_grad": optimizer.max_grad_norm,
            "lr_scheduler_type": optimizer.scheduler,
        },
        "checkpoint": {"save_contents": [], "load_contents": []},
        "trainer": {
            "total_epochs": 1,
            "total_training_steps": preregistration.step_count,
            "seed": preregistration.seed,
            "save_freq": -1,
            "test_freq": -1,
            "resume_mode": "disable",
            "resume_from_path": None,
            "nnodes": 1,
            "n_gpus_per_node": profile.world_size,
            "balance_batch": False,
        },
        "verigym_optimizer_smoke": {
            "format_id": preregistration.format_id,
            "preregistration_hash": preregistration.preregistration_hash,
            "schedule_hash": preregistration.schedule_hash,
            "sample_indices": [item.source_v4_record_index for item in preregistration.schedule],
            "sample_record_hashes": [
                item.source_v4_record_hash for item in preregistration.schedule
            ],
            "execution_authorized": False,
        },
    }


def prepare_optimizer_smoke_config(
    qualification_config: Any,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
) -> dict[str, Any]:
    """Merge to a plain mapping without importing the opt-in OmegaConf/GPU stack."""

    base = _plain_mapping(qualification_config)
    resolved = _merge(base, optimizer_smoke_overrides(preregistration))
    assert_optimizer_smoke_config(resolved, preregistration=preregistration)
    return resolved


def assert_optimizer_smoke_config(
    config: Any,
    *,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
) -> None:
    """Reject any resolved setting that changes the numerical smoke contract."""

    expected = optimizer_smoke_overrides(preregistration)
    paths = (
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
        "checkpoint.save_contents",
        "checkpoint.load_contents",
        "trainer.total_epochs",
        "trainer.total_training_steps",
        "trainer.seed",
        "trainer.save_freq",
        "trainer.test_freq",
        "trainer.resume_mode",
        "trainer.resume_from_path",
        "trainer.nnodes",
        "trainer.n_gpus_per_node",
        "trainer.balance_batch",
        "verigym_optimizer_smoke.format_id",
        "verigym_optimizer_smoke.preregistration_hash",
        "verigym_optimizer_smoke.schedule_hash",
        "verigym_optimizer_smoke.sample_indices",
        "verigym_optimizer_smoke.sample_record_hashes",
        "verigym_optimizer_smoke.execution_authorized",
    )
    for path in paths:
        actual = _nested_value(config, path)
        wanted = _nested_value(expected, path)
        if actual != wanted:
            raise ValueError(f"optimizer-smoke resolved config {path} changed")


def prepare_authorized_optimizer_smoke_config(
    qualification_config: Any,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    authorization: OptimizerSmokeExecutionAuthorization,
) -> dict[str, Any]:
    """Derive the sole executable config without altering the preregistration snapshot."""

    resolved = prepare_optimizer_smoke_config(qualification_config, preregistration)
    metadata = resolved["verigym_optimizer_smoke"]
    metadata["execution_authorized"] = True
    metadata["authorization_hash"] = authorization.authorization_hash
    metadata["preregistration_receipt_hash"] = authorization.preregistration_receipt_hash
    if isinstance(
        authorization,
        HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    ):
        metadata.update(
            {
                "bf16_tolerance_replay": True,
                "gradient_clip_target": authorization.gradient_clip_target,
                "post_clip_global_norm_relative_tolerance": (
                    authorization.post_clip_global_norm_relative_tolerance
                ),
                "post_clip_global_norm_acceptance_lte": (
                    authorization.post_clip_global_norm_acceptance_lte
                ),
                "tolerance_basis": authorization.tolerance_basis,
            }
        )
    assert_authorized_optimizer_smoke_config(
        resolved,
        preregistration=preregistration,
        authorization=authorization,
    )
    return resolved


def assert_authorized_optimizer_smoke_config(
    config: Any,
    *,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    authorization: OptimizerSmokeExecutionAuthorization,
) -> None:
    """Require both sealed identities and the narrowly scoped one-use authorization."""

    if authorization.preregistration_hash != preregistration.preregistration_hash:
        raise ValueError("optimizer-smoke authorization preregistration changed")
    if authorization.schedule_hash != preregistration.schedule_hash:
        raise ValueError("optimizer-smoke authorization schedule changed")
    if authorization.optimizer_steps_authorized != preregistration.step_count:
        raise ValueError("optimizer-smoke authorization step count changed")
    resolved = _plain_mapping(config)
    metadata = resolved.get("verigym_optimizer_smoke")
    if not isinstance(metadata, dict):
        raise ValueError("optimizer-smoke authorized config is missing metadata")
    expected_authorization = {
        "execution_authorized": True,
        "authorization_hash": authorization.authorization_hash,
        "preregistration_receipt_hash": authorization.preregistration_receipt_hash,
    }
    if isinstance(
        authorization,
        HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    ):
        expected_authorization.update(
            {
                "bf16_tolerance_replay": True,
                "gradient_clip_target": 1.0,
                "post_clip_global_norm_relative_tolerance": 0.015625,
                "post_clip_global_norm_acceptance_lte": 1.015625,
                "tolerance_basis": "two_bfloat16_eps_relative_rounding_margin",
            }
        )
    for key, expected in expected_authorization.items():
        if metadata.get(key) != expected:
            raise ValueError(f"optimizer-smoke authorized config {key} changed")
    metadata["execution_authorized"] = False
    for key in (
        "authorization_hash",
        "preregistration_receipt_hash",
        "bf16_tolerance_replay",
        "gradient_clip_target",
        "post_clip_global_norm_relative_tolerance",
        "post_clip_global_norm_acceptance_lte",
        "tolerance_basis",
    ):
        metadata.pop(key, None)
    assert_optimizer_smoke_config(resolved, preregistration=preregistration)


CheckpointResumeBranch = Literal["control", "producer", "resume"]


def prepare_checkpoint_resume_branch_config(
    qualification_config: Any,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    authorization: HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    *,
    branch: CheckpointResumeBranch,
    checkpoint_root: str,
) -> dict[str, Any]:
    """Derive one exact control, checkpoint-producer, or resumed branch config."""

    resolved = prepare_authorized_optimizer_smoke_config(
        qualification_config,
        preregistration,
        authorization,
    )
    checkpoint = resolved["checkpoint"]
    trainer = resolved["trainer"]
    metadata = resolved["verigym_optimizer_smoke"]
    checkpoint["async_save"] = False
    checkpoint["strict"] = True
    trainer["default_local_dir"] = checkpoint_root
    trainer["default_hdfs_dir"] = None
    trainer["max_ckpt_to_keep"] = 1
    start_step: int
    end_step: int
    if branch == "control":
        start_step, end_step = 1, authorization.control_optimizer_steps
        checkpoint["save_contents"] = []
        checkpoint["load_contents"] = []
        trainer["resume_mode"] = "disable"
        trainer["resume_from_path"] = None
    elif branch == "producer":
        start_step, end_step = 1, authorization.checkpoint_producer_optimizer_steps
        checkpoint["save_contents"] = list(authorization.checkpoint_save_contents)
        checkpoint["load_contents"] = []
        trainer["resume_mode"] = "disable"
        trainer["resume_from_path"] = None
    elif branch == "resume":
        start_step = authorization.checkpoint_global_step + 1
        end_step = authorization.checkpoint_global_step + authorization.resumed_optimizer_steps
        checkpoint["save_contents"] = []
        checkpoint["load_contents"] = list(authorization.checkpoint_load_contents)
        trainer["resume_mode"] = "resume_path"
        trainer["resume_from_path"] = (
            f"{checkpoint_root}/global_step_{authorization.checkpoint_global_step}"
        )
    else:
        raise ValueError("checkpoint/resume branch changed")
    metadata.update(
        {
            "checkpoint_resume_qualification": True,
            "checkpoint_resume_branch": branch,
            "checkpoint_resume_start_step": start_step,
            "checkpoint_resume_end_step": end_step,
            "checkpoint_global_step": authorization.checkpoint_global_step,
            "checkpoint_count_allowed": authorization.checkpoint_count_allowed,
        }
    )
    assert_checkpoint_resume_branch_config(
        resolved,
        preregistration=preregistration,
        authorization=authorization,
        branch=branch,
        checkpoint_root=checkpoint_root,
    )
    return resolved


def assert_checkpoint_resume_branch_config(
    config: Any,
    *,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    authorization: HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    branch: CheckpointResumeBranch,
    checkpoint_root: str,
) -> None:
    """Reject any branch config that exceeds the attempt-8 checkpoint boundary."""

    resolved = _plain_mapping(config)
    metadata = resolved.get("verigym_optimizer_smoke")
    if not isinstance(metadata, dict):
        raise ValueError("checkpoint/resume config is missing optimizer metadata")
    if branch == "control":
        expected_save: list[str] = []
        expected_load: list[str] = []
        expected_mode = "disable"
        expected_path = None
        start_step, end_step = 1, 4
    elif branch == "producer":
        expected_save = ["model", "optimizer", "extra"]
        expected_load = []
        expected_mode = "disable"
        expected_path = None
        start_step, end_step = 1, 2
    elif branch == "resume":
        expected_save = []
        expected_load = ["model", "optimizer", "extra"]
        expected_mode = "resume_path"
        expected_path = f"{checkpoint_root}/global_step_2"
        start_step, end_step = 3, 4
    else:
        raise ValueError("checkpoint/resume branch changed")
    expected_paths: dict[str, Any] = {
        "checkpoint.save_contents": expected_save,
        "checkpoint.load_contents": expected_load,
        "checkpoint.async_save": False,
        "checkpoint.strict": True,
        "trainer.default_local_dir": checkpoint_root,
        "trainer.default_hdfs_dir": None,
        "trainer.max_ckpt_to_keep": 1,
        "trainer.resume_mode": expected_mode,
        "trainer.resume_from_path": expected_path,
        "verigym_optimizer_smoke.checkpoint_resume_qualification": True,
        "verigym_optimizer_smoke.checkpoint_resume_branch": branch,
        "verigym_optimizer_smoke.checkpoint_resume_start_step": start_step,
        "verigym_optimizer_smoke.checkpoint_resume_end_step": end_step,
        "verigym_optimizer_smoke.checkpoint_global_step": 2,
        "verigym_optimizer_smoke.checkpoint_count_allowed": 1,
    }
    for path, expected in expected_paths.items():
        if _nested_value(resolved, path) != expected:
            raise ValueError(f"checkpoint/resume resolved config {path} changed")
    resolved["checkpoint"]["save_contents"] = []
    resolved["checkpoint"]["load_contents"] = []
    resolved["trainer"]["resume_mode"] = "disable"
    resolved["trainer"]["resume_from_path"] = None
    for key in (
        "checkpoint_resume_qualification",
        "checkpoint_resume_branch",
        "checkpoint_resume_start_step",
        "checkpoint_resume_end_step",
        "checkpoint_global_step",
        "checkpoint_count_allowed",
    ):
        metadata.pop(key, None)
    assert_authorized_optimizer_smoke_config(
        resolved,
        preregistration=preregistration,
        authorization=authorization,
    )


def prepare_authorized_optimizer_diagnostic_replay_config(
    qualification_config: Any,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    authorization: OptimizerDiagnosticReplayAuthorization,
) -> dict[str, Any]:
    """Derive an executable config that permits exactly the registered first step."""

    resolved = prepare_optimizer_smoke_config(qualification_config, preregistration)
    resolved["optim"]["total_training_steps"] = 1
    resolved["trainer"]["total_training_steps"] = 1
    metadata = resolved["verigym_optimizer_smoke"]
    metadata.update(
        {
            "execution_authorized": True,
            "diagnostic_replay": True,
            "authorization_hash": authorization.authorization_hash,
            "preregistration_receipt_hash": authorization.preregistration_receipt_hash,
            "optimizer_steps_authorized": authorization.optimizer_steps_authorized,
            "diagnostic_record_index": authorization.source_v4_record_index,
            "diagnostic_record_hash": authorization.source_v4_record_hash,
        }
    )
    if isinstance(authorization, HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization):
        metadata.update(
            {
                "bf16_tolerance_replay": True,
                "gradient_clip_target": authorization.gradient_clip_target,
                "post_clip_global_norm_relative_tolerance": (
                    authorization.post_clip_global_norm_relative_tolerance
                ),
                "post_clip_global_norm_acceptance_lte": (
                    authorization.post_clip_global_norm_acceptance_lte
                ),
                "tolerance_basis": authorization.tolerance_basis,
            }
        )
    assert_authorized_optimizer_diagnostic_replay_config(
        resolved,
        preregistration=preregistration,
        authorization=authorization,
    )
    return resolved


def assert_authorized_optimizer_diagnostic_replay_config(
    config: Any,
    *,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    authorization: OptimizerDiagnosticReplayAuthorization,
) -> None:
    """Reject an authorization/config pair that could reach a second optimizer step."""

    first_step = preregistration.schedule[0]
    if authorization.preregistration_hash != preregistration.preregistration_hash:
        raise ValueError("optimizer diagnostic authorization preregistration changed")
    if authorization.schedule_hash != preregistration.schedule_hash:
        raise ValueError("optimizer diagnostic authorization schedule changed")
    if authorization.optimizer_steps_authorized != 1:
        raise ValueError("optimizer diagnostic authorization must permit exactly one step")
    if (
        authorization.source_v4_record_index != first_step.source_v4_record_index
        or authorization.source_v4_record_hash != first_step.source_v4_record_hash
        or authorization.task_id != first_step.task_id
        or authorization.token_count != first_step.token_count
    ):
        raise ValueError("optimizer diagnostic authorization first record changed")
    resolved = _plain_mapping(config)
    metadata = resolved.get("verigym_optimizer_smoke")
    if not isinstance(metadata, dict):
        raise ValueError("optimizer diagnostic authorized config is missing metadata")
    expected = {
        "execution_authorized": True,
        "diagnostic_replay": True,
        "authorization_hash": authorization.authorization_hash,
        "preregistration_receipt_hash": authorization.preregistration_receipt_hash,
        "optimizer_steps_authorized": 1,
        "diagnostic_record_index": first_step.source_v4_record_index,
        "diagnostic_record_hash": first_step.source_v4_record_hash,
    }
    if isinstance(authorization, HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization):
        expected.update(
            {
                "bf16_tolerance_replay": True,
                "gradient_clip_target": 1.0,
                "post_clip_global_norm_relative_tolerance": 0.015625,
                "post_clip_global_norm_acceptance_lte": 1.015625,
                "tolerance_basis": "two_bfloat16_eps_relative_rounding_margin",
            }
        )
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"optimizer diagnostic authorized config {key} changed")
    if _nested_value(resolved, "optim.total_training_steps") != 1:
        raise ValueError("optimizer diagnostic authorized config optim step count changed")
    if _nested_value(resolved, "trainer.total_training_steps") != 1:
        raise ValueError("optimizer diagnostic authorized config trainer step count changed")
    resolved["optim"]["total_training_steps"] = preregistration.step_count
    resolved["trainer"]["total_training_steps"] = preregistration.step_count
    metadata["execution_authorized"] = False
    for key in (
        "diagnostic_replay",
        "authorization_hash",
        "preregistration_receipt_hash",
        "optimizer_steps_authorized",
        "diagnostic_record_index",
        "diagnostic_record_hash",
        "bf16_tolerance_replay",
        "gradient_clip_target",
        "post_clip_global_norm_relative_tolerance",
        "post_clip_global_norm_acceptance_lte",
        "tolerance_basis",
    ):
        metadata.pop(key, None)
    assert_optimizer_smoke_config(resolved, preregistration=preregistration)


def optimizer_diagnostic_clip_acceptance(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    authorization: OptimizerDiagnosticReplayAuthorization,
) -> tuple[float, float, float]:
    """Return the target, relative rounding margin, and effective limit."""

    target = preregistration.acceptance.post_clip_global_norm_lte
    if isinstance(authorization, HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization):
        return (
            authorization.gradient_clip_target,
            authorization.post_clip_global_norm_relative_tolerance,
            authorization.post_clip_global_norm_acceptance_lte,
        )
    return target, 0.0, target


def optimizer_smoke_clip_acceptance(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    authorization: OptimizerSmokeExecutionAuthorization,
) -> tuple[float, float, float]:
    """Return strict or explicitly authorized full-smoke clipping acceptance."""

    target = preregistration.acceptance.post_clip_global_norm_lte
    if isinstance(
        authorization,
        HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    ):
        return (
            authorization.gradient_clip_target,
            authorization.post_clip_global_norm_relative_tolerance,
            authorization.post_clip_global_norm_acceptance_lte,
        )
    return target, 0.0, target


def optimizer_diagnostic_execution_identity(
    authorization: OptimizerDiagnosticReplayAuthorization,
) -> tuple[str, str]:
    """Select the report format and scope for one diagnostic authorization."""

    if isinstance(
        authorization,
        HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization,
    ):
        return (
            "verigym_hwe_decision_sft_64k_optimizer_authorized_schedule_replay_execution_v1",
            "single_record_single_optimizer_step_authorized_schedule",
        )
    if isinstance(authorization, HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization):
        return (
            "verigym_hwe_decision_sft_64k_optimizer_bf16_tolerance_replay_execution_v1",
            "single_record_single_optimizer_step_bf16_tolerance",
        )
    return (
        "verigym_hwe_decision_sft_64k_optimizer_diagnostic_replay_execution_v1",
        "single_record_single_optimizer_step_diagnostic",
    )


def summarize_post_step_failure_diagnostics(
    rank_failures: list[dict[str, Any]],
    *,
    world_size: int,
) -> dict[str, Any]:
    """Collect only rank-bound diagnostic snapshots with a known format."""

    diagnostics: list[dict[str, Any]] = []
    diagnostic_ranks: set[int] = set()
    failed_invariant_names: set[str] = set()
    for failure in rank_failures:
        rank = failure.get("rank")
        diagnostic = failure.get("post_step_diagnostics")
        if (
            not isinstance(rank, int)
            or not isinstance(diagnostic, dict)
            or diagnostic.get("format_id") != "verigym_hwe_optimizer_smoke_post_step_diagnostics_v1"
            or diagnostic.get("rank") != rank
        ):
            continue
        invariants = diagnostic.get("invariants")
        if not isinstance(invariants, dict) or any(
            not isinstance(name, str) or not isinstance(passed, bool)
            for name, passed in invariants.items()
        ):
            continue
        diagnostics.append(diagnostic)
        diagnostic_ranks.add(rank)
        failed_invariant_names.update(name for name, passed in invariants.items() if not passed)
    return {
        "post_step_diagnostics_complete": (
            len(diagnostics) == world_size and diagnostic_ranks == set(range(world_size))
        ),
        "failed_post_step_invariants": sorted(failed_invariant_names),
        "post_step_diagnostics_by_rank": sorted(
            diagnostics,
            key=lambda value: int(value["rank"]),
        ),
    }


def run_optimizer_smoke() -> NoReturn:
    """Prevent a preregistration-only package from taking optimizer steps."""

    raise RuntimeError(
        "optimizer-smoke-v1 is preregistered but execution is not enabled by this entry"
    )


def _plain_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("optimizer-smoke base config must be a mapping")
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
                raise ValueError(f"optimizer-smoke resolved config is missing {path}")
            current = current[key]
        else:
            if not hasattr(current, key):
                raise ValueError(f"optimizer-smoke resolved config is missing {path}")
            current = getattr(current, key)
    return current


__all__ = [
    "CheckpointResumeBranch",
    "assert_checkpoint_resume_branch_config",
    "assert_authorized_optimizer_diagnostic_replay_config",
    "assert_authorized_optimizer_smoke_config",
    "assert_optimizer_smoke_config",
    "optimizer_smoke_overrides",
    "optimizer_smoke_clip_acceptance",
    "optimizer_diagnostic_clip_acceptance",
    "optimizer_diagnostic_execution_identity",
    "prepare_authorized_optimizer_smoke_config",
    "prepare_checkpoint_resume_branch_config",
    "prepare_authorized_optimizer_diagnostic_replay_config",
    "prepare_optimizer_smoke_config",
    "run_optimizer_smoke",
    "summarize_post_step_failure_diagnostics",
]
