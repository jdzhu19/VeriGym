"""Torchrun entry for an authorized 64K HWE optimizer smoke or diagnostic replay."""

from __future__ import annotations

import argparse
import gc
import hashlib
import math
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--rllm-source", type=Path, required=True)
    parser.add_argument("--verl-source", type=Path, required=True)
    parser.add_argument("--transformers-source", type=Path, required=True)
    return parser


def _isolate_runtime(scratch_root: Path) -> Path:
    rank = os.environ.get("LOCAL_RANK") or os.environ.get("RANK") or "0"
    root = scratch_root.resolve(strict=True) / f"rank-{rank}"
    root.mkdir(mode=0o700, exist_ok=True)
    os.environ["TRITON_CACHE_DIR"] = str(root / "triton")
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(root / "inductor")
    os.environ["TMPDIR"] = str(root)
    os.environ["TEMP"] = str(root)
    os.environ["TMP"] = str(root)
    return root


def _guarded_checkpoint(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("optimizer-smoke guard blocked checkpoint or adapter mutation")


def _local_trainable_parameter_hash(torch_module: Any, module: Any) -> str:
    digest = hashlib.sha256()
    count = 0
    for name, parameter in sorted(module.named_parameters(), key=lambda item: item[0]):
        if not parameter.requires_grad:
            continue
        value = parameter.detach()
        if hasattr(value, "to_local"):
            value = value.to_local()
        payload = value.contiguous().view(torch_module.uint8).cpu().numpy().tobytes()
        encoded_name = name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(4, "big"))
        digest.update(encoded_name)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        count += 1
    if count == 0:
        raise RuntimeError("optimizer smoke found no trainable LoRA parameters")
    return digest.hexdigest()


def _global_gradient_stats(torch_module: Any, module: Any) -> dict[str, Any]:
    device = torch_module.device("cuda", torch_module.cuda.current_device())
    squared_norm = torch_module.zeros((), dtype=torch_module.float64, device=device)
    finite = torch_module.ones((), dtype=torch_module.int64, device=device)
    nonzero = torch_module.zeros((), dtype=torch_module.int64, device=device)
    local_count = 0
    with torch_module.no_grad():
        for parameter in module.parameters():
            if not parameter.requires_grad or parameter.grad is None:
                continue
            gradient = parameter.grad
            if hasattr(gradient, "to_local"):
                gradient = gradient.to_local()
            squared_norm.add_(gradient.double().square().sum())
            finite.mul_(torch_module.isfinite(gradient).all().to(dtype=torch_module.int64))
            nonzero = torch_module.maximum(
                nonzero,
                torch_module.count_nonzero(gradient).gt(0).to(torch_module.int64),
            )
            local_count += 1
    count = torch_module.tensor(local_count, dtype=torch_module.int64, device=device)
    torch_module.distributed.all_reduce(squared_norm, op=torch_module.distributed.ReduceOp.SUM)
    torch_module.distributed.all_reduce(count, op=torch_module.distributed.ReduceOp.SUM)
    torch_module.distributed.all_reduce(finite, op=torch_module.distributed.ReduceOp.MIN)
    torch_module.distributed.all_reduce(nonzero, op=torch_module.distributed.ReduceOp.MIN)
    return {
        "finite": bool(finite.item()),
        "nonzero_on_every_rank": bool(nonzero.item()),
        "local_tensor_count": local_count,
        "global_tensor_count": int(count.item()),
        "global_norm": math.sqrt(float(squared_norm.item())),
    }


def _optimizer_state_steps(torch_module: Any, optimizer: Any) -> tuple[list[int], int]:
    steps: list[int] = []
    for state in optimizer.state.values():
        if "step" not in state:
            continue
        value = state["step"]
        if hasattr(value, "to_local"):
            value = value.to_local()
        if isinstance(value, torch_module.Tensor):
            if value.numel() != 1:
                raise RuntimeError("optimizer smoke found a non-scalar AdamW step")
            raw = float(value.item())
        else:
            raw = float(value)
        if not raw.is_integer():
            raise RuntimeError("optimizer smoke found a fractional AdamW step")
        steps.append(int(raw))
    return sorted(set(steps)), len(steps)


def _post_step_invariants(
    *,
    actual_optimizer_steps: int,
    scheduled_step: int,
    engine_pre_clip_norm: float,
    post_clip: dict[str, Any],
    post_clip_global_norm_limit: float,
    parameter_hash_before: str,
    parameter_hash_after: str,
    optimizer_state_steps: list[int],
    optimizer_state_parameter_count: int,
    gradient_tensor_count: int,
) -> dict[str, bool]:
    """Name every local condition contributing to the post-step acceptance gate."""

    return {
        "optimizer_step_count_matches": actual_optimizer_steps == scheduled_step,
        "engine_pre_clip_norm_finite": math.isfinite(engine_pre_clip_norm),
        "engine_pre_clip_norm_positive": engine_pre_clip_norm > 0.0,
        "post_clip_gradients_finite": bool(post_clip["finite"]),
        "post_clip_gradients_nonzero_on_every_rank": bool(post_clip["nonzero_on_every_rank"]),
        "post_clip_global_norm_within_limit": (
            float(post_clip["global_norm"]) <= post_clip_global_norm_limit
        ),
        "trainable_parameter_hash_changed": parameter_hash_after != parameter_hash_before,
        "optimizer_state_step_matches": optimizer_state_steps == [scheduled_step],
        "optimizer_state_parameter_count_matches_gradient_count": (
            optimizer_state_parameter_count == gradient_tensor_count
        ),
    }


def _diagnostic_float(value: float) -> float | str:
    if math.isfinite(value):
        return value
    if math.isnan(value):
        return "nan"
    return "inf" if value > 0 else "-inf"


def _post_step_diagnostics(
    *,
    rank: int,
    scheduled: Any,
    invariants: dict[str, bool],
    actual_optimizer_steps: int,
    engine_pre_clip_norm: float,
    post_clip: dict[str, Any],
    post_clip_global_norm_target: float,
    post_clip_global_norm_relative_tolerance: float,
    post_clip_global_norm_acceptance_limit: float,
    parameter_hash_before: str,
    parameter_hash_after: str,
    optimizer_state_steps: list[int],
    optimizer_state_parameter_count: int,
    gradient_tensor_count: int,
    all_ranks_invariants_passed: bool,
) -> dict[str, Any]:
    observed_post_clip = dict(post_clip)
    observed_post_clip["global_norm"] = _diagnostic_float(float(post_clip["global_norm"]))
    return {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_optimizer_smoke_post_step_diagnostics_v1",
        "rank": rank,
        "step": scheduled.step,
        "source_v4_record_index": scheduled.source_v4_record_index,
        "source_v4_record_hash": scheduled.source_v4_record_hash,
        "token_count": scheduled.token_count,
        "invariants": invariants,
        "failed_local_invariants": sorted(
            name for name, passed in invariants.items() if not passed
        ),
        "all_local_invariants_passed": all(invariants.values()),
        "all_ranks_invariants_passed": all_ranks_invariants_passed,
        "observed": {
            "optimizer_steps": actual_optimizer_steps,
            "engine_pre_clip_global_norm": _diagnostic_float(engine_pre_clip_norm),
            "post_clip_gradients": observed_post_clip,
            "post_clip_global_norm_target": post_clip_global_norm_target,
            "post_clip_global_norm_relative_tolerance": (post_clip_global_norm_relative_tolerance),
            "post_clip_global_norm_acceptance_limit": (post_clip_global_norm_acceptance_limit),
            "parameter_hash_before": parameter_hash_before,
            "parameter_hash_after": parameter_hash_after,
            "optimizer_state_steps": optimizer_state_steps,
            "optimizer_state_parameter_count": optimizer_state_parameter_count,
            "gradient_tensor_count": gradient_tensor_count,
        },
    }


def _write_post_step_diagnostics(rank_root: Path, diagnostics: dict[str, Any]) -> Path:
    from verigym.experiments.state import atomic_dump_json

    step = diagnostics.get("step")
    if not isinstance(step, int) or not 1 <= step <= 8:
        raise RuntimeError("optimizer smoke post-step diagnostics has an invalid step")
    path = rank_root / f"step-{step:02d}-post-step-diagnostics.json"
    if path.exists() or path.is_symlink():
        raise RuntimeError("optimizer smoke post-step diagnostics already exists")
    atomic_dump_json(path, diagnostics)
    return path


def _all_ranks_true(torch_module: Any, value: bool) -> bool:
    device = torch_module.device("cuda", torch_module.cuda.current_device())
    flag = torch_module.tensor(int(value), dtype=torch_module.int64, device=device)
    torch_module.distributed.all_reduce(flag, op=torch_module.distributed.ReduceOp.MIN)
    return bool(flag.item())


def _authorized_execution_schedule(
    schedule: Sequence[Any],
    *,
    optimizer_steps_authorized: int,
) -> tuple[Any, ...]:
    """Bound both validation and execution loops to the authorization step count."""

    if optimizer_steps_authorized <= 0 or optimizer_steps_authorized > len(schedule):
        raise RuntimeError("optimizer authorization has an invalid step count")
    return tuple(schedule[:optimizer_steps_authorized])


def _batch_meta(config: Any, tokenizer: Any) -> dict[str, Any]:
    return {
        "use_remove_padding": True,
        "use_dynamic_bsz": False,
        "max_token_len_per_gpu": 16_384,
        "micro_batch_size_per_gpu": 1,
        "use_fused_kernels": True,
        "temperature": 1.0,
        "global_batch_size": 1,
        "pad_mode": config.data.pad_mode,
        "pad_token_id": tokenizer.pad_token_id,
    }


def _write_rank_failure(
    rank_root: Path,
    *,
    rank: int,
    error: BaseException,
    optimizer_steps: int,
    torch_module: Any,
    post_step_diagnostics: dict[str, Any] | None,
) -> None:
    from verigym.experiments.state import atomic_dump_json

    atomic_dump_json(
        rank_root / "failure.json",
        {
            "rank": rank,
            "error_type": type(error).__name__,
            "error_message": str(error)[:1000],
            "optimizer_steps_observed": optimizer_steps,
            "peak_memory_allocated_bytes": int(torch_module.cuda.max_memory_allocated()),
            "peak_memory_reserved_bytes": int(torch_module.cuda.max_memory_reserved()),
            "post_step_diagnostics": post_step_diagnostics,
        },
    )


def run_optimizer_smoke(
    config_path: Path,
    preregistration_path: Path,
    authorization_path: Path,
    report: Path,
    scratch_root: Path,
    rllm_source: Path,
    verl_source: Path,
    transformers_source: Path,
) -> None:
    """Revalidate every loader row, then perform exactly eight guarded AdamW steps."""

    rank_root = _isolate_runtime(scratch_root)
    from .hwe_decision_sft_64k_backend import validate_qualification_runtime
    from .hwe_decision_sft_64k_optimizer_smoke import (
        assert_authorized_optimizer_diagnostic_replay_config,
        assert_authorized_optimizer_smoke_config,
        optimizer_diagnostic_clip_acceptance,
        optimizer_diagnostic_execution_identity,
        optimizer_smoke_clip_acceptance,
    )

    runtime = validate_qualification_runtime(
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )
    import torch  # type: ignore[import-not-found]
    from omegaconf import OmegaConf  # type: ignore[import-not-found]
    from tensordict.tensorclass import NonTensorData  # type: ignore[import-not-found]
    from verigym.experiments.state import atomic_dump_json
    from verigym.hwe.deepseek_harness_optimizer_smoke import (
        load_optimizer_smoke_execution_authorization,
        load_optimizer_smoke_preregistration,
    )
    from verigym.schemas.hwe_training import (
        HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
    )
    from verl.trainer.sft_trainer import SFTTrainer  # type: ignore[import-not-found]
    from verl.utils import tensordict_utils as tu  # type: ignore[import-not-found]
    from verl.utils.device import auto_set_device  # type: ignore[import-not-found]
    from verl.utils.distributed import (  # type: ignore[import-not-found]
        destroy_global_process_group,
        initialize_global_process_group,
    )

    preregistration = load_optimizer_smoke_preregistration(preregistration_path)
    authorization = load_optimizer_smoke_execution_authorization(authorization_path)
    config = OmegaConf.load(config_path)
    if isinstance(authorization, HweDecisionSft64kOptimizerDiagnosticReplayAuthorization):
        assert_authorized_optimizer_diagnostic_replay_config(
            config,
            preregistration=preregistration,
            authorization=authorization,
        )
    else:
        assert_authorized_optimizer_smoke_config(
            config,
            preregistration=preregistration,
            authorization=authorization,
        )
    is_diagnostic = isinstance(
        authorization,
        HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
    )
    if isinstance(authorization, HweDecisionSft64kOptimizerDiagnosticReplayAuthorization):
        (
            post_clip_global_norm_target,
            post_clip_global_norm_relative_tolerance,
            post_clip_global_norm_acceptance_limit,
        ) = optimizer_diagnostic_clip_acceptance(preregistration, authorization)
        diagnostic_format_id, diagnostic_scope = optimizer_diagnostic_execution_identity(
            authorization
        )
    else:
        (
            post_clip_global_norm_target,
            post_clip_global_norm_relative_tolerance,
            post_clip_global_norm_acceptance_limit,
        ) = optimizer_smoke_clip_acceptance(preregistration, authorization)
        diagnostic_format_id = ""
        diagnostic_scope = ""
    required_step_count = authorization.optimizer_steps_authorized
    scheduled_steps = _authorized_execution_schedule(
        preregistration.schedule,
        optimizer_steps_authorized=required_step_count,
    )
    if len(scheduled_steps) != required_step_count:
        raise RuntimeError("optimizer execution schedule differs from its authorized step count")
    auto_set_device(config)
    initialize_global_process_group()
    rank = torch.distributed.get_rank()
    world_size = torch.distributed.get_world_size()
    if world_size != 4:
        raise RuntimeError(f"64K optimizer smoke requires world size 4; found {world_size}")

    trainer: Any = None
    sample: Any = None
    batch: Any = None
    data: Any = None
    output: Any = None
    report_payload: dict[str, Any] | None = None
    failure: BaseException | None = None
    last_post_step_diagnostics: dict[str, Any] | None = None
    actual_optimizer_steps = 0
    execution_started = time.monotonic()
    torch.cuda.reset_peak_memory_stats()
    try:
        trainer = SFTTrainer(config=config)
        trainer.ckpt_handler.save_checkpoint = _guarded_checkpoint
        original_optimizer_step = trainer.engine.optimizer.step

        def counted_optimizer_step(*args: Any, **kwargs: Any) -> Any:
            nonlocal actual_optimizer_steps
            if actual_optimizer_steps >= required_step_count:
                raise RuntimeError("optimizer guard blocked a step beyond its authorization")
            result = original_optimizer_step(*args, **kwargs)
            actual_optimizer_steps += 1
            return result

        trainer.engine.optimizer.step = counted_optimizer_step

        token_counts = [
            int(trainer.train_dataset[index]["input_ids"].shape[0])
            for index in range(len(trainer.train_dataset))
        ]
        if (
            len(token_counts) != 83
            or max(token_counts) != 50_117
            or sum(value > 32_768 for value in token_counts) != 19
        ):
            raise RuntimeError("actual veRL loader did not revalidate all frozen 64K receipts")
        dataframe_hashes = [str(value) for value in trainer.train_dataset.dataframe["record_hash"]]
        for scheduled in scheduled_steps:
            index = scheduled.source_v4_record_index
            if (
                token_counts[index] != scheduled.token_count
                or dataframe_hashes[index] != scheduled.source_v4_record_hash
            ):
                raise RuntimeError(f"optimizer smoke scheduled row {scheduled.step} drifted")

        loader_wall = time.monotonic() - execution_started
        initial_parameter_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
        previous_parameter_hash = initial_parameter_hash
        step_results: list[dict[str, Any]] = []
        for scheduled in scheduled_steps:
            torch.cuda.reset_peak_memory_stats()
            step_started = time.monotonic()
            sample = trainer.train_dataset[scheduled.source_v4_record_index]
            batch = trainer.collate_fn([sample])
            data = tu.get_tensordict(
                tensor_dict=batch,
                non_tensor_dict=_batch_meta(config, trainer.model_config.tokenizer),
            )
            batch_seqlens = trainer._get_batch_seqlens(data=data)
            tu.assign_non_tensor(
                data,
                update_lr_scheduler=False,
                global_token_num=NonTensorData(batch_seqlens),
            )

            with trainer.engine.train_mode(disable_auto_offload=False):
                trainer.engine.optimizer_zero_grad()
                before_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
                if before_hash != previous_parameter_hash:
                    raise RuntimeError("trainable parameters changed outside an optimizer step")
                output = trainer.engine.forward_backward_batch(
                    data,
                    trainer.loss_fn,
                    forward_only=False,
                )
                losses = [float(value) for value in output.get("loss", [])]
                losses_valid = bool(losses) and all(
                    math.isfinite(value) and value > 0.0 for value in losses
                )
                pre_clip = _global_gradient_stats(torch, trainer.engine.module)
                gradients_valid = (
                    pre_clip["finite"]
                    and pre_clip["nonzero_on_every_rank"]
                    and pre_clip["global_norm"] > 0.0
                    and pre_clip["local_tensor_count"] > 0
                )
                if not _all_ranks_true(torch, losses_valid and gradients_valid):
                    raise RuntimeError(
                        f"optimizer smoke step {scheduled.step} produced invalid loss or gradients"
                    )
                engine_pre_clip_norm = float(trainer.engine.optimizer_step())
                post_clip = _global_gradient_stats(torch, trainer.engine.module)
                after_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
                state_steps, state_parameter_count = _optimizer_state_steps(
                    torch,
                    trainer.engine.optimizer,
                )
                post_step_invariants = _post_step_invariants(
                    actual_optimizer_steps=actual_optimizer_steps,
                    scheduled_step=scheduled.step,
                    engine_pre_clip_norm=engine_pre_clip_norm,
                    post_clip=post_clip,
                    post_clip_global_norm_limit=post_clip_global_norm_acceptance_limit,
                    parameter_hash_before=before_hash,
                    parameter_hash_after=after_hash,
                    optimizer_state_steps=state_steps,
                    optimizer_state_parameter_count=state_parameter_count,
                    gradient_tensor_count=pre_clip["local_tensor_count"],
                )
                all_ranks_post_step_valid = _all_ranks_true(
                    torch,
                    all(post_step_invariants.values()),
                )
                last_post_step_diagnostics = _post_step_diagnostics(
                    rank=rank,
                    scheduled=scheduled,
                    invariants=post_step_invariants,
                    actual_optimizer_steps=actual_optimizer_steps,
                    engine_pre_clip_norm=engine_pre_clip_norm,
                    post_clip=post_clip,
                    post_clip_global_norm_target=post_clip_global_norm_target,
                    post_clip_global_norm_relative_tolerance=(
                        post_clip_global_norm_relative_tolerance
                    ),
                    post_clip_global_norm_acceptance_limit=(post_clip_global_norm_acceptance_limit),
                    parameter_hash_before=before_hash,
                    parameter_hash_after=after_hash,
                    optimizer_state_steps=state_steps,
                    optimizer_state_parameter_count=state_parameter_count,
                    gradient_tensor_count=pre_clip["local_tensor_count"],
                    all_ranks_invariants_passed=all_ranks_post_step_valid,
                )
                _write_post_step_diagnostics(rank_root, last_post_step_diagnostics)
                if not all_ranks_post_step_valid:
                    raise RuntimeError(
                        f"optimizer smoke step {scheduled.step} failed its post-step invariants"
                    )
                last_post_step_diagnostics = None
                learning_rate = float(trainer.engine.lr_scheduler_step())
                previous_parameter_hash = after_hash

            torch.cuda.synchronize()
            local_result = {
                "rank": rank,
                "parameter_hash_before": before_hash,
                "parameter_hash_after": after_hash,
                "parameter_hash_changed": before_hash != after_hash,
                "loss_values": losses,
                "losses_finite_positive": losses_valid,
                "pre_clip_gradients": pre_clip,
                "engine_pre_clip_global_norm": engine_pre_clip_norm,
                "post_clip_gradients": post_clip,
                "post_clip_global_norm_target": post_clip_global_norm_target,
                "post_clip_global_norm_relative_tolerance": (
                    post_clip_global_norm_relative_tolerance
                ),
                "post_clip_global_norm_acceptance_limit": (post_clip_global_norm_acceptance_limit),
                "optimizer_state_steps": state_steps,
                "optimizer_state_parameter_count": state_parameter_count,
                "post_step_invariants": post_step_invariants,
                "optimizer_steps_observed": actual_optimizer_steps,
                "learning_rate": learning_rate,
                "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                "peak_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
                "wall_seconds": time.monotonic() - step_started,
            }
            gathered: list[dict[str, Any] | None] = [None] * world_size
            torch.distributed.all_gather_object(gathered, local_result)
            if rank == 0:
                step_results.append(
                    {
                        "step": scheduled.step,
                        "source_v4_record_index": scheduled.source_v4_record_index,
                        "source_v4_record_hash": scheduled.source_v4_record_hash,
                        "task_id": scheduled.task_id,
                        "token_count": scheduled.token_count,
                        "role": scheduled.role,
                        "rank_results": [item for item in gathered if item is not None],
                    }
                )

        final_parameter_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
        final_state_steps, final_state_parameter_count = _optimizer_state_steps(
            torch,
            trainer.engine.optimizer,
        )
        final_valid = (
            actual_optimizer_steps == required_step_count
            and final_parameter_hash != initial_parameter_hash
            and final_state_steps == [required_step_count]
            and final_state_parameter_count > 0
        )
        if not _all_ranks_true(torch, final_valid):
            raise RuntimeError(
                "optimizer smoke final parameter or optimizer-state invariant failed"
            )
        torch.distributed.barrier()
        execution_wall = time.monotonic() - execution_started
        repeat_step_4 = 0
        repeat_step_8 = 0
        repeat_delta = 0
        if rank == 0 and not is_diagnostic:
            repeat_step_4 = max(
                item["peak_memory_reserved_bytes"] for item in step_results[3]["rank_results"]
            )
            repeat_step_8 = max(
                item["peak_memory_reserved_bytes"] for item in step_results[7]["rank_results"]
            )
            repeat_delta = abs(repeat_step_8 - repeat_step_4)
        repeat_valid = is_diagnostic or (
            rank != 0
            or repeat_delta <= preregistration.acceptance.repeat_peak_reserved_delta_max_bytes
        )
        if not _all_ranks_true(torch, repeat_valid):
            raise RuntimeError("optimizer smoke repeated-longest memory delta exceeded 1 GiB")
        if rank == 0:
            all_rank_results = [
                item for step_result in step_results for item in step_result["rank_results"]
            ]
            report_payload = {
                "schema_version": "1.0",
                "format_id": (
                    diagnostic_format_id
                    if is_diagnostic
                    else "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_v1"
                ),
                "status": "passed",
                "scope": (
                    diagnostic_scope
                    if is_diagnostic
                    else "development_optimizer_numerical_smoke_only"
                ),
                "diagnostic_replay": is_diagnostic,
                "diagnostic_replay_passed": is_diagnostic,
                "bf16_tolerance_replay": post_clip_global_norm_relative_tolerance > 0.0,
                "gradient_clip_target": post_clip_global_norm_target,
                "post_clip_global_norm_relative_tolerance": (
                    post_clip_global_norm_relative_tolerance
                ),
                "post_clip_global_norm_acceptance_lte": (post_clip_global_norm_acceptance_limit),
                "optimizer_steps_authorized": required_step_count,
                "optimizer_step_guard_limit": required_step_count,
                "second_optimizer_step_blocked_by_guard": is_diagnostic,
                "preregistration_hash": preregistration.preregistration_hash,
                "preregistration_config_sha256": authorization.preregistration_config_sha256,
                "preregistration_receipt_hash": authorization.preregistration_receipt_hash,
                "authorization_hash": authorization.authorization_hash,
                "authorization_format_id": authorization.format_id,
                "authorization_attempt": getattr(authorization, "attempt", 1),
                "replaces_authorization_hash": getattr(
                    authorization,
                    "replaces_authorization_hash",
                    None,
                ),
                "source_v3_dataset_hash": preregistration.source_v3_dataset_hash,
                "source_v4_dataset_hash": preregistration.source_v4_dataset_hash,
                "source_v4_manifest_sha256": preregistration.source_v4_manifest_sha256,
                "source_v4_train_jsonl_sha256": preregistration.source_v4_train_jsonl_sha256,
                "schedule_hash": preregistration.schedule_hash,
                "loader_ready": True,
                "loader_rows_validated": len(token_counts),
                "exact_receipts_revalidated": len(token_counts),
                "over_32768_rows_validated": sum(value > 32_768 for value in token_counts),
                "max_token_count": max(token_counts),
                "gpu_smoke_passed": True,
                "development_training_ready": not is_diagnostic,
                "production_training_ready": False,
                "training_started": True,
                "optimizer_steps": actual_optimizer_steps,
                "trainable_parameter_hash_changed": True,
                "optimizer_state_steps_final": final_state_steps,
                "checkpoint_written": False,
                "adapter_written": False,
                "checkpoint_resume_validation_deferred": True,
                "offload_used": False,
                "truncation_used": False,
                "bounded_fused_vocabulary_head": True,
                "global_shift_labels_used": True,
                "runtime": runtime,
                "world_size": world_size,
                "ulysses_sequence_parallel_size": 4,
                "existing_lsf_job_id": preregistration.existing_lsf_job_id,
                "host": preregistration.planned_host,
                "selected_gpu_indices": list(preregistration.selected_gpu_indices),
                "new_hpc_jobs_submitted": False,
                "existing_allocation_modified": False,
                "allocation_released": False,
                "loader_wall_seconds": loader_wall,
                "step_results": step_results,
                "longest_repeat_peak_reserved_bytes": {
                    "step_4": repeat_step_4,
                    "step_8": repeat_step_8,
                    "absolute_delta": repeat_delta,
                    "allowed_delta": (
                        preregistration.acceptance.repeat_peak_reserved_delta_max_bytes
                    ),
                },
                "longest_repeat_validation_deferred": is_diagnostic,
                "peak_memory_allocated_bytes": max(
                    item["peak_memory_allocated_bytes"] for item in all_rank_results
                ),
                "peak_memory_reserved_bytes": max(
                    item["peak_memory_reserved_bytes"] for item in all_rank_results
                ),
                "execution_wall_seconds": execution_wall,
                "gpu_seconds": execution_wall * world_size,
                "benchmark_score_claimed": False,
            }
    except BaseException as exc:
        failure = exc
        _write_rank_failure(
            rank_root,
            rank=rank,
            error=exc,
            optimizer_steps=actual_optimizer_steps,
            torch_module=torch,
            post_step_diagnostics=last_post_step_diagnostics,
        )
    finally:
        try:
            if trainer is not None:
                trainer.engine.optimizer_zero_grad()
                trainer.engine.optimizer.step = _guarded_checkpoint
            output = None
            data = None
            batch = None
            sample = None
            trainer = None
            gc.collect()
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            if failure is None:
                torch.distributed.barrier()
            destroy_global_process_group()
        except BaseException as cleanup_error:
            if failure is None:
                failure = cleanup_error
                _write_rank_failure(
                    rank_root,
                    rank=rank,
                    error=cleanup_error,
                    optimizer_steps=actual_optimizer_steps,
                    torch_module=torch,
                    post_step_diagnostics=last_post_step_diagnostics,
                )
    if failure is not None:
        raise failure
    if rank == 0:
        if report_payload is None:
            raise RuntimeError("optimizer smoke completed without a report payload")
        atomic_dump_json(report, report_payload)


def main() -> None:
    arguments = _parser().parse_args()
    run_optimizer_smoke(
        arguments.config,
        arguments.preregistration,
        arguments.authorization,
        arguments.report,
        arguments.scratch_root,
        arguments.rllm_source,
        arguments.verl_source,
        arguments.transformers_source,
    )


if __name__ == "__main__":
    main()
