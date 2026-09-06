#!/usr/bin/env python3
"""Enter the zero-provider child environment for the v186 context refinement."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str((_REPOSITORY / "src").resolve(strict=True)))

from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
)

OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V186_DIAGNOSTIC_CONTEXT"
SANITIZED_CHILD_ENV = "VERIGYM_V186_SANITIZED_CHILD"
RUNNER = _REPOSITORY / "scripts/materialize_hwe_deepseek_harness_v186_diagnostic_context.py"


def main() -> int:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.environ.get(SANITIZED_CHILD_ENV) == "1":
        raise ConfigurationError("v186 sanitized child marker already exists")
    unset_names = sorted(
        {
            *ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
            "DOCKER_CONTEXT",
            "DOCKER_HOST",
        }
    )
    arguments = ["env"]
    for name in unset_names:
        arguments.extend(["-u", name])
    arguments.extend(
        [
            f"{SANITIZED_CHILD_ENV}=1",
            sys.executable,
            str(RUNNER),
            *sys.argv[1:],
        ]
    )
    os.execvp("env", arguments)
    raise AssertionError("exec returned unexpectedly")


if __name__ == "__main__":
    raise SystemExit(main())
