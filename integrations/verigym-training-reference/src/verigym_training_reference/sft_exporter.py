"""Fail-closed export of verified Codex solution samples to portable SFT JSONL."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.integrity import verify_artifact_manifest
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl, atomic_write_text
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard
from verigym.schemas.task import VeriTask

from .schemas import SftMessage, VerifiedSftDatasetManifest, VerifiedSftExample

_MAX_JSON_BYTES = 32 * 1024 * 1024
_MAX_CANDIDATE_BYTES = 4 * 1024 * 1024
_PRIVATE_KEY_PREAMBLE = b"-----BEGIN "
_FORBIDDEN_EXPORT_MARKERS = (
    _PRIVATE_KEY_PREAMBLE + b"PRIVATE KEY-----",
    _PRIVATE_KEY_PREAMBLE + b"RSA PRIVATE KEY-----",
    _PRIVATE_KEY_PREAMBLE + b"EC PRIVATE KEY-----",
    _PRIVATE_KEY_PREAMBLE + b"OPENSSH PRIVATE KEY-----",
    b"Bearer ",
    b"/data/",
    b"/home/",
    b"/tmp/",
    b"\\Users\\",
)
_FORBIDDEN_EXPORT_PATTERNS = (
    re.compile(rb"\b" + b"sk-" + rb"[A-Za-z0-9_-]{24,}\b"),
    re.compile(rb"://[^/@\s:]+:[^/@\s]+@"),
)


def _safe_directory(path: Path, *, label: str) -> Path:
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


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("SFT output must be a new or empty real directory")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _read_regular(path: Path, maximum: int) -> bytes:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"expected a regular file: {path.name}")
    if metadata.st_nlink != 1 or metadata.st_size <= 0 or metadata.st_size > maximum:
        raise ConfigurationError(f"unsafe or oversized input file: {path.name}")
    payload = path.read_bytes()
    if len(payload) != metadata.st_size:
        raise ConfigurationError(f"input changed while being read: {path.name}")
    return payload


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular(path, _MAX_JSON_BYTES))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid JSON input: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"JSON input must be an object: {path.name}")
    return value


def _record_hash(record: dict[str, Any], field: str) -> str:
    expected = record.get(field)
    if not isinstance(expected, str):
        raise ConfigurationError(f"record omits {field}")
    payload = dict(record)
    payload.pop(field)
    actual = content_hash(payload)
    if actual != expected:
        raise ConfigurationError(f"record identity differs: {field}")
    return actual


def _safe_run_path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw or raw.startswith(("/", "\\")):
        raise ConfigurationError("sampling summary has an unsafe run path")
    relative = Path(raw)
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ConfigurationError("sampling summary has an unsafe run path")
    resolved = (root / relative).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ConfigurationError("sampling run path escapes its root")
    return resolved


def _training_user_message(public_input: dict[str, Any]) -> str:
    return (
        "Implement the RTL task below. Return the complete source for "
        f"{public_input['candidate_path']} with no Markdown fences.\n\n"
        f"TASK DESCRIPTION\n{public_input['task_description']}\n\n"
        f"PUBLIC README\n{public_input['public_readme']}\n\n"
        "CURRENT INCOMPLETE CANDIDATE\n"
        f"{public_input['candidate_skeleton']}"
    )


def _reject_forbidden(payload: bytes, *, label: str) -> None:
    for marker in _FORBIDDEN_EXPORT_MARKERS:
        if marker in payload:
            raise ConfigurationError(f"SFT export contains a forbidden value in {label}")
    for pattern in _FORBIDDEN_EXPORT_PATTERNS:
        if pattern.search(payload):
            raise ConfigurationError(f"SFT export contains a credential pattern in {label}")


def export_verified_solution_sft(
    sampling_root: Path,
    output: Path,
) -> VerifiedSftDatasetManifest:
    """Export one verified solution sample without hidden verifier or reasoning content."""

    root = _safe_directory(sampling_root, label="sampling root")
    summary = _json_object(root / "sampling-summary.json")
    model_call = _json_object(root / "model-call.json")
    public_input = _json_object(root / "public-input.json")
    _record_hash(summary, "summary_hash")
    model_call_hash = _record_hash(model_call, "record_hash")
    public_input_hash = _record_hash(public_input, "record_hash")
    if summary.get("resolved") is not True or summary.get("infrastructure_invalid") is not False:
        raise ConfigurationError("only infrastructure-valid resolved samples are exportable")
    if summary.get("model_call_hash") != model_call_hash:
        raise ConfigurationError("sampling summary differs from the model call")
    if summary.get("public_input_hash") != public_input_hash:
        raise ConfigurationError("sampling summary differs from the public input")
    if public_input.get("hidden_assets_included") is not False:
        raise ConfigurationError("public model input may not include hidden assets")

    run_dir = _safe_run_path(root, summary.get("run_dir"))
    integrity = verify_artifact_manifest(run_dir, expected_scope="run")
    if integrity.status != "verified" or integrity.manifest_hash is None:
        raise ConfigurationError("sample run integrity is not verified")
    manifest = RunManifest.model_validate(_json_object(run_dir / "run_manifest.json"))
    scorecard = ScoreCard.model_validate(_json_object(run_dir / "scorecard.json"))
    task = VeriTask.model_validate(_json_object(run_dir / "task_snapshot.json"))
    if not scorecard.resolved or scorecard.correctness.infrastructure_error:
        raise ConfigurationError("sample scorecard is not a valid resolved outcome")
    if manifest.task_id != task.id or manifest.task_hash != content_hash(task):
        raise ConfigurationError("run and task identities differ")
    if summary.get("task_id") != task.id or summary.get("task_hash") != manifest.task_hash:
        raise ConfigurationError("sampling and run task identities differ")
    if summary.get("source_hash") != manifest.source_hash:
        raise ConfigurationError("sampling and run source identities differ")
    if summary.get("verigym_candidate_hash") != manifest.candidate_hash:
        raise ConfigurationError("sampling and run candidate identities differ")
    if manifest.candidate_hash != scorecard.reproducibility.candidate_hash:
        raise ConfigurationError("manifest and scorecard candidate identities differ")

    candidate_path = task.interaction.final_submission.path
    if candidate_path is None or public_input.get("candidate_path") != candidate_path:
        raise ConfigurationError("public input differs from the task submission path")
    candidate = _read_regular(run_dir / "candidate" / candidate_path, _MAX_CANDIDATE_BYTES)
    candidate_sha256 = hash_bytes(candidate)
    if summary.get("candidate_hash") != candidate_sha256:
        raise ConfigurationError("sampling and candidate file hashes differ")
    try:
        candidate_text = candidate.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigurationError("candidate must be UTF-8") from exc

    official_task_id = task.metadata.get("official_task_id", task.id)
    if not isinstance(official_task_id, str) or not official_task_id:
        raise ConfigurationError("task has no portable official identity")
    model_id = model_call.get("requested_model_id")
    effort = model_call.get("requested_reasoning_effort")
    if not isinstance(model_id, str) or effort not in {"xhigh", "max"}:
        raise ConfigurationError("model call identity is incomplete")
    messages = [
        SftMessage(
            role="system",
            content="You are a professional RTL designer. Produce complete, synthesizable RTL.",
        ),
        SftMessage(role="user", content=_training_user_message(public_input)),
        SftMessage(role="assistant", content=candidate_text),
    ]
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_verified_solution_sft_v1",
        "task_id": task.id,
        "official_task_id": official_task_id,
        "task_hash": manifest.task_hash,
        "source_hash": manifest.source_hash,
        "verifier_hash": manifest.verifier_hash,
        "candidate_path": candidate_path,
        "candidate_sha256": candidate_sha256,
        "verigym_candidate_hash": manifest.candidate_hash,
        "source_model_id": model_id,
        "source_reasoning_effort": effort,
        "model_call_hash": model_call_hash,
        "public_input_hash": public_input_hash,
        "messages": [message.model_dump(mode="json") for message in messages],
        "verifier_resolved": True,
        "infrastructure_valid": True,
        "hidden_assets_exported": False,
        "reference_solution_exported": False,
        "private_reasoning_exported": False,
    }
    example_hash = content_hash(base)
    example = VerifiedSftExample.model_validate(
        {**base, "sample_id": example_hash, "example_hash": example_hash}
    )
    destination = _new_directory(output)
    atomic_dump_jsonl(destination / "train.jsonl", [example])
    file_hashes = {"train.jsonl": hash_bytes((destination / "train.jsonl").read_bytes())}
    manifest_base = {
        "schema_version": "1.0",
        "format_id": "verigym_verified_solution_sft_dataset_v1",
        "record_count": 1,
        "task_ids": [task.id],
        "source_model_ids": [model_id],
        "source_reasoning_efforts": [effort],
        "example_hashes": [example_hash],
        "file_hashes": file_hashes,
        "only_resolved_samples": True,
        "infrastructure_invalid_excluded": True,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "private_reasoning_exported": False,
        "raw_host_paths_exported": False,
        "credential_values_exported": False,
    }
    dataset_manifest = VerifiedSftDatasetManifest.model_validate(
        {**manifest_base, "manifest_hash": content_hash(manifest_base)}
    )
    atomic_dump_json(destination / "dataset-manifest.json", dataset_manifest)
    file_hashes["dataset-manifest.json"] = hash_bytes(
        (destination / "dataset-manifest.json").read_bytes()
    )
    sums = "".join(f"{digest}  {name}\n" for name, digest in sorted(file_hashes.items()))
    atomic_write_text(destination / "SHA256SUMS", sums)
    for name in ("train.jsonl", "dataset-manifest.json", "SHA256SUMS"):
        _reject_forbidden((destination / name).read_bytes(), label=name)
    return dataset_manifest


__all__ = ["export_verified_solution_sft"]
