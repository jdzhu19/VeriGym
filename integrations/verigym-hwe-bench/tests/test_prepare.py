from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError

from verigym_hwe_bench import prepare
from verigym_hwe_bench.prepare import _image_baseline, _materialize_internal_file_symlinks


def test_materialize_internal_file_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    target = repository / "rtl" / "shared.sv"
    link = repository / "dv" / "shared.sv"
    target.parent.mkdir(parents=True)
    link.parent.mkdir(parents=True)
    target.write_text("module shared; endmodule\n", encoding="utf-8")
    link.symlink_to(Path("../rtl/shared.sv"))

    _materialize_internal_file_symlinks(repository)

    assert not link.is_symlink()
    assert link.read_bytes() == target.read_bytes()


def test_reject_escaping_file_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside.sv"
    outside.write_text("secret\n", encoding="utf-8")
    os.symlink(outside, repository / "escape.sv")

    with pytest.raises(ConfigurationError, match="escaping symlink"):
        _materialize_internal_file_symlinks(repository)


def test_materialize_dangling_internal_symlink_as_git_blob(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    link = repository / "missing.sv"
    link.symlink_to(Path("rtl/missing.sv"))

    _materialize_internal_file_symlinks(repository)

    assert not link.is_symlink()
    assert link.read_bytes() == b"rtl/missing.sv"


def test_synthetic_runtime_baseline_is_bound_to_official_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official = "1" * 40
    runtime = "2" * 40

    def fake_command(
        argv: list[str],
        *,
        timeout_s: int = 300,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        del timeout_s, input_bytes
        path = argv[-1]
        payload = official if path.endswith("/.baseline_commit") else runtime
        return subprocess.CompletedProcess(argv, 0, f"{payload}\n".encode(), b"")

    monkeypatch.setattr(prepare, "_command", fake_command)

    assert (
        _image_baseline(
            image_id=f"sha256:{'3' * 64}",
            repository_home="/home/ibex",
            base_commit=official,
        )
        == runtime
    )
