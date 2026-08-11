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

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import canonical_json, content_hash
from verigym.core.orchestrator import VeriGym
from verigym.evolution.memory import validate_agent_version
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest
from verigym.schemas.options import JsonValue
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
        description="Run bounded training or held-out Codex repository samples through VeriGym."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--campaign-role",
        choices=("training", "heldout"),
        default="training",
    )
    parser.add_argument("--heldout-freeze", type=Path)
    parser.add_argument("--agent-version", type=Path)
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


@dataclass(frozen=True)
class _HeldoutBinding:
    split_id: str
    split_manifest_hash: str
    freeze_manifest_hash: str
    agent_version: AgentVersionManifest


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


def _read_json_object(path: Path, *, label: str) -> dict[str, object]:
    resolved = path.expanduser()
    if resolved.is_symlink():
        raise SystemExit(f"{label} must be a regular JSON file")
    try:
        resolved = resolved.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"could not resolve {label}") from exc
    if not resolved.is_file() or not 0 < resolved.stat().st_size <= 16 * 1024 * 1024:
        raise SystemExit(f"{label} must be a bounded regular JSON file")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"could not read {label}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must contain a JSON object")
    return value


def _heldout_binding(
    arguments: argparse.Namespace,
    *,
    auth_semantic_id: str,
    task_records: list[dict[str, object]],
) -> _HeldoutBinding | None:
    role = arguments.campaign_role
    if role == "training":
        if arguments.heldout_freeze is not None or arguments.agent_version is not None:
            raise SystemExit("training campaigns may not accept held-out freeze inputs")
        return None
    if arguments.samples != 1:
        raise SystemExit("held-out repository campaigns require exactly one sample per task")
    if arguments.heldout_freeze is None or arguments.agent_version is None:
        raise SystemExit("held-out campaigns require --heldout-freeze and --agent-version")
    try:
        from verigym_training_reference.heldout import load_repository_heldout_freeze

        freeze, _split = load_repository_heldout_freeze(arguments.heldout_freeze)
        agent_version = validate_agent_version(
            AgentVersionManifest.model_validate(
                _read_json_object(arguments.agent_version, label="agent version")
            )
        )
    except (ConfigurationError, ImportError, OSError, ValueError) as exc:
        raise SystemExit(f"invalid held-out campaign binding: {exc}") from exc
    if freeze.agent_version_hash != agent_version.version_hash:
        raise SystemExit("held-out split and frozen agent version disagree")
    if (
        agent_version.base_agent_id != "codex-cli-agent"
        or agent_version.model_id != arguments.model_id
        or agent_version.reasoning_effort != arguments.reasoning_effort
        or agent_version.auth_semantic_id != auth_semantic_id
        or not agent_version.executable_in_m10b
        or agent_version.model_weights_modified
    ):
        raise SystemExit("frozen agent version differs from the requested Codex policy")
    expected_images: dict[str, str] = {
        "agent": arguments.agent_image_id.removeprefix("sha256:"),
        "verifier": arguments.verifier_image_id.removeprefix("sha256:"),
    }
    expected_tasks: list[tuple[str, str, str]] = []
    for record in task_records:
        task_id = record["task_id"]
        task_hash = record["task_hash"]
        source_hash = record["source_hash"]
        suite_images = record.get("suite_verifier_images", {})
        if (
            not isinstance(task_id, str)
            or not isinstance(task_hash, str)
            or not isinstance(source_hash, str)
            or not isinstance(suite_images, dict)
        ):
            raise SystemExit("campaign task records contain invalid verifier image identities")
        expected_tasks.append((task_id, task_hash, source_hash))
        for node_id, image_id in suite_images.items():
            if not isinstance(node_id, str) or not isinstance(image_id, str):
                raise SystemExit("campaign task records contain invalid verifier image identities")
            expected_images[f"suite-verifier:{task_id}:{node_id}"] = image_id.removeprefix(
                "sha256:"
            )
    if agent_version.image_hashes != expected_images:
        raise SystemExit("frozen agent version differs from the requested runtime images")
    expected_tasks.sort()
    frozen_tasks = [(item.task_id, item.task_hash, item.source_hash) for item in freeze.tasks]
    if expected_tasks != frozen_tasks:
        raise SystemExit("campaign task set differs from the frozen held-out split")
    return _HeldoutBinding(
        split_id=freeze.split_id,
        split_manifest_hash=freeze.split_manifest_hash,
        freeze_manifest_hash=freeze.manifest_hash,
        agent_version=agent_version,
    )


def _suite_verifier_images(task: object) -> dict[str, str]:
    """Collect digest-locked suite verifier images without suite-specific imports."""

    graph = getattr(task, "verifier", None)
    nodes = getattr(graph, "nodes", ())
    images: dict[str, str] = {}
    for node in nodes:
        request = getattr(node, "request", None)
        image_id = request.get("image_id") if isinstance(request, dict) else None
        node_id = getattr(node, "id", None)
        if image_id is None:
            continue
        if not isinstance(node_id, str) or not isinstance(image_id, str):
            raise SystemExit("suite verifier image identity must be a string")
        normalized = image_id.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise SystemExit("suite verifier image identity must be lowercase SHA-256")
        images[node_id] = normalized
    return dict(sorted(images.items()))


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
    for field in ("campaign_role", "split_manifest_hash", "agent_version_hash"):
        if field in plan:
            summary[field] = plan[field]
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
    runtime = _runtime(arguments)
    registries = build_registries()
    service = VeriGym(registries)

    loaded_tasks: list[tuple[SuiteSourceConfig, dict[str, object]]] = []
    task_records: list[dict[str, object]] = []
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
            "suite_verifier_images": _suite_verifier_images(task),
        }
        task_records.append(task_record)
        loaded_tasks.append((source, task_record))

    heldout = _heldout_binding(
        arguments,
        auth_semantic_id=_AUTH_SEMANTICS[auth_mode],
        task_records=task_records,
    )
    root = _new_root(arguments.output)
    runs_root = root / "runs"
    runs_root.mkdir()

    plan = {
        "schema_version": "1.0",
        "campaign_role": arguments.campaign_role,
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
    if heldout is not None:
        plan.update(
            {
                "split_id": heldout.split_id,
                "split_manifest_hash": heldout.split_manifest_hash,
                "heldout_freeze_manifest_hash": heldout.freeze_manifest_hash,
                "agent_version_id": heldout.agent_version.agent_version_id,
                "agent_version_hash": heldout.agent_version.version_hash,
            }
        )
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
        record_task_id = task_record["task_id"]
        record_task_hash = task_record["task_hash"]
        record_source_hash = task_record["source_hash"]
        if (
            not isinstance(record_task_id, str)
            or not isinstance(record_task_hash, str)
            or not isinstance(record_source_hash, str)
        ):
            raise AssertionError("validated task record lacks string identities")
        campaign_task_id = record_task_id
        for sample_index in range(arguments.samples):
            run_id = _safe_run_id(index, campaign_task_id, sample_index)
            agent_options: dict[str, JsonValue] = {
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
            }
            if heldout is not None:
                agent_options.update(
                    {
                        "agent_version_id": heldout.agent_version.agent_version_id,
                        "agent_version_hash": heldout.agent_version.version_hash,
                        "agent_version_manifest_json": canonical_json(heldout.agent_version),
                    }
                )
            config = RunConfig(
                task_id=campaign_task_id,
                suite_source=source,
                expected_task_hash=record_task_hash,
                expected_source_hash=record_source_hash,
                mode=InteractionMode.AGENT,
                agent="codex-cli-agent",
                agent_options=agent_options,
                runtime="docker",
                docker_config=runtime,
                seed=arguments.base_seed + index,
                sample_index=sample_index,
                output=runs_root,
                run_id=run_id,
                experiment_id=(
                    "codex-repository-heldout-v1"
                    if heldout is not None
                    else "codex-training-sampler-v1"
                ),
                plan_item_id=f"sample-{index:04d}",
                system_id=(
                    "codex-frozen-heldout-agent"
                    if heldout is not None
                    else "codex-strong-agent-sampler"
                ),
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
                        "task_id": campaign_task_id,
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
                        "task_id": campaign_task_id,
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
