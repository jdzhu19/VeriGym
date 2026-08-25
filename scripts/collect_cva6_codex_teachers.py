#!/usr/bin/env python3
"""Collect a frozen Codex-only CVA6 teacher campaign."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer
from verigym_training_reference.cva6_teacher_collection import (
    _MAX_PROCESS_TIME_S,
    _MAX_TOKENS,
    _ensure_plugins,
    _episode_limits,
    _is_infrastructure_invalid,
    _provider_usage,
    _qualified_source,
    _regular_file,
    _run_config,
    _save_progress,
    _stop_for_campaign_limit,
    _training_transcript,
)
from verigym_training_reference.multiturn_sft_exporter import rllm_hf_template_token_count

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.splits import validate_task_split
from verigym.evolution.training_transcript import validate_teacher_transcript
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_TARGET_SUCCESSES = 8
_CAMPAIGN_FORMAT_ID = "verigym_cva6_teacher_collection_v2"
_CAMPAIGN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_OPT_IN_ENV = "VERIGYM_RUN_CVA6_TEACHER_COLLECTION"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect eight Codex-only CVA6 trajectories.")
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--campaign-id",
        default="cva6-verified-multiturn-codex-teachers-v2",
        help="Use a new identity for every changed provider or campaign policy.",
    )
    parser.add_argument("--max-process-time-s", type=int, default=_MAX_PROCESS_TIME_S)
    return parser


def _campaign_output(
    path: Path,
    *,
    campaign_id: str,
    split_hash: str,
    docker_config_hash: str,
    max_process_time_s: int,
) -> tuple[Path, dict[str, Any]]:
    expanded = path.expanduser()
    progress_path = expanded / "collection-progress.json"
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or not progress_path.is_file():
            raise ConfigurationError("Codex campaign output is neither new nor resumable")
        root = expanded.resolve(strict=True)
        progress = json.loads(_regular_file(progress_path, 32 * 1024 * 1024))
        expected_limits = _episode_limits(max_process_time_s)
        if (
            progress.get("format_id") != _CAMPAIGN_FORMAT_ID
            or progress.get("campaign_id") != campaign_id
            or progress.get("provider") != "codex"
            or progress.get("task_split_hash") != split_hash
            or progress.get("docker_config_hash") != docker_config_hash
            or progress.get("episode_limits") != expected_limits
        ):
            raise ConfigurationError("Codex campaign resume identity changed")
        if progress.get("status") == "stopped_infrastructure_invalid":
            raise ConfigurationError("infrastructure-invalid Codex campaign cannot auto-resume")
        return root, progress

    expanded.mkdir(parents=True)
    root = expanded.resolve(strict=True)
    progress: dict[str, Any] = {
        "format_id": _CAMPAIGN_FORMAT_ID,
        "campaign_id": campaign_id,
        "provider": "codex",
        "codex_model": "gpt-5.4",
        "codex_effort": "xhigh",
        "codex_samples_per_task": 1,
        "status": "running",
        "task_split_hash": split_hash,
        "docker_config_hash": docker_config_hash,
        "target_success_count": _TARGET_SUCCESSES,
        "max_tokens": _MAX_TOKENS,
        "observation_policy_id": "repository_observation_v1",
        "transcript_format": "v2",
        "episode_limits": _episode_limits(max_process_time_s),
        "attempts": [],
        "successes": [],
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
    }
    _save_progress(root, progress)
    return root, progress


def collect_cva6_codex_trajectories(
    *,
    qualification_root: Path,
    docker_config_path: Path,
    tokenizer: Any,
    output: Path,
    campaign_id: str,
    max_process_time_s: int = _MAX_PROCESS_TIME_S,
) -> dict[str, Any]:
    """Collect one Codex attempt per qualified task, stopping at eight successes."""

    import os

    if os.environ.get(_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{_OPT_IN_ENV}=1 is required")
    if not 1 <= max_process_time_s <= _MAX_PROCESS_TIME_S:
        raise ConfigurationError(f"teacher process timeout must be in [1, {_MAX_PROCESS_TIME_S}]")
    if _CAMPAIGN_ID.fullmatch(campaign_id) is None:
        raise ConfigurationError("Codex campaign ID is not a canonical public identifier")

    qualification = qualification_root.expanduser().resolve(strict=True)
    split = validate_task_split(
        TaskSplitManifest.model_validate_json(
            _regular_file(qualification / "task-split.json", 4 * 1024 * 1024)
        )
    )
    qualification_report = json.loads(
        _regular_file(qualification / "qualification-progress.json", 16 * 1024 * 1024)
    )
    if (
        qualification_report.get("status") != "completed"
        or qualification_report.get("task_split_hash") != split.manifest_hash
    ):
        raise ConfigurationError("CVA6 qualification is incomplete or differs from its split")
    training_pool = qualification_report.get("training_pool")
    if not isinstance(training_pool, list) or len(training_pool) != 11:
        raise ConfigurationError("qualification must freeze exactly 11 training candidates")

    docker_config = DockerRuntimeConfig.model_validate_json(
        _regular_file(docker_config_path.expanduser().resolve(strict=True), 1024 * 1024)
    )
    if docker_config.pull_policy != "never" or docker_config.network_mode != "none":
        raise ConfigurationError("teacher Docker runtime must be frozen offline")

    root, progress = _campaign_output(
        output,
        campaign_id=campaign_id,
        split_hash=split.manifest_hash,
        docker_config_hash=content_hash(docker_config),
        max_process_time_s=max_process_time_s,
    )
    attempts = progress["attempts"]
    successes = progress["successes"]
    if not isinstance(attempts, list) or not isinstance(successes, list):
        raise ConfigurationError("Codex campaign progress has malformed attempt state")
    attempted_ids = {item["attempt_id"] for item in attempts if isinstance(item, dict)}
    successful_tasks = {item["task_id"] for item in successes if isinstance(item, dict)}

    registries = build_registries(discover_external=True)
    _ensure_plugins(registries)
    service = VeriGym(registries)
    runs = root / "runs"
    runs.mkdir(exist_ok=True)

    for pool_index, item in enumerate(training_pool):
        if len(successes) >= _TARGET_SUCCESSES:
            break
        if not isinstance(item, dict):
            raise ConfigurationError("qualification training pool contains a malformed entry")
        task_id = item.get("task_id")
        relative_source = item.get("source")
        if not isinstance(task_id, str) or not isinstance(relative_source, str):
            raise ConfigurationError("qualification entry omits task/source identity")
        if task_id in successful_tasks:
            continue

        source_root = _qualified_source(qualification, relative_source)
        source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
        suite, task, _assets = service.load_task(task_id, source)
        snapshot = suite.source_snapshot()
        split_entry = next(entry for entry in split.training if entry.task_id == task_id)
        if (
            snapshot is None
            or content_hash(task) != split_entry.task_hash
            or task.source.content_hash != split_entry.source_hash
        ):
            raise ConfigurationError("qualified task identity changed before Codex collection")

        attempt_id = f"{campaign_id}-{pool_index:02d}-codex-sample-0"
        if attempt_id in attempted_ids:
            continue
        run_dir = runs / attempt_id
        if run_dir.exists() or run_dir.is_symlink():
            raise ConfigurationError("Codex campaign found an untracked run directory")

        config = _run_config(
            attempt_id=attempt_id,
            provider="codex",
            sample_index=0,
            task_id=task_id,
            task_hash=split_entry.task_hash,
            source_hash=split_entry.source_hash,
            source=source,
            source_snapshot=snapshot,
            docker_config=docker_config,
            output=runs,
            max_process_time_s=max_process_time_s,
            campaign_id=campaign_id,
        )
        try:
            result = service.run(config)
        except Exception as exc:
            attempts.append(
                {
                    "attempt_id": attempt_id,
                    "task_id": task_id,
                    "provider": "codex",
                    "sample_index": 0,
                    "status": "infrastructure_invalid",
                    "error_type": type(exc).__name__,
                }
            )
            progress["status"] = "stopped_infrastructure_invalid"
            progress["stop_reason"] = "run_boundary_exception"
            _save_progress(root, progress)
            raise ConfigurationError(
                f"Codex collection stopped on infrastructure-invalid {attempt_id}"
            ) from exc

        infrastructure_invalid = _is_infrastructure_invalid(result.scorecard)
        attempt: dict[str, Any] = {
            "attempt_id": attempt_id,
            "task_id": task_id,
            "provider": "codex",
            "sample_index": 0,
            "resolved": result.scorecard.resolved,
            "infrastructure_valid": not infrastructure_invalid,
        }
        try:
            resolved_run = Path(result.run_dir).expanduser().resolve(strict=True)
            if not resolved_run.is_relative_to(root):
                raise ConfigurationError("Codex teacher run escaped its campaign root")
            attempt["run"] = resolved_run.relative_to(root).as_posix()
        except (ConfigurationError, OSError) as exc:
            attempt.update(
                {
                    "status": "infrastructure_invalid",
                    "infrastructure_valid": False,
                    "error_type": type(exc).__name__,
                }
            )
            attempts.append(attempt)
            progress["status"] = "stopped_infrastructure_invalid"
            progress["stop_reason"] = "run_artifact_boundary_invalid"
            _save_progress(root, progress)
            raise ConfigurationError(
                f"Codex collection stopped on infrastructure-invalid {attempt_id}"
            ) from exc

        if infrastructure_invalid:
            attempt["status"] = "infrastructure_invalid"
            attempts.append(attempt)
            progress["status"] = "stopped_infrastructure_invalid"
            progress["stop_reason"] = "scorecard_infrastructure_invalid"
            _save_progress(root, progress)
            raise ConfigurationError(
                f"Codex collection stopped on infrastructure-invalid {attempt_id}"
            )

        try:
            attempt["provider_usage"] = _provider_usage(resolved_run, require_observed=False)
        except Exception as exc:
            attempt.update(
                {
                    "status": "infrastructure_invalid",
                    "infrastructure_valid": False,
                    "error_type": type(exc).__name__,
                }
            )
            attempts.append(attempt)
            progress["status"] = "stopped_infrastructure_invalid"
            progress["stop_reason"] = "provider_usage_artifact_invalid"
            _save_progress(root, progress)
            raise ConfigurationError(
                f"Codex collection stopped on infrastructure-invalid {attempt_id}"
            ) from exc

        if not result.scorecard.resolved:
            attempt["status"] = "verifier_rejected_or_agent_failed"
            attempts.append(attempt)
            attempted_ids.add(attempt_id)
            _save_progress(root, progress)
            if _stop_for_campaign_limit(root, progress):
                return progress
            continue

        try:
            transcript_path = _training_transcript(resolved_run)
            transcript = validate_teacher_transcript(
                json.loads(_regular_file(transcript_path, 32 * 1024 * 1024))
            )
            if transcript.get("task_id") != task_id:
                raise ConfigurationError("successful transcript has the wrong task identity")
            token_count = rllm_hf_template_token_count(tokenizer, transcript["messages"])
        except Exception as exc:
            attempt.update(
                {
                    "status": "infrastructure_invalid",
                    "infrastructure_valid": False,
                    "error_type": type(exc).__name__,
                }
            )
            attempts.append(attempt)
            progress["status"] = "stopped_infrastructure_invalid"
            progress["stop_reason"] = "successful_transcript_invalid"
            _save_progress(root, progress)
            raise ConfigurationError(
                f"Codex collection stopped on infrastructure-invalid {attempt_id}"
            ) from exc

        attempt["token_count"] = token_count
        attempt["transcript"] = transcript_path.relative_to(root).as_posix()
        if token_count > _MAX_TOKENS:
            attempt["status"] = "resolved_but_over_token_limit"
            attempts.append(attempt)
            attempted_ids.add(attempt_id)
            _save_progress(root, progress)
            if _stop_for_campaign_limit(root, progress):
                return progress
            continue

        attempt["status"] = "sft_eligible_success"
        attempts.append(attempt)
        successes.append(
            {
                "task_id": task_id,
                "provider": "codex",
                "attempt_id": attempt_id,
                "run": attempt["run"],
                "transcript": attempt["transcript"],
                "token_count": token_count,
                "transcript_hash": transcript["transcript_hash"],
            }
        )
        successful_tasks.add(task_id)
        attempted_ids.add(attempt_id)
        _save_progress(root, progress)

    progress["status"] = (
        "completed" if len(successes) == _TARGET_SUCCESSES else "incomplete_training_pool_exhausted"
    )
    progress["eligible_success_count"] = len(successes)
    _save_progress(root, progress)
    if len(successes) == _TARGET_SUCCESSES:
        atomic_dump_json(
            root / "successful-bindings.json",
            {
                "format_id": "verigym_cva6_teacher_bindings_v2",
                "task_split_hash": split.manifest_hash,
                "record_count": _TARGET_SUCCESSES,
                "bindings": successes,
                "private_reasoning_exported": False,
                "hidden_assets_exported": False,
                "reference_solutions_exported": False,
                "credential_values_exported": False,
            },
        )
    return progress


def main() -> int:
    arguments = _parser().parse_args()
    tokenizer = AutoTokenizer.from_pretrained(
        arguments.tokenizer.expanduser().resolve(strict=True), local_files_only=True
    )
    report = collect_cva6_codex_trajectories(
        qualification_root=arguments.qualification_root,
        docker_config_path=arguments.docker_config,
        tokenizer=tokenizer,
        output=arguments.output,
        campaign_id=arguments.campaign_id,
        max_process_time_s=arguments.max_process_time_s,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
