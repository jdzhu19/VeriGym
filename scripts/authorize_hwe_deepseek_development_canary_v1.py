#!/usr/bin/env python3
"""Seal one execution authorization for the preregistered 32-step canary."""

from __future__ import annotations

import argparse
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_development_training import (
    create_development_training_execution_authorization,
    load_development_training_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def authorize(
    *,
    config: Path,
    preregistration_receipt: Path,
    dataset_root: Path,
    model_root: Path,
    repository_root: Path,
    qualification_root: Path,
    output: Path,
) -> dict[str, object]:
    """Persist one exclusive authorization after revalidating all frozen bytes."""

    if output.exists() or output.is_symlink():
        raise ValueError("development canary authorization must not already exist")
    preregistration = load_development_training_preregistration(config)
    authorization = create_development_training_execution_authorization(
        preregistration,
        config_path=config,
        preregistration_receipt_path=preregistration_receipt,
        dataset_root=dataset_root,
        model_root=model_root,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    payload = authorization.model_dump(mode="json")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_dump_json(output, payload)
    return payload


def main() -> None:
    arguments = _parser().parse_args()
    authorize(
        config=arguments.config,
        preregistration_receipt=arguments.preregistration_receipt,
        dataset_root=arguments.dataset_root,
        model_root=arguments.model_root,
        repository_root=arguments.repository_root,
        qualification_root=arguments.qualification_root,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
