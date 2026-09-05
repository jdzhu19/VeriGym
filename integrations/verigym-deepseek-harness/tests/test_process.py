from __future__ import annotations

import io
import os
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from verigym_deepseek_harness.config import API_KEY_ENV, BASE_URL_ENV
from verigym_deepseek_harness.process import (
    DeepSeekHarnessProcessError,
    run_harness_helper,
)


class _CompletedHelper:
    def __init__(
        self,
        *,
        stdout: bytes = b'{"ok":true,"events":[],"format_repairs":[],"run_interval_count":0}\n',
        returncode: int = 0,
    ) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO()
        self.pid = os.getpid()
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: int | None = None) -> int:
        del timeout
        return self.returncode


def _settings(tmp_path: Path) -> Any:
    return SimpleNamespace(
        source_root=tmp_path,
        runtime_assets=tmp_path,
        sdk_source_root=tmp_path,
        controller_image_id="sha256:" + "1" * 64,
        max_output_bytes=1024 * 1024,
        process_timeout_s=30,
    )


def test_helper_propagates_only_an_explicit_local_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_path = tmp_path / "docker.sock"
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.bind(str(socket_path))
    observed: dict[str, str] = {}

    def popen(*args: Any, **kwargs: Any) -> _CompletedHelper:
        del args
        observed.update(kwargs["env"])
        return _CompletedHelper()

    monkeypatch.setattr("verigym_deepseek_harness.process.subprocess.Popen", popen)
    monkeypatch.setenv(API_KEY_ENV, "synthetic-key")
    monkeypatch.setenv(BASE_URL_ENV, "http://127.0.0.1:9/v1")
    monkeypatch.setenv("DOCKER_CONTEXT", "untrusted-context")
    monkeypatch.setenv("VERIGYM_UNRELATED_SECRET", "must-not-propagate")
    session_root = tmp_path / "session"
    broker_root = tmp_path / "broker"
    session_root.mkdir()
    broker_root.mkdir()
    try:
        result = run_harness_helper(
            _settings(tmp_path),
            mode="initialize",
            prompt="",
            system_prompt="offline initialization",
            session_id="socket-regression",
            session_root=session_root,
            broker_root=broker_root,
            docker_host=f"unix://{socket_path}",
        )
    finally:
        endpoint.close()

    assert result.run_interval_count == 0
    assert observed["DOCKER_HOST"] == f"unix://{socket_path}"
    assert set(observed) == {
        "PATH",
        "PYTHONPATH",
        "LANG",
        "LC_ALL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DOCKER_HOST",
    }


def test_helper_omits_an_inherited_docker_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, str] = {}

    def popen(*args: Any, **kwargs: Any) -> _CompletedHelper:
        del args
        observed.update(kwargs["env"])
        return _CompletedHelper()

    monkeypatch.setattr("verigym_deepseek_harness.process.subprocess.Popen", popen)
    monkeypatch.setenv(API_KEY_ENV, "synthetic-key")
    monkeypatch.setenv(BASE_URL_ENV, "http://127.0.0.1:9/v1")
    monkeypatch.setenv("DOCKER_HOST", "tcp://untrusted.example:2375")
    session_root = tmp_path / "session"
    broker_root = tmp_path / "broker"
    session_root.mkdir()
    broker_root.mkdir()

    run_harness_helper(
        _settings(tmp_path),
        mode="initialize",
        prompt="",
        system_prompt="offline initialization",
        session_id="unbound-regression",
        session_root=session_root,
        broker_root=broker_root,
    )

    assert "DOCKER_HOST" not in observed


def test_helper_rejects_an_unsafe_explicit_docker_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "synthetic-key")
    monkeypatch.setenv(BASE_URL_ENV, "http://127.0.0.1:9/v1")

    with pytest.raises(DeepSeekHarnessProcessError, match="Docker endpoint is unsafe") as raised:
        run_harness_helper(
            _settings(tmp_path),
            mode="initialize",
            prompt="",
            system_prompt="offline initialization",
            session_id="unsafe-regression",
            session_root=tmp_path,
            broker_root=tmp_path,
            docker_host="tcp://127.0.0.1:2375",
        )

    assert raised.value.category == "docker_endpoint_unsafe"


@pytest.mark.parametrize(
    ("error_type", "category"),
    [
        ("TransportClosedError", "helper_transport_closed"),
        ("JsonRpcError", "helper_json_rpc_error"),
        ("UnexpectedSensitiveName", "helper_unclassified_error"),
    ],
)
def test_helper_failure_exposes_only_a_bounded_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: str,
    category: str,
) -> None:
    payload = ('{"ok":false,"error_type":"' + error_type + '"}\n').encode()
    monkeypatch.setattr(
        "verigym_deepseek_harness.process.subprocess.Popen",
        lambda *_args, **_kwargs: _CompletedHelper(stdout=payload, returncode=1),
    )
    monkeypatch.setenv(API_KEY_ENV, "synthetic-key")
    monkeypatch.setenv(BASE_URL_ENV, "http://127.0.0.1:9/v1")

    with pytest.raises(DeepSeekHarnessProcessError) as raised:
        run_harness_helper(
            _settings(tmp_path),
            mode="initialize",
            prompt="",
            system_prompt="offline initialization",
            session_id="category-regression",
            session_root=tmp_path,
            broker_root=tmp_path,
        )

    assert raised.value.category == category
