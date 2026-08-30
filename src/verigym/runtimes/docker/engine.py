"""Small Docker CLI transport with bounded, argument-array subprocess calls."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from verigym.runtimes.docker.errors import (
    DockerDaemonError,
    DockerImageError,
    DockerPermissionError,
    DockerUnavailableError,
    sanitize_diagnostic,
)

_CONTAINER_CONTROL_TIMEOUT_S = 60


@dataclass(frozen=True)
class EngineResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    output_truncated: bool = False
    execution_protocol: str | None = None
    phase_durations_s: dict[str, float] = field(default_factory=dict)


class DockerEngine(Protocol):
    backend_type: str

    def version(self) -> dict[str, Any]: ...

    def info(self) -> dict[str, Any]: ...

    def inspect_image(self, reference: str) -> dict[str, Any] | None: ...

    def pull_image(self, reference: str) -> None: ...

    def create_container(self, arguments: list[str]) -> str: ...

    def inspect_container(self, container_id: str) -> dict[str, Any]: ...

    def start_container(self, container_id: str) -> EngineResult: ...

    def wait_container(self, container_id: str, *, timeout_s: int) -> EngineResult: ...

    def logs_container(self, container_id: str, *, max_output_bytes: int) -> EngineResult: ...

    def start_attach_streaming(self, container_id: str) -> subprocess.Popen[bytes]: ...

    def kill_container(self, container_id: str) -> EngineResult: ...

    def remove_container(self, container_id: str, *, force: bool = True) -> EngineResult: ...

    def list_managed_containers(self) -> list[str]: ...

    def list_managed_volumes(self) -> list[str]: ...

    def close(self) -> None: ...


_DETACHED_EXECUTION_PROTOCOL = "docker_detached_start_wait_logs_v1"


def _require_control_success(
    result: EngineResult,
    *,
    action: str,
    timeout_subreason: str,
    failure_subreason: str,
) -> None:
    if result.timed_out:
        raise DockerDaemonError(
            f"Docker {action} timed out",
            subreason=timeout_subreason,
            origin="container_execution",
            details={
                "stage": action,
                "duration_s": result.duration_s,
                "timed_out": True,
                "exit_code": result.exit_code,
            },
        )
    if result.exit_code != 0:
        message = f"Docker {action} failed"
        raise DockerDaemonError(
            message,
            subreason=failure_subreason,
            origin="container_execution",
            details={
                "stage": action,
                "duration_s": result.duration_s,
                "timed_out": False,
                "exit_code": result.exit_code,
            },
        )


def _waited_exit_code(result: EngineResult) -> int:
    raw = result.stdout.strip()
    try:
        exit_code = int(raw)
    except ValueError as exc:
        raise DockerDaemonError(
            "Docker wait returned an invalid container exit code",
            subreason="invalid_daemon_response",
            origin="container_execution",
            details={"stage": "container wait exit-code validation"},
        ) from exc
    if exit_code < 0 or exit_code > 255:
        raise DockerDaemonError(
            "Docker wait returned an out-of-range container exit code",
            subreason="invalid_daemon_response",
            origin="container_execution",
            details={"stage": "container wait exit-code validation"},
        )
    return exit_code


def execute_container(
    engine: DockerEngine,
    container_id: str,
    *,
    timeout_s: int,
    max_output_bytes: int,
) -> EngineResult:
    """Run a created non-interactive container with phase-specific deadlines.

    Container startup is a bounded control-plane operation. The candidate wall clock starts only
    after startup succeeds, and output is collected through a separate bounded logs call after the
    container exits. This avoids coupling command runtime to Docker's attach-stream teardown.
    """

    started_at = time.monotonic()
    phase_durations: dict[str, float] = {}

    start = engine.start_container(container_id)
    phase_durations["start"] = start.duration_s
    _require_control_success(
        start,
        action="container start",
        timeout_subreason="container_start_timeout",
        failure_subreason="container_start_failed",
    )

    wait = engine.wait_container(container_id, timeout_s=timeout_s)
    phase_durations["wait"] = wait.duration_s
    timed_out = wait.timed_out
    if timed_out:
        kill = engine.kill_container(container_id)
        phase_durations["kill"] = kill.duration_s
        _require_control_success(
            kill,
            action="container kill after command timeout",
            timeout_subreason="container_kill_timeout",
            failure_subreason="container_kill_failed",
        )
        settled = engine.wait_container(
            container_id,
            timeout_s=_CONTAINER_CONTROL_TIMEOUT_S,
        )
        phase_durations["post_timeout_wait"] = settled.duration_s
        _require_control_success(
            settled,
            action="container wait after command timeout",
            timeout_subreason="container_wait_cleanup_timeout",
            failure_subreason="container_wait_cleanup_failed",
        )
        exit_code = _waited_exit_code(settled)
    else:
        _require_control_success(
            wait,
            action="container wait",
            timeout_subreason="container_wait_timeout",
            failure_subreason="container_wait_failed",
        )
        exit_code = _waited_exit_code(wait)

    logs = engine.logs_container(container_id, max_output_bytes=max_output_bytes)
    phase_durations["logs"] = logs.duration_s
    _require_control_success(
        logs,
        action="container logs",
        timeout_subreason="container_logs_timeout",
        failure_subreason="container_logs_failed",
    )
    return EngineResult(
        argv=["docker", "start/wait/logs", container_id],
        exit_code=exit_code,
        stdout=logs.stdout,
        stderr=logs.stderr,
        duration_s=time.monotonic() - started_at,
        timed_out=timed_out,
        output_truncated=logs.output_truncated,
        execution_protocol=_DETACHED_EXECUTION_PROTOCOL,
        phase_durations_s=phase_durations,
    )


class DockerCliEngine:
    """Docker Engine transport implemented solely through the Docker CLI."""

    backend_type = "docker_cli"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("docker")
        self._closed = False

    def _invoke(
        self,
        arguments: list[str],
        *,
        timeout_s: int,
        max_output_bytes: int = 1024 * 1024,
    ) -> EngineResult:
        if self._closed:
            raise DockerUnavailableError(
                "Docker CLI transport is closed",
                subreason="backend_closed",
            )
        if self.executable is None:
            raise DockerUnavailableError(
                "Docker CLI is not installed or is not on PATH",
                subreason="missing_cli",
            )
        argv = [self.executable, *arguments]
        started = time.monotonic()
        timed_out = False
        exit_code: int | None = None
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=environment,
                    shell=False,
                    text=False,
                    start_new_session=True,
                )
                try:
                    process.communicate(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            exit_code = None
                exit_code = process.returncode
            except FileNotFoundError as exc:
                raise DockerUnavailableError(
                    "Docker CLI disappeared before execution",
                    subreason="missing_cli",
                ) from exc
            except OSError as exc:
                raise DockerUnavailableError(
                    sanitize_diagnostic(f"Docker CLI could not start: {exc}"),
                    subreason="cli_launch_failed",
                ) from exc
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout_bytes = stdout_file.read(max_output_bytes + 1)
            stderr_bytes = stderr_file.read(max_output_bytes + 1)
        truncated = len(stdout_bytes) > max_output_bytes or len(stderr_bytes) > max_output_bytes
        return EngineResult(
            argv=["docker", *arguments],
            exit_code=exit_code,
            stdout=stdout_bytes[:max_output_bytes].decode("utf-8", errors="replace"),
            stderr=stderr_bytes[:max_output_bytes].decode("utf-8", errors="replace"),
            duration_s=time.monotonic() - started,
            timed_out=timed_out,
            output_truncated=truncated,
        )

    @staticmethod
    def _raise_control_error(result: EngineResult, *, action: str) -> None:
        detail = sanitize_diagnostic((result.stderr or result.stdout).strip())
        message = f"Docker {action} failed"
        if detail:
            message += f": {detail}"
        lowered = detail.lower()
        if "permission denied" in lowered or "access denied" in lowered:
            raise DockerPermissionError(message, subreason="permission_denied")
        raise DockerDaemonError(message, subreason=f"{action}_failed")

    def version(self) -> dict[str, Any]:
        result = self._invoke(["version", "--format", "{{json .}}"], timeout_s=10)
        if result.timed_out:
            raise DockerDaemonError("Docker version request timed out", subreason="daemon_timeout")
        if result.exit_code != 0:
            self._raise_control_error(result, action="version")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DockerDaemonError(
                "Docker version response was not valid JSON",
                subreason="invalid_daemon_response",
            ) from exc
        if not isinstance(payload, dict):
            raise DockerDaemonError(
                "Docker version response has an unexpected shape",
                subreason="invalid_daemon_response",
            )
        return payload

    def info(self) -> dict[str, Any]:
        result = self._invoke(["info", "--format", "{{json .}}"], timeout_s=10)
        if result.timed_out:
            raise DockerDaemonError("Docker info request timed out", subreason="daemon_timeout")
        if result.exit_code != 0:
            self._raise_control_error(result, action="info")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DockerDaemonError(
                "Docker info response was not valid JSON",
                subreason="invalid_daemon_response",
            ) from exc
        if not isinstance(payload, dict):
            raise DockerDaemonError(
                "Docker info response has an unexpected shape",
                subreason="invalid_daemon_response",
            )
        return payload

    def inspect_image(self, reference: str) -> dict[str, Any] | None:
        result = self._invoke(["image", "inspect", reference], timeout_s=15)
        if result.timed_out:
            raise DockerDaemonError("Docker image inspection timed out", subreason="daemon_timeout")
        if result.exit_code != 0:
            detail = sanitize_diagnostic((result.stderr or result.stdout).strip())
            if "no such image" in detail.lower() or "not found" in detail.lower():
                return None
            self._raise_control_error(result, action="image_inspect")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DockerImageError(
                "Docker image inspection returned invalid JSON",
                subreason="invalid_image_metadata",
            ) from exc
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise DockerImageError(
                "Docker image inspection returned an unexpected result",
                subreason="invalid_image_metadata",
            )
        return payload[0]

    def pull_image(self, reference: str) -> None:
        result = self._invoke(["pull", reference], timeout_s=600, max_output_bytes=2 * 1024 * 1024)
        if result.timed_out:
            raise DockerImageError("Docker image pull timed out", subreason="image_pull_timeout")
        if result.exit_code != 0:
            detail = sanitize_diagnostic((result.stderr or result.stdout).strip())
            raise DockerImageError(
                f"Docker image pull failed: {detail}" if detail else "Docker image pull failed",
                subreason="image_pull_failed",
            )

    def create_container(self, arguments: list[str]) -> str:
        result = self._invoke(
            ["create", *arguments],
            timeout_s=_CONTAINER_CONTROL_TIMEOUT_S,
        )
        if result.timed_out:
            raise DockerDaemonError(
                "Docker container creation timed out",
                subreason="container_create_timeout",
            )
        if result.exit_code != 0:
            self._raise_control_error(result, action="container_create")
        container_id = result.stdout.strip()
        if not container_id:
            raise DockerDaemonError(
                "Docker create returned no container ID",
                subreason="invalid_daemon_response",
            )
        return container_id

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        result = self._invoke(
            ["inspect", container_id],
            timeout_s=_CONTAINER_CONTROL_TIMEOUT_S,
        )
        if result.timed_out:
            raise DockerDaemonError(
                "Docker container inspection timed out",
                subreason="container_inspect_timeout",
            )
        if result.exit_code != 0:
            self._raise_control_error(result, action="container_inspect")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DockerDaemonError(
                "Docker container inspection returned invalid JSON",
                subreason="invalid_daemon_response",
            ) from exc
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise DockerDaemonError(
                "Docker container inspection returned an unexpected result",
                subreason="invalid_daemon_response",
            )
        return payload[0]

    def start_container(self, container_id: str) -> EngineResult:
        return self._invoke(
            ["start", container_id],
            timeout_s=_CONTAINER_CONTROL_TIMEOUT_S,
        )

    def wait_container(self, container_id: str, *, timeout_s: int) -> EngineResult:
        return self._invoke(
            ["wait", container_id],
            timeout_s=timeout_s,
            max_output_bytes=64 * 1024,
        )

    def logs_container(self, container_id: str, *, max_output_bytes: int) -> EngineResult:
        return self._invoke(
            ["logs", container_id],
            timeout_s=_CONTAINER_CONTROL_TIMEOUT_S,
            max_output_bytes=max_output_bytes,
        )

    def start_attach_streaming(self, container_id: str) -> subprocess.Popen[bytes]:
        """Attach a bounded-protocol broker to an interactive managed container."""

        if self._closed:
            raise DockerUnavailableError(
                "Docker CLI transport is closed",
                subreason="backend_closed",
            )
        if self.executable is None:
            raise DockerUnavailableError(
                "Docker CLI is not installed or is not on PATH",
                subreason="missing_cli",
            )
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        try:
            return subprocess.Popen(
                [
                    self.executable,
                    "start",
                    "--attach",
                    "--interactive",
                    container_id,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                shell=False,
                text=False,
                start_new_session=True,
                close_fds=True,
            )
        except FileNotFoundError as exc:
            raise DockerUnavailableError(
                "Docker CLI disappeared before streaming attach",
                subreason="missing_cli",
            ) from exc
        except OSError as exc:
            raise DockerUnavailableError(
                sanitize_diagnostic(f"Docker streaming attach could not start: {exc}"),
                subreason="cli_launch_failed",
            ) from exc

    def kill_container(self, container_id: str) -> EngineResult:
        return self._invoke(
            ["kill", container_id],
            timeout_s=_CONTAINER_CONTROL_TIMEOUT_S,
        )

    def remove_container(self, container_id: str, *, force: bool = True) -> EngineResult:
        arguments = ["rm"]
        if force:
            arguments.append("--force")
        arguments.append(container_id)
        return self._invoke(arguments, timeout_s=_CONTAINER_CONTROL_TIMEOUT_S)

    def _list_values(self, noun: str, template: str) -> list[str]:
        result = self._invoke(
            [
                noun,
                "ls",
                "--filter",
                "label=org.verigym.managed=true",
                "--format",
                template,
            ],
            timeout_s=_CONTAINER_CONTROL_TIMEOUT_S,
        )
        if result.exit_code != 0 or result.timed_out:
            self._raise_control_error(result, action=f"{noun}_list")
        return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())

    def list_managed_containers(self) -> list[str]:
        result = self._invoke(
            [
                "ps",
                "--all",
                "--filter",
                "label=org.verigym.managed=true",
                "--format",
                "{{.ID}}",
            ],
            timeout_s=_CONTAINER_CONTROL_TIMEOUT_S,
        )
        if result.exit_code != 0 or result.timed_out:
            self._raise_control_error(result, action="container_list")
        return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())

    def list_managed_volumes(self) -> list[str]:
        return self._list_values("volume", "{{.Name}}")

    def close(self) -> None:
        self._closed = True


__all__ = ["DockerCliEngine", "DockerEngine", "EngineResult", "execute_container"]
