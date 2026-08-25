#!/usr/bin/env python3
"""Consume one authorization and execute the sealed adapter/inference canary."""

from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path

from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_adapter_canary import (
    load_adapter_canary_authorization,
    validate_adapter_canary_authorization,
)
from verigym.hwe.deepseek_harness_development_training import (
    load_development_training_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--predecessor-execution-report", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rllm-source", type=Path, required=True)
    parser.add_argument("--verl-source", type=Path, required=True)
    parser.add_argument("--transformers-source", type=Path, required=True)
    return parser


def _consume(path: Path, authorization_hash: str) -> None:
    marker = path.with_name("adapter-execution-started.json")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_adapter_canary_execution_start_v1",
        "status": "execution_started",
        "authorization_hash": authorization_hash,
        "single_use_authorization_consumed": True,
    }
    payload = (
        json.dumps({**base, "marker_hash": content_hash(base)}, indent=2, sort_keys=True).encode()
        + b"\n"
    )
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> None:
    arguments = _parser().parse_args()
    output_root = arguments.report.parent
    for output in (
        arguments.checkpoint_root,
        arguments.evidence_root,
        arguments.report,
        output_root / "lora_adapter",
    ):
        if output.exists() or output.is_symlink():
            raise SystemExit("adapter canary output already exists")
    if arguments.checkpoint_root.name != "temporary-fsdp2-checkpoints":
        raise SystemExit("adapter canary checkpoint basename changed")
    if (
        arguments.checkpoint_root.parent != output_root
        or arguments.evidence_root.parent != output_root
    ):
        raise SystemExit("adapter canary outputs must share one experiment root")
    if socket.gethostname().split(".", maxsplit=1)[0] != "gpu03":
        raise SystemExit("adapter canary is authorized only on gpu03")
    if os.environ.get("LSB_JOBID") != "466876":
        raise SystemExit("adapter canary requires existing LSF job 466876")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0,1,2,3":
        raise SystemExit("adapter canary requires physical GPUs 0,1,2,3")

    preregistration = load_development_training_preregistration(arguments.config)
    authorization = load_adapter_canary_authorization(arguments.authorization)
    validate_adapter_canary_authorization(
        authorization,
        config_path=arguments.config,
        preregistration_receipt_path=arguments.preregistration_receipt,
        predecessor_execution_report_path=arguments.predecessor_execution_report,
        dataset_root=arguments.dataset_root,
        model_root=arguments.model_root,
        repository_root=arguments.repository_root,
        qualification_root=arguments.qualification_root,
    )
    for source in (
        arguments.model_root,
        arguments.rllm_source,
        arguments.verl_source,
        arguments.transformers_source,
    ):
        if source.is_symlink() or not source.resolve(strict=True).is_dir():
            raise SystemExit("adapter canary source binding is unsafe")
    from verigym_training_reference.hwe_decision_sft_64k_backend import (
        validate_qualification_runtime,
    )

    validate_qualification_runtime(
        rllm_source=arguments.rllm_source,
        verl_source=arguments.verl_source,
        transformers_source=arguments.transformers_source,
    )
    output_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    _consume(arguments.authorization, authorization.authorization_hash)
    from verigym_training_reference.hwe_decision_sft_64k_adapter_canary import (
        VeriGymHweDecisionSft64kAdapterCanaryTrainer,
    )

    trainer = VeriGymHweDecisionSft64kAdapterCanaryTrainer(
        preregistration=preregistration,
        authorization=authorization,
        dataset_root=arguments.dataset_root,
        model_root=arguments.model_root,
        scratch_root=arguments.scratch_root,
        checkpoint_root=arguments.checkpoint_root,
        evidence_root=arguments.evidence_root,
        output_root=output_root,
    )
    trainer.launch(
        preregistration_path=arguments.config,
        authorization_path=arguments.authorization,
        report=arguments.report,
        rllm_source=arguments.rllm_source,
        verl_source=arguments.verl_source,
        transformers_source=arguments.transformers_source,
    )


if __name__ == "__main__":
    main()
