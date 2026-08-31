"""Content-free filesystem headroom gate for HWE image materialization."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

_GIB = 1024**3
_MAX_DOCKER_INFO_BYTES = 4096
_PLANNED_COMMAND_IMAGE_COUNT = 6
_MAX_BYTES_PER_COMMAND_IMAGE = 8 * _GIB
_DOCKER_HEADROOM_MULTIPLIER = 2


@dataclass(frozen=True)
class _Requirement:
    role: str
    minimum_free_bytes: int
    minimum_free_inodes: int


_REQUIREMENTS = (
    _Requirement("control_root", 4 * _GIB, 100_000),
    _Requirement(
        "docker_root",
        _PLANNED_COMMAND_IMAGE_COUNT * _MAX_BYTES_PER_COMMAND_IMAGE * _DOCKER_HEADROOM_MULTIPLIER,
        250_000,
    ),
    _Requirement("scratch_root", 8 * _GIB, 50_000),
    _Requirement("output_parent", 2 * _GIB, 10_000),
)


class MaterializationHeadroomError(ConfigurationError):
    """Fail-closed headroom rejection carrying only a content-free receipt."""

    def __init__(self, receipt: dict[str, Any]) -> None:
        super().__init__("HWE command-image materialization headroom preflight failed")
        self.receipt = receipt


def discover_docker_root() -> Path:
    """Resolve Docker's data root without promoting daemon output into an artifact."""

    completed = subprocess.run(
        ["docker", "info", "--format", "{{.DockerRootDir}}"],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if (
        completed.returncode != 0
        or not completed.stdout
        or len(completed.stdout) > _MAX_DOCKER_INFO_BYTES
        or len(completed.stderr) > _MAX_DOCKER_INFO_BYTES
    ):
        raise ConfigurationError("Docker data-root discovery failed or exceeded its output bound")
    try:
        value = completed.stdout.decode("utf-8", errors="strict").strip()
        root = Path(value).resolve(strict=True)
    except (OSError, UnicodeError):
        raise ConfigurationError("Docker returned an invalid data-root path") from None
    if not value or not root.is_dir():
        raise ConfigurationError("Docker returned an unavailable data-root directory")
    return root


def materialization_headroom_receipt(
    *,
    control_root: Path,
    docker_root: Path,
    scratch_root: Path,
    output_parent: Path,
) -> dict[str, Any]:
    """Measure frozen absolute byte/inode thresholds without model or provider work."""

    supplied = {
        "control_root": control_root,
        "docker_root": docker_root,
        "scratch_root": scratch_root,
        "output_parent": output_parent,
    }
    observations: list[dict[str, Any]] = []
    for requirement in _REQUIREMENTS:
        path = _safe_directory(supplied[requirement.role])
        try:
            values = os.statvfs(path)
        except OSError:
            raise ConfigurationError("HWE materialization filesystem measurement failed") from None
        block_size = values.f_frsize or values.f_bsize
        free_bytes = values.f_bavail * block_size
        free_inodes = values.f_favail
        observations.append(
            {
                "role": requirement.role,
                "minimum_free_bytes": requirement.minimum_free_bytes,
                "observed_free_bytes": free_bytes,
                "minimum_free_inodes": requirement.minimum_free_inodes,
                "observed_free_inodes": free_inodes,
                "bytes_satisfied": free_bytes >= requirement.minimum_free_bytes,
                "inodes_satisfied": free_inodes >= requirement.minimum_free_inodes,
            }
        )
    passed = all(item["bytes_satisfied"] and item["inodes_satisfied"] for item in observations)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_command_image_materialization_headroom_v1",
        "status": "passed" if passed else "rejected_insufficient_headroom",
        "policy": {
            "absolute_thresholds": True,
            "percentage_thresholds": False,
            "planned_command_image_count": _PLANNED_COMMAND_IMAGE_COUNT,
            "maximum_bytes_per_command_image": _MAX_BYTES_PER_COMMAND_IMAGE,
            "docker_headroom_multiplier": _DOCKER_HEADROOM_MULTIPLIER,
        },
        "filesystems": observations,
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_command_output_persisted": False,
    }
    return {**base, "preflight_hash": content_hash(base)}


def require_materialization_headroom(
    *,
    control_root: Path,
    docker_root: Path,
    scratch_root: Path,
    output_parent: Path,
) -> dict[str, Any]:
    """Return a passed receipt or raise with the rejected content-free receipt."""

    receipt = materialization_headroom_receipt(
        control_root=control_root,
        docker_root=docker_root,
        scratch_root=scratch_root,
        output_parent=output_parent,
    )
    if receipt["status"] != "passed":
        raise MaterializationHeadroomError(receipt)
    return receipt


def _safe_directory(path: Path) -> Path:
    if path.is_symlink():
        raise ConfigurationError("HWE materialization headroom path must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ConfigurationError("HWE materialization headroom path is unavailable") from None
    if not resolved.is_dir():
        raise ConfigurationError("HWE materialization headroom path is not a directory")
    return resolved


__all__ = [
    "MaterializationHeadroomError",
    "discover_docker_root",
    "materialization_headroom_receipt",
    "require_materialization_headroom",
]
