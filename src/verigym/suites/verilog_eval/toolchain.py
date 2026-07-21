"""Offline Icarus version detection and upstream compatibility labeling."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from verigym.suites.verilog_eval.schemas import IcarusCompatibility


@dataclass(frozen=True)
class IcarusVersionInfo:
    executable: str | None
    version: str | None
    compatibility: IcarusCompatibility


def detect_icarus(executable_name: str) -> IcarusVersionInfo:
    executable = shutil.which(executable_name)
    if executable is None:
        return IcarusVersionInfo(
            executable=None,
            version=None,
            compatibility=IcarusCompatibility.UNVERIFIED,
        )
    try:
        completed = subprocess.run(
            [executable, "-V"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return IcarusVersionInfo(
            executable=executable,
            version=None,
            compatibility=IcarusCompatibility.UNVERIFIED,
        )
    lines = [
        line.strip()
        for line in (completed.stdout + "\n" + completed.stderr).splitlines()
        if line.strip()
    ]
    version = lines[0] if lines else None
    return IcarusVersionInfo(
        executable=executable,
        version=version,
        compatibility=classify_icarus_version(version),
    )


def classify_icarus_version(version: str | None) -> IcarusCompatibility:
    if version is None:
        return IcarusCompatibility.UNVERIFIED
    match = re.search(r"\bversion\s+(\d+)(?:\.|\b)", version, flags=re.IGNORECASE)
    if match is None:
        return IcarusCompatibility.UNVERIFIED
    major = int(match.group(1))
    if major == 12:
        return IcarusCompatibility.REFERENCE_COMPATIBLE
    if major == 13:
        return IcarusCompatibility.INCOMPATIBLE
    return IcarusCompatibility.UNVERIFIED


__all__ = ["IcarusVersionInfo", "classify_icarus_version", "detect_icarus"]
