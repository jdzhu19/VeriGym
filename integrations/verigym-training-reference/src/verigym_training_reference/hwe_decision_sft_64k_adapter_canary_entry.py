"""Torchrun branch entry for the 32-step adapter-retention canary."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any

from .hwe_decision_sft_64k_checkpoint_resume_entry import (
    _configure_exact_replay_determinism,
    _normalize_host_rng_at_step_boundary,
    _state_receipt,
)
from .hwe_decision_sft_64k_development_canary_entry import (
    DevelopmentCanaryBranch,
    _branch_bounds,
    _make_data,
    _scheduled_steps,
    checkpoint_manifest,
)
from .hwe_decision_sft_64k_optimizer_smoke_entry import (
    _all_ranks_true,
    _global_gradient_stats,
    _guarded_checkpoint,
    _isolate_runtime,
    _local_trainable_parameter_hash,
    _optimizer_state_steps,
    _post_step_invariants,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", choices=("producer", "resume"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--rllm-source", type=Path, required=True)
    parser.add_argument("--verl-source", type=Path, required=True)
    parser.add_argument("--transformers-source", type=Path, required=True)
    return parser


def model_checkpoint_manifest(root: Path, *, global_step: int) -> dict[str, Any]:
    """Hash the model-only FSDP checkpoint used solely for compact adapter export."""

    step = root / f"global_step_{global_step}"
    resolved_root = root.resolve(strict=True)
    resolved = step.resolve(strict=True)
    if root.is_symlink() or step.is_symlink() or not resolved.is_relative_to(resolved_root):
        raise RuntimeError("adapter canary final checkpoint root is unsafe")
    files: list[dict[str, Any]] = []
    for path in sorted(resolved.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("adapter canary final checkpoint contains a symlink")
        if not path.is_file():
            continue
        digest = _sha256_file(path)
        files.append(
            {
                "relative_path": path.relative_to(resolved).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
    expected = {f"model_world_size_4_rank_{rank}.pt" for rank in range(4)}
    observed = {item["relative_path"] for item in files}
    if not expected.issubset(observed) or not any(
        value.startswith("huggingface/") for value in observed
    ):
        raise RuntimeError("adapter canary final checkpoint lacks model shards or HF metadata")
    if any(value.startswith(("optim_", "extra_state_")) for value in observed):
        raise RuntimeError("adapter canary final checkpoint exceeded model-only scope")
    identity = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "format_id": "verigym_hwe_adapter_canary_model_checkpoint_manifest_v1",
        "global_step": global_step,
        "file_count": len(files),
        "total_bytes": sum(int(item["size_bytes"]) for item in files),
        "checkpoint_hash": identity,
        "files": files,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run_branch(
    *,
    branch: DevelopmentCanaryBranch,
    config_path: Path,
    preregistration_path: Path,
    authorization_path: Path,
    checkpoint_root: Path,
    report: Path,
    scratch_root: Path,
    rllm_source: Path,
    verl_source: Path,
    transformers_source: Path,
) -> None:
    """Execute one exact 16-step branch and save only its authorized state."""

    rank_root = _isolate_runtime(scratch_root)
    import numpy as np
    import torch  # type: ignore[import-not-found]

    determinism = _configure_exact_replay_determinism(torch, os.environ)
    from omegaconf import OmegaConf  # type: ignore[import-not-found]
    from tensordict.tensorclass import NonTensorData  # type: ignore[import-not-found]
    from verigym.experiments.state import atomic_dump_json
    from verigym.hwe.deepseek_harness_adapter_canary import (
        load_adapter_canary_authorization,
    )
    from verigym.hwe.deepseek_harness_development_training import (
        load_development_training_preregistration,
    )
    from verl.trainer.sft_trainer import SFTTrainer  # type: ignore[import-not-found]
    from verl.utils import tensordict_utils as tu  # type: ignore[import-not-found]
    from verl.utils.device import auto_set_device  # type: ignore[import-not-found]
    from verl.utils.distributed import (  # type: ignore[import-not-found]
        destroy_global_process_group,
        initialize_global_process_group,
    )

    from .hwe_decision_sft_64k_adapter_canary_training import (
        assert_adapter_canary_branch_config,
    )
    from .hwe_decision_sft_64k_backend import validate_qualification_runtime

    runtime = validate_qualification_runtime(
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )
    preregistration = load_development_training_preregistration(preregistration_path)
    authorization = load_adapter_canary_authorization(authorization_path)
    config = OmegaConf.load(config_path)
    assert_adapter_canary_branch_config(
        config,
        preregistration=preregistration,
        authorization=authorization,
        branch=branch,
        checkpoint_root=str(checkpoint_root),
    )
    auto_set_device(config)
    initialize_global_process_group()
    rank = torch.distributed.get_rank()
    world_size = torch.distributed.get_world_size()
    if world_size != 4:
        raise RuntimeError("adapter canary requires world size 4")
    seed = preregistration.determinism.seed
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

    trainer: Any = None
    failure: BaseException | None = None
    actual_optimizer_steps = 0
    checkpoint_saves = 0
    started = time.monotonic()
    torch.cuda.reset_peak_memory_stats()
    try:
        trainer = SFTTrainer(config=config)
        start_step, end_step = _branch_bounds(branch)
        state_steps, state_count = _optimizer_state_steps(torch, trainer.engine.optimizer)
        if branch == "resume":
            if trainer.resume_global_step != 16 or state_steps != [16] or state_count <= 0:
                raise RuntimeError("adapter canary did not restore optimizer step 16")
            cursor = json.loads(
                (checkpoint_root / "global_step_16/verigym_schedule_cursor.json").read_text()
            )
            if (
                cursor.get("authorization_hash") != authorization.authorization_hash
                or cursor.get("schedule_hash") != authorization.schedule_hash
                or cursor.get("completed_step") != 16
                or cursor.get("next_step") != 17
            ):
                raise RuntimeError("adapter canary schedule cursor changed")
            actual_optimizer_steps = 16
        elif trainer.resume_global_step != 0 or state_steps or state_count != 0:
            raise RuntimeError("adapter canary producer unexpectedly restored state")

        original_optimizer_step = trainer.engine.optimizer.step

        def counted_optimizer_step(*args: Any, **kwargs: Any) -> Any:
            nonlocal actual_optimizer_steps
            if actual_optimizer_steps >= end_step:
                raise RuntimeError("adapter canary blocked an excess optimizer step")
            result = original_optimizer_step(*args, **kwargs)
            actual_optimizer_steps += 1
            return result

        trainer.engine.optimizer.step = counted_optimizer_step
        original_checkpoint_save = trainer.ckpt_handler.save_checkpoint

        def counted_checkpoint_save(*args: Any, **kwargs: Any) -> Any:
            nonlocal checkpoint_saves
            if checkpoint_saves >= 1:
                raise RuntimeError("adapter canary blocked an excess checkpoint")
            result = original_checkpoint_save(*args, **kwargs)
            checkpoint_saves += 1
            return result

        trainer.ckpt_handler.save_checkpoint = counted_checkpoint_save
        token_counts = [
            int(trainer.train_dataset[index]["input_ids"].shape[0])
            for index in range(len(trainer.train_dataset))
        ]
        if (
            len(token_counts) != 83
            or max(token_counts) != 50_117
            or sum(value > 32_768 for value in token_counts) != 19
        ):
            raise RuntimeError("adapter canary loader receipts changed")
        dataframe_hashes = [str(value) for value in trainer.train_dataset.dataframe["record_hash"]]
        for scheduled in _scheduled_steps(preregistration, branch):
            index = scheduled.source_v4_record_index
            if (
                token_counts[index] != scheduled.token_count
                or dataframe_hashes[index] != scheduled.source_v4_record_hash
            ):
                raise RuntimeError("adapter canary scheduled row changed")

        initial_receipt = _state_receipt(torch, trainer)
        previous_hash = initial_receipt["trainable_parameter_hash"]
        step_results: list[dict[str, Any]] = []
        for scheduled in _scheduled_steps(preregistration, branch):
            step_started = time.monotonic()
            torch.cuda.reset_peak_memory_stats()
            data = _make_data(trainer, config, tu, NonTensorData, scheduled.source_v4_record_index)
            with trainer.engine.train_mode(disable_auto_offload=False):
                trainer.engine.optimizer_zero_grad()
                before_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
                if before_hash != previous_hash:
                    raise RuntimeError("adapter canary parameters changed outside a step")
                output = trainer.engine.forward_backward_batch(
                    data, trainer.loss_fn, forward_only=False
                )
                losses = [float(value) for value in output.get("loss", [])]
                pre_clip = _global_gradient_stats(torch, trainer.engine.module)
                valid = (
                    bool(losses)
                    and all(math.isfinite(value) and value > 0.0 for value in losses)
                    and pre_clip["finite"]
                    and pre_clip["nonzero_on_every_rank"]
                    and pre_clip["global_norm"] > 0.0
                )
                if not _all_ranks_true(torch, valid):
                    raise RuntimeError("adapter canary produced invalid loss or gradients")
                engine_norm = float(trainer.engine.optimizer_step())
                post_clip = _global_gradient_stats(torch, trainer.engine.module)
                after_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
                optimizer_steps, optimizer_state_count = _optimizer_state_steps(
                    torch, trainer.engine.optimizer
                )
                invariants = _post_step_invariants(
                    actual_optimizer_steps=actual_optimizer_steps,
                    scheduled_step=scheduled.step,
                    engine_pre_clip_norm=engine_norm,
                    post_clip=post_clip,
                    post_clip_global_norm_limit=1.015625,
                    parameter_hash_before=before_hash,
                    parameter_hash_after=after_hash,
                    optimizer_state_steps=optimizer_steps,
                    optimizer_state_parameter_count=optimizer_state_count,
                    gradient_tensor_count=pre_clip["local_tensor_count"],
                )
                if not _all_ranks_true(torch, all(invariants.values())):
                    raise RuntimeError("adapter canary post-step invariant failed")
                trainer.engine.lr_scheduler_step()
                previous_hash = after_hash
            torch.cuda.synchronize()
            local = {
                "rank": rank,
                "step": scheduled.step,
                "record_index": scheduled.source_v4_record_index,
                "token_count": scheduled.token_count,
                "loss_values": losses,
                "parameter_hash_before": before_hash,
                "parameter_hash_after": after_hash,
                "post_step_invariants": invariants,
                "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                "peak_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
                "wall_seconds": time.monotonic() - step_started,
            }
            gathered: list[dict[str, Any] | None] = [None] * world_size
            torch.distributed.all_gather_object(gathered, local)
            if rank == 0:
                step_results.append(
                    {"step": scheduled.step, "rank_results": [item for item in gathered if item]}
                )
            _normalize_host_rng_at_step_boundary(
                engine_seed=seed,
                global_step=scheduled.step,
                random_module=random,
                numpy_module=np,
                torch_module=torch,
            )

        final_receipt = _state_receipt(torch, trainer)
        trainer.ckpt_handler.save_checkpoint(step=end_step)
        if rank == 0 and branch == "producer":
            atomic_dump_json(
                checkpoint_root / "global_step_16/verigym_schedule_cursor.json",
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_adapter_canary_schedule_cursor_v1",
                    "authorization_hash": authorization.authorization_hash,
                    "schedule_hash": authorization.schedule_hash,
                    "completed_step": 16,
                    "next_step": 17,
                },
            )
        torch.distributed.barrier()
        manifest = (
            checkpoint_manifest(checkpoint_root, global_step=16)
            if rank == 0 and branch == "producer"
            else model_checkpoint_manifest(checkpoint_root, global_step=32)
            if rank == 0
            else None
        )
        trainer.ckpt_handler.save_checkpoint = _guarded_checkpoint
        if checkpoint_saves != 1:
            raise RuntimeError("adapter canary did not write exactly one authorized checkpoint")

        initial_local = {"rank": rank, **initial_receipt}
        final_local = {"rank": rank, **final_receipt}
        gathered_initial: list[dict[str, Any] | None] = [None] * world_size
        gathered_final: list[dict[str, Any] | None] = [None] * world_size
        torch.distributed.all_gather_object(gathered_initial, initial_local)
        torch.distributed.all_gather_object(gathered_final, final_local)
        torch.distributed.barrier()
        if rank == 0:
            rank_steps = [item for value in step_results for item in value["rank_results"]]
            atomic_dump_json(
                report,
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_adapter_canary_branch_execution_v1",
                    "status": "passed",
                    "branch": branch,
                    "authorization_hash": authorization.authorization_hash,
                    "recipe_hash": preregistration.recipe_hash,
                    "start_step": start_step,
                    "end_step": end_step,
                    "optimizer_steps_observed": actual_optimizer_steps,
                    "optimizer_steps_executed_in_branch": 16,
                    "resume_global_step": trainer.resume_global_step,
                    "checkpoint_saves": checkpoint_saves,
                    "checkpoint_manifest": manifest,
                    "initial_rank_state": [item for item in gathered_initial if item],
                    "final_rank_state": [item for item in gathered_final if item],
                    "step_results": step_results,
                    "loader_rows_validated": 83,
                    "exact_receipts_revalidated": 83,
                    "over_32768_rows_validated": 19,
                    "max_token_count": 50_117,
                    "runtime": runtime,
                    "determinism": determinism,
                    "world_size": 4,
                    "peak_memory_allocated_bytes": max(
                        int(item["peak_memory_allocated_bytes"]) for item in rank_steps
                    ),
                    "peak_memory_reserved_bytes": max(
                        int(item["peak_memory_reserved_bytes"]) for item in rank_steps
                    ),
                    "execution_wall_seconds": time.monotonic() - started,
                    "adapter_written": False,
                    "production_training_ready": False,
                },
            )
    except BaseException as error:
        failure = error
        atomic_dump_json(
            rank_root / "failure.json",
            {
                "format_id": "verigym_hwe_adapter_canary_branch_failure_v1",
                "branch": branch,
                "rank": rank,
                "error_type": type(error).__name__,
                "error_message": str(error)[:1000],
                "optimizer_steps_observed": actual_optimizer_steps,
                "checkpoint_saves": checkpoint_saves,
                "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                "peak_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
            },
        )
    finally:
        try:
            if trainer is not None:
                trainer.engine.optimizer_zero_grad()
                trainer.engine.optimizer.step = _guarded_checkpoint
                trainer.ckpt_handler.save_checkpoint = _guarded_checkpoint
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
    if failure is not None:
        raise failure


def main() -> None:
    arguments = _parser().parse_args()
    run_branch(
        branch=arguments.branch,
        config_path=arguments.config,
        preregistration_path=arguments.preregistration,
        authorization_path=arguments.authorization,
        checkpoint_root=arguments.checkpoint_root,
        report=arguments.report,
        scratch_root=arguments.scratch_root,
        rllm_source=arguments.rllm_source,
        verl_source=arguments.verl_source,
        transformers_source=arguments.transformers_source,
    )


if __name__ == "__main__":
    main()


__all__ = ["model_checkpoint_manifest", "run_branch"]
