"""Run-directory layout creation and candidate export."""

from __future__ import annotations

import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from verigym.core.errors import PathPolicyError
from verigym.core.workspace import copy_tree_safely


@dataclass(frozen=True)
class RunLayout:
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "run_manifest.json"

    @property
    def task_snapshot(self) -> Path:
        return self.root / "task_snapshot.json"

    @property
    def trace(self) -> Path:
        return self.root / "trace.jsonl"

    @property
    def scorecard(self) -> Path:
        return self.root / "scorecard.json"

    @property
    def workspace_diff(self) -> Path:
        return self.root / "workspace_diff.patch"

    @property
    def candidate(self) -> Path:
        return self.root / "candidate"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @classmethod
    def create(cls, root: Path) -> RunLayout:
        if root.exists():
            raise FileExistsError(f"run directory already exists: {root}")
        root.mkdir(parents=True)
        layout = cls(root=root)
        layout.logs.mkdir()
        layout.artifacts.mkdir()
        for name in ("agent.log", "runtime.log", "verifier.log"):
            (layout.logs / name).write_text("", encoding="utf-8")
        return layout

    def export_candidate(
        self,
        session_root: Path,
        *,
        reference_file_modes: Mapping[str, int],
    ) -> None:
        copy_tree_safely(
            session_root,
            self.candidate,
            excluded_names={".verigym_internal"},
        )
        _restore_candidate_file_modes(
            candidate_root=self.candidate,
            reference_file_modes=reference_file_modes,
        )


def snapshot_candidate_file_modes(reference_root: Path) -> dict[str, int]:
    """Freeze safe visible-source file modes before a runtime can mutate its staging tree."""

    reference = reference_root.resolve(strict=True)
    modes: dict[str, int] = {}
    for source in sorted(reference.rglob("*")):
        relative = source.relative_to(reference).as_posix()
        if source.is_symlink():
            raise PathPolicyError(f"candidate mode reference cannot be a symlink: {relative}")
        metadata = source.stat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise PathPolicyError(f"candidate mode reference is not a regular file: {relative}")
        mode = stat.S_IMODE(metadata.st_mode)
        if mode & 0o7022:
            raise PathPolicyError(f"candidate mode reference has unsafe permissions: {relative}")
        modes[relative] = mode
    return modes


def _restore_candidate_file_modes(
    *,
    candidate_root: Path,
    reference_file_modes: Mapping[str, int],
) -> None:
    """Remove runtime permission broadening from one exported candidate tree."""

    candidate = candidate_root.resolve(strict=True)
    for target in sorted(candidate.rglob("*")):
        if target.is_symlink():
            raise PathPolicyError("candidate export cannot contain symlinks")
        if not target.is_file():
            continue
        relative = target.relative_to(candidate).as_posix()
        mode = reference_file_modes.get(relative, 0o644)
        if not isinstance(mode, int) or mode < 0 or mode > 0o7777 or mode & 0o7022:
            raise PathPolicyError(f"candidate mode receipt has unsafe permissions: {relative}")
        target.chmod(mode)
