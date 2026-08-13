"""Fail-closed export of verified public tool transcripts for rLLM SFT."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.integrity import verify_artifact_manifest
from verigym.evolution.splits import validate_task_split
from verigym.evolution.training_transcript import validate_teacher_transcript
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl, atomic_write_text
from verigym.protocols.repository_action import repository_tool_definitions
from verigym.schemas.evolution import TaskSplitEntry, TaskSplitManifest
from verigym.schemas.multiturn_sft import (
    VerifiedMultiTurnSftDatasetManifest,
    VerifiedMultiTurnSftExample,
    seal_multi_turn_example,
)
from verigym.schemas.provenance import BuildProvenance
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard
from verigym.schemas.task import VeriTask

_MAX_JSON_BYTES = 32 * 1024 * 1024
_TOKENIZER_FILE_NAMES = {
    "added_tokens.json",
    "chat_template.jinja",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
    "vocab.json",
    "vocab.txt",
}


class ChatTemplateTokenizer(Protocol):
    def apply_chat_template(
        self,
        conversation: list[dict[str, Any]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> Any: ...

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


@dataclass(frozen=True)
class TranscriptRunBinding:
    transcript: Path
    run: Path


def bindings_from_cva6_collection(
    collection_root: Path, *, split_manifest_path: Path
) -> list[TranscriptRunBinding]:
    """Resolve the eight sealed relative paths written by the teacher campaign."""

    root = _safe_directory(collection_root, label="teacher collection")
    split = validate_task_split(TaskSplitManifest.model_validate(_json_object(split_manifest_path)))
    progress = _json_object(root / "collection-progress.json")
    receipt = _json_object(root / "successful-bindings.json")
    if (
        progress.get("format_id") != "verigym_cva6_teacher_collection_v1"
        or progress.get("status") != "completed"
        or progress.get("task_split_hash") != split.manifest_hash
        or receipt.get("format_id") != "verigym_cva6_teacher_bindings_v1"
        or receipt.get("task_split_hash") != split.manifest_hash
        or receipt.get("record_count") != 8
    ):
        raise ConfigurationError("CVA6 teacher collection is incomplete or has changed identity")
    for flag in (
        "private_reasoning_exported",
        "hidden_assets_exported",
        "reference_solutions_exported",
        "credential_values_exported",
    ):
        if receipt.get(flag) is not False:
            raise ConfigurationError(f"CVA6 teacher collection has an unsafe {flag} claim")
    raw_bindings = receipt.get("bindings")
    progress_successes = progress.get("successes")
    if not isinstance(raw_bindings, list) or len(raw_bindings) != 8:
        raise ConfigurationError("CVA6 teacher collection does not contain eight bindings")
    if raw_bindings != progress_successes:
        raise ConfigurationError("CVA6 teacher binding receipt differs from campaign progress")

    bindings: list[TranscriptRunBinding] = []
    for item in raw_bindings:
        if not isinstance(item, dict):
            raise ConfigurationError("CVA6 teacher binding is malformed")
        run = _relative_collection_path(root, item.get("run"), label="run")
        transcript = _relative_collection_path(root, item.get("transcript"), label="transcript")
        bindings.append(TranscriptRunBinding(transcript=transcript, run=run))
    return bindings


def export_verified_multiturn_sft(
    bindings: list[TranscriptRunBinding],
    *,
    split_manifest_path: Path,
    tokenizer: ChatTemplateTokenizer,
    tokenizer_root: Path,
    output: Path,
) -> VerifiedMultiTurnSftDatasetManifest:
    """Export only resolved training records; never truncate a trajectory."""

    if not bindings:
        raise ConfigurationError("multi-turn SFT export requires at least one binding")
    split = validate_task_split(TaskSplitManifest.model_validate(_json_object(split_manifest_path)))
    training = {entry.task_id: entry for entry in split.training}
    validation_ids = {entry.task_id for entry in split.validation}
    heldout_ids = {entry.task_id for entry in split.heldout}
    tokenizer_hash = _tokenizer_identity(tokenizer_root)
    tool_contract_hash = content_hash(repository_tool_definitions(dialect="openai"))
    examples: list[VerifiedMultiTurnSftExample] = []
    seen_tasks: set[str] = set()
    for binding in bindings:
        transcript = validate_teacher_transcript(_json_object(binding.transcript))
        task_id = transcript.get("task_id")
        if not isinstance(task_id, str):
            raise ConfigurationError("teacher transcript omits task_id")
        if task_id in validation_ids or task_id in heldout_ids or task_id not in training:
            raise ConfigurationError("teacher transcript is not in the frozen training split")
        if task_id in seen_tasks:
            raise ConfigurationError("multi-turn SFT accepts only one trajectory per task")
        seen_tasks.add(task_id)
        run, scorecard, task, provenance = _validated_run(binding.run, binding.transcript)
        entry = training[task_id]
        _validate_split_binding(entry, run, task)
        if task.id != task_id or run.task_id != task_id:
            raise ConfigurationError("teacher transcript and verified run task differ")
        messages = transcript["messages"]
        token_count = rllm_hf_template_token_count(tokenizer, messages)
        if token_count > 16_384:
            raise ConfigurationError(
                f"multi-turn trajectory {task_id} uses {token_count} tokens; "
                "truncation is forbidden"
            )
        official_task_id = task.metadata.get("official_task_id", task.id)
        if not isinstance(official_task_id, str) or not official_task_id:
            raise ConfigurationError("verified task has no official portable identity")
        payload = {
            "schema_version": "1.0",
            "format_id": "verigym_verified_multiturn_sft_v1",
            "sample_id": transcript["transcript_hash"],
            "task_id": task_id,
            "official_task_id": official_task_id,
            "task_hash": run.task_hash,
            "source_hash": run.source_hash,
            "candidate_hash": run.candidate_hash,
            "verifier_hash": scorecard.reproducibility.verifier_hash,
            "verigym_source_commit": provenance.source_commit,
            "verigym_source_tree_hash": provenance.source_tree_hash,
            "provider": transcript["provider"],
            "model_id": transcript["model_id"],
            "reasoning_effort": transcript["reasoning_effort"],
            "client_kind": transcript["client_kind"],
            "client_name": transcript["client_name"],
            "client_version": transcript["client_version"],
            "prompt_hash": transcript["prompt_hash"],
            "tool_contract_hash": transcript["tool_contract_hash"],
            "harness_hash": transcript["harness_hash"],
            "tokenizer_hash": tokenizer_hash,
            "split": "training",
            "messages": messages,
            "token_count": token_count,
            "max_length": 16_384,
            "truncation": "error",
            "supervised_roles": ["assistant"],
            "masked_roles": ["system", "user", "tool"],
            "verifier_resolved": True,
            "infrastructure_valid": True,
            "non_registry_tool_events_observed": False,
            "hidden_assets_exported": False,
            "reference_solutions_exported": False,
            "private_reasoning_exported": False,
            "credential_values_exported": False,
            "raw_host_paths_exported": False,
        }
        example = seal_multi_turn_example(payload)
        if example.tool_contract_hash != tool_contract_hash:
            raise ConfigurationError("teacher transcript uses a stale repository tool contract")
        examples.append(example)
    examples.sort(key=lambda example: example.task_id)
    destination = _new_directory(output)
    records = [example.model_dump(mode="json", exclude_none=True) for example in examples]
    atomic_dump_jsonl(destination / "train.jsonl", records)
    records_sha256 = hash_bytes((destination / "train.jsonl").read_bytes())
    manifest_base = {
        "schema_version": "1.0",
        "format_id": "verigym_verified_multiturn_sft_dataset_v1",
        "record_count": len(examples),
        "task_ids": [example.task_id for example in examples],
        "example_hashes": [example.example_hash for example in examples],
        "tokenizer_hash": tokenizer_hash,
        "tool_contract_hash": tool_contract_hash,
        "verigym_source_commits": sorted({example.verigym_source_commit for example in examples}),
        "verigym_source_tree_hashes": sorted(
            {example.verigym_source_tree_hash for example in examples}
        ),
        "records_sha256": records_sha256,
        "only_training_split": True,
        "only_resolved_samples": True,
        "infrastructure_invalid_excluded": True,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "private_reasoning_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    manifest = VerifiedMultiTurnSftDatasetManifest.model_validate(
        {**manifest_base, "manifest_hash": content_hash(manifest_base)}
    )
    atomic_dump_json(destination / "dataset-manifest.json", manifest)
    hashes = {
        name: hash_bytes((destination / name).read_bytes())
        for name in ("dataset-manifest.json", "train.jsonl")
    }
    atomic_write_text(
        destination / "SHA256SUMS",
        "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())),
    )
    return manifest


def rllm_hf_template_token_count(
    tokenizer: ChatTemplateTokenizer,
    messages: list[dict[str, Any]],
) -> int:
    """Match pinned rLLM's incremental ``hf_template`` tokenization exactly."""

    full = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    if not isinstance(full, str):
        raise ConfigurationError("tokenizer chat template did not return text")
    offsets = [0]
    for index in range(len(messages)):
        prefix = tokenizer.apply_chat_template(
            messages[: index + 1], tokenize=False, add_generation_prompt=False
        )
        if not isinstance(prefix, str) or not full.startswith(prefix):
            raise ConfigurationError("tokenizer chat template is not prefix-stable for rLLM")
        offsets.append(len(prefix))
    count = 0
    for index in range(len(messages)):
        count += len(
            tokenizer.encode(full[offsets[index] : offsets[index + 1]], add_special_tokens=False)
        )
    if count < 1:
        raise ConfigurationError("tokenizer produced an empty multi-turn trajectory")
    return count


def _validated_run(
    run_path: Path, transcript_path: Path
) -> tuple[RunManifest, ScoreCard, VeriTask, BuildProvenance]:
    run_root = _safe_directory(run_path, label="verified run")
    transcript = transcript_path.resolve(strict=True)
    if not transcript.is_relative_to(run_root):
        raise ConfigurationError("teacher transcript must be an integrity-bound run artifact")
    integrity = verify_artifact_manifest(run_root, expected_scope="run")
    if integrity.status != "verified":
        raise ConfigurationError("verified run artifact manifest is invalid")
    manifest = RunManifest.model_validate(_json_object(run_root / "run_manifest.json"))
    scorecard = ScoreCard.model_validate(_json_object(run_root / "scorecard.json"))
    task = VeriTask.model_validate(_json_object(run_root / "task_snapshot.json"))
    if not scorecard.resolved or scorecard.correctness.infrastructure_error:
        raise ConfigurationError("multi-turn SFT run is rejected or infrastructure-invalid")
    if manifest.candidate_hash is None:
        raise ConfigurationError("verified run omits its candidate identity")
    provenance = manifest.build_provenance
    if (
        provenance is None
        or provenance.dirty
        or provenance.source_commit is None
        or provenance.source_tree_hash is None
    ):
        raise ConfigurationError("verified run does not have clean source-code lineage")
    if (
        manifest.candidate_hash != scorecard.reproducibility.candidate_hash
        or manifest.verifier_hash != scorecard.reproducibility.verifier_hash
    ):
        raise ConfigurationError("verified run identities disagree")
    return manifest, scorecard, task, provenance


def _validate_split_binding(
    entry: TaskSplitEntry,
    run: RunManifest,
    task: VeriTask,
) -> None:
    if (
        entry.task_hash != run.task_hash
        or entry.source_hash != run.source_hash
        or run.task_hash != content_hash(task)
    ):
        raise ConfigurationError("verified run differs from the frozen training split")


def _tokenizer_identity(root: Path) -> str:
    directory = _safe_directory(root, label="tokenizer root")
    inventory: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if path.name not in _TOKENIZER_FILE_NAMES or not path.is_file():
            continue
        if path.is_symlink() or path.stat().st_size <= 0:
            raise ConfigurationError("tokenizer identity contains an unsafe file")
        inventory.append(
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": hash_bytes(path.read_bytes()),
            }
        )
    if not inventory or not any(item["name"] == "tokenizer_config.json" for item in inventory):
        raise ConfigurationError("tokenizer root lacks its local tokenizer identity")
    return content_hash(inventory)


def _json_object(path: Path) -> dict[str, Any]:
    try:
        metadata = os.lstat(path)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= _MAX_JSON_BYTES
        ):
            raise ConfigurationError(f"unsafe JSON input: {path.name}")
        value = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid JSON input: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"JSON input must be an object: {path.name}")
    return value


def _safe_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ConfigurationError(f"{label} cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"{label} does not exist") from exc
    if not resolved.is_dir():
        raise ConfigurationError(f"{label} must be a directory")
    return resolved


def _new_directory(path: Path) -> Path:
    if path.exists():
        if path.is_symlink() or not path.is_dir() or any(path.iterdir()):
            raise ConfigurationError("multi-turn SFT output must be a new or empty directory")
    else:
        path.mkdir(parents=True)
    return path.resolve(strict=True)


def _relative_collection_path(root: Path, raw: object, *, label: str) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ConfigurationError(f"CVA6 teacher {label} path is not relative")
    try:
        path = (root / raw).resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"CVA6 teacher {label} path does not exist") from exc
    if not path.is_relative_to(root):
        raise ConfigurationError(f"CVA6 teacher {label} path escapes the collection")
    return path


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


__all__ = [
    "TranscriptRunBinding",
    "bindings_from_cva6_collection",
    "export_verified_multiturn_sft",
    "rllm_hf_template_token_count",
]
