"""Torchrun branch entry for the authorized 32-step development canary."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import random
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .hwe_decision_sft_64k_checkpoint_resume_entry import (
    _configure_exact_replay_determinism,
    _normalize_host_rng_at_step_boundary,
    _state_receipt,
)
from .hwe_decision_sft_64k_optimizer_smoke_entry import (
    _all_ranks_true,
    _batch_meta,
    _global_gradient_stats,
    _guarded_checkpoint,
    _isolate_runtime,
    _local_trainable_parameter_hash,
    _optimizer_state_steps,
    _post_step_invariants,
)

DevelopmentCanaryBranch = Literal["producer", "resume"]


@dataclass(frozen=True)
class ScheduledStep:
    """One exact training row selected by the frozen canary schedule."""

    step: int
    source_v4_record_index: int
    source_v4_record_hash: str
    token_count: int


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


def _branch_bounds(branch: DevelopmentCanaryBranch) -> tuple[int, int]:
    if branch == "producer":
        return 1, 16
    if branch == "resume":
        return 17, 32
    raise RuntimeError("development canary branch changed")


def _scheduled_steps(
    preregistration: Any,
    branch: DevelopmentCanaryBranch,
) -> tuple[ScheduledStep, ...]:
    start, end = _branch_bounds(branch)
    canary = preregistration.canary
    return tuple(
        ScheduledStep(
            step=step,
            source_v4_record_index=canary.schedule_indices[step - 1],
            source_v4_record_hash=canary.schedule_record_hashes[step - 1],
            token_count=canary.schedule_token_counts[step - 1],
        )
        for step in range(start, end + 1)
    )


def checkpoint_manifest(root: Path, *, global_step: int) -> dict[str, Any]:
    """Hash every checkpoint shard and require the step-16 state components."""

    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise RuntimeError("development canary checkpoint root is unsafe")
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(resolved.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("development canary checkpoint contains a symlink")
        if path.is_dir():
            continue
        metadata = path.stat()
        if not path.is_file() or metadata.st_nlink != 1:
            raise RuntimeError("development canary checkpoint contains an unsafe file")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
        total_bytes += metadata.st_size
        files.append(
            {
                "relative_path": path.relative_to(resolved).as_posix(),
                "size_bytes": metadata.st_size,
                "sha256": digest.hexdigest(),
            }
        )
    prefix = f"global_step_{global_step}"
    expected_rank_files = {
        f"{prefix}/{kind}_world_size_4_rank_{rank}.pt"
        for kind in ("model", "optim", "extra_state")
        for rank in range(4)
    }
    observed = {item["relative_path"] for item in files}
    if not expected_rank_files.issubset(observed):
        raise RuntimeError("development canary checkpoint is missing required rank shards")
    if f"{prefix}/data_0.pt" not in observed:
        raise RuntimeError("development canary checkpoint lacks dataloader state")
    if f"{prefix}/verigym_schedule_cursor.json" not in observed:
        raise RuntimeError("development canary checkpoint lacks its schedule cursor")
    return {
        "format_id": "verigym_hwe_development_canary_fsdp2_checkpoint_manifest_v1",
        "global_step": global_step,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "checkpoint_hash": _checkpoint_identity(files),
        "files": files,
    }


def verify_checkpoint_manifest(root: Path, manifest: Any, *, global_step: int) -> None:
    """Rehash a checkpoint against its producer-branch manifest."""

    if not isinstance(manifest, dict) or manifest.get("format_id") != (
        "verigym_hwe_development_canary_fsdp2_checkpoint_manifest_v1"
    ):
        raise RuntimeError("development canary checkpoint manifest is missing")
    if manifest.get("global_step") != global_step:
        raise RuntimeError("development canary checkpoint manifest step changed")
    expected_files = manifest.get("files")
    if not isinstance(expected_files, list) or not expected_files:
        raise RuntimeError("development canary checkpoint manifest has no files")
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise RuntimeError("development canary checkpoint root is unsafe")
    observed: list[dict[str, Any]] = []
    for item in expected_files:
        if not isinstance(item, dict):
            raise RuntimeError("development canary checkpoint manifest entry changed")
        relative = item.get("relative_path")
        if not isinstance(relative, str) or relative.startswith(("/", "../")):
            raise RuntimeError("development canary checkpoint manifest path is unsafe")
        path = resolved.joinpath(*relative.split("/"))
        resolved_path = path.resolve(strict=True)
        if path.is_symlink() or not path.is_file() or not resolved_path.is_relative_to(resolved):
            raise RuntimeError("development canary checkpoint file is unsafe")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
        observed_item = {
            "relative_path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
        }
        if observed_item != item:
            raise RuntimeError("development canary checkpoint file identity changed")
        observed.append(observed_item)
    actual_paths = {
        path.relative_to(resolved).as_posix() for path in resolved.rglob("*") if path.is_file()
    }
    if actual_paths != {item["relative_path"] for item in observed}:
        raise RuntimeError("development canary checkpoint file set changed")
    if sum(item["size_bytes"] for item in observed) != manifest.get("total_bytes"):
        raise RuntimeError("development canary checkpoint total size changed")
    if _checkpoint_identity(observed) != manifest.get("checkpoint_hash"):
        raise RuntimeError("development canary checkpoint aggregate hash changed")


def _checkpoint_identity(files: list[dict[str, Any]]) -> str:
    identity = hashlib.sha256()
    for item in files:
        path_bytes = item["relative_path"].encode("utf-8")
        identity.update(len(path_bytes).to_bytes(4, "big") + path_bytes)
        identity.update(struct.pack(">Q", item["size_bytes"]))
        identity.update(bytes.fromhex(item["sha256"]))
    return identity.hexdigest()


def _make_data(trainer: Any, config: Any, tu: Any, non_tensor_data: Any, index: int) -> Any:
    sample = trainer.train_dataset[index]
    batch = trainer.collate_fn([sample])
    data = tu.get_tensordict(
        tensor_dict=batch,
        non_tensor_dict=_batch_meta(config, trainer.model_config.tokenizer),
    )
    batch_seqlens = trainer._get_batch_seqlens(data=data)
    tu.assign_non_tensor(
        data,
        update_lr_scheduler=False,
        global_token_num=non_tensor_data(batch_seqlens),
    )
    return data


def _evaluate_heldout(
    *,
    torch_module: Any,
    trainer: Any,
    config: Any,
    tu: Any,
    non_tensor_data: Any,
    rank: int,
    world_size: int,
    evaluation_step: int,
    heldout_indices: list[int],
    dataframe_hashes: list[str],
    token_counts: list[int],
) -> dict[str, Any]:
    """Evaluate the complete held-out trajectory without changing any training state."""

    state_before = _state_receipt(torch_module, trainer)
    started = time.monotonic()
    records: list[dict[str, Any]] = []
    with trainer.engine.eval_mode(disable_auto_offload=False):
        for index in heldout_indices:
            data = _make_data(trainer, config, tu, non_tensor_data, index)
            output = trainer.engine.forward_backward_batch(
                data,
                trainer.loss_fn,
                forward_only=True,
            )
            losses = [float(value) for value in output.get("loss", [])]
            valid = bool(losses) and all(math.isfinite(value) and value > 0.0 for value in losses)
            if not _all_ranks_true(torch_module, valid):
                raise RuntimeError("development canary held-out evaluation produced invalid loss")
            local = {"rank": rank, "loss_values": losses}
            gathered: list[dict[str, Any] | None] = [None] * world_size
            torch_module.distributed.all_gather_object(gathered, local)
            if rank == 0:
                rank_results = [item for item in gathered if item is not None]
                flat_losses = [
                    float(value) for item in rank_results for value in item.get("loss_values", [])
                ]
                records.append(
                    {
                        "source_v4_record_index": index,
                        "source_v4_record_hash": dataframe_hashes[index],
                        "token_count": token_counts[index],
                        "mean_loss": sum(flat_losses) / len(flat_losses),
                        "rank_results": rank_results,
                    }
                )
    torch_module.cuda.synchronize()
    state_after = _state_receipt(torch_module, trainer)
    state_unchanged = state_before == state_after
    if not _all_ranks_true(torch_module, state_unchanged):
        raise RuntimeError("development canary held-out evaluation changed training state")
    if rank != 0:
        return {
            "evaluation_step": evaluation_step,
            "record_count": len(heldout_indices),
            "state_unchanged": True,
        }
    return {
        "evaluation_step": evaluation_step,
        "record_count": len(records),
        "forward_only": True,
        "state_unchanged": True,
        "mean_loss": sum(item["mean_loss"] for item in records) / len(records),
        "records": records,
        "wall_seconds": time.monotonic() - started,
    }


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
    """Run one fresh producer or resume process under the single-use authorization."""

    rank_root = _isolate_runtime(scratch_root)
    import numpy as np
    import torch  # type: ignore[import-not-found]

    determinism = _configure_exact_replay_determinism(torch, os.environ)
    from .hwe_decision_sft_64k_backend import validate_qualification_runtime
    from .hwe_decision_sft_64k_development_training import (
        assert_development_canary_branch_config,
    )

    runtime = validate_qualification_runtime(
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )
    from omegaconf import OmegaConf  # type: ignore[import-not-found]
    from tensordict.tensorclass import NonTensorData  # type: ignore[import-not-found]
    from verigym.experiments.state import atomic_dump_json
    from verigym.hwe.deepseek_harness_development_training import (
        load_development_training_execution_authorization,
        load_development_training_preregistration,
    )
    from verl.trainer.sft_trainer import SFTTrainer  # type: ignore[import-not-found]
    from verl.utils import tensordict_utils as tu  # type: ignore[import-not-found]
    from verl.utils.device import auto_set_device  # type: ignore[import-not-found]
    from verl.utils.distributed import (  # type: ignore[import-not-found]
        destroy_global_process_group,
        initialize_global_process_group,
    )

    preregistration = load_development_training_preregistration(preregistration_path)
    authorization = load_development_training_execution_authorization(authorization_path)
    config = OmegaConf.load(config_path)
    assert_development_canary_branch_config(
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
        raise RuntimeError("development canary requires world size 4")

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
                raise RuntimeError("development canary did not restore optimizer step 16")
            cursor_path = checkpoint_root / "global_step_16/verigym_schedule_cursor.json"
            cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
            if (
                cursor.get("authorization_hash") != authorization.authorization_hash
                or cursor.get("schedule_hash") != preregistration.canary.schedule_hash
                or cursor.get("completed_step") != 16
                or cursor.get("next_step") != 17
            ):
                raise RuntimeError("development canary schedule cursor changed")
            actual_optimizer_steps = 16
        elif trainer.resume_global_step != 0 or state_steps or state_count != 0:
            raise RuntimeError("development canary producer unexpectedly restored state")

        original_optimizer_step = trainer.engine.optimizer.step

        def counted_optimizer_step(*args: Any, **kwargs: Any) -> Any:
            nonlocal actual_optimizer_steps
            if actual_optimizer_steps >= end_step:
                raise RuntimeError("development canary optimizer guard blocked an excess step")
            result = original_optimizer_step(*args, **kwargs)
            actual_optimizer_steps += 1
            return result

        trainer.engine.optimizer.step = counted_optimizer_step
        original_checkpoint_save = trainer.ckpt_handler.save_checkpoint

        def counted_checkpoint_save(*args: Any, **kwargs: Any) -> Any:
            nonlocal checkpoint_saves
            if branch != "producer" or checkpoint_saves >= 1:
                raise RuntimeError("development canary guard blocked an excess checkpoint")
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
            raise RuntimeError("development canary actual loader receipts changed")
        dataframe_hashes = [str(value) for value in trainer.train_dataset.dataframe["record_hash"]]
        for scheduled in _scheduled_steps(preregistration, branch):
            index = scheduled.source_v4_record_index
            if (
                token_counts[index] != scheduled.token_count
                or dataframe_hashes[index] != scheduled.source_v4_record_hash
            ):
                raise RuntimeError("development canary scheduled loader row changed")
        heldout_indices = list(preregistration.split.heldout_record_indices)
        if any(index < 62 for index in heldout_indices) or len(heldout_indices) != 21:
            raise RuntimeError("development canary held-out split changed")

        initial_receipt = _state_receipt(torch, trainer)
        evaluations: list[dict[str, Any]] = []
        if branch == "producer":
            evaluations.append(
                _evaluate_heldout(
                    torch_module=torch,
                    trainer=trainer,
                    config=config,
                    tu=tu,
                    non_tensor_data=NonTensorData,
                    rank=rank,
                    world_size=world_size,
                    evaluation_step=0,
                    heldout_indices=heldout_indices,
                    dataframe_hashes=dataframe_hashes,
                    token_counts=token_counts,
                )
            )

        step_results: list[dict[str, Any]] = []
        previous_hash = initial_receipt["trainable_parameter_hash"]
        for scheduled in _scheduled_steps(preregistration, branch):
            step_started = time.monotonic()
            torch.cuda.reset_peak_memory_stats()
            data = _make_data(
                trainer,
                config,
                tu,
                NonTensorData,
                scheduled.source_v4_record_index,
            )
            with trainer.engine.train_mode(disable_auto_offload=False):
                trainer.engine.optimizer_zero_grad()
                before_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
                if before_hash != previous_hash:
                    raise RuntimeError("development canary parameters changed outside a step")
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
                    raise RuntimeError("development canary produced invalid loss or gradients")
                engine_pre_clip_norm = float(trainer.engine.optimizer_step())
                post_clip = _global_gradient_stats(torch, trainer.engine.module)
                after_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
                optimizer_steps, optimizer_state_count = _optimizer_state_steps(
                    torch,
                    trainer.engine.optimizer,
                )
                invariants = _post_step_invariants(
                    actual_optimizer_steps=actual_optimizer_steps,
                    scheduled_step=scheduled.step,
                    engine_pre_clip_norm=engine_pre_clip_norm,
                    post_clip=post_clip,
                    post_clip_global_norm_limit=(
                        authorization.post_clip_global_norm_acceptance_lte
                    ),
                    parameter_hash_before=before_hash,
                    parameter_hash_after=after_hash,
                    optimizer_state_steps=optimizer_steps,
                    optimizer_state_parameter_count=optimizer_state_count,
                    gradient_tensor_count=pre_clip["local_tensor_count"],
                )
                if not _all_ranks_true(torch, all(invariants.values())):
                    raise RuntimeError("development canary post-step invariant failed")
                learning_rate = float(trainer.engine.lr_scheduler_step())
                previous_hash = after_hash
            torch.cuda.synchronize()
            local_result = {
                "rank": rank,
                "step": scheduled.step,
                "source_v4_record_index": scheduled.source_v4_record_index,
                "source_v4_record_hash": scheduled.source_v4_record_hash,
                "token_count": scheduled.token_count,
                "parameter_hash_before": before_hash,
                "parameter_hash_after": after_hash,
                "loss_values": losses,
                "pre_clip_gradients": pre_clip,
                "engine_pre_clip_global_norm": engine_pre_clip_norm,
                "post_clip_gradients": post_clip,
                "optimizer_state_steps": optimizer_steps,
                "optimizer_state_parameter_count": optimizer_state_count,
                "post_step_invariants": invariants,
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
                        "token_count": scheduled.token_count,
                        "rank_results": [item for item in gathered if item is not None],
                    }
                )
            _normalize_host_rng_at_step_boundary(
                engine_seed=seed,
                global_step=scheduled.step,
                random_module=random,
                numpy_module=np,
                torch_module=torch,
            )

        evaluation_step = 16 if branch == "producer" else 32
        evaluations.append(
            _evaluate_heldout(
                torch_module=torch,
                trainer=trainer,
                config=config,
                tu=tu,
                non_tensor_data=NonTensorData,
                rank=rank,
                world_size=world_size,
                evaluation_step=evaluation_step,
                heldout_indices=heldout_indices,
                dataframe_hashes=dataframe_hashes,
                token_counts=token_counts,
            )
        )
        final_receipt = _state_receipt(torch, trainer)
        manifest: dict[str, Any] | None = None
        if branch == "producer":
            trainer.ckpt_handler.save_checkpoint(step=16)
            if rank == 0:
                atomic_dump_json(
                    checkpoint_root / "global_step_16/verigym_schedule_cursor.json",
                    {
                        "schema_version": "1.0",
                        "format_id": "verigym_hwe_development_canary_schedule_cursor_v1",
                        "authorization_hash": authorization.authorization_hash,
                        "schedule_hash": preregistration.canary.schedule_hash,
                        "completed_step": 16,
                        "next_step": 17,
                    },
                )
            torch.distributed.barrier()
            if rank == 0:
                manifest = checkpoint_manifest(checkpoint_root, global_step=16)
        trainer.ckpt_handler.save_checkpoint = _guarded_checkpoint
        if branch == "producer" and checkpoint_saves != 1:
            raise RuntimeError("development canary producer did not write one checkpoint")
        if branch == "resume" and checkpoint_saves != 0:
            raise RuntimeError("development canary resume wrote a checkpoint")

        initial_local = {"rank": rank, **initial_receipt}
        final_local = {"rank": rank, **final_receipt}
        gathered_initial: list[dict[str, Any] | None] = [None] * world_size
        gathered_final: list[dict[str, Any] | None] = [None] * world_size
        torch.distributed.all_gather_object(gathered_initial, initial_local)
        torch.distributed.all_gather_object(gathered_final, final_local)
        torch.distributed.barrier()
        if rank == 0:
            all_rank_steps = [item for step in step_results for item in step["rank_results"]]
            atomic_dump_json(
                report,
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_development_canary_branch_execution_v1",
                    "status": "passed",
                    "branch": branch,
                    "authorization_hash": authorization.authorization_hash,
                    "recipe_hash": preregistration.recipe_hash,
                    "schedule_hash": preregistration.canary.schedule_hash,
                    "start_step": start_step,
                    "end_step": end_step,
                    "optimizer_steps_observed": actual_optimizer_steps,
                    "optimizer_steps_executed_in_branch": end_step - start_step + 1,
                    "resume_global_step": trainer.resume_global_step,
                    "checkpoint_saves": checkpoint_saves,
                    "checkpoint_written": branch == "producer",
                    "checkpoint_loaded": branch == "resume",
                    "initial_rank_state": [item for item in gathered_initial if item is not None],
                    "final_rank_state": [item for item in gathered_final if item is not None],
                    "step_results": step_results,
                    "heldout_evaluations": evaluations,
                    "checkpoint_manifest": manifest,
                    "loader_rows_validated": len(token_counts),
                    "exact_receipts_revalidated": len(token_counts),
                    "heldout_rows_validated": len(heldout_indices),
                    "over_32768_rows_validated": sum(value > 32_768 for value in token_counts),
                    "max_token_count": max(token_counts),
                    "runtime": runtime,
                    "determinism": determinism,
                    "world_size": world_size,
                    "selected_gpu_indices": [0, 1, 2, 3],
                    "peak_memory_allocated_bytes": max(
                        item["peak_memory_allocated_bytes"] for item in all_rank_steps
                    ),
                    "peak_memory_reserved_bytes": max(
                        item["peak_memory_reserved_bytes"] for item in all_rank_steps
                    ),
                    "execution_wall_seconds": time.monotonic() - started,
                    "adapter_written": False,
                    "production_training_ready": False,
                },
            )
    except BaseException as error:
        failure = error
        from verigym.experiments.state import atomic_dump_json

        atomic_dump_json(
            rank_root / "failure.json",
            {
                "format_id": "verigym_hwe_development_canary_branch_failure_v1",
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


__all__ = [
    "ScheduledStep",
    "checkpoint_manifest",
    "run_branch",
    "verify_checkpoint_manifest",
]
