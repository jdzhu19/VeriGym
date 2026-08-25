#!/usr/bin/env python3
"""Seal one replacement authorization after the registered zero-step implementation failure."""

from __future__ import annotations

import argparse
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    create_optimizer_smoke_execution_retry_authorization,
    load_optimizer_smoke_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration-receipt", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--prior-authorization", type=Path, required=True)
    parser.add_argument("--prior-failure-report", type=Path, required=True)
    parser.add_argument("--implementation-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def authorize_retry(
    *,
    config: Path,
    preregistration_receipt: Path,
    dataset_root: Path,
    qualification_root: Path,
    prior_authorization: Path,
    prior_failure_report: Path,
    implementation_source: Path,
    output: Path,
) -> dict[str, object]:
    """Persist a one-use retry bound to the failed receipt and fixed entry source."""

    if output.exists() or output.is_symlink():
        raise ValueError("optimizer-smoke retry authorization must not already exist")
    preregistration = load_optimizer_smoke_preregistration(config)
    authorization = create_optimizer_smoke_execution_retry_authorization(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config,
        preregistration_receipt_path=preregistration_receipt,
        prior_authorization_path=prior_authorization,
        prior_failure_report_path=prior_failure_report,
        implementation_source_path=implementation_source,
    )
    payload = authorization.model_dump(mode="json")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_dump_json(output, payload)
    return payload


def main() -> None:
    arguments = _parser().parse_args()
    authorize_retry(
        config=arguments.config,
        preregistration_receipt=arguments.preregistration_receipt,
        dataset_root=arguments.dataset_root,
        qualification_root=arguments.qualification_root,
        prior_authorization=arguments.prior_authorization,
        prior_failure_report=arguments.prior_failure_report,
        implementation_source=arguments.implementation_source,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
