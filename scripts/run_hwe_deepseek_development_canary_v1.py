#!/usr/bin/env python3
"""Consume one authorization and run the sealed 32-step development canary."""

from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path

from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_development_training import (
    load_development_training_execution_authorization,
    load_development_training_preregistration,
    validate_development_training_execution_authorization,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
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


def _consume_authorization(path: Path, authorization_hash: str) -> Path:
    if path.name != "execution-authorization.json":
        raise ValueError("development canary authorization filename changed")
    marker = path.with_name("execution-started.json")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_development_canary_execution_start_v1",
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
    return marker


def run(
    *,
    config: Path,
    preregistration_receipt: Path,
    authorization_path: Path,
    dataset_root: Path,
    model_root: Path,
    repository_root: Path,
    qualification_root: Path,
    scratch_root: Path,
    checkpoint_root: Path,
    evidence_root: Path,
    report: Path,
    rllm_source: Path,
    verl_source: Path,
    transformers_source: Path,
) -> None:
    """Validate all bindings before importing the distributed GPU stack."""

    for output in (checkpoint_root, evidence_root, report):
        if output.exists() or output.is_symlink():
            raise ValueError("development canary output already exists")
    if checkpoint_root.name != "temporary-fsdp2-checkpoint":
        raise ValueError("development canary checkpoint basename changed")
    if checkpoint_root.parent != evidence_root.parent:
        raise ValueError("development canary checkpoint and evidence roots must share a parent")
    if socket.gethostname().split(".", maxsplit=1)[0] != "gpu03":
        raise RuntimeError("development canary is authorized only on gpu03")
    if os.environ.get("LSB_JOBID") != "466876":
        raise RuntimeError("development canary requires existing LSF job 466876")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0,1,2,3":
        raise RuntimeError("development canary requires physical GPUs 0,1,2,3")

    preregistration = load_development_training_preregistration(config)
    authorization = load_development_training_execution_authorization(authorization_path)
    validate_development_training_execution_authorization(
        authorization,
        preregistration=preregistration,
        config_path=config,
        preregistration_receipt_path=preregistration_receipt,
        dataset_root=dataset_root,
        model_root=model_root,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    for source in (model_root, rllm_source, verl_source, transformers_source):
        if source.is_symlink() or not source.resolve(strict=True).is_dir():
            raise ValueError("development canary source bindings must be real directories")

    from verigym_training_reference.hwe_decision_sft_64k_backend import (
        validate_qualification_runtime,
    )

    validate_qualification_runtime(
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _consume_authorization(authorization_path, authorization.authorization_hash)

    from verigym_training_reference.hwe_decision_sft_64k_development_canary import (
        VeriGymHweDecisionSft64kDevelopmentCanaryTrainer,
    )

    trainer = VeriGymHweDecisionSft64kDevelopmentCanaryTrainer(
        preregistration=preregistration,
        authorization=authorization,
        dataset_root=dataset_root,
        model_root=model_root,
        scratch_root=scratch_root,
        checkpoint_root=checkpoint_root,
        evidence_root=evidence_root,
    )
    trainer.launch(
        preregistration_path=config,
        authorization_path=authorization_path,
        report=report,
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )


def main() -> None:
    arguments = _parser().parse_args()
    run(
        config=arguments.config,
        preregistration_receipt=arguments.preregistration_receipt,
        authorization_path=arguments.authorization,
        dataset_root=arguments.dataset_root,
        model_root=arguments.model_root,
        repository_root=arguments.repository_root,
        qualification_root=arguments.qualification_root,
        scratch_root=arguments.scratch_root,
        checkpoint_root=arguments.checkpoint_root,
        evidence_root=arguments.evidence_root,
        report=arguments.report,
        rllm_source=arguments.rllm_source,
        verl_source=arguments.verl_source,
        transformers_source=arguments.transformers_source,
    )


if __name__ == "__main__":
    main()
