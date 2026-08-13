#!/usr/bin/env python3
"""Two-task OpenHands base-versus-adapter CVA6 development pilot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from verigym.api import RunConfig, VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.memory import validate_agent_version
from verigym.evolution.splits import validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest, TaskSplitManifest
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_CVA6_DEVELOPMENT_PILOT"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one base and one adapter development task.")
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--base-model-id", required=True)
    parser.add_argument("--adapter-model-id", required=True)
    parser.add_argument("--base-agent-version", type=Path, required=True)
    parser.add_argument("--adapter-agent-version", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-process-time-s", type=int, default=1800)
    return parser


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{_OPT_IN_ENV}=1 is required")
    if arguments.base_model_id == arguments.adapter_model_id:
        raise ConfigurationError("base and adapter must have distinct model identities")
    qualification = _safe_directory(arguments.qualification_root, "qualification")
    split = validate_task_split(
        TaskSplitManifest.model_validate_json(_regular_file(qualification / "task-split.json"))
    )
    report = json.loads(_regular_file(qualification / "qualification-progress.json"))
    validation = report.get("development_validation")
    if (
        report.get("status") != "completed"
        or report.get("task_split_hash") != split.manifest_hash
        or not isinstance(validation, list)
        or len(validation) != 2
        or len(split.validation) != 2
    ):
        raise ConfigurationError("qualification has no frozen two-task development split")
    versions = [
        _agent_version(arguments.base_agent_version, arguments.base_model_id, "none"),
        _agent_version(
            arguments.adapter_agent_version, arguments.adapter_model_id, "external_adapter"
        ),
    ]
    if versions[1].parent_version_hash != versions[0].version_hash:
        raise ConfigurationError("adapter agent version is not descended from the base policy")
    docker = DockerRuntimeConfig.model_validate_json(_regular_file(arguments.docker_config))
    if docker.pull_policy != "never" or docker.network_mode != "none":
        raise ConfigurationError("development verifier Docker runtime must be frozen offline")
    output = _new_directory(arguments.output)
    runs = output / "runs"
    runs.mkdir()
    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "openhands-repository-agent" not in registries.agents.names():
        from verigym_openhands import OpenHandsRepositoryAgentAdapter

        registries.agents.register(OpenHandsRepositoryAgentAdapter())
    service = VeriGym(registries)
    policies = (
        ("base", arguments.base_model_id, versions[0], validation[0]),
        ("adapter", arguments.adapter_model_id, versions[1], validation[1]),
    )
    outcomes: list[dict[str, Any]] = []
    for index, (label, model_id, version, binding) in enumerate(policies):
        if not isinstance(binding, dict):
            raise ConfigurationError("development task binding is malformed")
        task_id = binding.get("task_id")
        source_value = binding.get("source")
        if not isinstance(task_id, str) or not isinstance(source_value, str):
            raise ConfigurationError("development task binding omits task/source")
        source_root = _qualified_source(qualification, source_value)
        source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
        suite, task, _assets = service.load_task(task_id, source)
        snapshot = suite.source_snapshot()
        frozen = next(entry for entry in split.validation if entry.task_id == task_id)
        if (
            snapshot is None
            or content_hash(task) != frozen.task_hash
            or task.source.content_hash != frozen.source_hash
        ):
            raise ConfigurationError("development task changed after qualification")
        run_id = f"openhands-cva6-development-{index}-{label}"
        try:
            result = service.run(
                RunConfig(
                    task_id=task_id,
                    suite_source=source,
                    expected_suite_source_snapshot=snapshot,
                    expected_task_hash=frozen.task_hash,
                    expected_source_hash=frozen.source_hash,
                    mode=InteractionMode.AGENT,
                    runtime="docker",
                    docker_config=docker,
                    agent="openhands-repository-agent",
                    agent_options={
                        "model_id": model_id,
                        "max_process_time_s": arguments.max_process_time_s,
                        "campaign_role": "development",
                        "agent_version_id": version.agent_version_id,
                        "agent_version_hash": version.version_hash,
                        "agent_version_manifest_json": version.model_dump_json(),
                    },
                    seed=484 + index,
                    sample_index=0,
                    output=runs,
                    run_id=run_id,
                    experiment_id="openhands-cva6-development-pilot-v1",
                    plan_item_id=run_id,
                    system_id=f"qwen35-{label}",
                    base_seed=484,
                )
            )
        except Exception as exc:
            partial = {
                "format_id": "verigym_openhands_cva6_development_pilot_v1",
                "status": "stopped_infrastructure_invalid",
                "failed_policy": label,
                "error_type": type(exc).__name__,
                "outcomes": outcomes,
                "benchmark_score_claimed": False,
            }
            atomic_dump_json(output / "pilot-report.json", partial)
            raise ConfigurationError(f"OpenHands {label} pilot was infrastructure-invalid") from exc
        infrastructure_invalid = bool(
            result.scorecard.status == "error"
            or result.scorecard.correctness.infrastructure_error
            or (result.scorecard.failure is not None and result.scorecard.failure.infrastructure)
        )
        if infrastructure_invalid:
            atomic_dump_json(
                output / "pilot-report.json",
                {
                    "format_id": "verigym_openhands_cva6_development_pilot_v1",
                    "status": "stopped_infrastructure_invalid",
                    "failed_policy": label,
                    "run": result.run_dir.relative_to(output).as_posix(),
                    "outcomes": outcomes,
                    "benchmark_score_claimed": False,
                },
            )
            raise ConfigurationError(f"OpenHands {label} pilot was infrastructure-invalid")
        outcomes.append(
            {
                "policy": label,
                "model_id": model_id,
                "agent_version_id": version.agent_version_id,
                "agent_version_hash": version.version_hash,
                "task_id": task_id,
                "run": result.run_dir.relative_to(output).as_posix(),
                "resolved": result.scorecard.resolved,
                "infrastructure_valid": True,
            }
        )
    base: dict[str, Any] = {
        "format_id": "verigym_openhands_cva6_development_pilot_v1",
        "status": "completed",
        "task_split_hash": split.manifest_hash,
        "outcomes": outcomes,
        "quality_improved": outcomes[1]["resolved"] is True and outcomes[0]["resolved"] is False,
        "development_pilot": True,
        "benchmark_score_claimed": False,
        "sample_count": 2,
        "grpo_started": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "private_reasoning_exported": False,
        "credential_values_exported": False,
    }
    sealed = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(output / "pilot-report.json", sealed)
    return sealed


def _agent_version(path: Path, model_id: str, update_type: str) -> AgentVersionManifest:
    try:
        version = validate_agent_version(
            AgentVersionManifest.model_validate_json(_regular_file(path))
        )
    except ValueError as exc:
        raise ConfigurationError("OpenHands agent-version manifest is invalid") from exc
    if (
        version.base_agent_id != "openhands-repository-agent"
        or version.model_id != model_id
        or version.update_type != update_type
    ):
        raise ConfigurationError("OpenHands agent version differs from its pilot policy")
    return version


def _qualified_source(root: Path, value: str) -> Path:
    if (
        value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ConfigurationError("development source path is not canonical")
    resolved = _safe_directory(root / value, "development source")
    if not resolved.is_relative_to(root):
        raise ConfigurationError("development source escaped qualification root")
    return resolved


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError(f"{label} cannot be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError(f"{label} must be a directory")
    return resolved


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("pilot output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _regular_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ConfigurationError(f"expected a bounded regular file: {path.name}")
    return path.read_bytes()


def main() -> int:
    try:
        result = _run(_parser().parse_args())
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
