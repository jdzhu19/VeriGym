"""Host-side VeriGym verification for isolated online-training rollouts."""

from __future__ import annotations

import difflib
import hashlib
import os
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


class _CandidateSubmitter(AgentAdapter):
    supported_modes: ClassVar[frozenset[InteractionMode]] = frozenset({InteractionMode.AGENT})

    def __init__(self, patch: str, name: str) -> None:
        self.descriptor = AgentDescriptor(
            schema_version=SCHEMA_VERSION,
            name=name,
            version="1.0.0",
            api_version=PLUGIN_API_VERSION,
            provider="verigym-training-reference",
            capabilities=["deterministic", "online_training_submission"],
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
        return FinalSubmissionAction(message="Submit the public-only online rollout candidate.")

    def finish(self, result: EpisodeResult) -> None:
        return None


def _patch(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def online_docker_runtime_config(image: str, image_id: str) -> DockerRuntimeConfig:
    """Build the shared network-none runtime used by online host-side episodes."""

    if os.getuid() == 0:
        raise RuntimeError("online Docker verification requires a non-root host identity")
    return DockerRuntimeConfig(
        image=image,
        expected_image_id=image_id,
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


def score_online_candidate(
    *,
    binding: dict[str, Any],
    request: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """Score one broker request without exposing verifier-owned material in the response."""

    public = binding.get("public_record")
    if not isinstance(public, dict):
        raise RuntimeError("online task binding omits its public record")
    task_id = request.get("task_id")
    candidate = request.get("candidate")
    candidate_hash = request.get("candidate_hash")
    if (
        task_id != binding.get("task_id")
        or task_id != public.get("task_id")
        or request.get("public_input_hash") != public.get("record_hash")
        or not isinstance(candidate, str)
        or not isinstance(candidate_hash, str)
        or hashlib.sha256(candidate.encode()).hexdigest() != candidate_hash
    ):
        raise RuntimeError("online verifier request does not match its bound public task")

    registries = build_registries()
    service = VeriGym(registries)
    source = SuiteSourceConfig(
        source_root=Path(str(binding["source_root"])).resolve(strict=True),
        variant=str(binding["variant"]),
    )
    suite, normalized, assets = service.load_task(str(task_id), source)
    snapshot = suite.source_snapshot()
    candidate_path = normalized.interaction.final_submission.path
    if (
        snapshot is None
        or candidate_path is None
        or candidate_path != public.get("candidate_path")
        or content_hash(normalized) != public.get("task_hash")
        or normalized.source.content_hash != public.get("source_hash")
    ):
        raise RuntimeError("evaluator task identity differs from the frozen public record")
    skeleton = (Path(assets.visible_root) / candidate_path).read_text(encoding="utf-8")
    request_id = str(request["request_id"])
    submitter = _CandidateSubmitter(
        _patch(candidate_path, skeleton, candidate),
        f"rllm-online-{request_id[:20]}",
    )
    registries.agents.register(submitter)
    result = service.run(
        RunConfig(
            task_id=normalized.id,
            suite_source=source,
            expected_task_hash=content_hash(normalized),
            expected_source_hash=normalized.source.content_hash or snapshot.content_hash,
            mode=InteractionMode.AGENT,
            agent=submitter.descriptor.name,
            runtime="docker",
            docker_config=online_docker_runtime_config(
                str(binding["verifier_image"]), str(binding["verifier_image_id"])
            ),
            seed=int(request.get("seed", 20260809)),
            sample_index=int(request.get("sample_index", 0)),
            output=output,
            run_id=f"online-{request_id[:20]}",
            experiment_id="qwen35-rllm-verl-online-smoke-v1",
            plan_item_id=f"online-{request_id[:20]}",
            system_id="qwen35-rllm-verl-online-policy",
            base_seed=int(request.get("seed", 20260809)),
        )
    )
    invalid = bool(
        result.scorecard.status == "error"
        or result.scorecard.correctness.infrastructure_error
        or (result.scorecard.failure is not None and result.scorecard.failure.infrastructure)
    )
    return {
        "infrastructure_valid": not invalid,
        "resolved": None if invalid else result.scorecard.resolved,
        "compile_status": result.scorecard.correctness.compile_status,
        "task_hash": result.scorecard.reproducibility.task_hash,
        "verifier_hash": result.scorecard.reproducibility.verifier_hash,
        "candidate_hash": result.scorecard.reproducibility.candidate_hash,
    }


__all__ = ["online_docker_runtime_config", "score_online_candidate"]
