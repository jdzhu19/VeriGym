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
    content_hash,
    hash_bytes,
)

from .models import (
    HweInstance,
    ImageLockEntryType,
    ImageLockEntryV2,
    VerifierDependencyFile,
    base_commit_marker,
    repository_profile,
)

_START = "HWE_BENCH_RESULTS_START"
_END = "HWE_BENCH_RESULTS_END"
_CACHE_READY = "VERIGYM_HWE_CACHE_SEED_OK"
_MARKER = re.compile(r"^TEST:\s*(.{1,256}?)\s*\.\.\.\s*(PASS|FAIL|SKIP)\s*$")

_RUNNER = """#!/bin/bash
set -euo pipefail
__CACHE_SEED__
cd __REPOSITORY_HOME__
git reset --hard >/dev/null
git clean -fdx >/dev/null
test -f __BASE_COMMIT_MARKER__
test "$(cat __BASE_COMMIT_MARKER__)" = "__BASE_COMMIT__"
git checkout "$(cat __BASE_COMMIT_MARKER__)" >/dev/null
if [[ -s /home/verigym-candidate.patch ]]; then
  git apply --check /home/verigym-candidate.patch
  git apply /home/verigym-candidate.patch
fi
bash /home/verigym-tb-script.sh
"""


def _render_runner(entry: ImageLockEntryType) -> str:
    marker = (
        entry.base_commit_marker
        if isinstance(entry, ImageLockEntryV2)
        else base_commit_marker(entry.repository_home)
    )
    return (
        _RUNNER.replace(
            "__CACHE_SEED__",
            (
                f"bash /home/verigym-cache-seed.sh\nprintf '{_CACHE_READY}\\n'"
                if isinstance(entry, ImageLockEntryV2) and entry.verifier_dependencies
                else ":"
            ),
        )
        .replace("__REPOSITORY_HOME__", entry.repository_home)
        .replace("__BASE_COMMIT_MARKER__", marker)
        .replace("__BASE_COMMIT__", entry.base_commit)
    )


def _render_cache_seed(dependencies: list[VerifierDependencyFile]) -> str:
    lines = ["#!/bin/bash", "set -euo pipefail"]
    for dependency in dependencies:
        source = f"/home/verigym-dependencies/{dependency.cache_path}"
        target = f"/tools/coursier/{dependency.cache_path}"
        filename = dependency.cache_path.rsplit("/", 1)[1]
        directory = target.rsplit("/", 1)[0]
        lines.extend(
            [
                f'test ! -L "{source}"',
                f'test -f "{source}"',
                f'test "$(stat -c %s "{source}")" = "{dependency.size_bytes}"',
                f'observed="$(sha256sum "{source}")"',
                f'test "${{observed%% *}}" = "{dependency.sha256}"',
                f'mkdir -p "{directory}"',
                f'install -m 0644 "{source}" "{target}"',
                f': > "{directory}/.{filename}.checked"',
                f'observed="$(md5sum "{target}")"',
                f'printf %s "${{observed%% *}}" > "{directory}/.{filename}__md5"',
                f'observed="$(sha1sum "{target}")"',
                f'printf %s "${{observed%% *}}" > "{directory}/.{filename}__sha1"',
            ]
        )
    return "\n".join(lines) + "\n"


def _run(argv: list[str], *, timeout_s: int = 60) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, check=False, capture_output=True, timeout=timeout_s)


def _remove_container(name: str) -> None:
    try:
        _run(["docker", "rm", "--force", name], timeout_s=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _remove_volume(name: str) -> bool:
    """Remove one verifier-owned volume after Docker releases its final mount."""

    attempts = 3
    for attempt in range(attempts):
        try:
            removed = _run(["docker", "volume", "rm", name], timeout_s=30)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        if removed.returncode == 0:
            return True
        if attempt + 1 < attempts:
            time.sleep(0.25)
    return False


def _validate_dependency_root(
    root: Path | None, dependencies: list[VerifierDependencyFile]
) -> Path | None:
    if not dependencies:
        if root is not None:
            raise ValueError("unexpected verifier dependency root")
        return None
    if root is None or root.is_symlink() or not root.is_dir():
        raise ValueError("verifier dependency root is missing or unsafe")
    resolved_root = root.resolve(strict=True)
    for dependency in dependencies:
        path = root / dependency.cache_path
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve(strict=True).is_relative_to(resolved_root)
            or path.stat().st_size != dependency.size_bytes
            or hash_bytes(path.read_bytes()) != dependency.sha256
        ):
            raise ValueError("verifier dependency differs from its frozen inventory")
    return resolved_root


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
        entry: ImageLockEntryType,
        node: VerifierNode,
        base_repository: Path,
        candidate_repository: Path,
        artifact_root: Path,
        verifier_dependency_root: Path | None = None,
    ) -> VerifierResult:
        started = time.monotonic()
        profile = repository_profile(instance.repository_id)
        artifact_dir = artifact_root / node.id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        dependencies = entry.verifier_dependencies if isinstance(entry, ImageLockEntryV2) else []
        try:
            dependency_root = _validate_dependency_root(verifier_dependency_root, dependencies)
        except (OSError, ValueError):
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.INVALID_REQUEST,
                message="Frozen HWE-Bench verifier dependencies are unavailable or changed",
            )
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
            seed_path = staging / "cache-seed.sh"
            patch_path.write_text(patch, encoding="utf-8", newline="")
            script_path.write_text(instance.tb_script, encoding="utf-8", newline="")
            runner_path.write_text(
                _render_runner(entry),
                encoding="utf-8",
                newline="",
            )
            if dependencies:
                seed_path.write_text(_render_cache_seed(dependencies), encoding="utf-8", newline="")
            container = f"verigym-hwe-{uuid.uuid4().hex[:20]}"
            cache_volume: str | None = None
            cache_mounts: list[str] = []
            if dependencies:
                assert dependency_root is not None
                cache_volume = f"verigym-hwe-cache-{uuid.uuid4().hex[:20]}"
                try:
                    volume_created = _run(
                        [
                            "docker",
                            "volume",
                            "create",
                            "--label",
                            "verigym.owner=hwe-verifier",
                            cache_volume,
                        ],
                        timeout_s=60,
                    )
                except subprocess.TimeoutExpired:
                    _remove_volume(cache_volume)
                    return self._result(
                        node=node,
                        artifact_dir=artifact_dir,
                        started=started,
                        status=VerifierStatus.ERROR,
                        category=ErrorCategory.TIMEOUT,
                        message="HWE-Bench verifier cache volume creation timed out",
                    )
                if volume_created.returncode != 0:
                    _remove_volume(cache_volume)
                    return self._result(
                        node=node,
                        artifact_dir=artifact_dir,
                        started=started,
                        status=VerifierStatus.ERROR,
                        category=ErrorCategory.SANDBOX_ERROR,
                        message="HWE-Bench verifier cache volume creation failed",
                        stdout=volume_created.stdout,
                        stderr=volume_created.stderr,
                    )
                cache_mounts = [
                    "--mount",
                    f"type=volume,src={cache_volume},dst=/tools/coursier",
                    "--mount",
                    (f"type=bind,src={dependency_root},dst=/home/verigym-dependencies,readonly"),
                    "--mount",
                    f"type=bind,src={seed_path},dst=/home/verigym-cache-seed.sh,readonly",
                ]
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
                str(profile.verifier_limits.pids_limit),
                "--memory",
                str(profile.verifier_limits.memory_bytes),
                "--cpus",
                str(profile.verifier_limits.cpus),
                "--init",
                "--mount",
                f"type=bind,src={patch_path},dst=/home/verigym-candidate.patch,readonly",
                "--mount",
                f"type=bind,src={script_path},dst=/home/verigym-tb-script.sh,readonly",
                "--mount",
                f"type=bind,src={runner_path},dst=/home/verigym-hwe-run.sh,readonly",
                *cache_mounts,
                "--entrypoint",
                "/bin/bash",
                entry.image_id,
                "/home/verigym-hwe-run.sh",
            ]
            cache_volume_removed = cache_volume is None
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
                if cache_volume is not None:
                    cache_volume_removed = _remove_volume(cache_volume)
        if not cache_volume_removed:
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.SANDBOX_ERROR,
                message="HWE-Bench verifier cache volume cleanup failed",
            )
        stdout = executed.stdout or b""
        stderr = executed.stderr or b""
        combined_output = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
        if dependencies and _CACHE_READY not in combined_output:
            return self._result(
                node=node,
                artifact_dir=artifact_dir,
                started=started,
                status=VerifierStatus.ERROR,
                category=ErrorCategory.SANDBOX_ERROR,
                message="HWE-Bench verifier cache initialization failed",
                stdout=stdout,
                stderr=stderr,
                exit_code=executed.returncode,
            )
        if len(stdout) + len(stderr) > profile.verifier_limits.max_output_bytes:
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
        tests = _parse_markers(combined_output)
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
                "dependency_count": len(dependencies),
                "dependency_inventory_hash": content_hash(dependencies),
                "ephemeral_cache_volume": bool(dependencies),
                "cache_volume_removed": cache_volume_removed,
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
