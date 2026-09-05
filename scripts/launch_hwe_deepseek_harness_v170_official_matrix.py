#!/usr/bin/env python3
"""Launch the one-use v170 provider matrix in an exact credential child environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

_REPOSITORY = Path(__file__).resolve().parents[1]
_SOURCE_ROOTS = (
    _REPOSITORY,
    _REPOSITORY / "src",
    _REPOSITORY / "integrations/verigym-hwe-bench/src",
    _REPOSITORY / "integrations/verigym-deepseek-harness/src",
)
for _source_root in reversed(_SOURCE_ROOTS):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from verigym_deepseek_harness.config import API_KEY_ENV, BASE_URL_ENV  # noqa: E402

from scripts import collect_hwe_deepseek_harness_v170_official_matrix as runner  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
)

_DOCKER_ENDPOINT_ENV_NAMES = ("DOCKER_CONTEXT", "DOCKER_HOST")
_REQUIRED_PROVIDER_ENV_NAMES = (API_KEY_ENV, BASE_URL_ENV)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def _blocked_child_environment_names() -> tuple[str, ...]:
    enforced = tuple(sorted(v69._PROVIDER_ENV_NAMES))  # noqa: SLF001
    if enforced != ZERO_PROVIDER_CONFIGURATION_ENV_NAMES:
        raise ConfigurationError("v170 launcher and runner provider boundaries differ")
    return (*enforced, *_DOCKER_ENDPOINT_ENV_NAMES)


def _sanitized_child_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Retain only the two required provider values without reading blocked aliases."""

    blocked = frozenset(_blocked_child_environment_names())
    child: dict[str, str] = {}
    for name in source:
        if name not in blocked:
            child[name] = source[name]
    for name in _REQUIRED_PROVIDER_ENV_NAMES:
        value = source.get(name)
        if not value:
            raise ConfigurationError("v170 provider execution environment is incomplete")
        child[name] = value
    child[runner.OPT_IN_ENV] = "1"
    child[runner.CHILD_BOUNDARY_ENV] = "1"
    present = {name for name in blocked if name in child}
    if present != set(_REQUIRED_PROVIDER_ENV_NAMES):
        raise ConfigurationError("v170 sanitized child environment is contaminated")
    return child


def main() -> int:
    arguments = _parser().parse_args()
    if os.environ.get(runner.OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{runner.OPT_IN_ENV}=1 is required")
    child = _sanitized_child_environment(os.environ)
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(runner.__file__).resolve(strict=True)),
            "--post-merge-main-run-id",
            str(arguments.post_merge_main_run_id),
        ],
        cwd=_REPOSITORY,
        env=child,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
