"""Explicit validation of declared host-backed Docker command artifacts."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath

from verigym.core.hashing import hash_bytes
from verigym.runtimes.docker.errors import DockerArtifactError
from verigym.schemas.base import StrictModel

_ALLOWED_OUTPUT_ROOTS = {".verigym_internal", "artifacts", "build"}


class DockerArtifactMetadata(StrictModel):
    path: str
    size_bytes: int
    content_hash: str


def collect_declared_artifacts(
    root: Path,
    patterns: list[str],
    *,
    max_file_bytes: int,
    max_total_bytes: int,
) -> list[DockerArtifactMetadata]:
    """Hash safe regular files from trusted declared output roots only."""

    root = root.resolve(strict=True)
    candidates: dict[str, Path] = {}
    for pattern in patterns:
        normalized = _validate_pattern(pattern)
        for candidate in root.glob(normalized):
            relative = candidate.relative_to(root).as_posix()
            _validate_candidate(root, candidate, relative)
            candidates[relative] = candidate
    total = 0
    artifacts: list[DockerArtifactMetadata] = []
    for relative, candidate in sorted(candidates.items()):
        metadata = os.lstat(candidate)
        if stat.S_ISLNK(metadata.st_mode):
            raise DockerArtifactError(
                f"declared artifact is a symlink: {relative}",
                subreason="artifact_symlink",
            )
        if not stat.S_ISREG(metadata.st_mode):
            if stat.S_ISDIR(metadata.st_mode):
                continue
            raise DockerArtifactError(
                f"declared artifact is not a regular file: {relative}",
                subreason="artifact_special_file",
            )
        if metadata.st_nlink > 1:
            raise DockerArtifactError(
                f"declared artifact has an unverified hard link: {relative}",
                subreason="artifact_hardlink",
            )
        if metadata.st_size > max_file_bytes:
            raise DockerArtifactError(
                f"declared artifact exceeds the per-file limit: {relative}",
                subreason="artifact_file_too_large",
                details={"size_bytes": metadata.st_size, "limit_bytes": max_file_bytes},
            )
        total += metadata.st_size
        if total > max_total_bytes:
            raise DockerArtifactError(
                "declared artifacts exceed the aggregate size limit",
                subreason="artifact_total_too_large",
                details={"size_bytes": total, "limit_bytes": max_total_bytes},
            )
        payload = candidate.read_bytes()
        artifacts.append(
            DockerArtifactMetadata(
                path=relative,
                size_bytes=len(payload),
                content_hash=hash_bytes(payload),
            )
        )
    return artifacts


def _validate_candidate(root: Path, candidate: Path, relative: str) -> None:
    """Reject a symlink in any path component before reading artifact metadata."""

    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        try:
            metadata = os.lstat(cursor)
        except FileNotFoundError as exc:
            raise DockerArtifactError(
                f"declared artifact disappeared during validation: {relative}",
                subreason="artifact_race",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise DockerArtifactError(
                f"declared artifact contains a symlink component: {relative}",
                subreason="artifact_symlink",
            )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DockerArtifactError(
            f"declared artifact cannot be resolved safely: {relative}",
            subreason="artifact_path_invalid",
        ) from exc
    if not resolved.is_relative_to(root):
        raise DockerArtifactError(
            f"declared artifact escapes its output root: {relative}",
            subreason="artifact_traversal",
        )


def _validate_pattern(pattern: str) -> str:
    if not pattern or "\x00" in pattern or "\\" in pattern:
        raise DockerArtifactError(
            "artifact patterns must be nonempty canonical POSIX paths",
            subreason="artifact_path_invalid",
        )
    path = PurePosixPath(pattern)
    if path.is_absolute() or ".." in path.parts:
        raise DockerArtifactError(
            "artifact pattern escapes the declared output roots",
            subreason="artifact_traversal",
        )
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts or parts[0] not in _ALLOWED_OUTPUT_ROOTS:
        raise DockerArtifactError(
            "artifact pattern is outside an approved output root",
            subreason="artifact_root_forbidden",
        )
    return PurePosixPath(*parts).as_posix()


__all__ = ["DockerArtifactMetadata", "collect_declared_artifacts"]
