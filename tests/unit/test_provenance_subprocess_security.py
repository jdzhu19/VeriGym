from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from verigym import provenance


def test_git_provenance_subprocess_receives_only_minimal_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["argv"] = argv
        captured["environment"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, stdout=b"clean", stderr=b"")

    monkeypatch.setenv("PROVIDER_API_KEY", "test-only-sensitive-value")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy-credential.invalid")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert provenance._git(Path.cwd(), ["status"]) == b"clean"
    assert captured["argv"] == ["git", "status"]
    assert captured["environment"] == {
        "PATH": provenance.os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
