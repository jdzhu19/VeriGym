#!/usr/bin/env python3
"""Consume one authorization and launch the sealed eight-step optimizer smoke."""

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
    validate_optimizer_authorized_schedule_replay_authorization,
    validate_optimizer_bf16_tolerance_replay_authorization,
    validate_optimizer_diagnostic_replay_authorization,
    validate_optimizer_full_smoke_bf16_tolerance_replay_authorization,
    validate_optimizer_full_smoke_replay_authorization,
    validate_optimizer_smoke_execution_authorization,
    validate_optimizer_smoke_execution_retry_authorization,
)
from verigym.schemas.hwe_training import (
    HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization,
    HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
    HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerFullSmokeReplayAuthorization,
    HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization,
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
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rllm-source", type=Path, required=True)
    parser.add_argument("--verl-source", type=Path, required=True)
    parser.add_argument("--transformers-source", type=Path, required=True)
    parser.add_argument("--prior-authorization", type=Path)
    parser.add_argument("--prior-failure-report", type=Path)
    parser.add_argument("--prior-retry-authorization", type=Path)
    parser.add_argument("--prior-retry-failure-report", type=Path)
    parser.add_argument("--prior-diagnostic-authorization", type=Path)
    parser.add_argument("--prior-diagnostic-failure-report", type=Path)
    parser.add_argument("--prior-bf16-tolerance-authorization", type=Path)
    parser.add_argument("--prior-bf16-tolerance-failure-report", type=Path)
    parser.add_argument("--prior-bf16-rank-diagnostic", type=Path, action="append")
    parser.add_argument("--prior-authorized-schedule-authorization", type=Path)
    parser.add_argument("--prior-authorized-schedule-pass-report", type=Path)
    parser.add_argument("--prior-authorized-schedule-rank-diagnostic", type=Path, action="append")
    parser.add_argument("--prior-full-smoke-authorization", type=Path)
    parser.add_argument("--prior-full-smoke-failure-report", type=Path)
    parser.add_argument("--prior-full-smoke-rank-diagnostic", type=Path, action="append")
    parser.add_argument("--implementation-source", type=Path)
    return parser


def _consume_authorization(path: Path, *, authorization_hash: str) -> Path:
    marker_names = {
        "execution-authorization.json": "execution-started.json",
        "execution-retry-authorization.json": "execution-retry-started.json",
        "execution-diagnostic-authorization.json": "execution-diagnostic-started.json",
        "execution-bf16-tolerance-authorization.json": "execution-bf16-tolerance-started.json",
        "execution-authorized-schedule-authorization.json": (
            "execution-authorized-schedule-started.json"
        ),
        "execution-full-smoke-authorization.json": "execution-full-smoke-started.json",
        "execution-full-smoke-bf16-authorization.json": ("execution-full-smoke-bf16-started.json"),
    }
    try:
        marker_name = marker_names[path.name]
    except KeyError as exc:
        raise ValueError("optimizer authorization filename is not registered") from exc
    marker = path.with_name(marker_name)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_start_v1",
        "status": "execution_started",
        "authorization_hash": authorization_hash,
        "single_use_authorization_consumed": True,
    }
    payload = (
        json.dumps(
            {**base, "marker_hash": content_hash(base)},
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
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
    report: Path,
    rllm_source: Path,
    verl_source: Path,
    transformers_source: Path,
    prior_authorization: Path | None = None,
    prior_failure_report: Path | None = None,
    prior_retry_authorization: Path | None = None,
    prior_retry_failure_report: Path | None = None,
    prior_diagnostic_authorization: Path | None = None,
    prior_diagnostic_failure_report: Path | None = None,
    prior_bf16_tolerance_authorization: Path | None = None,
    prior_bf16_tolerance_failure_report: Path | None = None,
    prior_bf16_rank_diagnostics: list[Path] | None = None,
    prior_authorized_schedule_authorization: Path | None = None,
    prior_authorized_schedule_pass_report: Path | None = None,
    prior_authorized_schedule_rank_diagnostics: list[Path] | None = None,
    prior_full_smoke_authorization: Path | None = None,
    prior_full_smoke_failure_report: Path | None = None,
    prior_full_smoke_rank_diagnostics: list[Path] | None = None,
    implementation_source: Path | None = None,
) -> None:
    """Validate the one-use boundary before importing the optional GPU stack."""

    if report.exists() or report.is_symlink():
        raise ValueError("optimizer-smoke execution report must not already exist")
    if socket.gethostname().split(".", maxsplit=1)[0] != "gpu03":
        raise RuntimeError("optimizer smoke is authorized only on gpu03")
    if os.environ.get("LSB_JOBID") != "466876":
        raise RuntimeError("optimizer smoke is authorized only inside existing LSF job 466876")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0,1,2,3":
        raise RuntimeError("optimizer smoke requires exactly physical GPUs 0,1,2,3")
    preregistration = load_optimizer_smoke_preregistration(config)
    authorization = load_optimizer_smoke_execution_authorization(authorization_path)
    if isinstance(
        authorization,
        HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    ):
        if (
            prior_full_smoke_authorization is None
            or prior_full_smoke_failure_report is None
            or prior_full_smoke_rank_diagnostics is None
            or len(prior_full_smoke_rank_diagnostics) != 8
            or implementation_source is None
        ):
            raise ValueError("optimizer full-smoke BF16 replay evidence paths are required")
        diagnostics = tuple(prior_full_smoke_rank_diagnostics)
        validate_optimizer_full_smoke_bf16_tolerance_replay_authorization(
            authorization,
            preregistration=preregistration,
            dataset_root=dataset_root,
            qualification_root=qualification_root,
            config_path=config,
            preregistration_receipt_path=preregistration_receipt,
            prior_full_smoke_authorization_path=prior_full_smoke_authorization,
            prior_full_smoke_failure_report_path=prior_full_smoke_failure_report,
            prior_full_smoke_rank_diagnostic_paths=(
                diagnostics[0],
                diagnostics[1],
                diagnostics[2],
                diagnostics[3],
                diagnostics[4],
                diagnostics[5],
                diagnostics[6],
                diagnostics[7],
            ),
            implementation_source_path=implementation_source,
        )
    elif isinstance(authorization, HweDecisionSft64kOptimizerFullSmokeReplayAuthorization):
        if (
            prior_authorized_schedule_authorization is None
            or prior_authorized_schedule_pass_report is None
            or prior_authorized_schedule_rank_diagnostics is None
            or len(prior_authorized_schedule_rank_diagnostics) != 4
            or implementation_source is None
        ):
            raise ValueError("optimizer full-smoke replay evidence paths are required")
        rank_0, rank_1, rank_2, rank_3 = prior_authorized_schedule_rank_diagnostics
        validate_optimizer_full_smoke_replay_authorization(
            authorization,
            preregistration=preregistration,
            dataset_root=dataset_root,
            qualification_root=qualification_root,
            config_path=config,
            preregistration_receipt_path=preregistration_receipt,
            prior_authorized_schedule_authorization_path=(prior_authorized_schedule_authorization),
            prior_authorized_schedule_pass_report_path=(prior_authorized_schedule_pass_report),
            prior_authorized_schedule_rank_diagnostic_paths=(
                rank_0,
                rank_1,
                rank_2,
                rank_3,
            ),
            implementation_source_path=implementation_source,
        )
    elif isinstance(
        authorization,
        HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization,
    ):
        if (
            prior_bf16_tolerance_authorization is None
            or prior_bf16_tolerance_failure_report is None
            or prior_bf16_rank_diagnostics is None
            or len(prior_bf16_rank_diagnostics) != 4
            or implementation_source is None
        ):
            raise ValueError("optimizer authorized-schedule replay evidence paths are required")
        rank_0, rank_1, rank_2, rank_3 = prior_bf16_rank_diagnostics
        validate_optimizer_authorized_schedule_replay_authorization(
            authorization,
            preregistration=preregistration,
            dataset_root=dataset_root,
            qualification_root=qualification_root,
            config_path=config,
            preregistration_receipt_path=preregistration_receipt,
            prior_bf16_tolerance_authorization_path=(prior_bf16_tolerance_authorization),
            prior_bf16_tolerance_failure_report_path=(prior_bf16_tolerance_failure_report),
            prior_bf16_rank_diagnostic_paths=(rank_0, rank_1, rank_2, rank_3),
            implementation_source_path=implementation_source,
        )
    elif isinstance(
        authorization,
        HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
    ):
        if (
            prior_diagnostic_authorization is None
            or prior_diagnostic_failure_report is None
            or implementation_source is None
        ):
            raise ValueError("optimizer BF16 tolerance replay evidence paths are required")
        validate_optimizer_bf16_tolerance_replay_authorization(
            authorization,
            preregistration=preregistration,
            dataset_root=dataset_root,
            qualification_root=qualification_root,
            config_path=config,
            preregistration_receipt_path=preregistration_receipt,
            prior_diagnostic_authorization_path=prior_diagnostic_authorization,
            prior_diagnostic_failure_report_path=prior_diagnostic_failure_report,
            implementation_source_path=implementation_source,
        )
    elif isinstance(authorization, HweDecisionSft64kOptimizerDiagnosticReplayAuthorization):
        if (
            prior_authorization is None
            or prior_failure_report is None
            or prior_retry_authorization is None
            or prior_retry_failure_report is None
            or implementation_source is None
        ):
            raise ValueError("optimizer diagnostic evidence paths are required")
        validate_optimizer_diagnostic_replay_authorization(
            authorization,
            preregistration=preregistration,
            dataset_root=dataset_root,
            qualification_root=qualification_root,
            config_path=config,
            preregistration_receipt_path=preregistration_receipt,
            prior_authorization_path=prior_authorization,
            prior_failure_report_path=prior_failure_report,
            prior_retry_authorization_path=prior_retry_authorization,
            prior_retry_failure_report_path=prior_retry_failure_report,
            instrumentation_source_path=implementation_source,
        )
    elif isinstance(authorization, HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization):
        if (
            prior_authorization is None
            or prior_failure_report is None
            or implementation_source is None
        ):
            raise ValueError("optimizer-smoke retry evidence paths are required")
        validate_optimizer_smoke_execution_retry_authorization(
            authorization,
            preregistration=preregistration,
            dataset_root=dataset_root,
            qualification_root=qualification_root,
            config_path=config,
            preregistration_receipt_path=preregistration_receipt,
            prior_authorization_path=prior_authorization,
            prior_failure_report_path=prior_failure_report,
            implementation_source_path=implementation_source,
        )
    else:
        validate_optimizer_smoke_execution_authorization(
            authorization,
            preregistration=preregistration,
            dataset_root=dataset_root,
            qualification_root=qualification_root,
            config_path=config,
            preregistration_receipt_path=preregistration_receipt,
        )
    for source in (model_root, rllm_source, verl_source, transformers_source):
        if source.is_symlink() or not source.resolve(strict=True).is_dir():
            raise ValueError("optimizer smoke model and source bindings must be real directories")
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _consume_authorization(
        authorization_path,
        authorization_hash=authorization.authorization_hash,
    )

    from verigym_training_reference.hwe_decision_sft_64k_backend import (
        validate_qualification_runtime,
    )
    from verigym_training_reference.hwe_decision_sft_64k_optimizer_smoke_backend import (
        VeriGymHweDecisionSft64kOptimizerSmokeTrainer,
    )

    validate_qualification_runtime(
        rllm_source=rllm_source,
        verl_source=verl_source,
        transformers_source=transformers_source,
    )
    dispatcher = VeriGymHweDecisionSft64kOptimizerSmokeTrainer(
        preregistration=preregistration,
        authorization=authorization,
        dataset_root=dataset_root,
        model_root=model_root,
        scratch_root=scratch_root,
    )
    dispatcher.launch(
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
        report=arguments.report,
        rllm_source=arguments.rllm_source,
        verl_source=arguments.verl_source,
        transformers_source=arguments.transformers_source,
        prior_authorization=arguments.prior_authorization,
        prior_failure_report=arguments.prior_failure_report,
        prior_retry_authorization=arguments.prior_retry_authorization,
        prior_retry_failure_report=arguments.prior_retry_failure_report,
        prior_diagnostic_authorization=arguments.prior_diagnostic_authorization,
        prior_diagnostic_failure_report=arguments.prior_diagnostic_failure_report,
        prior_bf16_tolerance_authorization=(arguments.prior_bf16_tolerance_authorization),
        prior_bf16_tolerance_failure_report=(arguments.prior_bf16_tolerance_failure_report),
        prior_bf16_rank_diagnostics=arguments.prior_bf16_rank_diagnostic,
        prior_authorized_schedule_authorization=(arguments.prior_authorized_schedule_authorization),
        prior_authorized_schedule_pass_report=(arguments.prior_authorized_schedule_pass_report),
        prior_authorized_schedule_rank_diagnostics=(
            arguments.prior_authorized_schedule_rank_diagnostic
        ),
        prior_full_smoke_authorization=arguments.prior_full_smoke_authorization,
        prior_full_smoke_failure_report=arguments.prior_full_smoke_failure_report,
        prior_full_smoke_rank_diagnostics=arguments.prior_full_smoke_rank_diagnostic,
        implementation_source=arguments.implementation_source,
    )


if __name__ == "__main__":
    main()
