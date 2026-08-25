#!/usr/bin/env python3
"""Run one adapter-only recovery after a bound infrastructure-invalid heldout attempt."""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path
from typing import Any

import run_hwe_deepseek_heldout_k1_v1 as original
from verigym_training_reference.hwe_decision_sft_64k_heldout import (
    Qwen35HweHeldoutAgentAdapter,
    adapter_artifact_inventory,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID
from verigym.hwe.image_lock import HweAgentImageLock
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID, HWE_TOOL_CONTRACT_V2_ID
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig, DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_TASK_ID = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"
_GPU_COUNT = 4
_MAX_MEMORY_PER_GPU_BYTES = 20 * 1024**3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--adapter-report", type=Path, required=True)
    parser.add_argument("--prior-heldout-report", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    return parser


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    """Validate the failed predecessor and consume one adapter-only recovery."""

    if socket.gethostname().split(".", maxsplit=1)[0] != "gpu03":
        raise ConfigurationError("heldout adapter recovery is authorized only on gpu03")
    if os.environ.get("LSB_JOBID") != "466876":
        raise ConfigurationError("heldout adapter recovery requires existing LSF job 466876")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0,1,2,3":
        raise ConfigurationError("heldout adapter recovery requires physical GPUs 0-3")
    if arguments.output.exists() or arguments.output.is_symlink():
        raise ConfigurationError("heldout adapter recovery output already exists")
    authorization = _authorization(arguments.authorization)
    repository = arguments.repository_root.resolve(strict=True)
    original._validate_sources(repository, authorization)
    qualification = arguments.qualification_root.resolve(strict=True)
    progress = original._json(qualification / "qualification-progress.json")
    split = original._json(qualification / "task-split.json")
    if (
        progress.get("status") != "completed"
        or split.get("manifest_hash") != authorization["qualification_task_split_hash"]
        or original._sha256_file(qualification / "qualification-progress.json")
        != authorization["qualification_progress_sha256"]
    ):
        raise ConfigurationError("heldout recovery qualification binding changed")
    source_root = (qualification / authorization["source_relative_path"]).resolve(strict=True)
    if not source_root.is_relative_to(qualification):
        raise ConfigurationError("heldout recovery source escapes qualification root")
    lock_path = arguments.image_lock.resolve(strict=True)
    lock = HweAgentImageLock.model_validate(original._json(lock_path))
    if (
        lock.task_id != authorization["task_id"]
        or lock.task_hash != authorization["task_hash"]
        or lock.source_hash != authorization["source_hash"]
        or lock.lock_hash != authorization["image_lock_hash"]
        or lock.format_id != "verigym_hwe_agent_image_lock_v2"
        or lock.collection_profile_id != HWE_COLLECTION_PROFILE_V2_ID
        or lock.tool_contract_id != HWE_TOOL_CONTRACT_V2_ID
        or original._sha256_file(lock_path) != authorization["image_lock_sha256"]
    ):
        raise ConfigurationError("heldout recovery image lock binding changed")
    adapter_report_path = arguments.adapter_report.resolve(strict=True)
    adapter_report = original._json(adapter_report_path)
    if (
        adapter_report.get("report_hash") != authorization["adapter_predecessor_report_hash"]
        or original._sha256_file(adapter_report_path)
        != authorization["adapter_predecessor_report_sha256"]
        or adapter_report.get("model_identity_hash") != authorization["model_identity_hash"]
    ):
        raise ConfigurationError("heldout recovery adapter report binding changed")
    prior = _prior_report(arguments.prior_heldout_report, authorization)
    _inventory, adapter_hash = adapter_artifact_inventory(arguments.adapter_root)
    if adapter_hash != authorization["adapter_artifact_hash"]:
        raise ConfigurationError("heldout recovery retained adapter binding changed")
    model_root = arguments.model_root.resolve(strict=True)
    if arguments.model_root.is_symlink() or not model_root.is_dir():
        raise ConfigurationError("heldout recovery model root is unsafe")
    scratch = arguments.scratch_root
    if not scratch.is_absolute() or scratch.is_symlink():
        raise ConfigurationError("heldout recovery scratch root is unsafe")
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)

    runtime_config = _docker_config(lock)
    runtime = DockerRuntime(runtime_config)
    try:
        runtime.prepare(f"qwen-heldout-recovery-{lock.task_id.rsplit('-', 1)[-1]}")
    finally:
        runtime.close()

    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    agent_name = Qwen35HweHeldoutAgentAdapter.descriptor.name
    if agent_name not in registries.agents.names():
        registries.agents.register(
            Qwen35HweHeldoutAgentAdapter(
                model_root=model_root,
                adapter_root=arguments.adapter_root.resolve(strict=True),
                control_root=scratch / "broker-control",
                authorization_hash=authorization["authorization_hash"],
                adapter_artifact_hash=adapter_hash,
            )
        )
    service = VeriGym(registries)
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(_TASK_ID, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != authorization["task_hash"]
        or task.source.content_hash != authorization["source_hash"]
    ):
        raise ConfigurationError("heldout recovery task/source identity changed")

    output = arguments.output
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    runs = output / "runs"
    runs.mkdir(mode=0o700)
    original._consume(arguments.authorization, authorization["authorization_hash"])
    base_report = _base_report(arguments.campaign_id, authorization, adapter_hash, prior)
    atomic_dump_json(output / "heldout-progress.json", original._seal(base_report))
    started = time.monotonic()
    run_id = f"{arguments.campaign_id}-adapter-infrastructure-recovery-k1"
    options: dict[str, Any] = {
        "policy": "adapter",
        "adapter_artifact_hash": adapter_hash,
        "execution_binding_sha256": authorization["authorization_hash"],
        "max_decisions": 200,
        "max_output_tokens": 256,
        "inference_gpu_count": _GPU_COUNT,
        "max_memory_per_gpu_bytes": _MAX_MEMORY_PER_GPU_BYTES,
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "agent_image_lock_hash": lock.lock_hash,
        "whole_episode_retries": 0,
    }
    config = RunConfig(
        task_id=_TASK_ID,
        suite_source=source,
        expected_suite_source_snapshot=snapshot,
        expected_task_hash=authorization["task_hash"],
        expected_source_hash=authorization["source_hash"],
        mode=InteractionMode.AGENT,
        agent=agent_name,
        agent_options=options,
        runtime="docker",
        docker_config=runtime_config,
        seed=484,
        sample_index=0,
        output=runs,
        run_id=run_id,
        experiment_id=arguments.campaign_id,
        plan_item_id=run_id,
        system_id="qwen35-hwe-heldout-adapter-infrastructure-recovery-v1",
        base_seed=484,
    )
    try:
        result = service.run(config)
    except Exception as exc:
        attempt = {
            "policy": "adapter",
            "run_id": run_id,
            "status": "infrastructure_invalid",
            "infrastructure_valid": False,
            "verifier_resolved": False,
            "failure": type(exc).__name__,
        }
        _write_failure(output, base_report, attempt, started, arguments.adapter_root, adapter_hash)
        raise ConfigurationError("heldout adapter recovery stopped on infrastructure") from exc
    scorecard = result.scorecard
    failure = scorecard.failure
    infrastructure_valid = not (
        scorecard.correctness.infrastructure_error
        or (failure is not None and failure.infrastructure)
        or (scorecard.status == "error" and (failure is None or failure.kind == "runtime"))
    )
    evidence_path = Path(result.run_dir) / (
        "artifacts/deepseek_harness/heldout-native-inference.json"
    )
    evidence = original._json(evidence_path) if evidence_path.is_file() else None
    attempt = original._attempt("adapter", run_id, scorecard, evidence, infrastructure_valid)
    _after_inventory, after_hash = adapter_artifact_inventory(arguments.adapter_root)
    if after_hash != adapter_hash:
        raise ConfigurationError("heldout adapter recovery modified the retained adapter")
    if not infrastructure_valid:
        _write_failure(output, base_report, attempt, started, arguments.adapter_root, adapter_hash)
        raise ConfigurationError("heldout adapter recovery remained infrastructure-invalid")
    wall = time.monotonic() - started
    model_wall = attempt.get("model_wall_seconds")
    peak_allocated = attempt.get("peak_memory_allocated_bytes")
    peak_reserved = attempt.get("peak_memory_reserved_bytes")
    final = {
        **base_report,
        "attempt": attempt,
        "status": "heldout_adapter_infrastructure_recovery_completed",
        "base_verifier_resolved": prior["attempts"][0]["verifier_resolved"],
        "adapter_verifier_resolved": attempt["verifier_resolved"],
        "adapter_artifact_hash_after": after_hash,
        "adapter_unchanged": True,
        "wall_seconds": wall,
        "gpu_seconds": (
            float(model_wall) * _GPU_COUNT if isinstance(model_wall, (int, float)) else 0.0
        ),
        "peak_memory_allocated_bytes": (
            int(peak_allocated) if isinstance(peak_allocated, (int, float)) else 0
        ),
        "peak_memory_reserved_bytes": (
            int(peak_reserved) if isinstance(peak_reserved, (int, float)) else 0
        ),
    }
    sealed = original._seal(final)
    atomic_dump_json(output / "heldout-progress.json", sealed)
    atomic_dump_json(output / "heldout-report.json", sealed)
    return sealed


def _authorization(path: Path) -> dict[str, Any]:
    value = original._json(path.resolve(strict=True))
    expected_hash = value.pop("authorization_hash", None)
    if (
        not isinstance(expected_hash, str)
        or content_hash(value) != expected_hash
        or value.get("format_id")
        != "verigym_hwe_qwen35_64k_heldout_adapter_recovery_authorization_v1"
        or value.get("status") != "authorized_for_single_adapter_infrastructure_recovery_k1"
        or value.get("task_id") != _TASK_ID
        or value.get("policies") != ["adapter"]
        or value.get("samples_per_policy") != 1
        or value.get("selected_gpu_indices") != [0, 1, 2, 3]
        or value.get("inference_gpu_count") != _GPU_COUNT
        or value.get("max_memory_per_gpu_bytes") != _MAX_MEMORY_PER_GPU_BYTES
        or value.get("base_sample_repeated") is not False
        or value.get("training_allowed") is not False
        or value.get("optimizer_steps_allowed") != 0
        or value.get("new_hpc_jobs_allowed") is not False
    ):
        raise ConfigurationError("heldout adapter recovery authorization is invalid")
    return {**value, "authorization_hash": expected_hash}


def _prior_report(path: Path, authorization: dict[str, Any]) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    value = original._json(resolved)
    unsealed = {key: item for key, item in value.items() if key != "report_hash"}
    attempts = value.get("attempts")
    if (
        content_hash(unsealed) != value.get("report_hash")
        or value.get("report_hash") != authorization["prior_heldout_report_hash"]
        or original._sha256_file(resolved) != authorization["prior_heldout_report_sha256"]
        or value.get("status") != "stopped_infrastructure_invalid"
        or not isinstance(attempts, list)
        or len(attempts) != 2
        or attempts[0].get("policy") != "base"
        or attempts[0].get("infrastructure_valid") is not True
        or attempts[1].get("policy") != "adapter"
        or attempts[1].get("infrastructure_valid") is not False
        or attempts[0].get("run_hash") != authorization["prior_base_attempt_run_hash"]
        or attempts[1].get("run_hash") != authorization["prior_invalid_attempt_run_hash"]
    ):
        raise ConfigurationError("heldout adapter recovery predecessor changed")
    return value


def _docker_config(lock: HweAgentImageLock) -> DockerRuntimeConfig:
    runtime_user = f"{os.getuid()}:{os.getgid()}"
    return DockerRuntimeConfig(
        image=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        expected_image_id=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        pull_policy="never",
        network_mode="none",
        run_as_user=runtime_user,
        memory_bytes=16 * 1024**3,
        cpus=4,
        pids_limit=4096,
        max_command_time_s=900,
        external_agent=DockerExternalAgentRuntimeConfig(
            image=lock.derived_agent_image_id,
            expected_image_id=lock.derived_agent_image_id,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.147.0",
            expected_executable_sha256=lock.agent_codex_sha256,
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="deepseek_harness_hwe_command_image_v1",
            required_image_labels={
                "org.verigym.collection.profile": HWE_COLLECTION_PROFILE_V2_ID,
                "org.verigym.tool.contract": HWE_TOOL_CONTRACT_V2_ID,
                "org.verigym.codex.version": "0.147.0",
                "org.verigym.codex.binary.sha256": lock.agent_codex_sha256,
                "org.verigym.codex.rg.sha256": lock.agent_rg_sha256,
                "org.verigym.hwe.task_id": lock.task_id,
                "org.verigym.cva6.verifier_base_image_id": lock.verifier_base_image_id,
                "org.verigym.provider_credentials": "absent",
                "org.verigym.hidden_assets": "absent",
                "org.verigym.reference_patch": "absent",
                "org.verigym.verifier_payload": "absent",
            },
            run_as_user=runtime_user,
            memory_bytes=16 * 1024**3,
            cpus=4,
            pids_limit=4096,
            max_process_time_s=3600,
            max_output_bytes=32 * 1024 * 1024,
            logical_workspace_root="/workspace/repository",
        ),
    )


def _base_report(
    campaign_id: str,
    authorization: dict[str, Any],
    adapter_hash: str,
    prior: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_qwen35_64k_heldout_adapter_recovery_v1",
        "campaign_id": campaign_id,
        "authorization_hash": authorization["authorization_hash"],
        "task_id": _TASK_ID,
        "task_hash": authorization["task_hash"],
        "source_hash": authorization["source_hash"],
        "image_lock_hash": authorization["image_lock_hash"],
        "model_identity_hash": authorization["model_identity_hash"],
        "adapter_artifact_hash_before": adapter_hash,
        "prior_heldout_report_hash": prior["report_hash"],
        "prior_base_attempt_run_hash": prior["attempts"][0]["run_hash"],
        "prior_invalid_attempt_run_hash": prior["attempts"][1]["run_hash"],
        "prior_invalid_attempt_excluded_from_quality": True,
        "base_sample_reused": True,
        "base_sample_repeated": False,
        "policies": ["adapter"],
        "samples_per_policy": 1,
        "seed": 484,
        "temperature": 0,
        "do_sample": False,
        "selected_gpu_indices": [0, 1, 2, 3],
        "inference_gpu_count": _GPU_COUNT,
        "max_memory_per_gpu_bytes": _MAX_MEMORY_PER_GPU_BYTES,
        "heldout_transcript_loaded": False,
        "training_dataset_loaded": False,
        "reference_solution_available_to_inference": False,
        "ordinary_verifier_required": True,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "new_hpc_jobs_submitted": False,
        "existing_lsf_job_id": "466876",
        "allocation_released": False,
        "benchmark_score_claimed": False,
        "quality_improvement_claimed": False,
        "production_training_ready": False,
        "attempt": None,
        "status": "running",
    }


def _write_failure(
    output: Path,
    base_report: dict[str, Any],
    attempt: dict[str, Any],
    started: float,
    adapter_root: Path,
    expected_adapter_hash: str,
) -> None:
    _inventory, observed = adapter_artifact_inventory(adapter_root)
    failed = {
        **base_report,
        "attempt": attempt,
        "status": "stopped_infrastructure_invalid",
        "adapter_artifact_hash_after": observed,
        "adapter_unchanged": observed == expected_adapter_hash,
        "wall_seconds": time.monotonic() - started,
    }
    sealed = original._seal(failed)
    atomic_dump_json(output / "heldout-progress.json", sealed)
    atomic_dump_json(output / "heldout-report.json", sealed)


def main() -> None:
    report = run(_parser().parse_args())
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
