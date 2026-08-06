#!/usr/bin/env python3
"""Audit optional plugin archives without extracting or executing their contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath

_MAX_MEMBERS = 2_000
_MAX_MEMBER_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_FORBIDDEN_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "runs",
}
_FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".pid"}
_SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_token": re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "uri_credentials": re.compile(rb"://[^/@\s:]+:[^/@\s]+@"),
}


@dataclass(frozen=True)
class Policy:
    distribution: str
    version: str
    module: str
    entry_markers: tuple[str, ...]
    forbidden_member_names: frozenset[str] = frozenset()
    forbidden_member_suffixes: frozenset[str] = frozenset()


_POLICIES = {
    "rtllm": Policy(
        distribution="verigym-rtllm",
        version="0.2.0",
        module="verigym_rtllm",
        entry_markers=("[verigym.suites]", "rtllm = verigym_rtllm:RTLLMSuite"),
        forbidden_member_names=frozenset(
            {"design_description.txt", "makefile", "testbench.v", "verified_counter_12.v"}
        ),
    ),
    "synopsys": Policy(
        distribution="verigym-synopsys",
        version="0.1.0",
        module="verigym_synopsys",
        entry_markers=(
            "[console_scripts]",
            "verigym-synopsys-prepare-profile = verigym_synopsys.prepare:main",
            "[verigym.tools]",
            "synopsys-dc-synthesis = verigym_synopsys:DesignCompilerSynthesisTool",
            "synopsys-vcs-simulate = verigym_synopsys:VcsSimulationTool",
        ),
        forbidden_member_suffixes=frozenset(
            {".db", ".ddc", ".lib", ".ndm", ".nlib", ".sdc", ".tf", ".tluplus"}
        ),
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_name(raw: str, policy: Policy) -> tuple[str, list[str]]:
    issues: list[str] = []
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "\\" in raw:
        issues.append(f"unsafe archive member: {raw}")
    if any(part in _FORBIDDEN_PARTS for part in path.parts):
        issues.append(f"generated or private archive member: {raw}")
    if path.suffix.lower() in _FORBIDDEN_SUFFIXES:
        issues.append(f"cache or runtime archive member: {raw}")
    if path.name.lower() in policy.forbidden_member_names:
        issues.append(f"upstream benchmark member is not redistributable here: {raw}")
    if path.suffix.lower() in policy.forbidden_member_suffixes:
        issues.append(f"site or vendor artifact is not redistributable here: {raw}")
    return path.as_posix(), issues


def _scan_payload(name: str, payload: bytes) -> list[str]:
    return [
        f"{label} pattern in {name}"
        for label, pattern in _SECRET_PATTERNS.items()
        if pattern.search(payload)
    ]


def _scan_wheel(path: Path, policy: Policy) -> dict[str, object]:
    issues: list[str] = []
    names: list[str] = []
    total = 0
    metadata_text: str | None = None
    entries_text: str | None = None
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > _MAX_MEMBERS:
            raise ValueError("wheel member-count bound exceeded")
        for member in members:
            name, name_issues = _safe_name(member.filename, policy)
            names.append(name)
            issues.extend(name_issues)
            if member.is_dir():
                continue
            if member.file_size > _MAX_MEMBER_BYTES:
                raise ValueError(f"wheel member exceeds size bound: {name}")
            payload = archive.read(member)
            total += len(payload)
            if total > _MAX_TOTAL_BYTES:
                raise ValueError("wheel expanded-size bound exceeded")
            issues.extend(_scan_payload(name, payload))
            if name.endswith(".dist-info/METADATA"):
                if metadata_text is not None:
                    issues.append("wheel contains multiple METADATA files")
                metadata_text = payload.decode("utf-8", errors="replace")
            if name.endswith(".dist-info/entry_points.txt"):
                if entries_text is not None:
                    issues.append("wheel contains multiple entry_points.txt files")
                entries_text = payload.decode("utf-8", errors="replace")
    if len(names) != len(set(names)):
        issues.append("wheel contains duplicate member names")
    if any("/tests/" in f"/{name}" for name in names):
        issues.append("wheel contains tests")
    if not any(name.startswith(f"{policy.module}/") for name in names):
        issues.append(f"wheel does not contain the {policy.module} package")
    if metadata_text is None:
        issues.append("wheel METADATA is missing")
    else:
        metadata = Parser().parsestr(metadata_text)
        if metadata.get("Name") != policy.distribution:
            issues.append("wheel distribution name does not match its policy")
        if metadata.get("Version") != policy.version:
            issues.append(f"wheel version is not {policy.version}")
    if entries_text is None:
        issues.append("wheel entry_points.txt is missing")
    else:
        for marker in policy.entry_markers:
            if marker not in entries_text:
                issues.append(f"wheel entry points missing {marker!r}")
    return {
        "name": path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "member_count": len(names),
        "issues": sorted(set(issues)),
    }


def _scan_sdist(path: Path, policy: Policy) -> dict[str, object]:
    issues: list[str] = []
    names: list[str] = []
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > _MAX_MEMBERS:
            raise ValueError("sdist member-count bound exceeded")
        for member in members:
            name, name_issues = _safe_name(member.name, policy)
            names.append(name)
            issues.extend(name_issues)
            if member.isdir():
                continue
            if not member.isfile():
                issues.append(f"sdist contains a non-regular member: {name}")
                continue
            if member.size > _MAX_MEMBER_BYTES:
                raise ValueError(f"sdist member exceeds size bound: {name}")
            stream = archive.extractfile(member)
            if stream is None:
                issues.append(f"sdist member cannot be read: {name}")
                continue
            payload = stream.read(_MAX_MEMBER_BYTES + 1)
            if len(payload) != member.size:
                raise ValueError(f"sdist member size changed while reading: {name}")
            total += len(payload)
            if total > _MAX_TOTAL_BYTES:
                raise ValueError("sdist expanded-size bound exceeded")
            issues.extend(_scan_payload(name, payload))
    if len(names) != len(set(names)):
        issues.append("sdist contains duplicate member names")
    required_suffixes = (
        "/README.md",
        "/pyproject.toml",
        f"/src/{policy.module}/__init__.py",
    )
    for suffix in required_suffixes:
        if not any(name.endswith(suffix) for name in names):
            issues.append(f"sdist is missing required member {suffix.removeprefix('/')}")
    return {
        "name": path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "member_count": len(names),
        "issues": sorted(set(issues)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", choices=sorted(_POLICIES), required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    arguments = parser.parse_args()
    policy = _POLICIES[arguments.policy]
    try:
        wheel = _scan_wheel(arguments.wheel.resolve(strict=True), policy)
        sdist = _scan_sdist(arguments.sdist.resolve(strict=True), policy)
        issues = [*wheel["issues"], *sdist["issues"]]
        report = {
            "schema_version": "1.0",
            "status": "passed" if not issues else "failed",
            "policy": arguments.policy,
            "wheel": wheel,
            "sdist": sdist,
        }
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        report = {
            "schema_version": "1.0",
            "status": "failed",
            "policy": arguments.policy,
            "issues": [f"{type(exc).__name__}: {exc}"],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
