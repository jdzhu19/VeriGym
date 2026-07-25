from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

INTEGRATION_ROOT = Path(__file__).resolve().parents[2] / "integrations" / "verigym-codex-cli"
sys.path.insert(0, str(INTEGRATION_ROOT / "src"))

from verigym_codex_cli.capabilities import clear_capability_cache  # noqa: E402


@pytest.fixture
def fake_codex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, Callable[[str], None]]:
    executable = INTEGRATION_ROOT / "tests" / "fake_codex.py"
    executable.chmod(0o755)
    log = tmp_path / "fake-codex-calls.jsonl"
    monkeypatch.setenv("VERIGYM_CODEX_BINARY", str(executable))
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "inherited_codex_login")
    monkeypatch.setenv("VERIGYM_CODEX_TEST_MODE", "1")
    monkeypatch.setenv("VERIGYM_FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("VERIGYM_FAKE_CODEX_SCENARIO", "valid")
    clear_capability_cache()

    def scenario(name: str) -> None:
        monkeypatch.setenv("VERIGYM_FAKE_CODEX_SCENARIO", name)

    return executable, log, scenario
