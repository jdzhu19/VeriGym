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


def test_hpc_scripts_execute_stdin_python_inside_the_selected_conda_environment() -> None:
    scripts = Path(__file__).parents[2] / "scripts"
    inventory = (scripts / "hpc_inventory_training_env.sh").read_text(encoding="utf-8")
    prepare = (scripts / "hpc_prepare_multiturn_environments.sh").read_text(encoding="utf-8")

    assert "conda_executable=${CONDA_EXE:-$(command -v conda || true)}" in inventory
    assert '"$conda_executable" run --no-capture-output -n agent python -' in inventory
    assert 'git -C "$rllm_checkout"' not in prepare
    assert "Docker is unavailable on this compute node" in prepare
    assert "pip install --upgrade" not in prepare
    assert '"vllm==0.22.1"' not in prepare
    assert '"verl==0.8.0"' not in prepare
    assert (
        '"$conda_executable" run --no-capture-output -n verigym-openhands-py312 python -' in prepare
    )
