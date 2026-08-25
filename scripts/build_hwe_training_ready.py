#!/usr/bin/env python3
"""Build the frozen HWE Complexity-Trap and CoACT training-ready handoff.

This command performs local inference only.  It writes a new experiment directory atomically and
fails closed if either route cannot satisfy its NAP or length contract.  It never starts an SFT,
GPU training, held-out evaluation, or HPC job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl
from verigym.hwe.coact import (
    build_coact_checkpoint_lock,
    build_coact_dataset_manifest,
    compress_hwe_trajectory,
    seal_coact_example,
)
from verigym.hwe.local_models import (
    AdaptiveLocalQwenActionPredictor,
    LocalCoactGenerator,
    LocalQwenActionPredictor,
    ParallelLocalQwenActionPredictor,
    SubprocessLocalQwenActionPredictor,
)
from verigym.hwe.nap import AnchorNapValidator, canonical_action_hash
from verigym.hwe.observation import TiktokenO200kCounter
from verigym.hwe.training import (
    HweTrainingInputs,
    build_dual_route_handoff,
    build_single_route_handoff,
    dry_run_trainer_inputs,
    load_coact_dataset,
    load_training_ready_action_conditioned_dataset,
)
from verigym.hwe.training_ready import (
    build_training_ready_action_conditioned_examples,
    build_training_ready_action_conditioned_manifest,
    freeze_old_jsonl_identity,
    load_jsonl_records,
    old_action_conditioned_identity,
)
from verigym.hwe.trajectory import validate_hwe_teacher_transcript

DEFAULT_SOURCE_ROOT = Path(
    "/data/jzhu484/Agent/experiments/"
    "cva6-hwe-codex-native-shell-v2/campaign-action-conditioned-m1p1-v9-lifecycle2-1"
)
DEFAULT_BASE_MODEL = Path("/data/jzhu484/Agent/datasets/Qwen3.5-9B")
DEFAULT_COACT_CHECKPOINT = Path(
    "/data/jzhu484/Agent/datasets/CoACT-1b2d660dfa5fccf80a5e3c508a9f0d3c1930ccf5"
)
DEFAULT_OUTPUT = Path(
    "/data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-dual-route-v1"
)


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = _build(arguments)
    except KeyboardInterrupt as exc:
        failure = KeyboardInterrupt(str(exc) or "bounded local inference interrupted")
        _write_failure(arguments.output, arguments.source_root, failure)
        print(
            json.dumps(
                {
                    "training_ready": False,
                    "hpc_jobs_submitted": False,
                    "error_type": type(failure).__name__,
                    "error": str(failure),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        _write_failure(arguments.output, arguments.source_root, exc)
        print(
            json.dumps(
                {
                    "training_ready": False,
                    "hpc_jobs_submitted": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--coact-checkpoint", type=Path, default=DEFAULT_COACT_CHECKPOINT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--nap-device", default="cuda:0")
    parser.add_argument(
        "--nap-devices",
        default=None,
        help="comma-separated devices for parallel frozen Qwen NAP replicas",
    )
    parser.add_argument("--coact-device", default="cuda:1")
    parser.add_argument(
        "--complexity-only",
        action="store_true",
        help="build and validate the independent Complexity-Trap arm without CoACT inference",
    )
    return parser


def _build(arguments: argparse.Namespace) -> dict[str, Any]:
    source_root = _regular_directory(arguments.source_root, "source root")
    base_model = _regular_directory(arguments.base_model, "base model")
    coact_checkpoint: Path | None = None
    if not arguments.complexity_only:
        coact_checkpoint = _regular_directory(arguments.coact_checkpoint, "CoACT checkpoint")
    output = _prepare_output(arguments.output)
    print("phase=freeze_source", file=sys.stderr, flush=True)
    old_records_path = source_root / "hwe-action-conditioned-sft.jsonl"
    old_manifest_path = source_root / "action-conditioned-dataset-manifest.json"
    old_records = load_jsonl_records(old_records_path)
    old_manifest = _read_json(old_manifest_path)
    old_identity = freeze_old_jsonl_identity(old_records_path, old_manifest)
    if old_identity != {
        **old_action_conditioned_identity(old_records, old_manifest),
        "jsonl_sha256": old_identity["jsonl_sha256"],
    }:
        raise ValueError("historical action-conditioned identity changed during the freeze")
    transcripts = _load_transcripts(source_root)
    _validate_source_set(transcripts, old_manifest)
    atomic_dump_json(output / "old-source-identity.json", old_identity)
    atomic_dump_json(output / "source-transcript-lock.json", _transcript_lock(transcripts))

    if coact_checkpoint is not None:
        checkpoint_lock = build_coact_checkpoint_lock(coact_checkpoint)
        atomic_dump_json(output / "coact-checkpoint-lock.json", checkpoint_lock)

    counter = TiktokenO200kCounter()
    print("phase=hash_models", file=sys.stderr, flush=True)
    base_snapshot, tokenizer_hash = _model_inventory(base_model)
    atomic_dump_json(
        output / "base-model-lock.json",
        {
            "model_id": "Qwen3.5-9B",
            "path": str(base_model),
            "snapshot_hash": base_snapshot,
            "tokenizer_hash": tokenizer_hash,
            "remote_code": False,
        },
    )

    nap_devices = _parse_devices(arguments.nap_devices)
    nap_predictor: (
        LocalQwenActionPredictor
        | ParallelLocalQwenActionPredictor
        | AdaptiveLocalQwenActionPredictor
        | SubprocessLocalQwenActionPredictor
    )
    if nap_devices:
        if len(nap_devices) == 1 and "+" in nap_devices[0]:
            # A caller may request a long-context-only run explicitly.  Keep the balanced model
            # in a fresh subprocess even when no adaptive replica switch is needed; the direct
            # in-process path is retained only for bounded diagnostics and has a known CUDA
            # synchronization hazard after a replica workload.
            nap_predictor = SubprocessLocalQwenActionPredictor(base_model, device=nap_devices[0])
        elif len(nap_devices) >= 2 and all("+" not in device for device in nap_devices):
            nap_predictor = AdaptiveLocalQwenActionPredictor(
                base_model, replica_devices=nap_devices
            )
        else:
            nap_predictor = ParallelLocalQwenActionPredictor(base_model, devices=nap_devices)
    else:
        nap_predictor = LocalQwenActionPredictor(base_model, device=arguments.nap_device)
    nap_validator = AnchorNapValidator(nap_predictor)
    complexity_root = output / "complexity-trap"
    complexity_root.mkdir()
    complexity_rows: list[dict[str, Any]] = []
    complexity_quality: dict[str, Any]
    complexity_failure: str | None = None
    try:
        complexity_rows, complexity_quality = build_training_ready_action_conditioned_examples(
            old_records,
            transcripts=transcripts,
            nap_validator=nap_validator,
            counter=counter,
            progress=_progress_report("complexity_nap"),
        )
        complexity_quality = _add_old_identity(complexity_quality, old_identity)
        complexity_manifest = build_training_ready_action_conditioned_manifest(
            complexity_rows,
            old_dataset_hash=str(old_manifest["dataset_hash"]),
            old_record_hashes=old_identity["record_hashes"],
            quality=complexity_quality,
        )
        atomic_dump_jsonl(complexity_root / "train.jsonl", complexity_rows)
        atomic_dump_json(complexity_root / "dataset-manifest.json", complexity_manifest)
    except ValueError as exc:
        complexity_failure = str(exc)
        complexity_quality = _blocked_quality(
            "verigym_hwe_training_ready_action_conditioned_quality_v1",
            record_count=0,
            failure=complexity_failure,
        )
        print(f"phase=complexity_nap blocked={complexity_failure}", file=sys.stderr, flush=True)
    finally:
        _close_predictor(nap_predictor)
    atomic_dump_json(complexity_root / "quality-manifest.json", complexity_quality)

    coact_root = output / "coact"
    coact_root.mkdir()
    coact_examples: list[dict[str, Any]] = []
    coact_quality: list[dict[str, Any]] = []
    coact_quality_payload: dict[str, Any]
    coact_manifest: dict[str, Any] | None = None
    coact_failure: str | None = None
    if arguments.complexity_only:
        coact_failure = "skipped_by_complexity_only"
        coact_quality_payload = _blocked_quality(
            "verigym_hwe_coact_multiturn_quality_v1",
            record_count=0,
            failure=coact_failure,
        )
        print("phase=coact_compression skipped=complexity_only", file=sys.stderr, flush=True)
    else:
        assert coact_checkpoint is not None
        try:
            coact_generator = LocalCoactGenerator(coact_checkpoint, device=arguments.coact_device)
            for task_id in sorted(transcripts):
                transcript = transcripts[task_id]
                compressed_messages, compression_manifest = compress_hwe_trajectory(
                    transcript,
                    task_goal=_public_task_goal(transcript),
                    counter=counter,
                    generator=coact_generator,
                    nap_validator=nap_validator,
                )
                token_count = _message_tokens(compressed_messages, counter)
                if token_count > 65_536:
                    raise ValueError(f"CoACT trajectory {task_id} exceeds 65,536 tokens")
                example = seal_coact_example(
                    transcript,
                    compressed_messages=compressed_messages,
                    compression_manifest=compression_manifest,
                    binding=_binding_for_task(old_records, task_id),
                    token_count=token_count,
                )
                coact_examples.append(example)
                coact_quality.append(
                    {
                        "task_id": task_id,
                        "source_tokens": _message_tokens(transcript["sft_messages"], counter),
                        "compressed_tokens": token_count,
                        "compression_manifest_hash": compression_manifest["manifest_hash"],
                        "changed_observation_count": sum(
                            entry["changed"] for entry in compression_manifest["entries"]
                        ),
                        "fallback_count": sum(
                            entry["fallback"] for entry in compression_manifest["entries"]
                        ),
                    }
                )
                print(
                    f"phase=coact_compression completed={len(coact_examples)}/8",
                    file=sys.stderr,
                    flush=True,
                )
            coact_examples.sort(key=lambda item: str(item["task_id"]))
            coact_manifest = build_coact_dataset_manifest(coact_examples)
            _validate_historical_action_set(coact_manifest, old_records)
            atomic_dump_jsonl(coact_root / "train.jsonl", coact_examples)
            atomic_dump_json(coact_root / "dataset-manifest.json", coact_manifest)
            coact_quality_payload = {
                "format_id": "verigym_hwe_coact_multiturn_quality_v1",
                "trajectory_count": len(coact_quality),
                "trajectories": sorted(coact_quality, key=lambda item: item["task_id"]),
                "max_token_count": coact_manifest["max_token_count"],
                "all_within_64k": coact_manifest["max_token_count"] <= 65_536,
                "all_truncation_error": True,
                "historical_action_set_match": True,
                "training_ready": True,
                "hpc_jobs_submitted": False,
            }
        except ValueError as exc:
            coact_failure = str(exc)
            coact_quality_payload = _blocked_quality(
                "verigym_hwe_coact_multiturn_quality_v1",
                record_count=len(coact_examples),
                failure=coact_failure,
            )
            print(f"phase=coact_compression blocked={coact_failure}", file=sys.stderr, flush=True)

    dry_runs: dict[str, Any] = {}
    complexity_inputs: HweTrainingInputs | None = None
    coact_inputs: HweTrainingInputs | None = None
    if complexity_failure is None:
        complexity_inputs = load_training_ready_action_conditioned_dataset(complexity_root)
        dry_runs["complexity_trap"] = dry_run_trainer_inputs(
            complexity_inputs, token_counter=counter
        )
    if coact_failure is None:
        coact_inputs = load_coact_dataset(coact_root)
        dry_runs["coact"] = dry_run_trainer_inputs(coact_inputs, token_counter=counter)
    dual_ready = complexity_failure is None and coact_failure is None
    complexity_ready = complexity_failure is None
    coact_ready = coact_failure is None
    if dual_ready:
        assert complexity_inputs is not None and coact_inputs is not None
        handoff = build_dual_route_handoff(
            complexity_inputs,
            coact_inputs,
            base_model_hash=str(base_snapshot),
            tokenizer_hash=tokenizer_hash,
            dry_runs=dry_runs,
        )
    elif complexity_inputs is not None:
        handoff = build_single_route_handoff(
            complexity_inputs,
            base_model_hash=str(base_snapshot),
            tokenizer_hash=tokenizer_hash,
            dry_run=dry_runs["complexity_trap"],
            other_route_failure=coact_failure,
        )
    elif coact_inputs is not None:
        handoff = build_single_route_handoff(
            coact_inputs,
            base_model_hash=str(base_snapshot),
            tokenizer_hash=tokenizer_hash,
            dry_run=dry_runs["coact"],
            other_route_failure=complexity_failure,
        )
    else:
        handoff = _blocked_handoff(
            base_snapshot=str(base_snapshot),
            tokenizer_hash=tokenizer_hash,
            complexity_failure=complexity_failure,
            coact_failure=coact_failure,
            dry_runs=dry_runs,
        )
    coact_quality_payload = _reseal_quality(coact_quality_payload, coact_ready, dual_ready)
    complexity_quality = _reseal_quality(complexity_quality, complexity_ready, dual_ready)
    atomic_dump_json(complexity_root / "quality-manifest.json", complexity_quality)
    atomic_dump_json(coact_root / "quality-manifest.json", coact_quality_payload)
    atomic_dump_json(
        output / "trainer-dry-run.json",
        {name: run.as_dict() for name, run in dry_runs.items()},
    )
    atomic_dump_json(output / "training-handoff.json", handoff)
    status = {
        "format_id": "verigym_hwe_dual_route_training_ready_status_v1",
        "training_ready": dual_ready,
        "complexity_training_ready": complexity_ready,
        "coact_training_ready": coact_ready,
        "complexity_dataset_ready": complexity_ready,
        "coact_dataset_ready": coact_ready,
        "complexity_only": bool(arguments.complexity_only),
        "complexity_failure": complexity_failure,
        "coact_failure": coact_failure,
        "trajectory_count": 8,
        "complexity_record_count": len(complexity_rows),
        "coact_record_count": len(coact_examples),
        "complexity_max_tokens": max(
            (item["token_count"] for item in complexity_rows), default=None
        ),
        "coact_max_tokens": coact_manifest["max_token_count"] if coact_manifest else None,
        "hpc_jobs_submitted": False,
        "training_started": False,
        "heldout_evaluation_started": False,
        "status_hash": "",
    }
    status["status_hash"] = content_hash(
        {key: value for key, value in status.items() if key != "status_hash"}
    )
    atomic_dump_json(output / "run-status.json", status)
    return status


def _prepare_output(path: Path) -> Path:
    if path.exists():
        raise ValueError(f"refusing to overwrite existing output directory: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    return path


def _close_predictor(predictor: object) -> None:
    close = getattr(predictor, "close", None)
    if callable(close):
        close()


def _write_failure(path: Path, source_root: Path, error: BaseException) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()
    elif not path.is_dir():
        return
    status = {
        "format_id": "verigym_hwe_dual_route_training_ready_status_v1",
        "training_ready": False,
        "complexity_training_ready": False,
        "coact_training_ready": False,
        "hpc_jobs_submitted": False,
        "training_started": False,
        "heldout_evaluation_started": False,
        "source_root": str(source_root),
        "failure_type": type(error).__name__,
        "failure": str(error),
    }
    status["status_hash"] = content_hash(status)
    atomic_dump_json(path / "run-status.json", status)


def _load_transcripts(root: Path) -> dict[str, dict[str, Any]]:
    transcripts: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("runs/*/artifacts/codex_cli/hwe_teacher_transcript.json")):
        value = _read_json(path)
        validated = validate_hwe_teacher_transcript(value)
        task_id = validated.get("task_id")
        if not isinstance(task_id, str) or task_id in transcripts:
            raise ValueError("source transcripts do not contain eight unique task IDs")
        transcripts[task_id] = validated
    if len(transcripts) != 8:
        raise ValueError("source HWE experiment must contain exactly eight transcripts")
    return transcripts


def _validate_source_set(
    transcripts: Mapping[str, Mapping[str, Any]], manifest: Mapping[str, Any]
) -> None:
    task_ids = manifest.get("task_ids")
    source_hashes = manifest.get("source_transcript_hashes")
    if sorted(transcripts) != task_ids or not isinstance(source_hashes, list):
        raise ValueError("source transcript task set differs from historical manifest")
    observed = sorted(str(value["transcript_hash"]) for value in transcripts.values())
    if observed != sorted(str(item) for item in source_hashes):
        raise ValueError("source transcript hashes differ from historical manifest")


def _transcript_lock(transcripts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "task_id": task_id,
            "transcript_hash": value["transcript_hash"],
            "sft_tokens": value["metrics"]["sft_total_tokens"],
            "sft_bucket": value["sft_bucket"],
            "primary_eligible": value["primary_eligible"],
        }
        for task_id, value in sorted(transcripts.items())
    ]
    return {
        "format_id": "verigym_hwe_source_transcript_lock_v1",
        "trajectory_count": len(rows),
        "transcripts": rows,
        "lock_hash": content_hash(rows),
    }


def _binding_for_task(records: Iterable[Mapping[str, Any]], task_id: str) -> dict[str, Any]:
    matches = [record for record in records if record.get("task_id") == task_id]
    if not matches:
        raise ValueError(f"historical action records omit {task_id}")
    row = matches[0]
    return {
        "sample_id": row["trajectory_sample_id"],
        "task_hash": row["task_hash"],
        "source_hash": row["source_hash"],
        "candidate_hash": row["candidate_hash"],
        "verifier_hash": row["verifier_hash"],
    }


def _public_task_goal(transcript: Mapping[str, Any]) -> str:
    messages = transcript.get("sft_messages")
    if not isinstance(messages, list):
        raise ValueError("source transcript lacks public SFT messages")
    for message in messages:
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return cast(str, message["content"])
    raise ValueError("source transcript lacks a public task goal")


def _model_inventory(root: Path) -> tuple[str, str]:
    files = _inventory(root)
    snapshot_hash = content_hash(files)
    tokenizer_names = {
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
        "special_tokens_map.json",
        "preprocessor_config.json",
    }
    tokenizer_files = [item for item in files if Path(str(item["path"])).name in tokenizer_names]
    if not tokenizer_files:
        raise ValueError("base model has no local tokenizer files")
    return snapshot_hash, content_hash(tokenizer_files)


def _parse_devices(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    devices = tuple(item.strip() for item in value.split(",") if item.strip())
    if not devices:
        raise ValueError("--nap-devices must contain at least one device")
    if len(set(devices)) != len(devices):
        raise ValueError("--nap-devices must contain distinct devices")
    return devices


def _progress_report(phase: str) -> Callable[[int, int], None]:
    def report(completed: int, total: int) -> None:
        if completed == 1 or completed == total or completed % 10 == 0:
            print(
                f"phase={phase} completed={completed}/{total}",
                file=sys.stderr,
                flush=True,
            )

    return report


def _blocked_quality(format_id: str, *, record_count: int, failure: str) -> dict[str, Any]:
    base = {
        "format_id": format_id,
        "record_count": record_count,
        "trajectory_count": 8,
        "training_ready": False,
        "dataset_ready": False,
        "dual_handoff_ready": False,
        "failure": failure,
        "hpc_jobs_submitted": False,
    }
    return {**base, "quality_hash": content_hash(base)}


def _reseal_quality(
    quality: Mapping[str, Any], route_ready: bool, dual_ready: bool
) -> dict[str, Any]:
    base = dict(quality)
    base.pop("quality_hash", None)
    dataset_ready = "failure" not in base
    base["dataset_ready"] = dataset_ready
    base["route_handoff_ready"] = route_ready
    base["dual_handoff_ready"] = dual_ready
    base["training_ready"] = dataset_ready and route_ready
    return {**base, "quality_hash": content_hash(base)}


def _blocked_handoff(
    *,
    base_snapshot: str,
    tokenizer_hash: str,
    complexity_failure: str | None,
    coact_failure: str | None,
    dry_runs: Mapping[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_dual_route_training_ready_handoff_v1",
        "model": {
            "id": "Qwen3.5-9B",
            "path": "/data/jzhu484/Agent/datasets/Qwen3.5-9B",
            "snapshot_hash": base_snapshot,
        },
        "tokenizer_hash": tokenizer_hash,
        "routes": {
            "complexity_trap": {
                "dataset_ready": complexity_failure is None,
                "failure": complexity_failure,
            },
            "coact": {"dataset_ready": coact_failure is None, "failure": coact_failure},
        },
        "trainer_dry_runs": {
            name: value.as_dict() if hasattr(value, "as_dict") else value
            for name, value in dry_runs.items()
        },
        "training_ready": False,
        "training_config_enabled": True,
        "training_started": False,
        "hpc_jobs_submitted": False,
        "heldout_evaluation_started": False,
    }
    return {**base, "handoff_hash": content_hash(base)}


def _validate_historical_action_set(
    coact_manifest: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> None:
    historical = [
        canonical_action_hash(
            {
                "name": record["target_action"],
                "arguments": record["messages"][-1]["tool_calls"][0]["function"]["arguments"],
            }
        )
        for record in records
    ]
    observed = coact_manifest.get("canonical_action_hashes")
    if not isinstance(observed, list) or sorted(observed) != sorted(historical):
        raise ValueError("CoACT canonical action multiset differs from historical 419 actions")


def _inventory(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"model artifact contains a symlink: {path.name}")
        if not path.is_file():
            continue
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    if not entries:
        raise ValueError("model artifact directory is empty")
    return entries


def _message_tokens(messages: Sequence[Mapping[str, Any]], counter: TiktokenO200kCounter) -> int:
    serialized = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return counter.count(serialized)


def _add_old_identity(quality: Mapping[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    base = {
        **dict(quality),
        "old_dataset_hash": identity["dataset_hash"],
        "old_jsonl_sha256": identity["jsonl_sha256"],
    }
    base.pop("quality_hash", None)
    return {**base, "quality_hash": content_hash(base)}


def _read_json(path: Path) -> dict[str, Any]:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"input is not a regular file: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"input is not a JSON object: {path.name}")
    return value


def _regular_directory(path: Path, label: str) -> Path:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a non-symlink directory")
    return path.resolve(strict=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
