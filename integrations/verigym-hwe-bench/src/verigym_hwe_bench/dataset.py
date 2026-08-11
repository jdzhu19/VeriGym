"""Fail-closed loading of prepared HWE-Bench sources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.plugin_api import ConfigurationError, content_hash, hash_bytes, hash_directory

from .models import (
    HweInstance,
    ImageLock,
    ImageLockEntry,
    ImageLockEntryType,
    ImageLockEntryV2,
    ImageLockType,
    ImageLockV2,
    LicenseFileLock,
    RepositoryProfile,
    VerifierDependencyFile,
    repository_profile,
)

VARIANT = "repo-repair-v1"
NATIVE_LAYOUT_V1 = "hwe_bench_selected_records_and_digest_locked_images_v1"
NATIVE_LAYOUT_V2 = "hwe_bench_profile_bound_digest_locked_images_v2"


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
    entries: dict[str, ImageLockEntryType]
    profiles: dict[str, RepositoryProfile]
    verifier_dependency_roots: dict[str, Path | None]
    lock: ImageLockType
    content_hash: str

    def instance_for_slug(self, slug: str) -> tuple[HweInstance, ImageLockEntryType]:
        instance = next((item for item in self.instances.values() if item.slug == slug), None)
        if instance is None:
            raise ConfigurationError(f"unknown prepared HWE-Bench task: {slug}")
        return instance, self.entries[instance.instance_id]

    @property
    def native_layout(self) -> str:
        return NATIVE_LAYOUT_V2 if isinstance(self.lock, ImageLockV2) else NATIVE_LAYOUT_V1

    def profile_for(self, instance_id: str) -> RepositoryProfile:
        return self.profiles[instance_id].model_copy(deep=True)

    def verifier_dependency_root(self, instance_id: str) -> Path | None:
        return self.verifier_dependency_roots[instance_id]


def _load_lock(value: dict[str, Any]) -> ImageLockType:
    format_id = value.get("format_id")
    if format_id == "verigym_hwe_bench_source_v1":
        return ImageLock.model_validate(value)
    if format_id == "verigym_hwe_bench_source_v2":
        return ImageLockV2.model_validate(value)
    raise ValueError("unsupported HWE-Bench source-lock format")


def _profile_for(instance: HweInstance, entry: ImageLockEntryType) -> RepositoryProfile:
    profile = repository_profile(instance.repository_id)
    if profile.repository_home != entry.repository_home:
        raise ConfigurationError("HWE-Bench repository home differs from its executable profile")
    if isinstance(entry, ImageLockEntryV2) and (
        entry.base_commit_marker != profile.base_commit_marker
        or entry.repository_profile_hash != profile.profile_hash
        or instance.language != profile.language
        or instance.license_id != profile.license_expression
        or entry.verifier_dependencies != profile.verifier_dependencies
    ):
        raise ConfigurationError("HWE-Bench v2 source lock differs from its repository profile")
    return profile


def _license_inventory(
    repository: Path,
    entry: ImageLockEntryType,
    profile: RepositoryProfile,
) -> list[LicenseFileLock]:
    if isinstance(entry, ImageLockEntry):
        license_file = repository / "LICENSE"
        if (
            not license_file.is_file()
            or license_file.is_symlink()
            or hash_bytes(license_file.read_bytes()) != entry.license_file_hash
        ):
            raise ConfigurationError("prepared repository license changed")
        return [LicenseFileLock(path="LICENSE", sha256=entry.license_file_hash)]
    if [item.path for item in entry.license_inventory] != profile.license_files:
        raise ConfigurationError("prepared repository license inventory differs from its profile")
    for item in entry.license_inventory:
        license_file = repository / item.path
        if (
            not license_file.is_file()
            or license_file.is_symlink()
            or hash_bytes(license_file.read_bytes()) != item.sha256
        ):
            raise ConfigurationError(f"prepared repository license changed: {item.path}")
    return [item.model_copy(deep=True) for item in entry.license_inventory]


def _verifier_dependency_root(
    source_root: Path,
    entry: ImageLockEntryType,
    profile: RepositoryProfile,
) -> Path | None:
    dependency_root = source_root / "verifier-dependencies" / entry.slug
    if isinstance(entry, ImageLockEntry):
        expected: list[VerifierDependencyFile] = []
    else:
        expected = entry.verifier_dependencies
    if not expected:
        if dependency_root.exists() or dependency_root.is_symlink():
            raise ConfigurationError("prepared source contains unexpected verifier dependencies")
        return None
    if dependency_root.is_symlink() or not dependency_root.is_dir():
        raise ConfigurationError("prepared verifier dependency root is missing or unsafe")
    resolved_root = dependency_root.resolve(strict=True)
    expected_paths = {item.cache_path for item in expected}
    observed_paths: set[str] = set()
    for path in dependency_root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("prepared verifier dependencies may not contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ConfigurationError("prepared verifier dependencies contain a special file")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(resolved_root):
            raise ConfigurationError("prepared verifier dependency escapes its root")
        observed_paths.add(path.relative_to(dependency_root).as_posix())
    if observed_paths != expected_paths:
        raise ConfigurationError("prepared verifier dependency inventory changed")
    for item in expected:
        path = dependency_root / item.cache_path
        if path.stat().st_size != item.size_bytes or hash_bytes(path.read_bytes()) != item.sha256:
            raise ConfigurationError(f"prepared verifier dependency changed: {item.cache_path}")
    return resolved_root


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
        lock = _load_lock(
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
    profiles: dict[str, RepositoryProfile] = {}
    verifier_dependency_roots: dict[str, Path | None] = {}
    for instance_id, instance in instances.items():
        entry = entries[instance_id]
        if entry.slug != instance.slug:
            raise ConfigurationError("HWE-Bench image lock identity differs from its record")
        workspace = resolved / "workspaces" / entry.slug
        repository = workspace / "repository"
        if not repository.is_dir() or not (workspace / "TASK.md").is_file():
            raise ConfigurationError(f"prepared workspace is incomplete: {entry.slug}")
        if hash_directory(repository) != entry.repository_hash:
            raise ConfigurationError(f"prepared repository hash changed: {entry.slug}")
        try:
            profile = _profile_for(instance, entry)
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc
        profiles[instance_id] = profile
        verifier_dependency_roots[instance_id] = _verifier_dependency_root(resolved, entry, profile)
        inventory = _license_inventory(repository, entry, profile)
        bundle_identity: dict[str, object] = {
            "instance": instance,
            "repository_hash": entry.repository_hash,
            "image_id": entry.image_id,
            "manifest_digest": entry.manifest_digest,
        }
        if isinstance(entry, ImageLockEntryV2):
            bundle_identity.update(
                {
                    "repository_profile_hash": profile.profile_hash,
                    "license_inventory": inventory,
                    "verifier_dependencies": entry.verifier_dependencies,
                }
            )
        if entry.base_commit != instance.base_commit:
            bundle_identity["runtime_base_commit"] = entry.base_commit
        expected_bundle = content_hash(bundle_identity)
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
        profiles=profiles,
        verifier_dependency_roots=verifier_dependency_roots,
        lock=lock,
        content_hash=source_hash,
    )


__all__ = ["Catalog", "NATIVE_LAYOUT_V1", "NATIVE_LAYOUT_V2", "VARIANT", "load_catalog"]
