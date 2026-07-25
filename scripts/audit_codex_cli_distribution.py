#!/usr/bin/env python3
"""Audit verigym-codex-cli wheel and sdist contents without extracting them."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, NamedTuple

_MAX_MEMBERS = 2_000
_MAX_MEMBER_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_FORBIDDEN_PARTS = {".codex", "__pycache__", "auth.json", "credentials.json"}
_FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".pid"}
_CONTENT_PATTERNS = {
    "external_corpus": re.compile(rb"dataset_spec-to-rtl|RefModule|Mismatches:"),
    "host_path": re.compile(rb"/(?:home|data)/[^ \t\r\n\"']+"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_token": re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "uri_credentials": re.compile(rb"://[^/@\s:]+:[^/@\s]+@"),
}


class Member(NamedTuple):
    name: str
    size: int
    stream: BinaryIO


def _safe_name(raw: str) -> PurePosixPath:
    name = PurePosixPath(raw)
    if (
        not raw
        or name.is_absolute()
        or ".." in name.parts
        or "\\" in raw
        or any(part in _FORBIDDEN_PARTS for part in name.parts)
        or name.suffix in _FORBIDDEN_SUFFIXES
    ):
        raise ValueError(f"unsafe archive member: {raw}")
    return name


def _scan_members(members: list[Member]) -> tuple[list[str], list[str]]:
    if len(members) > _MAX_MEMBERS:
        raise ValueError("archive member-count bound exceeded")
    issues: list[str] = []
    names: list[str] = []
    seen: set[str] = set()
    total = 0
    for raw_name, declared_size, stream in members:
        name = _safe_name(raw_name).as_posix()
        if name in seen:
            raise ValueError(f"duplicate archive member: {name}")
        seen.add(name)
        names.append(name)
        if declared_size > _MAX_MEMBER_BYTES:
            raise ValueError(f"archive member exceeds size bound: {name}")
        payload = stream.read(_MAX_MEMBER_BYTES + 1)
        if len(payload) != declared_size or len(payload) > _MAX_MEMBER_BYTES:
            raise ValueError(f"archive member size changed or exceeded its bound: {name}")
        total += len(payload)
        if total > _MAX_TOTAL_BYTES:
            raise ValueError("archive expanded-size bound exceeded")
        for label, pattern in _CONTENT_PATTERNS.items():
            if pattern.search(payload):
                issues.append(f"{label} pattern in {name}")
    return names, sorted(issues)


def _scan_wheel(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        members = [
            Member(info.filename, info.file_size, archive.open(info))
            for info in archive.infolist()
            if not info.is_dir()
        ]
        names, issues = _scan_members(members)
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        entry_names = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(metadata_names) != 1 or len(entry_names) != 1:
            issues.append("wheel must contain one METADATA and one entry_points.txt")
        else:
            metadata = archive.read(metadata_names[0]).decode("utf-8", errors="replace")
            entries = archive.read(entry_names[0]).decode("utf-8", errors="replace")
            for expected in (
                "Name: verigym-codex-cli",
                "Version: 0.1.0",
                "Requires-Dist: verigym==0.1.0",
            ):
                if expected not in metadata:
                    issues.append(f"wheel metadata missing {expected!r}")
            for expected in (
                "[verigym.models]",
                "codex-cli-exec-model",
                "[verigym.agents]",
                "codex-cli-agent",
                "[console_scripts]",
                "verigym-codex",
            ):
                if expected not in entries:
                    issues.append(f"wheel entry points missing {expected!r}")
        if any("/tests/" in f"/{name}" for name in names):
            issues.append("wheel contains test files")
    return _archive_result(path, names, issues)


def _scan_sdist(path: Path) -> dict[str, object]:
    with tarfile.open(path, "r:gz") as archive:
        members: list[Member] = []
        issues: list[str] = []
        for info in archive.getmembers():
            if info.isdir():
                continue
            if not info.isfile():
                issues.append(f"sdist contains non-regular member: {info.name}")
                continue
            stream = archive.extractfile(info)
            if stream is None:
                issues.append(f"sdist member could not be read: {info.name}")
                continue
            members.append(Member(info.name, info.size, stream))
        names, content_issues = _scan_members(members)
        issues.extend(content_issues)
        if any("/tests/" in f"/{name}" for name in names):
            issues.append("sdist contains test files")
    return _archive_result(path, names, sorted(issues))


def _archive_result(path: Path, names: list[str], issues: list[str]) -> dict[str, object]:
    return {
        "name": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "member_count": len(names),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        wheel = _scan_wheel(arguments.wheel.resolve(strict=True))
        sdist = _scan_sdist(arguments.sdist.resolve(strict=True))
        issues = [*wheel["issues"], *sdist["issues"]]
        report = {
            "schema_version": "1.0",
            "status": "passed" if not issues else "failed",
            "wheel": wheel,
            "sdist": sdist,
        }
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        report = {
            "schema_version": "1.0",
            "status": "failed",
            "issues": [f"{type(exc).__name__}: {exc}"],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
