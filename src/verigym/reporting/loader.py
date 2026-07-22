"""Safe, offline discovery and validation of ordinary child run artifacts."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.identity import (
    derive_experiment_id,
    evaluation_config_payload,
    plan_item_identity_payload,
    runtime_identity_hash,
)
from verigym.experiments.schemas import (
    ExperimentConfig,
    ExperimentManifest,
    PlanItem,
    RunIndexRecord,
)
from verigym.experiments.state import load_json_model, load_jsonl_models
from verigym.reporting.schemas import InvalidInput
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard

_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_DEPTH = 48
_MAX_CHILD_ENTRIES = 100_000
_REQUIRED_CHILD_FILES = {
    "run_manifest.json",
    "task_snapshot.json",
    "trace.jsonl",
    "scorecard.json",
    "workspace_diff.patch",
}
_REQUIRED_CHILD_DIRECTORIES = {"candidate", "logs", "artifacts"}
_REQUIRED_CHILD_ENTRIES = {
    *_REQUIRED_CHILD_FILES,
    *_REQUIRED_CHILD_DIRECTORIES,
}


@dataclass(frozen=True)
class ValidatedRun:
    plan_index: int
    attempt: int
    relative_path: str
    manifest: RunManifest
    scorecard: ScoreCard
    plan_item: PlanItem | None = None
    index_record: RunIndexRecord | None = None


@dataclass(frozen=True)
class LoadedReportInputs:
    root: Path
    source_kind: str
    experiment_id: str
    config_hash: str | None
    plan_hash: str | None
    task_set_hash: str | None
    planned_count: int
    plan_items: list[PlanItem]
    index_records: list[RunIndexRecord]
    valid_runs: list[ValidatedRun]
    invalid_inputs: list[InvalidInput]
    requested_k: list[int]
    samples_per_task: int


def _bounded_json(path: Path, model: type[Any]) -> Any:
    try:
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ConfigurationError(f"artifact is not a regular file: {path.name}")
        if metadata.st_size > _MAX_JSON_BYTES:
            raise ConfigurationError(f"artifact exceeds size limit: {path.name}")
        raw = path.read_bytes()
        if len(raw) != metadata.st_size:
            raise ConfigurationError(f"artifact changed while reading: {path.name}")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
        _check_depth(payload)
        return model.model_validate(payload)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"invalid {path.name}: {type(exc).__name__}") from exc


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigurationError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        raise ConfigurationError("JSON artifact exceeds nesting-depth limit")
    if isinstance(value, dict):
        for item in value.values():
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1)


def _safe_root(path: Path) -> Path:
    expanded = path.expanduser()
    current = Path(expanded.anchor) if expanded.is_absolute() else Path.cwd()
    parts = expanded.parts[1:] if expanded.is_absolute() else expanded.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ConfigurationError("report root cannot traverse symlink components")
    metadata = os.lstat(expanded)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ConfigurationError("report root must be a real directory, not a symlink")
    return expanded.resolve(strict=True)


def load_report_inputs(path: Path) -> LoadedReportInputs:
    root = _safe_root(path)
    if (root / "experiment_manifest.json").is_file() and (root / "plan.jsonl").is_file():
        return _load_experiment(root)
    experiment_markers = {
        "experiment_manifest.json",
        "experiment_config.json",
        "plan.jsonl",
        "run_index.jsonl",
        "state.json",
        "events.jsonl",
    }
    if any((root / name).exists() or (root / name).is_symlink() for name in experiment_markers):
        raise ConfigurationError("experiment root is incomplete or has invalid parent artifacts")
    return _load_arbitrary_root(root)


def _load_experiment(root: Path) -> LoadedReportInputs:
    manifest = load_json_model(root / "experiment_manifest.json", ExperimentManifest)
    config = load_json_model(root / "experiment_config.json", ExperimentConfig)
    if content_hash(config.identity_payload()) != manifest.config_hash:
        raise ConfigurationError("experiment config hash does not match its stored payload")
    if content_hash(evaluation_config_payload(config)) != manifest.evaluation_config_hash:
        raise ConfigurationError("experiment evaluation-config hash does not match its payload")
    plan_items = load_jsonl_models(root / "plan.jsonl", PlanItem)
    if [item.plan_index for item in plan_items] != list(range(len(plan_items))):
        raise ConfigurationError("experiment plan indices are not contiguous")
    if content_hash([item.model_dump(mode="json") for item in plan_items]) != manifest.plan_hash:
        raise ConfigurationError("experiment plan hash does not match plan.jsonl")
    if derive_experiment_id(config.name, manifest.plan_hash) != manifest.experiment_id:
        raise ConfigurationError("experiment ID does not match its immutable plan identity")
    if manifest.planned_item_count != len(plan_items):
        raise ConfigurationError("experiment manifest planned count does not match plan.jsonl")
    if manifest.suite_id != config.suite.id:
        raise ConfigurationError("experiment suite identity differs from its stored config")
    if manifest.sampling_policy != config.runs or manifest.execution_policy != config.execution:
        raise ConfigurationError("experiment policy identity differs from its stored config")
    for item in plan_items:
        raw = item.model_dump(mode="json")
        if content_hash(plan_item_identity_payload(raw)) != item.plan_item_id:
            raise ConfigurationError(f"plan item {item.plan_index} has an invalid identity")
    task_records: dict[str, dict[str, str]] = {}
    for item in plan_items:
        task_record = {
            "task_id": item.task_id,
            "task_hash": item.task_hash,
            "source_hash": item.source_hash,
        }
        incumbent = task_records.setdefault(item.task_id, task_record)
        if incumbent != task_record:
            raise ConfigurationError(f"plan contains inconsistent identity for {item.task_id}")
    if content_hash([task_records[key] for key in sorted(task_records)]) != manifest.task_set_hash:
        raise ConfigurationError("experiment task-set hash does not match plan.jsonl")
    _validate_manifest_plan_summary(manifest, plan_items)
    index_path = root / "run_index.jsonl"
    index_records = load_jsonl_models(index_path, RunIndexRecord) if index_path.is_file() else []
    attempts = [(record.plan_index, record.attempt) for record in index_records]
    if len(attempts) != len(set(attempts)):
        raise ConfigurationError("run index contains duplicate plan-index/attempt records")
    valid: list[ValidatedRun] = []
    invalid: list[InvalidInput] = []
    indexed_paths = {
        record.relative_child_path
        for record in index_records
        if record.relative_child_path is not None
    }
    runs_root = root / "runs"
    if runs_root.is_symlink():
        invalid.append(
            InvalidInput(
                relative_path="runs",
                category="symlink_rejected",
                message="experiment runs directory is a symlink",
            )
        )
    elif runs_root.is_dir():
        for child in sorted(runs_root.iterdir(), key=lambda path: path.name):
            relative = child.relative_to(root).as_posix()
            if relative not in indexed_paths:
                invalid.append(
                    InvalidInput(
                        relative_path=relative,
                        category="unindexed_child",
                        message="child artifact is not bound by run_index.jsonl",
                    )
                )
    by_index = {item.plan_index: item for item in plan_items}
    for record in sorted(index_records, key=lambda item: (item.plan_index, item.attempt)):
        plan_item = by_index.get(record.plan_index)
        if plan_item is None or plan_item.plan_item_id != record.plan_item_id:
            invalid.append(
                _invalid(
                    record.relative_child_path or ".",
                    "plan_mismatch",
                    "index has no matching plan item",
                    record,
                )
            )
            continue
        if record.artifact_validation_status != "valid":
            invalid.append(
                _invalid(
                    record.relative_child_path or ".",
                    record.artifact_validation_status,
                    "attempt was not a valid terminal child",
                    record,
                )
            )
            continue
        try:
            valid.append(
                _validate_child(
                    root,
                    record,
                    plan_item,
                    experiment_id=manifest.experiment_id,
                )
            )
        except Exception as exc:
            invalid.append(
                _invalid(
                    record.relative_child_path or ".",
                    "corrupt_artifact",
                    str(exc),
                    record,
                )
            )
    return LoadedReportInputs(
        root=root,
        source_kind="experiment",
        experiment_id=manifest.experiment_id,
        config_hash=manifest.config_hash,
        plan_hash=manifest.plan_hash,
        task_set_hash=manifest.task_set_hash,
        planned_count=len(plan_items),
        plan_items=plan_items,
        index_records=index_records,
        valid_runs=valid,
        invalid_inputs=invalid,
        requested_k=manifest.sampling_policy.pass_k,
        samples_per_task=manifest.sampling_policy.samples_per_task,
    )


def _validate_manifest_plan_summary(
    manifest: ExperimentManifest,
    plan_items: list[PlanItem],
) -> None:
    expected_systems = {item.system.system_id: item.system for item in plan_items}
    if sorted(manifest.system_identities, key=lambda item: item.system_id) != sorted(
        expected_systems.values(), key=lambda item: item.system_id
    ):
        raise ConfigurationError("experiment system identities differ from plan.jsonl")
    expected_runtimes = {item.runtime_identity_hash: item.runtime_descriptor for item in plan_items}
    if sorted(
        manifest.runtime_identities,
        key=lambda item: runtime_identity_hash(item),
    ) != sorted(
        expected_runtimes.values(),
        key=lambda item: runtime_identity_hash(item),
    ):
        raise ConfigurationError("experiment runtime identities differ from plan.jsonl")
    expected_snapshots = {
        item.suite_source_snapshot.model_dump_json(): item.suite_source_snapshot
        for item in plan_items
        if item.suite_source_snapshot is not None
    }
    if sorted(
        manifest.suite_source_snapshots,
        key=lambda item: item.configuration_fingerprint,
    ) != sorted(
        expected_snapshots.values(),
        key=lambda item: item.configuration_fingerprint,
    ):
        raise ConfigurationError("experiment source snapshots differ from plan.jsonl")
    expected_profiles = sorted(
        {item.resolved_profile_hash for item in plan_items if item.resolved_profile_hash}
    )
    checks = {
        "selected task count": manifest.selected_task_count
        == len({item.task_id for item in plan_items}),
        "suite versions": manifest.suite_versions
        == sorted({item.suite_version for item in plan_items}),
        "release IDs": manifest.release_ids
        == sorted({item.release_id for item in plan_items if item.release_id is not None}),
        "resolved profiles": manifest.resolved_profile_hashes == expected_profiles,
    }
    mismatches = [name for name, matches in checks.items() if not matches]
    if mismatches:
        raise ConfigurationError(
            "experiment manifest summary differs from plan.jsonl: " + ", ".join(mismatches)
        )


def _validate_child(
    root: Path,
    record: RunIndexRecord,
    plan_item: PlanItem,
    *,
    experiment_id: str,
) -> ValidatedRun:
    if record.relative_child_path is None:
        raise ConfigurationError("valid index record has no child path")
    child = root / record.relative_child_path
    if (root / "runs").is_symlink() or child.is_symlink():
        raise ConfigurationError("child run directory is a symlink")
    resolved = child.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ConfigurationError("child run path escapes the experiment root")
    names = {entry.name for entry in resolved.iterdir()}
    missing = sorted(_REQUIRED_CHILD_ENTRIES - names)
    if missing:
        raise ConfigurationError("child run is incomplete: " + ", ".join(missing))
    for name in _REQUIRED_CHILD_ENTRIES:
        entry = resolved / name
        if entry.is_symlink():
            raise ConfigurationError(f"required child artifact is a symlink: {name}")
    for name in _REQUIRED_CHILD_FILES:
        if not (resolved / name).is_file():
            raise ConfigurationError(f"required child artifact is not a file: {name}")
    for name in _REQUIRED_CHILD_DIRECTORIES:
        if not (resolved / name).is_dir():
            raise ConfigurationError(f"required child artifact is not a directory: {name}")
    _assert_safe_child_tree(resolved)
    manifest_path = resolved / "run_manifest.json"
    score_path = resolved / "scorecard.json"
    if record.child_manifest_hash != hash_bytes(manifest_path.read_bytes()):
        raise ConfigurationError("child manifest hash differs from the parent index")
    if record.scorecard_hash != hash_bytes(score_path.read_bytes()):
        raise ConfigurationError("child scorecard hash differs from the parent index")
    manifest = _bounded_json(manifest_path, RunManifest)
    scorecard = _bounded_json(score_path, ScoreCard)
    if record.child_run_id != manifest.run_id or child.name != manifest.run_id:
        raise ConfigurationError("child run ID differs from its parent index or directory")
    if manifest.experiment_id != experiment_id:
        raise ConfigurationError("child experiment identity differs from its parent")
    _validate_cross_references(manifest, scorecard, plan_item)
    return ValidatedRun(
        plan_index=record.plan_index,
        attempt=record.attempt,
        relative_path=record.relative_child_path,
        manifest=manifest,
        scorecard=scorecard,
        plan_item=plan_item,
        index_record=record,
    )


def _validate_cross_references(
    manifest: RunManifest,
    scorecard: ScoreCard,
    plan: PlanItem | None,
) -> None:
    if manifest.run_id != scorecard.run_id or manifest.task_id != scorecard.task_id:
        raise ConfigurationError("manifest and scorecard identities differ")
    if manifest.task_hash != scorecard.reproducibility.task_hash:
        raise ConfigurationError("manifest and scorecard task hashes differ")
    if manifest.verifier_hash != scorecard.reproducibility.verifier_hash:
        raise ConfigurationError("manifest and scorecard verifier hashes differ")
    if manifest.run_config_hash != scorecard.reproducibility.run_config_hash:
        raise ConfigurationError("manifest and scorecard run-config hashes differ")
    if plan is None:
        return
    mismatches: list[str] = []
    checks = {
        "plan_item_id": manifest.plan_item_id == plan.plan_item_id,
        "task": manifest.task_id == plan.task_id and manifest.task_hash == plan.task_hash,
        "source": manifest.source_hash == plan.source_hash,
        "suite": manifest.suite == plan.suite and manifest.suite_version == plan.suite_version,
        "suite_source": manifest.suite_source == plan.suite_source_snapshot,
        "release": manifest.release_id == plan.release_id,
        "mode": manifest.interaction_mode == plan.interaction_mode.value,
        "seed": manifest.seed == plan.child_seed and manifest.sample_index == plan.sample_index,
        "replicate": manifest.base_seed == plan.base_seed,
        "system": manifest.system_id == plan.system.system_id,
        "agent": manifest.agent == plan.system.agent_descriptor,
        "model": manifest.model == plan.system.model_descriptor,
        "prompt": manifest.prompt_policy == plan.prompt_policy,
        "tool_policy": manifest.tool_policy == plan.tool_policy,
        "budget": manifest.budget == plan.budget,
        "verifier": manifest.verifier_hash == plan.verifier_hash,
        "runtime": runtime_identity_hash(manifest.runtime) == plan.runtime_identity_hash,
        "profiles": manifest.toolchain_profiles == plan.toolchain_profiles,
        "declared_profile": manifest.declared_profile_hash == plan.declared_profile_hash,
        "resolved_profile": manifest.resolved_profile_hash == plan.resolved_profile_hash,
    }
    mismatches.extend(name for name, matches in checks.items() if not matches)
    if mismatches:
        raise ConfigurationError("child does not match plan fields: " + ", ".join(mismatches))


def validate_plan_binding(
    manifest: RunManifest,
    scorecard: ScoreCard,
    plan: PlanItem,
) -> None:
    """Validate a newly completed child against its immutable plan item."""

    _validate_cross_references(manifest, scorecard, plan)


def _load_arbitrary_root(root: Path) -> LoadedReportInputs:
    candidates: list[Path] = []
    invalid: list[InvalidInput] = []
    discovered_entries = 0
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        discovered_entries += len(names) + len(files)
        if discovered_entries > _MAX_CHILD_ENTRIES:
            raise ConfigurationError("report discovery contains too many filesystem entries")
        retained: list[str] = []
        for name in sorted(names):
            child = base / name
            if child.is_symlink():
                invalid.append(
                    InvalidInput(
                        relative_path=child.relative_to(root).as_posix(),
                        category="symlink_rejected",
                        message="report discovery does not follow directory symlinks",
                    )
                )
            else:
                retained.append(name)
        names[:] = retained
        if "run_manifest.json" in files:
            candidates.append(base)
    valid: list[ValidatedRun] = []
    ordered_candidates = sorted(
        candidates,
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for plan_index, child in enumerate(ordered_candidates):
        relative = child.relative_to(root).as_posix()
        try:
            entry_names = {entry.name for entry in child.iterdir()}
            missing = sorted(_REQUIRED_CHILD_ENTRIES - entry_names)
            if missing:
                raise ConfigurationError("child run is incomplete: " + ", ".join(missing))
            for name in _REQUIRED_CHILD_FILES:
                entry = child / name
                if entry.is_symlink() or not entry.is_file():
                    raise ConfigurationError(f"required child artifact is not a file: {name}")
            for name in _REQUIRED_CHILD_DIRECTORIES:
                entry = child / name
                if entry.is_symlink() or not entry.is_dir():
                    raise ConfigurationError(f"required child artifact is not a directory: {name}")
            _assert_safe_child_tree(child)
            manifest = _bounded_json(child / "run_manifest.json", RunManifest)
            scorecard = _bounded_json(child / "scorecard.json", ScoreCard)
            _validate_cross_references(manifest, scorecard, None)
            valid.append(
                ValidatedRun(
                    plan_index=plan_index,
                    attempt=1,
                    relative_path=relative,
                    manifest=manifest,
                    scorecard=scorecard,
                )
            )
        except Exception as exc:
            invalid.append(
                InvalidInput(
                    relative_path=relative,
                    category="corrupt_artifact",
                    message=_bounded_message(str(exc)),
                    plan_index=plan_index,
                    attempt=1,
                )
            )
    input_identity = content_hash(
        [
            {
                "path": run.relative_path,
                "run_id": run.manifest.run_id,
                "task_hash": run.manifest.task_hash,
                "candidate_hash": run.manifest.candidate_hash,
            }
            for run in valid
        ]
    )
    return LoadedReportInputs(
        root=root,
        source_kind="runs_root",
        experiment_id=f"runs-root-{input_identity[:16]}",
        config_hash=None,
        plan_hash=None,
        task_set_hash=None,
        planned_count=len(candidates),
        plan_items=[],
        index_records=[],
        valid_runs=valid,
        invalid_inputs=invalid,
        requested_k=[1],
        samples_per_task=1,
    )


def _assert_safe_child_tree(root: Path) -> None:
    count = 0
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in [*names, *files]:
            count += 1
            if count > _MAX_CHILD_ENTRIES:
                raise ConfigurationError("child run contains too many filesystem entries")
            entry = base / name
            metadata = os.lstat(entry)
            if stat.S_ISLNK(metadata.st_mode):
                raise ConfigurationError(
                    f"child run contains a symlink: {entry.relative_to(root).as_posix()}"
                )
            if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                raise ConfigurationError(
                    f"child run contains a special file: {entry.relative_to(root).as_posix()}"
                )


def _invalid(
    relative: str,
    category: str,
    message: str,
    record: RunIndexRecord,
) -> InvalidInput:
    return InvalidInput(
        relative_path=relative,
        category=category,
        message=_bounded_message(message),
        plan_index=record.plan_index,
        attempt=record.attempt,
    )


def _bounded_message(value: str) -> str:
    clean = "".join(
        character if ord(character) >= 32 or character == "\t" else " " for character in value
    )
    return clean[:1024]


__all__ = [
    "LoadedReportInputs",
    "ValidatedRun",
    "load_report_inputs",
    "validate_plan_binding",
]
