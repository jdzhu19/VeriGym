#!/usr/bin/env python3
"""Run bounded CVA6 base/reference/candidate acceptance through isolated DinD."""

from __future__ import annotations

import argparse
import os
import pwd
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path

import run_repository_rollout_dind_controller as dind

_ACCEPTANCE_PROGRAM = r"""
from pathlib import Path

from verigym.experiments.state import atomic_dump_json
from verigym.plugin_api import SuiteSourceConfig, VerifierStatus
from verigym_hwe_bench.adapter import HweBenchSuite
from verigym_hwe_bench.cva6_qualification import _verifier_summary, _zero_model_smoke
from verigym_hwe_bench.dataset import VARIANT

source = Path(__import__("os").environ["VERIGYM_ACCEPTANCE_SOURCE"])
candidate = Path(__import__("os").environ["VERIGYM_ACCEPTANCE_CANDIDATE"])
output = Path(__import__("os").environ["VERIGYM_ACCEPTANCE_OUTPUT"])
smoke = _zero_model_smoke(source=source, output=output / "zero-model")
suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=source, variant=VARIANT))
references = list(suite.discover())
if len(references) != 1:
    raise RuntimeError("CVA6 acceptance source did not expose exactly one task")
task = suite.load_task(references[0])
results = suite.verify_candidate(
    task=task,
    candidate_dir=candidate,
    artifact_root=output / "candidate-verifier",
)
if results is None:
    raise RuntimeError("CVA6 suite did not claim its Docker verifier")
candidate_passed = bool(results) and all(
    result.status == VerifierStatus.PASSED for result in results
)
candidate_infrastructure_valid = bool(results) and all(
    result.status != VerifierStatus.ERROR for result in results
)
accepted = (
    smoke["base_failed"] is True
    and smoke["base_infrastructure_error"] is False
    and smoke["reference_passed"] is True
    and candidate_passed
    and candidate_infrastructure_valid
)
report = {
    "schema_version": "1.0",
    "kind": "verigym_cva6_dind_acceptance_v1",
    "accepted": accepted,
    "task_id": task.id,
    "base_failed": smoke["base_failed"],
    "base_infrastructure_error": smoke["base_infrastructure_error"],
    "reference_passed": smoke["reference_passed"],
    "candidate_passed": candidate_passed,
    "candidate_infrastructure_valid": candidate_infrastructure_valid,
    "model_process_count": 0,
    "candidate_verifier_results": [_verifier_summary(result) for result in results],
}
atomic_dump_json(output / "acceptance-report.json", report)
raise SystemExit(0 if accepted else 2)
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-image-id", required=True)
    parser.add_argument("--dind-image-id", required=True)
    parser.add_argument("--verifier-image-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dind-data-volume", required=True)
    parser.add_argument("--empty-home", type=Path, required=True)
    parser.add_argument("--startup-timeout-s", type=int, default=60)
    parser.add_argument("--image-load-timeout-s", type=int, default=1800)
    return parser


def _controller_command(
    *,
    image_id: str,
    socket_volume: str,
    source: Path,
    candidate: Path,
    output: Path,
    empty_home: Path,
) -> list[str]:
    container_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "4096",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--env",
        "DOCKER_HOST=unix:///var/run/docker.sock",
        "--env",
        "HOME=/tmp",
        "--env",
        f"TMPDIR={output}/tmp",
        "--env",
        f"VERIGYM_ACCEPTANCE_SOURCE={source}",
        "--env",
        f"VERIGYM_ACCEPTANCE_CANDIDATE={candidate}",
        "--env",
        f"VERIGYM_ACCEPTANCE_OUTPUT={output}",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--volume",
        f"{empty_home}:{container_home}:rw",
        "--volume",
        f"{socket_volume}:/var/run:rw",
        "--volume",
        f"{source}:{source}:ro",
        "--volume",
        f"{candidate}:{candidate}:ro",
        "--volume",
        f"{output}:{output}:rw",
        "--entrypoint",
        "python3",
        image_id,
        "-c",
        _ACCEPTANCE_PROGRAM,
    ]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.startup_timeout_s <= 0 or arguments.image_load_timeout_s <= 0:
        raise RuntimeError("DinD timeouts must be positive")
    dind._controller_image(arguments.controller_image_id)
    dind._dind_image(arguments.dind_image_id)
    dind._image(arguments.verifier_image_id, role="verifier")
    source = dind._directory(arguments.source)
    candidate = dind._directory(arguments.candidate)
    if not (candidate / "repository").is_dir():
        raise RuntimeError("CVA6 acceptance candidate is missing repository/")
    empty_home = dind._empty_directory(arguments.empty_home)
    output = arguments.output.expanduser()
    if output.exists() or output.is_symlink():
        raise RuntimeError("CVA6 acceptance output must not already exist")
    output.mkdir(parents=True)
    output = output.resolve(strict=True)
    (output / "tmp").mkdir()
    dind._volume(
        arguments.dind_data_volume,
        owner=dind._DIND_OWNER,
        role="data",
    )

    socket_volume = dind._create_socket_volume()
    dind_name = f"verigym-dind-daemon-{uuid.uuid4().hex[:20]}"
    try:
        dind._start_dind(
            name=dind_name,
            image_id=arguments.dind_image_id,
            socket_volume=socket_volume,
            data_volume=arguments.dind_data_volume,
            source_volume=None,
            scratch_volume=None,
            empty_home=empty_home,
            same_path_mounts=dind._same_path_mounts({source: "ro", candidate: "ro", output: "rw"}),
            startup_timeout_s=arguments.startup_timeout_s,
        )
        dind._require_empty_inner_inventory(dind_name)
        dind._ensure_inner_image(
            container=dind_name,
            image_id=arguments.verifier_image_id,
            timeout_s=arguments.image_load_timeout_s,
        )
        command = _controller_command(
            image_id=arguments.controller_image_id,
            socket_volume=socket_volume,
            source=source,
            candidate=candidate,
            output=output,
            empty_home=empty_home,
        )
        completed = subprocess.run(command, check=False, shell=False)
        dind._require_empty_inner_inventory(dind_name)
        return completed.returncode
    finally:
        existing = dind._run(["docker", "container", "inspect", dind_name], timeout_s=30)
        dind_removed = existing.returncode != 0 or dind._remove_container(dind_name)
        socket_removed = dind._remove_volume(socket_volume)
        if not dind_removed:
            raise RuntimeError("DinD daemon cleanup failed")
        if not socket_removed:
            raise RuntimeError("DinD socket volume cleanup failed")


if __name__ == "__main__":
    raise SystemExit(main())
