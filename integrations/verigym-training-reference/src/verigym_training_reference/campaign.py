"""Fail-closed, resumable command campaigns for external training stacks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import tempfile
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_ENV_REFERENCE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_SECRET_NAME = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
_BASE_ENV_NAMES = {
    "CUDA_HOME",
    "HOME",
    "LANG",
    "LC_ALL",
    "LD_LIBRARY_PATH",
    "LOGNAME",
    "PATH",
    "PYTHONPATH",
    "USER",
    "VIRTUAL_ENV",
}


class CampaignStageSpec(StrictModel):
    """One shell-free stage with hash-bound outputs and bounded retries."""

    stage_id: str
    argv: list[str] = Field(min_length=1, max_length=256)
    depends_on: list[str] = Field(default_factory=list, max_length=128)
    expected_outputs: list[str] = Field(min_length=1, max_length=128)
    working_directory: Literal["repository", "workspace"] = "repository"
    environment: dict[str, str] = Field(default_factory=dict, max_length=64)
    gpu_ids: list[int] = Field(default_factory=list, max_length=8)
    timeout_s: int = Field(default=3600, ge=1, le=604_800)
    max_attempts: int = Field(default=1, ge=1, le=20)
    retry_exit_codes: list[int] = Field(default_factory=list, max_length=32)
    fatal_log_markers: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("stage_id")
    @classmethod
    def validate_stage_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("campaign stage IDs must use the safe identifier vocabulary")
        return value

    @field_validator("expected_outputs")
    @classmethod
    def validate_outputs(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("campaign stage outputs must be unique")
        for value in values:
            path = Path(value)
            if path.is_absolute() or not value or ".." in path.parts:
                raise ValueError("campaign outputs must be workspace-relative paths")
        return values

    @field_validator("gpu_ids")
    @classmethod
    def validate_gpu_ids(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)) or any(value < 0 for value in values):
            raise ValueError("campaign GPU IDs must be unique nonnegative integers")
        return values

    @field_validator("fatal_log_markers")
    @classmethod
    def validate_fatal_log_markers(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("campaign fatal log markers must be unique")
        invalid = (
            not value or len(value) > 256 or "\n" in value or "\x00" in value for value in values
        )
        if any(invalid):
            raise ValueError("campaign fatal log markers must be 1-256 single-line characters")
        return values

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, values: dict[str, str]) -> dict[str, str]:
        for name, value in values.items():
            if not name.isidentifier() or name.upper() != name or _SECRET_NAME.search(name):
                raise ValueError("campaign environment cannot contain credential-like names")
            if "\x00" in value:
                raise ValueError("campaign environment values cannot contain NUL")
        return values


class TrainingCampaignSpec(StrictModel):
    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_external_training_campaign_v1"]
    campaign_id: str
    stages: list[CampaignStageSpec] = Field(min_length=1, max_length=512)
    max_parallel_stages: int = Field(default=1, ge=1, le=32)
    max_workspace_bytes: int = Field(default=100 * 1024**3, ge=1)

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("campaign IDs must use the safe identifier vocabulary")
        return value

    @model_validator(mode="after")
    def validate_graph(self) -> TrainingCampaignSpec:
        identifiers = [stage.stage_id for stage in self.stages]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("campaign stage IDs must be unique")
        known = set(identifiers)
        graph = {stage.stage_id: set(stage.depends_on) for stage in self.stages}
        if any(stage_id in dependencies for stage_id, dependencies in graph.items()):
            raise ValueError("campaign stages cannot depend on themselves")
        missing = set().union(*graph.values()) - known
        if missing:
            raise ValueError(f"campaign dependencies are unknown: {sorted(missing)}")
        try:
            tuple(TopologicalSorter(graph).static_order())
        except CycleError as exc:
            raise ValueError("campaign dependency graph contains a cycle") from exc
        claimed: dict[str, str] = {}
        for stage in self.stages:
            for output in stage.expected_outputs:
                if output in claimed:
                    raise ValueError("campaign outputs must have exactly one producing stage")
                claimed[output] = stage.stage_id
        return self


@dataclass(frozen=True)
class StageExecution:
    stage_id: str
    receipt: dict[str, object]
    succeeded: bool
    error: str | None = None


def load_campaign_spec(path: Path) -> TrainingCampaignSpec:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("training campaign configuration is not valid JSON") from exc
    return TrainingCampaignSpec.model_validate(value)


def _expand(value: str, environment: Mapping[str, str]) -> str:
    names = _ENV_REFERENCE.findall(value)
    for name in names:
        if _SECRET_NAME.search(name):
            raise ConfigurationError("campaign commands cannot interpolate credentials")
        if name not in environment:
            raise ConfigurationError(f"campaign environment variable is unavailable: {name}")
    return _ENV_REFERENCE.sub(lambda match: environment[match.group(1)], value)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_identity(path: Path) -> dict[str, object]:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode):
        raise ConfigurationError("campaign outputs cannot be symlinks")
    if stat.S_ISREG(metadata.st_mode):
        return {"kind": "file", "size_bytes": metadata.st_size, "sha256": _file_hash(path)}
    if not stat.S_ISDIR(metadata.st_mode):
        raise ConfigurationError("campaign output must be a regular file or directory")
    inventory: list[dict[str, object]] = []
    for child in sorted(path.rglob("*")):
        child_metadata = os.lstat(child)
        if stat.S_ISLNK(child_metadata.st_mode):
            raise ConfigurationError("campaign output directories cannot contain symlinks")
        if stat.S_ISREG(child_metadata.st_mode):
            inventory.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "size_bytes": child_metadata.st_size,
                    "sha256": _file_hash(child),
                }
            )
        elif not stat.S_ISDIR(child_metadata.st_mode):
            raise ConfigurationError("campaign output contains a special filesystem entry")
    return {
        "kind": "directory",
        "file_count": len(inventory),
        "size_bytes": sum(
            value for item in inventory if isinstance((value := item["size_bytes"]), int)
        ),
        "inventory_hash": content_hash(inventory),
    }


def _workspace_size(root: Path) -> int:
    size = 0
    for path in root.rglob("*"):
        if path.relative_to(root).parts[0] == ".campaign":
            continue
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise ConfigurationError("campaign workspace cannot contain symlinks")
        if stat.S_ISREG(metadata.st_mode):
            size += metadata.st_size
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ConfigurationError("campaign workspace contains a special filesystem entry")
    return size


def _safe_environment(stage: CampaignStageSpec, host: Mapping[str, str]) -> dict[str, str]:
    environment = {name: host[name] for name in _BASE_ENV_NAMES if name in host}
    for name, value in stage.environment.items():
        environment[name] = _expand(value, host)
    if stage.gpu_ids:
        environment["CUDA_VISIBLE_DEVICES"] = ",".join(str(value) for value in stage.gpu_ids)
    return environment


def _find_new_fatal_log_marker(
    paths: tuple[Path, ...],
    markers: tuple[bytes, ...],
    offsets: dict[Path, int],
    tails: dict[Path, bytes],
) -> bytes | None:
    if not markers:
        return None
    tail_size = max(len(marker) for marker in markers) - 1
    for path in paths:
        with path.open("rb") as stream:
            stream.seek(offsets.get(path, 0))
            chunk = stream.read()
            offsets[path] = stream.tell()
        value = tails.get(path, b"") + chunk
        for marker in markers:
            if marker in value:
                return marker
        tails[path] = value[-tail_size:] if tail_size else b""
    return None


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def _dump_heartbeat(path: Path, value: dict[str, object]) -> None:
    """Atomically publish ephemeral liveness state without forcing a disk journal commit."""

    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _receipt_matches(receipt: dict[str, object], workspace: Path, stage_hash: str) -> bool:
    if receipt.get("status") != "completed" or receipt.get("stage_hash") != stage_hash:
        return False
    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict):
        return False
    for relative, expected in outputs.items():
        if not isinstance(relative, str) or not isinstance(expected, dict):
            return False
        path = workspace / relative
        if not path.exists() or _artifact_identity(path) != expected:
            raise ConfigurationError(f"completed campaign output changed: {relative}")
    return True


def _execute_stage(
    *,
    stage: CampaignStageSpec,
    workspace: Path,
    repository: Path,
    host_environment: Mapping[str, str],
    stage_hash: str,
) -> StageExecution:
    logs = workspace / ".campaign" / "logs" / stage.stage_id
    logs.mkdir(parents=True, exist_ok=True)
    state_path = workspace / ".campaign" / "states" / f"{stage.stage_id}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    context = {
        **host_environment,
        "VERIGYM_CAMPAIGN_WORKSPACE": str(workspace),
        "VERIGYM_REPOSITORY_ROOT": str(repository),
    }
    environment = _safe_environment(stage, context)
    environment["VERIGYM_CAMPAIGN_WORKSPACE"] = str(workspace)
    environment["VERIGYM_REPOSITORY_ROOT"] = str(repository)
    for name in ("RAY_TMPDIR", "RLLM_HOME", "TMPDIR"):
        value = environment.get(name)
        if value is None:
            continue
        directory = Path(value)
        try:
            directory.relative_to(workspace)
        except ValueError as exc:
            raise ConfigurationError(f"campaign {name} must remain under its workspace") from exc
        directory.mkdir(parents=True, exist_ok=True)
    argv = [_expand(value, context) for value in stage.argv]
    cwd = repository if stage.working_directory == "repository" else workspace
    started = time.monotonic()
    final_code: int | None = None
    for attempt in range(1, stage.max_attempts + 1):
        fatal_marker: str | None = None
        stdout_path = logs / f"attempt-{attempt:02d}.stdout.log"
        stderr_path = logs / f"attempt-{attempt:02d}.stderr.log"
        with (
            stdout_path.open("w", encoding="utf-8") as stdout,
            stderr_path.open("w", encoding="utf-8") as stderr,
        ):
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                text=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + stage.timeout_s
            next_heartbeat = 0.0
            timed_out = False
            encoded_markers = tuple(value.encode("utf-8") for value in stage.fatal_log_markers)
            log_offsets: dict[Path, int] = {}
            log_tails: dict[Path, bytes] = {}
            while True:
                now = time.monotonic()
                polled_code = process.poll()
                if polled_code is not None:
                    final_code = polled_code
                    break
                matched = _find_new_fatal_log_marker(
                    (stdout_path, stderr_path), encoded_markers, log_offsets, log_tails
                )
                if matched is not None:
                    fatal_marker = matched.decode("utf-8")
                    _terminate_process_group(process)
                    final_code = process.returncode
                    break
                if now >= deadline:
                    timed_out = True
                    final_code = None
                    _terminate_process_group(process)
                    break
                if now >= next_heartbeat:
                    _dump_heartbeat(
                        state_path,
                        {
                            "format_id": "verigym_training_campaign_stage_state_v1",
                            "stage_id": stage.stage_id,
                            "status": "running",
                            "attempt": attempt,
                            "pid": process.pid,
                            "elapsed_s": now - started,
                            "updated_at_unix_s": time.time(),
                        },
                    )
                    next_heartbeat = now + 5.0
                time.sleep(min(1.0, max(0.05, deadline - now)))
            atomic_dump_json(
                state_path,
                {
                    "format_id": "verigym_training_campaign_stage_state_v1",
                    "stage_id": stage.stage_id,
                    "status": (
                        "fatal_log" if fatal_marker else "timed_out" if timed_out else "exited"
                    ),
                    "attempt": attempt,
                    "pid": process.pid,
                    "exit_code": final_code,
                    **({"fatal_log_marker": fatal_marker} if fatal_marker else {}),
                    "elapsed_s": time.monotonic() - started,
                    "updated_at_unix_s": time.time(),
                },
            )
        success = final_code == 0
        retryable = final_code is None or final_code in stage.retry_exit_codes
        if success:
            break
        if attempt == stage.max_attempts or not retryable:
            base: dict[str, object] = {
                "schema_version": "1.0",
                "format_id": "verigym_training_campaign_stage_receipt_v1",
                "stage_id": stage.stage_id,
                "stage_hash": stage_hash,
                "status": "failed",
                "attempt_count": attempt,
                "exit_code": final_code,
                "duration_s": time.monotonic() - started,
                "outputs": {},
                **({"failure_reason": "fatal_log_marker"} if fatal_marker else {}),
                **({"fatal_log_marker": fatal_marker} if fatal_marker else {}),
            }
            receipt = {**base, "receipt_hash": content_hash(base)}
            atomic_dump_json(
                state_path,
                {
                    "format_id": "verigym_training_campaign_stage_state_v1",
                    "stage_id": stage.stage_id,
                    "status": "failed",
                    "attempt": attempt,
                    "exit_code": final_code,
                    **({"failure_reason": "fatal_log_marker"} if fatal_marker else {}),
                    **({"fatal_log_marker": fatal_marker} if fatal_marker else {}),
                    "elapsed_s": time.monotonic() - started,
                    "updated_at_unix_s": time.time(),
                },
            )
            error = "fatal log marker detected" if fatal_marker else "stage command failed"
            return StageExecution(stage.stage_id, receipt, False, error)

    outputs: dict[str, object] = {}
    for relative in stage.expected_outputs:
        path = workspace / relative
        if not path.exists():
            base = {
                "schema_version": "1.0",
                "format_id": "verigym_training_campaign_stage_receipt_v1",
                "stage_id": stage.stage_id,
                "stage_hash": stage_hash,
                "status": "failed",
                "attempt_count": attempt,
                "exit_code": final_code,
                "duration_s": time.monotonic() - started,
                "outputs": outputs,
            }
            receipt = {**base, "receipt_hash": content_hash(base)}
            atomic_dump_json(
                state_path,
                {
                    "format_id": "verigym_training_campaign_stage_state_v1",
                    "stage_id": stage.stage_id,
                    "status": "failed",
                    "attempt": attempt,
                    "exit_code": final_code,
                    "error": f"missing output: {relative}",
                    "elapsed_s": time.monotonic() - started,
                    "updated_at_unix_s": time.time(),
                },
            )
            return StageExecution(stage.stage_id, receipt, False, f"missing output: {relative}")
        outputs[relative] = _artifact_identity(path)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_training_campaign_stage_receipt_v1",
        "stage_id": stage.stage_id,
        "stage_hash": stage_hash,
        "status": "completed",
        "attempt_count": attempt,
        "exit_code": final_code,
        "duration_s": time.monotonic() - started,
        "outputs": outputs,
    }
    receipt = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(
        state_path,
        {
            "format_id": "verigym_training_campaign_stage_state_v1",
            "stage_id": stage.stage_id,
            "status": "completed",
            "attempt": attempt,
            "exit_code": final_code,
            "elapsed_s": time.monotonic() - started,
            "updated_at_unix_s": time.time(),
        },
    )
    return StageExecution(stage.stage_id, receipt, True)


def run_training_campaign(
    *,
    spec: TrainingCampaignSpec,
    workspace: Path,
    repository: Path,
    host_environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Execute ready stages in GPU-disjoint waves and resume from sealed receipts."""

    workspace = workspace.expanduser()
    if workspace.exists():
        if workspace.is_symlink() or not workspace.is_dir():
            raise ConfigurationError("campaign workspace must be a real directory")
    else:
        workspace.mkdir(parents=True)
    repository = repository.resolve(strict=True)
    control = workspace / ".campaign"
    receipts_root = control / "receipts"
    receipts_root.mkdir(parents=True, exist_ok=True)
    config_hash = content_hash(spec.model_dump(mode="json"))
    host = dict(os.environ if host_environment is None else host_environment)
    stages = {stage.stage_id: stage for stage in spec.stages}
    stage_hashes = {
        stage_id: content_hash(
            {"campaign_config_hash": config_hash, "stage": stage.model_dump(mode="json")}
        )
        for stage_id, stage in stages.items()
    }
    completed: set[str] = set()
    receipts: dict[str, dict[str, object]] = {}
    for stage_id in stages:
        receipt_path = receipts_root / f"{stage_id}.json"
        if not receipt_path.exists():
            continue
        value = json.loads(receipt_path.read_text(encoding="utf-8"))
        if _receipt_matches(value, workspace, stage_hashes[stage_id]):
            completed.add(stage_id)
            receipts[stage_id] = value
    pending = set(stages) - completed
    while pending:
        ready = sorted(
            stage_id for stage_id in pending if set(stages[stage_id].depends_on).issubset(completed)
        )
        if not ready:
            raise ConfigurationError("campaign has no runnable stages")
        selected: list[str] = []
        claimed_gpus: set[int] = set()
        for stage_id in ready:
            gpu_ids = set(stages[stage_id].gpu_ids)
            if gpu_ids.isdisjoint(claimed_gpus):
                selected.append(stage_id)
                claimed_gpus.update(gpu_ids)
            if len(selected) == spec.max_parallel_stages:
                break
        with ThreadPoolExecutor(max_workers=len(selected)) as executor:
            futures = {
                stage_id: executor.submit(
                    _execute_stage,
                    stage=stages[stage_id],
                    workspace=workspace,
                    repository=repository,
                    host_environment=host,
                    stage_hash=stage_hashes[stage_id],
                )
                for stage_id in selected
            }
            executions = [futures[stage_id].result() for stage_id in selected]
        for execution in executions:
            atomic_dump_json(receipts_root / f"{execution.stage_id}.json", execution.receipt)
            receipts[execution.stage_id] = execution.receipt
            if not execution.succeeded:
                raise ConfigurationError(
                    f"campaign stage {execution.stage_id!r} failed: {execution.error}"
                )
            completed.add(execution.stage_id)
            pending.remove(execution.stage_id)
        if _workspace_size(workspace) > spec.max_workspace_bytes:
            raise ConfigurationError("campaign workspace exceeded its byte quota")
    ordered_receipts = [receipts[stage.stage_id] for stage in spec.stages]
    base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "verigym_external_training_campaign_report_v1",
        "campaign_id": spec.campaign_id,
        "campaign_config_hash": config_hash,
        "status": "completed",
        "stage_count": len(spec.stages),
        "stage_receipt_hashes": [receipt["receipt_hash"] for receipt in ordered_receipts],
        "workspace_size_bytes": _workspace_size(workspace),
        "credential_environment_inherited": False,
        "shell_commands_used": False,
    }
    report = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(control / "campaign-report.json", report)
    return report


__all__ = [
    "CampaignStageSpec",
    "TrainingCampaignSpec",
    "load_campaign_spec",
    "run_training_campaign",
]
