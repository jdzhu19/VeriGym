#!/usr/bin/env python3
"""Seal attempt 7 against the exact attempt-6 BF16 clipping-only failure."""

from __future__ import annotations

import argparse
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    create_optimizer_full_smoke_bf16_tolerance_replay_authorization,
    load_optimizer_smoke_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--prior-full-smoke-authorization", type=Path, required=True)
    parser.add_argument("--prior-full-smoke-failure-report", type=Path, required=True)
    parser.add_argument(
        "--prior-full-smoke-rank-diagnostic",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--implementation-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def authorize_full_smoke_bf16_tolerance_replay(
    *,
    config: Path,
    preregistration_receipt: Path,
    dataset_root: Path,
    qualification_root: Path,
    prior_full_smoke_authorization: Path,
    prior_full_smoke_failure_report: Path,
    prior_full_smoke_rank_diagnostics: list[Path],
    implementation_source: Path,
    output: Path,
) -> dict[str, object]:
    """Persist one exclusive eight-step authorization bound to attempt 6."""

    if output.exists() or output.is_symlink():
        raise ValueError("optimizer full-smoke BF16 authorization must not already exist")
    if len(prior_full_smoke_rank_diagnostics) != 8:
        raise ValueError("optimizer full-smoke BF16 replay requires eight rank diagnostics")
    diagnostics = tuple(prior_full_smoke_rank_diagnostics)
    preregistration = load_optimizer_smoke_preregistration(config)
    authorization = create_optimizer_full_smoke_bf16_tolerance_replay_authorization(
        preregistration,
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
    payload = authorization.model_dump(mode="json")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_dump_json(output, payload)
    return payload


def main() -> None:
    arguments = _parser().parse_args()
    authorize_full_smoke_bf16_tolerance_replay(
        config=arguments.config,
        preregistration_receipt=arguments.preregistration_receipt,
        dataset_root=arguments.dataset_root,
        qualification_root=arguments.qualification_root,
        prior_full_smoke_authorization=arguments.prior_full_smoke_authorization,
        prior_full_smoke_failure_report=arguments.prior_full_smoke_failure_report,
        prior_full_smoke_rank_diagnostics=arguments.prior_full_smoke_rank_diagnostic,
        implementation_source=arguments.implementation_source,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
