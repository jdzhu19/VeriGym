"""Fail-closed command execution in one reusable, networkless episode container."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from verigym.runtimes.docker.engine import DockerEngine, EngineResult
from verigym.runtimes.docker.errors import (
    DockerContainerError,
    DockerDaemonError,
    DockerRuntimeError,
    sanitize_diagnostic,
)
from verigym.runtimes.docker.external_command import (
    command_environment,
    command_image_runtime_config,
)
from verigym.runtimes.docker.mounts import MountSpec, mount_arguments
from verigym.runtimes.docker.resources import (
    effective_timeout,
    resource_arguments,
    resource_summary,
)
from verigym.runtimes.docker.security import security_arguments, verify_effective_container
from verigym.schemas.common import RuntimeImageIdentity
from verigym.schemas.runtime import DockerCommandImageRuntimeConfig
from verigym.schemas.tool import CommandSpec, CompletedCommand

_KEEPALIVE_ARGV = ["/usr/bin/tail", "-f", "/dev/null"]
_EXECUTION_PROTOCOL = "docker_episode_container_exec_v1"


class DockerEpisodeCommandExecutor:
    """Reuse one immutable command container and reject leaked background processes."""

    def __init__(
        self,
        *,
        engine: DockerEngine,
        image: RuntimeImageIdentity,
        config: DockerCommandImageRuntimeConfig,
        run_id: str,
        session_id: str,
        register_container: Callable[[str], None],
        remove_container: Callable[[str], str | None],
    ) -> None:
        if config.execution_backend != "episode_container_exec_v1":
            raise ValueError("persistent command executor requires episode_container_exec_v1")
        self._engine = engine
        self._image = image
        self._config = config
        self._run_id = run_id
        self._session_id = session_id
        self._register_container = register_container
        self._remove_container = remove_container
        self._container_id: str | None = None
        self._baseline_processes: tuple[tuple[int, int, str], ...] | None = None
        self._poisoned = False
        self._startup_duration_s = 0.0
        self._command_count = 0

    def execute(self, command: CommandSpec, *, mounts: list[MountSpec]) -> CompletedCommand:
        _validate_command(command)
        started = time.monotonic()
        if self._poisoned:
            return self._failure(
                command,
                started=started,
                reason="episode_container_poisoned",
                origin="control_plane",
                error="episode command container was invalidated by an earlier command",
            )
        try:
            reused = self._container_id is not None
            self._ensure_started(mounts)
            assert self._container_id is not None
            assert self._baseline_processes is not None
            container_id = self._container_id
            environment = command_environment(self._config)
            logical_cwd = self._config.logical_workspace_root + (
                "" if command.cwd == "." else f"/{command.cwd}"
            )
            timeout_s = effective_timeout(command.timeout_s, self._config.max_command_time_s)
            execution = self._engine.exec_container(
                container_id,
                argv=list(command.argv),
                user=self._config.run_as_user,
                cwd=logical_cwd,
                environment=environment,
                timeout_s=timeout_s,
                max_output_bytes=self._config.max_output_bytes,
            )
            self._command_count += 1
            if execution.timed_out:
                cleanup_warning = self._invalidate(kill_running=True)
                completed = self._completed(
                    command,
                    started=started,
                    execution=execution,
                    exit_code=None,
                    timed_out=True,
                    oom_killed=False,
                    reason="timeout",
                    origin="candidate_process",
                    reused=reused,
                    effective_timeout_s=timeout_s,
                    container_id=container_id,
                )
                return _apply_cleanup_failure(completed, cleanup_warning)

            state = _container_state(self._engine.inspect_container(container_id))
            # Docker does not consistently project exec-process OOM kills onto the container's
            # State.OOMKilled bit. Exit 137 is conservatively treated as OOM/forced-kill evidence
            # and invalidates the reusable container instead of risking cross-command drift.
            oom_killed = state.get("OOMKilled") is True or execution.exit_code == 137
            state_error = state.get("Error")
            if oom_killed:
                cleanup_warning = self._invalidate(kill_running=state.get("Status") == "running")
                completed = self._completed(
                    command,
                    started=started,
                    execution=execution,
                    exit_code=execution.exit_code,
                    timed_out=False,
                    oom_killed=True,
                    reason="out_of_memory",
                    origin="candidate_process",
                    reused=reused,
                    effective_timeout_s=timeout_s,
                    container_id=container_id,
                )
                return _apply_cleanup_failure(completed, cleanup_warning)
            if state.get("Status") != "running" or (isinstance(state_error, str) and state_error):
                cleanup_warning = self._invalidate(kill_running=False)
                completed = self._completed(
                    command,
                    started=started,
                    execution=execution,
                    exit_code=execution.exit_code,
                    timed_out=False,
                    oom_killed=False,
                    reason="episode_container_stopped",
                    origin="candidate_process",
                    reused=reused,
                    effective_timeout_s=timeout_s,
                    container_id=container_id,
                )
                return _apply_cleanup_failure(completed, cleanup_warning)

            observed = _process_fingerprint(self._engine.top_container(container_id))
            if observed != self._baseline_processes:
                expected_process_count = len(self._baseline_processes)
                cleanup_warning = self._invalidate(kill_running=True)
                completed = self._completed(
                    command,
                    started=started,
                    execution=execution,
                    exit_code=execution.exit_code,
                    timed_out=False,
                    oom_killed=False,
                    reason="residual_process_detected",
                    origin="candidate_process",
                    reused=reused,
                    effective_timeout_s=timeout_s,
                    container_id=container_id,
                )
                completed.metadata["process_inventory"] = {
                    "expected_count": expected_process_count,
                    "observed_count": len(observed),
                    "raw_process_data_persisted": False,
                }
                return _apply_cleanup_failure(completed, cleanup_warning)

            return self._completed(
                command,
                started=started,
                execution=execution,
                exit_code=execution.exit_code,
                timed_out=False,
                oom_killed=False,
                reason=None,
                origin=None,
                reused=reused,
                effective_timeout_s=timeout_s,
                container_id=container_id,
            )
        except DockerRuntimeError as exc:
            failed_container_id = self._container_id
            cleanup_warning = self._invalidate(kill_running=True)
            completed = self._failure(
                command,
                started=started,
                reason=exc.subreason,
                origin=(
                    "candidate_process" if exc.origin == "candidate_process" else "control_plane"
                ),
                error=sanitize_diagnostic(str(exc), sensitive_paths=(str(Path.home()),)),
                container_id=failed_container_id,
                metadata={"origin": exc.origin, **dict(exc.details)},
            )
            return _apply_cleanup_failure(completed, cleanup_warning)

    def close(self) -> str | None:
        """Destroy the reusable container; future commands remain fail closed."""

        return self._invalidate(kill_running=True)

    def _ensure_started(self, mounts: list[MountSpec]) -> None:
        if self._container_id is not None:
            return
        runtime_config = command_image_runtime_config(self._config)
        environment = command_environment(self._config)
        labels = {
            "org.verigym.managed": "true",
            "org.verigym.run_id": self._run_id,
            "org.verigym.session_id": self._session_id,
            "org.verigym.role": "external-agent-command-episode",
            "org.verigym.external_protocol": self._config.protocol,
        }
        user = self._image.effective_user
        if user is None or user != self._config.run_as_user:
            raise DockerContainerError(
                "command image user identity changed",
                subreason="command_image_user_identity_changed",
            )
        arguments = [
            *security_arguments(
                runtime_config,
                user=user,
                cwd=self._config.logical_workspace_root,
                environment=environment,
                labels=labels,
            ),
            *resource_arguments(runtime_config),
            *mount_arguments(mounts),
            self._image.resolved_image_id,
            *_KEEPALIVE_ARGV,
        ]
        started = time.monotonic()
        container_id = self._engine.create_container(arguments)
        self._container_id = container_id
        self._register_container(container_id)
        inspection = self._engine.inspect_container(container_id)
        verify_effective_container(
            inspection,
            config=runtime_config,
            expected_user=user,
            expected_mounts=mounts,
            expected_environment=environment,
            expected_labels=labels,
        )
        start = self._engine.start_container(container_id)
        _require_control_success(start, "episode container start", "episode_container_start_failed")
        state = _container_state(self._engine.inspect_container(container_id))
        if state.get("Status") != "running":
            raise DockerContainerError(
                "episode command container did not remain running",
                subreason="episode_container_start_failed",
            )
        baseline = _process_fingerprint(self._engine.top_container(container_id))
        if not baseline or not any(process[2] == "tail" for process in baseline):
            raise DockerContainerError(
                "episode command container has an invalid keepalive process inventory",
                subreason="episode_process_inventory_invalid",
            )
        self._baseline_processes = baseline
        self._startup_duration_s = time.monotonic() - started

    def _completed(
        self,
        command: CommandSpec,
        *,
        started: float,
        execution: EngineResult,
        exit_code: int | None,
        timed_out: bool,
        oom_killed: bool,
        reason: str | None,
        origin: Literal["candidate_process", "control_plane"] | None,
        reused: bool,
        effective_timeout_s: int,
        container_id: str,
    ) -> CompletedCommand:
        runtime_config = command_image_runtime_config(self._config)
        return CompletedCommand(
            argv=list(command.argv),
            cwd=command.cwd,
            exit_code=exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            duration_s=time.monotonic() - started,
            timed_out=timed_out,
            oom_killed=oom_killed,
            output_truncated=execution.output_truncated,
            failure_reason=reason,
            failure_origin=origin,
            container_id=container_id,
            runtime_role="external-agent-command",
            metadata={
                "effective_timeout_s": effective_timeout_s,
                "container_execution": {"protocol": _EXECUTION_PROTOCOL},
                "command_image_protocol": self._config.protocol,
                "command_execution_backend": self._config.execution_backend,
                "episode_container_reused": reused,
                "episode_container_startup_s": self._startup_duration_s if not reused else 0.0,
                "episode_command_index": self._command_count,
                "credential_environment_names": [],
                "network_mode": "none",
                "resource_limits": resource_summary(
                    runtime_config,
                    max_output_bytes=self._config.max_output_bytes,
                ).model_dump(mode="json"),
            },
        )

    def _failure(
        self,
        command: CommandSpec,
        *,
        started: float,
        reason: str,
        origin: Literal["candidate_process", "control_plane"],
        error: str,
        container_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> CompletedCommand:
        return CompletedCommand(
            argv=list(command.argv),
            cwd=command.cwd,
            exit_code=None,
            duration_s=time.monotonic() - started,
            error=error,
            failure_reason=reason,
            failure_origin=origin,
            container_id=container_id,
            runtime_role="external-agent-command",
            metadata={
                "container_execution": {"protocol": _EXECUTION_PROTOCOL},
                "command_image_protocol": self._config.protocol,
                "command_execution_backend": self._config.execution_backend,
                **(metadata or {}),
            },
        )

    def _invalidate(self, *, kill_running: bool) -> str | None:
        self._poisoned = True
        container_id = self._container_id
        self._container_id = None
        self._baseline_processes = None
        if container_id is None:
            return None
        kill_warning: str | None = None
        if kill_running:
            try:
                killed = self._engine.kill_container(container_id)
                if killed.timed_out or killed.exit_code != 0:
                    kill_warning = "Docker episode container kill failed"
            except DockerRuntimeError:
                kill_warning = "Docker episode container kill failed"
        remove_warning = self._remove_container(container_id)
        # A successful force-remove is the authoritative cleanup result: it also stops a
        # running container, so a preceding best-effort kill failure is not a leak.
        if remove_warning is None:
            return None
        return remove_warning or kill_warning


def _validate_command(command: CommandSpec) -> None:
    if command.argv[:2] != ["/bin/bash", "-lc"] or len(command.argv) != 3:
        raise ValueError("external-agent command argv is not exact /bin/bash -lc")
    if command.env or command.stdin is not None or command.artifact_globs:
        raise ValueError("external-agent command contains a forbidden side channel")


def _container_state(payload: dict[str, object]) -> dict[str, object]:
    value = payload.get("State")
    return value if isinstance(value, dict) else {}


def _require_control_success(result: EngineResult, action: str, subreason: str) -> None:
    if result.timed_out or result.exit_code != 0:
        raise DockerDaemonError(
            f"Docker {action} failed",
            subreason=subreason,
            details={
                "stage": action,
                "duration_s": result.duration_s,
                "timed_out": result.timed_out,
                "exit_code": result.exit_code,
            },
        )


def _process_fingerprint(result: EngineResult) -> tuple[tuple[int, int, str], ...]:
    _require_control_success(result, "episode process inventory", "episode_process_check_failed")
    processes: list[tuple[int, int, str]] = []
    for line in result.stdout.splitlines():
        values = line.split(None, 2)
        if len(values) == 3 and values[0].isdigit() and values[1].isdigit():
            processes.append((int(values[0]), int(values[1]), values[2]))
        elif [value.upper() for value in values] == ["PID", "PPID", "COMMAND"]:
            continue
        elif line.strip():
            raise DockerDaemonError(
                "Docker episode process inventory was malformed",
                subreason="episode_process_check_failed",
            )
    if not processes:
        raise DockerDaemonError(
            "Docker episode process inventory was empty",
            subreason="episode_process_check_failed",
        )
    return tuple(sorted(processes))


def _apply_cleanup_failure(
    completed: CompletedCommand,
    cleanup_warning: str | None,
) -> CompletedCommand:
    if cleanup_warning is None:
        return completed
    completed.error = cleanup_warning
    completed.failure_reason = "container_cleanup_failed"
    completed.failure_origin = "control_plane"
    return completed


__all__ = ["DockerEpisodeCommandExecutor"]
