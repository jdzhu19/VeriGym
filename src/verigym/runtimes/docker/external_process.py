"""Runtime-owned Codex control plane with all tools delegated to Docker."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import queue
import signal
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import unquote, urlsplit

from verigym.core.hashing import content_hash, hash_directory
from verigym.hwe.codex_collector import HweExecProtocolCollector
from verigym.hwe.observation import HweObservationCompactor
from verigym.hwe.private_audit import HweRawArtifactWriter
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_ID, HWE_COLLECTION_PROFILE_V2_ID
from verigym.runtimes.docker.control_plane_environment import (
    ControlPlaneEnvironmentError,
    build_trusted_host_app_server_environment,
)
from verigym.runtimes.docker.engine import DockerEngine
from verigym.runtimes.docker.errors import DockerContainerError, DockerRuntimeError
from verigym.runtimes.docker.mounts import MountSpec, mount_arguments
from verigym.runtimes.docker.resources import resource_arguments
from verigym.runtimes.docker.security import security_arguments, verify_effective_container
from verigym.runtimes.docker.stdio_broker import LoopbackWebSocketStdioBroker
from verigym.schemas.common import RuntimeImageIdentity
from verigym.schemas.external_agent import (
    ExternalProcessInvocationSpec,
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalProcessRuntimeIdentity,
    ExternalProcessSecurityEvidence,
    ExternalReadOnlyMountIdentity,
)
from verigym.schemas.runtime import (
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
)

_CONTAINER_ENVIRONMENT = {
    "PATH": "/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "/tmp/verigym-home",
    "CODEX_HOME": "/tmp/verigym-codex-home",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TMPDIR": "/tmp",
}
_FORWARDED_PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY")
_ALL_PROXY_NAMES = (
    *_FORWARDED_PROXY_NAMES,
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
)
_CREDENTIAL_NAME_MARKERS = (
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "AUTH",
)
_APP_SERVER_CONFIG_OVERRIDES = (
    "mcp_servers={}",
    "project_doc_max_bytes=0",
    'web_search="disabled"',
    "features.apps=false",
    "features.auth_elicitation=false",
    "features.browser_use=false",
    "features.browser_use_external=false",
    "features.browser_use_full_cdp_access=false",
    "features.code_mode_host=false",
    "features.computer_use=false",
    "features.goals=false",
    "features.hooks=false",
    "features.image_generation=false",
    "features.in_app_browser=false",
    "features.memories=false",
    "features.multi_agent=false",
    "features.network_proxy=false",
    "features.plugin_sharing=false",
    "features.plugins=false",
    "features.remote_plugin=false",
    "features.respect_system_proxy=true",
    "features.shell_snapshot=false",
    "features.skill_mcp_dependency_install=false",
    "features.tool_call_mcp_elicitation=false",
    "features.tool_suggest=false",
    "features.unified_exec=true",
    "features.workspace_dependencies=false",
    "skills.include_instructions=false",
    "skills.bundled.enabled=false",
    "orchestrator.skills.enabled=false",
    "orchestrator.mcp.enabled=false",
    "include_apps_instructions=false",
    "include_environment_context=false",
    'model_reasoning_effort="xhigh"',
    'approval_policy="never"',
)
_APP_SERVER_EOF = object()
_MAX_APP_SERVER_EVENTS = 10_000


def external_process_configuration_fingerprint(
    *,
    agent_config: DockerExternalAgentRuntimeConfig,
    agent_image_id: str,
    verifier_image_id: str,
    request: ExternalProcessRequest | ExternalProcessInvocationSpec,
    synthesized_environment_names: Sequence[str],
    mandatory_loopback_bypass_present: bool,
) -> str:
    """Hash the complete observable external-process configuration."""

    spec = request.invocation_spec if isinstance(request, ExternalProcessRequest) else request
    static = spec or request
    return content_hash(
        {
            "agent_config": agent_config,
            "agent_image_id": agent_image_id,
            "verifier_image_id": verifier_image_id,
            "protocol": static.protocol,
            "model": static.requested_model_id,
            "reasoning_effort": static.requested_reasoning_effort,
            "auth_semantic_id": static.auth_semantic_id,
            "prompt_policy_hash": static.prompt_policy_hash,
            "read_only_mounts": static.read_only_mounts,
            "proxy_names": static.forwarded_proxy_environment_names,
            "invocation_spec_hash": (
                static.invocation_spec_hash
                if isinstance(static, ExternalProcessInvocationSpec)
                else None
            ),
            "synthesized_control_plane_environment_names": synthesized_environment_names,
            "mandatory_loopback_bypass_present": mandatory_loopback_bypass_present,
            "overrides": list(_APP_SERVER_CONFIG_OVERRIDES),
        }
    )


class DockerExternalProcessExecutor:
    """Execute exactly one app-server turn with a network-none exec-server container."""

    def __init__(
        self,
        *,
        engine: DockerEngine,
        verifier_image: RuntimeImageIdentity,
        agent_image: RuntimeImageIdentity,
        agent_config: DockerExternalAgentRuntimeConfig,
        run_id: str,
        session_id: str,
        register_container: Any,
        remove_container: Any,
        private_audit_root: Path | None = None,
    ) -> None:
        self._engine = engine
        self._verifier_image = verifier_image
        self._agent_image = agent_image
        self._agent_config = agent_config
        self._run_id = run_id
        self._session_id = session_id
        self._register_container = register_container
        self._remove_container = remove_container
        self._private_audit_root = private_audit_root

    def execute(
        self,
        request: ExternalProcessRequest,
        visible_workspace: Path,
        mounts: list[MountSpec] | None = None,
    ) -> ExternalProcessResult:
        started = time.monotonic()
        mounts = mounts or [
            MountSpec(
                source=visible_workspace.resolve(strict=True),
                destination=request.logical_workspace_root,
                read_only=False,
            )
        ]
        self._validate_request(request, mounts)
        if request.workspace_mode == "fresh_empty":
            temporary = tempfile.TemporaryDirectory(prefix="verigym-docker-agent-empty-")
            workspace = Path(temporary.name).resolve()
        else:
            temporary = None
            workspace = visible_workspace.resolve(strict=True)
        before = _workspace_identity(workspace)
        workspace_empty_before = not before
        container_id: str | None = None
        broker: LoopbackWebSocketStdioBroker | None = None
        broker_stopped = False
        hwe_raw_writer: HweRawArtifactWriter | None = None
        hwe_private_audit_manifest: dict[str, object] | None = None
        hwe_protocol_records: list[dict[str, object]] = []
        container_removed = False
        container_exit_inspected = False
        cleanup_verified = False
        group_cleaned = True
        oom_killed = False
        attach_stderr = b""
        attach_stderr_truncated = False
        normalized_stdout = ""
        app_stderr = ""
        exit_code: int | None = None
        timed_out = False
        stdout_truncated = False
        stderr_truncated = False
        terminal = False
        failure_reason: str | None = None
        failure_origin: (
            Literal[
                "host_control_plane",
                "agent_container",
                "broker",
                "external_provider",
            ]
            | None
        ) = None
        effective_verified = False
        app_result: dict[str, Any] = {}
        control_plane_proxy_forwarding_enabled = request.allow_proxy_environment
        control_plane_forwarded_proxy_environment_names = cast(
            list[Literal["HTTP_PROXY", "HTTPS_PROXY"]],
            list(request.forwarded_proxy_environment_names),
        )
        control_plane_synthesized_environment_names: list[Literal["NO_PROXY", "no_proxy"]] = []
        control_plane_mandatory_loopback_bypass_present = not request.allow_proxy_environment
        proxy_redaction_values: tuple[str, ...] = ()
        effective_timeout = min(
            request.timeout_s,
            float(self._agent_config.max_process_time_s),
        )
        try:
            if request.workspace_mode == "fresh_empty":
                mounts = [
                    MountSpec(
                        source=workspace,
                        destination=mount.destination,
                        read_only=mount.read_only,
                    )
                    if mount.destination == request.logical_workspace_root
                    else mount
                    for mount in mounts
                ]
            effective_config = external_agent_runtime_config(self._agent_config)
            user = self._agent_image.effective_user
            if user is None:
                raise DockerContainerError(
                    "external-agent image has no effective non-root user",
                    subreason="root_image_user",
                )
            if user != self._agent_config.run_as_user:
                raise DockerContainerError(
                    "external-agent effective user differs from the runtime configuration",
                    subreason="agent_user_mapping_invalid",
                )
            labels = {
                "org.verigym.managed": "true",
                "org.verigym.run_id": self._run_id,
                "org.verigym.session_id": self._session_id,
                "org.verigym.role": "external-agent",
                "org.verigym.external_protocol": request.protocol,
            }
            arguments = [
                "--interactive",
                *security_arguments(
                    effective_config,
                    user=user,
                    cwd=request.logical_workspace_root,
                    environment=_CONTAINER_ENVIRONMENT,
                    labels=labels,
                ),
                *resource_arguments(effective_config),
                *mount_arguments(mounts),
                self._agent_image.resolved_image_id,
                *request.argv,
            ]
            container_id = self._engine.create_container(arguments)
            self._register_container(container_id)
            inspection = self._engine.inspect_container(container_id)
            verify_effective_container(
                inspection,
                config=effective_config,
                expected_user=user,
                expected_mounts=mounts,
                expected_environment=_CONTAINER_ENVIRONMENT,
                expected_labels=labels,
            )
            _verify_agent_inspection(inspection)
            effective_verified = True
            attach_process = self._engine.start_attach_streaming(container_id)
            protocol_collector: HweExecProtocolCollector | None = None
            if request.integration_track == "codex_cli_hwe_native_shell":
                if self._private_audit_root is None:
                    raise ValueError("HWE native-shell collection requires a private audit root")
                hwe_profile_id = _hwe_request_profile_id(request)
                hwe_raw_writer = HweRawArtifactWriter(
                    self._private_audit_root, profile_id=hwe_profile_id
                )
                protocol_collector = HweExecProtocolCollector(
                    workspace_root=workspace,
                    compactor=HweObservationCompactor(profile_id=hwe_profile_id),
                    raw_writer=hwe_raw_writer,
                    sft_mode=True,
                    profile_id=hwe_profile_id,
                )
            elif self._private_audit_root is not None:
                raise ValueError("private HWE audit root supplied to a non-HWE process")
            broker = LoopbackWebSocketStdioBroker(
                attach_process,
                max_output_bytes=min(
                    request.max_output_bytes,
                    self._agent_config.max_output_bytes,
                ),
                protocol_collector=protocol_collector,
            )
            broker.start()
            app_result = _run_app_server(
                request,
                broker_url=broker.url,
                workspace=workspace,
                effective_timeout_s=effective_timeout,
                broker_health_check=broker.assert_healthy,
            )
            if hwe_raw_writer is not None:
                raw_public_events = app_result.get("_hwe_raw_public_events")
                if not isinstance(raw_public_events, tuple):
                    raise ValueError("HWE app-server omitted its raw public trajectory")
                for sequence, event in enumerate(raw_public_events):
                    if not isinstance(event, dict):
                        raise ValueError("HWE app-server raw public event is malformed")
                    hwe_raw_writer.append(
                        {
                            "schema_version": "1.0",
                            "format_id": "verigym_hwe_raw_public_provider_event_v1",
                            "sequence": sequence,
                            "event": event,
                        }
                    )
            normalized_stdout = app_result["stdout"]
            app_stderr = app_result["stderr"]
            exit_code = app_result["exit_code"]
            timed_out = app_result["timed_out"]
            stdout_truncated = app_result["stdout_truncated"]
            stderr_truncated = app_result["stderr_truncated"]
            terminal = app_result["terminal_event_seen"]
            group_cleaned = app_result["process_group_cleaned"]
            failure_reason = app_result["failure_reason"]
            failure_origin = cast(
                Literal[
                    "host_control_plane",
                    "agent_container",
                    "broker",
                    "external_provider",
                ]
                | None,
                app_result["failure_origin"],
            )
            control_plane_identity = app_result.get("control_plane_environment_identity")
            if isinstance(control_plane_identity, dict):
                control_plane_proxy_forwarding_enabled = bool(
                    control_plane_identity["proxy_forwarding_enabled"]
                )
                control_plane_forwarded_proxy_environment_names = cast(
                    list[Literal["HTTP_PROXY", "HTTPS_PROXY"]],
                    list(control_plane_identity["forwarded_proxy_environment_names"]),
                )
                control_plane_synthesized_environment_names = cast(
                    list[Literal["NO_PROXY", "no_proxy"]],
                    list(control_plane_identity["synthesized_control_plane_environment_names"]),
                )
                control_plane_mandatory_loopback_bypass_present = bool(
                    control_plane_identity["mandatory_loopback_bypass_present"]
                )
                proxy_redaction_values = tuple(app_result.get("_proxy_redaction_values", ()))
            elif request.allow_proxy_environment:
                raise ValueError("app-server result omitted its loopback proxy-bypass identity")
            broker.assert_healthy()
        except DockerRuntimeError as exc:
            exit_code = None
            failure_reason = exc.subreason
            failure_origin = "agent_container"
            app_stderr = str(exc)
        except ControlPlaneEnvironmentError as exc:
            exit_code = None
            failure_reason = exc.reason
            failure_origin = "host_control_plane"
            app_stderr = str(exc)
        except (OSError, RuntimeError, ValueError) as exc:
            exit_code = None
            failure_reason = "runtime_external_process_error"
            failure_origin = "host_control_plane"
            app_stderr = f"{type(exc).__name__}: {exc}"
        finally:
            if broker is not None:
                try:
                    broker_result = broker.stop()
                    broker_stopped = broker_result.stopped
                    attach_stderr = broker_result.stderr
                    attach_stderr_truncated = broker_result.stderr_truncated
                    group_cleaned = group_cleaned and broker_result.process_group_cleaned
                    hwe_protocol_records = list(broker_result.protocol_records)
                except DockerRuntimeError as exc:
                    details = exc.details
                    broker_stopped = details.get("broker_stopped") is True
                    stopped_group_cleaned = details.get("process_group_cleaned") is True
                    group_cleaned = group_cleaned and stopped_group_cleaned
                    records = details.get("protocol_records")
                    if isinstance(records, tuple) and all(
                        isinstance(record, dict) for record in records
                    ):
                        hwe_protocol_records = list(records)
                    if exc.subreason.startswith("hwe_protocol_"):
                        failure_reason = exc.subreason
                        failure_origin = "broker"
                    else:
                        failure_reason = failure_reason or exc.subreason
                        failure_origin = failure_origin or "broker"
            if container_id is not None:
                try:
                    state_payload = self._engine.inspect_container(container_id)
                    state = state_payload.get("State")
                    state = state if isinstance(state, dict) else {}
                    if state.get("Running") is True:
                        kill_result = self._engine.kill_container(container_id)
                        if kill_result.timed_out or kill_result.exit_code != 0:
                            raise DockerContainerError(
                                "external-agent container could not be stopped",
                                subreason="container_kill_failed",
                            )
                        state_payload = self._engine.inspect_container(container_id)
                        state = state_payload.get("State")
                        state = state if isinstance(state, dict) else {}
                    oom_killed = state.get("OOMKilled") is True
                    container_exit_inspected = state.get("Running") is False
                    if not container_exit_inspected:
                        raise DockerContainerError(
                            "external-agent container exit state was not observable",
                            subreason="container_exit_unverified",
                        )
                except DockerRuntimeError as exc:
                    failure_reason = failure_reason or exc.subreason
                    failure_origin = failure_origin or "agent_container"
                    app_stderr = f"{app_stderr}\n{exc}".strip()
                warning = self._remove_container(container_id)
                container_removed = warning is None
                if warning is not None:
                    failure_reason = failure_reason or "container_cleanup_failed"
                    failure_origin = failure_origin or "agent_container"
                    app_stderr = f"{app_stderr}\n{warning}".strip()
                if container_removed:
                    try:
                        managed = self._engine.list_managed_containers()
                        cleanup_verified = not any(
                            container_id.startswith(value) or value.startswith(container_id)
                            for value in managed
                        )
                    except DockerRuntimeError as exc:
                        cleanup_verified = False
                        failure_reason = failure_reason or exc.subreason
                        failure_origin = failure_origin or "agent_container"
                        app_stderr = f"{app_stderr}\n{exc}".strip()
            after = _workspace_identity(workspace)
            if temporary is not None:
                temporary.cleanup()
            if hwe_raw_writer is not None:
                try:
                    hwe_private_audit_manifest = hwe_raw_writer.finalize()
                except (OSError, RuntimeError, ValueError) as exc:
                    failure_reason = failure_reason or "hwe_private_audit_invalid"
                    failure_origin = failure_origin or "broker"
                    app_stderr = f"{app_stderr}\n{type(exc).__name__}: {exc}".strip()
        changed_paths = sorted(
            path for path in set(before) | set(after) if before.get(path) != after.get(path)
        )
        workspace_empty_after = not after
        if request.workspace_mode == "fresh_empty" and changed_paths:
            failure_reason = failure_reason or "fresh_empty_workspace_modified"
            failure_origin = failure_origin or "agent_container"
        combined_stderr = "\n".join(
            item for item in (app_stderr, attach_stderr.decode("utf-8", errors="replace")) if item
        )
        normalized_stdout, stdout_redaction_truncated = _sanitize_and_bound(
            normalized_stdout,
            request=request,
            workspace=workspace,
            proxy_values=proxy_redaction_values,
        )
        combined_stderr, stderr_redaction_truncated = _sanitize_and_bound(
            combined_stderr,
            request=request,
            workspace=workspace,
            proxy_values=proxy_redaction_values,
        )
        stdout_truncated = stdout_truncated or stdout_redaction_truncated
        stderr_truncated = stderr_truncated or attach_stderr_truncated or stderr_redaction_truncated
        user_config_metadata_unchanged = bool(
            app_result.get("user_config_metadata_unchanged", False)
        )
        identity = ExternalProcessRuntimeIdentity(
            execution_owner="verigym_runtime",
            execution_backend="docker_outer_runtime_delegated",
            protocol=request.protocol,
            verifier_image_id=self._verifier_image.resolved_image_id,
            agent_image_id=self._agent_image.resolved_image_id,
            agent_image_reference=self._agent_image.requested_reference,
            agent_image_os=self._agent_image.os,
            agent_image_architecture=self._agent_image.architecture,
            agent_image_user=self._agent_image.effective_user or "",
            agent_executable_name=self._agent_config.expected_executable_name,
            agent_executable_sha256=self._agent_config.expected_executable_sha256,
            agent_executable_version=self._agent_config.expected_executable_version,
            container_id=container_id,
            host_executable_name=request.executable_name,
            host_executable_sha256=request.executable_sha256,
            host_executable_version=request.executable_version,
            capability_fingerprint=request.capability_fingerprint,
            configuration_fingerprint=external_process_configuration_fingerprint(
                agent_config=self._agent_config,
                agent_image_id=self._agent_image.resolved_image_id,
                verifier_image_id=self._verifier_image.resolved_image_id,
                request=request,
                synthesized_environment_names=control_plane_synthesized_environment_names,
                mandatory_loopback_bypass_present=(control_plane_mandatory_loopback_bypass_present),
            ),
            prompt_policy_hash=request.prompt_policy_hash,
            prompt_text_sha256=request.prompt_text_sha256,
            invocation_spec_hash=request.invocation_spec_hash,
            payload_binding_hash=request.payload_binding_hash,
            logical_workspace_root=request.logical_workspace_root,
        )
        security = ExternalProcessSecurityEvidence(
            boundary="docker_outer_runtime",
            network_mode="none",
            read_only_rootfs=True,
            non_root=True,
            cap_drop=["ALL"],
            no_new_privileges=True,
            init=True,
            private_pid_namespace=True,
            private_ipc_namespace=True,
            mount_destinations=cast(
                list[Literal["/verigym-public", "/workspace", "/workspace/repository"]],
                [mount.destination for mount in mounts],
            ),
            writable_destinations=[request.logical_workspace_root, "/tmp"],
            read_only_destinations=[
                cast(Literal["/verigym-public"], mount.destination)
                for mount in mounts
                if mount.read_only
            ],
            public_test_assets_mounted_read_only=any(
                mount.destination == "/verigym-public" and mount.read_only for mount in mounts
            ),
            environment_names=sorted(_CONTAINER_ENVIRONMENT),
            credential_environment_names_in_container=[],
            proxy_environment_names_in_container=[],
            control_plane_proxy_forwarding_enabled=(control_plane_proxy_forwarding_enabled),
            control_plane_forwarded_proxy_environment_names=(
                control_plane_forwarded_proxy_environment_names
            ),
            control_plane_synthesized_environment_names=(
                control_plane_synthesized_environment_names
            ),
            control_plane_mandatory_loopback_bypass_present=(
                control_plane_mandatory_loopback_bypass_present
            ),
            host_home_mounted=False,
            source_repository_mounted=False,
            hidden_verifier_mounted=False,
            docker_socket_mounted=False,
            credential_files_mounted=False,
            api_key_environment_forwarded=False,
            credential_contents_accessed_by_verigym=False,
            user_config_contents_accessed_by_verigym=False,
            user_config_metadata_unchanged=user_config_metadata_unchanged,
            provider_network_in_container=False,
            broker_transport="loopback_websocket_to_container_stdio",
            broker_listen_scope="127.0.0.1",
            effective_controls_verified=effective_verified,
            container_exit_inspected=container_exit_inspected,
            cleanup_verified=cleanup_verified,
            container_removed=container_removed,
            broker_stopped=broker_stopped,
            process_group_cleaned=group_cleaned,
            workspace_empty_before=(
                workspace_empty_before if request.workspace_mode == "fresh_empty" else None
            ),
            workspace_empty_after=(
                workspace_empty_after if request.workspace_mode == "fresh_empty" else None
            ),
            workspace_changed_paths=changed_paths,
            memory_bytes=self._agent_config.memory_bytes,
            cpus=self._agent_config.cpus,
            pids_limit=self._agent_config.pids_limit,
            tmpfs_bytes=self._agent_config.tmpfs_bytes,
            output_limit_bytes=min(
                request.max_output_bytes,
                self._agent_config.max_output_bytes,
            ),
            effective_timeout_s=effective_timeout,
        )
        return ExternalProcessResult(
            exit_code=exit_code,
            stdout=normalized_stdout,
            stderr=combined_stderr,
            duration_s=time.monotonic() - started,
            timed_out=timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            output_limit_hit=stdout_truncated or stderr_truncated,
            oom_killed=oom_killed,
            process_group_cleaned=group_cleaned,
            cleanup_complete=(
                container_removed and cleanup_verified and broker_stopped and group_cleaned
            ),
            terminal_event_seen=terminal,
            failure_reason=failure_reason,
            failure_kind=(
                "infrastructure" if failure_reason == "control_plane_loopback_proxy" else None
            ),
            failure_category=(
                failure_reason if failure_reason == "control_plane_loopback_proxy" else None
            ),
            failure_origin=failure_origin,
            runtime_identity=identity,
            security=security,
            hwe_protocol_records=hwe_protocol_records,
            hwe_private_audit_manifest=hwe_private_audit_manifest,
        )

    def _validate_request(
        self,
        request: ExternalProcessRequest,
        mounts: list[MountSpec],
    ) -> None:
        if request.protocol != self._agent_config.protocol:
            raise ValueError("external process protocol differs from the runtime configuration")
        if request.argv != self._agent_config.process_argv:
            raise ValueError("external process argv differs from the runtime configuration")
        if request.logical_workspace_root != self._agent_config.logical_workspace_root:
            raise ValueError("external process logical workspace root differs from the runtime")
        if request.logical_cwd != self._agent_config.logical_workspace_root:
            raise ValueError("external process logical cwd differs from the runtime")
        expected_mount_policy = (
            "task_workspace_and_public_tests" if request.read_only_mounts else "task_workspace_only"
        )
        if request.network_policy != "none" or request.mount_policy != expected_mount_policy:
            raise ValueError("external process weakened the Docker network or mount policy")
        observed_read_only = [
            ExternalReadOnlyMountIdentity(
                destination=cast(Literal["/verigym-public"], mount.destination),
                content_hash=hash_directory(mount.source),
                label="public_tests",
            )
            for mount in mounts
            if mount.read_only
        ]
        if observed_read_only != request.read_only_mounts:
            raise ValueError("external process read-only mount identity changed")
        workspace_mounts = [
            mount
            for mount in mounts
            if mount.destination == request.logical_workspace_root and not mount.read_only
        ]
        if len(workspace_mounts) != 1 or len(mounts) != 1 + len(observed_read_only):
            raise ValueError("external process mount plan contains an undeclared destination")
        if request.container_environment_names:
            raise ValueError("external process cannot select agent-container environment names")
        if request.timeout_s > float(self._agent_config.max_process_time_s):
            raise ValueError("external process timeout exceeds the runtime-owned limit")
        if request.max_output_bytes > self._agent_config.max_output_bytes:
            raise ValueError("external process output exceeds the runtime-owned limit")
        path = request.executable_path.resolve(strict=True)
        metadata = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
            raise ValueError("external control-plane executable is not a regular executable")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != request.executable_sha256 or path.name != request.executable_name:
            raise ValueError("external control-plane executable identity changed")
        present_names = [name for name in _FORWARDED_PROXY_NAMES if name in os.environ]
        if request.allow_proxy_environment:
            if present_names != request.forwarded_proxy_environment_names:
                raise ValueError("external process proxy-name identity changed")
        elif request.forwarded_proxy_environment_names:
            raise ValueError("external process requested forbidden proxy forwarding")


def _run_app_server(
    request: ExternalProcessRequest,
    *,
    broker_url: str,
    workspace: Path,
    effective_timeout_s: float,
    broker_health_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    arguments = [str(request.executable_path)]
    for override in _APP_SERVER_CONFIG_OVERRIDES:
        arguments.extend(["-c", override])
    arguments.extend(["app-server", "--listen", "stdio://"])
    control_plane_environment = build_trusted_host_app_server_environment(
        allow_proxy_environment=request.allow_proxy_environment,
        forwarded_proxy_environment_names=request.forwarded_proxy_environment_names,
        broker_url=broker_url,
    )
    config_metadata_before = _codex_config_metadata()
    process = subprocess.Popen(
        arguments,
        cwd=workspace,
        env=control_plane_environment.values,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        text=False,
        start_new_session=True,
        close_fds=True,
    )
    client = _AppServerClient(
        process,
        max_output_bytes=request.max_output_bytes,
        hwe_sft_mode=request.integration_track == "codex_cli_hwe_native_shell",
        health_check=broker_health_check,
    )
    deadline = time.monotonic() + effective_timeout_s
    timed_out = False
    terminal = False
    exit_code: int | None = None
    failure_reason: str | None = None
    failure_origin: str | None = None
    try:
        client.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "verigym-docker-external-agent",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
            deadline=deadline,
        )
        client.notify("notifications/initialized", {})
        client.request(
            "environment/add",
            {
                "environmentId": "verigym-docker-agent",
                "execServerUrl": broker_url,
                "connectTimeoutMs": 10_000,
            },
            deadline=deadline,
        )
        environment_info = client.request(
            "environment/info",
            {"environmentId": "verigym-docker-agent"},
            deadline=deadline,
        )
        if not _is_logical_workspace_uri(
            _nested_string(environment_info, "cwd"), request.logical_workspace_root
        ):
            raise RuntimeError("remote environment reported a non-logical workspace cwd")
        thread = client.request(
            "thread/start",
            {
                "model": request.requested_model_id,
                "approvalPolicy": "never",
                "ephemeral": True,
                "baseInstructions": (
                    "Operate only through the selected external Docker environment. "
                    "Never request permissions, network, MCP, apps, plugins, or other agents."
                ),
                "environments": [
                    {
                        "environmentId": "verigym-docker-agent",
                        "cwd": request.logical_workspace_root,
                    }
                ],
            },
            deadline=deadline,
        )
        thread_id = _nested_string(thread, "thread", "id")
        observed_model = _nested_string(thread, "model")
        if not thread_id:
            raise RuntimeError("thread/start returned no thread identity")
        if observed_model != request.requested_model_id:
            raise RuntimeError("thread/start changed the exact requested model")
        client.add_synthetic_event(
            {
                "type": "thread.started",
                "thread_id": thread_id,
                "model": observed_model,
            }
        )
        client.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": request.stdin_text}],
                "environments": [
                    {
                        "environmentId": "verigym-docker-agent",
                        "cwd": request.logical_workspace_root,
                    }
                ],
                "sandboxPolicy": {
                    "type": "externalSandbox",
                    "networkAccess": "restricted",
                },
                "effort": request.requested_reasoning_effort,
            },
            deadline=deadline,
        )
        terminal_payload = client.wait_for_notification("turn/completed", deadline=deadline)
        terminal = True
        turn_status = _nested_string(terminal_payload, "turn", "status")
        turn_error = terminal_payload.get("turn")
        turn_error = turn_error.get("error") if isinstance(turn_error, dict) else None
        if turn_status == "completed" and not turn_error:
            exit_code = 0
        else:
            exit_code = 1
            failure_reason = "external_provider_turn_failed"
            failure_origin = "external_provider"
    except TimeoutError:
        timed_out = True
        failure_reason = "timeout"
        failure_origin = "host_control_plane"
    except DockerRuntimeError as exc:
        client.add_synthetic_event(
            {
                "type": "error",
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
        failure_reason = exc.subreason
        failure_origin = "broker"
    except (RuntimeError, ValueError, OSError) as exc:
        client.add_synthetic_event(
            {
                "type": "error",
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
        failure_reason = (
            "control_plane_loopback_proxy"
            if _is_loopback_proxy_failure(exc, broker_url)
            else "app_server_protocol_error"
        )
        failure_origin = "host_control_plane"
    finally:
        process_group_cleaned = _terminate_process(process)
    config_metadata_after = _codex_config_metadata()
    stdout, stdout_truncated = client.normalized_jsonl()
    stderr, stderr_truncated = client.stderr_text()
    raw_public_events, raw_public_truncated = client.raw_public_events()
    if request.integration_track == "codex_cli_hwe_native_shell" and raw_public_truncated:
        failure_reason = failure_reason or "hwe_raw_public_trajectory_truncated"
        failure_origin = failure_origin or "host_control_plane"
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "terminal_event_seen": terminal,
        "process_group_cleaned": process_group_cleaned,
        "failure_reason": failure_reason,
        "failure_origin": failure_origin,
        "user_config_metadata_unchanged": (config_metadata_before == config_metadata_after),
        "control_plane_environment_identity": (control_plane_environment.safe_identity()),
        "_proxy_redaction_values": control_plane_environment.redaction_values,
        "_hwe_raw_public_events": raw_public_events,
    }


def _is_loopback_proxy_failure(exc: BaseException, broker_url: str) -> bool:
    """Classify an app-server attempt to proxy its runtime-owned loopback channel."""

    parsed = urlsplit(broker_url)
    if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1":
        return False
    message = str(exc).casefold()
    proxy_markers = (
        "proxy connection failed",
        "http connect failed",
        "proxy connect",
        "tunnel connection failed",
    )
    runtime_markers = (
        "exec-server",
        "exec server",
        "environment/info",
        "environment info",
        broker_url.casefold(),
    )
    return any(marker in message for marker in proxy_markers) and any(
        marker in message for marker in runtime_markers
    )


class _AppServerClient:
    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        max_output_bytes: int,
        hwe_sft_mode: bool = False,
        health_check: Callable[[], None] | None = None,
    ) -> None:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise ValueError("app-server process pipes are unavailable")
        self._process = process
        self._max_output_bytes = max_output_bytes
        self._hwe_sft_mode = hwe_sft_mode
        self._health_check = health_check
        self._messages: queue.Queue[dict[str, Any] | object] = queue.Queue(maxsize=1024)
        self._pending: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._event_bytes = 0
        self._events_truncated = False
        self._raw_public_events: list[dict[str, Any]] = []
        self._raw_public_bytes = 0
        self._raw_public_truncated = False
        self._next_id = 0
        self._stdout_error: BaseException | None = None
        self._stderr = bytearray()
        self._stderr_truncated = False
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def request(self, method: str, params: dict[str, Any], *, deadline: float) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            message = self._next_message(deadline)
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {_safe_rpc_error(message['error'])}")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError(f"{method} returned a non-object result")
                return result
            self._consume(message)
            if isinstance(message.get("method"), str):
                self._pending.append(message)

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def wait_for_notification(self, method: str, *, deadline: float) -> dict[str, Any]:
        for index, message in enumerate(self._pending):
            if message.get("method") == method:
                self._pending.pop(index)
                params = message.get("params")
                return params if isinstance(params, dict) else {}
        while True:
            message = self._next_message(deadline)
            if message.get("method") == method:
                self._consume(message)
                params = message.get("params")
                return params if isinstance(params, dict) else {}
            self._consume(message)

    def add_synthetic_event(self, value: dict[str, Any]) -> None:
        self._append_event(value)

    def normalized_jsonl(self) -> tuple[str, bool]:
        lines: list[str] = []
        size = 0
        truncated = self._events_truncated
        for event in self._events:
            line = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            encoded_size = len(line.encode("utf-8")) + 1
            if size + encoded_size > self._max_output_bytes:
                truncated = True
                break
            lines.append(line)
            size += encoded_size
        return ("\n".join(lines) + ("\n" if lines else ""), truncated)

    def stderr_text(self) -> tuple[str, bool]:
        return (
            bytes(self._stderr).decode("utf-8", errors="replace"),
            self._stderr_truncated,
        )

    def _write(self, value: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        payload = (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        try:
            self._process.stdin.write(payload)
            self._process.stdin.flush()
        except BrokenPipeError as exc:
            raise RuntimeError("app-server stdin closed") from exc

    def _next_message(self, deadline: float) -> dict[str, Any]:
        while True:
            if self._stdout_error is not None:
                raise RuntimeError("app-server emitted malformed JSON-RPC") from self._stdout_error
            if self._health_check is not None:
                self._health_check()
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise TimeoutError("app-server deadline expired")
            try:
                item = self._messages.get(timeout=min(timeout, 0.25))
                break
            except queue.Empty:
                continue
        if item is _APP_SERVER_EOF:
            if self._stdout_error is not None:
                raise RuntimeError("app-server emitted malformed JSON-RPC") from self._stdout_error
            raise RuntimeError("app-server stdout closed before the protocol completed")
        assert isinstance(item, dict)
        message = item
        if message.get("method") and "id" in message:
            raise RuntimeError("unexpected app-server request fails closed")
        return message

    def _consume(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        if self._hwe_sft_mode and _is_hwe_public_provider_event(method, params):
            encoded_size = len(
                json.dumps(
                    message, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
            )
            if self._raw_public_bytes + encoded_size + 1 > self._max_output_bytes:
                self._raw_public_truncated = True
            else:
                self._raw_public_events.append(message)
                self._raw_public_bytes += encoded_size + 1
        if (
            self._hwe_sft_mode
            and method.startswith("item/")
            and method
            not in {
                "item/started",
                "item/completed",
                "item/commandExecution/outputDelta",
                "item/commandExecution/terminalInteraction",
                "item/fileChange/outputDelta",
                "item/fileChange/patchUpdated",
                "item/agentMessage/delta",
                "item/reasoning/delta",
                "item/reasoning/summaryTextDelta",
                "item/reasoning/summaryPartAdded",
                "item/plan/delta",
            }
        ):
            raise RuntimeError("unknown output-bearing app-server notification fails closed")
        event = _normalize_app_server_notification(method, params)
        if (
            self._hwe_sft_mode
            and isinstance(event, dict)
            and isinstance(event.get("item"), dict)
            and event["item"].get("type")
            in {
                "agent_message",
                "command_execution",
                "file_change",
                "mcp_tool_call",
                "web_search",
                "plan",
            }
        ):
            return
        if event is not None:
            self._append_event(event)

    def raw_public_events(self) -> tuple[tuple[dict[str, Any], ...], bool]:
        return tuple(self._raw_public_events), self._raw_public_truncated

    def _append_event(self, event: dict[str, Any]) -> None:
        encoded_size = (
            len(
                json.dumps(
                    event,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            + 1
        )
        if (
            len(self._events) >= _MAX_APP_SERVER_EVENTS
            or self._event_bytes + encoded_size > self._max_output_bytes
        ):
            self._events_truncated = True
            return
        self._events.append(event)
        self._event_bytes += encoded_size

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                if len(line) > 1024 * 1024:
                    raise ValueError("app-server JSON-RPC line exceeds its bound")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("app-server JSON-RPC message is not an object")
                self._messages.put(value)
        except BaseException as exc:
            self._stdout_error = exc
        finally:
            self._messages.put(_APP_SERVER_EOF)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        while True:
            chunk = self._process.stderr.read(8192)
            if not chunk:
                return
            remaining = self._max_output_bytes - len(self._stderr)
            if remaining > 0:
                self._stderr.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self._stderr_truncated = True


def _normalize_app_server_notification(
    method: str, params: dict[str, Any]
) -> dict[str, Any] | None:
    if method in {"thread/started", "turn/started"}:
        return {
            "type": method.replace("/", "."),
            "thread_id": params.get("threadId"),
            "status": _nested_string(params, "turn", "status"),
        }
    if method == "turn/completed":
        turn = params.get("turn")
        turn_mapping = turn if isinstance(turn, dict) else {}
        value: dict[str, Any] = {
            "type": "turn.completed",
            "thread_id": params.get("threadId"),
            "status": turn_mapping.get("status"),
        }
        if turn_mapping.get("error") is not None:
            value["error"] = turn_mapping.get("error")
        return value
    if method in {"item/started", "item/completed"}:
        item = params.get("item")
        if not isinstance(item, dict):
            return None
        item_type = str(item.get("type", ""))
        if item_type in {"userMessage", "reasoning", "reasoningSummary"}:
            return None
        mapped = {
            "agentMessage": "agent_message",
            "commandExecution": "command_execution",
            "fileChange": "file_change",
            "mcpToolCall": "mcp_tool_call",
            "webSearch": "web_search",
            "plan": "plan",
        }.get(item_type, _camel_to_snake(item_type))
        safe_item = {_camel_to_snake(str(key)): _snake_value(value) for key, value in item.items()}
        safe_item["type"] = mapped
        return {
            "type": method.replace("/", "."),
            "thread_id": params.get("threadId"),
            "turn_id": params.get("turnId"),
            "item": safe_item,
        }
    if method == "item/fileChange/patchUpdated":
        changes = params.get("changes")
        paths: list[str] = []
        raw_diffs: list[str] = []
        if not isinstance(changes, list) or not changes:
            raise RuntimeError("HWE patchUpdated notification omits schema-defined changes")
        for change in changes:
            if not isinstance(change, dict):
                raise RuntimeError("HWE patchUpdated change is malformed")
            path = change.get("path")
            diff = change.get("diff")
            kind = change.get("kind")
            if (
                not isinstance(path, str)
                or not path
                or not isinstance(diff, str)
                or not isinstance(kind, dict)
                or kind.get("type") not in {"add", "delete", "update"}
            ):
                raise RuntimeError("HWE patchUpdated change violates the Codex 0.147 schema")
            paths.append(_hwe_patch_path(path))
            raw_diffs.append(diff)
        patch = "".join(value if value.endswith("\n") else f"{value}\n" for value in raw_diffs)
        return {
            "type": "file_change.patch_updated",
            "thread_id": params.get("threadId"),
            "turn_id": params.get("turnId"),
            "item_id": params.get("itemId"),
            "paths": paths,
            "patch": patch,
        }
    if method in {
        "item/commandExecution/outputDelta",
        "item/commandExecution/terminalInteraction",
        "item/fileChange/outputDelta",
        "item/agentMessage/delta",
        "item/reasoning/delta",
        "item/reasoning/summaryTextDelta",
        "item/reasoning/summaryPartAdded",
        "item/plan/delta",
    }:
        # Incremental/private/UI material never becomes a training message. Completed command and
        # patch items retain the public action/observation evidence.
        return None
    if method == "thread/tokenUsage/updated":
        usage = params.get("tokenUsage")
        usage = usage.get("last") if isinstance(usage, dict) else None
        if not isinstance(usage, dict):
            return None
        return {
            "type": "usage",
            "usage": {
                "input_tokens": usage.get("inputTokens"),
                "output_tokens": usage.get("outputTokens"),
                "total_tokens": usage.get("totalTokens"),
            },
        }
    if method == "error":
        return {"type": "error", "message": params.get("message")}
    return None


def _is_hwe_public_provider_event(method: str, params: dict[str, Any]) -> bool:
    if method.startswith("item/reasoning/") or method.startswith("item/plan/"):
        return False
    if method in {"item/started", "item/completed"}:
        item = params.get("item")
        if isinstance(item, dict) and item.get("type") in {
            "userMessage",
            "reasoning",
            "reasoningSummary",
            "plan",
        }:
            return False
    return method.startswith(("thread/", "turn/", "item/"))


def _hwe_patch_path(value: str) -> str:
    if value.startswith("/workspace/repository/"):
        return value.removeprefix("/workspace/repository/")
    if value.startswith("/workspace/"):
        return value.removeprefix("/workspace/")
    return value


def _hwe_request_profile_id(request: ExternalProcessRequest) -> str:
    spec = request.invocation_spec
    if spec is None:
        raise ValueError("HWE native-shell request lacks its invocation identity")
    mapping = {
        "codex_cli_hwe_native_shell_context_v2": HWE_COLLECTION_PROFILE_ID,
        "codex_cli_hwe_native_shell_context_v3": HWE_COLLECTION_PROFILE_V2_ID,
        "codex_cli_hwe_native_shell_context_v4": HWE_COLLECTION_PROFILE_V2_ID,
        "codex_cli_hwe_native_shell_context_v5": HWE_COLLECTION_PROFILE_V2_ID,
        "codex_cli_hwe_native_shell_context_v6": HWE_COLLECTION_PROFILE_V2_ID,
        "codex_cli_hwe_native_shell_context_v7": HWE_COLLECTION_PROFILE_V2_ID,
        "codex_cli_hwe_native_shell_context_v8": HWE_COLLECTION_PROFILE_V2_ID,
        "codex_cli_hwe_native_shell_context_v9": HWE_COLLECTION_PROFILE_V2_ID,
    }
    try:
        return mapping[spec.prompt_contract_id]
    except KeyError as exc:
        raise ValueError("HWE native-shell request uses an unknown prompt contract") from exc


def _snake_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {_camel_to_snake(str(key)): _snake_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snake_value(item) for item in value]
    return value


def _camel_to_snake(value: str) -> str:
    result: list[str] = []
    for character in value:
        if character.isupper() and result:
            result.append("_")
        result.append(character.lower())
    return "".join(result)


def _terminate_process(process: subprocess.Popen[bytes]) -> bool:
    if process.stdin is not None and not process.stdin.closed:
        try:
            process.stdin.close()
        except OSError:
            pass
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return False
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _workspace_identity(root: Path) -> dict[str, str]:
    identity: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".verigym_internal" in relative.parts:
            continue
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"external-agent workspace symlink is forbidden: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError(f"external-agent workspace special link is forbidden: {relative}")
        identity[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return identity


def _verify_agent_inspection(payload: dict[str, Any]) -> None:
    config = payload.get("Config")
    host = payload.get("HostConfig")
    config = config if isinstance(config, dict) else {}
    host = host if isinstance(host, dict) else {}
    env = config.get("Env")
    names = {str(value).partition("=")[0] for value in env} if isinstance(env, list) else set()
    forbidden = sorted(
        name
        for name in names
        if name in _ALL_PROXY_NAMES
        or any(marker in name.upper() for marker in _CREDENTIAL_NAME_MARKERS)
    )
    if forbidden:
        raise DockerContainerError(
            "agent container received a credential or proxy environment name",
            subreason="credential_boundary_violation",
        )
    if host.get("NetworkMode") != "none":
        raise DockerContainerError(
            "agent container does not have network=none",
            subreason="mandatory_control_mismatch",
        )


def external_agent_runtime_config(
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
        environment_allowlist=["CODEX_HOME"],
    )


def _sanitize_and_bound(
    value: str,
    *,
    request: ExternalProcessRequest,
    workspace: Path,
    proxy_values: tuple[str, ...] = (),
) -> tuple[str, bool]:
    clean = value.replace(str(workspace), "<task_workspace>")
    home = os.environ.get("HOME")
    if home:
        clean = clean.replace(home, "<home>")
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        clean = clean.replace(codex_home, "<codex_home>")
    if request.allow_proxy_environment:
        values = {proxy for name in _ALL_PROXY_NAMES for proxy in (os.environ.get(name),) if proxy}
        values.update(proxy for proxy in proxy_values if proxy)
        for proxy in sorted(values, key=len, reverse=True):
            clean = clean.replace(proxy, "<redacted-proxy>")
            clean = clean.replace(
                json.dumps(proxy, ensure_ascii=False)[1:-1],
                "<redacted-proxy>",
            )
    encoded = clean.encode("utf-8")
    if len(encoded) <= request.max_output_bytes:
        return clean, False
    half = request.max_output_bytes // 2
    bounded = encoded[:half] + encoded[-(request.max_output_bytes - half) :]
    return bounded.decode("utf-8", errors="replace"), True


def _nested_string(value: dict[str, Any], *keys: str) -> str | None:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, str) else None


def _safe_rpc_error(value: Any) -> str:
    if isinstance(value, dict):
        message = value.get("message")
        return str(message)[:1024] if message is not None else "unspecified JSON-RPC error"
    return str(value)[:1024]


def _is_logical_workspace_uri(value: str | None, expected_path: str = "/workspace") -> bool:
    if value is None:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "file"
        and parsed.netloc == ""
        and unquote(parsed.path) == expected_path
        and not parsed.query
        and not parsed.fragment
    )


def _codex_config_metadata() -> tuple[tuple[int, ...] | None, tuple[int, ...] | None]:
    """Observe config identity without reading, hashing, or persisting its contents/path."""

    home = os.environ.get("HOME")
    if home is None:
        raise RuntimeError("inherited Codex login requires HOME")
    root = Path(os.environ.get("CODEX_HOME", str(Path(home) / ".codex")))
    path = root / "config.toml"

    def metadata(*, follow_symlinks: bool) -> tuple[int, ...] | None:
        try:
            value = os.stat(path, follow_symlinks=follow_symlinks)
        except FileNotFoundError:
            return None
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_uid,
            value.st_gid,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    return metadata(follow_symlinks=False), metadata(follow_symlinks=True)


def path_matches(path: str, patterns: list[str]) -> bool:
    """Stable glob helper retained for runtime-policy tests."""

    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


__all__ = ["DockerExternalProcessExecutor", "path_matches"]
