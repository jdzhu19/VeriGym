from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _script():
    path = Path("scripts/run_qwen35_online_proot.py").resolve(strict=True)
    spec = importlib.util.spec_from_file_location("verigym_online_proot_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_proot_launcher_validates_portable_identities(tmp_path: Path) -> None:
    module = _script()

    assert module._image_id(f"sha256:{'a' * 64}") == f"sha256:{'a' * 64}"
    with pytest.raises(RuntimeError, match="Docker SHA-256"):
        module._image_id("latest")


def test_proot_launcher_never_accepts_source_or_hidden_arguments() -> None:
    source = Path("scripts/run_qwen35_online_proot.py").read_text(encoding="utf-8")

    assert "--source-root" not in source
    assert "--hidden" not in source
    assert "docker.sock" not in source
    assert 'environment["PROOT_NO_SECCOMP"] = "1"' in source


def test_proot_launcher_strips_credentials_and_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _script()
    monkeypatch.setenv("HF_TOKEN", "not-forwarded")
    monkeypatch.setenv("HTTPS_PROXY", "not-forwarded")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1,0,2,3")

    environment = module._clean_environment()

    assert "HF_TOKEN" not in environment
    assert "HTTPS_PROXY" not in environment
    assert environment["CUDA_VISIBLE_DEVICES"] == "1,0,2,3"
