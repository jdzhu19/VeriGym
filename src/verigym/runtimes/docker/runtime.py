"""Production-oriented optional Docker runtime plugin."""

from __future__ import annotations

import os
import re
import tempfile
import threading
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
from verigym.schemas.runtime import (
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
    SessionSpec,
)
from verigym.schemas.tool import CommandSpec, HealthCheckResult
from verigym.suites.verilog_eval.toolchain import classify_icarus_version

_VERSION_LINE = re.compile(r"^Icarus Verilog (?:runtime )?version\b", re.IGNORECASE)
_IMAGE_OBSERVATION_CACHE_LOCK = threading.Lock()
_IMAGE_OBSERVATION_CACHE: dict[
    str,
    tuple[RuntimeImageIdentity, RuntimeImageIdentity | None],
] = {}


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
        self._agent_image: RuntimeImageIdentity | None = None
        self._image_observation_source: str | None = None
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
            if self._config.external_agent is not None:
                self._agent_image = resolve_image(
                    engine,
                    _external_agent_as_runtime_config(self._config.external_agent),
                    expected_image_id=self._config.external_agent.expected_image_id,
                )
                if self._agent_image.resolved_image_id == image.resolved_image_id:
                    raise DockerImageError(
                        "agent and verifier resolved to the same image identity",
                        subreason="role_image_identity_collision",
                    )
                expected_user = f"{os.getuid()}:{os.getgid()}"
                if os.getuid() == 0 or self._agent_image.effective_user != expected_user:
                    raise DockerImageError(
                        "external-agent runtime user must match the current non-root host UID:GID",
                        subreason="agent_user_mapping_invalid",
                    )
                self._descriptor.capabilities = sorted(
                    set(self._descriptor.capabilities)
                    | {
                        "external_agent_runtime_process",
                        "outer_runtime_delegated",
                        "role_separated_images",
                        "container_network_none_stdio_broker",
                    }
                )
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
                if self._restore_cached_image_observations():
                    self._image_observation_source = "in_process_immutable_cache"
                else:
                    self._probe_image()
                    if self._agent_image is not None:
                        self._probe_agent_image()
                    self._cache_image_observations()
                    self._image_observation_source = "fresh_probe"
            else:
                self._restore_replay_observations(self._replay_image)
                self._image_observation_source = "replay_manifest"
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

    def _observation_cache_key(self) -> str:
        descriptor = self._descriptor
        if descriptor.backend is None or descriptor.image is None:
            raise RuntimeError("Docker image observation cache identity is unavailable")
        external = self._require_config().external_agent
        return content_hash(
            {
                "backend": descriptor.backend,
                "verifier_image": descriptor.image.model_copy(
                    update={
                        "observed_uid": None,
                        "observed_gid": None,
                        "iverilog_version": None,
                        "vvp_version": None,
                        "compatibility_status": None,
                    }
                ),
                "agent_image": (
                    self._agent_image.model_copy(
                        update={
                            "observed_uid": None,
                            "observed_gid": None,
                            "iverilog_version": None,
                            "vvp_version": None,
                            "compatibility_status": None,
                        }
                    )
                    if self._agent_image is not None
                    else None
                ),
                "agent_expected_executable_version": (
                    external.expected_executable_version if external is not None else None
                ),
                "agent_expected_executable_sha256": (
                    external.expected_executable_sha256 if external is not None else None
                ),
                "agent_runtime_configuration": external,
            }
        )

    def _cache_image_observations(self) -> None:
        verifier = self._descriptor.image
        if verifier is None:
            raise RuntimeError("Docker verifier image observations are unavailable")
        with _IMAGE_OBSERVATION_CACHE_LOCK:
            _IMAGE_OBSERVATION_CACHE[self._observation_cache_key()] = (
                verifier.model_copy(deep=True),
                self._agent_image.model_copy(deep=True) if self._agent_image is not None else None,
            )

    def _restore_cached_image_observations(self) -> bool:
        key = self._observation_cache_key()
        with _IMAGE_OBSERVATION_CACHE_LOCK:
            cached = _IMAGE_OBSERVATION_CACHE.get(key)
            if cached is None:
                return False
            verifier, agent = (
                cached[0].model_copy(deep=True),
                cached[1].model_copy(deep=True) if cached[1] is not None else None,
            )
        current = self._descriptor.image
        if current is None or self._descriptor.security is None:
            raise RuntimeError("Docker verifier image identity is unavailable")
        if (
            verifier.resolved_image_id != current.resolved_image_id
            or verifier.os != current.os
            or verifier.architecture != current.architecture
            or verifier.effective_user != current.effective_user
            or verifier.observed_uid in {None, 0}
            or verifier.observed_gid is None
            or verifier.iverilog_version is None
            or verifier.vvp_version is None
        ):
            raise DockerImageError(
                "cached Docker verifier observations do not match the immutable image",
                subreason="image_observation_cache_invalid",
            )
        if (self._agent_image is None) != (agent is None):
            raise DockerImageError(
                "cached Docker role observations are incomplete",
                subreason="image_observation_cache_invalid",
            )
        if agent is not None and self._agent_image is not None:
            if (
                agent.resolved_image_id != self._agent_image.resolved_image_id
                or agent.os != self._agent_image.os
                or agent.architecture != self._agent_image.architecture
                or agent.effective_user != self._agent_image.effective_user
                or agent.observed_uid in {None, 0}
                or agent.observed_gid is None
                or agent.compatibility_status is None
            ):
                raise DockerImageError(
                    "cached Docker external-agent observations do not match the immutable image",
                    subreason="image_observation_cache_invalid",
                )
            self._agent_image = agent
        self._descriptor.image = verifier
        self._descriptor.security = self._descriptor.security.model_copy(
            update={
                "observed_uid": verifier.observed_uid,
                "observed_gid": verifier.observed_gid,
            }
        )
        return True

    def _probe_image(self) -> None:
        if self._descriptor.image is None:
            raise RuntimeError("Docker image identity is unavailable")
        if self._run_id is None:
            raise RuntimeError("Docker run identity is unavailable")
        health_timeout_s = min(60, max(10, self._require_config().max_command_time_s))
        probe_config = self._require_config().model_copy(
            update={"max_command_time_s": health_timeout_s}
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
                uid_result = session.execute(
                    CommandSpec(argv=["id", "-u"], timeout_s=health_timeout_s)
                )
                gid_result = session.execute(
                    CommandSpec(argv=["id", "-g"], timeout_s=health_timeout_s)
                )
                compiler = session.execute(
                    CommandSpec(argv=["iverilog", "-V"], timeout_s=health_timeout_s)
                )
                runner = session.execute(
                    CommandSpec(argv=["vvp", "-V"], timeout_s=health_timeout_s)
                )
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

    def _probe_agent_image(self) -> None:
        if self._agent_image is None or self._run_id is None:
            raise RuntimeError("Docker external-agent image identity is unavailable")
        external = self._require_config().external_agent
        if external is None:
            raise RuntimeError("Docker external-agent configuration is unavailable")
        health_timeout_s = min(60, max(10, external.max_process_time_s))
        probe_config = _external_agent_as_runtime_config(external).model_copy(
            update={"max_command_time_s": health_timeout_s}
        )
        with tempfile.TemporaryDirectory(prefix="verigym-docker-agent-probe-") as temporary:
            session = DockerRuntimeSession(
                spec=SessionSpec(
                    source_dir=str(Path(temporary)),
                    label="diagnostic",
                    max_output_bytes=128 * 1024,
                ),
                engine=self._get_engine(),
                config=probe_config,
                image=self._agent_image,
                run_id=self._run_id,
                owner=self,
            )
            self._sessions.append(session)
            try:
                uid_result = session.execute(
                    CommandSpec(argv=["id", "-u"], timeout_s=health_timeout_s)
                )
                gid_result = session.execute(
                    CommandSpec(argv=["id", "-g"], timeout_s=health_timeout_s)
                )
                version = session.execute(
                    CommandSpec(
                        argv=[external.expected_executable_name, "--version"],
                        timeout_s=health_timeout_s,
                    )
                )
                binary_hash = session.execute(
                    CommandSpec(
                        argv=[
                            "sha256sum",
                            f"../{external.expected_executable_path.lstrip('/')}",
                        ],
                        timeout_s=health_timeout_s,
                    )
                )
                repository_agent = (
                    external.required_image_labels.get("org.verigym.runtime.role")
                    == "repository-agent"
                )
                iverilog_result = (
                    session.execute(
                        CommandSpec(argv=["iverilog", "-V"], timeout_s=health_timeout_s)
                    )
                    if repository_agent
                    else None
                )
                vvp_result = (
                    session.execute(CommandSpec(argv=["vvp", "-V"], timeout_s=health_timeout_s))
                    if repository_agent
                    else None
                )
                launcher_hash = (
                    session.execute(
                        CommandSpec(
                            argv=[
                                "sha256sum",
                                "../usr/local/bin/verigym-public-test",
                            ],
                            timeout_s=health_timeout_s,
                        )
                    )
                    if repository_agent
                    else None
                )
                health_results = [
                    ("id -u", uid_result),
                    ("id -g", gid_result),
                    (f"{external.expected_executable_name} --version", version),
                    ("external-agent executable SHA-256", binary_hash),
                ]
                if repository_agent:
                    assert (
                        iverilog_result is not None
                        and vvp_result is not None
                        and launcher_hash is not None
                    )
                    health_results.extend(
                        [
                            ("repository-agent iverilog -V", iverilog_result),
                            ("repository-agent vvp -V", vvp_result),
                            ("public-test launcher SHA-256", launcher_hash),
                        ]
                    )
                for name, result in health_results:
                    if (
                        result.error
                        or result.timed_out
                        or result.oom_killed
                        or result.output_truncated
                        or result.exit_code != 0
                    ):
                        raise DockerImageError(
                            f"Docker external-agent image health command failed: {name}",
                            subreason="agent_image_health_failed",
                            details={
                                "command": name,
                                "failure_reason": result.failure_reason,
                                "failure_origin": result.failure_origin,
                                "timed_out": result.timed_out,
                                "oom_killed": result.oom_killed,
                                "output_truncated": result.output_truncated,
                                "exit_code": result.exit_code,
                            },
                        )
                uid = int(uid_result.stdout.strip())
                gid = int(gid_result.stdout.strip())
                version_output = version.stdout.strip()
                observed_binary_hash = binary_hash.stdout.partition(" ")[0].strip()
                if (
                    uid == 0
                    or version_output != external.expected_executable_version
                    or observed_binary_hash != external.expected_executable_sha256
                ):
                    raise DockerImageError(
                        "Docker external-agent image identity is invalid",
                        subreason="agent_image_identity_invalid",
                    )
                raw = self._get_engine().inspect_image(self._agent_image.resolved_image_id)
                raw_config = raw.get("Config") if isinstance(raw, dict) else None
                labels = raw_config.get("Labels") if isinstance(raw_config, dict) else None
                labels = labels if isinstance(labels, dict) else {}
                if any(
                    labels.get(key) != value
                    for key, value in external.required_image_labels.items()
                ):
                    raise DockerImageError(
                        "Docker external-agent image lacks required immutable identity labels",
                        subreason="agent_image_labels_invalid",
                    )
                iverilog_output = (
                    _extract_version(iverilog_result.stdout + "\n" + iverilog_result.stderr)
                    if iverilog_result is not None
                    else None
                )
                vvp_output = (
                    _extract_version(vvp_result.stdout + "\n" + vvp_result.stderr)
                    if vvp_result is not None
                    else None
                )
                if repository_agent:
                    assert launcher_hash is not None
                    expected_launcher_hash = external.required_image_labels.get(
                        "org.verigym.public_test_launcher.sha256"
                    )
                    observed_launcher_hash = launcher_hash.stdout.partition(" ")[0].strip()
                    if (
                        expected_launcher_hash is None
                        or observed_launcher_hash != expected_launcher_hash
                        or iverilog_output is None
                        or "version 12." not in iverilog_output
                        or vvp_output is None
                        or "version 12." not in vvp_output
                    ):
                        raise DockerImageError(
                            "Docker repository-agent tool identity is invalid",
                            subreason="repository_agent_tool_identity_invalid",
                        )
                self._agent_image = self._agent_image.model_copy(
                    update={
                        "observed_uid": uid,
                        "observed_gid": gid,
                        "iverilog_version": iverilog_output,
                        "vvp_version": vvp_output,
                        "compatibility_status": (
                            "codex_cli_0.144.6_iverilog12_repository_agent"
                            if repository_agent
                            else version_output
                        ),
                    }
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
            agent_config=self._require_config().external_agent,
            agent_image=self._agent_image,
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
            "docker_role_images": {
                "verifier": (
                    descriptor.image.model_dump(mode="json") if descriptor.image else None
                ),
                "external_agent": (
                    self._agent_image.model_dump(mode="json") if self._agent_image else None
                ),
            },
            "external_agent_execution_backend": (
                "docker_outer_runtime_delegated"
                if self._agent_image is not None
                else "runtime_external_process_unavailable"
            ),
            "image_observation_source": self._image_observation_source,
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

    def session_registered(
        self,
        session_id: str,
        role: str,
        resolved_image_id: str,
    ) -> None:
        self._session_records[session_id] = RuntimeSessionRecord(
            session_id=session_id,
            role=role,
            resolved_image_id=resolved_image_id,
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


def _external_agent_as_runtime_config(
    config: DockerExternalAgentRuntimeConfig,
) -> DockerRuntimeConfig:
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
        max_command_time_s=config.max_process_time_s,
        max_artifact_file_bytes=16 * 1024 * 1024,
        max_artifact_bytes=64 * 1024 * 1024,
        environment_allowlist=[],
    )


__all__ = ["DockerRuntime"]
