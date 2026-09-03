#!/usr/bin/env python3
"""Run the trusted repository controller against an isolated nested Docker daemon."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_OUTER_OWNER = "rollout-controller"
_DIND_OWNER = "rollout-controller-dind"
_DIND_SERVER_VERSION = "23.0.6"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-image-id", required=True)
    parser.add_argument("--dind-image-id", required=True)
    parser.add_argument("--verifier-image-id", action="append", required=True)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--source-volume", required=True)
    parser.add_argument("--scratch-volume", required=True)
    parser.add_argument("--dind-data-volume", required=True)
    parser.add_argument(
        "--empty-home",
        type=Path,
        required=True,
        help="Dedicated empty host directory used for the controller home and site mount policy",
    )
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--verifier-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--startup-timeout-s", type=int, default=60)
    parser.add_argument("--image-load-timeout-s", type=int, default=1800)
    return parser


def _run(argv: list[str], *, timeout_s: int = 60) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        shell=False,
        timeout=timeout_s,
    )


def _inspect(kind: str, value: str) -> dict[str, Any]:
    completed = _run(["docker", kind, "inspect", value], timeout_s=30)
    if completed.returncode != 0:
        raise RuntimeError(f"Docker cannot inspect the selected {kind}")
    try:
        values = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Docker returned malformed {kind} metadata") from exc
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


def _volume(name: str, *, owner: str, role: str) -> None:
    value = _inspect("volume", name)
    labels = value.get("Labels")
    if (
        value.get("Driver") != "local"
        or not isinstance(labels, dict)
        or labels.get("verigym.owner") != owner
        or labels.get("verigym.role") != role
    ):
        raise RuntimeError(f"Docker volume does not satisfy the frozen {role} policy")


def _bind_backed_volume(name: str, *, owner: str, role: str, backing: Path) -> Path:
    """Require a labeled local volume whose bytes live in one exact host directory."""

    resolved = _directory(backing)
    value = _inspect("volume", name)
    labels = value.get("Labels")
    options = value.get("Options")
    if (
        value.get("Driver") != "local"
        or not isinstance(labels, dict)
        or labels.get("verigym.owner") != owner
        or labels.get("verigym.role") != role
        or options
        != {
            "device": str(resolved),
            "o": "bind",
            "type": "none",
        }
    ):
        raise RuntimeError(f"Docker volume does not satisfy the frozen bind-backed {role} policy")
    return resolved


def _create_bind_backed_volume(
    name: str,
    *,
    owner: str,
    role: str,
    backing: Path,
) -> Path:
    """Create one new labeled bind-backed volume without changing the daemon data root."""

    resolved = _directory(backing)
    existing = _run(["docker", "volume", "inspect", name], timeout_s=30)
    if existing.returncode == 0:
        raise RuntimeError(f"Docker bind-backed {role} volume already exists")
    created = _run(
        [
            "docker",
            "volume",
            "create",
            "--driver",
            "local",
            "--opt",
            "type=none",
            "--opt",
            "o=bind",
            "--opt",
            f"device={resolved}",
            "--label",
            f"verigym.owner={owner}",
            "--label",
            f"verigym.role={role}",
            name,
        ],
        timeout_s=30,
    )
    if created.returncode != 0 or created.stdout.decode().strip() != name:
        raise RuntimeError(f"Docker bind-backed {role} volume creation failed")
    return _bind_backed_volume(
        name,
        owner=owner,
        role=role,
        backing=resolved,
    )


def _image(image_id: str, *, role: str) -> dict[str, Any]:
    if not _IMAGE_ID.fullmatch(image_id):
        raise RuntimeError(f"{role} image must be an immutable image ID")
    image = _inspect("image", image_id)
    if image.get("Id") != image_id:
        raise RuntimeError(f"{role} image identity changed")
    return image


def _controller_image(image_id: str) -> None:
    image = _image(image_id, role="controller")
    labels = image.get("Config", {}).get("Labels", {})
    if (
        not isinstance(labels, dict)
        or labels.get("io.verigym.role") != "rollout-controller"
        or labels.get("io.verigym.docker.client") != "19.03.14"
        or labels.get("io.verigym.git.client") != "2.30.2"
    ):
        raise RuntimeError("controller image role labels differ from policy")


def _dind_image(image_id: str) -> None:
    image = _image(image_id, role="DinD")
    config = image.get("Config")
    entrypoint = config.get("Entrypoint") if isinstance(config, dict) else None
    if (
        not isinstance(entrypoint, list)
        or len(entrypoint) != 1
        or not isinstance(entrypoint[0], str)
        or Path(entrypoint[0]).name != "dockerd-entrypoint.sh"
    ):
        raise RuntimeError("DinD image does not expose the expected official entrypoint")


def _create_socket_volume() -> str:
    name = f"verigym-dind-socket-{uuid.uuid4().hex[:20]}"
    created = _run(
        [
            "docker",
            "volume",
            "create",
            "--label",
            f"verigym.owner={_DIND_OWNER}",
            "--label",
            "verigym.role=socket",
            name,
        ],
        timeout_s=30,
    )
    if created.returncode != 0:
        raise RuntimeError("DinD socket volume creation failed")
    _volume(name, owner=_DIND_OWNER, role="socket")
    return name


def _remove_container(name: str) -> bool:
    removed = _run(["docker", "rm", "--force", name], timeout_s=60)
    inspected = _run(["docker", "container", "inspect", name], timeout_s=30)
    return removed.returncode == 0 and inspected.returncode != 0


def _remove_volume(name: str) -> bool:
    for _attempt in range(3):
        removed = _run(["docker", "volume", "rm", name], timeout_s=60)
        if removed.returncode == 0:
            return True
        time.sleep(0.25)
    return False


def _same_path_mounts(paths: dict[Path, str]) -> list[str]:
    arguments: list[str] = []
    for path, mode in sorted(paths.items(), key=lambda item: str(item[0])):
        arguments.extend(["--volume", f"{path}:{path}:{mode}"])
    return arguments


def _start_dind(
    *,
    name: str,
    image_id: str,
    socket_volume: str,
    data_volume: str,
    source_volume: str | None,
    scratch_volume: str | None,
    empty_home: Path,
    same_path_mounts: list[str],
    startup_timeout_s: int,
    on_container_started: Callable[[], None] | None = None,
) -> dict[str, Any]:
    project_volumes: list[str] = []
    if source_volume is not None:
        project_volumes.extend(["--volume", f"{source_volume}:/verigym-source:ro"])
    if scratch_volume is not None:
        project_volumes.extend(["--volume", f"{scratch_volume}:/verigym-scratch:rw"])
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        f"verigym.owner={_DIND_OWNER}",
        "--label",
        "verigym.role=daemon",
        "--privileged",
        "--network",
        "none",
        "--pids-limit",
        "32768",
        "--env",
        "DOCKER_TLS_CERTDIR=",
        "--volume",
        f"{socket_volume}:/var/run:rw",
        "--volume",
        f"{data_volume}:/var/lib/docker:rw",
        *project_volumes,
        "--mount",
        f"type=bind,src={empty_home},dst=/verigym-host-sentinel,readonly",
        *same_path_mounts,
        image_id,
        "--storage-driver=vfs",
        "--iptables=false",
        "--ip6tables=false",
        "--bridge=none",
        f"--group={os.getgid()}",
    ]
    started = _run(command, timeout_s=60)
    if started.returncode != 0:
        raise RuntimeError("isolated DinD daemon container failed to start")
    if on_container_started is not None:
        on_container_started()
    deadline = time.monotonic() + startup_timeout_s
    while time.monotonic() < deadline:
        try:
            ready = _run(["docker", "exec", name, "docker", "info"], timeout_s=15)
        except subprocess.TimeoutExpired:
            continue
        if ready.returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("isolated DinD daemon did not become ready")
    version = _run(
        [
            "docker",
            "exec",
            name,
            "docker",
            "version",
            "--format",
            "{{.Server.Version}}",
        ],
        timeout_s=30,
    )
    info = _run(
        ["docker", "exec", name, "docker", "info", "--format", "{{json .}}"],
        timeout_s=30,
    )
    socket_gid = _run(
        ["docker", "exec", name, "stat", "-c", "%g", "/var/run/docker.sock"],
        timeout_s=30,
    )
    if version.returncode != 0 or version.stdout.decode().strip() != _DIND_SERVER_VERSION:
        raise RuntimeError("isolated DinD daemon version differs from policy")
    try:
        metadata = json.loads(info.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("isolated DinD daemon returned malformed metadata") from exc
    if (
        info.returncode != 0
        or not isinstance(metadata, dict)
        or metadata.get("Driver") != "vfs"
        or metadata.get("DefaultRuntime") != "runc"
        or socket_gid.stdout.decode().strip() != str(os.getgid())
    ):
        raise RuntimeError("isolated DinD daemon controls differ from policy")
    return metadata


def _inner(
    argv: list[str], *, container: str, timeout_s: int = 60
) -> subprocess.CompletedProcess[bytes]:
    return _run(["docker", "exec", container, "docker", *argv], timeout_s=timeout_s)


def _pipe_image(*, container: str, image_id: str, timeout_s: int) -> tuple[bytes, bytes]:
    save = subprocess.Popen(
        ["docker", "save", image_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if save.stdout is None or save.stderr is None:
        save.kill()
        raise RuntimeError("Docker image export pipe is unavailable")
    load = subprocess.Popen(
        ["docker", "exec", "-i", container, "docker", "load"],
        stdin=save.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    save.stdout.close()
    try:
        stdout, stderr = load.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        load.kill()
        save.kill()
        load.communicate()
        save.communicate()
        raise RuntimeError("DinD verifier-image import timed out") from exc
    save_stderr = save.stderr.read()
    try:
        save_status = save.wait(timeout=30)
    except subprocess.TimeoutExpired as exc:
        save.kill()
        save.communicate()
        raise RuntimeError("Docker image export did not terminate") from exc
    if save_status != 0 or load.returncode != 0:
        raise RuntimeError("DinD verifier-image import failed")
    return stdout, save_stderr + stderr


def _ensure_inner_image(*, container: str, image_id: str, timeout_s: int) -> None:
    _image(image_id, role="verifier")
    present = _inner(["image", "inspect", image_id], container=container, timeout_s=30)
    if present.returncode != 0:
        _pipe_image(container=container, image_id=image_id, timeout_s=timeout_s)
    observed = _inner(
        ["image", "inspect", image_id, "--format", "{{.Id}}"],
        container=container,
        timeout_s=30,
    )
    if observed.returncode != 0 or observed.stdout.decode().strip() != image_id:
        raise RuntimeError("DinD verifier image differs after import")


def _require_empty_inner_inventory(container: str) -> None:
    containers = _inner(["container", "ls", "--all", "--quiet"], container=container, timeout_s=30)
    volumes = _inner(["volume", "ls", "--quiet"], container=container, timeout_s=30)
    if containers.returncode != 0 or volumes.returncode != 0:
        raise RuntimeError("DinD resource inventory is unavailable")
    if containers.stdout.strip() or volumes.stdout.strip():
        raise RuntimeError("DinD data volume contains stale runtime resources")


def _controller_command(
    *,
    image_id: str,
    socket_volume: str,
    source_volume: str,
    scratch_volume: str,
    empty_home: Path,
    task_manifest: Path,
    broker_root: Path,
    verifier_output: Path,
    report: Path,
) -> list[str]:
    container_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
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
        "--env",
        "DOCKER_HOST=unix:///var/run/docker.sock",
        "--env",
        "HOME=/tmp",
        "--env",
        "TMPDIR=/verigym-scratch",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--volume",
        f"{empty_home}:{container_home}:rw",
        "--volume",
        f"{socket_volume}:/var/run:rw",
        "--volume",
        f"{source_volume}:/verigym-source:ro",
        "--volume",
        f"{scratch_volume}:/verigym-scratch:rw",
    ]
    for path, mode in {
        task_manifest.parent: "ro",
        broker_root: "rw",
        verifier_output: "rw",
        report.parent: "rw",
    }.items():
        command.extend(["--volume", f"{path}:{path}:{mode}"])
    command.extend(
        [
            image_id,
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
    return command


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.startup_timeout_s <= 0 or arguments.image_load_timeout_s <= 0:
        raise RuntimeError("DinD timeouts must be positive")
    _controller_image(arguments.controller_image_id)
    _dind_image(arguments.dind_image_id)
    for image_id in arguments.verifier_image_id:
        _image(image_id, role="verifier")
    task_manifest = _file(arguments.task_manifest)
    empty_home = _empty_directory(arguments.empty_home)
    broker_root = _directory(arguments.broker_root)
    verifier_output = _directory(arguments.verifier_output)
    report_parent = _directory(arguments.report.parent)
    report = report_parent / arguments.report.name
    if report.exists() or report.is_symlink():
        raise RuntimeError("controller report already exists")
    _volume(arguments.source_volume, owner=_OUTER_OWNER, role="source")
    _volume(arguments.scratch_volume, owner=_OUTER_OWNER, role="scratch")
    _volume(arguments.dind_data_volume, owner=_DIND_OWNER, role="data")

    same_paths = {
        task_manifest.parent: "ro",
        broker_root: "rw",
        verifier_output: "rw",
        report_parent: "rw",
    }
    socket_volume = _create_socket_volume()
    dind_name = f"verigym-dind-daemon-{uuid.uuid4().hex[:20]}"
    try:
        _start_dind(
            name=dind_name,
            image_id=arguments.dind_image_id,
            socket_volume=socket_volume,
            data_volume=arguments.dind_data_volume,
            source_volume=arguments.source_volume,
            scratch_volume=arguments.scratch_volume,
            empty_home=empty_home,
            same_path_mounts=_same_path_mounts(same_paths),
            startup_timeout_s=arguments.startup_timeout_s,
        )
        _require_empty_inner_inventory(dind_name)
        for image_id in dict.fromkeys(arguments.verifier_image_id):
            _ensure_inner_image(
                container=dind_name,
                image_id=image_id,
                timeout_s=arguments.image_load_timeout_s,
            )
        command = _controller_command(
            image_id=arguments.controller_image_id,
            socket_volume=socket_volume,
            source_volume=arguments.source_volume,
            scratch_volume=arguments.scratch_volume,
            empty_home=empty_home,
            task_manifest=task_manifest,
            broker_root=broker_root,
            verifier_output=verifier_output,
            report=report,
        )
        completed = subprocess.run(command, check=False, shell=False)
        _require_empty_inner_inventory(dind_name)
        return completed.returncode
    finally:
        existing = _run(["docker", "container", "inspect", dind_name], timeout_s=30)
        dind_removed = existing.returncode != 0 or _remove_container(dind_name)
        socket_removed = _remove_volume(socket_volume)
        if not dind_removed:
            raise RuntimeError("DinD daemon cleanup failed")
        if not socket_removed:
            raise RuntimeError("DinD socket volume cleanup failed")


if __name__ == "__main__":
    raise SystemExit(main())
