#!/usr/bin/env python3
"""Launch the one-use v156 diagnostic in an exact zero-provider environment."""

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

from scripts import run_hwe_deepseek_harness_v156_command_runtime_diagnostic as runner  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
)

_DOCKER_ENDPOINT_ENV_NAMES = ("DOCKER_CONTEXT", "DOCKER_HOST")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def _sanitized_child_environment(source: Mapping[str, str]) -> dict[str, str]:
    blocked = frozenset((*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, *_DOCKER_ENDPOINT_ENV_NAMES))
    child = {name: value for name, value in source.items() if name not in blocked}
    child[runner.OPT_IN_ENV] = "1"
    child[runner.CHILD_BOUNDARY_ENV] = "1"
    if any(name in child for name in blocked):
        raise ConfigurationError("v156 zero-provider child environment is contaminated")
    return child


def main() -> int:
    arguments = _parser().parse_args()
    if os.environ.get(runner.OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{runner.OPT_IN_ENV}=1 is required")
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(runner.__file__).resolve(strict=True)),
            "--post-merge-main-run-id",
            str(arguments.post_merge_main_run_id),
        ],
        cwd=_REPOSITORY,
        env=_sanitized_child_environment(os.environ),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
