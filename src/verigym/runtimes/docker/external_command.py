"""Credential-free command execution in the configured external-agent image."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from verigym.runtimes.docker.engine import DockerEngine, execute_container
from verigym.runtimes.docker.errors import (
    DockerContainerError,
    DockerRuntimeError,
    sanitize_diagnostic,
)
from verigym.runtimes.docker.external_process import external_agent_runtime_config
from verigym.runtimes.docker.mounts import MountSpec, mount_arguments
from verigym.runtimes.docker.resources import (
    effective_timeout,
    resource_arguments,
    resource_summary,
)
from verigym.runtimes.docker.security import security_arguments, verify_effective_container
from verigym.schemas.common import RuntimeImageIdentity
from verigym.schemas.runtime import (
    DockerCommandImageRuntimeConfig,
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
)
from verigym.schemas.tool import CommandSpec, CompletedCommand

_BASE_ENVIRONMENT = {
    "PATH": "/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "/tmp/verigym-home",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TMPDIR": "/tmp",
}
_LEGACY_EXTERNAL_AGENT_ENVIRONMENT = {
    **_BASE_ENVIRONMENT,
    "CODEX_HOME": "/tmp/verigym-codex-home",
}

CommandImageConfig = DockerCommandImageRuntimeConfig | DockerExternalAgentRuntimeConfig


def command_image_runtime_config(config: DockerCommandImageRuntimeConfig) -> DockerRuntimeConfig:
    """Project command-only limits onto the ordinary immutable-image resolver schema."""

    return DockerRuntimeConfig(
        image=config.image,
        expected_image_id=config.expected_image_id,
        pull_policy=config.pull_policy,
        network_mode="none",
        run_as_user=config.run_as_user,
        read_only_rootfs=True,
        memory_bytes=config.memory_bytes,
        cpus=config.cpus,
        pids_limit=config.pids_limit,
        tmpfs_bytes=config.tmpfs_bytes,
        stop_timeout_s=config.stop_timeout_s,
        max_command_time_s=config.max_command_time_s,
        max_artifact_file_bytes=16 * 1024 * 1024,
        max_artifact_bytes=64 * 1024 * 1024,
    )


def command_environment(config: CommandImageConfig) -> dict[str, str]:
    if isinstance(config, DockerExternalAgentRuntimeConfig):
        return dict(_LEGACY_EXTERNAL_AGENT_ENVIRONMENT)
    return dict(_BASE_ENVIRONMENT)


def effective_command_runtime_config(config: CommandImageConfig) -> DockerRuntimeConfig:
    if isinstance(config, DockerExternalAgentRuntimeConfig):
        return external_agent_runtime_config(config)
    return command_image_runtime_config(config)


def command_max_output_bytes(config: CommandImageConfig) -> int:
    return config.max_output_bytes


class DockerExternalAgentCommandExecutor:
    """Run one bounded `/bin/bash -lc` call without the provider credential."""

    def __init__(
        self,
        *,
        engine: DockerEngine,
        image: RuntimeImageIdentity,
        config: CommandImageConfig,
        run_id: str,
        session_id: str,
        register_container: Callable[[str], None],
        remove_container: Callable[[str], str | None],
    ) -> None:
        self._engine = engine
        self._image = image
        self._config = config
        self._run_id = run_id
        self._session_id = session_id
        self._register_container = register_container
        self._remove_container = remove_container

    def execute(self, command: CommandSpec, *, mounts: list[MountSpec]) -> CompletedCommand:
        if command.argv[:2] != ["/bin/bash", "-lc"] or len(command.argv) != 3:
            raise ValueError("external-agent command argv is not exact /bin/bash -lc")
        if command.env or command.stdin is not None or command.artifact_globs:
            raise ValueError("external-agent command contains a forbidden side channel")
        if (
            isinstance(self._config, DockerCommandImageRuntimeConfig)
            and self._config.execution_backend != "ephemeral_container_v1"
        ):
            raise ValueError("episode command-image config requires the persistent executor")
        runtime_config = effective_command_runtime_config(self._config)
        environment = command_environment(self._config)
        logical_cwd = "/workspace/repository" + ("" if command.cwd == "." else f"/{command.cwd}")
        timeout_s = effective_timeout(command.timeout_s, runtime_config.max_command_time_s)
        labels = {
            "org.verigym.managed": "true",
            "org.verigym.run_id": self._run_id,
            "org.verigym.session_id": self._session_id,
            "org.verigym.role": "external-agent-command",
            "org.verigym.external_protocol": "hwe-native-shell-v2",
        }
        user = self._image.effective_user
        if user is None or user != self._config.run_as_user:
            raise ValueError("external-agent command image user identity changed")
        arguments = [
            *security_arguments(
                runtime_config,
                user=user,
                cwd=logical_cwd,
                environment=environment,
                labels=labels,
            ),
            *resource_arguments(runtime_config),
            *mount_arguments(mounts),
            self._image.resolved_image_id,
            *command.argv,
        ]
        container_id: str | None = None
        started = time.monotonic()
        completed: CompletedCommand | None = None
        try:
            container_id = self._engine.create_container(arguments)
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
            execution = execute_container(
                self._engine,
                container_id,
                timeout_s=timeout_s,
                max_output_bytes=command_max_output_bytes(self._config),
            )
            state_payload = self._engine.inspect_container(container_id)
            state = state_payload.get("State")
            state = state if isinstance(state, dict) else {}
            state_status = state.get("Status")
            state_error = state.get("Error")
            if not execution.timed_out and (
                state_status != "exited" or (isinstance(state_error, str) and state_error)
            ):
                raise DockerContainerError(
                    "Docker could not complete the external-agent command",
                    subreason="container_start_failed",
                    details={"state": state_status},
                )
            oom_killed = state.get("OOMKilled") is True
            exit_code = state.get("ExitCode") if isinstance(state.get("ExitCode"), int) else None
            failure_reason = (
                "timeout" if execution.timed_out else "out_of_memory" if oom_killed else None
            )
            completed = CompletedCommand(
                argv=list(command.argv),
                cwd=command.cwd,
                exit_code=exit_code,
                stdout=execution.stdout,
                stderr=execution.stderr,
                duration_s=time.monotonic() - started,
                timed_out=execution.timed_out,
                oom_killed=oom_killed,
                output_truncated=execution.output_truncated,
                failure_reason=failure_reason,
                failure_origin="candidate_process" if failure_reason else None,
                container_id=container_id,
                runtime_role="external-agent-command",
                metadata={
                    "effective_timeout_s": timeout_s,
                    "container_execution": {
                        "protocol": execution.execution_protocol,
                        "phase_durations_s": dict(execution.phase_durations_s),
                    },
                    "credential_environment_names": [],
                    "network_mode": "none",
                    "resource_limits": resource_summary(
                        runtime_config,
                        max_output_bytes=command_max_output_bytes(self._config),
                    ).model_dump(mode="json"),
                    "command_image_protocol": self._config.protocol,
                    "command_execution_backend": "ephemeral_container_v1",
                },
            )
        except DockerRuntimeError as exc:
            completed = CompletedCommand(
                argv=list(command.argv),
                cwd=command.cwd,
                exit_code=None,
                duration_s=time.monotonic() - started,
                error=sanitize_diagnostic(str(exc), sensitive_paths=(str(Path.home()),)),
                failure_reason=exc.subreason,
                failure_origin="control_plane",
                container_id=container_id,
                runtime_role="external-agent-command",
                metadata={
                    "origin": exc.origin,
                    **(
                        {"container_execution": dict(exc.details)}
                        if exc.origin == "container_execution"
                        else {}
                    ),
                },
            )
        finally:
            cleanup_warning = self._remove_container(container_id) if container_id else None
        assert completed is not None
        if cleanup_warning is not None:
            completed.error = cleanup_warning
            completed.failure_reason = "container_cleanup_failed"
            completed.failure_origin = "control_plane"
        return completed


__all__ = [
    "DockerExternalAgentCommandExecutor",
    "command_environment",
    "command_image_runtime_config",
    "command_max_output_bytes",
    "effective_command_runtime_config",
]
