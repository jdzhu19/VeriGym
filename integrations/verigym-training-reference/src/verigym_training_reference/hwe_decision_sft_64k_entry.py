"""Torchrun entry for one zero-step 64K HWE forward/backward qualification."""

from __future__ import annotations

import argparse
import gc
import hashlib
import math
import os
import time
from pathlib import Path
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--rllm-source", type=Path, required=True)
    parser.add_argument("--verl-source", type=Path, required=True)
    parser.add_argument("--transformers-source", type=Path, required=True)
    return parser


def _isolate_runtime(scratch_root: Path) -> None:
    rank = os.environ.get("LOCAL_RANK") or os.environ.get("RANK") or "0"
    root = scratch_root.resolve(strict=True) / f"rank-{rank}"
    root.mkdir(mode=0o700, exist_ok=True)
    os.environ["TRITON_CACHE_DIR"] = str(root / "triton")
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(root / "inductor")
    os.environ["TMPDIR"] = str(root)
    os.environ["TEMP"] = str(root)
    os.environ["TMP"] = str(root)


def _guarded_operation(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("qualification guard blocked optimizer or checkpoint mutation")


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
        raise RuntimeError("qualification found no trainable LoRA parameters")
    return digest.hexdigest()


def _finite_local_gradients(torch_module: Any, module: Any) -> tuple[bool, int, float]:
    count = 0
    squared_norm = 0.0
    finite = True
    for parameter in module.parameters():
        if not parameter.requires_grad or parameter.grad is None:
            continue
        gradient = parameter.grad
        if hasattr(gradient, "to_local"):
            gradient = gradient.to_local()
        finite = finite and bool(torch_module.isfinite(gradient).all().item())
        squared_norm += float(gradient.float().square().sum().item())
        count += 1
    return finite and count > 0, count, squared_norm**0.5


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


def run_qualification(
    config_path: Path,
    report: Path,
    scratch_root: Path,
    rllm_source: Path,
    verl_source: Path,
    transformers_source: Path,
) -> None:
    """Initialize veRL once, run all loader rows, then backward the longest row."""

    _isolate_runtime(scratch_root)
    from .hwe_decision_sft_64k_backend import validate_qualification_runtime

    runtime = validate_qualification_runtime(
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )
    import torch  # type: ignore[import-not-found]
    from omegaconf import OmegaConf  # type: ignore[import-not-found]
    from tensordict.tensorclass import NonTensorData  # type: ignore[import-not-found]
    from verigym.experiments.state import atomic_dump_json
    from verl.trainer.sft_trainer import SFTTrainer  # type: ignore[import-not-found]
    from verl.utils import tensordict_utils as tu  # type: ignore[import-not-found]
    from verl.utils.device import auto_set_device  # type: ignore[import-not-found]
    from verl.utils.distributed import (  # type: ignore[import-not-found]
        destroy_global_process_group,
        initialize_global_process_group,
    )

    config = OmegaConf.load(config_path)
    auto_set_device(config)
    initialize_global_process_group()
    rank = torch.distributed.get_rank()
    world_size = torch.distributed.get_world_size()
    if world_size != 4:
        raise RuntimeError(f"64K qualification requires world size 4; found {world_size}")
    torch.cuda.reset_peak_memory_stats()
    qualification_started = time.monotonic()
    trainer: Any = None
    sample: Any = None
    batch: Any = None
    data: Any = None
    output: Any = None
    try:
        trainer = SFTTrainer(config=config)
        trainer.ckpt_handler.save_checkpoint = _guarded_operation
        trainer.engine.optimizer.step = _guarded_operation
        trainer.engine.optimizer_step = _guarded_operation

        token_counts: list[int] = []
        for index in range(len(trainer.train_dataset)):
            token_counts.append(int(trainer.train_dataset[index]["input_ids"].shape[0]))
        if len(token_counts) != 83 or max(token_counts) != 50_117:
            raise RuntimeError("actual veRL dataset did not validate all frozen 64K rows")
        longest_index = max(range(len(token_counts)), key=token_counts.__getitem__)
        sample = trainer.train_dataset[longest_index]
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

        probe_started = time.monotonic()
        with trainer.engine.train_mode(disable_auto_offload=False):
            trainer.engine.optimizer_zero_grad()
            before_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
            output = trainer.engine.forward_backward_batch(
                data,
                trainer.loss_fn,
                forward_only=False,
            )
            after_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
            gradients_finite, gradient_tensors, gradient_norm = _finite_local_gradients(
                torch, trainer.engine.module
            )
            losses = output.get("loss", [])
            loss_values = [float(value) for value in losses]
            losses_finite = bool(loss_values) and all(math.isfinite(value) for value in loss_values)
        torch.cuda.synchronize()
        probe_wall = time.monotonic() - probe_started

        local_result = {
            "rank": rank,
            "parameter_hash_before": before_hash,
            "parameter_hash_after": after_hash,
            "parameter_hash_unchanged": before_hash == after_hash,
            "losses_finite": losses_finite,
            "loss_values": loss_values,
            "gradients_finite": gradients_finite,
            "gradient_tensor_count": gradient_tensors,
            "gradient_norm": gradient_norm,
            "peak_memory_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_memory_reserved_bytes": torch.cuda.max_memory_reserved(),
            "probe_wall_seconds": probe_wall,
        }
        gathered: list[dict[str, Any] | None] = [None] * world_size
        torch.distributed.all_gather_object(gathered, local_result)
        torch.distributed.barrier()
        qualification_wall = time.monotonic() - qualification_started
        if rank == 0:
            ranks = [item for item in gathered if item is not None]
            passed = all(
                item["parameter_hash_unchanged"]
                and item["losses_finite"]
                and item["gradients_finite"]
                for item in ranks
            )
            if not passed:
                raise RuntimeError(
                    "64K forward/backward produced invalid loss, gradients, or mutation"
                )
            atomic_dump_json(
                report,
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_deepseek_harness_gpu_qualification_64k_v4",
                    "status": "passed",
                    "loader_ready": True,
                    "loader_rows_validated": len(token_counts),
                    "gpu_probe_passed": True,
                    "development_training_ready": True,
                    "production_training_ready": False,
                    "training_started": False,
                    "optimizer_steps": 0,
                    "adapter_written": False,
                    "checkpoint_written": False,
                    "new_hpc_jobs_submitted": False,
                    "runtime": runtime,
                    "world_size": world_size,
                    "ulysses_sequence_parallel_size": 4,
                    "longest_record_index": longest_index,
                    "longest_record_tokens": max(token_counts),
                    "bounded_fused_vocabulary_head": True,
                    "global_shift_labels_used": True,
                    "rank_results": ranks,
                    "peak_memory_allocated_bytes": max(
                        item["peak_memory_allocated_bytes"] for item in ranks
                    ),
                    "peak_memory_reserved_bytes": max(
                        item["peak_memory_reserved_bytes"] for item in ranks
                    ),
                    "probe_wall_seconds": max(item["probe_wall_seconds"] for item in ranks),
                    "qualification_wall_seconds": qualification_wall,
                    "gpu_seconds": qualification_wall * world_size,
                },
            )
    finally:
        if trainer is not None:
            trainer.engine.optimizer_zero_grad()
        output = None
        data = None
        batch = None
        sample = None
        trainer = None
        gc.collect()
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.distributed.barrier()
        destroy_global_process_group()


def main() -> None:
    arguments = _parser().parse_args()
    run_qualification(
        arguments.config,
        arguments.report,
        arguments.scratch_root,
        arguments.rllm_source,
        arguments.verl_source,
        arguments.transformers_source,
    )


if __name__ == "__main__":
    main()
