"""Auditable non-interactive Docker container lifecycle helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verigym.runtimes.docker.engine import DockerEngine, EngineResult
from verigym.runtimes.docker.errors import DockerContainerError, DockerDaemonError


@dataclass(frozen=True)
class ContainerExecution:
    """Output and final state after a separate start, wait, inspect, and logs flow."""

    logs: EngineResult
    state: dict[str, Any]
    timed_out: bool
    start_duration_s: float
    wait_duration_s: float
    logs_duration_s: float


def execute_created_container(
    engine: DockerEngine,
    container_id: str,
    *,
    timeout_s: int,
    max_output_bytes: int,
) -> ContainerExecution:
    """Execute a verified created container and distinguish process from control timeouts."""

    started = engine.start_container(container_id)
    waited = engine.wait_container(container_id, timeout_s=timeout_s)
    timed_out = waited.timed_out
    if waited.timed_out:
        timeout_inspection = engine.inspect_container(container_id)
        timeout_state = _state(timeout_inspection)
        if timeout_state.get("Status") == "exited":
            raise DockerDaemonError(
                "Docker wait timed out after the container had already exited",
                subreason="container_wait_timeout_after_exit",
            )
        killed = engine.kill_container(container_id)
        if killed.timed_out or killed.exit_code != 0:
            raise DockerDaemonError(
                "Docker could not stop a command container after its process deadline",
                subreason="container_kill_failed",
            )
    elif waited.exit_code != 0:
        raise DockerDaemonError(
            "Docker wait failed before returning the container status",
            subreason="container_wait_failed",
        )

    inspection = engine.inspect_container(container_id)
    state = _state(inspection)
    state_status = state.get("Status")
    state_error = state.get("Error")
    if state_status != "exited" or (isinstance(state_error, str) and state_error):
        raise DockerContainerError(
            "Docker could not complete the command container",
            subreason="container_start_failed",
            details={"state": state_status},
        )
    logs = engine.container_logs(container_id, max_output_bytes=max_output_bytes)
    return ContainerExecution(
        logs=logs,
        state=state,
        timed_out=timed_out,
        start_duration_s=started.duration_s,
        wait_duration_s=waited.duration_s,
        logs_duration_s=logs.duration_s,
    )


def _state(inspection: dict[str, Any]) -> dict[str, Any]:
    value = inspection.get("State")
    return value if isinstance(value, dict) else {}


__all__ = ["ContainerExecution", "execute_created_container"]
