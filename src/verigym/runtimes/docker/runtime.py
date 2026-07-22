"""Production-oriented optional Docker runtime plugin."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.runtimes.base import Runtime
from verigym.runtimes.docker.engine import DockerCliEngine, DockerEngine
from verigym.runtimes.docker.errors import (
    DockerImageError,
    DockerRuntimeError,
    sanitize_diagnostic,
)
from verigym.runtimes.docker.image import inspect_backend, resolve_image
from verigym.runtimes.docker.resources import resource_summary
from verigym.runtimes.docker.security import BASELINE_ENVIRONMENT
from verigym.runtimes.docker.session import DockerRuntimeSession
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import (
    RuntimeCleanupSummary,
    RuntimeDescriptor,
    RuntimeImageIdentity,
    RuntimeSecuritySummary,
    RuntimeSessionRecord,
)
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.tool import CommandSpec, HealthCheckResult
from verigym.suites.verilog_eval.toolchain import classify_icarus_version

_VERSION_LINE = re.compile(r"^Icarus Verilog (?:runtime )?version\b", re.IGNORECASE)


class DockerRuntime(Runtime):
    """Short-lived constrained container per command over private session workspaces."""

    def __init__(
        self,
        config: DockerRuntimeConfig | None = None,
        *,
        engine: DockerEngine | None = None,
        expected_image_id: str | None = None,
        replay_image: RuntimeImageIdentity | None = None,
    ) -> None:
        self._config = config
        self._engine = engine
        self._engine_was_injected = engine is not None
        self._expected_image_id = expected_image_id
        self._replay_image = replay_image
        self._run_id: str | None = None
        self._prepared = False
        self._closed = False
        self._sessions: list[DockerRuntimeSession] = []
        self._session_records: dict[str, RuntimeSessionRecord] = {}
        self._removed_container_ids: list[str] = []
        self._cleanup_warnings: list[str] = []
        self._descriptor = RuntimeDescriptor(
            schema_version=SCHEMA_VERSION,
            name="docker",
            version="0.1.0",
            api_version=PLUGIN_API_VERSION,
            provider="verigym",
            capabilities=[
                "docker_cli",
                "immutable_image",
                "network_none",
                "non_root",
                "resource_limits",
                "bounded_output",
            ],
            isolation_level="docker_standard",
            deterministic=True,
        )

    @property
    def descriptor(self) -> RuntimeDescriptor:
        self._refresh_descriptor()
        return self._descriptor.model_copy(deep=True)

    def _get_engine(self) -> DockerEngine:
        if self._engine is None:
            self._engine = DockerCliEngine()
        return self._engine

    def configure(self, config: DockerRuntimeConfig | None) -> Runtime:
        if config is None:
            raise ConfigurationError("DockerRuntime requires --docker-image")
        engine = self._engine if self._engine_was_injected else None
        return DockerRuntime(config, engine=engine)

    def configure_for_replay(self, descriptor: RuntimeDescriptor) -> Runtime:
        if descriptor.name != "docker" or descriptor.image is None:
            raise ConfigurationError("stored run has no Docker image identity")
        if descriptor.security is None or descriptor.resources is None:
            raise ConfigurationError("stored Docker descriptor lacks mandatory controls")
        security = descriptor.security
        resources = descriptor.resources
        custom_environment = sorted(set(security.environment_names) - set(BASELINE_ENVIRONMENT))
        config = DockerRuntimeConfig(
            image=descriptor.image.resolved_image_id,
            pull_policy="never",
            network_mode="none",
            run_as_user=descriptor.image.effective_user or security.configured_user,
            read_only_rootfs=True,
            memory_bytes=resources.memory_bytes,
            cpus=resources.cpus,
            pids_limit=resources.pids_limit,
            tmpfs_bytes=resources.tmpfs_bytes,
            stop_timeout_s=resources.stop_timeout_s or 3,
            max_command_time_s=resources.max_command_time_s,
            max_artifact_file_bytes=resources.max_artifact_file_bytes or 16 * 1024 * 1024,
            max_artifact_bytes=resources.max_artifact_bytes or 64 * 1024 * 1024,
            environment_allowlist=custom_environment,
        )
        engine = self._engine if self._engine_was_injected else None
        return DockerRuntime(
            config,
            engine=engine,
            expected_image_id=descriptor.image.resolved_image_id,
            replay_image=descriptor.image,
        )

    def prepare(self, run_id: str) -> None:
        if self._prepared:
            if run_id != self._run_id:
                raise ConfigurationError("a DockerRuntime instance cannot be reused across runs")
            return
        if self._config is None:
            raise ConfigurationError("DockerRuntime has not been configured with an image")
        self._run_id = run_id
        try:
            engine = self._get_engine()
            backend, _info = inspect_backend(engine)
            image = resolve_image(
                engine,
                self._config,
                expected_image_id=self._expected_image_id,
            )
            self._descriptor.backend = backend
            self._descriptor.image = image
            self._descriptor.security = RuntimeSecuritySummary(
                network_mode="none",
                read_only_rootfs=True,
                configured_user=image.effective_user,
                privileged=False,
                cap_drop=["ALL"],
                no_new_privileges=True,
                init=True,
                mount_destinations=["/workspace"],
                writable_destinations=["/workspace", "/tmp"],
                environment_names=sorted(
                    set(BASELINE_ENVIRONMENT) | set(self._config.environment_allowlist)
                ),
                docker_socket_mounted=False,
                host_home_mounted=False,
            )
            self._descriptor.resources = resource_summary(self._config)
            self._descriptor.configuration_fingerprint = content_hash(self._config)
            self._descriptor.cleanup = RuntimeCleanupSummary(complete=False)
            self._prepared = True
            if self._replay_image is None:
                self._probe_image()
            else:
                self._restore_replay_observations(self._replay_image)
        except BaseException:
            try:
                self.close()
            except Exception:
                pass
            raise

    def _restore_replay_observations(self, stored: RuntimeImageIdentity) -> None:
        """Reuse observations already bound to an exact immutable replay image ID."""

        current = self._descriptor.image
        if current is None or self._descriptor.security is None:
            raise RuntimeError("Docker replay image identity is unavailable")
        if current.resolved_image_id != stored.resolved_image_id:
            raise DockerImageError(
                "Docker replay image changed during preparation",
                subreason="replay_image_mismatch",
            )
        if current.os != stored.os or current.architecture != stored.architecture:
            raise DockerImageError(
                "Docker replay image platform metadata differs from the stored run",
                subreason="replay_platform_mismatch",
            )
        if (
            stored.observed_uid in {None, 0}
            or stored.observed_gid is None
            or stored.iverilog_version is None
            or stored.vvp_version is None
        ):
            raise DockerImageError(
                "stored Docker run lacks verified image observations required for replay",
                subreason="replay_observations_missing",
            )
        self._descriptor.image = current.model_copy(
            update={
                "observed_uid": stored.observed_uid,
                "observed_gid": stored.observed_gid,
                "iverilog_version": stored.iverilog_version,
                "vvp_version": stored.vvp_version,
                "compatibility_status": stored.compatibility_status,
            }
        )
        self._descriptor.security = self._descriptor.security.model_copy(
            update={"observed_uid": stored.observed_uid, "observed_gid": stored.observed_gid}
        )

    def _probe_image(self) -> None:
        if self._descriptor.image is None:
            raise RuntimeError("Docker image identity is unavailable")
        if self._run_id is None:
            raise RuntimeError("Docker run identity is unavailable")
        probe_config = self._require_config().model_copy(
            update={"max_command_time_s": max(10, self._require_config().max_command_time_s)}
        )
        with tempfile.TemporaryDirectory(prefix="verigym-docker-probe-") as temporary:
            session = DockerRuntimeSession(
                spec=SessionSpec(
                    source_dir=str(Path(temporary)),
                    label="diagnostic",
                    max_output_bytes=128 * 1024,
                ),
                engine=self._get_engine(),
                config=probe_config,
                image=self._descriptor.image,
                run_id=self._run_id,
                owner=self,
            )
            self._sessions.append(session)
            try:
                uid_result = session.execute(CommandSpec(argv=["id", "-u"], timeout_s=10))
                gid_result = session.execute(CommandSpec(argv=["id", "-g"], timeout_s=10))
                compiler = session.execute(CommandSpec(argv=["iverilog", "-V"], timeout_s=10))
                runner = session.execute(CommandSpec(argv=["vvp", "-V"], timeout_s=10))
                for name, result in (
                    ("id -u", uid_result),
                    ("id -g", gid_result),
                    ("iverilog -V", compiler),
                    ("vvp -V", runner),
                ):
                    if (
                        result.error
                        or result.timed_out
                        or result.oom_killed
                        or result.output_truncated
                        or result.exit_code != 0
                    ):
                        raise DockerImageError(
                            f"Docker image health command failed: {name}",
                            subreason="image_health_failed",
                            details={"command": name, "failure_reason": result.failure_reason},
                        )
                try:
                    uid = int(uid_result.stdout.strip())
                    gid = int(gid_result.stdout.strip())
                except ValueError as exc:
                    raise DockerImageError(
                        "Docker image returned an invalid effective user identity",
                        subreason="invalid_runtime_user",
                    ) from exc
                if uid == 0:
                    raise DockerImageError(
                        "Docker image executes as root and is rejected",
                        subreason="root_runtime_user",
                    )
                iverilog_version = _extract_version(compiler.stdout + "\n" + compiler.stderr)
                vvp_version = _extract_version(runner.stdout + "\n" + runner.stderr)
                if iverilog_version is None or vvp_version is None:
                    raise DockerImageError(
                        "Docker image did not report valid Icarus tool versions",
                        subreason="tool_version_unavailable",
                    )
                compatibility = classify_icarus_version(iverilog_version).value
                self._descriptor.image = self._descriptor.image.model_copy(
                    update={
                        "observed_uid": uid,
                        "observed_gid": gid,
                        "iverilog_version": iverilog_version,
                        "vvp_version": vvp_version,
                        "compatibility_status": compatibility,
                    }
                )
                assert self._descriptor.security is not None
                self._descriptor.security = self._descriptor.security.model_copy(
                    update={"observed_uid": uid, "observed_gid": gid}
                )
            finally:
                session.close()

    def health_check(self) -> HealthCheckResult:
        temporary_engine = self._engine is None
        engine: DockerEngine = self._engine or DockerCliEngine()
        try:
            backend, _info = inspect_backend(engine)
        except DockerRuntimeError as exc:
            return HealthCheckResult(healthy=False, message=str(exc))
        finally:
            if temporary_engine:
                engine.close()
        return HealthCheckResult(
            healthy=True,
            message=(
                "Docker CLI and daemon are available; image is configured per run "
                f"(server {backend.server_version}, API {backend.api_version})"
            ),
            version=backend.server_version,
            executable=engine.executable if isinstance(engine, DockerCliEngine) else None,
        )

    def create_session(self, spec: SessionSpec) -> DockerRuntimeSession:
        if not self._prepared or self._run_id is None or self._descriptor.image is None:
            raise ConfigurationError(
                "DockerRuntime must resolve its image before creating sessions"
            )
        resources = self._descriptor.resources
        if resources is not None:
            current_limit = resources.max_output_bytes
            self._descriptor.resources = resources.model_copy(
                update={
                    "max_output_bytes": (
                        spec.max_output_bytes
                        if current_limit is None
                        else min(current_limit, spec.max_output_bytes)
                    )
                }
            )
        session = DockerRuntimeSession(
            spec=spec,
            engine=self._get_engine(),
            config=self._require_config(),
            image=self._descriptor.image,
            run_id=self._run_id,
            owner=self,
        )
        self._sessions.append(session)
        return session

    def environment_summary(self) -> dict[str, object]:
        descriptor = self.descriptor
        return {
            "docker_backend": (
                descriptor.backend.model_dump(mode="json") if descriptor.backend else None
            ),
            "docker_image": (
                descriptor.image.model_dump(mode="json") if descriptor.image else None
            ),
            "docker_security": (
                descriptor.security.model_dump(mode="json") if descriptor.security else None
            ),
            "docker_resources": (
                descriptor.resources.model_dump(mode="json") if descriptor.resources else None
            ),
        }

    def close(self) -> None:
        if self._closed:
            return
        for session in self._sessions:
            try:
                session.close()
            except Exception as exc:
                warning = sanitize_diagnostic(f"Docker session cleanup failed: {exc}")
                if warning not in self._cleanup_warnings:
                    self._cleanup_warnings.append(warning)
        if self._engine is not None:
            try:
                self._engine.close()
            except Exception as exc:
                warning = sanitize_diagnostic(f"Docker backend cleanup failed: {exc}")
                if warning not in self._cleanup_warnings:
                    self._cleanup_warnings.append(warning)
        self._closed = True
        self._refresh_descriptor()
        if self._descriptor.cleanup is not None:
            complete = all(record.cleanup_complete for record in self._session_records.values())
            complete = complete and not self._cleanup_warnings
            self._descriptor.cleanup = self._descriptor.cleanup.model_copy(
                update={"complete": complete}
            )

    def session_registered(self, session_id: str, role: str) -> None:
        assert self._descriptor.image is not None
        self._session_records[session_id] = RuntimeSessionRecord(
            session_id=session_id,
            role=role,
            resolved_image_id=self._descriptor.image.resolved_image_id,
        )

    def container_registered(self, session_id: str, container_id: str) -> None:
        record = self._session_records[session_id]
        record.container_ids.append(container_id)
        record.command_count += 1

    def container_removed(self, session_id: str, container_id: str) -> None:
        del session_id
        if container_id not in self._removed_container_ids:
            self._removed_container_ids.append(container_id)

    def session_frozen(self, session_id: str) -> None:
        self._session_records[session_id].frozen = True

    def session_closed(self, session_id: str, warnings: list[str]) -> None:
        record = self._session_records[session_id]
        record.cleanup_warnings = list(warnings)
        record.cleanup_complete = not warnings
        self._cleanup_warnings.extend(
            warning for warning in warnings if warning not in self._cleanup_warnings
        )

    def _refresh_descriptor(self) -> None:
        self._descriptor.sessions = [
            record.model_copy(deep=True) for record in self._session_records.values()
        ]
        if self._prepared:
            self._descriptor.cleanup = RuntimeCleanupSummary(
                complete=(
                    self._closed
                    and all(record.cleanup_complete for record in self._session_records.values())
                    and not self._cleanup_warnings
                ),
                removed_container_ids=sorted(self._removed_container_ids),
                warnings=list(self._cleanup_warnings),
            )

    def _require_config(self) -> DockerRuntimeConfig:
        if self._config is None:
            raise RuntimeError("DockerRuntime is not configured")
        return self._config


def _extract_version(output: str) -> str | None:
    return next(
        (line.strip() for line in output.splitlines() if _VERSION_LINE.search(line.strip())),
        None,
    )


__all__ = ["DockerRuntime"]
