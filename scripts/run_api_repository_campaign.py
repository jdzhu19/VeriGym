#!/usr/bin/env python3
"""Run a frozen, provider-neutral API repository evaluation campaign."""

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
from verigym.provenance import get_build_provenance
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest
from verigym.schemas.model import ModelRunConfig
from verigym.schemas.options import JsonValue
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig, DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_OPT_IN_ENV = "VERIGYM_RUN_API_REPOSITORY_CAMPAIGN"
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_AUTH_SEMANTIC_ID = "deepseek.env-bearer.v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bounded training or held-out API repository samples through VeriGym."
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
    parser.add_argument("--provider-id", default="DeepSeek")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--base-url-env", default="VERIGYM_DEEPSEEK_API_BASE_URL")
    parser.add_argument("--api-key-env", default="VERIGYM_DEEPSEEK_API_KEY")
    parser.add_argument("--thinking-mode", choices=("disabled", "enabled"), default="disabled")
    parser.add_argument(
        "--action-plan-protocol",
        choices=(
            "strict_four_action_repository_repair_v1",
            "strict_three_action_repository_repair_v1",
        ),
        default="strict_four_action_repository_repair_v1",
    )
    parser.add_argument("--max-output-tokens", type=int, default=16_384)
    parser.add_argument("--connect-timeout-s", type=float, default=10.0)
    parser.add_argument("--read-timeout-s", type=float, default=120.0)
    parser.add_argument("--request-timeout-s", type=float, default=120.0)
    parser.add_argument("--max-response-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument("--max-process-time-s", type=int, default=900)
    parser.add_argument("--verifier-image", required=True)
    parser.add_argument("--verifier-image-id", required=True)
    parser.add_argument("--agent-image", required=True)
    parser.add_argument("--agent-image-id", required=True)
    parser.add_argument("--agent-executable-version", required=True)
    parser.add_argument("--agent-executable-sha256", required=True)
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


def _read_json_object(path: Path, *, label: str) -> dict[str, object]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise SystemExit(f"{label} must be a regular JSON file")
    try:
        resolved = expanded.resolve(strict=True)
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


def _suite_verifier_images(task: object) -> dict[str, str]:
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


def _heldout_binding(
    arguments: argparse.Namespace,
    *,
    task_records: list[dict[str, object]],
    agent_descriptor_hash: str,
) -> _HeldoutBinding | None:
    if arguments.campaign_role == "training":
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
    reasoning_effort = f"thinking-{arguments.thinking_mode}"
    if freeze.agent_version_hash != agent_version.version_hash:
        raise SystemExit("held-out split and frozen agent version disagree")
    if (
        agent_version.base_agent_id != "api-repository-agent"
        or agent_version.agent_descriptor_hash != agent_descriptor_hash
        or agent_version.model_id != arguments.model_id
        or agent_version.reasoning_effort != reasoning_effort
        or agent_version.auth_semantic_id != _AUTH_SEMANTIC_ID
        or agent_version.package_hashes.get("api-request-policy") != _model_policy_hash(arguments)
        or not agent_version.executable_in_m10b
        or agent_version.model_weights_modified
    ):
        raise SystemExit("frozen agent version differs from the requested API policy")
    provenance = get_build_provenance()
    if provenance.dirty or provenance.source_commit != agent_version.source_commit:
        raise SystemExit("held-out API campaign requires the frozen clean source commit")
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


def _runtime(arguments: argparse.Namespace) -> DockerRuntimeConfig:
    if os.getuid() == 0:
        raise SystemExit("Docker API repository evaluation requires a non-root host identity")
    user = f"{os.getuid()}:{os.getgid()}"
    labels = {
        "org.verigym.codex.version": arguments.agent_executable_version.removeprefix("codex-cli "),
        "org.verigym.codex.binary.sha256": arguments.agent_executable_sha256,
        "org.verigym.credential_material": "absent",
        "org.verigym.provider_credentials": "absent",
        "org.verigym.external_agent.protocol": "codex_app_server_remote_environment_v1",
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
            expected_executable_version=arguments.agent_executable_version,
            expected_executable_sha256=arguments.agent_executable_sha256,
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels=labels,
            pull_policy="never",
            run_as_user=user,
            max_process_time_s=arguments.max_process_time_s,
        ),
    )


def _model_options(arguments: argparse.Namespace) -> ModelRunConfig:
    return ModelRunConfig(
        base_url_env=arguments.base_url_env,
        provider_id=arguments.provider_id,
        model_id=arguments.model_id,
        api_key_env=arguments.api_key_env,
        connect_timeout_s=arguments.connect_timeout_s,
        read_timeout_s=arguments.read_timeout_s,
        request_timeout_s=arguments.request_timeout_s,
        max_response_bytes=arguments.max_response_bytes,
        require_exact_model_id=True,
        client_options={"thinking_mode": arguments.thinking_mode},
    )


def _model_policy_hash(arguments: argparse.Namespace) -> str:
    """Bind the secret-free provider request policy into the frozen agent version."""

    return content_hash(
        {
            "schema_version": "1.0",
            "protocol": "openai.chat.completions",
            "provider_id": arguments.provider_id,
            "model_id": arguments.model_id,
            "base_url_env": arguments.base_url_env,
            "api_key_env": arguments.api_key_env,
            "auth_semantic_id": _AUTH_SEMANTIC_ID,
            "thinking_mode": arguments.thinking_mode,
            "action_plan_protocol": arguments.action_plan_protocol,
            "max_output_tokens": arguments.max_output_tokens,
            "connect_timeout_s": arguments.connect_timeout_s,
            "read_timeout_s": arguments.read_timeout_s,
            "request_timeout_s": arguments.request_timeout_s,
            "max_response_bytes": arguments.max_response_bytes,
            "require_exact_model_id": True,
            "allow_retry": False,
            "allow_best_of_k_selection": False,
        }
    )


def _new_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        raise SystemExit(f"sampling output already exists: {expanded}")
    expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _safe_run_id(index: int, task_id: str, sample_index: int) -> str:
    task = _SAFE_ID.sub("-", task_id).strip("-")
    return f"api-repository-{index:04d}-{task}-sample-{sample_index:03d}"


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
        "provider_id": plan["provider_id"],
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


def _validate_arguments(arguments: argparse.Namespace) -> None:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    if not 1 <= arguments.samples <= 32:
        raise SystemExit("--samples must be in [1, 32]")
    if not 1 <= arguments.max_process_time_s <= 1800:
        raise SystemExit("--max-process-time-s must be in [1, 1800]")
    if not 1 <= arguments.max_output_tokens <= 65_536:
        raise SystemExit("--max-output-tokens must be in [1, 65536]")
    for field in ("connect_timeout_s", "read_timeout_s", "request_timeout_s"):
        if not 0 < getattr(arguments, field) <= 1800:
            raise SystemExit(f"--{field.replace('_', '-')} must be in (0, 1800]")
    for name in (arguments.base_url_env, arguments.api_key_env):
        if not _ENV_NAME.fullmatch(name):
            raise SystemExit("model environment names must be safe identifiers")
        if not os.environ.get(name):
            raise SystemExit(f"set {name}")


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    _validate_arguments(arguments)
    requests = _task_requests(arguments)
    runtime = _runtime(arguments)
    model_options = _model_options(arguments)
    registries = build_registries()
    service = VeriGym(registries)
    agent = registries.agents.get("api-repository-agent")

    loaded_tasks: list[tuple[SuiteSourceConfig, dict[str, object]]] = []
    task_records: list[dict[str, object]] = []
    for request in requests:
        source = SuiteSourceConfig(
            source_root=request.source.expanduser().resolve(strict=True),
            variant=arguments.variant,
        )
        suite, task, _assets = service.load_task(request.task_id, source)
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
        task_records=task_records,
        agent_descriptor_hash=content_hash(agent.descriptor),
    )
    root = _new_root(arguments.output)
    runs_root = root / "runs"
    runs_root.mkdir()
    reasoning_effort = f"thinking-{arguments.thinking_mode}"
    plan: dict[str, object] = {
        "schema_version": "1.0",
        "campaign_role": arguments.campaign_role,
        "provider_id": arguments.provider_id,
        "model_id": arguments.model_id,
        "reasoning_effort": reasoning_effort,
        "thinking_mode": arguments.thinking_mode,
        "action_plan_protocol": arguments.action_plan_protocol,
        "max_output_tokens": arguments.max_output_tokens,
        "connect_timeout_s": arguments.connect_timeout_s,
        "read_timeout_s": arguments.read_timeout_s,
        "request_timeout_s": arguments.request_timeout_s,
        "max_response_bytes": arguments.max_response_bytes,
        "base_seed": arguments.base_seed,
        "samples_per_task": arguments.samples,
        "maximum_model_processes": len(task_records) * arguments.samples,
        "maximum_model_calls": len(task_records) * arguments.samples,
        "allow_retry": False,
        "allow_best_of_k_selection": False,
        "auth_semantic_id": _AUTH_SEMANTIC_ID,
        "model_policy_hash": _model_policy_hash(arguments),
        "credential_environment_names": [arguments.api_key_env],
        "base_url_environment_name": arguments.base_url_env,
        "credential_values_persisted_or_hashed": False,
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
    infrastructure_invalid = False
    for source, task_record in loaded_tasks:
        task_id = task_record["task_id"]
        task_hash = task_record["task_hash"]
        source_hash = task_record["source_hash"]
        if (
            not isinstance(task_id, str)
            or not isinstance(task_hash, str)
            or not isinstance(source_hash, str)
        ):
            raise AssertionError("validated task record lacks string identities")
        for sample_index in range(arguments.samples):
            run_id = _safe_run_id(index, task_id, sample_index)
            agent_options: dict[str, JsonValue] = {
                "action_plan_protocol": arguments.action_plan_protocol,
                "max_output_tokens": arguments.max_output_tokens,
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
                task_id=task_id,
                suite_source=source,
                expected_task_hash=task_hash,
                expected_source_hash=source_hash,
                mode=InteractionMode.AGENT,
                agent="api-repository-agent",
                agent_options=agent_options,
                model="openai-compatible",
                model_options=model_options.model_copy(update={"sample_index": sample_index}),
                runtime="docker",
                docker_config=runtime,
                seed=arguments.base_seed + index,
                sample_index=sample_index,
                output=runs_root,
                run_id=run_id,
                experiment_id=(
                    "api-repository-heldout-v1"
                    if heldout is not None
                    else "api-repository-training-v1"
                ),
                plan_item_id=f"sample-{index:04d}",
                system_id=(
                    "deepseek-frozen-heldout-agent"
                    if heldout is not None
                    else "api-repository-sampler"
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
