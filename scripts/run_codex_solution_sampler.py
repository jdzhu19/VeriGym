#!/usr/bin/env python3
"""Sample one bounded Codex solution, then verify it in an isolated VeriGym runtime."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from verigym.agents.base import AgentAdapter, AgentContext
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.experiments.state import atomic_dump_json
from verigym.registry.collections import build_registries
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    EpisodeResult,
    FinalSubmissionAction,
    Observation,
)
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor, InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_OPT_IN_ENV = "VERIGYM_RUN_CODEX_SOLUTION_SAMPLER"
_CAPABILITY_ENV = "VERIGYM_CODEX_CAPABILITY_FILE"
_CODEX_BINARY_ENV = "VERIGYM_CODEX_BINARY"


class _CandidateSubmitter(AgentAdapter):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="sampled-candidate-submitter",
        version="1.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-training-reference",
        capabilities=["deterministic", "offline_sample_submission"],
    )
    supported_modes: ClassVar[frozenset[InteractionMode]] = frozenset({InteractionMode.AGENT})

    def __init__(self, patch: str) -> None:
        self._patch = patch
        self._index = 0

    def start(self, context: AgentContext) -> None:
        self._index = 0

    def act(self, observation: Observation) -> AgentAction:
        if self._index == 0:
            self._index += 1
            return ApplyPatchAction(patch=self._patch)
        return FinalSubmissionAction(message="Submit hash-bound offline Codex sample.")

    def finish(self, result: EpisodeResult) -> None:
        return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a public-task Codex solution sample and isolated VeriGym verification."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--reasoning-effort", choices=("xhigh", "max"), default="max")
    parser.add_argument("--model-timeout-s", type=int, default=900)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--verifier-image", required=True)
    parser.add_argument("--verifier-image-id", required=True)
    return parser


def _new_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        raise SystemExit(f"sampling output already exists: {expanded}")
    expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _regular_file_from_env(name: str) -> Path:
    raw = os.environ.get(name)
    if not raw:
        raise SystemExit(f"set {name}")
    path = Path(raw).expanduser().resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"{name} must name a regular file")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timeout_text(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _candidate_patch(path: str, before: str, after: str) -> str:
    if before == after:
        raise SystemExit("Codex returned the unchanged candidate skeleton")
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _prompt(task_description: str, readme: str, candidate_path: str, skeleton: str) -> str:
    return f"""You are producing one RTL training candidate for an authorized benchmark task.
Do not call tools or inspect the filesystem. Use only the public task material below.
Return the exact JSON object required by the supplied output schema. The value for
`{candidate_path}` must be the complete Verilog source, with no Markdown fences or commentary.

TASK DESCRIPTION
{task_description}

PUBLIC README
{readme}

CURRENT INCOMPLETE CANDIDATE ({candidate_path})
{skeleton}
"""


def _schema(candidate_path: str) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "files": {
                "type": "object",
                "properties": {candidate_path: {"type": "string", "minLength": 1}},
                "required": [candidate_path],
                "additionalProperties": False,
            }
        },
        "required": ["files"],
        "additionalProperties": False,
    }


def _verifier_runtime(arguments: argparse.Namespace) -> DockerRuntimeConfig:
    if os.getuid() == 0:
        raise SystemExit("Docker verification requires a non-root host identity")
    return DockerRuntimeConfig(
        image=arguments.verifier_image,
        expected_image_id=arguments.verifier_image_id,
        pull_policy="never",
        network_mode="none",
        run_as_user=f"{os.getuid()}:{os.getgid()}",
        read_only_rootfs=True,
        memory_bytes=512 * 1024 * 1024,
        cpus=1.0,
        pids_limit=128,
        tmpfs_bytes=64 * 1024 * 1024,
        stop_timeout_s=3,
        max_command_time_s=120,
        environment_allowlist=[],
    )


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    if os.environ.get(_OPT_IN_ENV) != "1":
        raise SystemExit(f"{_OPT_IN_ENV}=1 is required")
    if not 1 <= arguments.model_timeout_s <= 1800:
        raise SystemExit("--model-timeout-s must be in [1, 1800]")
    capability_path = _regular_file_from_env(_CAPABILITY_ENV)
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    codex = _regular_file_from_env(_CODEX_BINARY_ENV)
    if _sha256_file(codex) != capability["executable_sha256"]:
        raise SystemExit("Codex executable hash differs from the capability record")

    root = _new_root(arguments.output)
    source = SuiteSourceConfig(
        source_root=arguments.source.expanduser().resolve(strict=True),
        variant=arguments.variant,
    )
    registries = build_registries()
    service = VeriGym(registries)
    suite, task, assets = service.load_task(arguments.task, source)
    snapshot = suite.source_snapshot()
    if snapshot is None:
        raise SystemExit("offline solution sampling requires a frozen source snapshot")
    if task.interaction.final_submission.kind != "file":
        raise SystemExit("offline solution sampling requires a single-file submission task")
    candidate_path = task.interaction.final_submission.path
    if candidate_path is None:
        raise SystemExit("task final submission path is missing")
    visible_root = Path(assets.visible_root)
    skeleton = (visible_root / candidate_path).read_text(encoding="utf-8")
    readme_path = visible_root / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""

    public_input: dict[str, object] = {
        "schema_version": "1.0",
        "task_id": task.id,
        "task_hash": content_hash(task),
        "source_hash": task.source.content_hash or snapshot.content_hash,
        "candidate_path": candidate_path,
        "task_description": task.description,
        "public_readme": readme,
        "candidate_skeleton": skeleton,
        "hidden_assets_included": False,
    }
    public_input["record_hash"] = content_hash(public_input)
    atomic_dump_json(root / "public-input.json", public_input)

    schema_path = root / "output-schema.json"
    response_path = root / "codex-final.json"
    atomic_dump_json(schema_path, _schema(candidate_path))
    command = [
        str(codex),
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        arguments.model_id,
        "--config",
        f'model_reasoning_effort="{arguments.reasoning_effort}"',
        "--config",
        'approval_policy="never"',
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(response_path),
        "--json",
        "-",
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            input=_prompt(task.description, readme, candidate_path, skeleton),
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=arguments.model_timeout_s,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(
            command,
            124,
            stdout=_timeout_text(exc.stdout),
            stderr=_timeout_text(exc.stderr),
        )
        timed_out = True
    duration_s = time.monotonic() - started
    model_record: dict[str, object] = {
        "schema_version": "1.0",
        "execution_surface": "codex_cli_exec",
        "requested_model_id": arguments.model_id,
        "requested_reasoning_effort": arguments.reasoning_effort,
        "cli_version": capability["version_output"],
        "executable_sha256": capability["executable_sha256"],
        "capability_fingerprint": capability["capability_fingerprint"],
        "public_input_hash": public_input["record_hash"],
        "sandbox": "read-only",
        "approval_policy": "never",
        "ephemeral": True,
        "return_code": completed.returncode,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
    }
    model_record["record_hash"] = content_hash(model_record)
    atomic_dump_json(root / "model-call.json", model_record)
    if completed.returncode != 0 or not response_path.is_file():
        raise SystemExit("Codex solution sampling failed; see model-call.json hashes")

    response = json.loads(response_path.read_text(encoding="utf-8"))
    files = response.get("files")
    if not isinstance(files, dict) or set(files) != {candidate_path}:
        raise SystemExit("Codex response does not match the exact candidate path")
    candidate = files[candidate_path]
    if not isinstance(candidate, str) or not candidate.strip():
        raise SystemExit("Codex returned an empty candidate")
    candidate_hash = hashlib.sha256(candidate.encode()).hexdigest()
    patch = _candidate_patch(candidate_path, skeleton, candidate)

    submitter = _CandidateSubmitter(patch)
    registries.agents.register(submitter)
    run_config = RunConfig(
        task_id=task.id,
        suite_source=source,
        expected_task_hash=content_hash(task),
        expected_source_hash=task.source.content_hash or snapshot.content_hash,
        mode=InteractionMode.AGENT,
        agent=submitter.descriptor.name,
        runtime="docker",
        docker_config=_verifier_runtime(arguments),
        seed=arguments.seed,
        sample_index=0,
        output=root / "runs",
        run_id="codex-offline-sample-000",
        experiment_id="codex-offline-solution-sampler-v1",
        plan_item_id="sample-0000",
        system_id="codex-strong-solution-sampler",
        base_seed=arguments.seed,
    )
    result = service.run(run_config)
    infrastructure_invalid = bool(
        result.scorecard.status == "error"
        or result.scorecard.correctness.infrastructure_error
        or (result.scorecard.failure is not None and result.scorecard.failure.infrastructure)
    )
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "task_id": task.id,
        "task_hash": content_hash(task),
        "source_hash": task.source.content_hash or snapshot.content_hash,
        "model_call_hash": model_record["record_hash"],
        "public_input_hash": public_input["record_hash"],
        "requested_model_id": arguments.model_id,
        "requested_reasoning_effort": arguments.reasoning_effort,
        "candidate_path": candidate_path,
        "candidate_hash": candidate_hash,
        "verigym_candidate_hash": result.scorecard.reproducibility.candidate_hash,
        "run_dir": result.run_dir.relative_to(root).as_posix(),
        "resolved": result.scorecard.resolved,
        "infrastructure_invalid": infrastructure_invalid,
    }
    summary["summary_hash"] = content_hash(summary)
    atomic_dump_json(root / "sampling-summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    summary = _run(_parser().parse_args(argv))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["resolved"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
