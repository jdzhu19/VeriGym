"""Command-line entry point for the external training reference pipeline."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from verigym.core.errors import ConfigurationError
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.options import JsonValue

from .pipeline import (
    exclusion_counts,
    load_training_config,
    prepare_training_bundle,
    register_checkpoint,
    resolve_model_root,
    validate_training_bundle,
)
from .reward_oracle import TrainingRewardOracle
from .sft_exporter import export_verified_solution_sft

_MAX_CANDIDATE_BYTES = 4 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verigym-training-reference",
        description="Prepare, validate, score, and register external VeriGym training artifacts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="build a sealed trainer handoff")
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--model-root", type=Path)
    prepare.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="replay a trainer handoff offline")
    validate.add_argument("--bundle", type=Path, required=True)
    validate.add_argument("--dataset", type=Path, required=True)

    register = subparsers.add_parser(
        "register-checkpoint",
        help="hash an external checkpoint or adapter and write its VeriGym import manifest",
    )
    register.add_argument("--bundle", type=Path, required=True)
    register.add_argument("--dataset", type=Path, required=True)
    register.add_argument("--checkpoint", type=Path, required=True)
    register.add_argument("--output", type=Path, required=True)
    register.add_argument("--import-id", required=True)
    register.add_argument("--parent-version-hash", required=True)
    register.add_argument("--compatible-runtime-hash", required=True)
    register.add_argument("--license", required=True)
    register.add_argument("--provenance", required=True)
    register.add_argument(
        "--update-type",
        choices=("external_adapter", "external_checkpoint"),
        default="external_adapter",
    )
    register.add_argument("--format", default="safetensors")
    register.add_argument("--revision", required=True)

    score = subparsers.add_parser(
        "score",
        help="score one completion through the frozen training split",
    )
    score.add_argument("--bundle", type=Path, required=True)
    score.add_argument("--dataset", type=Path, required=True)
    score.add_argument("--task-id", required=True)
    score.add_argument("--candidate", type=Path, required=True)
    score.add_argument("--run-output", type=Path, required=True)
    score.add_argument("--result", type=Path, required=True)
    score.add_argument("--runtime", default="local")
    score.add_argument("--toolchain-profile")
    score.add_argument("--suite-source-root", type=Path)
    score.add_argument("--suite-variant")

    export_sft = subparsers.add_parser(
        "export-sft",
        help="export a verifier-filtered Codex solution sample as portable chat JSONL",
    )
    export_sft.add_argument("--sampling-root", type=Path, required=True)
    export_sft.add_argument("--output", type=Path, required=True)
    return parser


def _read_candidate(path: Path) -> str:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError("candidate input must be a regular file")
    if metadata.st_size <= 0 or metadata.st_size > _MAX_CANDIDATE_BYTES:
        raise ConfigurationError("candidate input is empty or oversized")
    try:
        payload = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigurationError("candidate input must be UTF-8 text") from exc
    if len(payload.encode("utf-8")) != metadata.st_size:
        raise ConfigurationError("candidate input changed while being read")
    return payload


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "prepare":
        config = load_training_config(arguments.config)
        manifest = prepare_training_bundle(
            arguments.dataset,
            arguments.output,
            config=config,
            model_root=resolve_model_root(config, arguments.model_root),
        )
        return {
            "status": "prepared",
            "manifest_hash": manifest.manifest_hash,
            "record_count": manifest.record_count,
            "training_task_ids": manifest.training_task_ids,
            "excluded_counts": exclusion_counts(manifest),
            "model_snapshot_hash": manifest.model_snapshot.snapshot_hash,
        }
    if arguments.command == "validate":
        manifest = validate_training_bundle(arguments.bundle, source_dataset=arguments.dataset)
        return {
            "status": "valid",
            "manifest_hash": manifest.manifest_hash,
            "record_count": manifest.record_count,
        }
    if arguments.command == "register-checkpoint":
        loading_configuration: dict[str, JsonValue] = {
            "format": arguments.format,
            "revision": arguments.revision,
        }
        imported = register_checkpoint(
            arguments.bundle,
            arguments.checkpoint,
            arguments.output,
            source_dataset=arguments.dataset,
            import_id=arguments.import_id,
            parent_version_hash=arguments.parent_version_hash,
            compatible_runtime_hash=arguments.compatible_runtime_hash,
            license=arguments.license,
            provenance=arguments.provenance,
            update_type=arguments.update_type,
            loading_configuration=loading_configuration,
        )
        return {
            "status": "registered",
            "import_id": imported.import_id,
            "manifest_hash": imported.manifest_hash,
            "artifact_hash": imported.artifact_hash,
        }
    if arguments.command == "score":
        oracle = TrainingRewardOracle(
            bundle=arguments.bundle,
            source_dataset=arguments.dataset,
            output_root=arguments.run_output,
            runtime=arguments.runtime,
            toolchain_profile=arguments.toolchain_profile,
            suite_source_root=arguments.suite_source_root,
            suite_variant=arguments.suite_variant,
        )
        result = oracle.score(arguments.task_id, _read_candidate(arguments.candidate))
        atomic_dump_json(arguments.result, result)
        return {
            "status": "scored",
            "task_id": result.task_id,
            "run_id": result.run_id,
            "outcome_kind": result.outcome_kind,
            "scalar_reward": result.scalar_reward,
            "infrastructure_valid": result.infrastructure_valid,
            "result_hash": result.result_hash,
        }
    if arguments.command == "export-sft":
        sft_manifest = export_verified_solution_sft(arguments.sampling_root, arguments.output)
        return {
            "status": "exported",
            "format_id": sft_manifest.format_id,
            "record_count": sft_manifest.record_count,
            "task_ids": sft_manifest.task_ids,
            "source_model_ids": sft_manifest.source_model_ids,
            "manifest_hash": sft_manifest.manifest_hash,
        }
    raise AssertionError(f"unhandled command: {arguments.command}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = _run(_parser().parse_args(argv))
    except (ConfigurationError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
