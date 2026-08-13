#!/usr/bin/env python3
"""Run the immutable trusted controller that creates sibling benchmark sandboxes."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_OWNER = "rollout-controller"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--source-volume", required=True)
    parser.add_argument("--scratch-volume", required=True)
    parser.add_argument(
        "--empty-home",
        type=Path,
        required=True,
        help="Dedicated empty host directory mounted at the container user-home path",
    )
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--verifier-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
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
        raise RuntimeError(f"Docker returned invalid {kind} identity metadata")
    return values[0]


def _directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_dir():
        raise RuntimeError(f"controller mount is unavailable or unsafe: {path.name}")
    return resolved


def _file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise RuntimeError(f"controller input is unavailable or unsafe: {path.name}")
    return resolved


def _empty_directory(path: Path) -> Path:
    resolved = _directory(path)
    if next(resolved.iterdir(), None) is not None:
        raise RuntimeError("controller empty-home mount is not empty")
    return resolved


def _volume(name: str, role: str) -> str:
    value = _inspect("volume", name)
    labels = value.get("Labels")
    mountpoint = value.get("Mountpoint")
    if (
        not isinstance(labels, dict)
        or labels.get("verigym.owner") != _OWNER
        or labels.get("verigym.role") != role
        or not isinstance(mountpoint, str)
        or not mountpoint.startswith("/var/lib/docker/volumes/")
        or not mountpoint.endswith("/_data")
    ):
        raise RuntimeError(f"Docker volume does not satisfy the frozen {role} policy")
    return mountpoint


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not _IMAGE_ID.fullmatch(arguments.image_id):
        raise RuntimeError("controller image must be an immutable image ID")
    image = _inspect("image", arguments.image_id)
    labels = image.get("Config", {}).get("Labels", {})
    if (
        image.get("Id") != arguments.image_id
        or not isinstance(labels, dict)
        or labels.get("io.verigym.role") != "rollout-controller"
        or labels.get("io.verigym.docker.client") != "19.03.14"
    ):
        raise RuntimeError("controller image identity or role labels differ from policy")

    task_manifest = _file(arguments.task_manifest)
    empty_home = _empty_directory(arguments.empty_home)
    container_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    broker_root = _directory(arguments.broker_root)
    verifier_output = _directory(arguments.verifier_output)
    report_parent = _directory(arguments.report.parent)
    report = report_parent / arguments.report.name
    if report.exists() or report.is_symlink():
        raise RuntimeError("controller report already exists")
    _volume(arguments.source_volume, "source")
    scratch_mountpoint = _volume(arguments.scratch_volume, "scratch")

    socket = Path("/var/run/docker.sock")
    if not stat.S_ISSOCK(os.stat(socket, follow_symlinks=False).st_mode):
        raise RuntimeError("Docker controller endpoint is not a socket")
    socket_gid = os.stat(socket, follow_symlinks=False).st_gid
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
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
        "HOME=/tmp",
        "--env",
        f"TMPDIR={scratch_mountpoint}",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--volume",
        f"{empty_home}:{container_home}:rw",
        "--volume",
        f"{socket}:{socket}:rw",
        "--volume",
        f"{arguments.source_volume}:/verigym-source:ro",
        "--volume",
        f"{arguments.scratch_volume}:{scratch_mountpoint}:rw",
    ]
    for path, mode in {
        task_manifest.parent: "ro",
        broker_root: "rw",
        verifier_output: "rw",
        report_parent: "rw",
    }.items():
        command.extend(["--volume", f"{path}:{path}:{mode}"])
    command.extend(
        [
            arguments.image_id,
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
    return subprocess.run(command, shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
