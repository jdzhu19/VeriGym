"""Deterministic external-training bundle preparation and checkpoint registration."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.exporter import validate_trajectory_dataset
from verigym.evolution.trainer import (
    build_agent_import_manifest,
    build_trainer_export_manifest,
    validate_agent_import_manifest,
)
from verigym.experiments.state import (
    atomic_dump_json,
    atomic_dump_jsonl,
    atomic_write_text,
    load_json_model,
    load_jsonl_models,
)
from verigym.schemas.evolution import (
    EpisodeTrajectory,
    ExternalAgentVersionImportManifest,
    ExternalTrainerExportManifest,
    RewardDerivationRecord,
    RewardProfile,
    RewardVector,
    TaskSplitManifest,
)
from verigym.schemas.options import JsonValue

from .schemas import (
    ModelSnapshotIdentity,
    TrainingReferenceBundleManifest,
    TrainingReferenceConfig,
)

_MAX_METADATA_BYTES = 16 * 1024 * 1024
_BUNDLE_FILES = (
    "episodes.jsonl",
    "model-snapshot.json",
    "rewards.jsonl",
    "task-split-manifest.json",
    "trainer-config.json",
    "trainer-export-manifest.json",
)
_SEALED_BUNDLE_MEMBERS = frozenset((*_BUNDLE_FILES, "bundle-manifest.json", "SHA256SUMS"))
_METADATA_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
_FORBIDDEN_ARTIFACT_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN RSA " + b"PRIVATE KEY-----",
    b"Bearer ",
    b"/data/",
    b"/home/",
    b"/tmp/",
    b"\\Users\\",
)


def _safe_existing_directory(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError(f"{label} cannot be a symlink")
    try:
        resolved = expanded.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"{label} does not exist") from exc
    if not resolved.is_dir():
        raise ConfigurationError(f"{label} must be a directory")
    return resolved


def _new_output_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("training output must be a new or empty real directory")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _read_regular_bytes(path: Path, *, maximum: int | None = None) -> bytes:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"expected a regular file: {path.name}")
    if maximum is not None and metadata.st_size > maximum:
        raise ConfigurationError(f"metadata file is oversized: {path.name}")
    payload = path.read_bytes()
    if len(payload) != metadata.st_size:
        raise ConfigurationError(f"file changed while being read: {path.name}")
    return payload


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular_bytes(path, maximum=_MAX_METADATA_BYTES))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid JSON metadata: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"JSON metadata must be an object: {path.name}")
    return value


def _hash_file_streaming(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _directory_artifact_hash(root: Path) -> str:
    inventory: list[dict[str, int | str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ConfigurationError(
                f"checkpoint artifacts cannot contain symlinks: {relative.as_posix()}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise ConfigurationError(
                f"checkpoint artifacts must be regular files: {relative.as_posix()}"
            )
        inventory.append(
            {
                "path": relative.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _hash_file_streaming(path),
            }
        )
    if not inventory:
        raise ConfigurationError("checkpoint artifact directory is empty")
    return content_hash(inventory)


def _snapshot_hash(snapshot: ModelSnapshotIdentity) -> str:
    payload = snapshot.model_dump(mode="json")
    expected = str(payload.pop("snapshot_hash"))
    actual = content_hash(payload)
    if actual != expected:
        raise ConfigurationError("model snapshot identity changed")
    return actual


def inspect_model_snapshot(model_root: Path, *, model_id: str) -> ModelSnapshotIdentity:
    """Bind portable Qwen/Hugging Face metadata without copying or hashing full weights."""

    root = _safe_existing_directory(model_root, label="model root")
    config_path = root / "config.json"
    if not config_path.is_file():
        raise ConfigurationError("model root has no config.json")
    config = _read_json_object(config_path)
    architectures = config.get("architectures")
    if (
        not isinstance(architectures, list)
        or not architectures
        or not all(isinstance(item, str) and item for item in architectures)
    ):
        raise ConfigurationError("model config has no valid architectures")
    model_type = config.get("model_type")
    if not isinstance(model_type, str) or not model_type:
        raise ConfigurationError("model config has no valid model_type")

    index_path = root / "model.safetensors.index.json"
    declared_weight_bytes: int | None = None
    indexed_names: set[str] = set()
    if index_path.is_file():
        index = _read_json_object(index_path)
        metadata = index.get("metadata")
        if isinstance(metadata, dict):
            raw_total = metadata.get("total_size")
            if isinstance(raw_total, int) and raw_total >= 0:
                declared_weight_bytes = raw_total
        weight_map = index.get("weight_map")
        if not isinstance(weight_map, dict) or not weight_map:
            raise ConfigurationError("model weight index has no weight_map")
        for value in weight_map.values():
            if not isinstance(value, str) or Path(value).name != value:
                raise ConfigurationError("model weight index contains an unsafe shard name")
            indexed_names.add(value)

    disk_names = {path.name for path in root.glob("*.safetensors")}
    weight_names = sorted(indexed_names or disk_names)
    if not weight_names or not indexed_names.issubset(disk_names):
        raise ConfigurationError("model weight shards are missing")
    weight_files: dict[str, int] = {}
    for name in weight_names:
        path = root / name
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ConfigurationError(f"model shard is not a regular file: {name}")
        if metadata.st_size <= 0:
            raise ConfigurationError(f"model shard is empty: {name}")
        weight_files[name] = metadata.st_size
    actual_weight_bytes = sum(weight_files.values())
    if declared_weight_bytes is not None:
        overhead = actual_weight_bytes - declared_weight_bytes
        if overhead < 0 or overhead > max(1024 * 1024, len(weight_files) * 1024 * 1024):
            raise ConfigurationError("model weight sizes differ unexpectedly from their index")

    metadata_file_hashes = {
        name: hash_bytes(_read_regular_bytes(root / name, maximum=_MAX_METADATA_BYTES))
        for name in _METADATA_FILES
        if (root / name).is_file()
    }
    base = {
        "schema_version": "1.0",
        "model_id": model_id,
        "architectures": architectures,
        "model_type": model_type,
        "transformers_version": (
            str(config["transformers_version"])
            if isinstance(config.get("transformers_version"), str)
            else None
        ),
        "metadata_file_hashes": dict(sorted(metadata_file_hashes.items())),
        "weight_files": weight_files,
        "declared_weight_bytes": declared_weight_bytes,
        "actual_weight_bytes": actual_weight_bytes,
        "weights_content_hashed": False,
        "raw_host_path_exported": False,
    }
    return ModelSnapshotIdentity.model_validate({**base, "snapshot_hash": content_hash(base)})


def load_training_config(path: Path) -> TrainingReferenceConfig:
    return load_json_model(path, TrainingReferenceConfig)


def resolve_model_root(config: TrainingReferenceConfig, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    value = os.environ.get(config.model_root_env)
    if not value:
        raise ConfigurationError(f"set {config.model_root_env} or pass --model-root")
    return Path(value)


def _write_sha256sums(root: Path, names: Iterable[str]) -> None:
    lines = [f"{_hash_file_streaming(root / name)}  {name}" for name in sorted(names)]
    atomic_write_text(root / "SHA256SUMS", "\n".join(lines) + "\n")


def _reject_forbidden_bundle_values(root: Path, names: Iterable[str]) -> None:
    for name in names:
        payload = _read_regular_bytes(root / name)
        for marker in _FORBIDDEN_ARTIFACT_MARKERS:
            if marker in payload:
                raise ConfigurationError(f"training bundle contains a forbidden value in {name}")


def _trainer_identity(
    config: TrainingReferenceConfig,
    snapshot: ModelSnapshotIdentity,
    *,
    config_hash: str,
) -> str:
    return content_hash(
        {
            "bridge_id": "observable_trajectory_external_trainer_v1",
            "framework": config.framework,
            "algorithm": config.algorithm,
            "adapter_type": config.adapter_type,
            "trainer_config_hash": config_hash,
            "model_snapshot_hash": snapshot.snapshot_hash,
        }
    )


def prepare_training_bundle(
    dataset: Path,
    output: Path,
    *,
    config: TrainingReferenceConfig,
    model_root: Path,
) -> TrainingReferenceBundleManifest:
    """Create a sealed, path-free trainer handoff from a validated trajectory dataset."""

    dataset_root = _safe_existing_directory(dataset, label="trajectory dataset")
    dataset_manifest = validate_trajectory_dataset(dataset_root)
    split = load_json_model(dataset_root / "task-split-manifest.json", TaskSplitManifest)
    profile = load_json_model(dataset_root / "reward-profile-manifest.json", RewardProfile)
    trajectories = load_jsonl_models(dataset_root / "trajectories.jsonl", EpisodeTrajectory)
    rewards = load_jsonl_models(dataset_root / "rewards.jsonl", RewardDerivationRecord)
    rewards_by_run = {record.run_id: record for record in rewards}
    if len(rewards_by_run) != len(rewards):
        raise ConfigurationError("trajectory dataset repeats reward run IDs")

    selected: list[EpisodeTrajectory] = []
    selected_rewards: list[RewardDerivationRecord] = []
    excluded: dict[str, str] = {}
    for trajectory in sorted(trajectories, key=lambda item: item.trajectory_id):
        if trajectory.split != "training":
            excluded[trajectory.run_id] = "not_training_split"
            continue
        if not trajectory.eligibility.eligible:
            excluded[trajectory.run_id] = trajectory.eligibility.reason
            continue
        if trajectory.reward.infrastructure_valid != 1:
            excluded[trajectory.run_id] = "infrastructure_invalid"
            continue
        record = rewards_by_run.get(trajectory.run_id)
        if record is None or record.reward != trajectory.reward:
            raise ConfigurationError("trajectory and reward records differ")
        if record.reward_hash != trajectory.reward_hash:
            raise ConfigurationError("trajectory and reward identities differ")
        selected.append(trajectory)
        selected_rewards.append(record)
    if not selected:
        raise ConfigurationError("trajectory dataset has no eligible training records")

    destination = _new_output_directory(output)
    snapshot = inspect_model_snapshot(model_root, model_id=config.model_id)
    trainer_export = build_trainer_export_manifest(
        trajectory_dataset_hash=dataset_manifest.dataset_hash,
        split_manifest_hash=split.manifest_hash,
        reward_schema_hash=content_hash(RewardVector.model_json_schema(mode="serialization")),
        reward_profile_hash=profile.profile_hash,
    )
    config_hash = content_hash(config)
    trainer_identity_hash = _trainer_identity(config, snapshot, config_hash=config_hash)

    atomic_dump_jsonl(destination / "episodes.jsonl", selected)
    atomic_dump_jsonl(destination / "rewards.jsonl", selected_rewards)
    atomic_dump_json(destination / "task-split-manifest.json", split)
    atomic_dump_json(destination / "trainer-config.json", config)
    atomic_dump_json(destination / "trainer-export-manifest.json", trainer_export)
    atomic_dump_json(destination / "model-snapshot.json", snapshot)
    file_hashes = {name: _hash_file_streaming(destination / name) for name in _BUNDLE_FILES}
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_external_training_reference_v1",
        "trajectory_dataset_hash": dataset_manifest.dataset_hash,
        "split_manifest_hash": split.manifest_hash,
        "trainer_export_manifest_hash": trainer_export.manifest_hash,
        "trainer_config_hash": config_hash,
        "trainer_identity_hash": trainer_identity_hash,
        "model_snapshot": snapshot.model_dump(mode="json"),
        "record_count": len(selected),
        "trajectory_hashes": [item.trajectory_hash for item in selected],
        "reward_hashes": [item.reward_hash for item in selected_rewards],
        "training_task_ids": sorted({item.task_id for item in selected}),
        "excluded_records": dict(sorted(excluded.items())),
        "file_hashes": file_hashes,
        "only_training_split": True,
        "infrastructure_invalid_excluded": True,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "private_reasoning_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    manifest = TrainingReferenceBundleManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )
    atomic_dump_json(destination / "bundle-manifest.json", manifest)
    protected_names = (*_BUNDLE_FILES, "bundle-manifest.json")
    _reject_forbidden_bundle_values(destination, protected_names)
    _write_sha256sums(destination, protected_names)
    return manifest


def _validate_manifest_identity(manifest: TrainingReferenceBundleManifest) -> None:
    payload = manifest.model_dump(mode="json")
    expected = str(payload.pop("manifest_hash"))
    if content_hash(payload) != expected:
        raise ConfigurationError("training bundle manifest identity changed")


def _validate_sha256sums(root: Path, names: Iterable[str]) -> None:
    expected = (
        "\n".join(f"{_hash_file_streaming(root / name)}  {name}" for name in sorted(names)) + "\n"
    )
    actual = _read_regular_bytes(root / "SHA256SUMS").decode("utf-8")
    if actual != expected:
        raise ConfigurationError("training bundle SHA256SUMS differs from its contents")


def _validate_bundle_members(root: Path) -> None:
    members = {path.name for path in root.iterdir()}
    if members != _SEALED_BUNDLE_MEMBERS:
        raise ConfigurationError("training bundle contains missing or unexpected top-level members")
    for path in root.iterdir():
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ConfigurationError("training bundle members must be regular files")


def validate_training_bundle(
    bundle: Path,
    *,
    source_dataset: Path,
) -> TrainingReferenceBundleManifest:
    """Recompute the complete trainer handoff with no model, runtime, verifier, or network."""

    root = _safe_existing_directory(bundle, label="training bundle")
    dataset_root = _safe_existing_directory(source_dataset, label="trajectory dataset")
    _validate_bundle_members(root)
    manifest = load_json_model(root / "bundle-manifest.json", TrainingReferenceBundleManifest)
    _validate_manifest_identity(manifest)
    dataset_manifest = validate_trajectory_dataset(dataset_root)
    if dataset_manifest.dataset_hash != manifest.trajectory_dataset_hash:
        raise ConfigurationError("source trajectory dataset identity changed")

    config = load_json_model(root / "trainer-config.json", TrainingReferenceConfig)
    snapshot = load_json_model(root / "model-snapshot.json", ModelSnapshotIdentity)
    split = load_json_model(root / "task-split-manifest.json", TaskSplitManifest)
    trainer_export = load_json_model(
        root / "trainer-export-manifest.json", ExternalTrainerExportManifest
    )
    episodes = load_jsonl_models(root / "episodes.jsonl", EpisodeTrajectory)
    rewards = load_jsonl_models(root / "rewards.jsonl", RewardDerivationRecord)
    if split.manifest_hash != manifest.split_manifest_hash:
        raise ConfigurationError("training split identity changed")
    if trainer_export.manifest_hash != manifest.trainer_export_manifest_hash:
        raise ConfigurationError("trainer export manifest identity changed")
    rebuilt_export = build_trainer_export_manifest(
        trajectory_dataset_hash=trainer_export.trajectory_dataset_hash,
        split_manifest_hash=trainer_export.split_manifest_hash,
        reward_schema_hash=trainer_export.reward_schema_hash,
        reward_profile_hash=trainer_export.reward_profile_hash,
    )
    if rebuilt_export != trainer_export:
        raise ConfigurationError("trainer export manifest contents changed")
    _snapshot_hash(snapshot)
    if snapshot != manifest.model_snapshot:
        raise ConfigurationError("model snapshot differs from the bundle manifest")
    config_hash = content_hash(config)
    if config_hash != manifest.trainer_config_hash:
        raise ConfigurationError("trainer configuration identity changed")
    if (
        _trainer_identity(config, snapshot, config_hash=config_hash)
        != manifest.trainer_identity_hash
    ):
        raise ConfigurationError("trainer identity changed")
    if [item.trajectory_hash for item in episodes] != manifest.trajectory_hashes:
        raise ConfigurationError("training episode identities changed")
    if [item.reward_hash for item in rewards] != manifest.reward_hashes:
        raise ConfigurationError("training reward identities changed")
    if [item.run_id for item in episodes] != [item.run_id for item in rewards]:
        raise ConfigurationError("training episodes and rewards are not aligned")
    if any(
        item.split != "training"
        or not item.eligibility.eligible
        or item.reward.infrastructure_valid != 1
        for item in episodes
    ):
        raise ConfigurationError("training bundle contains an ineligible episode")
    if sorted({item.task_id for item in episodes}) != manifest.training_task_ids:
        raise ConfigurationError("training task identities changed")
    actual_file_hashes = {name: _hash_file_streaming(root / name) for name in _BUNDLE_FILES}
    if actual_file_hashes != manifest.file_hashes:
        raise ConfigurationError("training bundle file hashes changed")
    protected_names = (*_BUNDLE_FILES, "bundle-manifest.json")
    _reject_forbidden_bundle_values(root, protected_names)
    _validate_sha256sums(root, protected_names)
    return manifest


def register_checkpoint(
    bundle: Path,
    checkpoint: Path,
    output: Path,
    *,
    source_dataset: Path,
    import_id: str,
    parent_version_hash: str,
    compatible_runtime_hash: str,
    license: str,
    provenance: str,
    loading_configuration: Mapping[str, JsonValue],
    update_type: str = "external_adapter",
) -> ExternalAgentVersionImportManifest:
    """Hash a completed external artifact and create VeriGym's provenance-only import record."""

    manifest = validate_training_bundle(bundle, source_dataset=source_dataset)
    checkpoint_root = _safe_existing_directory(checkpoint, label="checkpoint artifact")
    artifact_hash = _directory_artifact_hash(checkpoint_root)
    imported = build_agent_import_manifest(
        import_id=import_id,
        update_type=update_type,
        parent_version_hash=parent_version_hash,
        trainer_identity_hash=manifest.trainer_identity_hash,
        training_dataset_hash=manifest.trajectory_dataset_hash,
        artifact_hash=artifact_hash,
        compatible_runtime_hash=compatible_runtime_hash,
        license=license,
        provenance=provenance,
        loading_configuration=loading_configuration,
    )
    validate_agent_import_manifest(imported)
    destination = output.expanduser()
    if destination.exists() and (destination.is_symlink() or not destination.is_file()):
        raise ConfigurationError("checkpoint import output must be a regular file path")
    atomic_dump_json(destination, imported)
    return imported


def exclusion_counts(manifest: TrainingReferenceBundleManifest) -> dict[str, int]:
    """Return stable human-readable exclusion counts without exposing record contents."""

    return dict(sorted(Counter(manifest.excluded_records.values()).items()))


__all__ = [
    "exclusion_counts",
    "inspect_model_snapshot",
    "load_training_config",
    "prepare_training_bundle",
    "register_checkpoint",
    "resolve_model_root",
    "validate_training_bundle",
]
