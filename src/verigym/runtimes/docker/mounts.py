"""Canonical Docker bind-mount policy for VeriGym-created staging roots."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from verigym.core.errors import PathPolicyError

_DOCKER_SOCKET_DESTINATIONS = {"/var/run/docker.sock", "/run/docker.sock"}


@dataclass(frozen=True)
class MountSpec:
    source: Path
    destination: str
    read_only: bool


def validate_mount_plan(
    mounts: list[MountSpec],
    *,
    approved_roots: tuple[Path, ...],
    host_home: Path | None = None,
    repository_root: Path | None = None,
) -> list[MountSpec]:
    """Reject path escapes, special sources, protected roots, and overlap."""

    approved = tuple(root.resolve(strict=True) for root in approved_roots)
    home = (host_home or Path.home()).resolve(strict=False)
    repository = repository_root.resolve(strict=False) if repository_root is not None else None
    normalized: list[MountSpec] = []
    destinations: list[PurePosixPath] = []
    for mount in mounts:
        raw_source = mount.source.expanduser()
        _reject_symlink_components(raw_source)
        source = raw_source.resolve(strict=True)
        if not any(source == root or source.is_relative_to(root) for root in approved):
            raise PathPolicyError("Docker mount source is outside its private staging root")
        if source == home or source.is_relative_to(home):
            raise PathPolicyError("DockerRuntime never mounts the host home directory")
        if repository is not None and (source == repository or source.is_relative_to(repository)):
            raise PathPolicyError("DockerRuntime never mounts the repository source root")
        mode = os.lstat(source).st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise PathPolicyError("Docker mount sources must be regular files or directories")
        destination = PurePosixPath(mount.destination)
        if not destination.is_absolute() or ".." in destination.parts:
            raise PathPolicyError("Docker mount destination must be a canonical absolute path")
        destination_text = destination.as_posix()
        if destination_text in _DOCKER_SOCKET_DESTINATIONS:
            raise PathPolicyError("mounting the Docker socket is forbidden")
        for existing in destinations:
            if (
                destination == existing
                or destination.is_relative_to(existing)
                or existing.is_relative_to(destination)
            ):
                raise PathPolicyError("Docker mount destinations must not overlap")
        destinations.append(destination)
        normalized.append(
            MountSpec(source=source, destination=destination_text, read_only=mount.read_only)
        )
    return normalized


def workspace_mount(root: Path) -> MountSpec:
    plan = validate_mount_plan(
        [MountSpec(source=root, destination="/workspace", read_only=False)],
        approved_roots=(root,),
    )
    return plan[0]


def mount_arguments(mounts: list[MountSpec]) -> list[str]:
    arguments: list[str] = []
    for mount in mounts:
        option = f"type=bind,src={mount.source},dst={mount.destination}"
        if mount.read_only:
            option += ",readonly"
        arguments.extend(["--mount", option])
    return arguments


def _reject_symlink_components(path: Path) -> None:
    cursor = Path(path.anchor) if path.is_absolute() else Path.cwd()
    for part in path.parts:
        if part in {path.anchor, "", "."}:
            continue
        cursor = cursor / part
        if cursor.is_symlink():
            raise PathPolicyError("symlink components are forbidden in Docker mount sources")


__all__ = ["MountSpec", "mount_arguments", "validate_mount_plan", "workspace_mount"]
