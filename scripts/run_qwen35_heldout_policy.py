#!/usr/bin/env python3
"""Evaluate one registered Qwen3.5 policy on an exact frozen held-out split."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_OPT_IN_ENV = "VERIGYM_RUN_QWEN35_HELDOUT"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heldout-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--policy-version", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--verifier-image", required=True)
    parser.add_argument("--verifier-image-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group-size", type=int, default=2)
    parser.add_argument("--plan-tokens", type=int, default=96)
    parser.add_argument("--solution-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=20260809)
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


def _read_hashed(path: Path, hash_field: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"invalid JSON object: {path.name}")
    identity = dict(value)
    expected = identity.pop(hash_field, None)
    if not isinstance(expected, str) or _canonical_hash(identity) != expected:
        raise SystemExit(f"identity differs from {hash_field}: {path.name}")
    return value


def _run_command(command: list[str], log: Path, env: dict[str, str]) -> None:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=3600,
    )
    log.write_text(
        completed.stdout
        + ("\nSTDERR\n" + completed.stderr if completed.stderr else "")
        + f"\nDURATION_S={time.monotonic() - started:.6f}\n",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"held-out command failed with exit {completed.returncode}; see {log.name}"
        )


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    heldout_root = arguments.heldout_root.resolve(strict=True)
    split = _read_hashed(heldout_root / "task-split.json", "manifest_hash")
    public_manifest = _read_hashed(heldout_root / "public-input-manifest.json", "manifest_hash")
    policy = _read_hashed(arguments.policy_version.resolve(strict=True), "version_hash")
    if public_manifest.get("split_manifest_hash") != split["manifest_hash"]:
        raise SystemExit("held-out public inputs differ from the frozen split")
    if public_manifest.get("sample_eligible_for_training") is not False:
        raise SystemExit("held-out inputs must be permanently ineligible for training")
    output = arguments.output.expanduser()
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise SystemExit("held-out policy output must be a real directory")
    else:
        output.mkdir(parents=True)
    if (output / "evaluation-manifest.json").exists():
        raise SystemExit("held-out policy evaluation is already sealed")

    repository = Path(__file__).resolve().parents[1]
    generator = repository / "scripts" / "generate_qwen35_rllm_rollouts.py"
    scorer = repository / "scripts" / "score_rllm_rollouts.py"
    env = dict(os.environ)
    env["VERIGYM_RUN_RLLM_ROLLOUTS"] = "1"
    env["VERIGYM_RUN_RLLM_REWARD"] = "1"
    tasks: list[dict[str, Any]] = []
    started = time.monotonic()
    for task_index, entry in enumerate(split["heldout"]):
        native_id = entry["task_id"].rsplit("/", 1)[1]
        public_input = heldout_root / "public-inputs" / native_id / "public-input.json"
        task_root = output / "tasks" / native_id
        trajectories = task_root / "trajectories"
        rewards = task_root / "rewards"
        task_root.mkdir(parents=True, exist_ok=True)
        if not (trajectories / "rollout-manifest.json").exists():
            _run_command(
                [
                    sys.executable,
                    str(generator),
                    "--public-input",
                    str(public_input),
                    "--model-root",
                    str(arguments.model_root),
                    "--adapter",
                    str(arguments.adapter),
                    "--policy-version",
                    str(arguments.policy_version),
                    "--output",
                    str(trajectories),
                    "--group-size",
                    str(arguments.group_size),
                    "--plan-tokens",
                    str(arguments.plan_tokens),
                    "--solution-tokens",
                    str(arguments.solution_tokens),
                    "--temperature",
                    str(arguments.temperature),
                    "--top-p",
                    str(arguments.top_p),
                    "--seed",
                    str(arguments.seed + task_index * 100),
                ],
                task_root / "generate.log",
                env,
            )
        if not (rewards / "reward-manifest.json").exists():
            _run_command(
                [
                    sys.executable,
                    str(scorer),
                    "--rollouts",
                    str(trajectories),
                    "--output",
                    str(rewards),
                    "--source",
                    str(arguments.source),
                    "--variant",
                    arguments.variant,
                    "--task",
                    entry["task_id"],
                    "--verifier-image",
                    arguments.verifier_image,
                    "--verifier-image-id",
                    arguments.verifier_image_id,
                    "--seed",
                    str(arguments.seed + task_index * 100),
                ],
                task_root / "score.log",
                env,
            )
        reward_manifest = _read_hashed(rewards / "reward-manifest.json", "manifest_hash")
        tasks.append(
            {
                "task_id": entry["task_id"],
                "task_hash": entry["task_hash"],
                "reward_manifest_hash": reward_manifest["manifest_hash"],
                "rewards": reward_manifest["rewards"],
                "infrastructure_invalid_count": reward_manifest["infrastructure_invalid_count"],
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_qwen35_heldout_policy_evaluation_v1",
        "split_manifest_hash": split["manifest_hash"],
        "policy_version_hash": policy["version_hash"],
        "policy_version_id": policy["policy_version_id"],
        "weight_version": policy["weight_version"],
        "adapter_weights_sha256": _sha256(arguments.adapter / "adapter_model.safetensors"),
        "task_count": len(tasks),
        "sample_count": len(tasks) * arguments.group_size,
        "group_size": arguments.group_size,
        "plan_tokens": arguments.plan_tokens,
        "solution_tokens": arguments.solution_tokens,
        "temperature": arguments.temperature,
        "top_p": arguments.top_p,
        "seed": arguments.seed,
        "tasks": tasks,
        "duration_s": time.monotonic() - started,
        "hidden_assets_exported_to_policy": False,
        "reference_solutions_exported_to_policy": False,
        "training_reuse_allowed": False,
    }
    manifest = {**base, "manifest_hash": _canonical_hash(base)}
    _atomic_json(output / "evaluation-manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    _run(_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
