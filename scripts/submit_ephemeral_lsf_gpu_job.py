#!/usr/bin/env python3
"""Submit one bounded GPU payload to LSF without an interactive bash allocation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verigym_training_reference.lsf_ephemeral import (
    request_from_values,
    submit_ephemeral_lsf_gpu_job,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--queue", default="gpu")
    parser.add_argument("--gpus", type=int, required=True)
    parser.add_argument("--cpus", type=int, required=True)
    parser.add_argument("--wall-minutes", type=int, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    command = arguments.command
    if command and command[0] == "--":
        command = command[1:]
    request = request_from_values(
        job_name=arguments.job_name,
        queue=arguments.queue,
        gpu_count=arguments.gpus,
        cpu_slots=arguments.cpus,
        wall_minutes=arguments.wall_minutes,
        working_directory=arguments.working_directory,
        output_directory=arguments.output_directory,
        command=command,
    )
    receipt = submit_ephemeral_lsf_gpu_job(request)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
