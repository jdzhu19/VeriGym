from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import cast

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.orchestrator import VeriGym
from verigym.runtimes.base import Runtime
from verigym.schemas.common import (
    AssetRef,
    InteractionMode,
    SuiteDescriptor,
    TaskType,
    ToolVisibility,
)
from verigym.schemas.task import (
    BudgetSpec,
    InteractionSpec,
    ResolvedTaskAssets,
    ScoringSpec,
    SourceSpec,
    TaskRef,
    ValidationReport,
    VeriTask,
    WorkspaceSpec,
)
from verigym.schemas.verifier import VerifierGraph, VerifierNode, VerifierResult, VerifierStatus
from verigym.suites.base import SuiteAdapter


def _task() -> VeriTask:
    node = VerifierNode(
        id="run_hidden",
        plugin="external.simulate",
        visibility=ToolVisibility.VERIFIER_ONLY,
        request={"identity": "frozen"},
    )
    return VeriTask(
        id="managed/task",
        suite="managed",
        suite_version="1.0",
        task_type=TaskType.REPAIR,
        title="managed verifier fixture",
        description="fixture",
        source=SourceSpec(kind="synthetic"),
        workspace=WorkspaceSpec(base=AssetRef(kind="directory", path="."), editable_globs=["**"]),
        interaction=InteractionSpec(
            supported_modes=[InteractionMode.AGENT],
            default_mode=InteractionMode.AGENT,
            allowed_tools=[],
        ),
        budget=BudgetSpec(),
        verifier=VerifierGraph(nodes=[node]),
        scoring=ScoringSpec(correctness_required_nodes=[node.id]),
    )


class _ManagedSuite(SuiteAdapter):
    descriptor = SuiteDescriptor(
        name="managed",
        version="1.0",
        provider="tests",
        title="fixture",
        description="fixture",
        suite_version="1.0",
    )

    def __init__(self, result: VerifierResult) -> None:
        self.result = result

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        del source_root
        return []

    def load_task(self, ref: TaskRef) -> VeriTask:
        del ref
        return _task()

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        del task
        raise AssertionError("suite-managed verification must not resolve verifier assets")

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        del source_root
        return ValidationReport(valid=True)

    def verify_candidate(
        self,
        *,
        task: VeriTask,
        candidate_dir: Path,
        artifact_root: Path,
    ) -> list[VerifierResult] | None:
        del task, candidate_dir, artifact_root
        return [self.result]


def test_suite_managed_verifier_bypasses_runtime_and_preserves_frozen_identity(
    tmp_path: Path,
) -> None:
    task = _task()
    result = VerifierResult(
        node_id="run_hidden",
        plugin="external.simulate",
        status=VerifierStatus.PASSED,
        request={"identity": "frozen"},
    )
    observed = VeriGym()._verify_candidate(
        suite=_ManagedSuite(result),
        task=task,
        assets=ResolvedTaskAssets(visible_root=str(tmp_path)),
        runtime=cast(Runtime, object()),
        candidate_dir=tmp_path,
        artifact_root=tmp_path / "artifacts",
    )
    assert observed == [result]


@pytest.mark.parametrize("field", ["node", "plugin", "request"])
def test_suite_managed_verifier_rejects_result_identity_drift(
    tmp_path: Path,
    field: str,
) -> None:
    payload: dict[str, object] = {
        "node_id": "run_hidden",
        "plugin": "external.simulate",
        "status": VerifierStatus.PASSED,
        "request": {"identity": "frozen"},
    }
    if field == "node":
        payload["node_id"] = "other"
    elif field == "plugin":
        payload["plugin"] = "other.simulate"
    else:
        payload["request"] = {"identity": "changed"}
    with pytest.raises(ConfigurationError, match="suite-managed verifier"):
        VeriGym()._verify_candidate(
            suite=_ManagedSuite(VerifierResult.model_validate(payload)),
            task=_task(),
            assets=ResolvedTaskAssets(visible_root=str(tmp_path)),
            runtime=cast(Runtime, object()),
            candidate_dir=tmp_path,
            artifact_root=tmp_path / "artifacts",
        )
