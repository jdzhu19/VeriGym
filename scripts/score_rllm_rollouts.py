#!/usr/bin/env python3
"""Score public-only rLLM candidates with an isolated VeriGym verifier."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from verigym.agents.base import AgentAdapter, AgentContext
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.registry.collections import build_registries
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    EpisodeResult,
    FinalSubmissionAction,
    Observation,
)
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor, InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_OPT_IN_ENV = "VERIGYM_RUN_RLLM_REWARD"
_MAX_RECORD_BYTES = 8 * 1024 * 1024


class _CandidateSubmitter(AgentAdapter):
    supported_modes: ClassVar[frozenset[InteractionMode]] = frozenset({InteractionMode.AGENT})

    def __init__(self, patch: str, index: int) -> None:
        self.descriptor = AgentDescriptor(
            schema_version=SCHEMA_VERSION,
            name=f"rllm-candidate-submitter-{index:04d}",
            version="1.0.0",
            api_version=PLUGIN_API_VERSION,
            provider="verigym-training-reference",
            capabilities=["deterministic", "offline_rollout_submission"],
        )
        self._patch = patch
        self._index = 0

    def start(self, context: AgentContext) -> None:
        self._index = 0

    def act(self, observation: Observation) -> AgentAction:
        if self._index == 0 and self._patch:
            self._index += 1
            return ApplyPatchAction(patch=self._patch)
        self._index += 1
        return FinalSubmissionAction(message="Submit hash-bound rLLM rollout candidate.")

    def finish(self, result: EpisodeResult) -> None:
        return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply VeriGym rewards to rLLM rollouts.")
    parser.add_argument("--rollouts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--verifier-image", required=True)
    parser.add_argument("--verifier-image-id", required=True)
    parser.add_argument("--seed", type=int, default=484)
    return parser


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _hash(encoded.encode())


def _read_records(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resolved = root.expanduser().resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise SystemExit("rollout input must be a real directory")
    manifest_path = resolved / "rollout-manifest.json"
    rollout_path = resolved / "rollouts.unscored.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lines = rollout_path.read_bytes()
    if not 0 < len(lines) <= _MAX_RECORD_BYTES * 16:
        raise SystemExit("rollout JSONL is empty or oversized")
    if _hash(lines) != manifest.get("rollout_file_sha256"):
        raise SystemExit("rollout JSONL differs from its manifest")
    records = [json.loads(line) for line in lines.decode().splitlines()]
    if len(records) != manifest.get("record_count"):
        raise SystemExit("rollout record count differs from its manifest")
    for record, expected in zip(records, manifest.get("record_hashes", []), strict=True):
        actual = dict(record)
        record_hash = actual.pop("record_hash", None)
        if record_hash != expected or _canonical_hash(actual) != expected:
            raise SystemExit("rollout record identity differs from its manifest")
    return manifest, records


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise SystemExit("reward output must be a new or empty real directory")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _patch(path: str, before: str, after: str) -> str:
    if before == after:
        return ""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _runtime(arguments: argparse.Namespace) -> DockerRuntimeConfig:
    if os.getuid() == 0:
        raise SystemExit("Docker verification requires a non-root host identity")
    return DockerRuntimeConfig(
        image=arguments.verifier_image,
        expected_image_id=arguments.verifier_image_id,
        pull_policy="never",
        network_mode="none",
        run_as_user=f"{os.getuid()}:{os.getgid()}",
        read_only_rootfs=True,
        memory_bytes=512 * 1024 * 1024,
        cpus=1.0,
        pids_limit=128,
        tmpfs_bytes=64 * 1024 * 1024,
        stop_timeout_s=3,
        max_command_time_s=120,
        environment_allowlist=[],
    )


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


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    input_manifest, records = _read_records(arguments.rollouts)
    output = _new_directory(arguments.output)
    source = SuiteSourceConfig(
        source_root=arguments.source.expanduser().resolve(strict=True),
        variant=arguments.variant,
    )
    registries = build_registries()
    service = VeriGym(registries)
    suite, task, assets = service.load_task(arguments.task, source)
    snapshot = suite.source_snapshot()
    if snapshot is None or task.interaction.final_submission.path is None:
        raise SystemExit("reward scoring requires a frozen single-file task")
    candidate_path = task.interaction.final_submission.path
    skeleton = (Path(assets.visible_root) / candidate_path).read_text(encoding="utf-8")
    if input_manifest.get("task_ids") != [task.id]:
        raise SystemExit("rollout task differs from the selected verifier task")
    scored: list[dict[str, Any]] = []
    infrastructure_invalid = 0
    for index, record in enumerate(records):
        candidate = record.get("candidate")
        oversized = isinstance(candidate, str) and len(candidate.encode()) > 4 * 1024 * 1024
        if not isinstance(candidate, str) or not candidate or oversized:
            raise SystemExit("rollout candidate is empty or oversized")
        if _hash(candidate.encode()) != record.get("candidate_sha256"):
            raise SystemExit("rollout candidate differs from its record hash")
        submitter = _CandidateSubmitter(_patch(candidate_path, skeleton, candidate), index)
        registries.agents.register(submitter)
        result = service.run(
            RunConfig(
                task_id=task.id,
                suite_source=source,
                expected_task_hash=content_hash(task),
                expected_source_hash=task.source.content_hash or snapshot.content_hash,
                mode=InteractionMode.AGENT,
                agent=submitter.descriptor.name,
                runtime="docker",
                docker_config=_runtime(arguments),
                seed=arguments.seed + index,
                sample_index=index,
                output=output / "runs",
                run_id=f"rllm-rollout-{index:04d}",
                experiment_id="rllm-verigym-reward-smoke-v1",
                plan_item_id=f"rollout-{index:04d}",
                system_id="qwen35-rllm-policy",
                base_seed=arguments.seed,
            )
        )
        invalid = bool(
            result.scorecard.status == "error"
            or result.scorecard.correctness.infrastructure_error
            or (result.scorecard.failure is not None and result.scorecard.failure.infrastructure)
        )
        infrastructure_invalid += int(invalid)
        reward = None if invalid else float(result.scorecard.resolved)
        episode = record["episode"]
        episode["is_correct"] = bool(result.scorecard.resolved and not invalid)
        episode["termination_reason"] = "infrastructure_invalid" if invalid else "verified"
        episode["metadata"]["verifier_pending"] = False
        trajectory = episode["trajectories"][0]
        trajectory["reward"] = reward
        trajectory["signals"] = {"verigym_sparse_reward": reward or 0.0}
        trajectory["steps"][1]["reward"] = reward or 0.0
        base = {
            **{key: value for key, value in record.items() if key != "record_hash"},
            "format_id": "verigym_rllm_rollout_scored_v1",
            "episode": episode,
            "reward": reward,
            "reward_profile_id": "verigym_resolved_sparse_v1",
            "infrastructure_valid": not invalid,
            "verification": {
                "run_id": result.scorecard.run_id,
                "run_dir": result.run_dir.relative_to(output).as_posix(),
                "resolved": result.scorecard.resolved,
                "candidate_hash": result.scorecard.reproducibility.candidate_hash,
                "task_hash": result.scorecard.reproducibility.task_hash,
                "verifier_hash": result.scorecard.reproducibility.verifier_hash,
            },
        }
        scored.append({**base, "record_hash": _canonical_hash(base)})
    scored_path = output / "rollouts.scored.jsonl"
    _atomic_jsonl(scored_path, scored)
    valid_rewards = [record["reward"] for record in scored if record["infrastructure_valid"]]
    base_manifest = {
        "schema_version": "1.0",
        "format_id": "verigym_rllm_rollout_dataset_scored_v1",
        "record_count": len(scored),
        "record_hashes": [record["record_hash"] for record in scored],
        "input_manifest_hash": input_manifest["manifest_hash"],
        "scored_file_sha256": _hash(scored_path.read_bytes()),
        "group_ids": input_manifest["group_ids"],
        "task_ids": [task.id],
        "task_hash": content_hash(task),
        "source_hash": task.source.content_hash or snapshot.content_hash,
        "reward_profile_id": "verigym_resolved_sparse_v1",
        "rewards": valid_rewards,
        "resolved_count": sum(reward == 1.0 for reward in valid_rewards),
        "unresolved_count": sum(reward == 0.0 for reward in valid_rewards),
        "infrastructure_invalid_count": infrastructure_invalid,
        "hidden_assets_exported_to_trainer": False,
        "reference_solution_exported_to_trainer": False,
    }
    manifest = {**base_manifest, "manifest_hash": _canonical_hash(base_manifest)}
    _atomic_json(output / "reward-manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    manifest = _run(_parser().parse_args(argv))
    return 0 if manifest["infrastructure_invalid_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
