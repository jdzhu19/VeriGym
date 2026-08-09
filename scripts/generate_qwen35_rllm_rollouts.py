#!/usr/bin/env python3
"""Generate a bounded group of multi-turn rLLM RTL trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import peft
import torch
import transformers
from peft import PeftModel
from rllm.types import Episode, Step, Trajectory
from transformers import AutoModelForCausalLM, AutoTokenizer

_OPT_IN_ENV = "VERIGYM_RUN_RLLM_ROLLOUTS"
_MAX_INPUT_BYTES = 4 * 1024 * 1024
_VERILOG_BLOCK = re.compile(r"<verilog>\s*(.*?)\s*</verilog>", re.DOTALL | re.IGNORECASE)
_FENCED_BLOCK = re.compile(r"```(?:system)?verilog\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sample multi-turn Qwen3.5 rLLM trajectories.")
    parser.add_argument("--public-input", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--policy-version", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group-size", type=int, default=4)
    parser.add_argument("--plan-tokens", type=int, default=96)
    parser.add_argument("--solution-tokens", type=int, default=224)
    parser.add_argument("--temperature", type=float, default=1.2)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=484)
    return parser


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_bytes(encoded.encode())


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise SystemExit(f"{label} cannot be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise SystemExit(f"{label} must be a directory")
    return resolved


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise SystemExit("rollout output must be a new or empty real directory")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _read_public_input(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_INPUT_BYTES:
        raise SystemExit("public input must be a small regular file")
    payload = path.read_bytes()
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("public input is not valid JSON") from exc
    required = {
        "task_id",
        "task_description",
        "public_readme",
        "candidate_path",
        "candidate_skeleton",
        "record_hash",
    }
    if not isinstance(value, dict) or not required.issubset(value):
        raise SystemExit("public input omits required task fields")
    if value.get("hidden_assets_included") is not False:
        raise SystemExit("rollout input must explicitly exclude hidden assets")
    expected = value["record_hash"]
    identity = dict(value)
    identity.pop("record_hash")
    if not isinstance(expected, str) or _canonical_hash(identity) != expected:
        raise SystemExit("public input identity differs from its record hash")
    return value, _sha256_bytes(payload)


def _read_policy_version(path: Path, adapter: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_INPUT_BYTES:
        raise SystemExit("policy version must be a small regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("policy version is not valid JSON") from exc
    if (
        not isinstance(value, dict)
        or value.get("format_id") != "verigym_training_policy_version_v1"
    ):
        raise SystemExit("unsupported policy version format")
    expected = value.get("version_hash")
    identity = dict(value)
    identity.pop("version_hash", None)
    if not isinstance(expected, str) or _canonical_hash(identity) != expected:
        raise SystemExit("policy version identity differs from its version hash")
    weight_version = value.get("weight_version")
    configuration = value.get("loading_configuration")
    if not isinstance(weight_version, int) or weight_version < 0:
        raise SystemExit("rollout generation requires a trained policy weight version")
    if not isinstance(configuration, dict):
        raise SystemExit("policy version has no loading configuration")
    if (
        value.get("artifact_kind") != "lora_adapter"
        or value.get("executable") is not True
        or value.get("hidden_assets_loaded") is not False
        or value.get("reference_solution_loaded") is not False
        or value.get("credential_values_included") is not False
        or value.get("raw_host_paths_included") is not False
    ):
        raise SystemExit("policy version is not eligible for public rollout generation")
    actual_weights = _sha256(adapter / "adapter_model.safetensors")
    if configuration.get("adapter_weights_sha256") != actual_weights:
        raise SystemExit("adapter weights differ from the registered policy version")
    return value


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


def _atomic_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _template_ids(tokenizer: Any, messages: list[dict[str, str]]) -> torch.Tensor:
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
        return_tensors="pt",
    )
    if isinstance(encoded, torch.Tensor):
        return encoded
    return encoded["input_ids"]


def _generate(
    model: Any,
    tokenizer: Any,
    messages: list[dict[str, str]],
    *,
    maximum: int,
    temperature: float,
    top_p: float,
    seed: int,
) -> tuple[str, list[int], list[int], list[float]]:
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    prompt = _template_ids(tokenizer, messages).to(model.device)
    with torch.inference_mode():
        generated = model.generate(
            input_ids=prompt,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            max_new_tokens=maximum,
            pad_token_id=tokenizer.eos_token_id,
            return_dict_in_generate=True,
            output_scores=True,
        )
    response = generated.sequences[0, prompt.shape[1] :]
    scores = generated.scores
    if len(scores) != response.numel():
        raise RuntimeError("generation scores differ from the sampled response length")
    logprobs = [
        float(torch.log_softmax(score[0].float(), dim=-1)[token].item())
        for score, token in zip(scores, response, strict=True)
    ]
    text = tokenizer.decode(response, skip_special_tokens=True)
    return text, prompt[0].tolist(), response.tolist(), logprobs


def _candidate(response: str) -> tuple[str, str]:
    tagged = _VERILOG_BLOCK.search(response)
    if tagged is not None:
        return tagged.group(1).strip() + "\n", "verilog_tags"
    fenced = _FENCED_BLOCK.search(response)
    if fenced is not None:
        return fenced.group(1).strip() + "\n", "markdown_fence_fallback"
    return response.strip() + "\n", "full_response_fallback"


def _task_material(public_input: dict[str, Any]) -> str:
    return (
        f"TASK DESCRIPTION\n{public_input['task_description']}\n\n"
        f"PUBLIC README\n{public_input['public_readme']}\n\n"
        f"CURRENT FILE ({public_input['candidate_path']})\n"
        f"{public_input['candidate_skeleton']}"
    )


def _record(
    public_input: dict[str, Any],
    *,
    group_id: str,
    policy_version: dict[str, Any],
    sample_index: int,
    plan: tuple[str, list[int], list[int], list[float]],
    solution: tuple[str, list[int], list[int], list[float]],
) -> dict[str, Any]:
    plan_text, plan_prompt, plan_ids, plan_logprobs = plan
    solution_text, solution_prompt, solution_ids, solution_logprobs = solution
    candidate, extraction = _candidate(solution_text)
    weight_version = policy_version["weight_version"]
    version_hash = policy_version["version_hash"]
    trajectory = Trajectory(
        name="verigym_rtl_multiturn_v2",
        task=public_input["task_id"],
        input={"public_input_hash": public_input["record_hash"]},
        output=candidate,
        reward=None,
        steps=[
            Step(
                input="analyze_public_task",
                output=plan_text,
                action="plan",
                reward=0.0,
                done=False,
                prompt_ids=plan_prompt,
                response_ids=plan_ids,
                logprobs=plan_logprobs,
                model_response=plan_text,
                weight_version=weight_version,
                metadata={
                    "trainable": False,
                    "turn": 0,
                    "policy_version_hash": version_hash,
                    "weight_version": weight_version,
                },
            ),
            Step(
                input="emit_complete_rtl",
                output=candidate,
                action="submit_candidate",
                reward=0.0,
                done=True,
                prompt_ids=solution_prompt,
                response_ids=solution_ids,
                logprobs=solution_logprobs,
                model_response=solution_text,
                weight_version=weight_version,
                metadata={
                    "trainable": True,
                    "turn": 1,
                    "candidate_extraction": extraction,
                    "policy_version_hash": version_hash,
                    "weight_version": weight_version,
                },
            ),
        ],
        metadata={
            "group_id": group_id,
            "sample_index": sample_index,
            "trainable_step": 1,
            "policy_version_hash": version_hash,
            "weight_version": weight_version,
        },
    )
    episode = Episode(
        task=public_input["task_id"],
        termination_reason="candidate_submitted",
        is_correct=False,
        trajectories=[trajectory],
        metadata={
            "group_id": group_id,
            "sample_index": sample_index,
            "verifier_pending": True,
            "policy_version_hash": version_hash,
            "weight_version": weight_version,
        },
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_rllm_rollout_unscored_v2",
        "group_id": group_id,
        "policy_version_hash": version_hash,
        "weight_version": weight_version,
        "sample_index": sample_index,
        "task_id": public_input["task_id"],
        "public_input_hash": public_input["record_hash"],
        "candidate_path": public_input["candidate_path"],
        "candidate_sha256": _sha256_bytes(candidate.encode()),
        "candidate": candidate,
        "episode": episode.model_dump(mode="json"),
        "hidden_assets_loaded": False,
        "reference_solution_loaded": False,
    }
    return {**base, "record_hash": _canonical_hash(base)}


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    if not 2 <= arguments.group_size <= 16:
        raise SystemExit("--group-size must be in [2, 16]")
    if not 32 <= arguments.plan_tokens <= 256:
        raise SystemExit("--plan-tokens must be in [32, 256]")
    if not 64 <= arguments.solution_tokens <= 512:
        raise SystemExit("--solution-tokens must be in [64, 512]")
    public_input, public_file_hash = _read_public_input(arguments.public_input)
    model_root = _safe_directory(arguments.model_root, "model root")
    adapter = _safe_directory(arguments.adapter, "adapter")
    policy_version = _read_policy_version(arguments.policy_version, adapter)
    output = _new_directory(arguments.output)

    group_id = _canonical_hash(
        {
            "format_id": "verigym_rllm_rollout_group_v2",
            "public_input_hash": public_input["record_hash"],
            "policy_version_hash": policy_version["version_hash"],
            "weight_version": policy_version["weight_version"],
            "group_size": arguments.group_size,
            "temperature": arguments.temperature,
            "top_p": arguments.top_p,
            "seed": arguments.seed,
        }
    )

    tokenizer = AutoTokenizer.from_pretrained(model_root, local_files_only=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        model_root,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    model = PeftModel.from_pretrained(
        base_model,
        adapter,
        is_trainable=False,
        autocast_adapter_dtype=False,
    ).to("cuda:0")
    model.eval()
    system = "You are a professional RTL design agent. Use only the supplied public task material."
    material = _task_material(public_input)
    records: list[dict[str, Any]] = []
    started = time.monotonic()
    for index in range(arguments.group_size):
        plan_messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": material
                + "\n\nAnalyze the required behavior and give a concise implementation plan. "
                "Do not emit the final Verilog yet.",
            },
        ]
        plan = _generate(
            model,
            tokenizer,
            plan_messages,
            maximum=arguments.plan_tokens,
            temperature=arguments.temperature,
            top_p=arguments.top_p,
            seed=arguments.seed + index * 2,
        )
        solution_messages = [
            *plan_messages,
            {"role": "assistant", "content": plan[0]},
            {
                "role": "user",
                "content": "Now return the complete candidate source and nothing else between "
                "<verilog> and </verilog> tags. Preserve the exact requested module interface.",
            },
        ]
        solution = _generate(
            model,
            tokenizer,
            solution_messages,
            maximum=arguments.solution_tokens,
            temperature=arguments.temperature,
            top_p=arguments.top_p,
            seed=arguments.seed + index * 2 + 1,
        )
        records.append(
            _record(
                public_input,
                group_id=group_id,
                policy_version=policy_version,
                sample_index=index,
                plan=plan,
                solution=solution,
            )
        )
    del model, base_model
    torch.cuda.empty_cache()
    rollout_path = output / "rollouts.unscored.jsonl"
    _atomic_jsonl(rollout_path, records)
    base_manifest = {
        "schema_version": "1.0",
        "format_id": "verigym_rllm_rollout_dataset_unscored_v2",
        "record_count": len(records),
        "record_hashes": [record["record_hash"] for record in records],
        "group_ids": sorted({record["group_id"] for record in records}),
        "task_ids": sorted({record["task_id"] for record in records}),
        "rollout_file_sha256": _sha256(rollout_path),
        "public_input_file_sha256": public_file_hash,
        "public_input_hash": public_input["record_hash"],
        "policy_version_hash": policy_version["version_hash"],
        "policy_version_id": policy_version["policy_version_id"],
        "weight_version": policy_version["weight_version"],
        "base_model_config_sha256": _sha256(model_root / "config.json"),
        "adapter_config_sha256": _sha256(adapter / "adapter_config.json"),
        "adapter_weights_sha256": _sha256(adapter / "adapter_model.safetensors"),
        "group_size": arguments.group_size,
        "temperature": arguments.temperature,
        "top_p": arguments.top_p,
        "seed": arguments.seed,
        "turn_count": 2,
        "trainable_step": 1,
        "duration_s": time.monotonic() - started,
        "software": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "peft": peft.__version__,
        },
        "hidden_assets_loaded": False,
        "reference_solution_loaded": False,
    }
    manifest = {**base_manifest, "manifest_hash": _canonical_hash(base_manifest)}
    _atomic_json(output / "rollout-manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    _run(_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
