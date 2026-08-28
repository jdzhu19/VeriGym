"""One-shot DC worker and LSF launcher for agent-visible candidate feedback."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import verigym
from pydantic import ValidationError
from verigym.plugin_api import content_hash, hash_bytes

from .agent_worker_protocol import (
    AGENT_WORKER_PROTOCOL,
    AgentWorkerDescribeResponse,
    AgentWorkerEnvelope,
    AgentWorkerIsolationContract,
    AgentWorkerLaunchRequest,
    AgentWorkerReceipt,
)
from .mcp_server import (
    SERVICE_PROTOCOL,
    DesignCompilerMcpService,
    McpSynthesisRequest,
)

LAUNCHER_VERSION = "0.1.0"
_MAX_MESSAGE_BYTES = 48 * 1024 * 1024
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_QUEUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_JOB_ID = re.compile(r"Job <([0-9]+)>")
_MAX_CODE_FILES = 4096
_MAX_CODE_BYTES = 128 * 1024 * 1024


def _read_request() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(_MAX_MESSAGE_BYTES + 1)
    if len(raw) > _MAX_MESSAGE_BYTES:
        raise ValueError("worker request exceeds the byte bound")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("worker request is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("worker request must be one JSON object")
    return payload


def _write_response(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_RESPONSE_BYTES:
        raise ValueError("worker response exceeds the byte bound")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


def _regular_executable(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    metadata = os.lstat(resolved)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular non-symlink executable")
    if not os.access(resolved, os.X_OK):
        raise ValueError(f"{label} is not executable")
    return resolved


def _dedicated_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError("worker root cannot be a symlink")
    expanded.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = expanded.resolve(strict=True)
    if resolved == Path("/") or not resolved.is_dir():
        raise ValueError("worker root must be a dedicated directory")
    return resolved


def _source_tree_hash(root: Path) -> str:
    records: list[dict[str, Any]] = []
    total = 0
    for path in sorted(root.rglob("*.py")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("worker code identity contains a non-regular Python source")
        payload = path.read_bytes()
        total += len(payload)
        if len(records) >= _MAX_CODE_FILES or total > _MAX_CODE_BYTES:
            raise ValueError("worker code identity exceeds its source-tree bound")
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hash_bytes(payload),
            }
        )
    if not records:
        raise ValueError("worker code identity contains no Python sources")
    return content_hash(records)


def _worker_code_identity() -> str:
    core_file = getattr(verigym, "__file__", None)
    if not isinstance(core_file, str):
        raise ValueError("VeriGym core package has no hashable source identity")
    return content_hash(
        {
            "verigym": _source_tree_hash(Path(core_file).resolve(strict=True).parent),
            "verigym_synopsys": _source_tree_hash(Path(__file__).resolve(strict=True).parent),
        }
    )


def _cleanup_run_dir(run_dir: Path, root: Path) -> None:
    if run_dir.parent != root or not run_dir.name.startswith("verigym-dc-agent-"):
        raise RuntimeError("refusing to clean an unexpected worker path")
    deadline = time.monotonic() + 15
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if run_dir.exists():
            if run_dir.is_symlink():
                raise RuntimeError("refusing to clean a symlinked worker path")
            try:
                shutil.rmtree(run_dir, ignore_errors=False)
            except OSError:
                time.sleep(0.1)
                continue
            stable_since = None
        else:
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= 1:
                return
        time.sleep(0.1)
    raise RuntimeError("disposable worker cleanup did not stabilize")


def _launcher_contract(args: argparse.Namespace) -> AgentWorkerIsolationContract:
    python = _regular_executable(args.python_executable, "Python executable")
    bsub = _regular_executable(args.bsub_executable, "LSF bsub executable")
    if _QUEUE.fullmatch(args.queue) is None:
        raise ValueError("LSF queue name is invalid")
    profile_paths = [str(path.expanduser().resolve(strict=True)) for path in args.profile]
    code_identity = _worker_code_identity()
    identity = {
        "launcher_version": LAUNCHER_VERSION,
        "code_identity_hash": code_identity,
        "scheduler": "lsf",
        "queue_hash": content_hash(args.queue),
        "python_sha256": hash_bytes(python.read_bytes()),
        "bsub_sha256": hash_bytes(bsub.read_bytes()),
        "profile_hashes": [hash_bytes(Path(path).read_bytes()) for path in profile_paths],
        "max_wall_seconds": args.max_wall_seconds,
        "memory_mb": args.memory_mb,
        "cores": args.cores,
    }
    return AgentWorkerIsolationContract(
        isolation_kind="lsf_job",
        launcher_version=LAUNCHER_VERSION,
        code_identity_hash=code_identity,
        isolation_profile_hash=content_hash(identity),
        network_policy="site_license_controlled",
        max_wall_seconds=args.max_wall_seconds,
        memory_mb=args.memory_mb,
        cores=args.cores,
    )


def _validate_launch_identity(request: AgentWorkerLaunchRequest) -> McpSynthesisRequest:
    if content_hash(request.synthesis) != request.request_hash:
        raise ValueError("worker synthesis request hash mismatch")
    synthesis = McpSynthesisRequest.model_validate(request.synthesis)
    source_bundle = [{"path": item.path, "sha256": item.sha256} for item in synthesis.sources]
    if content_hash({"top": synthesis.top, "sources": source_bundle}) != (
        request.source_bundle_hash
    ):
        raise ValueError("worker source bundle hash mismatch")
    if synthesis.run_label != "agent_feedback" or synthesis.artifact_content_policy != "none":
        raise ValueError("worker accepts only no-artifact agent feedback requests")
    return synthesis


def inner_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one DC feedback request inside a worker.")
    parser.add_argument("--profile", type=Path, action="append", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if not os.environ.get("LSB_JOBID"):
        raise ValueError("the DC agent worker must run inside an LSF job")
    request = AgentWorkerLaunchRequest.model_validate(_read_request())
    if (
        request.code_identity_hash != _worker_code_identity()
        or os.environ.get("VERIGYM_AGENT_WORKER_ISOLATION_PROFILE_HASH")
        != request.isolation_profile_hash
    ):
        raise ValueError("worker code or isolation identity changed after dispatch")
    synthesis = _validate_launch_identity(request)
    service = DesignCompilerMcpService(args.profile, args.work_root)
    response = service._synthesize_local(synthesis)
    if response.get("protocol") != SERVICE_PROTOCOL or response.get("artifacts") != []:
        raise ValueError("inner worker produced a non-sanitized response")
    _write_response(response)
    return 0


def _job_script(
    *,
    python: Path,
    profiles: list[Path],
    work_root: Path,
    request_path: Path,
    response_path: Path,
    isolation_profile_hash: str,
) -> str:
    profile_args = " ".join(f"--profile {shlex.quote(str(path))}" for path in profiles)
    command = (
        f"{shlex.quote(str(python))} -m verigym_synopsys.agent_worker inner "
        f"{profile_args} --work-root {shlex.quote(str(work_root))} "
        f"< {shlex.quote(str(request_path))} > {shlex.quote(str(response_path))}"
    )
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        "umask 077\n"
        f"export VERIGYM_AGENT_WORKER_ISOLATION_PROFILE_HASH="
        f"{shlex.quote(isolation_profile_hash)}\n"
        f"exec {command}\n"
    )


def _failed_envelope(
    request: AgentWorkerLaunchRequest,
    *,
    dispatch_id_hash: str,
    scheduler_dispatched: bool,
    worker_started: bool,
    duration_s: float,
    category: str,
) -> AgentWorkerEnvelope:
    return AgentWorkerEnvelope(
        success=False,
        failure_category=category,  # type: ignore[arg-type]
        receipt=AgentWorkerReceipt(
            contract_hash=request.contract_hash,
            code_identity_hash=request.code_identity_hash,
            isolation_profile_hash=request.isolation_profile_hash,
            request_hash=request.request_hash,
            source_bundle_hash=request.source_bundle_hash,
            dispatch_id_hash=dispatch_id_hash,
            scheduler_dispatched=scheduler_dispatched,
            worker_started=worker_started,
            worker_completed=False,
            lifecycle="infrastructure_failed_clean",
            duration_s=duration_s,
        ),
    )


def _run_lsf(request: AgentWorkerLaunchRequest, args: argparse.Namespace) -> AgentWorkerEnvelope:
    _validate_launch_identity(request)
    contract = _launcher_contract(args)
    if (
        request.code_identity_hash != contract.code_identity_hash
        or request.isolation_profile_hash != contract.isolation_profile_hash
    ):
        raise ValueError("worker code or isolation identity differs from the resolved contract")
    root = _dedicated_root(args.work_root)
    started = time.monotonic()
    run_dir = Path(tempfile.mkdtemp(prefix="verigym-dc-agent-", dir=root))
    os.chmod(run_dir, 0o700)
    request_path = run_dir / "request.json"
    response_path = run_dir / "response.json"
    job_script = run_dir / "job.sh"
    inner_work = run_dir / "worker"
    inner_work.mkdir(mode=0o700)
    request_path.write_text(
        json.dumps(request.model_dump(mode="json"), separators=(",", ":")),
        encoding="utf-8",
    )
    request_path.chmod(0o600)
    profiles = [path.expanduser().resolve(strict=True) for path in args.profile]
    python = _regular_executable(args.python_executable, "Python executable")
    bsub = _regular_executable(args.bsub_executable, "LSF bsub executable")
    job_script.write_text(
        _job_script(
            python=python,
            profiles=profiles,
            work_root=inner_work,
            request_path=request_path,
            response_path=response_path,
            isolation_profile_hash=contract.isolation_profile_hash,
        ),
        encoding="utf-8",
    )
    job_script.chmod(0o700)
    nonce = uuid.uuid4().hex
    command = [
        str(bsub),
        "-K",
        "-q",
        args.queue,
        "-J",
        f"verigym-dc-agent-{nonce[:12]}",
        "-n",
        str(args.cores),
        "-M",
        str(args.memory_mb * 1024),
        "-W",
        str(max(1, math.ceil(args.max_wall_seconds / 60))),
        "-oo",
        "/dev/null",
        "-eo",
        "/dev/null",
        "/bin/sh",
        str(job_script),
    ]
    completed: subprocess.CompletedProcess[bytes] | None = None
    envelope: AgentWorkerEnvelope | None = None
    job_id = ""
    try:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=args.max_wall_seconds + 240,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        stdout = completed.stdout.decode("utf-8", errors="replace") if completed else ""
        match = _JOB_ID.search(stdout)
        job_id = match.group(1) if match else ""
        scheduler_dispatched = bool(job_id)
        dispatch_hash = content_hash(
            {"request_hash": request.request_hash, "scheduler_job": job_id or nonce}
        )
        if completed is None or completed.returncode != 0 or not response_path.is_file():
            envelope = _failed_envelope(
                request,
                dispatch_id_hash=dispatch_hash,
                scheduler_dispatched=scheduler_dispatched,
                worker_started=response_path.exists(),
                duration_s=time.monotonic() - started,
                category="scheduler" if not scheduler_dispatched else "worker",
            )
        else:
            raw = response_path.read_bytes()
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ValueError("inner worker response exceeds the byte bound")
            synthesis = json.loads(raw)
            if not isinstance(synthesis, dict):
                raise ValueError("inner worker response must be an object")
            tool_result = synthesis.get("tool_result")
            if (
                synthesis.get("protocol") != SERVICE_PROTOCOL
                or synthesis.get("artifacts") != []
                or not isinstance(tool_result, dict)
            ):
                raise ValueError("inner worker response is not sanitized synthesis data")
            lifecycle: Literal["completed_clean", "candidate_failed_clean"] = (
                "completed_clean"
                if tool_result.get("success") is True
                else "candidate_failed_clean"
            )
            envelope = AgentWorkerEnvelope(
                success=True,
                synthesis=synthesis,
                receipt=AgentWorkerReceipt(
                    contract_hash=request.contract_hash,
                    code_identity_hash=request.code_identity_hash,
                    isolation_profile_hash=request.isolation_profile_hash,
                    request_hash=request.request_hash,
                    source_bundle_hash=request.source_bundle_hash,
                    dispatch_id_hash=dispatch_hash,
                    scheduler_dispatched=True,
                    worker_started=True,
                    worker_completed=True,
                    lifecycle=lifecycle,
                    duration_s=time.monotonic() - started,
                ),
            )
    except (OSError, ValueError, json.JSONDecodeError, ValidationError):
        dispatch_hash = content_hash(
            {"request_hash": request.request_hash, "scheduler_job": job_id or nonce}
        )
        envelope = _failed_envelope(
            request,
            dispatch_id_hash=dispatch_hash,
            scheduler_dispatched=bool(job_id),
            worker_started=response_path.exists(),
            duration_s=time.monotonic() - started,
            category="response",
        )
    finally:
        _cleanup_run_dir(run_dir, root)
    if run_dir.exists() or envelope is None:
        raise RuntimeError("disposable worker cleanup did not complete")
    return envelope


def lsf_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch one DC feedback job through LSF.")
    parser.add_argument("--profile", type=Path, action="append", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--queue", required=True)
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument("--bsub-executable", type=Path, required=True)
    parser.add_argument("--max-wall-seconds", type=int, default=900, choices=range(1, 7201))
    parser.add_argument("--memory-mb", type=int, default=4096, choices=range(256, 1_048_577))
    parser.add_argument("--cores", type=int, default=1, choices=range(1, 257))
    args = parser.parse_args(argv)
    raw = _read_request()
    if raw.get("operation") == "describe":
        response = AgentWorkerDescribeResponse(contract=_launcher_contract(args))
        _write_response(response.model_dump(mode="json"))
        return 0
    request = AgentWorkerLaunchRequest.model_validate(raw)
    envelope = _run_lsf(request, args)
    _write_response(envelope.model_dump(mode="json"))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VeriGym disposable DC agent worker.")
    parser.add_argument("mode", choices=["inner", "lsf"])
    args, remaining = parser.parse_known_args(argv)
    return inner_main(remaining) if args.mode == "inner" else lsf_main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["AGENT_WORKER_PROTOCOL", "inner_main", "lsf_main", "main"]
