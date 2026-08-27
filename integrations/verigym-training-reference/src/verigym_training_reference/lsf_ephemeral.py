"""Shell-free LSF submission for bounded, self-terminating GPU commands."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from verigym.experiments.state import atomic_dump_json

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SUBMITTED_JOB = re.compile(r"^Job <([1-9][0-9]*)> is submitted", re.MULTILINE)
_SHELL_EXECUTABLES = frozenset({"bash", "csh", "dash", "fish", "ksh", "sh", "tcsh", "zsh"})


@dataclass(frozen=True)
class EphemeralLsfGpuRequest:
    """One non-interactive LSF GPU command that exits with its payload."""

    job_name: str
    queue: str
    gpu_count: int
    cpu_slots: int
    wall_minutes: int
    working_directory: Path
    output_directory: Path
    command: tuple[str, ...]

    def validate(self) -> None:
        if not _SAFE_NAME.fullmatch(self.job_name) or not _SAFE_NAME.fullmatch(self.queue):
            raise ValueError("LSF job name and queue must use bounded safe characters")
        if not 1 <= self.gpu_count <= 8:
            raise ValueError("ephemeral LSF GPU count must be between 1 and 8")
        if not self.gpu_count <= self.cpu_slots <= 256:
            raise ValueError("ephemeral LSF CPU slots must cover GPUs and remain bounded")
        if not 1 <= self.wall_minutes <= 24 * 60:
            raise ValueError("ephemeral LSF wall time must be between one minute and one day")
        if not self.working_directory.is_absolute() or not self.output_directory.is_absolute():
            raise ValueError("ephemeral LSF working and output directories must be absolute")
        if "experiments" not in self.output_directory.parts:
            raise ValueError("ephemeral LSF logs and receipts must be stored under experiments")
        _existing_directory(self.working_directory, label="working directory")
        if not self.command or any(
            not item or "\x00" in item or "\n" in item for item in self.command
        ):
            raise ValueError("ephemeral LSF command is empty or malformed")
        executable = Path(self.command[0]).name.lower()
        if executable in _SHELL_EXECUTABLES:
            raise ValueError("persistent or command-carrying shell jobs are forbidden")
        if any(item in {"-I", "-Ip", "-Is"} for item in self.command):
            raise ValueError("interactive LSF payload arguments are forbidden")


def build_bsub_command(request: EphemeralLsfGpuRequest) -> list[str]:
    """Build an argv-only bsub call; the payload is never wrapped in bash."""

    request.validate()
    output = request.output_directory.absolute()
    hours, minutes = divmod(request.wall_minutes, 60)
    wall = f"{hours:02d}:{minutes:02d}"
    gpu = f"num={request.gpu_count}:mode=shared:mps=no:j_exclusive=yes:gvendor=nvidia"
    return [
        "bsub",
        "-q",
        request.queue,
        "-J",
        request.job_name,
        "-n",
        str(request.cpu_slots),
        "-gpu",
        gpu,
        "-R",
        "span[hosts=1]",
        "-W",
        wall,
        "-cwd",
        str(request.working_directory.resolve(strict=True)),
        "-oo",
        str(output / "%J.stdout.log"),
        "-eo",
        str(output / "%J.stderr.log"),
        *request.command,
    ]


def submit_ephemeral_lsf_gpu_job(request: EphemeralLsfGpuRequest) -> dict[str, object]:
    """Submit one job and write a secret-free receipt beside its scheduler logs."""

    request.validate()
    output = _new_directory(request.output_directory)
    command = build_bsub_command(request)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("failed to invoke the LSF submission client") from exc
    if result.returncode != 0:
        raise RuntimeError(f"LSF rejected the ephemeral GPU job (return code {result.returncode})")
    match = _SUBMITTED_JOB.search(result.stdout)
    if match is None:
        raise RuntimeError("LSF submission succeeded without a parseable job identity")
    job_id = match.group(1)
    receipt: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "verigym_ephemeral_lsf_gpu_submission_v1",
        "status": "submitted",
        "job_id": job_id,
        "job_name": request.job_name,
        "queue": request.queue,
        "gpu_count": request.gpu_count,
        "cpu_slots": request.cpu_slots,
        "wall_minutes": request.wall_minutes,
        "gpu_requirement": (
            f"num={request.gpu_count}:mode=shared:mps=no:j_exclusive=yes:gvendor=nvidia"
        ),
        "span_requirement": "span[hosts=1]",
        "working_directory": str(request.working_directory.resolve(strict=True)),
        "stdout_log": str(output / f"{job_id}.stdout.log"),
        "stderr_log": str(output / f"{job_id}.stderr.log"),
        "payload_executable": Path(request.command[0]).name,
        "payload_argument_count": len(request.command) - 1,
        "payload_arguments_persisted": False,
        "interactive": False,
        "shell_payload": False,
        "persistent_allocation": False,
        "auto_exit_on_payload_completion": True,
    }
    atomic_dump_json(output / "lsf-submission-receipt.json", receipt)
    return receipt


def request_from_values(
    *,
    job_name: str,
    queue: str,
    gpu_count: int,
    cpu_slots: int,
    wall_minutes: int,
    working_directory: Path,
    output_directory: Path,
    command: Sequence[str],
) -> EphemeralLsfGpuRequest:
    """Normalize CLI-style values into an immutable validated request."""

    request = EphemeralLsfGpuRequest(
        job_name=job_name,
        queue=queue,
        gpu_count=gpu_count,
        cpu_slots=cpu_slots,
        wall_minutes=wall_minutes,
        working_directory=working_directory,
        output_directory=output_directory,
        command=tuple(command),
    )
    request.validate()
    return request


def _existing_directory(path: Path, *, label: str) -> Path:
    metadata = os.lstat(path)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"LSF {label} must be a real directory")
    return path.resolve(strict=True)


def _new_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ValueError("LSF output directory must not already exist")
    parent = _existing_directory(path.parent, label="output parent")
    destination = parent / path.name
    destination.mkdir(mode=0o700)
    return destination


__all__ = [
    "EphemeralLsfGpuRequest",
    "build_bsub_command",
    "request_from_values",
    "submit_ephemeral_lsf_gpu_job",
]
