"""Registration and validation for executable external training-policy versions."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.options import JsonValue

from .pipeline import inspect_model_snapshot
from .schemas import TrainingPolicyVersionManifest

_MAX_JSON_BYTES = 16 * 1024 * 1024


def _read_json(path: Path) -> dict[str, Any]:
    metadata = os.lstat(path)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not 0 < metadata.st_size <= _MAX_JSON_BYTES
    ):
        raise ConfigurationError(f"unsafe JSON input: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid JSON input: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"JSON input must be an object: {path.name}")
    return value


def _verified_hash(record: dict[str, Any], field: str, *, label: str) -> str:
    expected = record.get(field)
    if not isinstance(expected, str):
        raise ConfigurationError(f"{label} omits {field}")
    identity = dict(record)
    identity.pop(field)
    if content_hash(identity) != expected:
        raise ConfigurationError(f"{label} identity differs from {field}")
    return expected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _adapter_artifact_hash(root: Path, report: dict[str, Any]) -> str:
    expanded = root.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError("adapter artifact cannot be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError("adapter artifact must be a directory")
    raw_inventory = report.get("adapter_inventory")
    if not isinstance(raw_inventory, list) or not raw_inventory:
        raise ConfigurationError("training report has no adapter inventory")
    inventory: list[dict[str, int | str]] = []
    seen: set[str] = set()
    for item in raw_inventory:
        if not isinstance(item, dict):
            raise ConfigurationError("adapter inventory entries must be objects")
        relative = item.get("path")
        size = item.get("size_bytes")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not relative or relative in seen:
            raise ConfigurationError("adapter inventory has an invalid path")
        unresolved = resolved / relative
        if unresolved.is_symlink():
            raise ConfigurationError(f"adapter inventory contains a symlink: {relative}")
        candidate = unresolved.resolve(strict=True)
        if (
            not candidate.is_relative_to(resolved)
            or candidate.is_symlink()
            or not candidate.is_file()
            or not isinstance(size, int)
            or candidate.stat().st_size != size
            or not isinstance(expected, str)
            or _sha256(candidate) != expected
        ):
            raise ConfigurationError(f"adapter inventory differs for {relative}")
        seen.add(relative)
        inventory.append({"path": relative, "size_bytes": size, "sha256": expected})
    actual_paths = {
        path.relative_to(resolved).as_posix()
        for path in resolved.rglob("*")
        if path.is_file() and path.name != "training-report.json"
    }
    if actual_paths != seen:
        raise ConfigurationError("adapter file set differs from its training report")
    if inventory != sorted(inventory, key=lambda item: str(item["path"])):
        raise ConfigurationError("adapter inventory is not sorted")
    encoded = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    actual = hashlib.sha256(encoded).hexdigest()
    if actual != report.get("adapter_artifact_hash"):
        raise ConfigurationError("adapter artifact hash differs from its training report")
    return actual


def _parent(path: Path | None) -> TrainingPolicyVersionManifest | None:
    if path is None:
        return None
    value = TrainingPolicyVersionManifest.model_validate(_read_json(path.expanduser()))
    payload = value.model_dump(mode="json")
    expected = payload.pop("version_hash")
    if content_hash(payload) != expected:
        raise ConfigurationError("parent policy version identity changed")
    return value


def _manifest_hash(path: Path | None, *, label: str) -> str | None:
    if path is None:
        return None
    value = _read_json(path.expanduser())
    return _verified_hash(value, "manifest_hash", label=label)


def register_training_policy_version(
    *,
    output: Path,
    policy_version_id: str,
    weight_version: int | None,
    update_type: str,
    model_id: str,
    model_root: Path,
    source_commit: str,
    loading_configuration: Mapping[str, JsonValue],
    artifact: Path | None = None,
    parent_manifest: Path | None = None,
    training_manifest: Path | None = None,
    reward_manifest: Path | None = None,
    training_report: Path | None = None,
) -> TrainingPolicyVersionManifest:
    """Register a base, verified-SFT, or VeriGym-GRPO policy without storing host paths."""

    snapshot = inspect_model_snapshot(model_root, model_id=model_id)
    parent = _parent(parent_manifest)
    training_data_hash = _manifest_hash(training_manifest, label="training data manifest")
    reward_hash = _manifest_hash(reward_manifest, label="reward manifest")
    report: dict[str, Any] | None = None
    report_hash: str | None = None
    trainer_identity_hash: str | None = None
    framework_commits: dict[str, str] = {}
    if training_report is not None:
        report = _read_json(training_report.expanduser())
        report_hash = _verified_hash(report, "report_hash", label="training report")
        software = report.get("software")
        trainer_identity_hash = content_hash(
            {
                "training_kind": report.get("training_kind"),
                "software": software if isinstance(software, dict) else {},
                "learning_rate": report.get("learning_rate"),
                "world_size": report.get("world_size"),
                "source_commit": source_commit,
            }
        )
        for name in ("rllm", "verl"):
            value = report.get(f"{name}_commit")
            if isinstance(value, str):
                framework_commits[name] = value

    if update_type == "base":
        artifact_kind = "model_snapshot"
        artifact_hash = snapshot.snapshot_hash
    else:
        if artifact is None or report is None:
            raise ConfigurationError("trained policy versions require an artifact and report")
        artifact_kind = "lora_adapter"
        artifact_hash = _adapter_artifact_hash(artifact, report)
    parent_hash = parent.version_hash if parent is not None else None
    if parent is not None:
        if parent.base_model_snapshot_hash != snapshot.snapshot_hash or parent.model_id != model_id:
            raise ConfigurationError("parent and child base-model identities differ")
        expected_weight = 0 if parent.weight_version is None else parent.weight_version + 1
        if weight_version != expected_weight:
            raise ConfigurationError("policy weight version is not the parent successor")
        if report is not None and parent.artifact_kind == "lora_adapter":
            expected_parent = report.get("parent_adapter_weights_sha256")
            if expected_parent is not None:
                if not isinstance(expected_parent, str):
                    raise ConfigurationError("training report has incomplete adapter lineage")
                parent_loading = parent.loading_configuration.get("adapter_weights_sha256")
                if expected_parent != parent_loading:
                    raise ConfigurationError(
                        "training report parent differs from the registered parent"
                    )

    configuration = dict(loading_configuration)
    if report is not None:
        weights_hash = next(
            (
                item.get("sha256")
                for item in report.get("adapter_inventory", [])
                if isinstance(item, dict) and item.get("path") == "adapter_model.safetensors"
            ),
            None,
        )
        if isinstance(weights_hash, str):
            configuration["adapter_weights_sha256"] = weights_hash
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_training_policy_version_v1",
        "policy_version_id": policy_version_id,
        "weight_version": weight_version,
        "parent_version_hash": parent_hash,
        "update_type": update_type,
        "model_id": model_id,
        "base_model_snapshot_hash": snapshot.snapshot_hash,
        "artifact_kind": artifact_kind,
        "artifact_hash": artifact_hash,
        "training_data_hash": training_data_hash,
        "reward_manifest_hash": reward_hash,
        "trainer_report_hash": report_hash,
        "trainer_identity_hash": trainer_identity_hash,
        "source_commit": source_commit,
        "framework_commits": framework_commits,
        "loading_configuration": configuration,
        "executable": True,
        "hidden_assets_loaded": False,
        "reference_solution_loaded": False,
        "credential_values_included": False,
        "raw_host_paths_included": False,
    }
    version = TrainingPolicyVersionManifest.model_validate(
        {**base, "version_hash": content_hash(base)}
    )
    destination = output.expanduser()
    if destination.exists():
        raise ConfigurationError("policy version output already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_dump_json(destination, version)
    return version


__all__ = ["register_training_policy_version"]
