#!/usr/bin/env python3
"""Run the trusted online repository broker with private Docker-volume source state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--source-volume", required=True)
    parser.add_argument("--scratch-volume", required=True)
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--verifier-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--docker-helper", type=Path)
    parser.add_argument("--expected-docker-helper-sha256")
    return parser


def _inspect(kind: str, value: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["docker", kind, "inspect", value],
        check=True,
        capture_output=True,
        shell=False,
        text=True,
        timeout=30,
    )
    values = json.loads(completed.stdout)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise RuntimeError(f"Docker returned an invalid {kind} inspection")
    return values[0]


def _safe_directory(path: Path) -> Path:
    value = path.resolve(strict=True)
    if not value.is_dir() or value.is_symlink():
        raise RuntimeError(f"required directory is unavailable or unsafe: {path.name}")
    return value


def _safe_file(path: Path) -> Path:
    value = path.resolve(strict=True)
    if not value.is_file() or value.is_symlink():
        raise RuntimeError(f"required file is unavailable or unsafe: {path.name}")
    return value


def _volume(name: str, role: str) -> str:
    value = _inspect("volume", name)
    labels = value.get("Labels")
    mountpoint = value.get("Mountpoint")
    if (
        not isinstance(labels, dict)
        or labels.get("verigym.owner") != "online-repository-broker"
        or labels.get("verigym.role") != role
        or not isinstance(mountpoint, str)
        or not mountpoint.startswith("/var/lib/docker/volumes/")
        or not mountpoint.endswith("/_data")
    ):
        raise RuntimeError(f"Docker volume does not satisfy the frozen {role} policy")
    return mountpoint


def _mount(path: Path, mode: str) -> str:
    return f"{path}:{path}:{mode}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _docker_helper(
    docker: Path,
    helper: Path | None,
    expected_sha256: str | None,
) -> Path | None:
    if (helper is None) != (expected_sha256 is None):
        raise RuntimeError("Docker helper path and SHA-256 must be supplied together")
    if helper is None or expected_sha256 is None:
        return None
    resolved = _safe_file(helper)
    if resolved == docker or resolved.parent != docker.parent:
        raise RuntimeError("Docker helper must be a distinct sibling of the Docker executable")
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise RuntimeError("expected Docker helper SHA-256 is malformed")
    digest = _sha256_file(resolved)
    if digest != expected_sha256:
        raise RuntimeError("Docker helper identity differs from its pin")
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    image = _inspect("image", arguments.image)
    if image.get("Id") != arguments.expected_image_id:
        raise RuntimeError("trusted broker image identity differs from its pin")
    repository = _safe_directory(arguments.repository)
    python = _safe_file(arguments.python)
    environment_root = _safe_directory(python.parents[1])
    task_manifest = _safe_file(arguments.task_manifest)
    broker_root = _safe_directory(arguments.broker_root)
    verifier_output = _safe_directory(arguments.verifier_output)
    report_parent = _safe_directory(arguments.report.resolve().parent)
    report = report_parent / arguments.report.name
    if report.exists() or report.is_symlink():
        raise RuntimeError("trusted broker report already exists")
    _volume(arguments.source_volume, "source")
    scratch_mountpoint = _volume(arguments.scratch_volume, "scratch")
    docker = Path(shutil.which("docker") or "").resolve(strict=True)
    docker_helper = _docker_helper(
        docker,
        arguments.docker_helper,
        arguments.expected_docker_helper_sha256,
    )
    socket = Path("/var/run/docker.sock").resolve(strict=True)
    socket_mode = os.lstat(socket).st_mode
    if not stat.S_ISSOCK(socket_mode):
        raise RuntimeError("Docker broker endpoint is not a socket")
    socket_gid = os.stat(socket).st_gid
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "4096",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--group-add",
        str(socket_gid),
        "--env",
        f"HOME={scratch_mountpoint}/home",
        "--env",
        f"TMPDIR={scratch_mountpoint}/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        (
            "PYTHONPATH="
            f"{repository / 'src'}:"
            f"{repository / 'integrations/verigym-hwe-bench/src'}:"
            f"{repository / 'integrations/verigym-training-reference/src'}"
        ),
        "--volume",
        f"{arguments.source_volume}:/verigym-source:ro",
        "--volume",
        f"{arguments.scratch_volume}:{scratch_mountpoint}:rw",
        "--volume",
        f"{socket}:{socket}:rw",
        "--volume",
        f"{docker}:{docker}:ro",
    ]
    if docker_helper is not None:
        command.extend(["--volume", _mount(docker_helper, "ro")])
    host_mounts = {
        repository: "ro",
        environment_root: "ro",
        task_manifest.parent: "ro",
        broker_root.parent: "rw",
        verifier_output.parent: "rw",
        report_parent: "rw",
    }
    for path, mode in host_mounts.items():
        command.extend(["--volume", _mount(path, mode)])
    command.extend(
        [
            "--workdir",
            str(repository),
            arguments.image,
            str(python),
            str(repository / "scripts/run_qwen35_online_repository_broker.py"),
            "--task-manifest",
            str(task_manifest),
            "--source-root",
            "/verigym-source",
            "--broker-root",
            str(broker_root),
            "--verifier-output",
            str(verifier_output),
            "--report",
            str(report),
        ]
    )
    return subprocess.run(command, cwd=repository, shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
