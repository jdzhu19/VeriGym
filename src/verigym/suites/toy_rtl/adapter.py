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
        self._task_root = Path(__file__).parent / "assets" / "counter_basic"

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        if source_root is not None and source_root.resolve() != self._task_root.resolve():
            return []
        return [
            TaskRef(
                id="toy-rtl/counter-basic",
                suite="toy-rtl",
                native_id="counter-basic",
            )
        ]

    def load_task(self, ref: TaskRef) -> VeriTask:
        if ref.id != "toy-rtl/counter-basic" or ref.suite != "toy-rtl":
            raise KeyError(f"unknown toy-rtl task: {ref.id}")
        task = load_model(self._task_root / "task.yaml", VeriTask)
        task.source.content_hash = hash_directory(
            self._task_root, excluded_names={"candidates", "__pycache__"}
        )
        return task

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        if task.id != "toy-rtl/counter-basic":
            raise KeyError(f"unknown toy-rtl task: {task.id}")
        visible = (self._task_root / "workspace").resolve(strict=True)
        hidden = (self._task_root / "hidden").resolve(strict=True)
        return ResolvedTaskAssets(visible_root=str(visible), hidden_roots=[str(hidden)])

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        root = source_root.resolve() if source_root is not None else self._task_root.resolve()
        required = [
            "task.yaml",
            "workspace/README.md",
            "workspace/rtl/counter.v",
            "workspace/visible/tb_smoke.sv",
            "hidden/tb_counter.sv",
            "hidden/check_result.py",
            "candidates/good/rtl/counter.v",
            "candidates/bad/rtl/counter.v",
        ]
        missing = [relative for relative in required if not (root / relative).is_file()]
        if missing:
            return ValidationReport(
                valid=False, errors=[f"missing fixture: {path}" for path in missing]
            )
        try:
            load_model(root / "task.yaml", VeriTask)
        except Exception as exc:
            return ValidationReport(valid=False, errors=[str(exc)])
        return ValidationReport(valid=True)

    def reference_solution(self, task: VeriTask) -> Candidate | None:
        if task.id != "toy-rtl/counter-basic":
            return None
        return Candidate(
            files={
                "rtl/counter.v": (
                    self._task_root / "candidates" / "good" / "rtl" / "counter.v"
                ).read_text(encoding="utf-8")
            },
            label="known-good",
        )

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        for label, expected in (("good", True), ("bad", False)):
            content = (self._task_root / "candidates" / label / "rtl" / "counter.v").read_text(
                encoding="utf-8"
            )
            yield ConformanceCase(
                name=f"counter-{label}",
                candidate=Candidate(files={"rtl/counter.v": content}, label=label),
                expected_resolved=expected,
            )
