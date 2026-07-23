"""Small validator and gate evaluator for local MVP release-audit bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

from verigym.core.loaders import load_model
from verigym.schemas.audit import AuditManifest, EvidenceEntry
from verigym.schemas.provenance import BuildProvenance

_REQUIRED_BUNDLE_FILES = {
    "audit_manifest.json",
    "artifact_inventory.json",
    "compliance.json",
    "distribution_inventory.json",
    "environment.json",
    "evidence.json",
    "hashes.sha256",
    "reproducible_build.json",
    "schema_inventory.json",
    "security_summary.json",
    "test_summary.json",
    "reports/MVP_AUDIT_REPORT.md",
    "reports/MVP_COMPLIANCE.md",
    "reports/RELEASE_CHECKLIST.md",
}
_MAX_FILES = 20_000
_MAX_FILE_BYTES = 256 * 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_SECRET_PATTERNS = (
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evaluate_gate(
    evidence: list[EvidenceEntry],
    provenance: BuildProvenance,
    required_check_ids: list[str],
) -> tuple[str, list[str]]:
    """Return an honest gate result; missing/non-passed requirements always fail."""

    reasons: list[str] = []
    by_id: dict[str, EvidenceEntry] = {}
    for entry in evidence:
        if entry.check_id in by_id:
            reasons.append(f"duplicate evidence ID: {entry.check_id}")
        else:
            by_id[entry.check_id] = entry
    for check_id in required_check_ids:
        required_entry = by_id.get(check_id)
        if required_entry is None:
            reasons.append(f"required check has no evidence: {check_id}")
        elif required_entry.classification != "passed":
            reasons.append(
                f"required check {check_id} is {required_entry.classification}"
                + (f": {required_entry.reason}" if required_entry.reason else "")
            )
    if not provenance.source_commit or not provenance.source_tree_hash:
        reasons.append("official package source commit/tree provenance is unknown")
    if provenance.provenance_method == "unknown":
        reasons.append("official package provenance method is unknown")
    return ("FAIL", sorted(set(reasons))) if reasons else ("PASS", [])


def _safe_files(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("audit root must be an ordinary directory")
    files: list[Path] = []
    total = 0
    for current, directories, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            metadata = os.lstat(current_path / directory)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"audit bundle contains symlink: {directory}")
        for name in names:
            path = current_path / name
            metadata = os.lstat(path)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError(f"audit bundle contains unsafe file: {path.relative_to(root)}")
            if metadata.st_size > _MAX_FILE_BYTES:
                raise ValueError(f"audit file exceeds size bound: {path.relative_to(root)}")
            total += metadata.st_size
            if total > _MAX_TOTAL_BYTES:
                raise ValueError("audit bundle exceeds aggregate size bound")
            files.append(path)
            if len(files) > _MAX_FILES:
                raise ValueError("audit bundle exceeds file-count bound")
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def write_hash_manifest(root: Path) -> str:
    """Hash every current bundle file except the hash list itself."""

    lines = []
    for path in _safe_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == "hashes.sha256":
            continue
        lines.append(f"{sha256_file(path)}  {relative}\n")
    hashes = root / "hashes.sha256"
    temporary = root / ".hashes.sha256.tmp"
    temporary.write_text("".join(lines), encoding="utf-8")
    os.replace(temporary, hashes)
    return sha256_file(hashes)


def _read_hash_manifest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (root / "hashes.sha256").read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        path = PurePosixPath(relative)
        if (
            not separator
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or relative == "hashes.sha256"
            or relative in result
        ):
            raise ValueError("invalid hashes.sha256 entry")
        result[relative] = digest
    return result


def load_evidence(path: Path) -> list[EvidenceEntry]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValueError("evidence.json must be a schema-versioned object")
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise ValueError("evidence.json entries must be a list")
    return [EvidenceEntry.model_validate(item) for item in entries]


def validate_bundle(root: Path) -> tuple[AuditManifest, str]:
    """Validate structure, hashes, evidence, and the recorded release gate."""

    files = _safe_files(root)
    relative_files = {path.relative_to(root).as_posix() for path in files}
    missing = sorted(_REQUIRED_BUNDLE_FILES - relative_files)
    if missing:
        raise ValueError(f"audit bundle is missing required files: {', '.join(missing)}")
    for path in files:
        payload = path.read_bytes()
        if any(pattern.search(payload) for pattern in _SECRET_PATTERNS):
            raise ValueError(
                f"audit bundle contains a secret-shaped value: {path.relative_to(root)}"
            )
        if b"\0" not in payload:
            text = payload.decode("utf-8", errors="ignore")
            if "/home/" in text or "/data/" in text:
                raise ValueError(f"audit bundle contains a host path: {path.relative_to(root)}")
    expected_hashes = _read_hash_manifest(root)
    actual_hashed = relative_files - {"hashes.sha256"}
    if set(expected_hashes) != actual_hashed:
        raise ValueError("hash manifest file set does not match the audit bundle")
    for relative, expected in expected_hashes.items():
        if sha256_file(root / relative) != expected:
            raise ValueError(f"audit bundle hash mismatch: {relative}")

    manifest = load_model(root / "audit_manifest.json", AuditManifest)
    if manifest.evidence_sha256 != sha256_file(root / "evidence.json"):
        raise ValueError("audit manifest does not bind evidence.json")
    evidence = load_evidence(root / "evidence.json")
    gate, reasons = evaluate_gate(
        evidence,
        manifest.package_provenance,
        manifest.required_check_ids,
    )
    if manifest.gate_result != gate or manifest.gate_reasons != reasons:
        raise ValueError("recorded release gate does not match its evidence")
    return manifest, sha256_file(root / "hashes.sha256")


__all__ = [
    "evaluate_gate",
    "load_evidence",
    "sha256_file",
    "validate_bundle",
    "write_hash_manifest",
]
