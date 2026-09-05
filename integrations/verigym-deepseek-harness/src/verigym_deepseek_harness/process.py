"""Bounded launch of the sanitized DeepSeek Harness SDK helper."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.runtimes.docker.engine import validate_local_docker_host

from .config import API_KEY_ENV, BASE_URL_ENV, DeepSeekHarnessSettings


class DeepSeekHarnessProcessError(RuntimeError):
    """The helper/controller boundary failed before a valid Harness result."""

    def __init__(self, message: str, *, category: str = "process_failure") -> None:
        super().__init__(message)
        self.category = category


_HELPER_ERROR_CATEGORIES = {
    "FileNotFoundError": "helper_file_not_found",
    "JsonRpcError": "helper_json_rpc_error",
    "OSError": "helper_os_error",
    "PermissionError": "helper_permission_error",
    "RuntimeError": "helper_runtime_error",
    "SdkProtocolError": "helper_sdk_protocol_error",
    "TimeoutError": "helper_timeout_error",
    "TransportClosedError": "helper_transport_closed",
    "ValueError": "helper_value_error",
}


@dataclass(frozen=True)
class DeepSeekHarnessProcessResult:
    events: tuple[dict[str, Any], ...]
    session_id: str
    finish_reason: str | None
    final_response: str
    duration_s: float
    helper_exit_code: int
    stdout_bytes: int
    stderr_bytes: int
    format_repairs: tuple[str, ...]
    run_interval_count: int
    provider_request_started: bool


_PROVIDER_MARKER_NAME = "provider-request-started-v1.json"
_PROVIDER_MARKER_VALUE = {
    "format_id": "verigym_deepseek_harness_provider_request_started_v1",
    "provider_request_ordinal": 1,
}


def provider_request_started(session_root: Path) -> bool:
    """Validate the private first-request marker without retaining provider data."""

    marker = session_root / _PROVIDER_MARKER_NAME
    try:
        metadata = os.lstat(marker)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 256:
        raise DeepSeekHarnessProcessError("DeepSeek Harness provider marker is unsafe")
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeepSeekHarnessProcessError("DeepSeek Harness provider marker is malformed") from exc
    if value != _PROVIDER_MARKER_VALUE:
        raise DeepSeekHarnessProcessError("DeepSeek Harness provider marker identity changed")
    return True


def run_harness_helper(
    settings: DeepSeekHarnessSettings,
    *,
    mode: str,
    prompt: str,
    system_prompt: str,
    session_id: str,
    session_root: Path,
    broker_root: Path,
    max_format_repairs: int = 0,
    docker_host: str | None = None,
) -> DeepSeekHarnessProcessResult:
    payload = {
        "mode": mode,
        "prompt": prompt,
        "system_prompt": system_prompt,
        "session_id": session_id,
        "source_root": str(settings.source_root),
        "runtime_assets": str(settings.runtime_assets),
        "session_root": str(session_root),
        "broker_root": str(broker_root),
        "controller_image_id": settings.controller_image_id,
        "max_format_repairs": max_format_repairs,
    }
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > 4 * 1024 * 1024:
        raise DeepSeekHarnessProcessError("DeepSeek Harness helper request is oversized")
    environment = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONPATH": str(settings.sdk_source_root),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "DEEPSEEK_API_KEY": os.environ[API_KEY_ENV],
        "DEEPSEEK_BASE_URL": os.environ[BASE_URL_ENV],
    }
    if docker_host is not None:
        try:
            environment["DOCKER_HOST"] = validate_local_docker_host(docker_host)
        except ValueError as exc:
            raise DeepSeekHarnessProcessError(
                "DeepSeek Harness Docker endpoint is unsafe",
                category="docker_endpoint_unsafe",
            ) from exc
    helper = Path(__file__).with_name("helper.py").resolve(strict=True)
    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, str(helper)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=settings.source_root,
        env=environment,
        start_new_session=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdin.write(encoded)
    process.stdin.close()
    overflow = threading.Event()
    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []
    stdout_thread = threading.Thread(
        target=_read_bounded,
        args=(process.stdout, stdout_parts, settings.max_output_bytes, overflow),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_bounded,
        args=(process.stderr, stderr_parts, 1024 * 1024, overflow),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    deadline = started + settings.process_timeout_s
    timed_out = False
    while process.poll() is None:
        if overflow.wait(timeout=0.1):
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
    if process.poll() is None:
        _kill_process_group(process.pid)
    exit_code = process.wait(timeout=10)
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    stdout = b"".join(stdout_parts)
    stderr = b"".join(stderr_parts)
    if timed_out:
        raise DeepSeekHarnessProcessError(
            "DeepSeek Harness helper timed out", category="helper_timeout"
        )
    if overflow.is_set():
        raise DeepSeekHarnessProcessError(
            "DeepSeek Harness helper exceeded its output bound",
            category="helper_output_oversized",
        )
    try:
        value = json.loads(stdout)
    except Exception as exc:
        raise DeepSeekHarnessProcessError(
            "DeepSeek Harness helper returned malformed JSON",
            category="helper_malformed_json",
        ) from exc
    if not isinstance(value, dict) or value.get("ok") is not True or exit_code != 0:
        error_type = value.get("error_type") if isinstance(value, dict) else None
        label = error_type if isinstance(error_type, str) else "unknown_error"
        raise DeepSeekHarnessProcessError(
            f"DeepSeek Harness helper failed closed: {label}",
            category=_HELPER_ERROR_CATEGORIES.get(label, "helper_unclassified_error"),
        )
    events = value.get("events")
    if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
        raise DeepSeekHarnessProcessError(
            "DeepSeek Harness helper events are malformed",
            category="helper_events_malformed",
        )
    observed_session = value.get("session_id", session_id)
    finish_reason = value.get("finish_reason")
    final_response = value.get("final_response", "")
    format_repairs = value.get("format_repairs", [])
    run_interval_count = value.get("run_interval_count", 0 if mode == "initialize" else 1)
    if (
        observed_session != session_id
        or (finish_reason is not None and not isinstance(finish_reason, str))
        or not isinstance(final_response, str)
        or not isinstance(format_repairs, list)
        or not all(isinstance(item, str) for item in format_repairs)
        or not isinstance(run_interval_count, int)
        or run_interval_count < 0
        or run_interval_count != (0 if mode == "initialize" else 1 + len(format_repairs))
    ):
        raise DeepSeekHarnessProcessError(
            "DeepSeek Harness helper result identity changed",
            category="helper_result_identity_changed",
        )
    provider_started = provider_request_started(session_root)
    if provider_started is not (mode == "run"):
        raise DeepSeekHarnessProcessError(
            "DeepSeek Harness provider marker state changed",
            category="provider_marker_state_changed",
        )
    return DeepSeekHarnessProcessResult(
        events=tuple(dict(event) for event in events),
        session_id=session_id,
        finish_reason=finish_reason,
        final_response=final_response,
        duration_s=time.monotonic() - started,
        helper_exit_code=exit_code,
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
        format_repairs=tuple(format_repairs),
        run_interval_count=run_interval_count,
        provider_request_started=provider_started,
    )


def _read_bounded(
    stream: Any,
    destination: list[bytes],
    limit: int,
    overflow: threading.Event,
) -> None:
    observed = 0
    while block := stream.read(65_536):
        observed += len(block)
        if observed > limit:
            overflow.set()
            return
        destination.append(block)


def _kill_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


__all__ = [
    "DeepSeekHarnessProcessError",
    "DeepSeekHarnessProcessResult",
    "provider_request_started",
    "run_harness_helper",
]
