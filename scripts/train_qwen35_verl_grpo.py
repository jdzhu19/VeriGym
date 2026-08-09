#!/usr/bin/env python3
"""Run one real Qwen3.5 LoRA GRPO update from scored rLLM trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
import warnings
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import accelerate
import numpy as np
import peft
import rllm
import torch
import transformers
import verl
from accelerate import Accelerator
from peft import PeftModel
from rllm.types import Episode
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from verl.trainer.ppo.core_algos import compute_grpo_outcome_advantage, compute_policy_loss

_OPT_IN_ENV = "VERIGYM_RUN_QWEN35_GRPO"
_MAX_DATASET_BYTES = 128 * 1024 * 1024


class _RolloutDataset(Dataset[dict[str, torch.Tensor]]):
    def __init__(self, items: list[dict[str, torch.Tensor]]) -> None:
        self._items = items

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        return {key: value.clone() for key, value in self._items[index].items()}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded rLLM/VeriGym/verl GRPO update.")
    parser.add_argument("--rollouts", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--input-policy-version", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--clip-range", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=484)
    parser.add_argument("--rllm-root", type=Path, required=True)
    parser.add_argument("--verl-root", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


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
            raise SystemExit("GRPO output must be a new or empty real directory")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _load_policy_version(path: Path, adapter: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4 * 1024 * 1024:
        raise SystemExit("input policy version must be a small regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("input policy version is not valid JSON") from exc
    if (
        not isinstance(value, dict)
        or value.get("format_id") != "verigym_training_policy_version_v1"
    ):
        raise SystemExit("unsupported input policy version format")
    expected = value.get("version_hash")
    identity = dict(value)
    identity.pop("version_hash", None)
    if not isinstance(expected, str) or _canonical_hash(identity) != expected:
        raise SystemExit("input policy version identity differs from its version hash")
    weight_version = value.get("weight_version")
    configuration = value.get("loading_configuration")
    if not isinstance(weight_version, int) or not isinstance(configuration, dict):
        raise SystemExit("GRPO input must be a registered trained policy")
    if (
        value.get("artifact_kind") != "lora_adapter"
        or value.get("executable") is not True
        or value.get("hidden_assets_loaded") is not False
        or value.get("reference_solution_loaded") is not False
        or value.get("credential_values_included") is not False
        or value.get("raw_host_paths_included") is not False
    ):
        raise SystemExit("input policy version is not eligible for GRPO")
    if configuration.get("adapter_weights_sha256") != _sha256(
        adapter / "adapter_model.safetensors"
    ):
        raise SystemExit("input adapter differs from its registered policy version")
    return value


def _load_records(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = root / "reward-manifest.json"
    data_path = root / "rollouts.scored.jsonl"
    if manifest_path.is_symlink() or data_path.is_symlink():
        raise SystemExit("reward inputs cannot be symlinks")
    payload = data_path.read_bytes()
    if not 0 < len(payload) <= _MAX_DATASET_BYTES:
        raise SystemExit("scored rollout JSONL is empty or oversized")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_identity = dict(manifest)
    expected_manifest_hash = manifest_identity.pop("manifest_hash", None)
    if (
        not isinstance(expected_manifest_hash, str)
        or _canonical_hash(manifest_identity) != expected_manifest_hash
    ):
        raise SystemExit("reward manifest identity differs from its manifest hash")
    format_id = manifest.get("format_id")
    if (
        format_id
        not in {
            "verigym_rllm_rollout_dataset_scored_v2",
            "verigym_rllm_rollout_dataset_scored_multi_v1",
        }
        or manifest.get("infrastructure_invalid_count") != 0
        or manifest.get("hidden_assets_exported_to_trainer") is not False
        or manifest.get("reference_solution_exported_to_trainer") is not False
        or _sha256(data_path) != manifest.get("scored_file_sha256")
    ):
        raise SystemExit("reward manifest is not eligible for GRPO")
    if format_id == "verigym_rllm_rollout_dataset_scored_multi_v1" and (
        manifest.get("credential_values_exported_to_trainer") is not False
        or manifest.get("raw_host_paths_exported_to_trainer") is not False
        or manifest.get("each_group_has_reward_variance") is not True
    ):
        raise SystemExit("multi-group reward manifest violates the trainer export policy")
    records = [json.loads(line) for line in payload.decode().splitlines()]
    if len(records) != manifest.get("record_count"):
        raise SystemExit("reward record count differs from its manifest")
    for record, expected in zip(records, manifest.get("record_hashes", []), strict=True):
        base = dict(record)
        record_hash = base.pop("record_hash", None)
        if record_hash != expected or _canonical_hash(base) != expected:
            raise SystemExit("scored rollout identity differs from its manifest")
        if record.get("infrastructure_valid") is not True or record.get("reward") not in {0.0, 1.0}:
            raise SystemExit("GRPO accepts only infrastructure-valid sparse rewards")
        episode = Episode.model_validate(record.get("episode"))
        if len(episode.trajectories) != 1 or len(episode.trajectories[0].steps) < 2:
            raise SystemExit("GRPO requires a multi-turn rLLM trajectory")
        if any(
            step.weight_version != manifest.get("weight_version")
            for step in episode.trajectories[0].steps
        ):
            raise SystemExit("rLLM step weight versions differ from the reward manifest")
        if record.get("policy_version_hash") != manifest.get("policy_version_hash") or record.get(
            "weight_version"
        ) != manifest.get("weight_version"):
            raise SystemExit("GRPO record policy binding differs from its reward manifest")
    grouped_rewards: defaultdict[str, list[float]] = defaultdict(list)
    for record in records:
        grouped_rewards[record["group_id"]].append(float(record["reward"]))
    if any(len(set(rewards)) < 2 for rewards in grouped_rewards.values()):
        raise SystemExit("GRPO requires nonzero reward variance within every group")
    if set(grouped_rewards) != set(manifest.get("group_ids", [])):
        raise SystemExit("GRPO record groups differ from the reward manifest")
    if {record.get("task_id") for record in records} != set(manifest.get("task_ids", [])):
        raise SystemExit("GRPO record tasks differ from the reward manifest")
    if format_id.endswith("multi_v1") and len(grouped_rewards) < 2:
        raise SystemExit("multi-group GRPO requires at least two groups")
    if format_id.endswith("scored_v2") and len(grouped_rewards) != 1:
        raise SystemExit("single-group GRPO requires exactly one group")
    return manifest, records


def _advantages(records: list[dict[str, Any]]) -> tuple[list[torch.Tensor], list[float]]:
    lengths = [
        len(record["episode"]["trajectories"][0]["steps"][1]["response_ids"]) for record in records
    ]
    if any(length <= 0 for length in lengths):
        raise SystemExit("trainable rLLM steps cannot have empty responses")
    maximum = max(lengths)
    mask = torch.zeros((len(records), maximum), dtype=torch.float32)
    token_rewards = torch.zeros_like(mask)
    for index, (record, length) in enumerate(zip(records, lengths, strict=True)):
        mask[index, :length] = 1.0
        token_rewards[index, length - 1] = float(record["reward"])
    group_ids = np.asarray([record["group_id"] for record in records], dtype=object)
    advantages, _ = compute_grpo_outcome_advantage(token_rewards, mask, group_ids)
    scalar_advantages = [float(advantages[index, 0].item()) for index in range(len(records))]
    per_record = [advantages[index, :length].clone() for index, length in enumerate(lengths)]
    return per_record, scalar_advantages


def _items(
    records: list[dict[str, Any]],
    advantages: list[torch.Tensor],
) -> list[dict[str, torch.Tensor]]:
    items: list[dict[str, torch.Tensor]] = []
    for record, advantage in zip(records, advantages, strict=True):
        step = record["episode"]["trajectories"][0]["steps"][1]
        prompt_ids = step["prompt_ids"]
        response_ids = step["response_ids"]
        old_logprobs = step["logprobs"]
        if len(response_ids) != len(old_logprobs) or len(response_ids) != advantage.numel():
            raise SystemExit("rLLM token IDs, log probabilities, and advantages differ")
        input_ids = torch.tensor([*prompt_ids, *response_ids], dtype=torch.long)
        items.append(
            {
                "input_ids": input_ids,
                "attention_mask": torch.ones_like(input_ids),
                "response_start": torch.tensor(len(prompt_ids), dtype=torch.long),
                "old_logprobs": torch.tensor(old_logprobs, dtype=torch.float32),
                "advantages": advantage.to(torch.float32),
                "response_mask": torch.ones(len(response_ids), dtype=torch.float32),
            }
        )
    return items


def _collate(items: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    if len(items) != 1:
        raise RuntimeError("GRPO smoke uses a per-rank micro-batch of one")
    return {key: value.unsqueeze(0) for key, value in items[0].items()}


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        shell=False,
        text=True,
        timeout=10,
    )
    value = completed.stdout.strip()
    if len(value) != 40:
        raise SystemExit("dependency checkout has no commit identity")
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
    accelerator = Accelerator(mixed_precision="bf16")
    torch.manual_seed(arguments.seed)
    rollout_root = _safe_directory(arguments.rollouts, "rollout root")
    model_root = _safe_directory(arguments.model_root, "model root")
    adapter = _safe_directory(arguments.adapter, "adapter")
    policy_version = _load_policy_version(arguments.input_policy_version, adapter)
    rllm_root = _safe_directory(arguments.rllm_root, "rLLM root")
    verl_root = _safe_directory(arguments.verl_root, "verl root")
    manifest, records = _load_records(rollout_root)
    if (
        manifest.get("policy_version_hash") != policy_version["version_hash"]
        or manifest.get("weight_version") != policy_version["weight_version"]
    ):
        raise SystemExit("reward trajectories were not sampled by the input policy version")
    advantage_tensors, scalar_advantages = _advantages(records)
    items = _items(records, advantage_tensors)
    group_counts: defaultdict[str, int] = defaultdict(int)
    for record in records:
        group_counts[record["group_id"]] += 1
    if any(count != accelerator.num_processes for count in group_counts.values()):
        raise SystemExit("every GRPO group size must equal the distributed world size")
    optimizer_steps = len(group_counts)
    if accelerator.is_main_process:
        output = _new_directory(arguments.output)
    else:
        output = arguments.output.expanduser().resolve()
    accelerator.wait_for_everyone()

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
        is_trainable=True,
        autocast_adapter_dtype=False,
    )
    model.config.use_cache = False
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    trainable_parameters = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    total_parameters = sum(parameter.numel() for parameter in model.parameters())
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=arguments.learning_rate,
    )
    loader = DataLoader(_RolloutDataset(items), batch_size=1, shuffle=False, collate_fn=_collate)
    model, optimizer, loader = accelerator.prepare(model, optimizer, loader)
    tracked = [
        (parameter, parameter.detach().clone())
        for parameter in model.parameters()
        if parameter.requires_grad and parameter.numel() > 0
    ]
    if not tracked:
        raise RuntimeError("FSDP rank has no nonempty trainable parameter shard")

    started = time.monotonic()
    model.train()
    gathered_metric_steps: list[list[list[float]]] = []
    completed_steps = 0
    for batch in loader:
        optimizer.zero_grad(set_to_none=True)
        response_start = int(batch.pop("response_start").item())
        old_logprobs = batch.pop("old_logprobs")
        advantages = batch.pop("advantages")
        response_mask = batch.pop("response_mask")
        response_length = old_logprobs.shape[1]
        result = model(**batch, logits_to_keep=response_length + 1)
        token_logits = result.logits[:, :-1]
        targets = batch["input_ids"][:, response_start : response_start + response_length]
        logprobs = torch.log_softmax(token_logits.float(), dim=-1)
        current_logprobs = torch.gather(logprobs, dim=-1, index=targets.unsqueeze(-1)).squeeze(-1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            policy_loss, clip_fraction, approximate_kl, lower_clip_fraction = compute_policy_loss(
                old_logprobs,
                current_logprobs,
                advantages,
                response_mask,
                cliprange=arguments.clip_range,
                loss_agg_mode="token-mean",
            )
        if not torch.isfinite(policy_loss):
            raise RuntimeError("GRPO policy loss is not finite")
        accelerator.backward(policy_loss)
        accelerator.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        metrics = torch.tensor(
            [policy_loss.detach(), clip_fraction, approximate_kl, lower_clip_fraction],
            device=accelerator.device,
            dtype=torch.float32,
        )
        gathered_metrics = accelerator.gather(metrics).reshape(accelerator.num_processes, 4)
        gathered_metric_steps.append(gathered_metrics.tolist())
        completed_steps += 1
    duration_s = time.monotonic() - started
    if completed_steps != optimizer_steps:
        raise RuntimeError("distributed loader did not consume exactly one step per GRPO group")
    local_delta = torch.stack(
        [
            (parameter.detach() - initial).abs().max().to(torch.float32)
            for parameter, initial in tracked
        ]
    ).max()
    maximum_update = float(accelerator.reduce(local_delta, reduction="max").item())
    if maximum_update <= 0:
        raise RuntimeError("GRPO optimizer step did not change a trainable parameter")

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
        artifact_hash, inventory = _artifact_hash(output)
        report = {
            "schema_version": "1.0",
            "status": "completed",
            "training_kind": (
                "rllm_verigym_verl_multigroup_grpo_lora_smoke"
                if optimizer_steps > 1
                else "rllm_verigym_verl_grpo_lora_smoke"
            ),
            "optimizer_steps": optimizer_steps,
            "group_count": len(group_counts),
            "group_ids": list(group_counts),
            "task_ids": manifest["task_ids"],
            "world_size": accelerator.num_processes,
            "mixed_precision": accelerator.mixed_precision,
            "seed": arguments.seed,
            "learning_rate": arguments.learning_rate,
            "clip_range": arguments.clip_range,
            "rewards": [float(record["reward"]) for record in records],
            "grpo_scalar_advantages": scalar_advantages,
            "optimizer_step_rank_metrics_policy_loss_clipfrac_kl_lower_clipfrac": (
                gathered_metric_steps
            ),
            "maximum_trainable_parameter_update": maximum_update,
            "trainable_parameters": trainable_parameters,
            "total_parameters": total_parameters,
            "trainable_fraction": trainable_parameters / total_parameters,
            "rollout_manifest_hash": manifest["manifest_hash"],
            "input_policy_version_hash": policy_version["version_hash"],
            "input_policy_version_id": policy_version["policy_version_id"],
            "input_weight_version": policy_version["weight_version"],
            "output_weight_version": policy_version["weight_version"] + 1,
            "rollout_policy_binding_verified": True,
            "rollout_manifest_sha256": _sha256(rollout_root / "reward-manifest.json"),
            "parent_adapter_weights_sha256": _sha256(adapter / "adapter_model.safetensors"),
            "base_model_config_sha256": _sha256(model_root / "config.json"),
            "adapter_artifact_hash": artifact_hash,
            "adapter_inventory": inventory,
            "duration_s": duration_s,
            "rllm_commit": _git_head(rllm_root),
            "verl_commit": _git_head(verl_root),
            "software": {
                "python": platform.python_version(),
                "torch": torch.__version__,
                "transformers": transformers.__version__,
                "accelerate": accelerate.__version__,
                "peft": peft.__version__,
                "rllm": getattr(rllm, "__version__", "editable-checkout"),
                "verl": getattr(verl, "__version__", "editable-checkout"),
            },
            "rllm_episode_schema_validated": True,
            "verl_grpo_advantage_used": True,
            "verl_clipped_policy_loss_used": True,
            "hidden_assets_loaded": False,
            "reference_solution_loaded": False,
            "full_ray_vllm_stack_qualified": False,
        }
        report["report_hash"] = _canonical_hash(report)
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
