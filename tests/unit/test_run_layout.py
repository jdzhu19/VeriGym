from __future__ import annotations

from pathlib import Path

import pytest

from verigym.core.artifacts import RunLayout, snapshot_candidate_file_modes
from verigym.core.errors import PathPolicyError


def test_candidate_export_restores_reference_modes_after_runtime_broadening(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    session = tmp_path / "session"
    for root in (reference, session):
        (root / "repository").mkdir(parents=True)
        (root / "repository" / "design.sv").write_text("module design; endmodule\n")
        (root / "repository" / "check.sh").write_text("#!/bin/sh\nexit 0\n")
    (reference / "repository" / "design.sv").chmod(0o644)
    (reference / "repository" / "check.sh").chmod(0o755)
    (session / "repository" / "design.sv").chmod(0o666)
    (session / "repository" / "check.sh").chmod(0o666)
    (session / "repository" / "new.sv").write_text("module new_design; endmodule\n")
    (session / "repository" / "new.sv").chmod(0o666)
    layout = RunLayout.create(tmp_path / "run")
    reference_file_modes = snapshot_candidate_file_modes(reference)

    layout.export_candidate(session, reference_file_modes=reference_file_modes)

    repository = layout.candidate / "repository"
    assert repository.joinpath("design.sv").stat().st_mode & 0o7777 == 0o644
    assert repository.joinpath("check.sh").stat().st_mode & 0o7777 == 0o755
    assert repository.joinpath("new.sv").stat().st_mode & 0o7777 == 0o644


def test_candidate_export_rejects_unsafe_reference_modes(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    session = tmp_path / "session"
    reference.mkdir()
    session.mkdir()
    (reference / "design.sv").write_text("module design; endmodule\n")
    (reference / "design.sv").chmod(0o666)
    (session / "design.sv").write_text("module design; endmodule\n")

    with pytest.raises(PathPolicyError, match="unsafe permissions"):
        snapshot_candidate_file_modes(reference)


def test_candidate_export_rejects_unsafe_mode_receipt(tmp_path: Path) -> None:
    session = tmp_path / "session"
    session.mkdir()
    (session / "design.sv").write_text("module design; endmodule\n")
    layout = RunLayout.create(tmp_path / "run")

    with pytest.raises(PathPolicyError, match="unsafe permissions"):
        layout.export_candidate(session, reference_file_modes={"design.sv": 0o666})


def test_candidate_export_uses_pre_runtime_mode_receipt(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    session = tmp_path / "session"
    reference.mkdir()
    session.mkdir()
    (reference / "design.sv").write_text("module design; endmodule\n")
    (reference / "design.sv").chmod(0o644)
    reference_file_modes = snapshot_candidate_file_modes(reference)

    # A runtime may mutate both its session and the temporary visible-source tree.
    (reference / "design.sv").chmod(0o600)
    (session / "design.sv").write_text("module design; endmodule\n")
    (session / "design.sv").chmod(0o600)
    layout = RunLayout.create(tmp_path / "run")

    layout.export_candidate(session, reference_file_modes=reference_file_modes)

    assert layout.candidate.joinpath("design.sv").stat().st_mode & 0o7777 == 0o644
