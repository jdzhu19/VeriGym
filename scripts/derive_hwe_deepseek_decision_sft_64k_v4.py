#!/usr/bin/env python3
"""Derive the frozen DeepSeek Harness v3 pilot into an exact-token 64K v4 dataset."""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json, atomic_dump_jsonl
from verigym.hwe.deepseek_harness_sft_64k import (
    derive_decision_dataset_64k_v4,
    load_frozen_decision_dataset_v3,
)
from verigym.hwe.qwen_action_tokenizer import QwenDecisionExampleTokenizer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-v3-dataset", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def derive(*, source_v3_dataset: Path, tokenizer_root: Path, output: Path) -> dict[str, Any]:
    """Perform an offline derivation and persist only the new v4 directory."""

    if output.exists() or output.is_symlink():
        raise ValueError("v4 output must not already exist")
    source = load_frozen_decision_dataset_v3(source_v3_dataset)
    tokenizer_directory = tokenizer_root.resolve(strict=True)
    if tokenizer_root.is_symlink() or not tokenizer_directory.is_dir():
        raise ValueError("Qwen tokenizer root must be a non-symlink directory")

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_directory,
        local_files_only=True,
        trust_remote_code=False,
    )
    exact_tokenizer = QwenDecisionExampleTokenizer(
        tokenizer,
        tokenizer_root=tokenizer_directory,
    )
    derived = derive_decision_dataset_64k_v4(source, tokenizer=exact_tokenizer)

    output.mkdir(parents=True, mode=0o700)
    dataset_root = output / "dataset"
    dataset_root.mkdir(mode=0o700)
    atomic_dump_json(dataset_root / "dataset-manifest.json", derived.manifest)
    atomic_dump_jsonl(dataset_root / "train.jsonl", derived.rows)
    atomic_dump_json(
        dataset_root / "loader-dry-run.json",
        {
            "schema_version": "1.0",
            "format_id": "verigym_hwe_deepseek_harness_qwen_loader_dry_run_64k_v4",
            "record_count": len(derived.dry_runs),
            "tokenizer_hash": exact_tokenizer.tokenizer_hash,
            "chat_template_hash": exact_tokenizer.chat_template_hash,
            "max_token_count": max(item["token_count"] for item in derived.dry_runs),
            "over_32768_count": sum(item["token_count"] > 32_768 for item in derived.dry_runs),
            "over_65536_count": sum(item["overlength"] for item in derived.dry_runs),
            "truncation_applied": False,
            "records": list(derived.dry_runs),
        },
    )

    source_after = load_frozen_decision_dataset_v3(source_v3_dataset)
    source_actions = Counter(action for row in source.rows for action in row["action_names"])
    derived_actions = Counter(action for row in derived.rows for action in row["action_names"])
    if source_actions != derived_actions:
        raise ValueError("v4 action multiset differs from v3")
    report_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_deepseek_harness_decision_sft_64k_v4_derivation_report",
        "status": "completed",
        "source_v3_dataset_hash": source.manifest.dataset_hash,
        "source_v3_manifest_sha256_before": source.manifest_sha256,
        "source_v3_manifest_sha256_after": source_after.manifest_sha256,
        "source_v3_train_jsonl_sha256_before": source.train_jsonl_sha256,
        "source_v3_train_jsonl_sha256_after": source_after.train_jsonl_sha256,
        "source_v3_record_hashes_unchanged": (
            source.manifest.record_hashes == source_after.manifest.record_hashes
        ),
        "tools_messages_targets_unchanged": True,
        "record_order_unchanged": True,
        "action_multiset_unchanged": True,
        "record_count": len(derived.rows),
        "trajectory_count": derived.manifest.trajectory_count,
        "tool_action_count": derived.manifest.supervised_tool_action_count,
        "max_token_count": derived.manifest.max_observed_token_count,
        "over_32768_count": sum(row["token_count"] > 32_768 for row in derived.rows),
        "over_65536_count": 0,
        "max_length": 65_536,
        "truncation": "error",
        "nap_required": False,
        "nap_pass_claimed": False,
        "loader_ready": True,
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "adapter_written": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
        "v4_dataset_hash": derived.manifest.dataset_hash,
        "v4_train_jsonl_sha256": hashlib.sha256(
            (dataset_root / "train.jsonl").read_bytes()
        ).hexdigest(),
    }
    report = {**report_base, "report_hash": content_hash(report_base)}
    atomic_dump_json(output / "derivation-report.json", report)
    return report


def main() -> None:
    arguments = _parser().parse_args()
    derive(
        source_v3_dataset=arguments.source_v3_dataset,
        tokenizer_root=arguments.tokenizer_root,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
