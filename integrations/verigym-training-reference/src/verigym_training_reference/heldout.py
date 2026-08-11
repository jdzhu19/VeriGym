"""Freeze and summarize public-only RTL held-out evaluations."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.orchestrator import VeriGym
from verigym.evolution.memory import validate_agent_version
from verigym.evolution.splits import build_task_split, validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.registry.collections import build_registries
from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.evolution import AgentVersionManifest, TaskSplitEntry, TaskSplitManifest
from verigym.schemas.suite import SuiteSourceConfig

_MAX_JSON_BYTES = 8 * 1024 * 1024
_SHA256_LENGTH = 64


def _sha256(value: str) -> str:
    if len(value) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("repository held-out identities must be lowercase SHA-256")
    return value


class RepositoryHeldoutTaskIdentity(StrictModel):
    task_id: str
    task_hash: str
    source_hash: str

    @field_validator("task_hash", "source_hash")
    @classmethod
    def hash_value(cls, value: str) -> str:
        return _sha256(value)


class RepositoryHeldoutFreezeManifest(StrictModel):
    """Content-free binding between repository tasks, a split, and a frozen agent."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_repository_heldout_freeze_v1"] = (
        "verigym_repository_heldout_freeze_v1"
    )
    split_id: str
    tasks: list[RepositoryHeldoutTaskIdentity] = Field(min_length=1, max_length=32)
    split_manifest_hash: str
    agent_version_hash: str
    hidden_assets_exported: Literal[False] = False
    reference_solutions_exported: Literal[False] = False
    public_source_contents_exported: Literal[False] = False
    sample_eligible_for_training: Literal[False] = False
    manifest_hash: str

    @field_validator("split_manifest_hash", "agent_version_hash", "manifest_hash")
    @classmethod
    def hash_value(cls, value: str) -> str:
        return _sha256(value)

    @model_validator(mode="after")
    def task_set_is_canonical(self) -> RepositoryHeldoutFreezeManifest:
        task_ids = [item.task_id for item in self.tasks]
        if task_ids != sorted(task_ids) or len(task_ids) != len(set(task_ids)):
            raise ValueError("repository held-out tasks must be unique and sorted")
        return self


@dataclass(frozen=True)
class RepositoryHeldoutRequest:
    source: Path
    task_id: str


def _read_json(path: Path) -> dict[str, Any]:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"expected a regular JSON file: {path.name}")
    if not 0 < metadata.st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError(f"JSON file is empty or oversized: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid JSON file: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"JSON root must be an object: {path.name}")
    return value


def _validated_public_training_entry(path: Path) -> TaskSplitEntry:
    value = _read_json(path)
    expected = value.get("record_hash")
    identity = dict(value)
    identity.pop("record_hash", None)
    if not isinstance(expected, str) or content_hash(identity) != expected:
        raise ConfigurationError("training public input identity differs from its record hash")
    if value.get("hidden_assets_included") is not False:
        raise ConfigurationError("training public input must exclude hidden assets")
    return TaskSplitEntry(
        task_id=value["task_id"],
        source_hash=value["source_hash"],
        task_hash=value["task_hash"],
        license="upstream-benchmark",
        attribution="VeriGym prior training campaign public task",
    )


def build_public_input_record(task: Any, visible_root: Path) -> dict[str, Any]:
    """Build the public-only model input for one already-loaded task."""

    candidate_path = task.interaction.final_submission.path
    if candidate_path is None:
        raise ConfigurationError("held-out export requires a single-file final submission")
    readme_path = visible_root / "README.md"
    candidate = visible_root / candidate_path
    if not readme_path.is_file() or not candidate.is_file():
        raise ConfigurationError("held-out visible workspace omits README or candidate skeleton")
    base = {
        "schema_version": "1.0",
        "task_id": task.id,
        "task_description": task.description,
        "public_readme": readme_path.read_text(encoding="utf-8"),
        "candidate_path": candidate_path,
        "candidate_skeleton": candidate.read_text(encoding="utf-8"),
        "source_hash": task.source.content_hash,
        "task_hash": content_hash(task),
        "hidden_assets_included": False,
    }
    return {**base, "record_hash": content_hash(base)}


def freeze_repository_heldout(
    *,
    split_id: str,
    requests: Sequence[RepositoryHeldoutRequest],
    variant: str,
    agent_version_path: Path,
    output: Path,
) -> RepositoryHeldoutFreezeManifest:
    """Freeze a multi-source repository held-out using identities only."""

    if not requests or len(requests) > 32:
        raise ConfigurationError("repository held-out requires between 1 and 32 tasks")
    resolved_requests: list[RepositoryHeldoutRequest] = []
    request_pairs: set[tuple[Path, str]] = set()
    for request in requests:
        expanded = request.source.expanduser()
        if expanded.is_symlink():
            raise ConfigurationError("repository held-out source roots may not be symlinks")
        resolved = expanded.resolve(strict=True)
        pair = (resolved, request.task_id)
        if pair in request_pairs:
            raise ConfigurationError("repository held-out repeats a source/task pair")
        request_pairs.add(pair)
        resolved_requests.append(RepositoryHeldoutRequest(source=resolved, task_id=request.task_id))

    try:
        agent_version = validate_agent_version(
            AgentVersionManifest.model_validate(_read_json(agent_version_path.expanduser()))
        )
    except (ValueError, OSError) as exc:
        raise ConfigurationError(f"invalid frozen agent-version manifest: {exc}") from exc

    service = VeriGym(build_registries())
    entries: list[TaskSplitEntry] = []
    identities: list[RepositoryHeldoutTaskIdentity] = []
    for request in resolved_requests:
        source = SuiteSourceConfig(source_root=request.source, variant=variant)
        _suite, task, _assets = service.load_task(request.task_id, source)
        if (
            task.source.kind != "repository"
            or task.source.content_hash is None
            or task.source.license is None
            or task.source.attribution is None
        ):
            raise ConfigurationError("repository held-out tasks require a frozen repository hash")
        task_hash = content_hash(task)
        entries.append(
            TaskSplitEntry(
                task_id=task.id,
                source_hash=task.source.content_hash,
                task_hash=task_hash,
                license=task.source.license,
                attribution=task.source.attribution,
            )
        )
        identities.append(
            RepositoryHeldoutTaskIdentity(
                task_id=task.id,
                source_hash=task.source.content_hash,
                task_hash=task_hash,
            )
        )
    if len({item.task_id for item in identities}) != len(identities):
        raise ConfigurationError("repository held-out task IDs must be unique")

    split = build_task_split(
        split_id=split_id,
        training=[],
        heldout=entries,
        heldout_assets_loaded_after_version_hash=agent_version.version_hash,
    )
    validate_task_split(split)
    ordered = sorted(identities, key=lambda item: item.task_id)
    base = {
        "schema_version": SCHEMA_VERSION,
        "format_id": "verigym_repository_heldout_freeze_v1",
        "split_id": split_id,
        "tasks": [item.model_dump(mode="json") for item in ordered],
        "split_manifest_hash": split.manifest_hash,
        "agent_version_hash": agent_version.version_hash,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "public_source_contents_exported": False,
        "sample_eligible_for_training": False,
    }
    manifest = RepositoryHeldoutFreezeManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )
    destination = output.expanduser()
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
            raise ConfigurationError("repository held-out output must be new or empty")
    else:
        destination.mkdir(parents=True)
    atomic_dump_json(destination / "task-split.json", split)
    atomic_dump_json(destination / "repository-heldout-freeze.json", manifest)
    return manifest


def load_repository_heldout_freeze(
    root: Path,
) -> tuple[RepositoryHeldoutFreezeManifest, TaskSplitManifest]:
    """Validate a repository held-out freeze and its exact split binding."""

    expanded = root.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError("repository held-out freeze root may not be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError("repository held-out freeze must be a directory")
    try:
        manifest = RepositoryHeldoutFreezeManifest.model_validate(
            _read_json(resolved / "repository-heldout-freeze.json")
        )
        split = TaskSplitManifest.model_validate(_read_json(resolved / "task-split.json"))
        validate_task_split(split)
    except (ValueError, OSError) as exc:
        raise ConfigurationError(f"invalid repository held-out freeze: {exc}") from exc
    payload = manifest.model_dump(mode="json")
    expected = payload.pop("manifest_hash")
    if content_hash(payload) != expected:
        raise ConfigurationError("repository held-out freeze identity changed")
    split_tasks = sorted(
        (
            RepositoryHeldoutTaskIdentity(
                task_id=item.task_id,
                task_hash=item.task_hash,
                source_hash=item.source_hash,
            )
            for item in split.heldout
        ),
        key=lambda item: item.task_id,
    )
    if (
        split.training
        or split.validation
        or split.split_id != manifest.split_id
        or split.manifest_hash != manifest.split_manifest_hash
        or split.heldout_assets_loaded_after_version_hash != manifest.agent_version_hash
        or split_tasks != manifest.tasks
    ):
        raise ConfigurationError("repository held-out freeze differs from its task split")
    return manifest, split


def freeze_heldout_evaluation(
    *,
    split_id: str,
    suite_id: str,
    source_root: Path,
    variant: str,
    task_ids: Sequence[str],
    training_public_inputs: Sequence[Path],
    output: Path,
    frozen_after_policy_hash: str,
) -> TaskSplitManifest:
    """Write a new, hash-bound held-out split without exporting verifier assets."""

    if output.exists():
        if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
            raise ConfigurationError("held-out output must be a new or empty real directory")
    else:
        output.mkdir(parents=True)
    resolved_source = source_root.resolve(strict=True)
    source_config = SuiteSourceConfig(source_root=resolved_source, variant=variant)
    suite = build_registries().suites.get(suite_id).with_source(source_config)
    references = {reference.id: reference for reference in suite.discover()}
    native_references = {reference.native_id: reference for reference in references.values()}
    if len(task_ids) != len(set(task_ids)) or not task_ids:
        raise ConfigurationError("held-out task IDs must be nonempty and unique")

    entries: list[TaskSplitEntry] = []
    public_records: list[tuple[str, dict[str, Any]]] = []
    for requested in task_ids:
        reference = references.get(requested) or native_references.get(requested)
        if reference is None:
            raise ConfigurationError(f"held-out task was not found: {requested}")
        task = suite.load_task(reference)
        assets = suite.resolve_assets(task)
        public = build_public_input_record(task, Path(assets.visible_root))
        native_id = str(task.metadata.get("native_task_id", reference.native_id))
        public_records.append((native_id, public))
        entries.append(
            TaskSplitEntry(
                task_id=task.id,
                source_hash=task.source.content_hash,
                task_hash=content_hash(task),
                license="MIT",
                attribution="VerilogEval upstream dataset",
            )
        )

    training = [_validated_public_training_entry(path) for path in training_public_inputs]
    manifest = build_task_split(
        split_id=split_id,
        training=training,
        heldout=entries,
        heldout_assets_loaded_after_version_hash=frozen_after_policy_hash,
    )
    validate_task_split(manifest)
    inputs_root = output / "public-inputs"
    inputs_root.mkdir()
    for native_id, public in public_records:
        task_root = inputs_root / native_id
        task_root.mkdir()
        atomic_dump_json(task_root / "public-input.json", public)
    atomic_dump_json(output / "task-split.json", manifest)
    inventory_base = {
        "schema_version": "1.0",
        "format_id": "verigym_heldout_public_inputs_v1",
        "split_manifest_hash": manifest.manifest_hash,
        "task_ids": sorted(entry.task_id for entry in entries),
        "public_input_hashes": sorted(public["record_hash"] for _, public in public_records),
        "public_input_file_hashes": {
            native_id: hash_bytes((inputs_root / native_id / "public-input.json").read_bytes())
            for native_id, _ in sorted(public_records)
        },
        "sample_eligible_for_training": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
    }
    atomic_dump_json(
        output / "public-input-manifest.json",
        {**inventory_base, "manifest_hash": content_hash(inventory_base)},
    )
    return manifest


def summarize_heldout_results(
    *,
    split: Path,
    policy_roots: Mapping[str, Path],
    output: Path,
) -> dict[str, Any]:
    """Aggregate completed scorecards while preserving infrastructure failures."""

    manifest = TaskSplitManifest.model_validate(_read_json(split))
    validate_task_split(manifest)
    heldout_ids = {entry.task_id for entry in manifest.heldout}
    policies: list[dict[str, Any]] = []
    for policy_id, root in sorted(policy_roots.items()):
        scorecards = [_read_json(path) for path in sorted(root.rglob("runs/*/scorecard.json"))]
        if not scorecards:
            raise ConfigurationError(f"policy evaluation has no scorecards: {policy_id}")
        observed_ids = {scorecard.get("task_id") for scorecard in scorecards}
        if observed_ids != heldout_ids:
            raise ConfigurationError(f"policy {policy_id} did not evaluate the exact held-out set")
        per_task: list[dict[str, Any]] = []
        for task_id in sorted(heldout_ids):
            task_cards = [card for card in scorecards if card.get("task_id") == task_id]
            valid = [
                card
                for card in task_cards
                if card.get("status") != "error"
                and card.get("correctness", {}).get("infrastructure_error") is False
            ]
            resolved = sum(card.get("resolved") is True for card in valid)
            compiled = sum(
                card.get("correctness", {}).get("compile_status") == "passed" for card in valid
            )
            per_task.append(
                {
                    "task_id": task_id,
                    "sample_count": len(task_cards),
                    "infrastructure_invalid_count": len(task_cards) - len(valid),
                    "compile_pass_count": compiled,
                    "resolved_count": resolved,
                    "pass_at_k": resolved > 0,
                    "wall_time_s": sum(
                        float(card.get("efficiency", {}).get("wall_time_s", 0.0))
                        for card in task_cards
                    ),
                }
            )
        total = sum(item["sample_count"] for item in per_task)
        valid_total = total - sum(item["infrastructure_invalid_count"] for item in per_task)
        resolved_total = sum(item["resolved_count"] for item in per_task)
        compile_total = sum(item["compile_pass_count"] for item in per_task)
        policies.append(
            {
                "policy_id": policy_id,
                "task_count": len(per_task),
                "sample_count": total,
                "valid_sample_count": valid_total,
                "infrastructure_invalid_count": total - valid_total,
                "compile_rate": compile_total / valid_total if valid_total else None,
                "resolved_rate": resolved_total / valid_total if valid_total else None,
                "pass_at_k_task_rate": (
                    sum(item["pass_at_k"] for item in per_task) / len(per_task)
                ),
                "verifier_wall_time_s": sum(item["wall_time_s"] for item in per_task),
                "tasks": per_task,
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_heldout_policy_comparison_v1",
        "split_manifest_hash": manifest.manifest_hash,
        "policy_count": len(policies),
        "policies": policies,
        "training_reuse_allowed": False,
    }
    report = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(output, report)
    return report
