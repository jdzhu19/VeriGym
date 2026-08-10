"""Digest-locked Docker execution of one official HWE-Bench verifier."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from verigym.plugin_api import (
    ErrorCategory,
    VerifierNode,
    VerifierResult,
    VerifierStatus,
    build_repository_patch,
    hash_bytes,
)

from .models import HweInstance, ImageLockEntry

_START = "HWE_BENCH_RESULTS_START"
_END = "HWE_BENCH_RESULTS_END"
_MARKER = re.compile(r"^TEST:\s*(.{1,256}?)\s*\.\.\.\s*(PASS|FAIL|SKIP)\s*$")
_MAX_OUTPUT_BYTES = 32 * 1024 * 1024

_RUNNER = """#!/bin/bash
set -euo pipefail
cd __REPOSITORY_HOME__
git reset --hard >/dev/null
git clean -fdx >/dev/null
test -f /home/ibex_base_commit.txt
test "$(cat /home/ibex_base_commit.txt)" = "__BASE_COMMIT__"
git checkout "$(cat /home/ibex_base_commit.txt)" >/dev/null
if [[ -s /home/verigym-candidate.patch ]]; then
  git apply --check /home/verigym-candidate.patch
  git apply /home/verigym-candidate.patch
fi
bash /home/verigym-tb-script.sh
"""


def _run(argv: list[str], *, timeout_s: int = 60) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, check=False, capture_output=True, timeout=timeout_s)


def _remove_container(name: str) -> None:
    try:
        _run(["docker", "rm", "--force", name], timeout_s=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _parse_markers(output: str) -> dict[str, str]:
    if _START not in output or _END not in output:
        return {}
    bounded = output.split(_START, 1)[1].rsplit(_END, 1)[0]
    tests: dict[str, str] = {}
    for raw_line in bounded.splitlines():
        match = _MARKER.fullmatch(raw_line.strip())
        if match is not None:
            tests[match.group(1).strip()] = match.group(2)
    return tests


class DockerHweVerifier:
    """Execute a candidate without exposing Docker or hidden scripts to the agent runtime."""

    def evaluate(
        self,
        *,
        instance: HweInstance,
        entry: ImageLockEntry,
        node: VerifierNode,
        base_repository: Path,
        candidate_repository: Path,
        artifact_root: Path,
    ) -> VerifierResult:
        started = time.monotonic()
        artifact_dir = artifact_root / node.id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        try:
            inspection = _run(
                ["docker", "image", "inspect", entry.image_id, "--format", "{{json .}}"],
                timeout_s=30,
            )
        except FileNotFoundError:
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.TOOL_NOT_FOUND,
                message="Docker client is unavailable for the selected HWE-Bench image",
            )
        except subprocess.TimeoutExpired:
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.TIMEOUT,
                message="Docker image identity inspection timed out",
            )
        if inspection.returncode != 0:
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.TOOL_NOT_FOUND,
                message="The digest-locked HWE-Bench image is not available locally",
            )
        try:
            image = json.loads(inspection.stdout)
        except json.JSONDecodeError:
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.PARSER_ERROR,
                message="Docker returned malformed image identity metadata",
            )
        if not isinstance(image, dict) or not isinstance(image.get("RepoDigests"), list):
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.PARSER_ERROR,
                message="Docker image identity metadata has an unexpected shape",
            )
        if image.get("Id") != entry.image_id or not any(
            str(value).endswith(f"@{entry.manifest_digest}")
            for value in image.get("RepoDigests", [])
        ):
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.UNSUPPORTED_VERSION,
                message="The local HWE-Bench image differs from the frozen image lock",
            )
        patch = build_repository_patch(base_repository, candidate_repository)
        artifact_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="verigym-hwe-runtime-", dir=artifact_root.parent
        ) as temporary:
            staging = Path(temporary)
            patch_path = staging / "candidate.patch"
            script_path = staging / "tb-script.sh"
            runner_path = staging / "runner.sh"
            patch_path.write_text(patch, encoding="utf-8", newline="")
            script_path.write_text(instance.tb_script, encoding="utf-8", newline="")
            runner_path.write_text(
                _RUNNER.replace("__REPOSITORY_HOME__", entry.repository_home).replace(
                    "__BASE_COMMIT__", entry.base_commit
                ),
                encoding="utf-8",
                newline="",
            )
            container = f"verigym-hwe-{uuid.uuid4().hex[:20]}"
            create = [
                "docker",
                "create",
                "--name",
                container,
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "4096",
                "--memory",
                "16g",
                "--cpus",
                "4",
                "--init",
                "--mount",
                f"type=bind,src={patch_path},dst=/home/verigym-candidate.patch,readonly",
                "--mount",
                f"type=bind,src={script_path},dst=/home/verigym-tb-script.sh,readonly",
                "--mount",
                f"type=bind,src={runner_path},dst=/home/verigym-hwe-run.sh,readonly",
                "--entrypoint",
                "/bin/bash",
                entry.image_id,
                "/home/verigym-hwe-run.sh",
            ]
            try:
                try:
                    created = _run(create, timeout_s=60)
                except subprocess.TimeoutExpired:
                    return self._result(
                        node=node,
                        artifact_dir=artifact_dir,
                        started=started,
                        status=VerifierStatus.ERROR,
                        category=ErrorCategory.TIMEOUT,
                        message="HWE-Bench verifier container creation timed out",
                    )
                if created.returncode != 0:
                    return self._result(
                        node=node,
                        artifact_dir=artifact_dir,
                        started=started,
                        status=VerifierStatus.ERROR,
                        category=ErrorCategory.SANDBOX_ERROR,
                        message="HWE-Bench verifier container creation failed",
                        stdout=created.stdout,
                        stderr=created.stderr,
                    )
                try:
                    executed = _run(
                        ["docker", "start", "--attach", container],
                        timeout_s=node.timeout_s or 900,
                    )
                except subprocess.TimeoutExpired as exc:
                    return self._result(
                        node=node,
                        artifact_dir=artifact_dir,
                        started=started,
                        status=VerifierStatus.ERROR,
                        category=ErrorCategory.TIMEOUT,
                        message="HWE-Bench verifier timed out",
                        stdout=exc.stdout or b"",
                        stderr=exc.stderr or b"",
                    )
            finally:
                _remove_container(container)
        stdout = executed.stdout or b""
        stderr = executed.stderr or b""
        if len(stdout) + len(stderr) > _MAX_OUTPUT_BYTES:
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.OUTPUT_LIMIT,
                message="HWE-Bench verifier output exceeded the bounded capture limit",
                stdout=stdout,
                stderr=stderr,
                exit_code=executed.returncode,
            )
        tests = _parse_markers((stdout + b"\n" + stderr).decode("utf-8", errors="replace"))
        expected_tests = set(instance.expected_test_ids)
        passed = sum(tests.get(name) == "PASS" for name in expected_tests)
        all_passed = (
            set(tests) == expected_tests
            and passed == len(expected_tests)
            and executed.returncode == 0
        )
        return self._result(
            node=node,
            artifact_dir=artifact_dir,
            started=started,
            status=VerifierStatus.PASSED if all_passed else VerifierStatus.FAILED,
            category=ErrorCategory.SUCCESS if all_passed else ErrorCategory.TEST_FAILED,
            message=(
                "All HWE-Bench verifier tests passed"
                if all_passed
                else "The candidate did not satisfy the HWE-Bench verifier"
            ),
            stdout=stdout,
            stderr=stderr,
            exit_code=executed.returncode,
            tests_passed=passed,
            tests_total=len(expected_tests),
            metadata={
                "image_id": entry.image_id,
                "manifest_digest": entry.manifest_digest,
                "network_mode": "none",
                "capabilities_dropped": "all",
                "no_new_privileges": True,
                "container_user": "root",
                "output_persisted": False,
            },
        )

    @staticmethod
    def _result(
        *,
        node: VerifierNode,
        artifact_dir: Path,
        started: float,
        status: VerifierStatus,
        category: ErrorCategory,
        message: str,
        stdout: bytes = b"",
        stderr: bytes = b"",
        exit_code: int | None = None,
        tests_passed: int | None = None,
        tests_total: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> VerifierResult:
        summary = {
            "schema_version": "1.0",
            "status": status.value,
            "error_category": category.value,
            "exit_code": exit_code,
            "tests_passed": tests_passed,
            "tests_total": tests_total,
            "stdout_sha256": hash_bytes(stdout),
            "stderr_sha256": hash_bytes(stderr),
            "raw_output_persisted": False,
            "metadata": metadata or {},
        }
        summary_path = artifact_dir / "result.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return VerifierResult(
            node_id=node.id,
            plugin=node.plugin,
            status=status,
            error_category=category,
            message=message,
            request=node.request,
            duration_s=time.monotonic() - started,
            exit_code=exit_code,
            tests_passed=tests_passed,
            tests_total=tests_total,
            artifacts=[f"{node.id}/result.json"],
            metadata=metadata or {},
        )


__all__ = ["DockerHweVerifier"]
