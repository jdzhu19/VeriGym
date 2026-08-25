#!/usr/bin/env python3
"""Launch the frozen zero-step HWE 64K qualification under four torchrun ranks."""

from __future__ import annotations

import argparse
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rllm-source", type=Path, required=True)
    parser.add_argument("--verl-source", type=Path, required=True)
    parser.add_argument("--transformers-source", type=Path, required=True)
    parser.add_argument("--offload", action="store_true")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.report.exists() or arguments.report.is_symlink():
        raise ValueError("qualification report must not already exist")
    arguments.report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    from verigym_training_reference.hwe_decision_sft_64k_backend import (
        VeriGymHweDecisionSft64kTrainer,
        validate_qualification_runtime,
    )

    validate_qualification_runtime(
        rllm_source=arguments.rllm_source,
        verl_source=arguments.verl_source,
        transformers_source=arguments.transformers_source,
    )
    dispatcher = VeriGymHweDecisionSft64kTrainer(
        dataset_root=arguments.dataset_root,
        model_root=arguments.model_root,
        scratch_root=arguments.scratch_root,
        offload=arguments.offload,
    )
    dispatcher.launch_qualification(
        report=arguments.report,
        rllm_source=arguments.rllm_source,
        verl_source=arguments.verl_source,
        transformers_source=arguments.transformers_source,
    )


if __name__ == "__main__":
    main()
