from __future__ import annotations

from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.synthesis import _stage_candidate, _stage_reference
from verigym.core.synthesis_projection import (
    resolve_synthesis_source_projection,
    synthesis_source_projection_contract,
)
from verigym.schemas.task import Candidate, TaskRef
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite


def _projected_task():  # type: ignore[no-untyped-def]
    task = RepositoryRtlSuite().load_task(
        TaskRef(id="repo-rtl/counter-wrap", suite="repo-rtl", native_id="counter-wrap")
    )
    workspace_source = "repository/rtl/projected.v"
    workspace = task.workspace.model_copy(update={"entrypoints": [workspace_source]})
    metadata = {
        **task.metadata,
        "synthesis_source_projection": synthesis_source_projection_contract(
            {workspace_source: "rtl/projected.v"}
        ),
    }
    return task.model_copy(update={"workspace": workspace, "metadata": metadata})


def test_projection_is_hash_bound_and_stages_the_workspace_source(tmp_path: Path) -> None:
    task = _projected_task()
    projection = resolve_synthesis_source_projection(task)
    source_root = tmp_path / "candidate"
    source = source_root / "repository" / "rtl" / "projected.v"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"module projected; endmodule\n")
    staging = tmp_path / "staging"
    staging.mkdir()

    _stage_candidate(staging, source_root, projection.profile_sources, task=task)

    assert projection.profile_sources == ["rtl/projected.v"]
    assert projection.projection_hash is not None
    assert (staging / "rtl" / "projected.v").read_bytes() == source.read_bytes()
    assert not (staging / "repository").exists()


def test_projection_stages_reference_from_workspace_to_profile_path(tmp_path: Path) -> None:
    task = _projected_task()
    staging = tmp_path / "reference"
    staging.mkdir()
    reference = Candidate(
        files={"repository/rtl/projected.v": "module projected; endmodule\n"},
        label="reference",
    )

    _stage_reference(staging, reference, ["rtl/projected.v"], task=task)

    assert (staging / "rtl" / "projected.v").read_text(encoding="utf-8") == (
        "module projected; endmodule\n"
    )
    assert not (staging / "repository").exists()


def test_projection_rejects_hash_or_source_order_drift() -> None:
    task = _projected_task()
    metadata = dict(task.metadata)
    contract = dict(metadata["synthesis_source_projection"])
    contract["projection_hash"] = "0" * 64
    metadata["synthesis_source_projection"] = contract

    with pytest.raises(ValueError, match="hash is invalid"):
        resolve_synthesis_source_projection(task.model_copy(update={"metadata": metadata}))

    with pytest.raises(ConfigurationError, match="sources differ"):
        _stage_candidate(Path("unused"), Path("unused"), ["rtl/other.v"], task=task)
