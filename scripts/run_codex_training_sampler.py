#!/usr/bin/env python3
"""Run bounded Codex workspace-agent samples for verifier-filtered training data."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
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
_AUTH_SEMANTICS = {
    "chatgpt_cli_session": "codex.auth.inherited_chatgpt_session.v1",
    "inherited_codex_login": "codex.auth.inherited_chatgpt_session.v1",
    "api_key_env": "codex.auth.api_key_environment.v1",
    "custom_provider_environment": "codex.auth.custom_provider_environment.v1",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect bounded Codex CLI samples through ordinary VeriGym verification."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--task", action="append")
    parser.add_argument(
        "--source-task",
        action="append",
        metavar="SOURCE::TASK_ID",
        help="repeat to run tasks from different prepared source roots",
    )
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


@dataclass(frozen=True)
class _TaskRequest:
    source: Path
    task_id: str


def _task_requests(arguments: argparse.Namespace) -> list[_TaskRequest]:
    source_tasks = arguments.source_task or []
    legacy_tasks = arguments.task or []
    if source_tasks:
        if arguments.source is not None or legacy_tasks:
            raise SystemExit("use either --source/--task or repeated --source-task, not both")
        requests: list[_TaskRequest] = []
        for value in source_tasks:
            raw_source, separator, task_id = value.partition("::")
            if not separator or not raw_source or not task_id:
                raise SystemExit("--source-task must use SOURCE::TASK_ID")
            requests.append(_TaskRequest(source=Path(raw_source), task_id=task_id))
    else:
        if arguments.source is None or not legacy_tasks:
            raise SystemExit("provide --source with --task, or at least one --source-task")
        requests = [
            _TaskRequest(source=arguments.source, task_id=task_id) for task_id in legacy_tasks
        ]
    identities = [
        (request.source.expanduser().resolve(strict=True), request.task_id) for request in requests
    ]
    if len(identities) != len(set(identities)):
        raise SystemExit("task selection contains duplicate source/task pairs")
    return requests


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


def _summary(
    *,
    plan: dict[str, object],
    records: list[dict[str, object]],
    planned: int,
    stopped_early: bool,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "planned": planned,
        "completed": len(records),
        "resolved": sum(record["resolved"] is True for record in records),
        "infrastructure_invalid": sum(
            record["infrastructure_invalid"] is True for record in records
        ),
        "rejected": sum(
            record["resolved"] is not True and record["infrastructure_invalid"] is not True
            for record in records
        ),
        "stopped_early": stopped_early,
        "model_id": plan["model_id"],
        "reasoning_effort": plan["reasoning_effort"],
        "plan_hash": plan["plan_hash"],
    }
    summary["summary_hash"] = content_hash(summary)
    return summary


def _persist_progress(
    root: Path,
    *,
    plan: dict[str, object],
    records: list[dict[str, object]],
    planned: int,
    stopped_early: bool,
) -> dict[str, object]:
    atomic_dump_jsonl(root / "sampling-results.jsonl", records)
    summary = _summary(
        plan=plan,
        records=records,
        planned=planned,
        stopped_early=stopped_early,
    )
    atomic_dump_json(root / "sampling-summary.json", summary)
    return summary


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    if not 1 <= arguments.samples <= 32:
        raise SystemExit("--samples must be in [1, 32]")
    if not 1 <= arguments.max_process_time_s <= 1800:
        raise SystemExit("--max-process-time-s must be in [1, 1800]")
    auth_mode = os.environ.get("VERIGYM_CODEX_AUTH_MODE", "")
    if auth_mode not in _AUTH_SEMANTICS:
        raise SystemExit("set VERIGYM_CODEX_AUTH_MODE to a supported public label")

    capability_path = _required_file_from_env(_CAPABILITY_ENV)
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    requests = _task_requests(arguments)
    root = _new_root(arguments.output)
    runs_root = root / "runs"
    runs_root.mkdir()
    runtime = _runtime(arguments)
    registries = build_registries()
    service = VeriGym(registries)

    loaded_tasks: list[tuple[SuiteSourceConfig, dict[str, str]]] = []
    task_records: list[dict[str, str]] = []
    for request in requests:
        source = SuiteSourceConfig(
            source_root=request.source.expanduser().resolve(strict=True),
            variant=arguments.variant,
        )
        task_id = request.task_id
        suite, task, _assets = service.load_task(task_id, source)
        snapshot = suite.source_snapshot()
        task_record = {
            "task_id": task.id,
            "task_hash": content_hash(task),
            "source_hash": task.source.content_hash or snapshot.content_hash,
            "source_snapshot_hash": content_hash(snapshot),
        }
        task_records.append(task_record)
        loaded_tasks.append((source, task_record))

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
        "requested_auth_mode": auth_mode,
        "auth_semantic_id": _AUTH_SEMANTICS[auth_mode],
        "verifier_image_id": arguments.verifier_image_id,
        "agent_image_id": arguments.agent_image_id,
        "task_records": task_records,
    }
    plan["plan_hash"] = content_hash(plan)
    atomic_dump_json(root / "sampling-plan.json", plan)

    records: list[dict[str, object]] = []
    planned = len(task_records) * arguments.samples
    summary = _persist_progress(
        root,
        plan=plan,
        records=records,
        planned=planned,
        stopped_early=False,
    )
    index = 0
    stopped_early = False
    for source, task_record in loaded_tasks:
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
            try:
                result = service.run(config)
            except Exception as exc:
                infrastructure_invalid = True
                run_dir = runs_root / run_id
                records.append(
                    {
                        "run_id": run_id,
                        "run_dir": run_dir.relative_to(root).as_posix(),
                        "task_id": task_id,
                        "sample_index": sample_index,
                        "status": "error",
                        "resolved": False,
                        "infrastructure_invalid": True,
                        "candidate_hash": None,
                        "error_type": type(exc).__name__,
                    }
                )
            else:
                infrastructure_invalid = bool(
                    result.scorecard.status == "error"
                    or result.scorecard.correctness.infrastructure_error
                    or (
                        result.scorecard.failure is not None
                        and result.scorecard.failure.infrastructure
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
            stopped_early = infrastructure_invalid and index < planned
            summary = _persist_progress(
                root,
                plan=plan,
                records=records,
                planned=planned,
                stopped_early=stopped_early,
            )
            if infrastructure_invalid:
                break
        if infrastructure_invalid:
            break
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    summary = _run(_parser().parse_args(argv))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary["infrastructure_invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
