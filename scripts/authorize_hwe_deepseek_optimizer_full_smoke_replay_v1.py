#!/usr/bin/env python3
"""Seal one full eight-step optimizer smoke after the repaired one-step pass."""

from __future__ import annotations

import argparse
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    create_optimizer_full_smoke_replay_authorization,
    load_optimizer_smoke_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--prior-authorized-schedule-authorization", type=Path, required=True)
    parser.add_argument("--prior-authorized-schedule-pass-report", type=Path, required=True)
    parser.add_argument(
        "--prior-authorized-schedule-rank-diagnostic",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--implementation-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def authorize_full_smoke_replay(
    *,
    config: Path,
    preregistration_receipt: Path,
    dataset_root: Path,
    qualification_root: Path,
    prior_authorized_schedule_authorization: Path,
    prior_authorized_schedule_pass_report: Path,
    prior_authorized_schedule_rank_diagnostics: list[Path],
    implementation_source: Path,
    output: Path,
) -> dict[str, object]:
    """Persist one exclusive eight-step authorization bound to attempt 5."""

    if output.exists() or output.is_symlink():
        raise ValueError("optimizer full-smoke authorization must not already exist")
    if len(prior_authorized_schedule_rank_diagnostics) != 4:
        raise ValueError("optimizer full-smoke replay requires four rank diagnostics")
    rank_0, rank_1, rank_2, rank_3 = prior_authorized_schedule_rank_diagnostics
    preregistration = load_optimizer_smoke_preregistration(config)
    authorization = create_optimizer_full_smoke_replay_authorization(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config,
        preregistration_receipt_path=preregistration_receipt,
        prior_authorized_schedule_authorization_path=(prior_authorized_schedule_authorization),
        prior_authorized_schedule_pass_report_path=prior_authorized_schedule_pass_report,
        prior_authorized_schedule_rank_diagnostic_paths=(rank_0, rank_1, rank_2, rank_3),
        implementation_source_path=implementation_source,
    )
    payload = authorization.model_dump(mode="json")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_dump_json(output, payload)
    return payload


def main() -> None:
    arguments = _parser().parse_args()
    authorize_full_smoke_replay(
        config=arguments.config,
        preregistration_receipt=arguments.preregistration_receipt,
        dataset_root=arguments.dataset_root,
        qualification_root=arguments.qualification_root,
        prior_authorized_schedule_authorization=(arguments.prior_authorized_schedule_authorization),
        prior_authorized_schedule_pass_report=arguments.prior_authorized_schedule_pass_report,
        prior_authorized_schedule_rank_diagnostics=(
            arguments.prior_authorized_schedule_rank_diagnostic
        ),
        implementation_source=arguments.implementation_source,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
