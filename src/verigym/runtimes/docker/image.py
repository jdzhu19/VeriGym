"""Immutable Docker image and backend provenance resolution."""

from __future__ import annotations

import re
from typing import Any

from verigym.runtimes.docker.engine import DockerEngine
from verigym.runtimes.docker.errors import DockerCapabilityError, DockerImageError
from verigym.schemas.common import RuntimeBackendInfo, RuntimeImageIdentity
from verigym.schemas.runtime import DockerRuntimeConfig

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_BASELINE_IMAGE_ENV = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}


def inspect_backend(engine: DockerEngine) -> tuple[RuntimeBackendInfo, dict[str, Any]]:
    """Read bounded client/server information and mandatory limit capabilities."""

    version = engine.version()
    info = engine.info()
    raw_client = version.get("Client")
    raw_server = version.get("Server")
    client: dict[str, Any] = raw_client if isinstance(raw_client, dict) else {}
    server: dict[str, Any] = raw_server if isinstance(raw_server, dict) else {}
    security_options = info.get("SecurityOptions")
    rootless = None
    if isinstance(security_options, list):
        rootless = any("rootless" in str(option).lower() for option in security_options)
    backend = RuntimeBackendInfo(
        backend_type=engine.backend_type,
        client_version=_optional_string(client.get("Version")),
        server_version=_optional_string(server.get("Version")),
        api_version=_optional_string(server.get("ApiVersion")),
        server_os=_optional_string(server.get("Os") or info.get("OSType")),
        server_architecture=_optional_string(server.get("Arch") or info.get("Architecture")),
        rootless=rootless,
        memory_limit_supported=_optional_bool(info.get("MemoryLimit")),
        swap_limit_supported=_optional_bool(info.get("SwapLimit")),
        cpu_limit_supported=_cpu_limits_supported(info),
        pids_limit_supported=_optional_bool(info.get("PidsLimit")),
    )
    if not backend.server_version:
        raise DockerCapabilityError(
            "Docker daemon/server information is unavailable",
            subreason="daemon_unavailable",
        )
    missing = [
        name
        for name, supported in (
            ("memory", backend.memory_limit_supported),
            ("swap", backend.swap_limit_supported),
            ("CPU", backend.cpu_limit_supported),
            ("PID", backend.pids_limit_supported),
        )
        if supported is not True
    ]
    if missing:
        raise DockerCapabilityError(
            f"Docker daemon cannot verify mandatory controls: {', '.join(missing)}",
            subreason="mandatory_control_unavailable",
            details={"controls": missing},
        )
    return backend, info


def resolve_image(
    engine: DockerEngine,
    config: DockerRuntimeConfig,
    *,
    expected_image_id: str | None = None,
) -> RuntimeImageIdentity:
    """Resolve a tag once and return only identity reported by Docker Engine."""

    payload = engine.inspect_image(config.image)
    if payload is None and config.pull_policy == "if_missing":
        engine.pull_image(config.image)
        payload = engine.inspect_image(config.image)
    if payload is None:
        raise DockerImageError(
            f"Docker image is unavailable locally: {config.image}",
            subreason="image_missing",
        )
    image_id = payload.get("Id")
    if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
        raise DockerImageError(
            "Docker image has no valid immutable sha256 image ID",
            subreason="invalid_image_id",
        )
    if expected_image_id is not None and image_id != expected_image_id:
        raise DockerImageError(
            "resolved Docker image does not match the exact replay image ID",
            subreason="replay_image_mismatch",
            details={"expected_image_id": expected_image_id, "resolved_image_id": image_id},
        )
    os_name = payload.get("Os")
    architecture = payload.get("Architecture")
    if (
        not isinstance(os_name, str)
        or not os_name
        or not isinstance(architecture, str)
        or not architecture
    ):
        raise DockerImageError(
            "Docker image platform metadata is incomplete",
            subreason="invalid_image_metadata",
        )
    raw_image_config = payload.get("Config")
    image_config: dict[str, Any] = raw_image_config if isinstance(raw_image_config, dict) else {}
    image_environment = image_config.get("Env")
    image_environment_names = (
        {str(value).split("=", 1)[0] for value in image_environment}
        if isinstance(image_environment, list)
        else set()
    )
    forbidden_environment = sorted(image_environment_names - _BASELINE_IMAGE_ENV)
    if forbidden_environment:
        raise DockerImageError(
            "Docker image declares environment variables outside the runtime allowlist: "
            + ", ".join(forbidden_environment),
            subreason="image_environment_forbidden",
        )
    configured_user = _optional_string(image_config.get("User"))
    effective_user = config.run_as_user or configured_user
    if effective_user is None or _is_root_user(effective_user):
        raise DockerImageError(
            "Docker image has no verifiable non-root user; configure a non-root --docker-user",
            subreason="root_image_user",
        )
    digests = payload.get("RepoDigests")
    repository_digests = (
        sorted(value for value in digests if isinstance(value, str) and value)
        if isinstance(digests, list)
        else None
    )
    if repository_digests == []:
        repository_digests = None
    return RuntimeImageIdentity(
        requested_reference=config.image,
        resolved_image_id=image_id,
        repository_digests=repository_digests,
        created_at=_optional_string(payload.get("Created")),
        os=os_name,
        architecture=architecture,
        configured_image_user=configured_user,
        effective_user=effective_user,
    )


def _is_root_user(value: str) -> bool:
    return value.split(":", 1)[0].strip().lower() in {"", "0", "root"}


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _cpu_limits_supported(info: dict[str, Any]) -> bool | None:
    values = [info.get("CpuCfsPeriod"), info.get("CpuCfsQuota")]
    if all(isinstance(value, bool) for value in values):
        return all(values)
    return None


__all__ = ["inspect_backend", "resolve_image"]
