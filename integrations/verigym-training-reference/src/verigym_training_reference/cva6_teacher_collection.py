"""Sequential Claude-first, Codex-fallback CVA6 teacher collection."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from verigym.api import RunConfig, VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.splits import validate_task_split
from verigym.evolution.training_transcript import validate_teacher_transcript
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

from .multiturn_sft_exporter import ChatTemplateTokenizer, rllm_hf_template_token_count

_CLAUDE_MODEL = "deepseek-v4-flash[1m]"
_CLAUDE_CONTEXT_WINDOW = 1_000_000
_CODEX_MODEL = "gpt-5.4"
_BASE_SEED = 484
_TARGET_SUCCESSES = 8
_MAX_TOKENS = 16_384
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
_MAX_PROCESS_TIME_S = 600
_MAX_TOOL_CALLS = 32
_MAX_PATCH_CALLS = 8
_MAX_CONSECUTIVE_REJECTED_CALLS = 3
_MAX_PROVIDER_TOKENS = 2_000_000
_MAX_BUDGET_USD = 2.0
_MAX_CAMPAIGN_PROVIDER_TOKENS = 32_000_000
_MAX_CAMPAIGN_COST_USD = 40.0
_OPT_IN_ENV = "VERIGYM_RUN_CVA6_TEACHER_COLLECTION"
_DEFAULT_CAMPAIGN_ID = "cva6-verified-multiturn-teachers-v1"
_CAMPAIGN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def collect_cva6_teacher_trajectories(
    *,
    qualification_root: Path,
    docker_config_path: Path,
    tokenizer: ChatTemplateTokenizer,
    output: Path,
    max_process_time_s: int = _MAX_PROCESS_TIME_S,
    campaign_id: str = _DEFAULT_CAMPAIGN_ID,
) -> dict[str, Any]:
    """Collect at most one eligible success per task and stop after eight."""

    import os

    if os.environ.get(_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{_OPT_IN_ENV}=1 is required")
    if not 1 <= max_process_time_s <= _MAX_PROCESS_TIME_S:
        raise ConfigurationError(f"teacher process timeout must be in [1, {_MAX_PROCESS_TIME_S}]")
    if _CAMPAIGN_ID.fullmatch(campaign_id) is None:
        raise ConfigurationError("teacher campaign ID is not a canonical public identifier")
    qualification = _safe_directory(qualification_root, "qualification")
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
        raise ConfigurationError("CVA6 qualification must freeze exactly 11 training candidates")
    expected_tasks = {entry.task_id for entry in split.training}
    if {item.get("task_id") for item in training_pool if isinstance(item, dict)} != expected_tasks:
        raise ConfigurationError("qualification training pool differs from the frozen split")
    docker_config = DockerRuntimeConfig.model_validate_json(
        _regular_file(docker_config_path, 1024 * 1024)
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
    assert isinstance(attempts, list) and isinstance(successes, list)
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
            raise ConfigurationError("qualification training entry omits task/source identity")
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
            raise ConfigurationError("qualified task identity changed before teacher collection")

        schedule = [
            *(("claude", index) for index in range(3)),
            ("codex", 0),
        ]
        for provider, sample_index in schedule:
            if task_id in successful_tasks:
                break
            attempt_id = _attempt_id(campaign_id, pool_index, provider, sample_index)
            if attempt_id in attempted_ids:
                continue
            run_dir = runs / attempt_id
            if run_dir.exists() or run_dir.is_symlink():
                progress["status"] = "stopped_infrastructure_invalid"
                progress["stop_reason"] = "untracked_run_directory"
                _save_progress(root, progress)
                raise ConfigurationError("campaign found an untracked run directory")
            config = _run_config(
                attempt_id=attempt_id,
                provider=provider,
                sample_index=sample_index,
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
                        "provider": provider,
                        "sample_index": sample_index,
                        "status": "infrastructure_invalid",
                        "error_type": type(exc).__name__,
                    }
                )
                progress["status"] = "stopped_infrastructure_invalid"
                progress["stop_reason"] = "run_boundary_exception"
                _save_progress(root, progress)
                raise ConfigurationError(
                    f"teacher collection stopped on infrastructure-invalid {attempt_id}"
                ) from exc
            infrastructure_invalid = _is_infrastructure_invalid(result.scorecard)
            attempt: dict[str, Any] = {
                "attempt_id": attempt_id,
                "task_id": task_id,
                "provider": provider,
                "sample_index": sample_index,
                "resolved": result.scorecard.resolved,
                "infrastructure_valid": not infrastructure_invalid,
            }
            try:
                resolved_run = _safe_directory(result.run_dir, "teacher run")
                if not resolved_run.is_relative_to(root):
                    raise ConfigurationError("teacher run escaped its campaign root")
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
                    f"teacher collection stopped on infrastructure-invalid {attempt_id}"
                ) from exc
            if infrastructure_invalid:
                attempt["status"] = "infrastructure_invalid"
                attempts.append(attempt)
                progress["status"] = "stopped_infrastructure_invalid"
                progress["stop_reason"] = "scorecard_infrastructure_invalid"
                _save_progress(root, progress)
                raise ConfigurationError(
                    f"teacher collection stopped on infrastructure-invalid {attempt_id}"
                )
            try:
                attempt["provider_usage"] = _provider_usage(
                    resolved_run,
                    require_observed=provider == "claude",
                )
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
                    f"teacher collection stopped on infrastructure-invalid {attempt_id}"
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
                    f"teacher collection stopped on infrastructure-invalid {attempt_id}"
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
            success = {
                "task_id": task_id,
                "provider": provider,
                "attempt_id": attempt_id,
                "run": attempt["run"],
                "transcript": attempt["transcript"],
                "token_count": token_count,
                "transcript_hash": transcript["transcript_hash"],
            }
            successes.append(success)
            successful_tasks.add(task_id)
            attempted_ids.add(attempt_id)
            _save_progress(root, progress)
            if _stop_for_campaign_limit(root, progress):
                return progress

    progress["status"] = (
        "completed" if len(successes) == _TARGET_SUCCESSES else "incomplete_training_pool_exhausted"
    )
    progress["eligible_success_count"] = len(successes)
    _save_progress(root, progress)
    if len(successes) == _TARGET_SUCCESSES:
        atomic_dump_json(
            root / "successful-bindings.json",
            {
                "format_id": "verigym_cva6_teacher_bindings_v1",
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


def _run_config(
    *,
    attempt_id: str,
    provider: str,
    sample_index: int,
    task_id: str,
    task_hash: str,
    source_hash: str,
    source: SuiteSourceConfig,
    source_snapshot: Any,
    docker_config: DockerRuntimeConfig,
    output: Path,
    max_process_time_s: int,
    campaign_id: str,
) -> RunConfig:
    child_seed = int.from_bytes(
        hashlib.sha256(f"{_BASE_SEED}:{attempt_id}".encode()).digest()[:4], "big"
    )
    common: dict[str, Any] = {
        "task_id": task_id,
        "suite_source": source,
        "expected_suite_source_snapshot": source_snapshot,
        "expected_task_hash": task_hash,
        "expected_source_hash": source_hash,
        "mode": InteractionMode.AGENT,
        "runtime": "docker",
        "docker_config": docker_config,
        "seed": child_seed,
        "sample_index": sample_index,
        "output": output,
        "run_id": attempt_id,
        "experiment_id": campaign_id,
        "plan_item_id": attempt_id,
        "system_id": f"{provider}-mcp-teacher",
        "base_seed": _BASE_SEED,
    }
    if provider == "claude":
        return RunConfig(
            **common,
            agent="claude-cli-agent",
            agent_options={
                "model_id": _CLAUDE_MODEL,
                "reasoning_effort": "max",
                "expected_context_window": _CLAUDE_CONTEXT_WINDOW,
                "max_process_time_s": max_process_time_s,
                "max_output_bytes": _MAX_EVIDENCE_BYTES,
                "allow_proxy_environment": True,
                "campaign_role": "training",
                "capture_training_transcript": True,
                "max_tool_calls": _MAX_TOOL_CALLS,
                "max_patch_calls": _MAX_PATCH_CALLS,
                "max_consecutive_rejected_calls": _MAX_CONSECUTIVE_REJECTED_CALLS,
                "max_provider_billed_units": _MAX_PROVIDER_TOKENS,
                "max_budget_usd": _MAX_BUDGET_USD,
            },
        )
    return RunConfig(
        **common,
        agent="codex-cli-mcp-teacher",
        agent_options={
            "model_id": _CODEX_MODEL,
            "reasoning_effort": "xhigh",
            "max_process_time_s": max_process_time_s,
            "max_output_bytes": _MAX_EVIDENCE_BYTES,
            "allow_proxy_environment": True,
            "campaign_role": "training",
            "capture_training_transcript": True,
            "max_tool_calls": _MAX_TOOL_CALLS,
            "max_patch_calls": _MAX_PATCH_CALLS,
            "max_consecutive_rejected_calls": _MAX_CONSECUTIVE_REJECTED_CALLS,
        },
    )


def _ensure_plugins(registries: Any) -> None:
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "claude-cli-agent" not in registries.agents.names():
        from verigym_claude_cli import ClaudeCliAgentAdapter  # type: ignore[import-untyped]

        registries.agents.register(ClaudeCliAgentAdapter())
    if "codex-cli-mcp-teacher" not in registries.agents.names():
        from verigym_codex_cli import CodexCliMcpTeacherAdapter  # type: ignore[import-untyped]

        registries.agents.register(CodexCliMcpTeacherAdapter())


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
            raise ConfigurationError("collection output is neither new nor resumable")
        root = expanded.resolve(strict=True)
        progress = json.loads(_regular_file(progress_path, 32 * 1024 * 1024))
        if (
            progress.get("format_id") != "verigym_cva6_teacher_collection_v1"
            or progress.get("campaign_id") != campaign_id
            or progress.get("task_split_hash") != split_hash
            or progress.get("docker_config_hash") != docker_config_hash
            or progress.get("episode_limits") != _episode_limits(max_process_time_s)
        ):
            raise ConfigurationError("collection resume identity changed")
        if progress.get("status") == "stopped_infrastructure_invalid":
            raise ConfigurationError("infrastructure-invalid collection cannot auto-resume")
        if progress.get("status") == "incomplete_campaign_resource_limit":
            raise ConfigurationError("resource-exhausted collection cannot auto-resume")
        return root, progress
    expanded.mkdir(parents=True)
    root = expanded.resolve(strict=True)
    progress = {
        "format_id": "verigym_cva6_teacher_collection_v1",
        "campaign_id": campaign_id,
        "status": "running",
        "task_split_hash": split_hash,
        "docker_config_hash": docker_config_hash,
        "target_success_count": _TARGET_SUCCESSES,
        "claude_model": _CLAUDE_MODEL,
        "claude_effort": "max",
        "claude_samples_per_task": 3,
        "codex_fallback_model": _CODEX_MODEL,
        "codex_fallback_effort": "xhigh",
        "base_seed": _BASE_SEED,
        "max_tokens": _MAX_TOKENS,
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


def _episode_limits(max_process_time_s: int) -> dict[str, int | float]:
    return {
        "max_process_time_s": max_process_time_s,
        "max_tool_calls": _MAX_TOOL_CALLS,
        "max_patch_calls": _MAX_PATCH_CALLS,
        "max_consecutive_rejected_calls": _MAX_CONSECUTIVE_REJECTED_CALLS,
        "claude_max_provider_tokens": _MAX_PROVIDER_TOKENS,
        "claude_expected_context_window": _CLAUDE_CONTEXT_WINDOW,
        "claude_max_budget_usd": _MAX_BUDGET_USD,
        "max_campaign_provider_tokens": _MAX_CAMPAIGN_PROVIDER_TOKENS,
        "max_campaign_cost_usd": _MAX_CAMPAIGN_COST_USD,
    }


def _save_progress(root: Path, progress: dict[str, Any]) -> None:
    progress["eligible_success_count"] = len(progress["successes"])
    progress["provider_usage_totals"] = _provider_usage_totals(progress["attempts"])
    atomic_dump_json(root / "collection-progress.json", progress)


def _provider_usage_totals(attempts: Any) -> dict[str, int | float]:
    billed_tokens = 0
    known_cost_usd = 0.0
    usage_records = 0
    complete_records = 0
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            usage = attempt.get("provider_usage")
            if not isinstance(usage, dict):
                continue
            billed = usage.get("billed_tokens_observed")
            cost = usage.get("cost_usd")
            if isinstance(billed, int) and not isinstance(billed, bool) and billed >= 0:
                billed_tokens += billed
            if isinstance(cost, int | float) and not isinstance(cost, bool):
                parsed_cost = float(cost)
                if math.isfinite(parsed_cost) and parsed_cost >= 0:
                    known_cost_usd += parsed_cost
            usage_records += 1
            complete_records += int(usage.get("usage_complete") is True)
    return {
        "usage_records": usage_records,
        "complete_records": complete_records,
        "billed_tokens_observed": billed_tokens,
        "known_cost_usd": known_cost_usd,
    }


def _stop_for_campaign_limit(root: Path, progress: dict[str, Any]) -> bool:
    if len(progress["successes"]) >= _TARGET_SUCCESSES:
        return False
    totals = _provider_usage_totals(progress["attempts"])
    reason: str | None = None
    if totals["billed_tokens_observed"] >= _MAX_CAMPAIGN_PROVIDER_TOKENS:
        reason = "campaign_provider_token_limit"
    elif totals["known_cost_usd"] >= _MAX_CAMPAIGN_COST_USD:
        reason = "campaign_provider_budget_limit"
    if reason is None:
        return False
    progress["status"] = "incomplete_campaign_resource_limit"
    progress["stop_reason"] = reason
    _save_progress(root, progress)
    return True


def _attempt_id(campaign_id: str, pool_index: int, provider: str, sample_index: int) -> str:
    return f"{campaign_id}-{pool_index:02d}-{provider}-sample-{sample_index}"


def _is_infrastructure_invalid(scorecard: Any) -> bool:
    failure = scorecard.failure
    return bool(
        scorecard.correctness.infrastructure_error
        or (failure is not None and failure.infrastructure)
        or (scorecard.status == "error" and (failure is None or failure.kind == "runtime"))
    )


def _training_transcript(run: Path) -> Path:
    matches = sorted(run.glob("artifacts/*/training-transcript.json"))
    if len(matches) != 1 or matches[0].is_symlink():
        raise ConfigurationError("resolved teacher run has no unique training transcript")
    return matches[0]


def _provider_usage(run: Path, *, require_observed: bool = True) -> dict[str, Any]:
    matches = sorted(run.glob("artifacts/*/provider-usage.json"))
    if len(matches) != 1 or matches[0].is_symlink():
        raise ConfigurationError("teacher run has no unique provider usage artifact")
    payload = json.loads(_regular_file(matches[0], 1024 * 1024))
    if not isinstance(payload, dict):
        raise ConfigurationError("provider usage artifact is malformed")

    def token(name: str) -> int | None:
        value = payload.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigurationError("provider usage token count is malformed")
        return value

    input_tokens = token("input_tokens")
    output_tokens = token("output_tokens")
    cache_creation = token("cache_creation_input_tokens")
    cache_read = token("cache_read_input_tokens")
    cached_input = token("cached_input_tokens")
    billed = token("billed_tokens_observed")
    components = (input_tokens, output_tokens, cache_creation, cache_read)
    if billed is None and any(value is not None for value in components):
        billed = sum(value or 0 for value in components)
    if billed is None and require_observed:
        raise ConfigurationError("provider usage artifact has no observed token count")
    raw_cost = payload.get("cost_usd")
    cost_usd: float | None = None
    if raw_cost is not None:
        if isinstance(raw_cost, bool) or not isinstance(raw_cost, int | float):
            raise ConfigurationError("provider usage cost is malformed")
        cost_usd = float(raw_cost)
        if not math.isfinite(cost_usd) or cost_usd < 0:
            raise ConfigurationError("provider usage cost is malformed")
    limit_failure = payload.get("provider_limit_failure")
    if limit_failure is not None and (
        not isinstance(limit_failure, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", limit_failure) is None
    ):
        raise ConfigurationError("provider usage limit failure is malformed")
    return {
        "usage_complete": payload.get("usage_complete") is True,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "cached_input_tokens": cached_input,
        "billed_tokens_observed": billed,
        "cost_usd": cost_usd,
        "provider_limit_failure": limit_failure,
    }


def _qualified_source(root: Path, relative: str) -> Path:
    if (
        not relative
        or relative.startswith("/")
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ConfigurationError("qualification contains a non-canonical source path")
    path = root / relative
    resolved = _safe_directory(path, "qualified source")
    if not resolved.is_relative_to(root):
        raise ConfigurationError("qualified source escaped its root")
    return resolved


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError(f"{label} cannot be a symlink")
    try:
        resolved = expanded.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"{label} does not exist") from exc
    if not resolved.is_dir():
        raise ConfigurationError(f"{label} must be a directory")
    return resolved


def _regular_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"expected regular file: {path.name}")
    if path.stat().st_size <= 0 or path.stat().st_size > maximum:
        raise ConfigurationError(f"input file is empty or oversized: {path.name}")
    return path.read_bytes()


__all__ = ["collect_cva6_teacher_trajectories"]
