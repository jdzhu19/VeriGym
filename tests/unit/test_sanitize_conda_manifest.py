from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "sanitize_conda_explicit_manifest.py"
    spec = importlib.util.spec_from_file_location("sanitize_conda_explicit_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conda_manifest_sanitizer_removes_url_credentials_and_tokens() -> None:
    sanitize = _module().sanitize_explicit_line
    raw = "https://user:secret@example.test/t/private-token/pkg.conda?token=value#" + "a" * 64

    sanitized = sanitize(raw)

    assert "user" not in sanitized
    assert "secret" not in sanitized
    assert "private-token" not in sanitized
    assert "value" not in sanitized
    assert sanitized == ("https://example.test/t/REDACTED/pkg.conda?token=REDACTED#" + "a" * 64)


def test_conda_manifest_sanitizer_rejects_non_url_entries() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _module().sanitize_explicit_line("not-a-package-url")
