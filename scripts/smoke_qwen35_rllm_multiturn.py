#!/usr/bin/env python3
"""One opt-in rLLM-native repository rollout with no optimizer update."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from transformers import AutoTokenizer
from verigym_training_reference.multiturn_sft_training import validate_runtime_pins
from verigym_training_reference.repository_workflow import VeriGymRepositoryWorkflow

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

_OPT_IN_ENV = "VERIGYM_RUN_QWEN35_RLLM_MULTITURN_SMOKE"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one native MultiTurnWorkflow smoke.")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--base-url-env", default="VERIGYM_MODEL_BASE_URL")
    parser.add_argument("--api-key-env", default="VERIGYM_MODEL_API_KEY")
    parser.add_argument("--rllm-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{_OPT_IN_ENV}=1 is required")
    base_url = os.environ.get(arguments.base_url_env)
    api_key = os.environ.get(arguments.api_key_env)
    if not base_url or not api_key:
        raise ConfigurationError("model endpoint environment is incomplete")
    versions = validate_runtime_pins(arguments.rllm_source)
    task = _json_object(arguments.task)
    if task.get("hidden_assets_included") is not False or task.get("submission_kind") != "patch":
        raise ConfigurationError("native smoke task violates the public patch boundary")
    broker = _safe_directory(arguments.broker_root, "broker")
    model = _safe_directory(arguments.model_root, "model")
    destination = arguments.output.expanduser()
    if destination.exists() or destination.is_symlink():
        raise ConfigurationError("native smoke output must not exist")
    destination.mkdir(parents=True)
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)

    from rllm.engine.agent_workflow_engine import AgentWorkflowEngine
    from rllm.engine.rollout.openai_engine import OpenAIEngine
    from rllm.workflows.workflow import TerminationReason

    rollout = OpenAIEngine(
        model=arguments.model_id,
        tokenizer=tokenizer,
        max_prompt_length=16_384,
        max_response_length=16_384,
        max_model_length=32_768,
        api_retries=1,
        base_url=base_url,
        api_key=api_key,
        sampling_params={
            "temperature": 0.7,
            "top_p": 0.95,
            "seed": 484,
            "logprobs": 1,
        },
        accumulate_reasoning=False,
    )
    engine = AgentWorkflowEngine(
        workflow_cls=VeriGymRepositoryWorkflow,
        workflow_args={
            "repository_broker_root": str(broker),
            "broker_timeout_s": 3900,
            "timeout": 4200,
            "action_tokens": None,
            "max_steps": 128,
        },
        rollout_engine=rollout,
        config=None,
        n_parallel_tasks=1,
        retry_limit=1,
        raise_on_error=True,
    )
    episodes = await engine.execute_tasks([task], task_ids=[str(task["task_id"])])
    if len(episodes) != 1:
        raise RuntimeError("native rLLM smoke returned the wrong episode count")
    episode = episodes[0]
    if episode.termination_reason == TerminationReason.ERROR:
        raise RuntimeError("native rLLM smoke was infrastructure-invalid")
    if len(episode.trajectories) != 1 or not episode.trajectories[0].steps:
        raise RuntimeError("native rLLM smoke returned no trainable trajectory")
    steps = episode.trajectories[0].steps
    for step in steps:
        if (
            step.model_output is None
            or not step.prompt_ids
            or not step.response_ids
            or not step.logprobs
            or len(step.response_ids) != len(step.logprobs)
        ):
            raise RuntimeError("native rLLM smoke lost ModelOutput token/logprob payloads")
    base: dict[str, object] = {
        "format_id": "verigym_qwen35_rllm_native_multiturn_smoke_v1",
        "task_id": task["task_id"],
        "public_input_hash": task["record_hash"],
        "model_id": arguments.model_id,
        "workflow_class": "VeriGymRepositoryWorkflow",
        "upstream_loop_class": "MultiTurnWorkflow",
        "step_count": len(steps),
        "completion_token_count": sum(len(step.response_ids) for step in steps),
        "token_logprob_alignment_preserved": True,
        "infrastructure_valid": True,
        "resolved": bool(episode.is_correct),
        "termination_reason": episode.termination_reason.value,
        "optimizer_updates": 0,
        "grpo_optimizer_executed": False,
        "development_smoke": True,
        "benchmark_score_claimed": False,
        "rllm_commit": versions["rllm_commit"],
        "verl_version": versions["verl"],
        "vllm_version": versions["vllm"],
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
    }
    report = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(destination / "smoke-report.json", report)
    return report


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError(f"{label} cannot be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError(f"{label} must be a directory")
    return resolved


def _json_object(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
        raise ConfigurationError("native smoke task must be a bounded regular JSON file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ConfigurationError("native smoke task must be a JSON object")
    return value


def main() -> int:
    try:
        report = asyncio.run(_run(_parser().parse_args()))
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
