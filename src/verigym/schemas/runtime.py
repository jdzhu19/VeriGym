"""Runtime configuration, session, and workspace-diff schemas."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import StrictModel
from verigym.schemas.common import RuntimeDescriptor

_SECRET_ENV_PATTERN = re.compile(r"(?:TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DockerExternalAgentRuntimeConfig(StrictModel):
    """Immutable image and non-disableable limits for one external-agent episode."""

    image: str
    expected_image_id: str
    expected_executable_name: str = Field(pattern=r"^[A-Za-z0-9._+-]{1,128}$")
    expected_executable_path: str
    expected_executable_version: str = Field(min_length=1, max_length=128)
    expected_executable_sha256: str
    process_argv: list[str] = Field(min_length=1, max_length=64)
    protocol: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    required_image_labels: dict[str, str] = Field(min_length=1, max_length=64)
    pull_policy: Literal["never", "if_missing"] = "never"
    run_as_user: str
    read_only_rootfs: Literal[True] = True
    network_mode: Literal["none"] = "none"
    memory_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=64 * 1024 * 1024,
        le=4 * 1024**3,
    )
    cpus: float = Field(default=1.0, gt=0.0, le=16.0)
    pids_limit: int = Field(default=128, ge=16, le=1024)
    tmpfs_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1024 * 1024,
        le=512 * 1024**2,
    )
    stop_timeout_s: int = Field(default=3, ge=1, le=30)
    max_process_time_s: int = Field(default=300, ge=1, le=1800)
    max_output_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=1024,
        le=16 * 1024 * 1024,
    )
    inner_sandbox_mode: Literal["outer_runtime_delegated"] = "outer_runtime_delegated"
    logical_workspace_root: Literal["/workspace"] = "/workspace"

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        return _validate_image_reference(value)

    @field_validator("run_as_user")
    @classmethod
    def validate_run_as_user(cls, value: str) -> str:
        validated = _validate_non_root_user(value)
        assert validated is not None
        return validated

    @field_validator("expected_image_id")
    @classmethod
    def validate_expected_image_id(cls, value: str) -> str:
        if not _IMAGE_ID_PATTERN.fullmatch(value):
            raise ValueError("external-agent expected image ID must be sha256:<64 lowercase hex>")
        return value

    @field_validator("expected_executable_sha256")
    @classmethod
    def validate_executable_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("external-agent executable hash must be lowercase SHA-256")
        return value

    @field_validator("expected_executable_path")
    @classmethod
    def validate_executable_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value == "/"
            or "\x00" in value
            or any(part in {"", ".", ".."} for part in value.split("/")[1:])
        ):
            raise ValueError("external-agent executable path must be canonical and absolute")
        return value

    @field_validator("process_argv")
    @classmethod
    def validate_process_argv(cls, values: list[str]) -> list[str]:
        if any(
            not value or "\x00" in value or "\r" in value or "\n" in value or len(value) > 4096
            for value in values
        ):
            raise ValueError("external-agent process argv contains an invalid argument")
        return values

    @field_validator("required_image_labels")
    @classmethod
    def validate_required_image_labels(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 64:
            raise ValueError("external-agent image label requirements exceed the bound")
        for key, value in values.items():
            if (
                not key
                or len(key) > 256
                or not value
                or len(value) > 1024
                or "\x00" in key
                or "\x00" in value
            ):
                raise ValueError("external-agent image label requirement is invalid")
        return dict(sorted(values.items()))

    @model_validator(mode="after")
    def bind_executable_identity(self) -> DockerExternalAgentRuntimeConfig:
        if self.expected_executable_path.rsplit("/", 1)[-1] != self.expected_executable_name:
            raise ValueError("external-agent executable path and name disagree")
        if self.process_argv[0] != self.expected_executable_path:
            raise ValueError("external-agent argv does not start with the expected executable path")
        return self


class DockerRuntimeConfig(StrictModel):
    """Fail-closed configuration for the optional Docker CLI runtime."""

    image: str
    expected_image_id: str | None = None
    pull_policy: Literal["never", "if_missing"] = "never"
    network_mode: Literal["none"] = "none"
    run_as_user: str | None = None
    read_only_rootfs: Literal[True] = True
    memory_bytes: int = Field(default=512 * 1024 * 1024, ge=64 * 1024 * 1024, le=16 * 1024**3)
    cpus: float = Field(default=1.0, gt=0.0, le=64.0)
    pids_limit: int = Field(default=128, ge=16, le=4096)
    tmpfs_bytes: int = Field(default=64 * 1024 * 1024, ge=1024 * 1024, le=1024**3)
    stop_timeout_s: int = Field(default=3, ge=1, le=30)
    max_command_time_s: int = Field(default=60, ge=1, le=3600)
    max_artifact_file_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1,
        le=1024**3,
    )
    max_artifact_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        le=4 * 1024**3,
    )
    environment_allowlist: list[str] = Field(default_factory=list)
    external_agent: DockerExternalAgentRuntimeConfig | None = None

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        return _validate_image_reference(value)

    @field_validator("run_as_user")
    @classmethod
    def validate_run_as_user(cls, value: str | None) -> str | None:
        return _validate_non_root_user(value)

    @field_validator("expected_image_id")
    @classmethod
    def validate_expected_image_id(cls, value: str | None) -> str | None:
        if value is not None and not _IMAGE_ID_PATTERN.fullmatch(value):
            raise ValueError("Docker expected image ID must be sha256:<64 lowercase hex>")
        return value

    @field_validator("environment_allowlist")
    @classmethod
    def validate_environment_allowlist(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Docker environment allowlist contains duplicate names")
        for name in value:
            if not _ENV_NAME_PATTERN.fullmatch(name):
                raise ValueError(f"invalid Docker environment variable name: {name!r}")
            if _SECRET_ENV_PATTERN.search(name):
                raise ValueError(
                    f"secret-like environment variable is forbidden in RTL containers: {name}"
                )
        return sorted(value)

    @model_validator(mode="after")
    def enforce_role_separation(self) -> DockerRuntimeConfig:
        if self.external_agent is not None and self.external_agent.image == self.image:
            raise ValueError(
                "external-agent and verifier roles require separately identified images"
            )
        return self


class SessionSpec(StrictModel):
    source_dir: str
    label: str
    max_output_bytes: int = Field(default=1_000_000, ge=1)
    environment: dict[str, str] = Field(default_factory=dict)


class WorkspaceDiff(StrictModel):
    patch: str = ""
    changed_files: list[str] = Field(default_factory=list)
    added_lines: int = 0
    deleted_lines: int = 0
    changes_outside_expected_files: list[str] = Field(default_factory=list)


def _validate_image_reference(value: str) -> str:
    image = value.strip()
    if not image or image != value or "\x00" in image or any(ch.isspace() for ch in image):
        raise ValueError("Docker image must be a nonempty reference without whitespace")
    if "://" in image or "@" in image.partition("/")[0]:
        raise ValueError("Docker image references must not contain embedded credentials")
    return image


def _validate_non_root_user(value: str | None) -> str | None:
    if value is None:
        return None
    user = value.strip()
    if not user or user != value or "\x00" in user:
        raise ValueError("Docker user must be a nonempty user or uid[:gid]")
    principal = user.split(":", 1)[0].lower()
    if principal in {"0", "root"}:
        raise ValueError("DockerRuntime does not permit root execution")
    return user


__all__ = [
    "DockerExternalAgentRuntimeConfig",
    "DockerRuntimeConfig",
    "RuntimeDescriptor",
    "SessionSpec",
    "WorkspaceDiff",
]
