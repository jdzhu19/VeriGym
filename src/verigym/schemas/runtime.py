"""Runtime configuration, session, and workspace-diff schemas."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator

from verigym.schemas.base import StrictModel
from verigym.schemas.common import RuntimeDescriptor

_SECRET_ENV_PATTERN = re.compile(r"(?:TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DockerRuntimeConfig(StrictModel):
    """Fail-closed configuration for the optional Docker CLI runtime."""

    image: str
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

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        image = value.strip()
        if not image or image != value or "\x00" in image or any(ch.isspace() for ch in image):
            raise ValueError("Docker image must be a nonempty reference without whitespace")
        if "://" in image or "@" in image.partition("/")[0]:
            raise ValueError("Docker image references must not contain embedded credentials")
        return image

    @field_validator("run_as_user")
    @classmethod
    def validate_run_as_user(cls, value: str | None) -> str | None:
        if value is None:
            return None
        user = value.strip()
        if not user or user != value or "\x00" in user:
            raise ValueError("Docker user must be a nonempty user or uid[:gid]")
        principal = user.split(":", 1)[0].lower()
        if principal in {"0", "root"}:
            raise ValueError("DockerRuntime does not permit root execution")
        return user

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


__all__ = ["DockerRuntimeConfig", "RuntimeDescriptor", "SessionSpec", "WorkspaceDiff"]
