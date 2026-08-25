"""Independent Qwen3.5 base/LoRA reload and exact six-tool generation smoke."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_TOOL_CALL = re.compile(
    r"<tool_call>\s*<function=([^>\s]+)>\s*(.*?)\s*</function>\s*</tool_call>",
    re.DOTALL,
)
_PARAMETER = re.compile(
    r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>",
    re.DOTALL,
)
_EXPECTED_TOOLS = {
    "apply_patch",
    "finish",
    "inspect_diff",
    "list_files",
    "read_file",
    "shell",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def parse_qwen_tool_calls(text: str) -> list[dict[str, Any]]:
    """Parse the frozen Qwen3.5 XML tool-call contract without accepting suffix prose."""

    matches = list(_TOOL_CALL.finditer(text))
    if not matches:
        return []
    suffix = text[matches[-1].end() :].strip()
    if suffix:
        raise ValueError("Qwen tool-call generation contains a forbidden suffix")
    calls: list[dict[str, Any]] = []
    for match in matches:
        name = match.group(1)
        if name not in _EXPECTED_TOOLS:
            raise ValueError("Qwen generation selected a tool outside the six-tool contract")
        body = match.group(2)
        arguments: dict[str, Any] = {}
        spans: list[tuple[int, int]] = []
        for parameter in _PARAMETER.finditer(body):
            key, raw = parameter.group(1), parameter.group(2).strip()
            if key in arguments:
                raise ValueError("Qwen generation repeated a tool parameter")
            try:
                arguments[key] = json.loads(raw)
            except json.JSONDecodeError:
                arguments[key] = raw
            spans.append(parameter.span())
        residue = body
        for start, end in reversed(spans):
            residue = residue[:start] + residue[end:]
        if residue.strip():
            raise ValueError("Qwen generation contains malformed tool parameters")
        calls.append({"name": name, "arguments": arguments})
    return calls


def _load_model(model_root: Path, adapter: Path | None, *, device: str) -> Any:
    import torch  # type: ignore[import-not-found]
    from transformers import AutoConfig
    from transformers.models.qwen3_5.modeling_qwen3_5 import (  # type: ignore[import-not-found]
        Qwen3_5ForCausalLM,
    )

    composite = AutoConfig.from_pretrained(
        model_root,
        local_files_only=True,
        trust_remote_code=False,
    )
    config = getattr(composite, "text_config", None)
    if config is None or getattr(config, "model_type", None) != "qwen3_5_text":
        raise RuntimeError("frozen Qwen3.5 snapshot lacks its causal text config")
    model = Qwen3_5ForCausalLM.from_pretrained(
        model_root,
        config=config,
        key_mapping={r"^model\.language_model\.": "model."},
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        device_map={"": device},
        attn_implementation="flash_attention_2",
    )
    if adapter is not None:
        from peft import PeftModel  # type: ignore[import-not-found]

        model = PeftModel.from_pretrained(model, adapter, is_trainable=False)
    model.eval()
    return model


def _load_model_sharded(
    model_root: Path,
    adapter: Path | None,
    *,
    gpu_count: int,
    max_memory_per_gpu_bytes: int,
) -> Any:
    """Load the same BF16 model across a bounded set of local CUDA devices."""

    if gpu_count != 4:
        raise ValueError("sharded Qwen3.5 inference requires exactly four GPUs")
    if max_memory_per_gpu_bytes != 20 * 1024**3:
        raise ValueError("sharded Qwen3.5 inference memory bound changed")

    import torch
    from transformers import AutoConfig
    from transformers.models.qwen3_5.modeling_qwen3_5 import (
        Qwen3_5ForCausalLM,
    )

    if torch.cuda.device_count() != gpu_count:
        raise RuntimeError("sharded Qwen3.5 inference CUDA device count changed")
    composite = AutoConfig.from_pretrained(
        model_root,
        local_files_only=True,
        trust_remote_code=False,
    )
    config = getattr(composite, "text_config", None)
    if config is None or getattr(config, "model_type", None) != "qwen3_5_text":
        raise RuntimeError("frozen Qwen3.5 snapshot lacks its causal text config")
    model = Qwen3_5ForCausalLM.from_pretrained(
        model_root,
        config=config,
        key_mapping={r"^model\.language_model\.": "model."},
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        device_map="balanced",
        max_memory={index: max_memory_per_gpu_bytes for index in range(gpu_count)},
        attn_implementation="flash_attention_2",
    )
    if adapter is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter, is_trainable=False)
    model.eval()
    placement = getattr(getattr(model, "base_model", model), "model", model)
    device_map = getattr(placement, "hf_device_map", None)
    if not isinstance(device_map, dict) or {str(value) for value in device_map.values()} != {
        "0",
        "1",
        "2",
        "3",
    }:
        raise RuntimeError("sharded Qwen3.5 inference did not use all four GPUs")
    return model


def _generate(
    *,
    model_root: Path,
    adapter: Path | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    import torch
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
        model_root,
        local_files_only=True,
        trust_remote_code=False,
    )
    encoded_prompt = tokenizer.apply_chat_template(
        messages,
        tools=tools,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    prompt_ids = (
        encoded_prompt.get("input_ids") if isinstance(encoded_prompt, Mapping) else encoded_prompt
    )
    if (
        not isinstance(prompt_ids, list)
        or not prompt_ids
        or not all(isinstance(value, int) for value in prompt_ids)
        or len(prompt_ids) > 65_536
    ):
        raise RuntimeError("native inference prompt is empty or overlength")
    model = _load_model(model_root, adapter, device="cuda:0")
    input_ids = torch.tensor([prompt_ids], dtype=torch.long, device="cuda:0")
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    with torch.inference_mode():
        generated = model.generate(
            input_ids=input_ids,
            do_sample=False,
            max_new_tokens=256,
            use_cache=True,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    torch.cuda.synchronize()
    new_ids = generated[0, input_ids.shape[1] :].tolist()
    text = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
    calls = parse_qwen_tool_calls(text)
    result = {
        "prompt_token_count": len(prompt_ids),
        "generated_token_count": len(new_ids),
        "generated_ids_sha256": hashlib.sha256(
            b"".join(int(value).to_bytes(4, "big") for value in new_ids)
        ).hexdigest(),
        "generated_text": text,
        "tool_calls": calls,
        "tool_call_count": len(calls),
        "finite_generation": True,
        "wall_seconds": time.monotonic() - started,
        "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "peak_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
    }
    del model, input_ids, generated
    gc.collect()
    torch.cuda.empty_cache()
    return result


def run_reload_and_tool_smoke(
    *,
    model_root: Path,
    adapter: Path,
    dataset_root: Path,
    report: Path,
) -> dict[str, Any]:
    """Reload base and adapter independently and require a native tool call from the adapter."""

    if report.exists() or report.is_symlink():
        raise ValueError("native inference report already exists")
    for path, label in (
        (model_root, "model"),
        (adapter, "adapter"),
        (dataset_root, "dataset"),
    ):
        if path.is_symlink() or not path.resolve(strict=True).is_dir():
            raise ValueError(f"native inference {label} root is unsafe")
    rows = [
        json.loads(line)
        for line in (dataset_root / "train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if len(rows) != 83:
        raise ValueError("native inference dataset row count changed")
    row = rows[0]
    if row.get("source_v3_record_index") != 0 or row.get("token_count") != 2001:
        raise ValueError("native inference frozen smoke row changed")
    messages = row.get("input_messages")
    tools = row.get("tools")
    if not isinstance(messages, list) or not isinstance(tools, list):
        raise ValueError("native inference smoke row lacks messages or tools")
    names = {item.get("function", {}).get("name") for item in tools if isinstance(item, dict)}
    if names != _EXPECTED_TOOLS:
        raise ValueError("native inference smoke row six-tool schema changed")
    started = time.monotonic()
    base = _generate(model_root=model_root, adapter=None, messages=messages, tools=tools)
    adapted = _generate(model_root=model_root, adapter=adapter, messages=messages, tools=tools)
    if adapted["tool_call_count"] < 1:
        raise RuntimeError("reloaded adapter did not emit a native Qwen tool call")
    inventory = _inventory(adapter)
    value = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_qwen35_adapter_native_inference_smoke_v1",
        "status": "passed",
        "scope": "independent_base_and_adapter_reload_on_frozen_public_train_prefix",
        "source_v4_record_index": 0,
        "source_v4_record_hash": row["record_hash"],
        "tools_present": sorted(_EXPECTED_TOOLS),
        "base": base,
        "adapter": adapted,
        "adapter_artifact_hash": hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "adapter_artifacts": inventory,
        "independent_reload_passed": True,
        "native_tool_call_smoke_passed": True,
        "training_target_compared": False,
        "heldout_transcript_loaded": False,
        "benchmark_score_claimed": False,
        "production_training_ready": False,
        "wall_seconds": time.monotonic() - started,
    }
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    from verigym.experiments.state import atomic_dump_json

    atomic_dump_json(report, value)
    return value


def _inventory(root: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("adapter contains a symlink")
        if path.is_file():
            values.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    if not values or not any(item["path"].startswith("adapter_model") for item in values):
        raise ValueError("compact adapter inventory is incomplete")
    return values


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    arguments = _parser().parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0":
        raise SystemExit("native inference smoke requires CUDA_VISIBLE_DEVICES=0")
    value = run_reload_and_tool_smoke(
        model_root=arguments.model_root,
        adapter=arguments.adapter,
        dataset_root=arguments.dataset_root,
        report=arguments.report,
    )
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["parse_qwen_tool_calls", "run_reload_and_tool_smoke"]
