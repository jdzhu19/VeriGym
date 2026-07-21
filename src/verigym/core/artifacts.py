"""Run-directory layout creation and candidate export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

    def export_candidate(self, session_root: Path) -> None:
        copy_tree_safely(
            session_root,
            self.candidate,
            excluded_names={".verigym_internal"},
        )
