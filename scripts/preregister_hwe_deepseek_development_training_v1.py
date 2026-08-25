#!/usr/bin/env python3
"""Seal the 64K development-training recipe and 32-step canary without running it."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from verigym.experiments.state import atomic_dump_json, atomic_write_text
from verigym.hwe.deepseek_harness_development_training import (
    load_development_training_preregistration,
    validate_development_training_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def preregister(
    *,
    config: Path,
    dataset_root: Path,
    model_root: Path,
    repository_root: Path,
    qualification_root: Path,
    output: Path,
) -> dict[str, object]:
    """Validate every frozen binding and persist an explicitly unauthorized receipt."""

    if output.exists() or output.is_symlink():
        raise ValueError("development-training preregistration output must not already exist")
    recipe = load_development_training_preregistration(config)
    receipt = validate_development_training_preregistration(
        recipe,
        config_path=config,
        dataset_root=dataset_root,
        model_root=model_root,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    config_text = config.read_text(encoding="utf-8")
    if hashlib.sha256(config_text.encode()).hexdigest() != receipt.config_sha256:
        raise ValueError("development-training config changed after validation")
    output.mkdir(parents=True, mode=0o700)
    atomic_write_text(output / "development-training-v1.json", config_text)
    atomic_dump_json(
        output / "canary-preregistration-receipt.json",
        receipt.model_dump(mode="json"),
    )
    return receipt.model_dump(mode="json")


def main() -> None:
    arguments = _parser().parse_args()
    preregister(
        config=arguments.config,
        dataset_root=arguments.dataset_root,
        model_root=arguments.model_root,
        repository_root=arguments.repository_root,
        qualification_root=arguments.qualification_root,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
