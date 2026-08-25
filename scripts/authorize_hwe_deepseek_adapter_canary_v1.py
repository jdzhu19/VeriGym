#!/usr/bin/env python3
"""Seal one adapter-retention and native-inference canary authorization."""

from __future__ import annotations

import argparse
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_adapter_canary import create_adapter_canary_authorization


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--predecessor-execution-report", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.output.exists() or arguments.output.is_symlink():
        raise SystemExit("adapter canary authorization output already exists")
    authorization = create_adapter_canary_authorization(
        config_path=arguments.config,
        preregistration_receipt_path=arguments.preregistration_receipt,
        predecessor_execution_report_path=arguments.predecessor_execution_report,
        dataset_root=arguments.dataset_root,
        model_root=arguments.model_root,
        repository_root=arguments.repository_root,
        qualification_root=arguments.qualification_root,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_dump_json(arguments.output, authorization.model_dump(mode="json"))


if __name__ == "__main__":
    main()
