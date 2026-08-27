"""Workspace path policy and safe export helpers."""

from __future__ import annotations

import fnmatch
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from verigym.core.errors import PathPolicyError


def normalize_relative_path(raw_path: str, *, allow_root: bool = False) -> str:
    """Normalize a model-provided POSIX path while rejecting traversal."""

    if "\x00" in raw_path:
        raise PathPolicyError("paths cannot contain NUL bytes")
    normalized_input = raw_path.replace("\\", "/")
    path = PurePosixPath(normalized_input)
    if path.is_absolute():
        raise PathPolicyError("absolute paths are not allowed")
    if any(part == ".." for part in path.parts):
        raise PathPolicyError("parent path traversal is not allowed")
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts:
        if allow_root:
            return "."
        raise PathPolicyError("a file path is required")
    return PurePosixPath(*parts).as_posix()


def _glob_variants(pattern: str) -> set[str]:
    variants = {pattern}
    pending = [pattern]
    while pending:
        current = pending.pop()
        marker = "**/"
        start = current.find(marker)
        if start >= 0:
            collapsed = current[:start] + current[start + len(marker) :]
            if collapsed not in variants:
                variants.add(collapsed)
                pending.append(collapsed)
    return variants


def glob_matches(path: str, pattern: str) -> bool:
    """Match Git-style globs, treating ``**/`` as zero or more directories."""

    return any(fnmatch.fnmatchcase(path, variant) for variant in _glob_variants(pattern))


@dataclass(frozen=True)
class WorkspacePolicy:
    editable_globs: tuple[str, ...]
    readonly_globs: tuple[str, ...] = ()
    excluded_globs: tuple[str, ...] = ()
    max_changed_files: int | None = None
    max_patch_lines: int | None = None
    max_workspace_bytes: int | None = None
    internal_names: tuple[str, ...] = (".verigym_internal",)

    def _matches_any(self, path: str, patterns: tuple[str, ...]) -> bool:
        return any(glob_matches(path, pattern) for pattern in patterns)

    def is_excluded(self, path: str) -> bool:
        normalized = normalize_relative_path(path, allow_root=True)
        if normalized == ".":
            return False
        if any(part in self.internal_names for part in PurePosixPath(normalized).parts):
            return True
        return self._matches_any(normalized, self.excluded_globs)

    def check_read(self, path: str, *, allow_root: bool = False) -> str:
        normalized = normalize_relative_path(path, allow_root=allow_root)
        if self.is_excluded(normalized):
            raise PathPolicyError("path is not available in the agent workspace")
        return normalized

    def check_write(self, path: str) -> str:
        normalized = normalize_relative_path(path)
        if self.is_excluded(normalized):
            raise PathPolicyError("path is not editable")
        if self._matches_any(normalized, self.readonly_globs):
            raise PathPolicyError(f"path is read-only: {normalized}")
        if not self._matches_any(normalized, self.editable_globs):
            raise PathPolicyError(f"path is outside editable globs: {normalized}")
        return normalized

    def check_patch_size(self, changed_files: int, patch_lines: int) -> None:
        if self.max_changed_files is not None and changed_files > self.max_changed_files:
            raise PathPolicyError(
                f"patch changes {changed_files} files; limit is {self.max_changed_files}"
            )
        if self.max_patch_lines is not None and patch_lines > self.max_patch_lines:
            raise PathPolicyError(f"patch has {patch_lines} lines; limit is {self.max_patch_lines}")


def copy_tree_safely(
    source: Path,
    destination: Path,
    *,
    excluded_names: set[str] | None = None,
    preserve_safe_file_modes: bool = False,
) -> None:
    """Copy a tree without accepting symlinks or traversal-prone special files.

    Trusted canonical sources may opt in to exact regular-file mode preservation. Unsafe
    special-bit or group/world-writable source modes fail closed instead of being propagated.
    """

    source = source.resolve(strict=True)
    excluded = excluded_names or set()
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in excluded for part in relative.parts):
            continue
        if path.is_symlink():
            raise PathPolicyError(f"refusing to copy symlink: {relative.as_posix()}")
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            mode = stat.S_IMODE(path.stat().st_mode)
            if preserve_safe_file_modes and mode & 0o7022:
                raise PathPolicyError(
                    f"refusing to preserve unsafe file permissions: {relative.as_posix()}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if preserve_safe_file_modes:
                target.chmod(mode)
        else:
            raise PathPolicyError(f"refusing to copy special file: {relative.as_posix()}")


def merge_tree_safely(source: Path, destination: Path, *, mount_path: str = ".") -> None:
    """Copy a trusted asset tree into a staging root at a validated relative mount path."""

    relative_mount = normalize_relative_path(mount_path, allow_root=True)
    target = destination if relative_mount == "." else destination / relative_mount
    copy_tree_safely(source, target)
