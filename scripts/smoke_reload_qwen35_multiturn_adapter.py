#!/usr/bin/env python3
"""Four-A30 reload smoke for the frozen Qwen3.5 multi-turn LoRA adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import torch
import torch.distributed as dist
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

_OPT_IN_ENV = "VERIGYM_RUN_QWEN35_MULTITURN_RELOAD"
_EXPECTED_WORLD_SIZE = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reload the step-6 adapter on exactly four A30s.")
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--training-output", type=Path, required=True)
    return parser


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise SystemExit(f"{label} cannot be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise SystemExit(f"{label} must be a directory")
    return resolved


def _content_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    arguments = _parser().parse_args()
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required")
    if int(os.environ.get("WORLD_SIZE", "0")) != _EXPECTED_WORLD_SIZE:
        raise SystemExit("launch this smoke with torchrun --nproc-per-node=4")
    model_root = _safe_directory(arguments.model_root, "model root")
    output = _safe_directory(arguments.training_output, "training output")
    adapter = _safe_directory(output / "lora_adapter", "step-6 adapter")

    dist.init_process_group(backend="nccl")
    local_rank = int(os.environ["LOCAL_RANK"])
    rank = dist.get_rank()
    torch.cuda.set_device(local_rank)
    device_name = torch.cuda.get_device_name(local_rank)
    if "A30" not in device_name.upper():
        raise RuntimeError(f"rank {rank} is not running on an A30: {device_name}")

    tokenizer = AutoTokenizer.from_pretrained(model_root, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_root,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        device_map={"": local_rank},
    )
    model = PeftModel.from_pretrained(model, adapter, is_trainable=False)
    model.eval()
    encoded = tokenizer("module smoke;", return_tensors="pt")
    encoded = {key: value.to(local_rank) for key, value in encoded.items()}
    with torch.no_grad():
        logits = model(**encoded).logits[:, -1, :]
    passed = bool(torch.isfinite(logits).all().item() and logits.numel() > 0)
    flags = [None] * _EXPECTED_WORLD_SIZE if rank == 0 else None
    dist.gather_object(
        {"rank": rank, "device": device_name, "passed": passed},
        flags,
        dst=0,
    )
    dist.barrier()
    if rank == 0:
        if not flags or not all(item and item["passed"] for item in flags):
            raise RuntimeError("one or more ranks failed the adapter forward smoke")
        report_path = output / "training-report.json"
        report = json.loads(report_path.read_bytes())
        claimed = report.pop("report_hash", None)
        if claimed != _content_hash(report):
            raise RuntimeError("training report identity changed before reload smoke")
        report["reload_smoke"] = {
            "status": "passed",
            "world_size": _EXPECTED_WORLD_SIZE,
            "devices": flags,
        }
        report["report_hash"] = _content_hash(report)
        _atomic_json(report_path, report)
        print(json.dumps(report["reload_smoke"], sort_keys=True))
    dist.destroy_process_group()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
