"""Credential-free local Yosys and ABC identity probes."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from verigym.core.hashing import hash_bytes
from verigym.profiles.base import ResolvedToolIdentity
from verigym.schemas.tool import HealthCheckResult

_YOSYS_VERSION = re.compile(r"\bYosys\s+([0-9]+(?:\.[0-9]+)+(?:\+[0-9]+)?)\b")
_GIT_HASH = re.compile(r"\bgit sha1\s+([0-9a-fA-F]+)\b")
_ABC_VERSION = re.compile(r"\bABC\s+([0-9]+(?:\.[0-9]+)+)\b")
_OPENSTA_VERSION = re.compile(r"^([0-9]+(?:\.[0-9]+){1,2})$", re.MULTILINE)


def extract_yosys_version(output: str) -> str | None:
    match = _YOSYS_VERSION.search(output)
    return match.group(1) if match else None


def extract_yosys_git_hash(output: str) -> str | None:
    match = _GIT_HASH.search(output)
    return match.group(1).lower() if match else None


def extract_abc_version(output: str) -> str | None:
    match = _ABC_VERSION.search(output)
    return match.group(1) if match else None


def extract_opensta_version(output: str) -> str | None:
    match = _OPENSTA_VERSION.search(output.strip())
    return match.group(1) if match else None


def local_yosys_health() -> HealthCheckResult:
    executable = shutil.which("yosys")
    if executable is None:
        return HealthCheckResult(
            healthy=False,
            message="yosys was not found on PATH",
            executable=None,
        )
    try:
        completed = subprocess.run(
            [executable, "-V"],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return HealthCheckResult(
            healthy=False,
            message=f"yosys identity probe failed: {exc}",
            executable=executable,
        )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    version = extract_yosys_version(output)
    return HealthCheckResult(
        healthy=completed.returncode == 0 and version is not None,
        message="available" if version is not None else "yosys returned no supported version",
        version=output or None,
        executable=executable,
    )


def local_abc_health() -> HealthCheckResult:
    yosys = shutil.which("yosys")
    executable = shutil.which("yosys-abc")
    if executable is None and yosys is not None:
        sibling = Path(yosys).resolve().parent / "yosys-abc"
        executable = str(sibling) if sibling.is_file() else None
    if executable is None:
        return HealthCheckResult(
            healthy=False,
            message="yosys-abc was not found on PATH or beside yosys",
        )
    try:
        completed = subprocess.run(
            [executable, "-c", "version; quit"],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return HealthCheckResult(
            healthy=False,
            message=f"ABC identity probe failed: {exc}",
            executable=executable,
        )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    version = extract_abc_version(output)
    return HealthCheckResult(
        healthy=completed.returncode == 0 and version is not None,
        message="available" if version is not None else "ABC returned no supported version",
        version=output or None,
        executable=executable,
    )


def resolve_local_tool_identities(
    *, opensta_executable: str | None = None
) -> list[ResolvedToolIdentity]:
    yosys = shutil.which("yosys")
    if yosys is None:
        raise FileNotFoundError("yosys was not found on PATH")
    yosys_completed = subprocess.run(
        [yosys, "-V"],
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=10,
    )
    yosys_output = (yosys_completed.stdout + "\n" + yosys_completed.stderr).strip()
    yosys_version = extract_yosys_version(yosys_output)
    if yosys_completed.returncode != 0 or yosys_version is None:
        raise RuntimeError("yosys returned no supported version identity")
    abc = shutil.which("yosys-abc")
    if abc is None:
        sibling = Path(yosys).resolve().parent / "yosys-abc"
        abc = str(sibling) if sibling.is_file() else None
    if abc is None:
        raise FileNotFoundError("yosys-abc was not found on PATH or beside yosys")
    abc_completed = subprocess.run(
        [abc, "-c", "version; quit"],
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=10,
    )
    abc_output = (abc_completed.stdout + "\n" + abc_completed.stderr).strip()
    abc_version = extract_abc_version(abc_output)
    if abc_completed.returncode != 0 or abc_version is None:
        raise RuntimeError("yosys-abc returned no supported version identity")
    identities = [
        ResolvedToolIdentity(
            logical_name="yosys",
            executable="yosys",
            version=yosys_version,
            version_output=yosys_output,
            git_hash=extract_yosys_git_hash(yosys_output),
            executable_sha256=hash_bytes(Path(yosys).resolve().read_bytes()),
            capabilities=["synth", "stat_json", "liberty", "abc"],
            identity_kind="local_executable",
        ),
        ResolvedToolIdentity(
            logical_name="yosys-abc",
            executable="yosys-abc",
            version=abc_version,
            version_output=abc_output,
            executable_sha256=hash_bytes(Path(abc).resolve().read_bytes()),
            capabilities=["liberty_mapping"],
            identity_kind="local_executable",
        ),
    ]
    if opensta_executable is not None:
        executable_path = (
            Path(opensta_executable)
            if Path(opensta_executable).is_absolute()
            else Path(shutil.which(opensta_executable) or opensta_executable)
        )
        if not executable_path.is_file():
            raise FileNotFoundError("OpenSTA was not found at the profile executable")
        resolved_opensta = executable_path.resolve(strict=True)
        opensta_completed = subprocess.run(
            [str(resolved_opensta), "-version"],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=10,
        )
        opensta_output = (opensta_completed.stdout + "\n" + opensta_completed.stderr).strip()
        opensta_version = extract_opensta_version(opensta_output)
        if opensta_completed.returncode != 0 or opensta_version is None:
            raise RuntimeError("OpenSTA returned no supported version identity")
        identities.append(
            ResolvedToolIdentity(
                logical_name="opensta",
                executable=str(resolved_opensta),
                version=opensta_version,
                version_output=opensta_output,
                executable_sha256=hash_bytes(resolved_opensta.read_bytes()),
                capabilities=["static_timing", "power_estimation", "wire_load_model"],
                identity_kind="local_executable",
            )
        )
    return identities


__all__ = [
    "extract_abc_version",
    "extract_opensta_version",
    "extract_yosys_git_hash",
    "extract_yosys_version",
    "local_abc_health",
    "local_yosys_health",
    "resolve_local_tool_identities",
]
