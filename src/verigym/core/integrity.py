"""Non-executing, bounded integrity manifests for persisted artifacts."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Literal

from verigym.core.errors import ArtifactIntegrityError, SchemaCompatibilityError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.schema_compat import validate_schema_version
from verigym.schemas.integrity import ArtifactEntry, ArtifactManifest, IntegrityValidation

_MANIFEST_NAME = "artifact_manifest.json"
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_MAX_ENTRIES = 100_000
_MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
_RUN_REQUIRED = {
    "run_manifest.json",
    "task_snapshot.json",
    "trace.jsonl",
    "scorecard.json",
    "workspace_diff.patch",
}
_EXPERIMENT_REQUIRED = {
    "experiment_manifest.json",
    "experiment_config.json",
    "plan.jsonl",
    "events.jsonl",
    "state.json",
    "run_index.jsonl",
    "reports/aggregate.json",
    "reports/runs.csv",
    "reports/report.md",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ArtifactIntegrityError(f"duplicate JSON key in artifact manifest: {key!r}")
        value[key] = item
    return value


def _safe_file(root: Path, relative: str) -> tuple[Path, os.stat_result]:
    current = root
    for part in relative.split("/"):
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise ArtifactIntegrityError(f"integrity artifact is missing: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ArtifactIntegrityError(f"integrity artifact traverses a symlink: {relative}")
    if not stat.S_ISREG(metadata.st_mode):
        raise ArtifactIntegrityError(f"integrity artifact is not a regular file: {relative}")
    if metadata.st_nlink != 1:
        raise ArtifactIntegrityError(f"integrity artifact is hard-linked: {relative}")
    return current, metadata


def _entry(
    root: Path,
    relative: str,
    *,
    role: str,
    required: bool,
    visibility: Literal["public", "private_summary"] = "public",
) -> ArtifactEntry:
    path, metadata = _safe_file(root, relative)
    payload = path.read_bytes()
    if len(payload) != metadata.st_size:
        raise ArtifactIntegrityError(f"integrity artifact changed while hashing: {relative}")
    content_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
    return ArtifactEntry(
        relative_path=relative,
        role=role,
        visibility=visibility,
        size_bytes=len(payload),
        sha256=hash_bytes(payload),
        required=required,
        content_type=content_type,
    )


def _atomic_manifest(path: Path, manifest: ArtifactManifest) -> None:
    payload = (
        json.dumps(
            manifest.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _manifest(
    *,
    scope: Literal["run", "experiment", "sample_set"],
    owner_id: str,
    entries: list[ArtifactEntry],
) -> ArtifactManifest:
    ordered = sorted(entries, key=lambda item: item.relative_path)
    paths = [entry.relative_path for entry in ordered]
    if len(paths) != len(set(paths)):
        raise ArtifactIntegrityError("artifact manifest contains duplicate normalized paths")
    if len(ordered) > _MAX_ENTRIES:
        raise ArtifactIntegrityError("artifact manifest exceeds its entry-count bound")
    if sum(entry.size_bytes for entry in ordered) > _MAX_TOTAL_BYTES:
        raise ArtifactIntegrityError("artifact manifest exceeds its total-byte bound")
    return ArtifactManifest(
        scope=scope,
        owner_id=owner_id,
        entries_hash=content_hash([entry.model_dump(mode="json") for entry in ordered]),
        entries=ordered,
    )


def _walk_regular_files(root: Path, prefix: str) -> list[str]:
    base = root / prefix
    if not base.is_dir() or base.is_symlink():
        raise ArtifactIntegrityError(f"required artifact directory is unsafe: {prefix}")
    found: list[str] = []
    count = 0
    for directory, names, files in os.walk(base, followlinks=False):
        directory_path = Path(directory)
        retained: list[str] = []
        for name in sorted(names):
            entry = directory_path / name
            metadata = os.lstat(entry)
            if stat.S_ISLNK(metadata.st_mode):
                raise ArtifactIntegrityError(
                    f"artifact directory contains a symlink: {entry.relative_to(root).as_posix()}"
                )
            if not stat.S_ISDIR(metadata.st_mode):
                raise ArtifactIntegrityError(
                    f"artifact directory contains a special entry: "
                    f"{entry.relative_to(root).as_posix()}"
                )
            relative = entry.relative_to(root).as_posix()
            if relative == "artifacts/replay-verification":
                continue
            retained.append(name)
        names[:] = retained
        for name in sorted(files):
            count += 1
            if count > _MAX_ENTRIES:
                raise ArtifactIntegrityError("artifact tree exceeds its entry-count bound")
            entry = directory_path / name
            relative = entry.relative_to(root).as_posix()
            _safe_file(root, relative)
            found.append(relative)
    return found


def write_run_artifact_manifest(root: Path, run_id: str) -> ArtifactManifest:
    """Hash a completed run after all stable writes."""

    entries = [
        _entry(
            root,
            relative,
            role={
                "run_manifest.json": "run_manifest",
                "task_snapshot.json": "task_snapshot",
                "trace.jsonl": "episode_trace",
                "scorecard.json": "scorecard",
                "workspace_diff.patch": "workspace_diff",
            }[relative],
            required=True,
        )
        for relative in sorted(_RUN_REQUIRED)
    ]
    for prefix, role in (
        ("candidate", "candidate_snapshot"),
        ("logs", "run_log"),
        ("artifacts", "run_artifact"),
    ):
        for relative in _walk_regular_files(root, prefix):
            entries.append(
                _entry(
                    root,
                    relative,
                    role=role,
                    required=prefix == "candidate",
                    visibility=(
                        "private_summary" if "/reference/" in f"/{relative}/" else "public"
                    ),
                )
            )
    manifest = _manifest(scope="run", owner_id=run_id, entries=entries)
    _atomic_manifest(root / _MANIFEST_NAME, manifest)
    return manifest


def _experiment_child_paths(root: Path) -> list[str]:
    index = root / "run_index.jsonl"
    if not index.is_file() or index.is_symlink():
        return []
    paths: list[str] = []
    for line_number, line in enumerate(index.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ArtifactIntegrityError(f"blank run-index record at line {line_number}")
        try:
            payload = json.loads(line, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ArtifactIntegrityError(f"invalid run-index record at line {line_number}") from exc
        relative = payload.get("relative_child_path")
        if not isinstance(relative, str):
            continue
        for name in ("run_manifest.json", "scorecard.json", "artifact_manifest.json"):
            candidate = f"{relative}/{name}"
            if (root / candidate).is_file():
                paths.append(candidate)
    return paths


def write_experiment_artifact_manifest(root: Path, experiment_id: str) -> ArtifactManifest:
    """Hash a terminal experiment parent and the child identities it indexes."""

    entries = [
        _entry(
            root,
            relative,
            role=("aggregate_report" if relative.startswith("reports/") else "experiment_parent"),
            required=True,
        )
        for relative in sorted(_EXPERIMENT_REQUIRED)
    ]
    batch_log = root / "logs" / "batch.log"
    if batch_log.is_file():
        entries.append(_entry(root, "logs/batch.log", role="batch_log", required=False))
    for relative in sorted(set(_experiment_child_paths(root))):
        role = (
            "child_artifact_manifest"
            if relative.endswith("artifact_manifest.json")
            else (
                "child_run_manifest"
                if relative.endswith("run_manifest.json")
                else "child_scorecard"
            )
        )
        entries.append(_entry(root, relative, role=role, required=True))
    manifest = _manifest(scope="experiment", owner_id=experiment_id, entries=entries)
    _atomic_manifest(root / _MANIFEST_NAME, manifest)
    return manifest


def verify_artifact_manifest(
    root: Path,
    *,
    expected_scope: Literal["run", "experiment", "sample_set"] | None = None,
) -> IntegrityValidation:
    """Verify a manifest without evaluating or importing artifact content."""

    path = root / _MANIFEST_NAME
    if not path.exists():
        return IntegrityValidation(status="legacy_unverified")
    _, metadata = _safe_file(root, _MANIFEST_NAME)
    if metadata.st_size > _MAX_MANIFEST_BYTES:
        raise ArtifactIntegrityError("artifact manifest exceeds its byte bound")
    raw = path.read_bytes()
    if len(raw) != metadata.st_size:
        raise ArtifactIntegrityError("artifact manifest changed while reading")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        validate_schema_version(payload, ArtifactManifest, artifact=_MANIFEST_NAME)
        manifest = ArtifactManifest.model_validate(payload)
    except (SchemaCompatibilityError, ArtifactIntegrityError):
        raise
    except Exception as exc:
        raise ArtifactIntegrityError(f"artifact manifest is invalid: {type(exc).__name__}") from exc
    if expected_scope is not None and manifest.scope != expected_scope:
        raise ArtifactIntegrityError(
            f"artifact manifest scope is {manifest.scope}, expected {expected_scope}"
        )
    paths = [entry.relative_path for entry in manifest.entries]
    if len(paths) != len(set(paths)):
        raise ArtifactIntegrityError("artifact manifest repeats a normalized path")
    if len(paths) > _MAX_ENTRIES:
        raise ArtifactIntegrityError("artifact manifest exceeds its entry-count bound")
    if content_hash([entry.model_dump(mode="json") for entry in manifest.entries]) != (
        manifest.entries_hash
    ):
        raise ArtifactIntegrityError("artifact manifest entry identity is invalid")
    required_paths = (
        _RUN_REQUIRED
        if manifest.scope == "run"
        else _EXPERIMENT_REQUIRED
        if manifest.scope == "experiment"
        else set()
    )
    by_path = {entry.relative_path: entry for entry in manifest.entries}
    missing_contract = sorted(
        relative
        for relative in required_paths
        if relative not in by_path or not by_path[relative].required
    )
    if missing_contract:
        raise ArtifactIntegrityError(
            "artifact manifest omits required contract paths: " + ", ".join(missing_contract)
        )
    total_bytes = 0
    for entry in manifest.entries:
        artifact, artifact_metadata = _safe_file(root, entry.relative_path)
        if artifact_metadata.st_size != entry.size_bytes:
            raise ArtifactIntegrityError(
                f"artifact size differs from manifest: {entry.relative_path}"
            )
        digest = hashlib.sha256()
        with artifact.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != entry.sha256:
            raise ArtifactIntegrityError(
                f"artifact hash differs from manifest: {entry.relative_path}"
            )
        total_bytes += entry.size_bytes
        if total_bytes > _MAX_TOTAL_BYTES:
            raise ArtifactIntegrityError("verified artifacts exceed their total-byte bound")
    return IntegrityValidation(
        status="verified",
        manifest_hash=hash_bytes(raw),
        verified_entry_count=len(manifest.entries),
        verified_byte_count=total_bytes,
    )


def remove_artifact_manifest(root: Path) -> None:
    """Remove only the derived integrity index before mutating a resumed parent."""

    path = root / _MANIFEST_NAME
    if not path.exists():
        return
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ArtifactIntegrityError("existing artifact manifest is not a regular file")
    path.unlink()


__all__ = [
    "remove_artifact_manifest",
    "verify_artifact_manifest",
    "write_experiment_artifact_manifest",
    "write_run_artifact_manifest",
]
