from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
from pathlib import Path

import pytest
from verigym_codex_cli.capabilities import (
    CapabilityError,
    discover_capabilities,
)
from verigym_codex_cli.cli import main
from verigym_codex_cli.process import CodexCliProcessRunner, resolve_executable

pytestmark = pytest.mark.codex_cli


def test_capability_discovery_is_exact_and_zero_call(
    fake_codex: tuple[Path, Path, object],
) -> None:
    executable, log, _scenario = fake_codex
    identity, report = discover_capabilities(force=True)
    assert report.executable_sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()
    assert report.version_output == "fake-codex 1.2.3"
    assert report.model_call_count == 0
    assert report.diagnostic_process_count == 3
    assert report.machine_output_flag == "--json"
    assert {"read-only", "workspace-write"} <= set(report.supported_sandbox_modes)
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert {record["kind"] for record in records} == {"diagnostic"}
    assert identity.sha256 == report.executable_sha256


@pytest.mark.parametrize(
    "scenario",
    [
        "unsupported_json",
        "unsupported_noninteractive",
        "unsupported_sandbox",
        "unsupported_ephemeral",
    ],
)
def test_unsupported_capability_fails_before_model_invocation(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    _executable, log, _setter = fake_codex
    monkeypatch.setenv("VERIGYM_FAKE_CODEX_SCENARIO", scenario)
    with pytest.raises(CapabilityError):
        discover_capabilities(force=True)
    if log.is_file():
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert all(record["kind"] == "diagnostic" for record in records)


def test_doctor_writes_sealed_report_without_model_call(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, _scenario = fake_codex
    output = tmp_path / "codex_cli_capabilities.json"
    main(["doctor", "--json", str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["model_call_count"] == 0
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert sum(record["kind"] == "model" for record in records) == 0


def test_process_runner_explicitly_disables_shell() -> None:
    source = inspect.getsource(CodexCliProcessRunner.run)
    assert "shell=False" in source
    assert "start_new_session=True" in source
    assert "bash -lc" not in source


def test_process_runner_kills_the_process_group_when_the_broker_cancels(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("timeout")
    cwd = tmp_path / "cwd-cancel"
    cwd.mkdir()
    cancellation = threading.Event()
    timer = threading.Timer(0.1, cancellation.set)
    timer.start()
    started = time.monotonic()
    try:
        result = CodexCliProcessRunner(
            resolve_executable(),
            auth_mode="inherited_codex_login",
        ).run(
            ["exec"],
            cwd=cwd,
            timeout_s=10,
            stdin_bytes=b"bounded prompt",
            cancellation_event=cancellation,
        )
    finally:
        timer.cancel()

    assert time.monotonic() - started < 3
    assert result.broker_cancelled is True
    assert result.timed_out is False
    assert result.process_group_cleaned is True


def test_sealed_report_rejects_executable_substitution(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    executable, _log, _scenario = fake_codex
    _identity, report = discover_capabilities(force=True)
    sealed = tmp_path / "capabilities.json"
    sealed.write_text(json.dumps(report.safe_dict()), encoding="utf-8")
    replacement = tmp_path / "fake_codex_replacement.py"
    replacement.write_text("#!/usr/bin/env python3\nprint('different')\n", encoding="utf-8")
    replacement.chmod(0o755)
    from verigym_codex_cli.capabilities import load_capability_report

    with pytest.raises(CapabilityError):
        load_capability_report(sealed, resolve_executable(str(replacement)))
