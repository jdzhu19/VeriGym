"""Docker environment construction and effective-control verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from verigym.runtimes.docker.errors import DockerCapabilityError
from verigym.runtimes.docker.mounts import MountSpec
from verigym.schemas.runtime import DockerRuntimeConfig

BASELINE_ENVIRONMENT = {
    "PATH": (
        "/opt/yosys/bin:/opt/iverilog/bin:/usr/local/sbin:/usr/local/bin:"
        "/usr/sbin:/usr/bin:/sbin:/bin"
    ),
    "HOME": "/workspace/.verigym_internal",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TMPDIR": "/tmp",
}


def build_environment(
    config: DockerRuntimeConfig,
    session_environment: Mapping[str, str],
    command_environment: Mapping[str, str],
) -> dict[str, str]:
    """Construct a fixed baseline plus only explicitly allowlisted values."""

    allowed = set(config.environment_allowlist)
    supplied = {**session_environment, **command_environment}
    forbidden = sorted(set(supplied) - allowed)
    if forbidden:
        raise DockerCapabilityError(
            f"container environment variable is not allowlisted: {', '.join(forbidden)}",
            subreason="environment_not_allowlisted",
        )
    environment = dict(BASELINE_ENVIRONMENT)
    for name in sorted(allowed):
        if name in supplied:
            value = supplied[name]
            if "\x00" in value:
                raise DockerCapabilityError(
                    "container environment values cannot contain NUL bytes",
                    subreason="invalid_environment",
                )
            environment[name] = value
    return environment


def security_arguments(
    config: DockerRuntimeConfig,
    *,
    user: str,
    cwd: str,
    environment: Mapping[str, str],
    labels: Mapping[str, str],
) -> list[str]:
    arguments = [
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={config.tmpfs_bytes},mode=1777",
        "--user",
        user,
        "--stop-timeout",
        str(config.stop_timeout_s),
        "--workdir",
        cwd,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--init",
    ]
    for name in sorted(environment):
        arguments.extend(["--env", f"{name}={environment[name]}"])
    for name in sorted(labels):
        arguments.extend(["--label", f"{name}={labels[name]}"])
    return arguments


def verify_effective_container(
    payload: dict[str, Any],
    *,
    config: DockerRuntimeConfig,
    expected_user: str,
    expected_mounts: list[MountSpec],
    expected_environment: Mapping[str, str],
    expected_labels: Mapping[str, str],
) -> None:
    """Fail closed unless Docker reports every mandatory requested control."""

    host = _mapping(payload.get("HostConfig"))
    container_config = _mapping(payload.get("Config"))
    failures: list[str] = []
    if host.get("NetworkMode") != "none":
        failures.append("network=none")
    if host.get("ReadonlyRootfs") is not True:
        failures.append("read-only root filesystem")
    if host.get("Privileged") is not False:
        failures.append("unprivileged mode")
    cap_drop = host.get("CapDrop")
    if not isinstance(cap_drop, list) or "ALL" not in {str(value).upper() for value in cap_drop}:
        failures.append("capabilities dropped")
    security_opt = host.get("SecurityOpt")
    if not isinstance(security_opt, list) or not any(
        str(value).startswith("no-new-privileges") for value in security_opt
    ):
        failures.append("no-new-privileges")
    if host.get("Init") is not True:
        failures.append("init/reaping")
    if host.get("PidMode") == "host":
        failures.append("private PID namespace")
    if host.get("IpcMode") == "host":
        failures.append("private IPC namespace")
    if host.get("UsernsMode") == "host":
        failures.append("private user namespace policy")
    if host.get("CapAdd") not in (None, (), []):
        failures.append("no added capabilities")
    if host.get("Devices") not in (None, (), []):
        failures.append("no host devices")
    if host.get("Binds") not in (None, (), []):
        failures.append("no undeclared bind mounts")
    if host.get("Memory") != config.memory_bytes:
        failures.append("memory limit")
    if host.get("MemorySwap") != config.memory_bytes:
        failures.append("swap limit")
    expected_nano_cpus = round(config.cpus * 1_000_000_000)
    if host.get("NanoCpus") != expected_nano_cpus:
        failures.append("CPU limit")
    if host.get("PidsLimit") != config.pids_limit:
        failures.append("PID limit")
    if container_config.get("StopTimeout") != config.stop_timeout_s:
        failures.append("stop timeout")
    tmpfs = host.get("Tmpfs")
    tmpfs_value = tmpfs.get("/tmp") if isinstance(tmpfs, dict) else None
    required_tmpfs_options = {
        "noexec",
        "nosuid",
        "nodev",
        f"size={config.tmpfs_bytes}",
        "mode=1777",
    }
    if not isinstance(tmpfs_value, str) or not required_tmpfs_options.issubset(
        set(tmpfs_value.split(","))
    ):
        failures.append("bounded /tmp tmpfs")
    if container_config.get("User") != expected_user:
        failures.append("configured non-root user")
    actual_labels = container_config.get("Labels")
    if not isinstance(actual_labels, dict) or any(
        actual_labels.get(name) != value for name, value in expected_labels.items()
    ):
        failures.append("ownership labels")
    actual_env = container_config.get("Env")
    actual_environment: dict[str, str] = {}
    if isinstance(actual_env, list):
        for value in actual_env:
            name, separator, content = str(value).partition("=")
            if separator:
                actual_environment[name] = content
    if (
        not isinstance(actual_env, list)
        or len(actual_env) != len(expected_environment)
        or actual_environment != dict(expected_environment)
    ):
        failures.append("environment allowlist")
    _verify_mounts(host, expected_mounts, failures)
    if failures:
        raise DockerCapabilityError(
            f"Docker effective configuration weakened mandatory controls: {', '.join(failures)}",
            subreason="mandatory_control_mismatch",
            details={"controls": failures},
        )


def _verify_mounts(
    host: dict[str, Any], expected_mounts: list[MountSpec], failures: list[str]
) -> None:
    raw_mounts = host.get("Mounts")
    if not isinstance(raw_mounts, list) or len(raw_mounts) != len(expected_mounts):
        failures.append("declared mount set")
        return
    expected = {
        mount.destination: (str(mount.source), mount.read_only) for mount in expected_mounts
    }
    actual: dict[str, tuple[str, bool]] = {}
    for value in raw_mounts:
        if not isinstance(value, dict):
            failures.append("declared mount set")
            return
        target = value.get("Target")
        source = value.get("Source")
        read_only = value.get("ReadOnly", False)
        if isinstance(target, str) and isinstance(source, str) and isinstance(read_only, bool):
            actual[target] = (source, read_only)
    if actual != expected:
        failures.append("declared mount set")
    if any(destination in {"/var/run/docker.sock", "/run/docker.sock"} for destination in actual):
        failures.append("Docker socket exclusion")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


__all__ = [
    "BASELINE_ENVIRONMENT",
    "build_environment",
    "security_arguments",
    "verify_effective_container",
]
