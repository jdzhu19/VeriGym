"""Inspect local wheel/sdist contents against the documented package policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any

_FORBIDDEN_MEMBER_PARTS = {
    ".env",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "release_audit",
    "runs",
}
_FORBIDDEN_MEMBER_SUFFIXES = {".pyc", ".pyo", ".pid"}
_SECRET_PATTERNS = {
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_api_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
}
_TEXT_LIMIT = 8 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(name: str) -> list[str]:
    issues: list[str] = []
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        issues.append(f"unsafe archive path: {name}")
    if any(part in _FORBIDDEN_MEMBER_PARTS for part in path.parts):
        issues.append(f"forbidden generated/private member: {name}")
    if path.suffix in _FORBIDDEN_MEMBER_SUFFIXES:
        issues.append(f"forbidden cache/runtime suffix: {name}")
    if name.startswith(("tmp/", "home/", "data/")):
        issues.append(f"host-root-shaped member: {name}")
    if "dataset_spec-to-rtl" in name and "verilog_eval_v2_synthetic" not in name:
        issues.append(f"possible external benchmark content: {name}")
    return issues


def _scan_payload(name: str, payload: bytes) -> list[str]:
    if len(payload) > _TEXT_LIMIT or b"\0" in payload:
        return []
    return [
        f"{label} pattern in {name}"
        for label, pattern in _SECRET_PATTERNS.items()
        if pattern.search(payload)
    ]


def _wheel(path: Path) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    metadata_text: str | None = None
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)):
            issues.append("wheel has duplicate member names")
        for member in members:
            issues.extend(_safe_member(member.filename))
            unix_type = (member.external_attr >> 16) & 0o170000
            if unix_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                issues.append(f"wheel has unsupported member type: {member.filename}")
            if not member.is_dir():
                payload = archive.read(member)
                issues.extend(_scan_payload(member.filename, payload))
                if member.filename.endswith(".dist-info/METADATA"):
                    metadata_text = payload.decode("utf-8")
    if metadata_text is None:
        issues.append("wheel METADATA is missing")
        metadata: dict[str, Any] = {}
    else:
        parsed = Parser().parsestr(metadata_text)
        metadata = {
            "name": parsed.get("Name"),
            "version": parsed.get("Version"),
            "requires_python": parsed.get("Requires-Python"),
            "license_expression": parsed.get("License-Expression"),
            "project_urls": parsed.get_all("Project-URL", []),
            "requires_dist": parsed.get_all("Requires-Dist", []),
        }
        if metadata["name"] != "verigym" or metadata["version"] != "0.1.0":
            issues.append("wheel name/version metadata does not match the project")
        if metadata["license_expression"] != "Apache-2.0":
            issues.append("wheel does not contain the expected SPDX license expression")
        if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
            issues.append("wheel license file is missing")
        if not any(name.endswith(".dist-info/licenses/NOTICE") for name in names):
            issues.append("wheel notice file is missing")
    forbidden_external = [
        name
        for name in names
        if "verilog_eval_v2_synthetic" in name or "dataset_spec-to-rtl" in name
    ]
    if forbidden_external:
        issues.append("wheel contains benchmark-shaped test fixture content")
    required_wheel_suffixes = [
        "verigym/_build_provenance.json",
        "verigym/profiles/builtins/assets/NOTICE",
        "verigym/profiles/builtins/assets/toy_cells.lib",
        "verigym/suites/toy_rtl/assets/and_gate_basic/task.yaml",
    ]
    for suffix in required_wheel_suffixes:
        if not any(name.endswith(suffix) for name in names):
            issues.append(f"wheel is missing required first-party asset: {suffix}")
    return {
        "path": path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "member_count": len(names),
        "metadata": metadata,
    }, issues


def _sdist(path: Path) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            issues.append("sdist has duplicate member names")
        for member in members:
            issues.extend(_safe_member(member.name))
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                issues.append(f"sdist has unsupported member type: {member.name}")
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    issues.append(f"sdist file cannot be read: {member.name}")
                else:
                    issues.extend(_scan_payload(member.name, stream.read()))
    required_sdist_fragments = [
        "/.github/workflows/ci.yml",
        "/build_backend/verigym_build_backend.py",
        "/examples/plugins/conformance/pyproject.toml",
        "/scripts/run_release_audit.py",
        "/tests/fixtures/verilog_eval_v2_synthetic/LICENSE",
    ]
    for fragment in required_sdist_fragments:
        if not any(name.endswith(fragment) for name in names):
            issues.append(f"sdist is missing required source asset: {fragment.removeprefix('/')}")
    return {
        "path": path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "member_count": len(names),
        "contains_synthetic_fixture": any(
            "tests/fixtures/verilog_eval_v2_synthetic/" in name for name in names
        ),
        "contains_plugin_fixture": any("examples/plugins/conformance/" in name for name in names),
    }, issues


def inspect_distributions(wheel: Path, sdist: Path) -> dict[str, Any]:
    wheel_result, wheel_issues = _wheel(wheel)
    sdist_result, sdist_issues = _sdist(sdist)
    issues = sorted(set(wheel_issues + sdist_issues))
    return {
        "schema_version": "1.0",
        "status": "passed" if not issues else "failed",
        "wheel": wheel_result,
        "sdist": sdist_result,
        "issues": issues,
        "policy": {
            "external_verilog_eval": "user-supplied and absent from distributions",
            "synthetic_fixture": "first-party MIT test fixture; sdist only",
            "toy_liberty": "first-party Apache-2.0 educational non-signoff asset",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = inspect_distributions(arguments.wheel, arguments.sdist)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if arguments.output is None:
        print(rendered, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
