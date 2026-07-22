"""Adapter for the committed, Apache-2.0 toy RTL fixtures."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from verigym.core.hashing import hash_directory
from verigym.core.loaders import load_model
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import SuiteDescriptor
from verigym.schemas.task import (
    Candidate,
    ConformanceCase,
    ResolvedTaskAssets,
    TaskRef,
    ValidationReport,
    VeriTask,
)
from verigym.suites.base import SuiteAdapter


class ToyRtlSuite(SuiteAdapter):
    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="toy-rtl",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=["generation", "hidden_regression", "conformance"],
        title="VeriGym toy RTL",
        description="Small committed RTL tasks used to prove the core execution contract.",
        suite_version="0.1.0",
        license="Apache-2.0",
    )

    def __init__(self) -> None:
        assets = Path(__file__).parent / "assets"
        self._task_roots = {
            "toy-rtl/and-gate-basic": assets / "and_gate_basic",
            "toy-rtl/counter-basic": assets / "counter_basic",
        }

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        if source_root is not None:
            return []
        return [
            TaskRef(
                id=task_id,
                suite="toy-rtl",
                native_id=task_id.split("/", 1)[1],
            )
            for task_id in sorted(self._task_roots)
        ]

    def load_task(self, ref: TaskRef) -> VeriTask:
        if ref.id not in self._task_roots or ref.suite != "toy-rtl":
            raise KeyError(f"unknown toy-rtl task: {ref.id}")
        root = self._task_roots[ref.id]
        task = load_model(root / "task.yaml", VeriTask)
        task.source.content_hash = hash_directory(
            root, excluded_names={"candidates", "__pycache__"}
        )
        return task

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        if task.id not in self._task_roots:
            raise KeyError(f"unknown toy-rtl task: {task.id}")
        root = self._task_roots[task.id]
        visible = (root / "workspace").resolve(strict=True)
        hidden = (root / "hidden").resolve(strict=True)
        return ResolvedTaskAssets(visible_root=str(visible), hidden_roots=[str(hidden)])

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        if source_root is not None:
            return ValidationReport(valid=False, errors=["toy-rtl does not accept a source root"])
        missing: list[str] = []
        for task_id, root in sorted(self._task_roots.items()):
            task = load_model(root / "task.yaml", VeriTask)
            required = [
                "task.yaml",
                "workspace/README.md",
                *[f"workspace/{entrypoint}" for entrypoint in task.workspace.entrypoints],
                "workspace/visible/tb_smoke.sv",
                "hidden/check_result.py",
            ]
            missing.extend(
                f"{task_id}: {relative}" for relative in required if not (root / relative).is_file()
            )
        if missing:
            return ValidationReport(
                valid=False, errors=[f"missing fixture: {path}" for path in missing]
            )
        return ValidationReport(valid=True)

    def reference_solution(self, task: VeriTask) -> Candidate | None:
        if task.id not in self._task_roots:
            return None
        root = self._task_roots[task.id]
        entrypoint = task.workspace.entrypoints[0]
        return Candidate(
            files={
                entrypoint: (root / "candidates" / "good" / entrypoint).read_text(encoding="utf-8")
            },
            label="known-good",
        )

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        for task_id, root in sorted(self._task_roots.items()):
            task = load_model(root / "task.yaml", VeriTask)
            entrypoint = task.workspace.entrypoints[0]
            for label, expected in (("good", True), ("bad", False)):
                content = (root / "candidates" / label / entrypoint).read_text(encoding="utf-8")
                yield ConformanceCase(
                    name=f"{task_id.split('/', 1)[1]}-{label}",
                    candidate=Candidate(files={entrypoint: content}, label=label),
                    expected_resolved=expected,
                )
