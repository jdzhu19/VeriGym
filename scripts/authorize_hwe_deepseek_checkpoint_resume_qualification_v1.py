#!/usr/bin/env python3
"""Seal attempt 8 against the exact passing attempt-7 optimizer smoke."""

from __future__ import annotations

import argparse
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    create_checkpoint_resume_qualification_authorization,
    load_optimizer_smoke_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
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
    parser.add_argument("--output", type=Path, required=True)
    return parser


def authorize_checkpoint_resume_qualification(
    *,
    config: Path,
    preregistration_receipt: Path,
    dataset_root: Path,
    qualification_root: Path,
    prior_attempt_7_authorization: Path,
    prior_attempt_7_pass_report: Path,
    prior_attempt_7_summary: Path,
    prior_attempt_7_rank_diagnostics: list[Path],
    implementation_source: Path,
    output: Path,
) -> dict[str, object]:
    """Persist one exclusive checkpoint/resume qualification authorization."""

    if output.exists() or output.is_symlink():
        raise ValueError("checkpoint/resume authorization must not already exist")
    if len(prior_attempt_7_rank_diagnostics) != 32:
        raise ValueError("checkpoint/resume authorization requires 32 rank diagnostics")
    preregistration = load_optimizer_smoke_preregistration(config)
    authorization = create_checkpoint_resume_qualification_authorization(
        preregistration,
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
    payload = authorization.model_dump(mode="json")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_dump_json(output, payload)
    return payload


def main() -> None:
    arguments = _parser().parse_args()
    authorize_checkpoint_resume_qualification(
        config=arguments.config,
        preregistration_receipt=arguments.preregistration_receipt,
        dataset_root=arguments.dataset_root,
        qualification_root=arguments.qualification_root,
        prior_attempt_7_authorization=arguments.prior_attempt_7_authorization,
        prior_attempt_7_pass_report=arguments.prior_attempt_7_pass_report,
        prior_attempt_7_summary=arguments.prior_attempt_7_summary,
        prior_attempt_7_rank_diagnostics=arguments.prior_attempt_7_rank_diagnostic,
        implementation_source=arguments.implementation_source,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
