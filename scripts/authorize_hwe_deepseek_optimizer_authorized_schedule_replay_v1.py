#!/usr/bin/env python3
"""Seal one replay after proving attempt 4 reached only its authorized first step."""

from __future__ import annotations

import argparse
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    create_optimizer_authorized_schedule_replay_authorization,
    load_optimizer_smoke_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--prior-bf16-tolerance-authorization", type=Path, required=True)
    parser.add_argument("--prior-bf16-tolerance-failure-report", type=Path, required=True)
    parser.add_argument(
        "--prior-bf16-rank-diagnostic",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--implementation-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def authorize_authorized_schedule_replay(
    *,
    config: Path,
    preregistration_receipt: Path,
    dataset_root: Path,
    qualification_root: Path,
    prior_bf16_tolerance_authorization: Path,
    prior_bf16_tolerance_failure_report: Path,
    prior_bf16_rank_diagnostics: list[Path],
    implementation_source: Path,
    output: Path,
) -> dict[str, object]:
    """Persist one exclusive attempt-5 authorization and its full evidence binding."""

    if output.exists() or output.is_symlink():
        raise ValueError("optimizer authorized-schedule authorization must not already exist")
    if len(prior_bf16_rank_diagnostics) != 4:
        raise ValueError("optimizer authorized-schedule replay requires four rank diagnostics")
    rank_0, rank_1, rank_2, rank_3 = prior_bf16_rank_diagnostics
    preregistration = load_optimizer_smoke_preregistration(config)
    authorization = create_optimizer_authorized_schedule_replay_authorization(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config,
        preregistration_receipt_path=preregistration_receipt,
        prior_bf16_tolerance_authorization_path=prior_bf16_tolerance_authorization,
        prior_bf16_tolerance_failure_report_path=prior_bf16_tolerance_failure_report,
        prior_bf16_rank_diagnostic_paths=(rank_0, rank_1, rank_2, rank_3),
        implementation_source_path=implementation_source,
    )
    payload = authorization.model_dump(mode="json")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_dump_json(output, payload)
    return payload


def main() -> None:
    arguments = _parser().parse_args()
    authorize_authorized_schedule_replay(
        config=arguments.config,
        preregistration_receipt=arguments.preregistration_receipt,
        dataset_root=arguments.dataset_root,
        qualification_root=arguments.qualification_root,
        prior_bf16_tolerance_authorization=arguments.prior_bf16_tolerance_authorization,
        prior_bf16_tolerance_failure_report=arguments.prior_bf16_tolerance_failure_report,
        prior_bf16_rank_diagnostics=arguments.prior_bf16_rank_diagnostic,
        implementation_source=arguments.implementation_source,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
