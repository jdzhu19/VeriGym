"""One private host workspace with one constrained Docker container per command."""

from __future__ import annotations

import difflib
import os
import stat
import tempfile
import time
import uuid
from pathlib import Path
from typing import Protocol

from verigym.core.errors import PathPolicyError
from verigym.core.workspace import copy_tree_safely, normalize_relative_path
from verigym.runtimes.base import RuntimeSession
from verigym.runtimes.docker.artifacts import collect_declared_artifacts
from verigym.runtimes.docker.engine import DockerEngine
from verigym.runtimes.docker.errors import (
    DockerContainerError,
    DockerRuntimeError,
    sanitize_diagnostic,
)
from verigym.runtimes.docker.mounts import mount_arguments, workspace_mount
from verigym.runtimes.docker.resources import (
    effective_timeout,
    resource_arguments,
    resource_summary,
)
from verigym.runtimes.docker.security import (
    build_environment,
    security_arguments,
    verify_effective_container,
)
from verigym.schemas.common import RuntimeImageIdentity
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec, WorkspaceDiff
from verigym.schemas.tool import CommandSpec, CompletedCommand


class DockerSessionOwner(Protocol):
    def session_registered(self, session_id: str, role: str) -> None: ...

    def container_registered(self, session_id: str, container_id: str) -> None: ...

    def container_removed(self, session_id: str, container_id: str) -> None: ...

    def session_frozen(self, session_id: str) -> None: ...

    def session_closed(self, session_id: str, warnings: list[str]) -> None: ...


class DockerRuntimeSession(RuntimeSession):
    """A private bind-mounted staging tree and short-lived command containers."""

    def __init__(
        self,
        *,
        spec: SessionSpec,
        engine: DockerEngine,
        config: DockerRuntimeConfig,
        image: RuntimeImageIdentity,
        run_id: str,
        owner: DockerSessionOwner,
    ) -> None:
        if spec.label not in {"agent", "verifier", "diagnostic"}:
            raise ValueError(f"unsupported Docker session role: {spec.label!r}")
        self.role = spec.label
        self.session_id = uuid.uuid4().hex
        self._temporary = tempfile.TemporaryDirectory(prefix="verigym-docker-session-")
        self._root = Path(self._temporary.name).resolve()
        self._engine = engine
        self._config = config
        self._image = image
        self._run_id = run_id
        self._owner = owner
        self._max_output_bytes = spec.max_output_bytes
        self._session_environment = dict(spec.environment)
        self._closed = False
        self._frozen = False
        self._active_containers: set[str] = set()
        self._cleanup_warnings: list[str] = []
        copy_tree_safely(Path(spec.source_dir), self._root)
        (self._root / ".verigym_internal").mkdir(exist_ok=True)
        self._prepare_permissions()
        self._mounts = [workspace_mount(self._root)]
        self._baseline = self._snapshot()
        owner.session_registered(self.session_id, self.role)

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, raw_path: str, *, allow_root: bool = False) -> Path:
        relative = normalize_relative_path(raw_path, allow_root=allow_root)
        candidate = self._root if relative == "." else self._root / relative
        cursor = self._root
        for part in () if relative == "." else Path(relative).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise PathPolicyError("symlinks are not permitted inside a Docker session")
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise PathPolicyError("path escapes the Docker runtime session")
        return resolved

    def execute(self, command: CommandSpec) -> CompletedCommand:
        if self._closed:
            raise PathPolicyError("Docker session is closed")
        if self._frozen:
            raise PathPolicyError("Docker session is frozen")
        if command.requires_shell:
            raise PathPolicyError("DockerRuntime does not execute shell command strings")
        cwd_path = self._resolve(command.cwd, allow_root=True)
        if not cwd_path.is_dir():
            raise PathPolicyError(f"command working directory does not exist: {command.cwd}")
        self._make_internal_writable()
        logical_argv = self._map_argv(command.argv)
        logical_cwd = "/workspace" + (
            "" if command.cwd == "." else f"/{normalize_relative_path(command.cwd)}"
        )
        effective_limit = effective_timeout(command.timeout_s, self._config.max_command_time_s)
        environment = build_environment(
            self._config,
            self._session_environment,
            command.env,
        )
        labels = {
            "org.verigym.managed": "true",
            "org.verigym.run_id": self._run_id,
            "org.verigym.session_id": self.session_id,
            "org.verigym.role": self.role,
        }
        user = self._image.effective_user
        if user is None:
            raise PathPolicyError("Docker image has no effective non-root user")
        arguments = [
            *security_arguments(
                self._config,
                user=user,
                cwd=logical_cwd,
                environment=environment,
                labels=labels,
            ),
            *resource_arguments(self._config),
            *mount_arguments(self._mounts),
            self._image.resolved_image_id,
            *logical_argv,
        ]
        container_id: str | None = None
        completed: CompletedCommand | None = None
        started = time.monotonic()
        try:
            container_id = self._engine.create_container(arguments)
            self._active_containers.add(container_id)
            self._owner.container_registered(self.session_id, container_id)
            inspection = self._engine.inspect_container(container_id)
            verify_effective_container(
                inspection,
                config=self._config,
                expected_user=user,
                expected_mounts=self._mounts,
                expected_environment=environment,
                expected_labels=labels,
            )
            execution = self._engine.start_attach(
                container_id,
                timeout_s=effective_limit,
                max_output_bytes=self._max_output_bytes,
            )
            if execution.timed_out:
                self._engine.kill_container(container_id)
            state_payload = self._engine.inspect_container(container_id)
            state = state_payload.get("State")
            state = state if isinstance(state, dict) else {}
            state_status = state.get("Status")
            state_error = state.get("Error")
            if not execution.timed_out and (
                state_status != "exited" or (isinstance(state_error, str) and state_error)
            ):
                raise DockerContainerError(
                    "Docker could not start or complete the command container",
                    subreason="container_start_failed",
                    details={"state": state_status},
                )
            oom_killed = state.get("OOMKilled") is True
            exit_code = state.get("ExitCode") if isinstance(state.get("ExitCode"), int) else None
            artifacts = collect_declared_artifacts(
                self._root,
                command.artifact_globs,
                max_file_bytes=self._config.max_artifact_file_bytes,
                max_total_bytes=self._config.max_artifact_bytes,
            )
            failure_reason = (
                "timeout" if execution.timed_out else "out_of_memory" if oom_killed else None
            )
            completed = CompletedCommand(
                argv=logical_argv,
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
                runtime_role=self.role,
                metadata={
                    "effective_timeout_s": effective_limit,
                    "memory_limit_bytes": self._config.memory_bytes,
                    "resource_limits": resource_summary(
                        self._config,
                        max_output_bytes=self._max_output_bytes,
                    ).model_dump(mode="json"),
                    "oom_evidence": {
                        "docker_state_oom_killed": oom_killed,
                        "container_state": state_status,
                        "exit_code": exit_code,
                    },
                    "artifact_metadata": [item.model_dump(mode="json") for item in artifacts],
                    "tool_versions": self._tool_versions(),
                },
            )
        except DockerRuntimeError as exc:
            completed = CompletedCommand(
                argv=logical_argv,
                cwd=command.cwd,
                exit_code=None,
                duration_s=time.monotonic() - started,
                error=sanitize_diagnostic(
                    str(exc),
                    sensitive_paths=(str(self._root), str(Path.home())),
                ),
                failure_reason=exc.subreason,
                failure_origin="control_plane",
                container_id=container_id,
                runtime_role=self.role,
                metadata={"origin": exc.origin, "tool_versions": self._tool_versions()},
            )
        finally:
            cleanup_warning = self._remove_container(container_id) if container_id else None
        assert completed is not None
        if cleanup_warning is not None:
            metadata = dict(completed.metadata)
            metadata["cleanup_warning"] = cleanup_warning
            completed.metadata = metadata
            if completed.error is None and completed.failure_reason is None:
                completed.error = cleanup_warning
                completed.failure_reason = "container_cleanup_failed"
                completed.failure_origin = "control_plane"
        return completed

    def _map_argv(self, argv: list[str]) -> list[str]:
        mapped: list[str] = []
        for index, value in enumerate(argv):
            if index == 0 and Path(value).is_absolute():
                try:
                    host_path = Path(value).resolve(strict=False)
                    if host_path.is_relative_to(self._root):
                        relative = host_path.relative_to(self._root).as_posix()
                        mapped.append(f"/workspace/{relative}")
                    else:
                        mapped.append(Path(value).name)
                except OSError as exc:
                    raise PathPolicyError("invalid executable path") from exc
                continue
            if value.startswith("/"):
                candidate = Path(value).resolve(strict=False)
                if not candidate.is_relative_to(self._root):
                    raise PathPolicyError("absolute host paths are forbidden in Docker commands")
                mapped.append(f"/workspace/{candidate.relative_to(self._root).as_posix()}")
            else:
                mapped.append(value)
        return mapped

    def read_file(self, path: str) -> bytes:
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise FileNotFoundError(path)
        return resolved.read_bytes()

    def write_file(self, path: str, data: bytes) -> None:
        if self._closed or self._frozen:
            raise PathPolicyError("Docker session is not writable")
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)
        if self.role in {"agent", "diagnostic"}:
            resolved.parent.chmod(0o777)
            resolved.chmod(0o666)

    def _snapshot(self) -> dict[str, bytes]:
        snapshot: dict[str, bytes] = {}
        for path in sorted(self._root.rglob("*")):
            relative = path.relative_to(self._root)
            if ".verigym_internal" in relative.parts:
                continue
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode):
                raise PathPolicyError(f"symlink found in workspace: {relative.as_posix()}")
            if stat.S_ISREG(metadata.st_mode):
                snapshot[relative.as_posix()] = path.read_bytes()
            elif not stat.S_ISDIR(metadata.st_mode):
                raise PathPolicyError(f"special file found in workspace: {relative.as_posix()}")
        return snapshot

    def snapshot_diff(self) -> WorkspaceDiff:
        current = self._snapshot()
        changed = sorted(
            path
            for path in set(self._baseline) | set(current)
            if self._baseline.get(path) != current.get(path)
        )
        parts: list[str] = []
        added = 0
        deleted = 0
        for path in changed:
            before_bytes = self._baseline.get(path, b"")
            after_bytes = current.get(path, b"")
            try:
                before = before_bytes.decode("utf-8").splitlines(keepends=True)
                after = after_bytes.decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError:
                parts.append(f"Binary files a/{path} and b/{path} differ\n")
                continue
            diff_lines = list(
                difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}")
            )
            parts.extend(diff_lines)
            added += sum(
                1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
            )
            deleted += sum(
                1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
            )
        return WorkspaceDiff(
            patch="".join(parts),
            changed_files=changed,
            added_lines=added,
            deleted_lines=deleted,
        )

    def freeze(self) -> None:
        if not self._frozen:
            self._frozen = True
            self._owner.session_frozen(self.session_id)

    def close(self) -> None:
        if self._closed:
            return
        for container_id in sorted(self._active_containers):
            self._remove_container(container_id)
        self._temporary.cleanup()
        self._closed = True
        self._owner.session_closed(self.session_id, list(self._cleanup_warnings))

    def _remove_container(self, container_id: str) -> str | None:
        if container_id not in self._active_containers:
            return None
        try:
            result = self._engine.remove_container(container_id, force=True)
            if result.exit_code != 0 or result.timed_out:
                detail = sanitize_diagnostic(result.stderr or result.stdout)
                warning = f"Docker container cleanup failed: {detail or 'unknown daemon error'}"
                self._cleanup_warnings.append(warning)
                return warning
            self._active_containers.discard(container_id)
            self._owner.container_removed(self.session_id, container_id)
            return None
        except DockerRuntimeError as exc:
            warning = sanitize_diagnostic(str(exc), sensitive_paths=(str(self._root),))
            self._cleanup_warnings.append(warning)
            return warning

    def _prepare_permissions(self) -> None:
        writable = self.role in {"agent", "diagnostic"}
        for path in sorted(self._root.rglob("*"), reverse=True):
            if path.is_symlink():
                raise PathPolicyError("symlinks are forbidden in Docker session sources")
            if path.is_dir():
                path.chmod(0o777 if writable else 0o555)
            elif path.is_file():
                path.chmod(0o666 if writable else 0o444)
        self._root.chmod(0o777 if writable else 0o555)
        self._make_internal_writable()

    def _make_internal_writable(self) -> None:
        internal = self._root / ".verigym_internal"
        internal.mkdir(exist_ok=True)
        internal.chmod(0o777)
        for path in internal.rglob("*"):
            if path.is_dir():
                path.chmod(0o777)

    def _tool_versions(self) -> dict[str, dict[str, str | None]]:
        return {
            "iverilog": {
                "version": self._image.iverilog_version,
                "executable": "iverilog",
                "compatibility_status": self._image.compatibility_status,
            },
            "vvp": {
                "version": self._image.vvp_version,
                "executable": "vvp",
                "compatibility_status": self._image.compatibility_status,
            },
        }


__all__ = ["DockerRuntimeSession", "DockerSessionOwner"]
