"""Mandatory Docker resource argument and effective-limit planning."""

from __future__ import annotations

from verigym.schemas.common import RuntimeResourceSummary
from verigym.schemas.runtime import DockerRuntimeConfig


def resource_arguments(config: DockerRuntimeConfig) -> list[str]:
    """Render non-disableable resource controls for ``docker create``."""

    return [
        "--memory",
        str(config.memory_bytes),
        "--memory-swap",
        str(config.memory_bytes),
        "--cpus",
        format(config.cpus, ".12g"),
        "--pids-limit",
        str(config.pids_limit),
    ]


def resource_summary(
    config: DockerRuntimeConfig,
    *,
    max_output_bytes: int | None = None,
) -> RuntimeResourceSummary:
    return RuntimeResourceSummary(
        memory_bytes=config.memory_bytes,
        memory_swap_bytes=config.memory_bytes,
        swap_enforced=True,
        cpus=config.cpus,
        pids_limit=config.pids_limit,
        tmpfs_bytes=config.tmpfs_bytes,
        stop_timeout_s=config.stop_timeout_s,
        max_command_time_s=config.max_command_time_s,
        max_output_bytes=max_output_bytes,
        max_artifact_file_bytes=config.max_artifact_file_bytes,
        max_artifact_bytes=config.max_artifact_bytes,
    )


def effective_timeout(command_timeout_s: int, site_ceiling_s: int) -> int:
    """A task may tighten but never raise the site-level command ceiling."""

    return min(command_timeout_s, site_ceiling_s)


__all__ = ["effective_timeout", "resource_arguments", "resource_summary"]
