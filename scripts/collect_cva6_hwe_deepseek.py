#!/usr/bin/env python3
"""Run the frozen three-task DeepSeek Harness HWE API pilot exactly once."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.evolution.splits import validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID
from verigym.hwe.deepseek_harness import (
    DEEPSEEK_HARNESS_MODEL,
    DEEPSEEK_HARNESS_PILOT_TASKS,
    build_deepseek_harness_dataset_manifest,
    materialize_deepseek_harness_action_examples,
    validate_deepseek_harness_transcript,
)
from verigym.hwe.image_lock import HweAgentImageLock
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID, HWE_TOOL_CONTRACT_V2_ID
from verigym.hwe.qwen_action_tokenizer import (
    QwenActionExampleTokenizer,
    dry_run_action_record,
)
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig, DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_OPT_IN = "VERIGYM_RUN_DEEPSEEK_HWE_PILOT"
_API_KEY_ENV = "VERIGYM_DEEPSEEK_API_KEY"
_BASE_URL_ENV = "VERIGYM_DEEPSEEK_API_BASE_URL"
_TRANSFORMERS_VERSION = "4.57.6"
_BASE_MODEL_ID = "Qwen3.5-9B"
_CAMPAIGN_FORMAT = "verigym_hwe_deepseek_harness_three_task_pilot_v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--supersedes-zero-call-preflight", type=Path)
    return parser


def collect(
    *,
    qualification_root: Path,
    image_lock_dir: Path,
    tokenizer_root: Path,
    base_model_lock: Path,
    output: Path,
    campaign_id: str,
    supersedes_zero_call_preflight: Path | None = None,
) -> dict[str, Any]:
    """Collect K=1 for the frozen tasks; never retry, expand, train, or submit HPC work."""

    if os.environ.get(_OPT_IN) != "1":
        raise ConfigurationError(f"{_OPT_IN}=1 is required")
    if not os.environ.get(_API_KEY_ENV) or not os.environ.get(_BASE_URL_ENV):
        raise ConfigurationError("DeepSeek provider environment is incomplete")
    qualification = qualification_root.resolve(strict=True)
    tokenizer_directory = tokenizer_root.resolve(strict=True)
    split = validate_task_split(
        TaskSplitManifest.model_validate(_json(qualification / "task-split.json"))
    )
    progress = _json(qualification / "qualification-progress.json")
    if progress.get("status") != "completed":
        raise ConfigurationError("CVA6 qualification is incomplete")
    source_by_task = _qualified_sources(progress)
    training = {entry.task_id: entry for entry in split.training}
    if any(
        task_id not in source_by_task or task_id not in training
        for task_id in DEEPSEEK_HARNESS_PILOT_TASKS
    ):
        raise ConfigurationError("qualification or split omits a frozen DeepSeek pilot task")
    locks = _image_locks(image_lock_dir, set(DEEPSEEK_HARNESS_PILOT_TASKS))
    model_lock = _base_model_lock(base_model_lock, tokenizer_directory)
    tokenizer, transformers_version = _load_tokenizer(tokenizer_directory)
    exact_tokenizer = QwenActionExampleTokenizer(tokenizer, tokenizer_root=tokenizer_directory)
    if exact_tokenizer.tokenizer_hash != model_lock["tokenizer_hash"]:
        raise ConfigurationError("Qwen tokenizer differs from the frozen base-model lock")
    superseded_preflight_hash = (
        _zero_model_call_preflight_receipt(supersedes_zero_call_preflight)
        if supersedes_zero_call_preflight is not None
        else None
    )
    _runtime_image_preflight(locks)

    root = _new_output(output)
    runs = root / "runs"
    records_root = root / "trajectory-records"
    dataset_root = root / "dataset"
    runs.mkdir(mode=0o700)
    records_root.mkdir(mode=0o700)
    dataset_root.mkdir(mode=0o700)
    base_report = {
        "schema_version": "1.0",
        "format_id": _CAMPAIGN_FORMAT,
        "campaign_id": campaign_id,
        "task_split_hash": split.manifest_hash,
        "pilot_task_ids": list(DEEPSEEK_HARNESS_PILOT_TASKS),
        "samples_per_task": 1,
        "best_of_k": False,
        "whole_episode_retries": 0,
        "supersedes_zero_model_call_preflight_report_hash": superseded_preflight_hash,
        "provider_request_retries": 0,
        "model_substitution": False,
        "provider": "deepseek-official",
        "model": DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "max_parallel_tool_calls": 1,
        "seed": 484,
        "harness_revision": "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e",
        "harness_version": "0.1.1-rc.2",
        "base_model_id": _BASE_MODEL_ID,
        "base_model_snapshot_hash": model_lock["snapshot_hash"],
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "chat_template_hash": exact_tokenizer.chat_template_hash,
        "transformers_version": transformers_version,
        "pilot_is_benchmark_score": False,
        "production_training_ready": False,
        "training_started": False,
        "heldout_evaluation_started": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
        "attempts": [],
        "status": "preflight",
    }
    atomic_dump_json(root / "campaign-progress.json", _seal_report(base_report))

    _zero_call_conformance()
    report = {**base_report, "status": "pilot_running", "zero_call_conformance": "passed"}
    atomic_dump_json(root / "campaign-progress.json", _seal_report(report))

    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "deepseek-harness-hwe-agent" not in registries.agents.names():
        from verigym_deepseek_harness import DeepSeekHarnessHweAgentAdapter

        registries.agents.register(DeepSeekHarnessHweAgentAdapter())
    service = VeriGym(registries)
    all_examples: list[dict[str, Any]] = []
    dry_runs: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []

    for task_id in DEEPSEEK_HARNESS_PILOT_TASKS:
        entry = training[task_id]
        lock = locks[task_id]
        source_root = (qualification / source_by_task[task_id]).resolve(strict=True)
        if not source_root.is_relative_to(qualification):
            raise ConfigurationError("CVA6 DeepSeek source escapes qualification root")
        source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
        suite, task, _assets = service.load_task(task_id, source)
        snapshot = suite.source_snapshot()
        if (
            snapshot is None
            or content_hash(task) != entry.task_hash
            or task.source.content_hash != entry.source_hash
            or lock.task_hash != entry.task_hash
            or lock.source_hash != entry.source_hash
        ):
            raise ConfigurationError("DeepSeek pilot task/source/image identity changed")
        suffix = task_id.rsplit("-", 1)[-1]
        run_id = f"{campaign_id}-{suffix}"
        config = RunConfig(
            task_id=task_id,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=entry.task_hash,
            expected_source_hash=entry.source_hash,
            mode=InteractionMode.AGENT,
            agent="deepseek-harness-hwe-agent",
            agent_options={
                "model_id": DEEPSEEK_HARNESS_MODEL,
                "max_process_time_s": 3600,
                "max_output_bytes": 32 * 1024 * 1024,
                "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                "agent_image_lock_hash": lock.lock_hash,
                "whole_episode_retries": 0,
            },
            runtime="docker",
            docker_config=_docker_config(lock),
            seed=484,
            sample_index=0,
            output=runs,
            run_id=run_id,
            experiment_id=campaign_id,
            plan_item_id=run_id,
            system_id="deepseek-harness-hwe-native-shell-v2",
            base_seed=484,
        )
        try:
            result = service.run(config)
        except Exception as exc:
            reason = str(getattr(exc, "subreason", type(exc).__name__))
            attempt = _infrastructure_attempt(task_id, run_id, reason)
            attempts.append(attempt)
            report = {**report, "attempts": attempts, "status": "stopped_infrastructure_invalid"}
            atomic_dump_json(root / "campaign-progress.json", _seal_report(report))
            atomic_dump_json(root / "campaign-report.json", _seal_report(report))
            raise ConfigurationError(
                f"DeepSeek HWE pilot stopped on infrastructure-invalid {task_id}"
            ) from exc

        scorecard = result.scorecard
        failure = scorecard.failure
        run_hash = content_hash({"run_id": run_id, "scorecard": scorecard.model_dump(mode="json")})
        if _infrastructure_invalid(scorecard):
            reason = (
                failure.protocol_error_subcategory or failure.category
                if failure is not None
                else "scorecard_infrastructure_invalid"
            )
            attempt = _infrastructure_attempt(task_id, run_id, reason, run_hash=run_hash)
            attempts.append(attempt)
            report = {**report, "attempts": attempts, "status": "stopped_infrastructure_invalid"}
            atomic_dump_json(root / "campaign-progress.json", _seal_report(report))
            atomic_dump_json(root / "campaign-report.json", _seal_report(report))
            raise ConfigurationError(
                f"DeepSeek HWE pilot stopped on infrastructure-invalid {task_id}"
            )

        transcript_path = (
            Path(result.run_dir)
            / "artifacts/deepseek_harness/deepseek_harness_teacher_transcript.json"
        )
        transcript: dict[str, Any] | None = None
        task_examples: list[dict[str, Any]] = []
        task_dry_runs: list[dict[str, Any]] = []
        status = "verifier_rejected"
        rejection_reason: str | None = "ordinary_verifier_rejected"
        if not transcript_path.is_symlink() and transcript_path.is_file():
            transcript = validate_deepseek_harness_transcript(_json(transcript_path))
        if scorecard.resolved:
            if transcript is None:
                status = "normalization_failed"
                rejection_reason = "resolved_run_lacks_deepseek_harness_transcript"
            else:
                reproducibility = scorecard.reproducibility
                binding = {
                    "sample_id": content_hash(
                        {"campaign_id": campaign_id, "task_id": task_id, "run_hash": run_hash}
                    ),
                    "task_hash": entry.task_hash,
                    "source_hash": entry.source_hash,
                    "candidate_hash": reproducibility.candidate_hash,
                    "verifier_hash": reproducibility.verifier_hash,
                }
                task_examples = materialize_deepseek_harness_action_examples(
                    transcript,
                    binding=binding,
                    tokenizer=exact_tokenizer,
                )
                task_dry_runs = [
                    dry_run_action_record(item, tokenizer=exact_tokenizer) for item in task_examples
                ]
                overlength = [item for item in task_examples if item["eligible"] is not True]
                status = "eligible" if not overlength else "overlength"
                rejection_reason = None if not overlength else "one_or_more_rows_exceed_32768"
                _write_trajectory_records(
                    records_root / f"{suffix}.jsonl",
                    task_examples,
                    task_id=task_id,
                    transcript_hash=str(transcript["transcript_hash"]),
                    run_hash=run_hash,
                )
                all_examples.extend(task_examples)
                dry_runs.extend(task_dry_runs)
        elif failure is not None and failure.kind in {"model", "policy"}:
            status = "policy_rejected"
            rejection_reason = failure.protocol_error_subcategory or failure.category

        attempt = {
            "task_id": task_id,
            "run_id": run_id,
            "run_hash": run_hash,
            "status": status,
            "infrastructure_valid": True,
            "verifier_pass": scorecard.resolved,
            "normalized": transcript is not None,
            "transcript_hash": transcript.get("transcript_hash") if transcript else None,
            "action_record_count": len(task_examples),
            "max_action_record_tokens": (
                max(int(item["token_count"]) for item in task_examples) if task_examples else None
            ),
            "overlength_record_count": sum(item["eligible"] is not True for item in task_examples),
            "model_call_count": scorecard.efficiency.external_model_call_count,
            "input_tokens": scorecard.efficiency.external_input_tokens,
            "output_tokens": scorecard.efficiency.external_output_tokens,
            "total_tokens": scorecard.efficiency.external_total_tokens,
            "rejection_reason": rejection_reason,
            "whole_episode_retries": 0,
        }
        attempts.append(attempt)
        report = {**report, "attempts": attempts}
        atomic_dump_json(root / "campaign-progress.json", _seal_report(report))

    _atomic_jsonl(dataset_root / "train.jsonl", all_examples)
    manifest = build_deepseek_harness_dataset_manifest(
        all_examples,
        pilot_task_ids=DEEPSEEK_HARNESS_PILOT_TASKS,
    )
    atomic_dump_json(dataset_root / "dataset-manifest.json", manifest)
    dry_run_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_deepseek_harness_qwen_loader_dry_run_v1",
        "record_count": len(dry_runs),
        "record_hashes": [item["record_hash"] for item in dry_runs],
        "max_token_count": max((int(item["token_count"]) for item in dry_runs), default=0),
        "overlength_record_count": sum(bool(item["overlength"]) for item in dry_runs),
        "final_assistant_action_only": True,
        "truncation_applied": False,
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "chat_template_hash": exact_tokenizer.chat_template_hash,
        "records": dry_runs,
    }
    atomic_dump_json(
        dataset_root / "loader-dry-run.json",
        {**dry_run_base, "dry_run_hash": content_hash(dry_run_base)},
    )
    _assert_provider_secret_absent(dataset_root)
    security = require_security_scan_pass(
        scan_artifact_roots(
            [dataset_root],
            report_id="deepseek-harness-hwe-pilot-public-dataset",
            forbidden_host_roots=(
                str(qualification),
                str(tokenizer_directory),
                str(Path.cwd().resolve()),
            ),
        )
    )
    atomic_dump_json(root / "dataset-security-scan.json", security)
    final = {
        **report,
        "attempts": attempts,
        "status": "pilot_completed",
        "attempt_count": len(attempts),
        "verifier_pass_count": sum(bool(item["verifier_pass"]) for item in attempts),
        "eligible_trajectory_count": sum(item["status"] == "eligible" for item in attempts),
        "overlength_trajectory_count": sum(item["status"] == "overlength" for item in attempts),
        "action_record_count": len(all_examples),
        "max_action_record_tokens": max(
            (int(item["token_count"]) for item in all_examples), default=0
        ),
        "overlength_record_count": len(manifest["overlength_records"]),
        "dataset_hash": manifest["dataset_hash"],
        "loader_ready": manifest["loader_ready"],
        "dataset_security_scan": security.gate,
        "production_training_ready": False,
        "training_started": False,
        "heldout_evaluation_started": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
    }
    sealed = _seal_report(final)
    atomic_dump_json(root / "campaign-progress.json", sealed)
    atomic_dump_json(root / "campaign-report.json", sealed)
    return sealed


def _zero_call_conformance() -> None:
    from verigym_deepseek_harness.config import resolve_settings
    from verigym_deepseek_harness.process import run_harness_helper

    settings = resolve_settings(
        {
            "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
            "model_id": DEEPSEEK_HARNESS_MODEL,
            "max_process_time_s": 120,
        },
        task_wall_time_s=120,
    )
    scratch = Path("/data/jzhu484/Agent/.verigym-tmp")
    scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dsh-preflight-", dir=scratch) as raw:
        root = Path(raw)
        session = root / "session"
        broker = root / "broker"
        session.mkdir(mode=0o700)
        broker.mkdir(mode=0o700)
        result = run_harness_helper(
            settings,
            mode="initialize",
            prompt="zero-call conformance",
            system_prompt="DeepSeek Harness zero-call conformance; no model request.",
            session_id="zero-call-conformance",
            session_root=session,
            broker_root=broker,
        )
    if result.events or result.finish_reason is not None or result.final_response:
        raise ConfigurationError("DeepSeek Harness zero-call conformance made an unexpected turn")


def _load_tokenizer(root: Path) -> tuple[Any, str]:
    try:
        transformers = importlib.import_module("transformers")
    except ImportError as exc:
        raise ConfigurationError(
            "transformers==4.57.6 is required for exact Qwen tokenization"
        ) from exc
    if transformers.__version__ != _TRANSFORMERS_VERSION:
        raise ConfigurationError("exact Qwen tokenization requires transformers==4.57.6")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        root,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    return tokenizer, transformers.__version__


def _base_model_lock(path: Path, tokenizer_root: Path) -> dict[str, str]:
    value = _json(path.resolve(strict=True))
    required = {
        "model_id": _BASE_MODEL_ID,
        "remote_code": False,
    }
    if any(value.get(key) != expected for key, expected in required.items()):
        raise ConfigurationError("base-model lock differs from frozen Qwen3.5-9B")
    if Path(str(value.get("path"))).resolve(strict=True) != tokenizer_root:
        raise ConfigurationError("base-model lock path differs from tokenizer root")
    for key in ("snapshot_hash", "tokenizer_hash"):
        item = value.get(key)
        if not isinstance(item, str) or len(item) != 64:
            raise ConfigurationError("base-model lock lacks a SHA-256 identity")
    return {
        "snapshot_hash": str(value["snapshot_hash"]),
        "tokenizer_hash": str(value["tokenizer_hash"]),
    }


def _qualified_sources(progress: dict[str, Any]) -> dict[str, str]:
    pool = progress.get("training_pool")
    if not isinstance(pool, list) or len(pool) != 11:
        raise ConfigurationError("CVA6 qualification must freeze exactly 11 training tasks")
    sources: dict[str, str] = {}
    for item in pool:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("task_id"), str)
            or not isinstance(item.get("source"), str)
        ):
            raise ConfigurationError("CVA6 qualification training pool is malformed")
        sources[item["task_id"]] = item["source"]
    return sources


def _image_locks(root: Path, task_ids: set[str]) -> dict[str, HweAgentImageLock]:
    directory = root.resolve(strict=True)
    locks: dict[str, HweAgentImageLock] = {}
    for task_id in task_ids:
        suffix = task_id.rsplit("-", 1)[-1]
        lock = HweAgentImageLock.model_validate(_json(directory / f"pr-{suffix}.json"))
        if (
            lock.task_id != task_id
            or lock.format_id != "verigym_hwe_agent_image_lock_v2"
            or lock.collection_profile_id != HWE_COLLECTION_PROFILE_V2_ID
            or lock.tool_contract_id != HWE_TOOL_CONTRACT_V2_ID
        ):
            raise ConfigurationError("DeepSeek pilot image lock identity changed")
        locks[task_id] = lock
    return locks


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


def _runtime_image_preflight(locks: dict[str, HweAgentImageLock]) -> None:
    for task_id in DEEPSEEK_HARNESS_PILOT_TASKS:
        runtime = DockerRuntime(_docker_config(locks[task_id]))
        try:
            runtime.prepare(f"deepseek-harness-preflight-{task_id.rsplit('-', 1)[-1]}")
        finally:
            runtime.close()


def _zero_model_call_preflight_receipt(path: Path) -> str:
    report = _json(path.resolve(strict=True))
    expected_hash = report.pop("report_hash", None)
    attempts = report.get("attempts")
    if (
        not isinstance(expected_hash, str)
        or content_hash(report) != expected_hash
        or report.get("status") != "stopped_infrastructure_invalid"
        or not isinstance(attempts, list)
        or not attempts
        or any(
            not isinstance(item, dict)
            or item.get("status") != "infrastructure_invalid"
            or item.get("model_call_count") not in (None, 0)
            or item.get("action_record_count") != 0
            or item.get("normalized") is not False
            for item in attempts
        )
    ):
        raise ConfigurationError("superseded preflight is not a sealed zero-model-call failure")
    return expected_hash


def _infrastructure_invalid(scorecard: Any) -> bool:
    failure = scorecard.failure
    return bool(
        scorecard.correctness.infrastructure_error
        or (failure is not None and failure.infrastructure)
        or (scorecard.status == "error" and (failure is None or failure.kind == "runtime"))
    )


def _infrastructure_attempt(
    task_id: str,
    run_id: str,
    reason: str,
    *,
    run_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "run_id": run_id,
        "run_hash": run_hash or content_hash({"run_id": run_id, "reason": reason}),
        "status": "infrastructure_invalid",
        "infrastructure_valid": False,
        "verifier_pass": False,
        "normalized": False,
        "transcript_hash": None,
        "action_record_count": 0,
        "max_action_record_tokens": None,
        "overlength_record_count": 0,
        "model_call_count": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "rejection_reason": reason,
        "whole_episode_retries": 0,
    }


def _write_trajectory_records(
    path: Path,
    examples: list[dict[str, Any]],
    *,
    task_id: str,
    transcript_hash: str,
    run_hash: str,
) -> None:
    _atomic_jsonl(path, examples)
    raw = path.read_bytes()
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_deepseek_harness_trajectory_records_v1",
        "task_id": task_id,
        "transcript_hash": transcript_hash,
        "run_hash": run_hash,
        "record_count": len(examples),
        "record_hashes": [item["record_hash"] for item in examples],
        "max_token_count": max(int(item["token_count"]) for item in examples),
        "overlength_record_count": sum(item["eligible"] is not True for item in examples),
        "records_file": path.name,
        "records_sha256": hashlib.sha256(raw).hexdigest(),
        "production_training_ready": False,
        "hpc_jobs_submitted": False,
    }
    atomic_dump_json(
        path.with_suffix(".manifest.json"), {**base, "manifest_hash": content_hash(base)}
    )


def _assert_provider_secret_absent(root: Path) -> None:
    credential = os.environ[_API_KEY_ENV].encode("utf-8")
    for path in root.rglob("*"):
        if path.is_file() and credential in path.read_bytes():
            raise ConfigurationError("provider credential value reached the public dataset")


def _new_output(path: Path) -> Path:
    target = path.expanduser()
    if target.exists():
        raise ConfigurationError(
            "DeepSeek pilot output must not already exist; retries are forbidden"
        )
    target.mkdir(parents=True, mode=0o700)
    return target.resolve(strict=True)


def _seal_report(value: dict[str, Any]) -> dict[str, Any]:
    base = {key: item for key, item in value.items() if key != "report_hash"}
    return {**base, "report_hash": content_hash(base)}


def _atomic_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for value in values:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError(f"unsafe DeepSeek pilot JSON input: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError(f"DeepSeek pilot JSON input is not an object: {path.name}")
    return value


def main() -> int:
    arguments = _parser().parse_args()
    report = collect(
        qualification_root=arguments.qualification_root,
        image_lock_dir=arguments.image_lock_dir,
        tokenizer_root=arguments.tokenizer_root,
        base_model_lock=arguments.base_model_lock,
        output=arguments.output,
        campaign_id=arguments.campaign_id,
        supersedes_zero_call_preflight=arguments.supersedes_zero_call_preflight,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
