"""Fail-closed loading of prepared HWE-Bench sources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.plugin_api import ConfigurationError, content_hash, hash_bytes, hash_directory

from .models import HweInstance, ImageLock, ImageLockEntry

VARIANT = "repo-repair-v1"
NATIVE_LAYOUT = "hwe_bench_selected_records_and_digest_locked_images_v1"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


@dataclass(frozen=True)
class Catalog:
    root: Path
    instances: dict[str, HweInstance]
    entries: dict[str, ImageLockEntry]
    lock: ImageLock
    content_hash: str

    def instance_for_slug(self, slug: str) -> tuple[HweInstance, ImageLockEntry]:
        instance = next((item for item in self.instances.values() if item.slug == slug), None)
        if instance is None:
            raise ConfigurationError(f"unknown prepared HWE-Bench task: {slug}")
        return instance, self.entries[instance.instance_id]


def load_catalog(root: Path) -> Catalog:
    resolved = root.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError("HWE-Bench source root must be a directory")
    lock_path = resolved / "image-lock.json"
    records_path = resolved / "instances.jsonl"
    if not lock_path.is_file() or not records_path.is_file():
        raise ConfigurationError("HWE-Bench source requires image-lock.json and instances.jsonl")
    if lock_path.is_symlink() or records_path.is_symlink():
        raise ConfigurationError("HWE-Bench source control files may not be symlinks")
    if lock_path.stat().st_size > 4 * 1024 * 1024 or records_path.stat().st_size > 64 * 1024 * 1024:
        raise ConfigurationError("HWE-Bench source control files exceed their size limits")
    try:
        lock = ImageLock.model_validate(
            json.loads(lock_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        )
        instances: dict[str, HweInstance] = {}
        for line_number, line in enumerate(
            records_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line or len(line.encode("utf-8")) > 16 * 1024 * 1024:
                raise ValueError(f"invalid instances.jsonl record at line {line_number}")
            instance = HweInstance.model_validate(
                json.loads(line, object_pairs_hook=_unique_object)
            )
            if instance.instance_id in instances:
                raise ValueError(f"duplicate HWE-Bench instance: {instance.instance_id}")
            instances[instance.instance_id] = instance
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ConfigurationError(f"invalid prepared HWE-Bench source: {exc}") from exc
    entries = {entry.instance_id: entry for entry in lock.entries}
    if set(entries) != set(instances):
        raise ConfigurationError("HWE-Bench image lock and selected records disagree")
    for instance_id, instance in instances.items():
        entry = entries[instance_id]
        if entry.slug != instance.slug or entry.base_commit != instance.base_commit:
            raise ConfigurationError("HWE-Bench image lock identity differs from its record")
        workspace = resolved / "workspaces" / entry.slug
        repository = workspace / "repository"
        if not repository.is_dir() or not (workspace / "TASK.md").is_file():
            raise ConfigurationError(f"prepared workspace is incomplete: {entry.slug}")
        if hash_directory(repository) != entry.repository_hash:
            raise ConfigurationError(f"prepared repository hash changed: {entry.slug}")
        license_file = repository / "LICENSE"
        if (
            not license_file.is_file()
            or hash_bytes(license_file.read_bytes()) != entry.license_file_hash
        ):
            raise ConfigurationError(f"prepared repository license changed: {entry.slug}")
        expected_bundle = content_hash(
            {
                "instance": instance,
                "repository_hash": entry.repository_hash,
                "image_id": entry.image_id,
                "manifest_digest": entry.manifest_digest,
            }
        )
        if expected_bundle != entry.task_bundle_hash:
            raise ConfigurationError(f"prepared task bundle identity changed: {entry.slug}")
    source_hash = content_hash(
        {
            "lock": lock,
            "records_sha256": hash_bytes(records_path.read_bytes()),
        }
    )
    return Catalog(
        root=resolved,
        instances=instances,
        entries=entries,
        lock=lock,
        content_hash=source_hash,
    )


__all__ = ["Catalog", "NATIVE_LAYOUT", "VARIANT", "load_catalog"]
