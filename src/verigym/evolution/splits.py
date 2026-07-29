"""Task-split identity and post-freeze contamination scanning."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path

from verigym.core.hashing import content_hash, hash_bytes
from verigym.schemas.evolution import (
    ContaminationFinding,
    ContaminationScan,
    MemoryPack,
    TaskSplitEntry,
    TaskSplitManifest,
)

_MAX_FILES = 20_000
_MAX_FILE_BYTES = 8 * 1024 * 1024
_SEMANTIC_EXCLUDED_NAMES = {"LICENSE", "NOTICE", ".gitignore"}
_COMMON_MEMORY_WORDS = {
    "behavior",
    "candidate",
    "control",
    "debugging",
    "editable",
    "failure",
    "priority",
    "principles",
    "repository",
    "reset",
    "strategy",
    "testing",
    "workspace",
}


def build_task_split(
    *,
    split_id: str,
    training: Sequence[TaskSplitEntry],
    heldout: Sequence[TaskSplitEntry],
    validation: Sequence[TaskSplitEntry] = (),
    heldout_assets_loaded_after_version_hash: str | None = None,
) -> TaskSplitManifest:
    payload = {
        "schema_version": "1.0",
        "split_id": split_id,
        "training": [
            item.model_dump(mode="json") for item in sorted(training, key=lambda item: item.task_id)
        ],
        "validation": [
            item.model_dump(mode="json")
            for item in sorted(validation, key=lambda item: item.task_id)
        ],
        "heldout": [
            item.model_dump(mode="json") for item in sorted(heldout, key=lambda item: item.task_id)
        ],
        "heldout_assets_loaded_after_version_hash": heldout_assets_loaded_after_version_hash,
    }
    return TaskSplitManifest.model_validate({**payload, "manifest_hash": content_hash(payload)})


def validate_task_split(manifest: TaskSplitManifest) -> TaskSplitManifest:
    payload = manifest.model_dump(mode="json")
    expected = payload.pop("manifest_hash")
    if content_hash(payload) != expected:
        raise ValueError("task split identity changed")
    return manifest


def _regular_files(root: Path) -> dict[str, bytes]:
    resolved = root.resolve(strict=True)
    result: dict[str, bytes] = {}
    inodes: set[tuple[int, int]] = set()
    for directory, names, files in os.walk(resolved, followlinks=False):
        names.sort()
        files.sort()
        base = Path(directory)
        for name in names:
            metadata = os.lstat(base / name)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("split source contains a symlink or special directory entry")
        for name in files:
            path = base / name
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("split source contains a symlink or special file")
            inode = (metadata.st_dev, metadata.st_ino)
            if inode in inodes or metadata.st_nlink != 1:
                raise ValueError("split source contains a hard-linked file")
            inodes.add(inode)
            if metadata.st_size > _MAX_FILE_BYTES:
                raise ValueError("split source contains an oversized file")
            relative = path.relative_to(resolved).as_posix()
            result[relative] = path.read_bytes()
            if len(result) > _MAX_FILES:
                raise ValueError("split source exceeds the file-count bound")
    return result


def _shingles(payload: bytes) -> set[str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return set()
    normalized = [
        " ".join(line.strip().split())
        for line in text.splitlines()
        if len(" ".join(line.strip().split())) >= 16
        and not line.lstrip().startswith(("//", "#", "/*", "*"))
    ]
    return {
        hash_bytes("\n".join(normalized[index : index + 5]).encode("utf-8"))
        for index in range(max(0, len(normalized) - 4))
    }


def _heldout_tokens(files: Mapping[str, bytes]) -> set[str]:
    tokens: set[str] = set()
    for path, payload in files.items():
        tokens.update(
            value.casefold() for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]{7,}", Path(path).stem)
        )
        if not path.endswith("issue.md"):
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        tokens.update(value.casefold() for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]{7,}", text))
    return tokens - _COMMON_MEMORY_WORDS


def scan_contamination(
    *,
    split_manifest: TaskSplitManifest,
    training_roots: Mapping[str, Path],
    heldout_roots: Mapping[str, Path],
    memory_pack: MemoryPack | None = None,
) -> ContaminationScan:
    """Compare identities after v1 freeze without exporting private asset content."""

    validate_task_split(split_manifest)
    expected_train = {item.task_id for item in split_manifest.training}
    expected_heldout = {item.task_id for item in split_manifest.heldout}
    if set(training_roots) != expected_train or set(heldout_roots) != expected_heldout:
        raise ValueError("contamination roots do not match the frozen split")
    train_files = {
        f"{task_id}:{path}": payload
        for task_id, root in sorted(training_roots.items())
        for path, payload in _regular_files(root).items()
    }
    heldout_files = {
        f"{task_id}:{path}": payload
        for task_id, root in sorted(heldout_roots.items())
        for path, payload in _regular_files(root).items()
    }
    findings: list[ContaminationFinding] = []
    train_hashes: dict[str, list[str]] = {}
    for identity, payload in train_files.items():
        if Path(identity.split(":", 1)[1]).name in _SEMANTIC_EXCLUDED_NAMES:
            continue
        train_hashes.setdefault(hash_bytes(payload), []).append(identity)
    for identity, payload in heldout_files.items():
        if Path(identity.split(":", 1)[1]).name in _SEMANTIC_EXCLUDED_NAMES:
            continue
        digest = hash_bytes(payload)
        for training_identity in train_hashes.get(digest, []):
            findings.append(
                ContaminationFinding(
                    category="identical_file",
                    training_identity=training_identity,
                    heldout_identity=identity,
                    evidence_hash=digest,
                )
            )
    for class_name, suffix, category in (
        ("reference", "/reference.patch", "reference_fragment"),
        ("hidden", ".sv", "hidden_test_fragment"),
    ):
        train_shingles = {
            shingle: identity
            for identity, payload in train_files.items()
            if (
                (class_name == "reference" and identity.endswith(suffix))
                or (class_name == "hidden" and ":hidden/" in identity and identity.endswith(suffix))
            )
            for shingle in _shingles(payload)
        }
        for identity, payload in heldout_files.items():
            selected = (class_name == "reference" and identity.endswith(suffix)) or (
                class_name == "hidden" and ":hidden/" in identity and identity.endswith(suffix)
            )
            if not selected:
                continue
            for shingle in sorted(_shingles(payload) & train_shingles.keys()):
                findings.append(
                    ContaminationFinding(
                        category=category,  # type: ignore[arg-type]
                        training_identity=train_shingles[shingle],
                        heldout_identity=identity,
                        evidence_hash=shingle,
                    )
                )
    train_issues = {
        hash_bytes(b" ".join(payload.split()).lower()): identity
        for identity, payload in train_files.items()
        if identity.endswith(":issue.md")
    }
    for identity, payload in heldout_files.items():
        if not identity.endswith(":issue.md"):
            continue
        digest = hash_bytes(b" ".join(payload.split()).lower())
        if digest in train_issues:
            findings.append(
                ContaminationFinding(
                    category="issue_text_overlap",
                    training_identity=train_issues[digest],
                    heldout_identity=identity,
                    evidence_hash=digest,
                )
            )
    if memory_pack is not None:
        memory_text = "\n".join(
            item for section in memory_pack.sections for item in section.items
        ).casefold()
        tokens = _heldout_tokens(heldout_files)
        for token in sorted(token for token in tokens if token in memory_text):
            findings.append(
                ContaminationFinding(
                    category="memory_heldout_token",
                    training_identity=memory_pack.memory_pack_id,
                    heldout_identity="<heldout-token>",
                    evidence_hash=hash_bytes(token.encode("utf-8")),
                )
            )
    findings.sort(
        key=lambda item: (
            item.category,
            item.training_identity,
            item.heldout_identity,
            item.evidence_hash,
        )
    )
    base = {
        "schema_version": "1.0",
        "scan_id": f"{split_manifest.split_id}-contamination",
        "split_manifest_hash": split_manifest.manifest_hash,
        "memory_pack_hash": memory_pack.content_hash if memory_pack is not None else None,
        "findings": [item.model_dump(mode="json") for item in findings],
        "passed": not findings,
        "train_file_count": len(train_files),
        "heldout_file_count": len(heldout_files),
        "hidden_assets_exported": False,
        "reference_assets_exported": False,
    }
    return ContaminationScan.model_validate({**base, "scan_hash": content_hash(base)})


def validate_contamination_scan(scan: ContaminationScan) -> ContaminationScan:
    payload = scan.model_dump(mode="json")
    expected = payload.pop("scan_hash")
    if content_hash(payload) != expected:
        raise ValueError("contamination scan identity changed")
    return scan


__all__ = [
    "build_task_split",
    "scan_contamination",
    "validate_contamination_scan",
    "validate_task_split",
]
