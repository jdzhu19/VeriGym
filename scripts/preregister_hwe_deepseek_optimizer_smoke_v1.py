#!/usr/bin/env python3
"""Seal the 64K HWE eight-step optimizer-smoke plan without starting training."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from verigym.experiments.state import atomic_dump_json, atomic_write_text
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    load_optimizer_smoke_preregistration,
    validate_optimizer_smoke_preregistration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def preregister(
    *,
    config: Path,
    dataset_root: Path,
    qualification_root: Path,
    output: Path,
) -> dict[str, object]:
    """Validate every frozen binding and persist a not-started receipt."""

    if output.exists() or output.is_symlink():
        raise ValueError("optimizer-smoke preregistration output must not already exist")
    plan = load_optimizer_smoke_preregistration(config)
    receipt = validate_optimizer_smoke_preregistration(
        plan,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config,
    )
    config_text = config.read_text(encoding="utf-8")
    if hashlib.sha256(config_text.encode("utf-8")).hexdigest() != receipt["config_sha256"]:
        raise ValueError("optimizer-smoke config changed after validation")
    output.mkdir(parents=True, mode=0o700)
    atomic_write_text(output / "preregistration-config.json", config_text)
    atomic_dump_json(output / "preregistration-receipt.json", receipt)
    return receipt


def main() -> None:
    arguments = _parser().parse_args()
    preregister(
        config=arguments.config,
        dataset_root=arguments.dataset_root,
        qualification_root=arguments.qualification_root,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
