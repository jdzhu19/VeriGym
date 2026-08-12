from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _script():
    path = Path("scripts/run_qwen35_online_glibc.py").resolve(strict=True)
    spec = importlib.util.spec_from_file_location("verigym_online_glibc_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_glibc_launcher_validates_portable_identity() -> None:
    module = _script()

    assert module._image_id(f"sha256:{'a' * 64}") == f"sha256:{'a' * 64}"
    with pytest.raises(RuntimeError, match="Docker SHA-256"):
        module._image_id("latest")


def test_glibc_launcher_strips_sensitive_and_loader_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _script()
    monkeypatch.setenv("HF_TOKEN", "not-forwarded")
    monkeypatch.setenv("HTTPS_PROXY", "not-forwarded")
    monkeypatch.setenv("LD_LIBRARY_PATH", "not-forwarded")
    monkeypatch.setenv("LD_PRELOAD", "not-forwarded")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1,0,2,3")

    environment = module._clean_environment()

    assert "HF_TOKEN" not in environment
    assert "HTTPS_PROXY" not in environment
    assert "LD_LIBRARY_PATH" not in environment
    assert "LD_PRELOAD" not in environment
    assert environment["CUDA_VISIBLE_DEVICES"] == "1,0,2,3"


def test_glibc_launcher_sets_a_fixed_runtime_library_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _script()
    monkeypatch.setenv("LD_LIBRARY_PATH", "/untrusted/inherited/path")
    compiler = Path("/opt/gcc/bin/gcc")
    process_tmp = tmp_path / "ipc"
    process_tmp.mkdir(mode=0o700)

    environment = module._runtime_environment(
        Path("/opt/agent/bin/python3.11"), compiler, process_tmp
    )

    assert environment["LD_LIBRARY_PATH"] == "/opt/agent/lib:/usr/lib64"
    assert environment["CC"] == str(compiler)
    assert environment["PATH"].startswith("/opt/gcc/bin:/opt/agent/bin:")
    assert environment["TMPDIR"] == str(process_tmp)


def test_glibc_launcher_requires_private_short_process_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _script()
    process_tmp = tmp_path / "ipc"
    process_tmp.mkdir(mode=0o700)
    monkeypatch.setattr(module.os, "fsencode", lambda _path: b"/short/ipc")

    assert module._private_directory(process_tmp) == process_tmp.resolve()
    process_tmp.chmod(0o755)
    with pytest.raises(RuntimeError, match="private"):
        module._private_directory(process_tmp)


def test_glibc_launcher_never_accepts_source_or_hidden_arguments() -> None:
    source = Path("scripts/run_qwen35_online_glibc.py").read_text(encoding="utf-8")

    assert "--source-root" not in source
    assert "--hidden" not in source
    assert "docker.sock" not in source
