"""Persistent identity and accounting for externally executed coding agents."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.prompt import PromptPolicyDescriptor

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_FORWARDED_PROXY_ENVIRONMENT_NAMES = {"HTTP_PROXY", "HTTPS_PROXY"}
_CONTAINER_PROXY_ENVIRONMENT_NAMES = {
    *_FORWARDED_PROXY_ENVIRONMENT_NAMES,
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
}


class ExternalReadOnlyMountIdentity(StrictModel):
    """Content identity for a runtime-staged agent-container read-only mount."""

    destination: Literal["/verigym-public"]
    content_hash: str
    label: Literal["public_tests"]

    @field_validator("content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("external read-only mount hash must be lowercase SHA-256")
        return value


class ExternalProcessInvocationSpec(StrictModel):
    """Static, payload-free identity for one runtime-owned external process."""

    schema_version: str = SCHEMA_VERSION
    protocol: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    runtime_role: Literal["agent"] = "agent"
    argv: list[str] = Field(min_length=1, max_length=64)
    logical_cwd: Literal["/workspace", "/workspace/repository"] = "/workspace"
    stdin_transport: Literal["runtime_protocol_adapter"] = "runtime_protocol_adapter"
    network_policy: Literal["none"] = "none"
    mount_policy: Literal[
        "task_workspace_only",
        "task_workspace_and_public_tests",
    ] = "task_workspace_only"
    writable_destinations: list[Literal["/workspace", "/workspace/repository", "/tmp"]]
    read_only_mounts: list[ExternalReadOnlyMountIdentity] = Field(default_factory=list)
    container_environment_names: list[str] = Field(default_factory=list)
    integration_track: str = Field(min_length=1, max_length=128)
    workspace_mode: Literal["fresh_empty", "visible_task_workspace"]
    logical_workspace_root: Literal["/workspace", "/workspace/repository"] = "/workspace"
    requested_model_id: str = Field(min_length=1, max_length=256)
    requested_reasoning_effort: str = Field(min_length=1, max_length=32)
    executable_path_identity: Literal["verified_host_codex_cli"] = "verified_host_codex_cli"
    executable_name: str = Field(min_length=1, max_length=256)
    executable_sha256: str
    executable_version: str = Field(min_length=1, max_length=512)
    capability_fingerprint: str
    requested_auth_mode: str = Field(min_length=1, max_length=64)
    resolved_auth_mode: str = Field(min_length=1, max_length=64)
    auth_semantic_id: str = Field(min_length=1, max_length=128)
    allow_proxy_environment: bool
    forwarded_proxy_environment_names: list[str] = Field(default_factory=list)
    timeout_s: float = Field(gt=0.0, le=3600.0)
    max_output_bytes: int = Field(ge=1024, le=32 * 1024 * 1024)
    editable_globs: list[str] = Field(default_factory=list)
    readonly_globs: list[str] = Field(default_factory=list)
    prompt_policy: PromptPolicyDescriptor | None = None
    prompt_policy_hash: str | None = None
    prompt_contract_id: str = Field(min_length=1, max_length=192)
    expected_output_schema_hash: str
    invocation_spec_hash: str

    @field_validator(
        "executable_sha256",
        "capability_fingerprint",
        "prompt_policy_hash",
        "expected_output_schema_hash",
        "invocation_spec_hash",
    )
    @classmethod
    def validate_spec_hash(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("external invocation hashes must be lowercase SHA-256")
        return value

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, values: list[str]) -> list[str]:
        if any(
            not value or "\x00" in value or "\r" in value or "\n" in value or len(value) > 4096
            for value in values
        ):
            raise ValueError("external invocation argv contains an invalid argument")
        return values

    @field_validator("forwarded_proxy_environment_names")
    @classmethod
    def validate_proxy_names(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("forwarded proxy environment names must be unique")
        if any(
            not _SAFE_ENVIRONMENT_NAME.fullmatch(value)
            or value not in _FORWARDED_PROXY_ENVIRONMENT_NAMES
            for value in values
        ):
            raise ValueError("external invocation proxy forwarding is outside the strict allowlist")
        return [name for name in ("HTTP_PROXY", "HTTPS_PROXY") if name in set(values)]

    @field_validator("container_environment_names")
    @classmethod
    def validate_container_environment_names(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("container environment names must be unique")
        if any(not _SAFE_ENVIRONMENT_NAME.fullmatch(value) for value in values):
            raise ValueError("invalid container environment name")
        if any(
            value in _CONTAINER_PROXY_ENVIRONMENT_NAMES
            or re.search(r"(?:TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH)", value, re.I)
            for value in values
        ):
            raise ValueError("credential or proxy environment names are forbidden in the agent")
        return sorted(values)

    @model_validator(mode="after")
    def validate_spec_contract(self) -> ExternalProcessInvocationSpec:
        expected_workspace = (
            "/workspace/repository"
            if self.integration_track == "codex_cli_hwe_native_shell"
            else "/workspace"
        )
        if self.logical_workspace_root != expected_workspace:
            raise ValueError("external invocation workspace differs from its integration track")
        if self.forwarded_proxy_environment_names and not self.allow_proxy_environment:
            raise ValueError("proxy names require allow_proxy_environment=true")
        if self.container_environment_names:
            raise ValueError(
                "external agent-container environment is owned entirely by the runtime"
            )
        if self.logical_cwd != self.logical_workspace_root:
            raise ValueError("external invocation cwd differs from its workspace root")
        if self.writable_destinations != [self.logical_workspace_root, "/tmp"]:
            raise ValueError("Docker external processes have exactly two writable destinations")
        expected_mount_policy = (
            "task_workspace_and_public_tests" if self.read_only_mounts else "task_workspace_only"
        )
        if self.mount_policy != expected_mount_policy:
            raise ValueError(
                "external invocation mount policy disagrees with read-only mount identity"
            )
        if len(self.read_only_mounts) > 1:
            raise ValueError("external invocation supports at most one public-test mount")
        if (self.prompt_policy is None) != (self.prompt_policy_hash is None):
            raise ValueError("external invocation prompt policy fields must be supplied together")
        if (
            self.prompt_policy is not None
            and self.prompt_policy_hash != self.prompt_policy.configuration_fingerprint
        ):
            raise ValueError("external invocation prompt policy hash is inconsistent")
        payload = self.model_dump(mode="json", exclude={"invocation_spec_hash"})
        if content_hash(payload) != self.invocation_spec_hash:
            raise ValueError("external invocation specification identity changed")
        return self


class ExternalProcessIdentityPreview(StrictModel):
    """Zero-I/O statement that a static process identity has no payload yet."""

    schema_version: str = SCHEMA_VERSION
    invocation_spec_hash: str
    payload_state: Literal["unbound"] = "unbound"
    stdin_sha256: None = None
    stdin_utf8_bytes: None = None
    payload_binding_hash: None = None
    launch_authorized: Literal[False] = False
    preview_hash: str

    @field_validator("invocation_spec_hash", "preview_hash")
    @classmethod
    def validate_preview_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("external process preview hashes must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_preview_identity(self) -> ExternalProcessIdentityPreview:
        payload = self.model_dump(mode="json", exclude={"preview_hash"})
        if content_hash(payload) != self.preview_hash:
            raise ValueError("external process identity preview changed")
        return self


class ExternalProcessPayloadBinding(StrictModel):
    """Hash-only binding between one static invocation and its rendered stdin."""

    schema_version: str = SCHEMA_VERSION
    invocation_spec_hash: str
    payload_state: Literal["bound"] = "bound"
    stdin_sha256: str
    stdin_utf8_bytes: int = Field(ge=1, le=2 * 1024 * 1024)
    prompt_contract_id: str = Field(min_length=1, max_length=192)
    template_hash: str
    input_dataset_hash: str
    rendered_prompt_hash: str
    payload_binding_hash: str

    @field_validator(
        "invocation_spec_hash",
        "stdin_sha256",
        "template_hash",
        "input_dataset_hash",
        "rendered_prompt_hash",
        "payload_binding_hash",
    )
    @classmethod
    def validate_binding_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("external payload hashes must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_payload_identity(self) -> ExternalProcessPayloadBinding:
        if self.stdin_sha256 != self.rendered_prompt_hash:
            raise ValueError("rendered prompt hash differs from stdin hash")
        payload = self.model_dump(mode="json", exclude={"payload_binding_hash"})
        if content_hash(payload) != self.payload_binding_hash:
            raise ValueError("external process payload binding changed")
        return self


class ExternalProcessRequest(StrictModel):
    """In-memory, runtime-owned request for one external agent process."""

    schema_version: str = SCHEMA_VERSION
    protocol: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    runtime_role: Literal["agent"] = "agent"
    argv: list[str] = Field(min_length=1, max_length=64)
    logical_cwd: Literal["/workspace", "/workspace/repository"] = "/workspace"
    stdin_text: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    stdin_transport: Literal["runtime_protocol_adapter"] = "runtime_protocol_adapter"
    network_policy: Literal["none"] = "none"
    mount_policy: Literal[
        "task_workspace_only",
        "task_workspace_and_public_tests",
    ] = "task_workspace_only"
    writable_destinations: list[Literal["/workspace", "/workspace/repository", "/tmp"]]
    read_only_mounts: list[ExternalReadOnlyMountIdentity] = Field(default_factory=list)
    container_environment_names: list[str] = Field(default_factory=list)
    integration_track: str = Field(min_length=1, max_length=128)
    workspace_mode: Literal["fresh_empty", "visible_task_workspace"]
    logical_workspace_root: Literal["/workspace", "/workspace/repository"] = "/workspace"
    requested_model_id: str = Field(min_length=1, max_length=256)
    requested_reasoning_effort: str = Field(min_length=1, max_length=32)
    executable_path: Path
    executable_name: str = Field(min_length=1, max_length=256)
    executable_sha256: str
    executable_version: str = Field(min_length=1, max_length=512)
    capability_fingerprint: str
    requested_auth_mode: str = Field(min_length=1, max_length=64)
    resolved_auth_mode: str = Field(min_length=1, max_length=64)
    auth_semantic_id: str = Field(min_length=1, max_length=128)
    allow_proxy_environment: bool
    forwarded_proxy_environment_names: list[str] = Field(default_factory=list)
    timeout_s: float = Field(gt=0.0, le=3600.0)
    max_output_bytes: int = Field(ge=1024, le=32 * 1024 * 1024)
    editable_globs: list[str] = Field(default_factory=list)
    readonly_globs: list[str] = Field(default_factory=list)
    prompt_policy: PromptPolicyDescriptor | None = None
    prompt_policy_hash: str | None = None
    prompt_text_sha256: str | None = None
    invocation_spec: ExternalProcessInvocationSpec | None = None
    payload_binding: ExternalProcessPayloadBinding | None = None
    invocation_spec_hash: str | None = None
    payload_binding_hash: str | None = None
    stdin_utf8_bytes: int | None = Field(default=None, ge=1, le=2 * 1024 * 1024)

    @field_validator(
        "executable_sha256",
        "capability_fingerprint",
        "prompt_policy_hash",
        "prompt_text_sha256",
        "invocation_spec_hash",
        "payload_binding_hash",
    )
    @classmethod
    def validate_request_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SHA256.fullmatch(value):
            raise ValueError("external process hashes must be lowercase SHA-256 values")
        return value

    @field_validator("forwarded_proxy_environment_names")
    @classmethod
    def validate_proxy_names(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("forwarded proxy environment names must be unique")
        if any(
            not _SAFE_ENVIRONMENT_NAME.fullmatch(value)
            or value not in _FORWARDED_PROXY_ENVIRONMENT_NAMES
            for value in values
        ):
            raise ValueError("external process proxy forwarding is outside the strict allowlist")
        return [name for name in ("HTTP_PROXY", "HTTPS_PROXY") if name in set(values)]

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, values: list[str]) -> list[str]:
        if any(
            not value or "\x00" in value or "\r" in value or "\n" in value or len(value) > 4096
            for value in values
        ):
            raise ValueError("external process argv contains an invalid argument")
        return values

    @field_validator("container_environment_names")
    @classmethod
    def validate_container_environment_names(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("container environment names must be unique")
        if any(not _SAFE_ENVIRONMENT_NAME.fullmatch(value) for value in values):
            raise ValueError("invalid container environment name")
        if any(
            value in _CONTAINER_PROXY_ENVIRONMENT_NAMES
            or re.search(r"(?:TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH)", value, re.I)
            for value in values
        ):
            raise ValueError("credential or proxy environment names are forbidden in the agent")
        return sorted(values)

    @model_validator(mode="after")
    def validate_request_contract(self) -> ExternalProcessRequest:
        expected_workspace = (
            "/workspace/repository"
            if self.integration_track == "codex_cli_hwe_native_shell"
            else "/workspace"
        )
        if self.logical_workspace_root != expected_workspace:
            raise ValueError("external process workspace differs from its integration track")
        if self.forwarded_proxy_environment_names and not self.allow_proxy_environment:
            raise ValueError("proxy names require allow_proxy_environment=true")
        if self.container_environment_names:
            raise ValueError(
                "external agent-container environment is owned entirely by the runtime"
            )
        if self.logical_cwd != self.logical_workspace_root:
            raise ValueError("external process cwd differs from its workspace root")
        if self.writable_destinations != [self.logical_workspace_root, "/tmp"]:
            raise ValueError("Docker external processes have exactly two writable destinations")
        expected_mount_policy = (
            "task_workspace_and_public_tests" if self.read_only_mounts else "task_workspace_only"
        )
        if self.mount_policy != expected_mount_policy:
            raise ValueError(
                "external process mount policy disagrees with read-only mount identity"
            )
        if len(self.read_only_mounts) > 1:
            raise ValueError("external process supports at most one public-test mount")
        prompt_fields = (
            self.prompt_policy,
            self.prompt_policy_hash,
            self.prompt_text_sha256,
        )
        if any(value is not None for value in prompt_fields) and not all(
            value is not None for value in prompt_fields
        ):
            raise ValueError("external process prompt identity fields must be supplied together")
        if self.prompt_policy is not None:
            if self.prompt_policy_hash != self.prompt_policy.configuration_fingerprint:
                raise ValueError("external process prompt policy hash is inconsistent")
            if (
                self.prompt_text_sha256
                != hashlib.sha256(self.stdin_text.encode("utf-8")).hexdigest()
            ):
                raise ValueError("external process prompt text hash is inconsistent")
        lifecycle_fields = (
            self.invocation_spec,
            self.payload_binding,
            self.invocation_spec_hash,
            self.payload_binding_hash,
            self.stdin_utf8_bytes,
        )
        if any(value is not None for value in lifecycle_fields) and not all(
            value is not None for value in lifecycle_fields
        ):
            raise ValueError("external process lifecycle identities must be supplied together")
        if self.invocation_spec is not None and self.payload_binding is not None:
            if (
                self.invocation_spec_hash != self.invocation_spec.invocation_spec_hash
                or self.payload_binding_hash != self.payload_binding.payload_binding_hash
                or self.payload_binding.invocation_spec_hash != self.invocation_spec_hash
                or self.payload_binding.prompt_contract_id
                != self.invocation_spec.prompt_contract_id
                or self.payload_binding.stdin_sha256
                != hashlib.sha256(self.stdin_text.encode("utf-8")).hexdigest()
                or self.stdin_utf8_bytes != len(self.stdin_text.encode("utf-8"))
            ):
                raise ValueError("external process request differs from its lifecycle binding")
        return self


class ExternalProcessRuntimeIdentity(StrictModel):
    schema_version: str = SCHEMA_VERSION
    execution_owner: Literal["verigym_runtime"]
    execution_backend: Literal["docker_outer_runtime_delegated"]
    protocol: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    verifier_image_id: str
    agent_image_id: str
    agent_image_reference: str
    agent_image_os: str
    agent_image_architecture: str
    agent_image_user: str
    agent_executable_name: str = Field(min_length=1, max_length=128)
    agent_executable_sha256: str
    agent_executable_version: str
    container_id: str | None = None
    host_executable_name: str
    host_executable_sha256: str
    host_executable_version: str
    capability_fingerprint: str
    configuration_fingerprint: str
    prompt_policy_hash: str | None = None
    prompt_text_sha256: str | None = None
    invocation_spec_hash: str | None = None
    payload_binding_hash: str | None = None
    logical_workspace_root: Literal["/workspace", "/workspace/repository"]
    model_process_count: Literal[1] = 1
    exec_server_process_count: Literal[1] = 1

    @field_validator(
        "host_executable_sha256",
        "capability_fingerprint",
        "configuration_fingerprint",
        "agent_executable_sha256",
        "prompt_policy_hash",
        "prompt_text_sha256",
        "invocation_spec_hash",
        "payload_binding_hash",
    )
    @classmethod
    def validate_identity_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SHA256.fullmatch(value):
            raise ValueError("external runtime identity hashes must be lowercase SHA-256")
        return value

    @field_validator("verifier_image_id", "agent_image_id")
    @classmethod
    def validate_image_id(cls, value: str) -> str:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("external runtime image identities must be immutable SHA-256 IDs")
        return value


class ExternalProcessSecurityEvidence(StrictModel):
    schema_version: str = SCHEMA_VERSION
    boundary: Literal["docker_outer_runtime"]
    network_mode: Literal["none"]
    read_only_rootfs: Literal[True]
    non_root: Literal[True]
    cap_drop: list[Literal["ALL"]]
    no_new_privileges: Literal[True]
    init: Literal[True]
    private_pid_namespace: Literal[True]
    private_ipc_namespace: Literal[True]
    mount_destinations: list[Literal["/verigym-public", "/workspace", "/workspace/repository"]]
    writable_destinations: list[Literal["/workspace", "/workspace/repository", "/tmp"]]
    read_only_destinations: list[Literal["/verigym-public"]] = Field(default_factory=list)
    public_test_assets_mounted_read_only: bool = False
    environment_names: list[str]
    credential_environment_names_in_container: list[str]
    proxy_environment_names_in_container: list[str]
    control_plane_proxy_forwarding_enabled: bool = False
    control_plane_forwarded_proxy_environment_names: list[Literal["HTTP_PROXY", "HTTPS_PROXY"]] = (
        Field(default_factory=list)
    )
    control_plane_synthesized_environment_names: list[Literal["NO_PROXY", "no_proxy"]] = Field(
        default_factory=list
    )
    control_plane_mandatory_loopback_bypass_present: bool = True
    host_home_mounted: Literal[False]
    source_repository_mounted: Literal[False]
    hidden_verifier_mounted: Literal[False]
    docker_socket_mounted: Literal[False]
    credential_files_mounted: Literal[False]
    api_key_environment_forwarded: Literal[False]
    credential_contents_accessed_by_verigym: Literal[False]
    user_config_contents_accessed_by_verigym: Literal[False]
    user_config_metadata_unchanged: bool
    provider_network_in_container: Literal[False]
    broker_transport: Literal["loopback_websocket_to_container_stdio"]
    broker_listen_scope: Literal["127.0.0.1"]
    effective_controls_verified: bool
    container_exit_inspected: bool
    cleanup_verified: bool
    container_removed: bool
    broker_stopped: bool
    process_group_cleaned: bool
    workspace_empty_before: bool | None = None
    workspace_empty_after: bool | None = None
    workspace_changed_paths: list[str] = Field(default_factory=list)
    memory_bytes: int = Field(ge=1)
    cpus: float = Field(gt=0.0)
    pids_limit: int = Field(ge=1)
    tmpfs_bytes: int = Field(ge=1)
    output_limit_bytes: int = Field(ge=1)
    effective_timeout_s: float = Field(gt=0.0)

    @model_validator(mode="after")
    def fail_closed_credential_boundary(self) -> ExternalProcessSecurityEvidence:
        if self.credential_environment_names_in_container:
            raise ValueError("agent container may not receive credential environment names")
        if self.proxy_environment_names_in_container:
            raise ValueError("agent container may not receive proxy environment names")
        if self.control_plane_forwarded_proxy_environment_names != [
            name
            for name in ("HTTP_PROXY", "HTTPS_PROXY")
            if name in set(self.control_plane_forwarded_proxy_environment_names)
        ]:
            raise ValueError("trusted host proxy-name identity must be canonical and unique")
        if self.control_plane_proxy_forwarding_enabled:
            if (
                self.control_plane_mandatory_loopback_bypass_present
                and self.control_plane_synthesized_environment_names != ["NO_PROXY", "no_proxy"]
            ):
                raise ValueError(
                    "trusted host loopback bypass requires both synthesized environment names"
                )
        elif (
            self.control_plane_forwarded_proxy_environment_names
            or self.control_plane_synthesized_environment_names
            or not self.control_plane_mandatory_loopback_bypass_present
        ):
            raise ValueError("disabled trusted host proxy forwarding has inconsistent evidence")
        if self.cap_drop != ["ALL"]:
            raise ValueError("agent container must drop all capabilities")
        if self.writable_destinations not in (
            ["/workspace", "/tmp"],
            ["/workspace/repository", "/tmp"],
        ):
            raise ValueError("agent container has an undeclared writable destination")
        expected_mounts = [*self.read_only_destinations, self.writable_destinations[0]]
        if self.mount_destinations != expected_mounts:
            raise ValueError("agent container has an undeclared mount destination")
        if self.read_only_destinations not in ([], ["/verigym-public"]):
            raise ValueError("agent container has an undeclared read-only destination")
        if self.public_test_assets_mounted_read_only != bool(self.read_only_destinations):
            raise ValueError("public-test mount evidence is inconsistent")
        return self


class ExternalProcessResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float = Field(ge=0.0)
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    output_limit_hit: bool
    oom_killed: bool
    process_group_cleaned: bool
    cleanup_complete: bool
    terminal_event_seen: bool
    failure_reason: str | None = None
    failure_kind: Literal["infrastructure"] | None = None
    failure_category: str | None = None
    failure_origin: (
        Literal[
            "host_control_plane",
            "agent_container",
            "broker",
            "external_provider",
        ]
        | None
    ) = None
    runtime_identity: ExternalProcessRuntimeIdentity
    security: ExternalProcessSecurityEvidence
    hwe_protocol_records: list[dict[str, object]] = Field(default_factory=list)
    hwe_private_audit_manifest: dict[str, object] | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_failure_taxonomy(self) -> ExternalProcessResult:
        if (self.failure_kind is None) != (self.failure_category is None):
            raise ValueError("external process failure kind and category must be paired")
        if self.failure_category is not None and self.failure_reason != self.failure_category:
            raise ValueError("external process failure category must match its stable reason")
        return self

    @model_validator(mode="after")
    def validate_result_consistency(self) -> ExternalProcessResult:
        if self.output_limit_hit != (self.stdout_truncated or self.stderr_truncated):
            raise ValueError("external process output-limit evidence is inconsistent")
        expected_cleanup = (
            self.security.container_removed
            and self.security.cleanup_verified
            and self.security.broker_stopped
            and self.process_group_cleaned
        )
        if self.cleanup_complete != expected_cleanup:
            raise ValueError("external process cleanup evidence is inconsistent")
        return self


class ExternalAgentCallIdentity(StrictModel):
    schema_version: str = SCHEMA_VERSION
    adapter_name: str
    adapter_version: str
    harness_name: str
    requested_model_id: str | None
    observed_model_id: str | None
    requested_reasoning_effort: str | None = Field(default=None, min_length=1, max_length=32)
    effective_reasoning_effort: str | None = Field(default=None, min_length=1, max_length=32)
    reasoning_effort_source: (
        Literal[
            "verigym_explicit_cli_override",
            "verigym_explicit_harness_override",
        ]
        | None
    ) = None
    inherited_reasoning_effort_allowed: bool | None = None
    executable_name: str
    executable_sha256: str
    executable_version: str
    capability_fingerprint: str
    configuration_fingerprint: str
    invocation_count: int = Field(ge=0)
    integration_track: (
        Literal[
            "codex_cli_readonly_single_turn_agent",
            "codex_cli_external_agent",
            "codex_cli_hwe_native_shell",
            "codex_cli_agenteval_scoring",
            "claude_cli_external_agent",
            "openhands_sdk_agent",
            "deepseek_harness_hwe_native_shell",
            "deepseek_harness_hwe_native_shell_v3",
        ]
        | None
    ) = None
    execution_surface: (
        Literal[
            "codex_cli",
            "claude_cli",
            "openhands_sdk",
            "deepseek_harness_sdk",
        ]
        | None
    ) = None
    interaction_class: (
        Literal[
            "cli_agent_single_turn_readonly",
            "cli_agent_workspace_writing",
            "cli_agent_mcp_repository_scoring",
            "sdk_agent_broker_tools",
        ]
        | None
    ) = None
    harness_id: str | None = Field(default=None, min_length=1, max_length=128)
    agent_version_hash: str | None = None
    prompt_contract_hash: str | None = None
    tool_policy_fingerprint: str | None = None
    model_client_kind: Literal["cli_agent_mediated", "sdk_agent_mediated"] | None = None
    agent_harness_kind: (
        Literal[
            "codex_cli",
            "claude_cli",
            "openhands_sdk",
            "deepseek_harness",
        ]
        | None
    ) = None
    tool_availability_policy: str | None = Field(default=None, min_length=1, max_length=128)
    tool_use_policy: str | None = Field(default=None, min_length=1, max_length=128)
    tool_event_count: int | None = Field(default=None, ge=0)
    side_effecting_tool_event_count: int | None = Field(default=None, ge=0)
    read_only_tool_event_count: int | None = Field(default=None, ge=0)
    external_network_tool_event_count: int | None = Field(default=None, ge=0)
    mcp_tool_event_count: int | None = Field(default=None, ge=0)
    workspace_write_count: int | None = Field(default=None, ge=0)
    chat_eval_compatible: bool | None = None
    pure_api_model_eval: bool | None = None
    direct_api_benchmark: bool | None = None
    auth_mode_label: str | None = None
    requested_auth_mode: str | None = Field(default=None, min_length=1, max_length=64)
    resolved_auth_mode: str | None = Field(default=None, min_length=1, max_length=64)
    auth_semantic_id: str | None = Field(default=None, min_length=1, max_length=128)
    auth_alias_used: bool | None = None
    sandbox_policy: str | None = None
    approval_policy: str | None = None
    identity_confidence: Literal["observed", "requested_only", "unknown"]
    reproducibility_scope: Literal[
        "site_specific_cli",
        "mutable_remote_observation",
        "unknown",
    ]

    @field_validator(
        "executable_sha256",
        "capability_fingerprint",
        "configuration_fingerprint",
        "agent_version_hash",
        "prompt_contract_hash",
        "tool_policy_fingerprint",
    )
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("external-agent identity hashes must be lowercase SHA-256 values")
        return value

    @model_validator(mode="after")
    def validate_authentication_identity(self) -> ExternalAgentCallIdentity:
        values = (
            self.requested_auth_mode,
            self.resolved_auth_mode,
            self.auth_semantic_id,
            self.auth_alias_used,
        )
        if any(value is not None for value in values) and any(value is None for value in values):
            raise ValueError(
                "external-agent authentication identity fields must be recorded together"
            )
        if (
            self.requested_auth_mode is not None
            and self.auth_mode_label is not None
            and self.requested_auth_mode != self.auth_mode_label
        ):
            raise ValueError("auth_mode_label must preserve the requested authentication mode")
        reasoning_values = (
            self.requested_reasoning_effort,
            self.effective_reasoning_effort,
            self.reasoning_effort_source,
            self.inherited_reasoning_effort_allowed,
        )
        if any(value is not None for value in reasoning_values) and any(
            value is None for value in reasoning_values
        ):
            raise ValueError(
                "external-agent reasoning-effort identity fields must be recorded together"
            )
        if (
            self.requested_reasoning_effort is not None
            and self.requested_reasoning_effort != self.effective_reasoning_effort
        ):
            raise ValueError("external-agent requested and effective reasoning effort must match")
        if self.inherited_reasoning_effort_allowed is True:
            raise ValueError("external-agent reasoning effort cannot permit inherited values")
        semantic_values = (
            self.execution_surface,
            self.interaction_class,
            self.harness_id,
            self.model_client_kind,
            self.agent_harness_kind,
            self.tool_availability_policy,
            self.tool_use_policy,
            self.tool_event_count,
            self.side_effecting_tool_event_count,
            self.read_only_tool_event_count,
            self.external_network_tool_event_count,
            self.mcp_tool_event_count,
            self.workspace_write_count,
            self.chat_eval_compatible,
            self.pure_api_model_eval,
            self.direct_api_benchmark,
        )
        if any(value is not None for value in semantic_values) and any(
            value is None for value in semantic_values
        ):
            raise ValueError("external-agent semantic identity fields must be recorded together")
        if self.execution_surface is not None:
            assert self.tool_event_count is not None
            assert self.side_effecting_tool_event_count is not None
            assert self.read_only_tool_event_count is not None
            assert self.external_network_tool_event_count is not None
            assert self.mcp_tool_event_count is not None
            if (
                self.side_effecting_tool_event_count
                + self.read_only_tool_event_count
                + self.external_network_tool_event_count
                + self.mcp_tool_event_count
                > self.tool_event_count
            ):
                raise ValueError("external-agent classified tool counts exceed total tool events")
            if (
                self.chat_eval_compatible is not False
                or self.pure_api_model_eval is not False
                or self.direct_api_benchmark is not False
            ):
                raise ValueError("CLI agent identities cannot claim direct or ChatEval status")
        return self


class ExternalAgentAccounting(StrictModel):
    schema_version: str = SCHEMA_VERSION
    process_wall_time_s: float = Field(ge=0.0)
    cli_event_count: int = Field(ge=0)
    model_call_count: int | None = Field(default=None, ge=0)
    external_tool_call_count: int | None = Field(default=None, ge=0)
    external_command_count: int | None = Field(default=None, ge=0)
    public_test_invocation_count: int | None = Field(default=None, ge=0)
    external_file_read_count: int | None = Field(default=None, ge=0)
    external_file_write_count: int | None = Field(default=None, ge=0)
    external_patch_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_complete: bool | None = None
    cost: float | None = Field(default=None, ge=0.0)
    currency: str | None = None

    @model_validator(mode="after")
    def validate_totals_and_cost(self) -> ExternalAgentAccounting:
        if (
            self.total_tokens is None
            and self.input_tokens is not None
            and self.output_tokens is not None
        ):
            self.total_tokens = self.input_tokens + self.output_tokens
        if self.currency is not None and self.cost is None:
            raise ValueError("external-agent currency requires a known cost")
        if self.usage_complete is False and any(
            value is not None
            for value in (self.input_tokens, self.output_tokens, self.total_tokens)
        ):
            raise ValueError("incomplete external-agent usage cannot contain token counts")
        if self.usage_complete is True and (
            self.input_tokens is None or self.output_tokens is None
        ):
            raise ValueError("complete external-agent usage requires input and output tokens")
        return self


__all__ = [
    "ExternalAgentAccounting",
    "ExternalAgentCallIdentity",
    "ExternalProcessIdentityPreview",
    "ExternalProcessInvocationSpec",
    "ExternalProcessPayloadBinding",
    "ExternalProcessRequest",
    "ExternalProcessResult",
    "ExternalProcessRuntimeIdentity",
    "ExternalProcessSecurityEvidence",
]
