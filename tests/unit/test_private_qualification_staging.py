from __future__ import annotations

import stat
from pathlib import Path

import pytest

from verigym.core.errors import PathPolicyError
from verigym.experiments.private_staging import PrivateQualificationStaging


def test_private_qualification_staging_freezes_modes_and_cleanup_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "qualification-private"
    staging = PrivateQualificationStaging(root)
    with staging:
        candidate = staging.write_text("task/case/candidate.sv", "module candidate; endmodule\n")
        manifest = staging.write_json("qualification.json", [{"expected": True}])
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(candidate.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(candidate.stat().st_mode) == 0o600
        assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
        receipt = staging.cleanup()

    assert not root.exists()
    assert receipt == {
        "format_id": "verigym_private_qualification_staging_receipt_v1",
        "private_directory_mode": "0700",
        "private_file_mode": "0600",
        "directories_created": 3,
        "files_created": 2,
        "stale_state_rejected": True,
        "cleanup_attempted": True,
        "cleanup_complete": True,
        "residual_paths": 0,
    }


def test_private_qualification_staging_rejects_stale_state_without_removing_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "qualification-private"
    root.mkdir()
    marker = root / "review-required"
    marker.write_text("stale", encoding="utf-8")

    with pytest.raises(PathPolicyError, match="stale state requires review"):
        PrivateQualificationStaging(root).__enter__()

    assert marker.read_text(encoding="utf-8") == "stale"


def test_private_qualification_staging_rejects_escape_and_duplicate_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "qualification-private"
    with PrivateQualificationStaging(root) as staging:
        staging.write_text("task/candidate.sv", "first")
        with pytest.raises(FileExistsError):
            staging.write_text("task/candidate.sv", "second")
        with pytest.raises(PathPolicyError):
            staging.write_text("../outside", "forbidden")

    assert not (tmp_path / "outside").exists()


def test_private_qualification_staging_cleans_up_after_body_failure(tmp_path: Path) -> None:
    root = tmp_path / "qualification-private"

    with pytest.raises(RuntimeError, match="qualification failed"):
        with PrivateQualificationStaging(root) as staging:
            staging.write_text("hidden/testbench.sv", "protected")
            raise RuntimeError("qualification failed")

    assert not root.exists()
