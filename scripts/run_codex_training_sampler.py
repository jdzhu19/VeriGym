#!/usr/bin/env python3
"""Run bounded Codex workspace-agent samples for verifier-filtered training data."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path

from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig, DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_OPT_IN_ENV = "VERIGYM_RUN_CODEX_TRAINING_SAMPLER"
_CAPABILITY_ENV = "VERIGYM_CODEX_CAPABILITY_FILE"
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect bounded Codex CLI samples through ordinary VeriGym verification."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--task", action="append", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--reasoning-effort", choices=("xhigh", "max"), default="max")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument("--max-process-time-s", type=int, default=900)
    parser.add_argument("--verifier-image", required=True)
    parser.add_argument("--verifier-image-id", required=True)
    parser.add_argument("--agent-image", required=True)
    parser.add_argument("--agent-image-id", required=True)
    parser.add_argument("--agent-codex-version", required=True)
    parser.add_argument("--agent-codex-sha256", required=True)
    return parser


def _required_file_from_env(name: str) -> Path:
    raw = os.environ.get(name)
    if not raw:
        raise SystemExit(f"set {name}")
    path = Path(raw).expanduser().resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"{name} must name a regular file")
    return path


def _new_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        raise SystemExit(f"sampling output already exists: {expanded}")
    expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _runtime(arguments: argparse.Namespace) -> DockerRuntimeConfig:
    if os.getuid() == 0:
        raise SystemExit("Docker training sampling requires a non-root host identity")
    user = f"{os.getuid()}:{os.getgid()}"
    labels = {
        "org.verigym.codex.version": arguments.agent_codex_version.removeprefix("codex-cli "),
        "org.verigym.codex.binary.sha256": arguments.agent_codex_sha256,
        "org.verigym.credential_material": "absent",
        "org.verigym.provider_credentials": "absent",
        "org.verigym.external_agent.protocol": ("codex_app_server_remote_environment_v1"),
    }
    return DockerRuntimeConfig(
        image=arguments.verifier_image,
        expected_image_id=arguments.verifier_image_id,
        pull_policy="never",
        network_mode="none",
        run_as_user=user,
        read_only_rootfs=True,
        memory_bytes=512 * 1024 * 1024,
        cpus=1.0,
        pids_limit=128,
        tmpfs_bytes=64 * 1024 * 1024,
        stop_timeout_s=3,
        max_command_time_s=arguments.max_process_time_s,
        environment_allowlist=[],
        external_agent=DockerExternalAgentRuntimeConfig(
            image=arguments.agent_image,
            expected_image_id=arguments.agent_image_id,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version=arguments.agent_codex_version,
            expected_executable_sha256=arguments.agent_codex_sha256,
            process_argv=[
                "/usr/local/bin/codex",
                "exec-server",
                "--listen",
                "stdio://",
            ],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels=labels,
            pull_policy="never",
            run_as_user=user,
            max_process_time_s=arguments.max_process_time_s,
        ),
    )


def _safe_run_id(index: int, task_id: str, sample_index: int) -> str:
    task = _SAFE_ID.sub("-", task_id).strip("-")
    return f"codex-training-{index:04d}-{task}-sample-{sample_index:03d}"


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    if not 1 <= arguments.samples <= 32:
        raise SystemExit("--samples must be in [1, 32]")
    if not 1 <= arguments.max_process_time_s <= 1800:
        raise SystemExit("--max-process-time-s must be in [1, 1800]")

    capability_path = _required_file_from_env(_CAPABILITY_ENV)
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    root = _new_root(arguments.output)
    runs_root = root / "runs"
    runs_root.mkdir()
    source = SuiteSourceConfig(
        source_root=arguments.source.expanduser().resolve(strict=True),
        variant=arguments.variant,
    )
    runtime = _runtime(arguments)
    registries = build_registries()
    service = VeriGym(registries)

    task_records: list[dict[str, str]] = []
    for task_id in arguments.task:
        suite, task, _assets = service.load_task(task_id, source)
        snapshot = suite.source_snapshot()
        task_records.append(
            {
                "task_id": task.id,
                "task_hash": content_hash(task),
                "source_hash": task.source.content_hash or snapshot.content_hash,
                "source_snapshot_hash": content_hash(snapshot),
            }
        )

    plan = {
        "schema_version": "1.0",
        "model_id": arguments.model_id,
        "reasoning_effort": arguments.reasoning_effort,
        "base_seed": arguments.base_seed,
        "samples_per_task": arguments.samples,
        "maximum_model_processes": len(task_records) * arguments.samples,
        "allow_retry": False,
        "allow_best_of_k_selection": False,
        "capability_fingerprint": capability["capability_fingerprint"],
        "cli_version": capability["version_output"],
        "verifier_image_id": arguments.verifier_image_id,
        "agent_image_id": arguments.agent_image_id,
        "task_records": task_records,
    }
    plan["plan_hash"] = content_hash(plan)
    atomic_dump_json(root / "sampling-plan.json", plan)

    records: list[dict[str, object]] = []
    index = 0
    for task_record in task_records:
        task_id = task_record["task_id"]
        for sample_index in range(arguments.samples):
            run_id = _safe_run_id(index, task_id, sample_index)
            config = RunConfig(
                task_id=task_id,
                suite_source=source,
                expected_task_hash=task_record["task_hash"],
                expected_source_hash=task_record["source_hash"],
                mode=InteractionMode.AGENT,
                agent="codex-cli-agent",
                agent_options={
                    "model_id": arguments.model_id,
                    "reasoning_effort": arguments.reasoning_effort,
                    "sandbox": "workspace-write",
                    "approval_policy": "non-interactive",
                    "allow_proxy_environment": True,
                    "max_process_time_s": arguments.max_process_time_s,
                    "expected_cli_version": capability["version_output"],
                    "expected_cli_executable_sha256": capability["executable_sha256"],
                    "expected_capability_fingerprint": capability["capability_fingerprint"],
                    "expected_execution_backend": "docker_outer_runtime_delegated",
                },
                runtime="docker",
                docker_config=runtime,
                seed=arguments.base_seed + index,
                sample_index=sample_index,
                output=runs_root,
                run_id=run_id,
                experiment_id="codex-training-sampler-v1",
                plan_item_id=f"sample-{index:04d}",
                system_id="codex-strong-agent-sampler",
                base_seed=arguments.base_seed,
            )
            result = service.run(config)
            infrastructure_invalid = bool(
                result.scorecard.status == "error"
                or result.scorecard.correctness.infrastructure_error
                or (
                    result.scorecard.failure is not None and result.scorecard.failure.infrastructure
                )
            )
            records.append(
                {
                    "run_id": result.manifest.run_id,
                    "run_dir": result.run_dir.relative_to(root).as_posix(),
                    "task_id": task_id,
                    "sample_index": sample_index,
                    "status": result.scorecard.status,
                    "resolved": result.scorecard.resolved,
                    "infrastructure_invalid": infrastructure_invalid,
                    "candidate_hash": result.scorecard.reproducibility.candidate_hash,
                }
            )
            index += 1

    atomic_dump_jsonl(root / "sampling-results.jsonl", records)
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "planned": len(records),
        "resolved": sum(record["resolved"] is True for record in records),
        "infrastructure_invalid": sum(
            record["infrastructure_invalid"] is True for record in records
        ),
        "rejected": sum(
            record["resolved"] is not True and record["infrastructure_invalid"] is not True
            for record in records
        ),
        "model_id": arguments.model_id,
        "reasoning_effort": arguments.reasoning_effort,
        "plan_hash": plan["plan_hash"],
    }
    summary["summary_hash"] = content_hash(summary)
    atomic_dump_json(root / "sampling-summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    summary = _run(_parser().parse_args(argv))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary["infrastructure_invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
