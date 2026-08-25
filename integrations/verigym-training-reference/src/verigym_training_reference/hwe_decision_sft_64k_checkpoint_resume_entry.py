"""Torchrun branch entry for the authorized 64K checkpoint/resume qualification."""

from __future__ import annotations

import argparse
import gc
import hashlib
import math
import os
import random
import shutil
import struct
import time
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", choices=("control", "producer", "resume"), required=True)
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


def _digest_state(torch_module: Any, digest: Any, value: Any) -> None:
    if value is None:
        digest.update(b"N")
    elif isinstance(value, bool):
        digest.update(b"B1" if value else b"B0")
    elif isinstance(value, int):
        digest.update(b"I" + str(value).encode("ascii") + b";")
    elif isinstance(value, float):
        digest.update(b"F" + value.hex().encode("ascii") + b";")
    elif isinstance(value, str):
        payload = value.encode("utf-8")
        digest.update(b"S" + len(payload).to_bytes(8, "big") + payload)
    elif isinstance(value, bytes):
        digest.update(b"Y" + len(value).to_bytes(8, "big") + value)
    elif isinstance(value, Mapping):
        digest.update(b"M" + len(value).to_bytes(8, "big"))
        for key in sorted(value, key=lambda item: (type(item).__name__, repr(item))):
            _digest_state(torch_module, digest, key)
            _digest_state(torch_module, digest, value[key])
    elif isinstance(value, tuple):
        digest.update(b"T" + len(value).to_bytes(8, "big"))
        for item in value:
            _digest_state(torch_module, digest, item)
    elif isinstance(value, list):
        digest.update(b"L" + len(value).to_bytes(8, "big"))
        for item in value:
            _digest_state(torch_module, digest, item)
    elif isinstance(value, torch_module.Tensor) or hasattr(value, "to_local"):
        tensor = value.to_local() if hasattr(value, "to_local") else value
        tensor = tensor.detach().contiguous().cpu()
        dtype = str(tensor.dtype).encode("ascii")
        digest.update(b"R" + len(dtype).to_bytes(4, "big") + dtype)
        digest.update(len(tensor.shape).to_bytes(4, "big"))
        for dimension in tensor.shape:
            digest.update(int(dimension).to_bytes(8, "big", signed=True))
        # PyTorch rejects dtype-changing ``view`` directly on a zero-dimensional
        # tensor.  Optimizer state contains scalar step tensors, so normalize all
        # tensors to a one-dimensional byte-addressable view first.
        payload = tensor.reshape(-1).view(torch_module.uint8).numpy().tobytes()
        digest.update(len(payload).to_bytes(8, "big") + payload)
    elif type(value).__module__.startswith("numpy") and hasattr(value, "tobytes"):
        dtype = str(value.dtype).encode("ascii")
        digest.update(b"A" + len(dtype).to_bytes(4, "big") + dtype)
        digest.update(len(value.shape).to_bytes(4, "big"))
        for dimension in value.shape:
            digest.update(int(dimension).to_bytes(8, "big", signed=True))
        payload = value.tobytes()
        digest.update(len(payload).to_bytes(8, "big") + payload)
    else:
        raise RuntimeError(
            f"checkpoint/resume state fingerprint found unsupported {type(value).__name__}"
        )


def _state_fingerprint(torch_module: Any, value: Any) -> str:
    digest = hashlib.sha256()
    _digest_state(torch_module, digest, value)
    return digest.hexdigest()


def _configure_exact_replay_determinism(
    torch_module: Any,
    environment: MutableMapping[str, str],
) -> dict[str, Any]:
    """Pin deterministic CUDA kernels before constructing a fresh branch.

    Transformers reads ``FLASH_ATTENTION_DETERMINISTIC`` when it prepares the
    FlashAttention call and forwards it to the pinned FA2 varlen kernel.  The
    CUBLAS setting and PyTorch guard cover the remaining CUDA reductions.  A
    conflicting inherited value is an infrastructure error rather than a reason
    to silently weaken exact checkpoint/replay comparison.
    """

    required_environment = {
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "FLASH_ATTENTION_DETERMINISTIC": "1",
    }
    for name, expected in required_environment.items():
        observed = environment.get(name)
        if observed not in (None, expected):
            raise RuntimeError(f"checkpoint/resume deterministic setting {name} conflicts")
        environment[name] = expected

    torch_module.use_deterministic_algorithms(True)
    torch_module.backends.cudnn.benchmark = False
    torch_module.backends.cudnn.deterministic = True
    if not torch_module.are_deterministic_algorithms_enabled():
        raise RuntimeError("checkpoint/resume deterministic algorithms were not enabled")
    return {
        "format_id": "verigym_hwe_checkpoint_resume_determinism_v1",
        "flash_attention_deterministic": True,
        "cublas_workspace_config": required_environment["CUBLAS_WORKSPACE_CONFIG"],
        "torch_deterministic_algorithms": True,
        "cudnn_benchmark": False,
        "cudnn_deterministic": True,
        "host_rng_step_boundary_normalized": True,
        "host_rng_step_seed_derivation": "engine_seed_times_1000003_plus_global_step",
    }


def _normalize_host_rng_at_step_boundary(
    *,
    engine_seed: int,
    global_step: int,
    random_module: Any,
    numpy_module: Any,
    torch_module: Any,
) -> int:
    """Make host-only RNG state a deterministic function of the completed step.

    CUDA RNG is deliberately left untouched so the qualification still proves
    that its checkpointed dropout state resumes exactly.  Normalizing Python,
    NumPy, and the CPU torch generator prevents branch-local bookkeeping from
    perturbing an otherwise identical continuation state.
    """

    boundary_seed = engine_seed * 1_000_003 + global_step
    random_module.seed(boundary_seed)
    numpy_module.random.seed(boundary_seed % (2**32))
    cpu_generator = torch_module.Generator(device="cpu")
    cpu_generator.manual_seed(boundary_seed)
    torch_module.set_rng_state(cpu_generator.get_state())
    return boundary_seed


def _checkpoint_manifest(root: Path) -> dict[str, Any]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise RuntimeError("checkpoint/resume checkpoint root is not a real directory")
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(resolved.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("checkpoint/resume checkpoint contains a symlink")
        if path.is_dir():
            continue
        metadata = path.stat()
        if not path.is_file() or metadata.st_nlink != 1:
            raise RuntimeError("checkpoint/resume checkpoint contains an unsafe file")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
        size = metadata.st_size
        total_bytes += size
        files.append(
            {
                "relative_path": path.relative_to(resolved).as_posix(),
                "size_bytes": size,
                "sha256": digest.hexdigest(),
            }
        )
    expected_rank_files = {
        f"global_step_2/{kind}_world_size_4_rank_{rank}.pt"
        for kind in ("model", "optim", "extra_state")
        for rank in range(4)
    }
    observed = {item["relative_path"] for item in files}
    if not expected_rank_files.issubset(observed):
        raise RuntimeError(
            "checkpoint/resume checkpoint is missing a model, optimizer, or RNG shard"
        )
    if "global_step_2/data_0.pt" not in observed:
        raise RuntimeError("checkpoint/resume checkpoint is missing StatefulDataLoader state")
    if "global_step_2/verigym_schedule_cursor.json" not in observed:
        raise RuntimeError("checkpoint/resume checkpoint is missing the explicit schedule cursor")
    identity = hashlib.sha256()
    for item in files:
        path_bytes = item["relative_path"].encode("utf-8")
        identity.update(len(path_bytes).to_bytes(4, "big") + path_bytes)
        identity.update(struct.pack(">Q", item["size_bytes"]))
        identity.update(bytes.fromhex(item["sha256"]))
    return {
        "format_id": "verigym_hwe_fsdp2_checkpoint_manifest_v1",
        "file_count": len(files),
        "total_bytes": total_bytes,
        "checkpoint_hash": identity.hexdigest(),
        "files": files,
    }


def _verify_checkpoint_manifest(root: Path, manifest: Any) -> None:
    if not isinstance(manifest, dict) or manifest.get("format_id") != (
        "verigym_hwe_fsdp2_checkpoint_manifest_v1"
    ):
        raise RuntimeError("checkpoint/resume checkpoint manifest is missing")
    expected_files = manifest.get("files")
    if not isinstance(expected_files, list) or not expected_files:
        raise RuntimeError("checkpoint/resume checkpoint manifest has no files")
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise RuntimeError("checkpoint/resume checkpoint root is unsafe")
    observed_paths: set[str] = set()
    total_bytes = 0
    identity = hashlib.sha256()
    for item in expected_files:
        if not isinstance(item, dict):
            raise RuntimeError("checkpoint/resume checkpoint manifest entry changed")
        relative = item.get("relative_path")
        if not isinstance(relative, str) or relative.startswith(("/", "../")):
            raise RuntimeError("checkpoint/resume checkpoint manifest path is unsafe")
        path = resolved / relative
        resolved_path = path.resolve(strict=True)
        if path.is_symlink() or not path.is_file() or not resolved_path.is_relative_to(resolved):
            raise RuntimeError("checkpoint/resume checkpoint file is unsafe")
        payload_hash = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                payload_hash.update(chunk)
        size = path.stat().st_size
        if size != item.get("size_bytes") or payload_hash.hexdigest() != item.get("sha256"):
            raise RuntimeError("checkpoint/resume checkpoint file identity changed")
        observed_paths.add(relative)
        total_bytes += size
        relative_bytes = relative.encode("utf-8")
        identity.update(len(relative_bytes).to_bytes(4, "big") + relative_bytes)
        identity.update(size.to_bytes(8, "big"))
        identity.update(bytes.fromhex(payload_hash.hexdigest()))
    actual_paths = {
        path.relative_to(resolved).as_posix() for path in resolved.rglob("*") if path.is_file()
    }
    if actual_paths != observed_paths:
        raise RuntimeError("checkpoint/resume checkpoint file set changed")
    if total_bytes != manifest.get("total_bytes"):
        raise RuntimeError("checkpoint/resume checkpoint total size changed")
    if identity.hexdigest() != manifest.get("checkpoint_hash"):
        raise RuntimeError("checkpoint/resume checkpoint aggregate hash changed")


def _delete_temporary_checkpoint(root: Path) -> bool:
    if root.name != "temporary-fsdp2-checkpoint":
        raise RuntimeError("checkpoint/resume refused to delete an unexpected path")
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("checkpoint/resume temporary checkpoint root is unsafe")
    shutil.rmtree(root)
    return not root.exists() and not root.is_symlink()


def _branch_bounds(branch: str) -> tuple[int, int]:
    if branch == "control":
        return 1, 4
    if branch == "producer":
        return 1, 2
    if branch == "resume":
        return 3, 4
    raise RuntimeError("checkpoint/resume branch changed")


def _scheduled_steps(schedule: Sequence[Any], branch: str) -> tuple[Any, ...]:
    start, end = _branch_bounds(branch)
    return tuple(schedule[start - 1 : end])


def _state_receipt(torch_module: Any, trainer: Any) -> dict[str, Any]:
    checkpoint_manager = trainer.engine.checkpoint_manager
    scheduler = trainer.engine.lr_scheduler
    rng_state = checkpoint_manager.get_rng_state()
    optimizer_state_steps, _ = _optimizer_state_steps(
        torch_module,
        trainer.engine.optimizer,
    )
    return {
        "trainable_parameter_hash": _local_trainable_parameter_hash(
            torch_module,
            trainer.engine.module,
        ),
        "optimizer_state_fingerprint": _state_fingerprint(
            torch_module,
            trainer.engine.optimizer.state_dict(),
        ),
        "lr_scheduler_state_fingerprint": _state_fingerprint(
            torch_module,
            scheduler.state_dict() if scheduler is not None else None,
        ),
        "rng_state_fingerprint": _state_fingerprint(
            torch_module,
            rng_state,
        ),
        "rng_component_fingerprints": {
            str(name): _state_fingerprint(torch_module, value)
            for name, value in sorted(rng_state.items())
        },
        "dataloader_state_fingerprint": _state_fingerprint(
            torch_module,
            trainer.train_dataloader.state_dict(),
        ),
        "optimizer_state_steps": optimizer_state_steps,
    }


def run_branch(
    *,
    branch: str,
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
    """Run one fresh distributed branch under the shared attempt-8 authorization."""

    rank_root = _isolate_runtime(scratch_root)
    import numpy as np
    import torch  # type: ignore[import-not-found]

    determinism = _configure_exact_replay_determinism(torch, os.environ)
    from .hwe_decision_sft_64k_backend import validate_qualification_runtime
    from .hwe_decision_sft_64k_optimizer_smoke import (
        assert_checkpoint_resume_branch_config,
        optimizer_smoke_clip_acceptance,
    )

    runtime = validate_qualification_runtime(
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )
    from omegaconf import OmegaConf  # type: ignore[import-not-found]
    from tensordict.tensorclass import NonTensorData  # type: ignore[import-not-found]
    from verigym.experiments.state import atomic_dump_json
    from verigym.hwe.deepseek_harness_optimizer_smoke import (
        load_optimizer_smoke_execution_authorization,
        load_optimizer_smoke_preregistration,
    )
    from verigym.schemas.hwe_training import (
        HweDecisionSft64kCheckpointResumeQualificationAuthorization,
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
    if not isinstance(
        authorization,
        HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    ):
        raise RuntimeError("checkpoint/resume branch requires attempt-8 authorization")
    config = OmegaConf.load(config_path)
    assert_checkpoint_resume_branch_config(
        config,
        preregistration=preregistration,
        authorization=authorization,
        branch=branch,  # type: ignore[arg-type]
        checkpoint_root=str(checkpoint_root),
    )
    _, _, post_clip_limit = optimizer_smoke_clip_acceptance(preregistration, authorization)
    auto_set_device(config)
    initialize_global_process_group()
    rank = torch.distributed.get_rank()
    world_size = torch.distributed.get_world_size()
    if world_size != 4:
        raise RuntimeError("checkpoint/resume qualification requires world size 4")

    # veRL 0.8's SFTTrainer does not seed fresh worker processes before it
    # initializes LoRA parameters.  Pin every RNG before trainer construction so
    # the control and producer processes begin from the same model and RNG state;
    # the resume branch subsequently replaces these states from the checkpoint.
    seed = int(config.engine.seed)
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
        initial_state_steps, initial_state_count = _optimizer_state_steps(
            torch,
            trainer.engine.optimizer,
        )
        if branch == "resume":
            if (
                trainer.resume_global_step != 2
                or initial_state_steps != [2]
                or initial_state_count <= 0
            ):
                raise RuntimeError("checkpoint/resume did not restore optimizer step 2")
            cursor_path = checkpoint_root / "global_step_2/verigym_schedule_cursor.json"
            cursor = __import__("json").loads(cursor_path.read_text(encoding="utf-8"))
            if (
                cursor.get("authorization_hash") != authorization.authorization_hash
                or cursor.get("schedule_hash") != preregistration.schedule_hash
                or cursor.get("completed_step") != 2
                or cursor.get("next_step") != 3
            ):
                raise RuntimeError("checkpoint/resume explicit schedule cursor changed")
            actual_optimizer_steps = 2
        elif trainer.resume_global_step != 0 or initial_state_steps or initial_state_count != 0:
            raise RuntimeError("checkpoint/resume fresh branch unexpectedly restored state")

        original_optimizer_step = trainer.engine.optimizer.step

        def counted_optimizer_step(*args: Any, **kwargs: Any) -> Any:
            nonlocal actual_optimizer_steps
            if actual_optimizer_steps >= end_step:
                raise RuntimeError("checkpoint/resume optimizer guard blocked an excess step")
            result = original_optimizer_step(*args, **kwargs)
            actual_optimizer_steps += 1
            return result

        trainer.engine.optimizer.step = counted_optimizer_step
        original_checkpoint_save = trainer.ckpt_handler.save_checkpoint

        def counted_checkpoint_save(*args: Any, **kwargs: Any) -> Any:
            nonlocal checkpoint_saves
            if branch != "producer" or checkpoint_saves >= 1:
                raise RuntimeError("checkpoint/resume guard blocked an excess checkpoint")
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
            raise RuntimeError("checkpoint/resume actual veRL loader receipts changed")
        dataframe_hashes = [str(value) for value in trainer.train_dataset.dataframe["record_hash"]]
        for scheduled in _scheduled_steps(preregistration.schedule, branch):
            index = scheduled.source_v4_record_index
            if (
                token_counts[index] != scheduled.token_count
                or dataframe_hashes[index] != scheduled.source_v4_record_hash
            ):
                raise RuntimeError("checkpoint/resume scheduled loader row changed")

        initial_receipt = _state_receipt(torch, trainer)
        step_results: list[dict[str, Any]] = []
        previous_hash = initial_receipt["trainable_parameter_hash"]
        for scheduled in _scheduled_steps(preregistration.schedule, branch):
            step_started = time.monotonic()
            torch.cuda.reset_peak_memory_stats()
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
                if before_hash != previous_hash:
                    raise RuntimeError(
                        "checkpoint/resume parameters changed outside an optimizer step"
                    )
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
                    raise RuntimeError("checkpoint/resume produced invalid loss or gradients")
                engine_pre_clip_norm = float(trainer.engine.optimizer_step())
                post_clip = _global_gradient_stats(torch, trainer.engine.module)
                after_hash = _local_trainable_parameter_hash(torch, trainer.engine.module)
                state_steps, state_parameter_count = _optimizer_state_steps(
                    torch,
                    trainer.engine.optimizer,
                )
                invariants = _post_step_invariants(
                    actual_optimizer_steps=actual_optimizer_steps,
                    scheduled_step=scheduled.step,
                    engine_pre_clip_norm=engine_pre_clip_norm,
                    post_clip=post_clip,
                    post_clip_global_norm_limit=post_clip_limit,
                    parameter_hash_before=before_hash,
                    parameter_hash_after=after_hash,
                    optimizer_state_steps=state_steps,
                    optimizer_state_parameter_count=state_parameter_count,
                    gradient_tensor_count=pre_clip["local_tensor_count"],
                )
                if not _all_ranks_true(torch, all(invariants.values())):
                    raise RuntimeError("checkpoint/resume post-step invariant failed")
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
                "optimizer_state_steps": state_steps,
                "optimizer_state_parameter_count": state_parameter_count,
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

        final_receipt = _state_receipt(torch, trainer)
        checkpoint_manifest: dict[str, Any] | None = None
        if branch == "producer":
            trainer.ckpt_handler.save_checkpoint(step=2)
            if rank == 0:
                cursor_path = checkpoint_root / "global_step_2/verigym_schedule_cursor.json"
                atomic_dump_json(
                    cursor_path,
                    {
                        "schema_version": "1.0",
                        "format_id": "verigym_hwe_checkpoint_schedule_cursor_v1",
                        "authorization_hash": authorization.authorization_hash,
                        "schedule_hash": preregistration.schedule_hash,
                        "completed_step": 2,
                        "next_step": 3,
                    },
                )
            torch.distributed.barrier()
            if rank == 0:
                checkpoint_manifest = _checkpoint_manifest(checkpoint_root)
        trainer.ckpt_handler.save_checkpoint = _guarded_checkpoint
        if branch != "producer" and checkpoint_saves != 0:
            raise RuntimeError("checkpoint/resume non-producer branch wrote a checkpoint")
        if branch == "producer" and checkpoint_saves != 1:
            raise RuntimeError("checkpoint/resume producer did not write exactly one checkpoint")

        final_local = {
            "rank": rank,
            **final_receipt,
            "optimizer_state_steps": _optimizer_state_steps(
                torch,
                trainer.engine.optimizer,
            )[0],
        }
        initial_local = {"rank": rank, **initial_receipt}
        gathered_initial: list[dict[str, Any] | None] = [None] * world_size
        gathered_final: list[dict[str, Any] | None] = [None] * world_size
        torch.distributed.all_gather_object(gathered_initial, initial_local)
        torch.distributed.all_gather_object(gathered_final, final_local)
        torch.distributed.barrier()
        if rank == 0:
            all_rank_results = [item for result in step_results for item in result["rank_results"]]
            atomic_dump_json(
                report,
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_checkpoint_resume_branch_execution_v1",
                    "status": "passed",
                    "branch": branch,
                    "authorization_hash": authorization.authorization_hash,
                    "authorization_attempt": 8,
                    "preregistration_hash": preregistration.preregistration_hash,
                    "schedule_hash": preregistration.schedule_hash,
                    "start_step": start_step,
                    "end_step": end_step,
                    "optimizer_steps_observed": actual_optimizer_steps,
                    "resume_global_step": trainer.resume_global_step,
                    "checkpoint_saves": checkpoint_saves,
                    "checkpoint_written": branch == "producer",
                    "checkpoint_loaded": branch == "resume",
                    "initial_rank_state": [item for item in gathered_initial if item is not None],
                    "final_rank_state": [item for item in gathered_final if item is not None],
                    "step_results": step_results,
                    "checkpoint_manifest": checkpoint_manifest,
                    "loader_rows_validated": len(token_counts),
                    "exact_receipts_revalidated": len(token_counts),
                    "over_32768_rows_validated": sum(value > 32_768 for value in token_counts),
                    "max_token_count": max(token_counts),
                    "runtime": runtime,
                    "determinism": determinism,
                    "host_rng_step_boundary_seeds": [
                        seed * 1_000_003 + scheduled.step
                        for scheduled in _scheduled_steps(preregistration.schedule, branch)
                    ],
                    "world_size": world_size,
                    "selected_gpu_indices": [0, 1, 2, 3],
                    "peak_memory_allocated_bytes": max(
                        item["peak_memory_allocated_bytes"] for item in all_rank_results
                    ),
                    "peak_memory_reserved_bytes": max(
                        item["peak_memory_reserved_bytes"] for item in all_rank_results
                    ),
                    "execution_wall_seconds": time.monotonic() - started,
                    "adapter_written": False,
                    "production_training_ready": False,
                },
            )
    except BaseException as exc:
        failure = exc
        from verigym.experiments.state import atomic_dump_json

        atomic_dump_json(
            rank_root / "failure.json",
            {
                "format_id": "verigym_hwe_checkpoint_resume_branch_failure_v1",
                "branch": branch,
                "rank": rank,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
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
