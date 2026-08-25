#!/usr/bin/env python3
"""Consume one authorization and run base/adapter K=1 on the frozen public HWE task."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import time
from pathlib import Path
from typing import Any

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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--adapter-report", type=Path, required=True)
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
    """Validate all bindings before making either of the two authorized model calls."""

    if socket.gethostname().split(".", maxsplit=1)[0] != "gpu03":
        raise ConfigurationError("heldout K=1 is authorized only on gpu03")
    if os.environ.get("LSB_JOBID") != "466876":
        raise ConfigurationError("heldout K=1 requires existing LSF job 466876")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0":
        raise ConfigurationError("heldout K=1 requires physical GPU 0")
    if arguments.output.exists() or arguments.output.is_symlink():
        raise ConfigurationError("heldout K=1 output already exists")
    authorization = _authorization(arguments.authorization)
    repository = arguments.repository_root.resolve(strict=True)
    _validate_sources(repository, authorization)
    qualification = arguments.qualification_root.resolve(strict=True)
    progress = _json(qualification / "qualification-progress.json")
    split = _json(qualification / "task-split.json")
    if (
        progress.get("status") != "completed"
        or split.get("manifest_hash") != authorization["qualification_task_split_hash"]
        or _sha256_file(qualification / "qualification-progress.json")
        != authorization["qualification_progress_sha256"]
    ):
        raise ConfigurationError("heldout qualification binding changed")
    source_root = (qualification / authorization["source_relative_path"]).resolve(strict=True)
    if not source_root.is_relative_to(qualification):
        raise ConfigurationError("heldout source escapes qualification root")
    lock_path = arguments.image_lock.resolve(strict=True)
    lock = HweAgentImageLock.model_validate(_json(lock_path))
    if (
        lock.task_id != authorization["task_id"]
        or lock.task_hash != authorization["task_hash"]
        or lock.source_hash != authorization["source_hash"]
        or lock.lock_hash != authorization["image_lock_hash"]
        or lock.format_id != "verigym_hwe_agent_image_lock_v2"
        or lock.collection_profile_id != HWE_COLLECTION_PROFILE_V2_ID
        or lock.tool_contract_id != HWE_TOOL_CONTRACT_V2_ID
        or _sha256_file(lock_path) != authorization["image_lock_sha256"]
    ):
        raise ConfigurationError("heldout image lock binding changed")
    predecessor = _json(arguments.adapter_report.resolve(strict=True))
    if (
        predecessor.get("report_hash") != authorization["adapter_predecessor_report_hash"]
        or _sha256_file(arguments.adapter_report.resolve(strict=True))
        != authorization["adapter_predecessor_report_sha256"]
        or predecessor.get("model_identity_hash") != authorization["model_identity_hash"]
    ):
        raise ConfigurationError("heldout predecessor report binding changed")
    _inventory, adapter_hash = adapter_artifact_inventory(arguments.adapter_root)
    if adapter_hash != authorization["adapter_artifact_hash"]:
        raise ConfigurationError("heldout retained adapter binding changed")
    model_root = arguments.model_root.resolve(strict=True)
    if arguments.model_root.is_symlink() or not model_root.is_dir():
        raise ConfigurationError("heldout model root is unsafe")
    scratch = arguments.scratch_root
    if not scratch.is_absolute() or scratch.is_symlink():
        raise ConfigurationError("heldout scratch root is unsafe")
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)

    runtime_config = _docker_config(lock)
    runtime = DockerRuntime(runtime_config)
    try:
        runtime.prepare(f"qwen-heldout-preflight-{lock.task_id.rsplit('-', 1)[-1]}")
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
        raise ConfigurationError("heldout task/source identity changed")

    output = arguments.output
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    runs = output / "runs"
    runs.mkdir(mode=0o700)
    _consume(arguments.authorization, authorization["authorization_hash"])
    base_report = _base_report(arguments.campaign_id, authorization, adapter_hash)
    atomic_dump_json(output / "heldout-progress.json", _seal(base_report))
    attempts: list[dict[str, Any]] = []
    started = time.monotonic()
    for policy in ("base", "adapter"):
        run_id = f"{arguments.campaign_id}-{policy}-k1"
        options: dict[str, Any] = {
            "policy": policy,
            "adapter_artifact_hash": adapter_hash,
            "execution_binding_sha256": authorization["authorization_hash"],
            "max_decisions": 200,
            "max_output_tokens": 256,
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
            system_id=f"qwen35-hwe-heldout-{policy}-v1",
            base_seed=484,
        )
        try:
            result = service.run(config)
        except Exception as exc:
            attempts.append(
                {
                    "policy": policy,
                    "run_id": run_id,
                    "status": "infrastructure_invalid",
                    "infrastructure_valid": False,
                    "verifier_resolved": False,
                    "failure": type(exc).__name__,
                }
            )
            _write_failure(output, base_report, attempts, started)
            raise ConfigurationError(f"heldout {policy} K=1 stopped on infrastructure") from exc
        scorecard = result.scorecard
        failure = scorecard.failure
        infrastructure_valid = not (
            scorecard.correctness.infrastructure_error
            or (failure is not None and failure.infrastructure)
            or (scorecard.status == "error" and (failure is None or failure.kind == "runtime"))
        )
        evidence_path = (
            Path(result.run_dir) / "artifacts/deepseek_harness/heldout-native-inference.json"
        )
        evidence = _json(evidence_path) if evidence_path.is_file() else None
        attempt = _attempt(policy, run_id, scorecard, evidence, infrastructure_valid)
        attempts.append(attempt)
        progress_report = {**base_report, "attempts": attempts, "status": "running"}
        atomic_dump_json(output / "heldout-progress.json", _seal(progress_report))
        if not infrastructure_valid:
            _write_failure(output, base_report, attempts, started)
            raise ConfigurationError(f"heldout {policy} K=1 was infrastructure-invalid")

    _after_inventory, after_hash = adapter_artifact_inventory(arguments.adapter_root)
    if after_hash != adapter_hash:
        raise ConfigurationError("heldout replay modified the retained adapter")
    wall = time.monotonic() - started
    gpu_seconds = sum(
        float(item["model_wall_seconds"])
        for item in attempts
        if isinstance(item.get("model_wall_seconds"), (int, float))
    )
    final = {
        **base_report,
        "attempts": attempts,
        "status": "heldout_k1_completed",
        "base_verifier_resolved": attempts[0]["verifier_resolved"],
        "adapter_verifier_resolved": attempts[1]["verifier_resolved"],
        "adapter_artifact_hash_after": after_hash,
        "adapter_unchanged": True,
        "wall_seconds": wall,
        "gpu_seconds": gpu_seconds,
        "peak_memory_allocated_bytes": max(
            int(item.get("peak_memory_allocated_bytes") or 0) for item in attempts
        ),
        "peak_memory_reserved_bytes": max(
            int(item.get("peak_memory_reserved_bytes") or 0) for item in attempts
        ),
    }
    sealed = _seal(final)
    atomic_dump_json(output / "heldout-progress.json", sealed)
    atomic_dump_json(output / "heldout-report.json", sealed)
    return sealed


def _base_report(
    campaign_id: str, authorization: dict[str, Any], adapter_hash: str
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_qwen35_64k_heldout_base_adapter_k1_v1",
        "campaign_id": campaign_id,
        "authorization_hash": authorization["authorization_hash"],
        "task_id": _TASK_ID,
        "task_hash": authorization["task_hash"],
        "source_hash": authorization["source_hash"],
        "image_lock_hash": authorization["image_lock_hash"],
        "model_identity_hash": authorization["model_identity_hash"],
        "adapter_artifact_hash_before": adapter_hash,
        "policies": ["base", "adapter"],
        "samples_per_policy": 1,
        "seed": 484,
        "temperature": 0,
        "do_sample": False,
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
        "attempts": [],
        "status": "running",
    }


def _attempt(
    policy: str,
    run_id: str,
    scorecard: Any,
    evidence: dict[str, Any] | None,
    infrastructure_valid: bool,
) -> dict[str, Any]:
    failure = scorecard.failure
    return {
        "policy": policy,
        "run_id": run_id,
        "run_hash": content_hash(
            {"run_id": run_id, "scorecard": scorecard.model_dump(mode="json")}
        ),
        "status": _attempt_status(scorecard, infrastructure_valid),
        "infrastructure_valid": infrastructure_valid,
        "verifier_resolved": scorecard.resolved,
        "scorecard_status": scorecard.status,
        "termination_reason": scorecard.termination_reason,
        "failure": failure.model_dump(mode="json") if failure is not None else None,
        "candidate_hash": scorecard.reproducibility.candidate_hash,
        "verifier_hash": scorecard.reproducibility.verifier_hash,
        "model_episode_evidence_hash": (
            evidence.get("evidence_hash") if evidence is not None else None
        ),
        "decision_count": (
            evidence.get("decision_count", evidence.get("completed_decisions"))
            if evidence is not None
            else None
        ),
        "tool_call_count": (
            evidence.get("broker", {}).get("tool_calls") if evidence is not None else None
        ),
        "input_tokens": evidence.get("input_tokens") if evidence is not None else None,
        "output_tokens": evidence.get("output_tokens") if evidence is not None else None,
        "peak_memory_allocated_bytes": (
            evidence.get("peak_memory_allocated_bytes") if evidence is not None else None
        ),
        "peak_memory_reserved_bytes": (
            evidence.get("peak_memory_reserved_bytes") if evidence is not None else None
        ),
        "model_wall_seconds": evidence.get("wall_seconds") if evidence is not None else None,
        "heldout_transcript_loaded": False,
    }


def _attempt_status(scorecard: Any, infrastructure_valid: bool) -> str:
    if not infrastructure_valid:
        return "infrastructure_invalid"
    if scorecard.termination_reason == "policy_violation":
        return "policy_rejected"
    return "verifier_pass" if scorecard.resolved else "verifier_rejected"


def _write_failure(
    output: Path,
    base_report: dict[str, Any],
    attempts: list[dict[str, Any]],
    started: float,
) -> None:
    failed = {
        **base_report,
        "attempts": attempts,
        "status": "stopped_infrastructure_invalid",
        "wall_seconds": time.monotonic() - started,
    }
    atomic_dump_json(output / "heldout-progress.json", _seal(failed))
    atomic_dump_json(output / "heldout-report.json", _seal(failed))


def _authorization(path: Path) -> dict[str, Any]:
    value = _json(path.resolve(strict=True))
    expected_hash = value.pop("authorization_hash", None)
    if (
        not isinstance(expected_hash, str)
        or content_hash(value) != expected_hash
        or value.get("format_id") != "verigym_hwe_qwen35_64k_heldout_k1_authorization_v1"
        or value.get("status") != "authorized_for_single_base_adapter_heldout_k1"
        or value.get("task_id") != _TASK_ID
        or value.get("policies") != ["base", "adapter"]
        or value.get("samples_per_policy") != 1
        or value.get("training_allowed") is not False
        or value.get("optimizer_steps_allowed") != 0
        or value.get("new_hpc_jobs_allowed") is not False
    ):
        raise ConfigurationError("heldout execution authorization is invalid")
    return {**value, "authorization_hash": expected_hash}


def _validate_sources(repository: Path, authorization: dict[str, Any]) -> None:
    sources = authorization.get("execution_source_artifacts")
    if not isinstance(sources, list) or content_hash(sources) != authorization.get(
        "execution_source_manifest_hash"
    ):
        raise ConfigurationError("heldout execution source manifest changed")
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ConfigurationError("heldout execution source receipt is malformed")
        path = repository / item["path"]
        if (
            path.is_symlink()
            or not path.resolve(strict=True).is_file()
            or not path.resolve(strict=True).is_relative_to(repository)
            or path.stat().st_size != item.get("size_bytes")
            or _sha256_file(path) != item.get("sha256")
        ):
            raise ConfigurationError(f"heldout execution source changed: {item['path']}")


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


def _consume(path: Path, authorization_hash: str) -> None:
    marker = path.with_name("heldout-execution-started.json")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_qwen35_heldout_execution_start_v1",
        "status": "execution_started",
        "authorization_hash": authorization_hash,
        "single_use_authorization_consumed": True,
    }
    payload = (
        json.dumps({**base, "marker_hash": content_hash(base)}, indent=2, sort_keys=True).encode()
        + b"\n"
    )
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    base = {key: item for key, item in value.items() if key != "report_hash"}
    return {**base, "report_hash": content_hash(base)}


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError(f"unsafe heldout JSON input: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError(f"heldout JSON input is not an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    arguments = _parser().parse_args()
    report = run(arguments)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
