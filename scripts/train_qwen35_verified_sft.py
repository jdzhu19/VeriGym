#!/usr/bin/env python3
"""Run a bounded Qwen3.5 LoRA SFT smoke from a verified VeriGym dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import accelerate
import peft
import torch
import transformers
from accelerate import Accelerator
from peft import LoraConfig, TaskType, get_peft_model
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer

_OPT_IN_ENV = "VERIGYM_RUN_QWEN35_SFT"
_MAX_DATASET_BYTES = 64 * 1024 * 1024


class _RepeatedExampleDataset(Dataset[dict[str, torch.Tensor]]):
    def __init__(self, item: dict[str, torch.Tensor], repetitions: int) -> None:
        self._item = item
        self._repetitions = repetitions

    def __len__(self) -> int:
        return self._repetitions

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        return {key: value.clone() for key, value in self._item.items()}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-step verifier-filtered Qwen3.5 LoRA SFT.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seq-length", type=int, default=640)
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--seed", type=int, default=484)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_directory(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise SystemExit(f"{label} cannot be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise SystemExit(f"{label} must be a directory")
    return resolved


def _read_file(path: Path, maximum: int = _MAX_DATASET_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"expected a regular file: {path.name}")
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise SystemExit(f"input file is empty or oversized: {path.name}")
    payload = path.read_bytes()
    if len(payload) != size:
        raise SystemExit(f"input changed while reading: {path.name}")
    return payload


def _load_example(dataset: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(_read_file(dataset / "dataset-manifest.json"))
    if (
        manifest.get("format_id") != "verigym_verified_solution_sft_dataset_v1"
        or manifest.get("record_count") != 1
        or manifest.get("only_resolved_samples") is not True
        or manifest.get("infrastructure_invalid_excluded") is not True
        or manifest.get("hidden_assets_exported") is not False
        or manifest.get("private_reasoning_exported") is not False
    ):
        raise SystemExit("dataset manifest is not an eligible verified SFT dataset")
    expected = manifest.get("file_hashes", {}).get("train.jsonl")
    if not isinstance(expected, str) or _sha256(dataset / "train.jsonl") != expected:
        raise SystemExit("training JSONL differs from its manifest")
    lines = _read_file(dataset / "train.jsonl").decode("utf-8").splitlines()
    if len(lines) != 1:
        raise SystemExit("SFT smoke requires exactly one JSONL record")
    example = json.loads(lines[0])
    if (
        example.get("verifier_resolved") is not True
        or example.get("infrastructure_valid") is not True
        or example.get("hidden_assets_exported") is not False
        or example.get("private_reasoning_exported") is not False
    ):
        raise SystemExit("SFT example is not verifier eligible")
    return manifest, example


def _tokenize_example(
    tokenizer: Any,
    messages: list[dict[str, str]],
    maximum: int,
) -> dict[str, torch.Tensor]:
    full = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
    )["input_ids"]
    prefix = tokenizer.apply_chat_template(
        messages[:-1],
        tokenize=True,
        add_generation_prompt=True,
    )["input_ids"]
    common = 0
    while common < min(len(full), len(prefix)) and full[common] == prefix[common]:
        common += 1
    if common == 0 or common >= len(full):
        raise SystemExit("chat template has no separable assistant target")
    if len(full) > maximum:
        raise SystemExit(f"tokenized example uses {len(full)} tokens; limit is {maximum}")
    input_ids = torch.tensor(full, dtype=torch.long)
    labels = input_ids.clone()
    labels[:common] = -100
    return {
        "input_ids": input_ids,
        "attention_mask": torch.ones_like(input_ids),
        "labels": labels,
    }


def _collate(items: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    if len(items) != 1:
        raise RuntimeError("SFT smoke uses a per-rank micro-batch of one")
    return {key: value.unsqueeze(0) for key, value in items[0].items()}


def _new_output(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise SystemExit("training output must be a new or empty real directory")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _artifact_hash(root: Path) -> tuple[str, list[dict[str, int | str]]]:
    inventory: list[dict[str, int | str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("adapter output contains a symlink")
        if not path.is_file() or path.name == "training-report.json":
            continue
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    encoded = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), inventory


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    if not 1 <= arguments.max_steps <= 16:
        raise SystemExit("--max-steps must be in [1, 16]")
    if not 128 <= arguments.max_seq_length <= 4096:
        raise SystemExit("--max-seq-length must be in [128, 4096]")

    accelerator = Accelerator(mixed_precision="bf16")
    torch.manual_seed(arguments.seed)
    dataset_root = _safe_directory(arguments.dataset, label="dataset")
    model_root = _safe_directory(arguments.model_root, label="model root")
    manifest, example = _load_example(dataset_root)
    if accelerator.is_main_process:
        output = _new_output(arguments.output)
    else:
        output = arguments.output.expanduser().resolve()
    accelerator.wait_for_everyone()

    tokenizer = AutoTokenizer.from_pretrained(model_root, local_files_only=True)
    item = _tokenize_example(tokenizer, example["messages"], arguments.max_seq_length)
    supervised_tokens = int((item["labels"] != -100).sum().item())
    repetitions = max(accelerator.num_processes * arguments.max_steps, accelerator.num_processes)
    dataset = _RepeatedExampleDataset(item, repetitions)
    loader = DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=_collate)

    model = AutoModelForCausalLM.from_pretrained(
        model_root,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    model.config.use_cache = False
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(
        model,
        LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=arguments.lora_r,
            lora_alpha=arguments.lora_alpha,
            lora_dropout=0.0,
            bias="none",
            target_modules="all-linear",
        ),
        autocast_adapter_dtype=False,
    )
    trainable_parameters = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    total_parameters = sum(parameter.numel() for parameter in model.parameters())
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=arguments.learning_rate,
    )
    model, optimizer, loader = accelerator.prepare(model, optimizer, loader)
    tracked = [
        (parameter, parameter.detach().clone())
        for parameter in model.parameters()
        if parameter.requires_grad and parameter.numel() > 0
    ]
    if not tracked:
        raise RuntimeError("FSDP rank has no nonempty trainable parameter shard")

    losses: list[float] = []
    started = time.monotonic()
    model.train()
    for step, batch in enumerate(loader):
        if step >= arguments.max_steps:
            break
        optimizer.zero_grad(set_to_none=True)
        result = model(**batch)
        loss = result.loss
        if not torch.isfinite(loss):
            raise RuntimeError("SFT loss is not finite")
        accelerator.backward(loss)
        accelerator.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        losses.append(float(accelerator.gather(loss.detach()).mean().item()))
    duration_s = time.monotonic() - started
    local_delta = torch.stack(
        [
            (parameter.detach() - initial).abs().max().to(torch.float32)
            for parameter, initial in tracked
        ]
    ).max()
    maximum_update = float(accelerator.reduce(local_delta, reduction="max").item())
    if maximum_update <= 0:
        raise RuntimeError("optimizer step did not change a trainable parameter")

    accelerator.wait_for_everyone()
    state_dict = accelerator.get_state_dict(model)
    unwrapped = accelerator.unwrap_model(model)
    unwrapped.save_pretrained(
        output,
        is_main_process=accelerator.is_main_process,
        save_function=accelerator.save,
        state_dict=state_dict,
        safe_serialization=True,
    )
    if accelerator.is_main_process:
        tokenizer.save_pretrained(output)
    accelerator.wait_for_everyone()

    report: dict[str, Any] = {}
    if accelerator.is_main_process:
        adapter_hash, inventory = _artifact_hash(output)
        report = {
            "schema_version": "1.0",
            "status": "completed",
            "training_kind": "verified_solution_lora_sft_smoke",
            "optimizer_steps": len(losses),
            "world_size": accelerator.num_processes,
            "mixed_precision": accelerator.mixed_precision,
            "seed": arguments.seed,
            "max_seq_length": arguments.max_seq_length,
            "input_tokens": int(item["input_ids"].numel()),
            "supervised_tokens": supervised_tokens,
            "losses": losses,
            "maximum_trainable_parameter_update": maximum_update,
            "tracked_nonempty_parameter_shards_rank0": len(tracked),
            "learning_rate": arguments.learning_rate,
            "lora_r": arguments.lora_r,
            "lora_alpha": arguments.lora_alpha,
            "lora_target_modules": "all-linear",
            "autocast_adapter_dtype": False,
            "trainable_parameters": trainable_parameters,
            "total_parameters": total_parameters,
            "trainable_fraction": trainable_parameters / total_parameters,
            "dataset_manifest_sha256": _sha256(dataset_root / "dataset-manifest.json"),
            "dataset_manifest_hash": manifest["manifest_hash"],
            "example_hash": example["example_hash"],
            "source_model_id": example["source_model_id"],
            "source_reasoning_effort": example["source_reasoning_effort"],
            "base_model_config_sha256": _sha256(model_root / "config.json"),
            "adapter_artifact_hash": adapter_hash,
            "adapter_inventory": inventory,
            "duration_s": duration_s,
            "software": {
                "python": platform.python_version(),
                "torch": torch.__version__,
                "transformers": transformers.__version__,
                "accelerate": accelerate.__version__,
                "peft": peft.__version__,
            },
            "hidden_assets_loaded": False,
            "reference_solution_loaded": False,
        }
        identity = dict(report)
        report["report_hash"] = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        _atomic_json(output / "training-report.json", report)
        print(json.dumps(report, indent=2, sort_keys=True))
    accelerator.wait_for_everyone()
    accelerator.end_training()
    return report


def main(argv: Sequence[str] | None = None) -> int:
    _run(_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
