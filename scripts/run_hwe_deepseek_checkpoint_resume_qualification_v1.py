#!/usr/bin/env python3
"""Consume attempt 8 and launch the sealed checkpoint/resume qualification."""

from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path

from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    load_optimizer_smoke_execution_authorization,
    load_optimizer_smoke_preregistration,
    validate_checkpoint_resume_qualification_authorization,
)
from verigym.schemas.hwe_training import (
    HweDecisionSft64kCheckpointResumeQualificationAuthorization,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rllm-source", type=Path, required=True)
    parser.add_argument("--verl-source", type=Path, required=True)
    parser.add_argument("--transformers-source", type=Path, required=True)
    parser.add_argument("--prior-attempt-7-authorization", type=Path, required=True)
    parser.add_argument("--prior-attempt-7-pass-report", type=Path, required=True)
    parser.add_argument("--prior-attempt-7-summary", type=Path, required=True)
    parser.add_argument(
        "--prior-attempt-7-rank-diagnostic",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--implementation-source", type=Path, required=True)
    return parser


def _consume_authorization(path: Path, authorization_hash: str) -> Path:
    if path.name != "execution-checkpoint-resume-authorization.json":
        raise ValueError("checkpoint/resume authorization filename changed")
    marker = path.with_name("execution-checkpoint-resume-started.json")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_checkpoint_resume_execution_start_v1",
        "status": "execution_started",
        "authorization_hash": authorization_hash,
        "single_use_authorization_consumed": True,
    }
    payload = (
        json.dumps({**base, "marker_hash": content_hash(base)}, indent=2, sort_keys=True).encode(
            "utf-8"
        )
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
    qualification_root: Path,
    model_root: Path,
    scratch_root: Path,
    checkpoint_root: Path,
    evidence_root: Path,
    report: Path,
    rllm_source: Path,
    verl_source: Path,
    transformers_source: Path,
    prior_attempt_7_authorization: Path,
    prior_attempt_7_pass_report: Path,
    prior_attempt_7_summary: Path,
    prior_attempt_7_rank_diagnostics: list[Path],
    implementation_source: Path,
) -> None:
    """Validate all bindings before importing the optional distributed GPU stack."""

    for output in (checkpoint_root, evidence_root, report):
        if output.exists() or output.is_symlink():
            raise ValueError("checkpoint/resume output already exists")
    if checkpoint_root.name != "temporary-fsdp2-checkpoint":
        raise ValueError("checkpoint/resume temporary checkpoint basename changed")
    if checkpoint_root.parent != evidence_root.parent:
        raise ValueError("checkpoint/resume checkpoint and evidence roots must share a parent")
    if socket.gethostname().split(".", maxsplit=1)[0] != "gpu03":
        raise RuntimeError("checkpoint/resume qualification is authorized only on gpu03")
    if os.environ.get("LSB_JOBID") != "466876":
        raise RuntimeError("checkpoint/resume qualification requires existing LSF job 466876")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0,1,2,3":
        raise RuntimeError("checkpoint/resume qualification requires physical GPUs 0,1,2,3")
    if len(prior_attempt_7_rank_diagnostics) != 32:
        raise ValueError("checkpoint/resume qualification requires 32 rank diagnostics")

    preregistration = load_optimizer_smoke_preregistration(config)
    authorization = load_optimizer_smoke_execution_authorization(authorization_path)
    if not isinstance(
        authorization,
        HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    ):
        raise ValueError("checkpoint/resume qualification requires attempt-8 authorization")
    validate_checkpoint_resume_qualification_authorization(
        authorization,
        preregistration=preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config,
        preregistration_receipt_path=preregistration_receipt,
        prior_attempt_7_authorization_path=prior_attempt_7_authorization,
        prior_attempt_7_pass_report_path=prior_attempt_7_pass_report,
        prior_attempt_7_summary_path=prior_attempt_7_summary,
        prior_attempt_7_rank_diagnostic_paths=tuple(prior_attempt_7_rank_diagnostics),
        implementation_source_path=implementation_source,
    )
    for source in (model_root, rllm_source, verl_source, transformers_source):
        if source.is_symlink() or not source.resolve(strict=True).is_dir():
            raise ValueError("checkpoint/resume model and source bindings must be real directories")
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _consume_authorization(authorization_path, authorization.authorization_hash)

    from verigym_training_reference.hwe_decision_sft_64k_backend import (
        validate_qualification_runtime,
    )
    from verigym_training_reference.hwe_decision_sft_64k_checkpoint_resume import (
        VeriGymHweDecisionSft64kCheckpointResumeTrainer,
    )

    validate_qualification_runtime(
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )
    trainer = VeriGymHweDecisionSft64kCheckpointResumeTrainer(
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
        qualification_root=arguments.qualification_root,
        model_root=arguments.model_root,
        scratch_root=arguments.scratch_root,
        checkpoint_root=arguments.checkpoint_root,
        evidence_root=arguments.evidence_root,
        report=arguments.report,
        rllm_source=arguments.rllm_source,
        verl_source=arguments.verl_source,
        transformers_source=arguments.transformers_source,
        prior_attempt_7_authorization=arguments.prior_attempt_7_authorization,
        prior_attempt_7_pass_report=arguments.prior_attempt_7_pass_report,
        prior_attempt_7_summary=arguments.prior_attempt_7_summary,
        prior_attempt_7_rank_diagnostics=arguments.prior_attempt_7_rank_diagnostic,
        implementation_source=arguments.implementation_source,
    )


if __name__ == "__main__":
    main()
