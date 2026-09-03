#!/usr/bin/env python3
"""Verify a Codex-free CVA6 HWE command image and seal its task-keyed lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import (
    HweAgentImageLock,
    HweCommandImageLock,
    HweCommandSourceLock,
    build_hwe_command_image_lock,
)

_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_DIAGNOSTIC_BYTES = 4096
_SCRATCH_PARENT = Path("/data/jzhu484/Agent/.verigym-tmp")
_EXPECTED_IMAGE_ENVIRONMENT = [
    "PATH=/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME=/tmp/verigym-home",
    "LANG=C.UTF-8",
    "LC_ALL=C.UTF-8",
    "TMPDIR=/tmp",
]
_RG_VERSION = "ripgrep 15.2.0 (rev e89fff89ac)"
_RG_SOURCE = "github.com/BurntSushi/ripgrep/releases/15.2.0"


@dataclass(frozen=True)
class _RepositoryProfile:
    name: str
    runtime_role: str
    verifier_label: str
    source_whiteout_path: str
    source_marker_path: str
    scanner_profile_id: str
    toolchain_profile_id: str
    exact_environment: tuple[str, ...]
    tool_assertions: tuple[tuple[str, int], ...]


_CVA6_PROFILE = _RepositoryProfile(
    name="cva6",
    runtime_role="hwe-cva6-command",
    verifier_label="org.verigym.cva6.verifier_base_image_id",
    source_whiteout_path="/home/cva6",
    source_marker_path="/home/cva6_base_commit.txt",
    scanner_profile_id="cva6-hwe-command-container-native-offline-v2",
    toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
    exact_environment=tuple(_EXPECTED_IMAGE_ENVIRONMENT),
    tool_assertions=(
        ("make --version >/tmp/make-version", 80),
        ("/tools/verilator/bin/verilator_bin --version >/tmp/verilator-bin-version", 81),
        ("VERILATOR_ROOT=/tools/verilator verilator --version >/tmp/verilator-version", 82),
    ),
)
_IBEX_PROFILE = _RepositoryProfile(
    name="ibex",
    runtime_role="hwe-ibex-command",
    verifier_label="org.verigym.ibex.verifier_base_image_id",
    source_whiteout_path="/home/ibex",
    source_marker_path="/home/ibex_base_commit.txt",
    scanner_profile_id="ibex-hwe-command-container-native-offline-v1",
    toolchain_profile_id="ibex-iverilog-container-native-v1",
    exact_environment=(
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "HOME=/tmp/verigym-home",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "TMPDIR=/tmp",
    ),
    tool_assertions=(
        ("make --version >/tmp/make-version", 80),
        ("iverilog -V >/tmp/iverilog-version 2>/tmp/iverilog-stderr", 83),
        ("vvp -V >/tmp/vvp-version 2>/tmp/vvp-stderr", 84),
    ),
)
_IBEX_VERILATOR_PROFILE = _RepositoryProfile(
    name="ibex-verilator",
    runtime_role="hwe-ibex-command",
    verifier_label="org.verigym.ibex.verifier_base_image_id",
    source_whiteout_path="/home/ibex",
    source_marker_path="/home/ibex_base_commit.txt",
    scanner_profile_id="ibex-hwe-command-container-native-offline-v2",
    toolchain_profile_id="ibex-verilator-system-container-native-v1",
    exact_environment=_IBEX_PROFILE.exact_environment,
    tool_assertions=(
        ("make --version >/tmp/make-version", 80),
        ("/usr/bin/verilator_bin --version >/tmp/verilator-bin-version", 81),
        ("/usr/bin/verilator --version >/tmp/verilator-version", 82),
    ),
)
_REPOSITORY_PROFILES = {
    "cva6": _CVA6_PROFILE,
    "ibex": _IBEX_PROFILE,
    "ibex-verilator": _IBEX_VERILATOR_PROFILE,
}
_IBEX_SCRATCH_PARENT = Path("/data2/jiadongzhu/Agent/.verigym-tmp")
_ASSERTION_EXIT_CODES = {
    41: "rootfs_write_rejected",
    42: "codex_command_absent",
    61: "non_root_identity",
    62: "source_whiteout_directory_present",
    63: "source_whiteout_empty",
    64: "legacy_source_marker_absent",
    65: "verifier_workspace_absent",
    66: "public_payload_absent",
    67: "hidden_verifier_absent",
    68: "reference_patch_absent",
    69: "codex_executable_absent",
    70: "codex_library_absent",
    71: "codex_auth_absent",
    72: "workspace_writable",
    73: "tmp_writable",
    74: "container_parent_readable",
    75: "repository_parent_visible",
    76: "absolute_toolchain_readable",
    77: "ripgrep_hash_exact",
    78: "ripgrep_version_exact",
    79: "keepalive_available",
    80: "make_available",
    81: "verilator_binary_available",
    82: "verilator_wrapper_available",
    83: "iverilog_available",
    84: "vvp_available",
    90: "allowlisted_artifact_hash_exact",
}
_ERROR_CATEGORIES = frozenset(
    {
        "container_assertion_failed",
        "container_cleanup_failed",
        "container_command_failed",
        "container_controls_invalid",
        "container_inspect_failed",
        "diagnostic_output_over_bound",
        "docker_create_failed",
        "docker_create_output_invalid",
        "docker_start_failed",
        "docker_start_timeout",
        "unexpected_command_output",
        "unknown",
        "workspace_cleanup_failed",
        "workspace_proof_missing",
    }
)
_FAILURE_STAGES = frozenset(
    {
        "container_cleanup",
        "container_control_inspection",
        "container_diagnostic_start",
        "container_state_inspection",
        "docker_create",
        "unknown",
        "workspace_cleanup",
        "workspace_proof_validation",
    }
)


class CommandImageScanFailure(RuntimeError):
    """A scan failure carrying only bounded, content-free diagnostics."""

    def __init__(self, diagnostic: dict[str, Any]) -> None:
        super().__init__("HWE command-image container scan failed")
        self.diagnostic = diagnostic


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-profile",
        choices=sorted(_REPOSITORY_PROFILES),
        default="cva6",
    )
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--identity-lock", type=Path, required=True)
    parser.add_argument("--security-scan-output", type=Path, required=True)
    parser.add_argument("--lock-output", type=Path, required=True)
    parser.add_argument("--runtime-scratch-parent", type=Path)
    return parser


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"unsafe HWE command-image JSON input: {path.name}")
    resolved = path.resolve(strict=True)
    if resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError(f"unsafe HWE command-image JSON input: {path.name}")
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"HWE command-image JSON input is not an object: {path.name}")
    return value


def _run(arguments: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _inspect(reference: str) -> dict[str, Any]:
    values = json.loads(_run(["docker", "image", "inspect", reference], timeout=30).stdout)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise RuntimeError("Docker returned malformed HWE command-image inspection data")
    return values[0]


def _environment_map(values: object) -> dict[str, str]:
    if not isinstance(values, list):
        return {}
    result: dict[str, str] = {}
    for value in values:
        name, separator, content = str(value).partition("=")
        if not separator or name in result:
            return {}
        result[name] = content
    return result


def _bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    return value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")


def _stream_receipt(stdout: bytes | str | None, stderr: bytes | str | None) -> dict[str, Any]:
    stdout_bytes = _bytes(stdout)
    stderr_bytes = _bytes(stderr)
    empty = hashlib.sha256(b"").hexdigest()
    return {
        "stdout_bytes": len(stdout_bytes),
        "stderr_bytes": len(stderr_bytes),
        "stdout_sha256": empty if not stdout_bytes else None,
        "stderr_sha256": empty if not stderr_bytes else None,
        "nonempty_output_hashed": False,
        "output_within_bound": (
            len(stdout_bytes) <= _MAX_DIAGNOSTIC_BYTES
            and len(stderr_bytes) <= _MAX_DIAGNOSTIC_BYTES
        ),
    }


def _empty_diagnostic() -> dict[str, Any]:
    empty = hashlib.sha256(b"").hexdigest()
    return {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_command_image_diagnostic_v2",
        "status": "running",
        "failure_stage": None,
        "error_category": None,
        "assertion_id": None,
        "create_exit_code": None,
        "create_stdout_bytes": 0,
        "create_stderr_bytes": 0,
        "create_stdout_sha256": empty,
        "create_stderr_sha256": empty,
        "create_nonempty_output_hashed": False,
        "create_output_within_bound": True,
        "exit_code": None,
        "container_exit_code": None,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "stdout_sha256": empty,
        "stderr_sha256": empty,
        "nonempty_output_hashed": False,
        "output_within_bound": True,
        "cleanup_exit_code": None,
        "cleanup_stdout_bytes": 0,
        "cleanup_stderr_bytes": 0,
        "cleanup_stdout_sha256": empty,
        "cleanup_stderr_sha256": empty,
        "cleanup_nonempty_output_hashed": False,
        "cleanup_output_within_bound": True,
        "temporary_container_created": False,
        "temporary_container_removed": False,
        "temporary_workspace_removed": False,
        "raw_output_persisted": False,
    }


def _seal_diagnostic(value: dict[str, Any]) -> dict[str, Any]:
    base = {key: item for key, item in value.items() if key != "diagnostic_hash"}
    if (
        base.get("error_category") is not None
        and base.get("error_category") not in _ERROR_CATEGORIES
    ):
        base["error_category"] = "unknown"
        base["assertion_id"] = None
    if base.get("failure_stage") is not None and base.get("failure_stage") not in _FAILURE_STAGES:
        base["failure_stage"] = "unknown"
    if (
        base.get("error_category") != "container_assertion_failed"
        or base.get("assertion_id") not in _ASSERTION_EXIT_CODES.values()
    ):
        base["assertion_id"] = None
    empty = hashlib.sha256(b"").hexdigest()
    for prefix in ("create_", "", "cleanup_"):
        for stream in ("stdout", "stderr"):
            count = base.get(f"{prefix}{stream}_bytes")
            base[f"{prefix}{stream}_sha256"] = empty if count == 0 else None
        base[f"{prefix}nonempty_output_hashed"] = False
    return {**base, "diagnostic_hash": content_hash(base)}


def _checked(command: str, exit_code: int) -> str:
    return f"{command} || exit {exit_code}"


def _container_scan(
    image_id: str,
    *,
    user: str,
    rg_sha256: str,
    artifacts: list[dict[str, Any]],
    profile: _RepositoryProfile = _CVA6_PROFILE,
    runtime_scratch_parent: Path | None = None,
) -> tuple[dict[str, bool], dict[str, Any]]:
    assertions = [
        _checked(f'test "$(id -u):$(id -g)" = "{user}"', 61),
        _checked(f"test -d {shlex.quote(profile.source_whiteout_path)}", 62),
        _checked(
            'test -z "$(find '
            f"{shlex.quote(profile.source_whiteout_path)} "
            '-mindepth 1 -maxdepth 1 -print -quit)"',
            63,
        ),
        _checked(f"test ! -e {shlex.quote(profile.source_marker_path)}", 64),
        _checked("test ! -e /workspace/verifier", 65),
        _checked("test ! -e /verigym-public", 66),
        _checked("test ! -e /hidden-verifier", 67),
        _checked("test ! -e /reference.patch", 68),
        _checked("test ! -e /usr/local/bin/codex", 69),
        _checked("test ! -e /usr/local/lib/codex", 70),
        _checked("test ! -e /root/.codex/auth.json", 71),
        "if command -v codex >/dev/null 2>&1; then exit 42; fi",
        "if touch /verigym-rootfs-write 2>/dev/null; then exit 41; fi",
        _checked("touch /workspace/repository/workspace-proof", 72),
        _checked("touch /tmp/ephemeral-proof", 73),
        _checked("find .. -maxdepth 2 -print >/tmp/parent-read", 74),
        _checked("grep -q ../repository /tmp/parent-read", 75),
        _checked("sed -n '1p' /etc/os-release >/tmp/absolute-read", 76),
        _checked(f'test "$(sha256sum /usr/local/bin/rg | cut -c1-64)" = "{rg_sha256}"', 77),
        _checked(f'test "$(rg --version | head -n 1)" = "{_RG_VERSION}"', 78),
        _checked("test -x /usr/bin/tail", 79),
    ]
    assertions.extend(
        _checked(command, exit_code) for command, exit_code in profile.tool_assertions
    )
    assertions.extend(
        _checked(
            'test "$(sha256sum -- '
            f'{shlex.quote(str(item["path"]))} | cut -c1-64)" = '
            f"{shlex.quote(str(item['sha256']))}",
            90,
        )
        for item in artifacts
    )
    command = "\n".join(("set -u", *assertions))
    if runtime_scratch_parent is None:
        scratch_parent = _SCRATCH_PARENT if profile.name == "cva6" else _IBEX_SCRATCH_PARENT
        scratch_parent.mkdir(parents=True, exist_ok=True)
    else:
        unresolved = Path(os.path.abspath(runtime_scratch_parent))
        if (
            not runtime_scratch_parent.is_absolute()
            or runtime_scratch_parent.is_symlink()
            or not runtime_scratch_parent.is_dir()
        ):
            raise ValueError("HWE command-image runtime scratch parent is unsafe")
        scratch_parent = runtime_scratch_parent.resolve(strict=True)
        if scratch_parent != unresolved or scratch_parent.stat().st_uid != os.getuid():
            raise ValueError("HWE command-image runtime scratch parent is unsafe")
    workspace = Path(tempfile.mkdtemp(prefix="hwe-command-image-scan.", dir=scratch_parent))
    container_id: str | None = None
    checks: dict[str, bool] = {}
    diagnostic = _empty_diagnostic()
    failure: BaseException | None = None
    phase = "docker_create"
    try:
        create = [
            "docker",
            "create",
            "--network",
            "none",
            "--ipc",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=1073741824,mode=1777",
            "--user",
            user,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--init",
            "--memory",
            str(16 * 1024**3),
            "--memory-swap",
            str(16 * 1024**3),
            "--cpus",
            "4",
            "--pids-limit",
            "4096",
            "--workdir",
            "/workspace/repository",
        ]
        for entry in profile.exact_environment:
            create.extend(("--env", entry))
        create.extend(
            (
                "--mount",
                f"type=bind,src={workspace},dst=/workspace/repository",
                image_id,
                "/bin/sh",
                "-c",
                command,
            )
        )
        created = subprocess.run(create, check=False, capture_output=True, timeout=60)
        create_streams = _stream_receipt(created.stdout, created.stderr)
        diagnostic.update(
            {
                "create_exit_code": created.returncode,
                **{f"create_{key}": value for key, value in create_streams.items()},
            }
        )
        if not create_streams["output_within_bound"]:
            diagnostic["error_category"] = "diagnostic_output_over_bound"
            raise RuntimeError("HWE command-image Docker create output exceeded its bound")
        if created.returncode != 0:
            diagnostic["error_category"] = "docker_create_failed"
            raise RuntimeError("HWE command-image Docker create failed")
        try:
            container_id = _bytes(created.stdout).decode("ascii", errors="strict").strip()
        except UnicodeError as exc:
            diagnostic["error_category"] = "docker_create_output_invalid"
            raise RuntimeError("HWE command-image Docker create output was malformed") from exc
        if not container_id or any(character.isspace() for character in container_id):
            diagnostic["error_category"] = "docker_create_output_invalid"
            raise RuntimeError("HWE command-image Docker create returned no container ID")
        diagnostic["temporary_container_created"] = True
        phase = "container_control_inspection"
        inspection_values = json.loads(
            _run(["docker", "container", "inspect", container_id], timeout=30).stdout
        )
        if (
            not isinstance(inspection_values, list)
            or len(inspection_values) != 1
            or not isinstance(inspection_values[0], dict)
        ):
            diagnostic["error_category"] = "container_inspect_failed"
            raise RuntimeError("HWE command-image container inspection was malformed")
        inspection = inspection_values[0]
        host = inspection["HostConfig"]
        config = inspection["Config"]
        mounts = inspection["Mounts"]
        checks.update(
            {
                "network_none": host["NetworkMode"] == "none",
                "ipc_private": host["IpcMode"] == "none",
                "read_only_rootfs": host["ReadonlyRootfs"] is True,
                "cap_drop_all": "ALL" in host["CapDrop"],
                "no_new_privileges": any(
                    value.startswith("no-new-privileges") for value in host["SecurityOpt"]
                ),
                "private_pid_namespace": host["PidMode"] == "",
                "bounded_resources": (
                    host["Memory"] == 16 * 1024**3
                    and host["MemorySwap"] == 16 * 1024**3
                    and host["NanoCpus"] == 4_000_000_000
                    and host["PidsLimit"] == 4096
                ),
                "single_visible_workspace_mount": (
                    len(mounts) == 1
                    and mounts[0]["Destination"] == "/workspace/repository"
                    and mounts[0]["RW"] is True
                ),
                "exact_environment": (
                    len(config["Env"]) == len(profile.exact_environment)
                    and _environment_map(config["Env"])
                    == _environment_map(list(profile.exact_environment))
                ),
                "non_root_identity": config["User"] == user,
            }
        )
        if not all(checks.values()):
            diagnostic["error_category"] = "container_controls_invalid"
            raise RuntimeError("HWE command container controls differ from the lock")
        phase = "container_diagnostic_start"
        try:
            started = subprocess.run(
                ["docker", "start", "--attach", container_id],
                check=False,
                capture_output=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            diagnostic.update(_stream_receipt(exc.stdout, exc.stderr))
            diagnostic["error_category"] = "docker_start_timeout"
            raise RuntimeError("HWE command-image diagnostic scan timed out") from exc
        diagnostic.update(
            {
                "exit_code": started.returncode,
                **_stream_receipt(started.stdout, started.stderr),
            }
        )
        if not diagnostic["output_within_bound"]:
            diagnostic["error_category"] = "diagnostic_output_over_bound"
            raise RuntimeError("HWE command-image diagnostic output exceeded its bound")
        phase = "container_state_inspection"
        state_values = json.loads(
            _run(["docker", "container", "inspect", container_id], timeout=30).stdout
        )
        if (
            not isinstance(state_values, list)
            or len(state_values) != 1
            or not isinstance(state_values[0], dict)
            or not isinstance(state_values[0].get("State"), dict)
            or type(state_values[0]["State"].get("ExitCode")) is not int
        ):
            diagnostic["error_category"] = "container_inspect_failed"
            raise RuntimeError("HWE command-image container state was malformed")
        container_exit_code = int(state_values[0]["State"]["ExitCode"])
        diagnostic["container_exit_code"] = container_exit_code
        if started.returncode != 0 or container_exit_code != 0:
            if container_exit_code in _ASSERTION_EXIT_CODES:
                diagnostic["error_category"] = "container_assertion_failed"
                diagnostic["assertion_id"] = _ASSERTION_EXIT_CODES[container_exit_code]
            elif container_exit_code != 0 and started.returncode == container_exit_code:
                diagnostic["error_category"] = "container_command_failed"
            else:
                diagnostic["error_category"] = "docker_start_failed"
            raise RuntimeError("HWE command-image diagnostic scan exited unsuccessfully")
        if diagnostic["stdout_bytes"] or diagnostic["stderr_bytes"]:
            diagnostic["error_category"] = "unexpected_command_output"
            raise RuntimeError("HWE command-image scan unexpectedly emitted command output")
        phase = "workspace_proof_validation"
        if not (workspace / "workspace-proof").is_file():
            diagnostic["error_category"] = "workspace_proof_missing"
            raise RuntimeError("HWE command-image workspace was not writable")
        checks.update(
            {
                "source_whiteout_empty": True,
                "container_native_parent_read": True,
                "container_native_absolute_read": True,
                "codex_absent": True,
                "rg_hash_exact": True,
                "rg_version_exact": True,
                "keepalive_available": True,
                "make_available": True,
                "toolchain_available": True,
                "hidden_reference_verifier_assets_absent": True,
                "rootfs_write_rejected": True,
                "tmp_ephemeral": not (workspace / "ephemeral-proof").exists(),
            }
        )
        if not all(checks.values()):
            diagnostic["error_category"] = "workspace_proof_missing"
            raise RuntimeError("HWE command-image post-run checks failed")
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
        diagnostic["failure_stage"] = phase
        diagnostic["error_category"] = diagnostic["error_category"] or {
            "docker_create": "docker_create_failed",
            "container_control_inspection": "container_inspect_failed",
            "container_diagnostic_start": "docker_start_failed",
            "container_state_inspection": "container_inspect_failed",
            "workspace_proof_validation": "workspace_proof_missing",
        }.get(phase, "unknown")
    if container_id:
        try:
            removed = subprocess.run(
                ["docker", "container", "rm", "--force", container_id],
                check=False,
                capture_output=True,
                timeout=30,
            )
            cleanup_streams = _stream_receipt(removed.stdout, removed.stderr)
            diagnostic.update(
                {
                    "cleanup_exit_code": removed.returncode,
                    **{f"cleanup_{key}": value for key, value in cleanup_streams.items()},
                }
            )
            if removed.returncode != 0 or not cleanup_streams["output_within_bound"]:
                raise RuntimeError("HWE command-image temporary container cleanup failed")
            diagnostic["temporary_container_removed"] = True
        except (Exception, KeyboardInterrupt) as exc:
            failure = exc
            diagnostic["failure_stage"] = "container_cleanup"
            diagnostic["error_category"] = "container_cleanup_failed"
    try:
        shutil.rmtree(workspace)
        diagnostic["temporary_workspace_removed"] = True
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
        diagnostic["failure_stage"] = "workspace_cleanup"
        diagnostic["error_category"] = "workspace_cleanup_failed"
    if failure is not None:
        diagnostic["status"] = "failed"
        raise CommandImageScanFailure(_seal_diagnostic(diagnostic)) from None
    diagnostic.update(
        {
            "status": "passed",
            "failure_stage": None,
            "error_category": None,
            "assertion_id": None,
        }
    )
    return checks, _seal_diagnostic(diagnostic)


def scan_and_lock(
    *,
    receipt_path: Path,
    identity_lock_path: Path,
    security_output: Path,
    lock_output: Path,
    repository_profile: str = "cva6",
    runtime_scratch_parent: Path | None = None,
) -> tuple[dict[str, Any], HweCommandImageLock]:
    if security_output.exists() or lock_output.exists():
        raise ValueError("HWE command-image scan and lock outputs must be new paths")
    try:
        profile = _REPOSITORY_PROFILES[repository_profile]
    except KeyError as exc:
        raise ValueError("unsupported HWE command-image repository profile") from exc
    receipt = _load_json(receipt_path)
    raw_identity = _load_json(identity_lock_path)
    identity: HweAgentImageLock | HweCommandSourceLock
    if raw_identity.get("format_id") == "verigym_hwe_command_source_lock_v1":
        identity = HweCommandSourceLock.model_validate(raw_identity)
    else:
        # Historical v32/v33 materializations remain byte-for-byte compatible.
        identity = HweAgentImageLock.model_validate(raw_identity)
    expected_receipt = {
        "format_id": "verigym_hwe_command_image_build_receipt_v1",
        "task_id": identity.task_id,
        "verifier_base_image_id": identity.verifier_base_image_id,
        "rg_version": _RG_VERSION,
        "rg_source": _RG_SOURCE,
        "codex_present": False,
        "collection_profile_id": "hwe_standard_v2",
        "tool_contract_id": "hwe_native_shell_v2",
        "command_protocol": "hwe_command_image_v1",
        "source_whiteout_path": profile.source_whiteout_path,
        "exact_image_environment": list(profile.exact_environment),
    }
    if any(receipt.get(key) != value for key, value in expected_receipt.items()):
        raise ValueError("HWE command-image receipt differs from the frozen task identity")
    receipt_toolchain = receipt.get("toolchain_profile_id")
    if receipt_toolchain is not None and receipt_toolchain != profile.toolchain_profile_id:
        raise ValueError("HWE command-image receipt toolchain differs from the scanner profile")
    for key in (
        "derived_command_image_id",
        "unsanitized_command_image_id",
        "rg_sha256",
        "rg_release_archive_sha256",
        "configuration_sanitizer_sha256",
    ):
        if not isinstance(receipt.get(key), str):
            raise ValueError("HWE command-image receipt lacks a required identity")

    image_id = str(receipt["derived_command_image_id"])
    unsanitized_id = str(receipt["unsanitized_command_image_id"])
    rg_sha256 = str(receipt["rg_sha256"])
    image = _inspect(image_id)
    unsanitized = _inspect(unsanitized_id)
    labels = image["Config"].get("Labels") or {}
    required_labels = {
        "org.verigym.runtime.role": profile.runtime_role,
        "org.verigym.collection.profile": "hwe_standard_v2",
        "org.verigym.tool.contract": "hwe_native_shell_v2",
        "org.verigym.command.protocol": "hwe_command_image_v1",
        "org.verigym.command.rg.version": _RG_VERSION,
        "org.verigym.command.rg.sha256": rg_sha256,
        "org.verigym.command.rg.release_archive.sha256": receipt["rg_release_archive_sha256"],
        "org.verigym.hwe.task_id": identity.task_id,
        profile.verifier_label: identity.verifier_base_image_id,
        "org.verigym.codex.present": "absent",
        "org.verigym.provider_credentials": "absent",
        "org.verigym.hidden_assets": "absent",
        "org.verigym.reference_patch": "absent",
        "org.verigym.verifier_payload": "absent",
    }
    if receipt_toolchain is not None:
        required_labels["org.verigym.ibex.toolchain.profile"] = {
            "ibex-iverilog-container-native-v1": "iverilog",
            "ibex-verilator-system-container-native-v1": "verilator",
        }.get(profile.toolchain_profile_id, "")
    image_checks = {
        "image_identity": image.get("Id") == image_id,
        "rootfs_layer_identity_preserved": image.get("RootFS") == unsanitized.get("RootFS"),
        "image_environment_exact": image["Config"].get("Env") == list(profile.exact_environment),
        "image_user_exact": image["Config"].get("User") == f"{os.getuid()}:{os.getgid()}",
        "image_declares_no_volumes": image["Config"].get("Volumes") in (None, {}),
        "image_default_command_is_inert": image["Config"].get("Cmd")
        == ["/usr/bin/tail", "-f", "/dev/null"],
        "required_labels": all(labels.get(key) == value for key, value in required_labels.items()),
    }
    if not all(image_checks.values()):
        raise RuntimeError("HWE command-image configuration scan failed")
    artifacts = [
        item.model_dump(mode="json")
        for item in identity.allowlisted_artifacts
        if not item.path.startswith("/usr/local/lib/codex/")
    ]
    artifacts.append(
        {
            "path": "/usr/local/lib/verigym-command-tools/rg",
            "sha256": rg_sha256,
            "role": "public_asset",
        }
    )
    try:
        runtime_checks, diagnostic = _container_scan(
            image_id,
            user=f"{os.getuid()}:{os.getgid()}",
            rg_sha256=rg_sha256,
            artifacts=artifacts,
            profile=profile,
            runtime_scratch_parent=runtime_scratch_parent,
        )
    except CommandImageScanFailure as exc:
        failure_base = {
            "schema_version": "1.0",
            "format_id": "verigym_hwe_command_image_security_scan_v2",
            "scanner_profile_id": profile.scanner_profile_id,
            "task_id": identity.task_id,
            "verifier_base_image_id": identity.verifier_base_image_id,
            "derived_command_image_id": image_id,
            "unsanitized_command_image_id": unsanitized_id,
            "diagnostic": exc.diagnostic,
            "secrets_detected": False,
            "scan_passed": False,
        }
        failure_scan = {**failure_base, "security_scan_id": content_hash(failure_base)}
        security_output.parent.mkdir(parents=True, exist_ok=True)
        atomic_dump_json(security_output, failure_scan)
        raise RuntimeError("HWE command-image runtime security scan failed") from None
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_command_image_security_scan_v2",
        "scanner_profile_id": profile.scanner_profile_id,
        "task_id": identity.task_id,
        "verifier_base_image_id": identity.verifier_base_image_id,
        "derived_command_image_id": image_id,
        "unsanitized_command_image_id": unsanitized_id,
        "configuration_sanitizer_sha256": receipt["configuration_sanitizer_sha256"],
        "rg_source": _RG_SOURCE,
        "rg_release_archive_sha256": receipt["rg_release_archive_sha256"],
        "exact_image_environment": list(profile.exact_environment),
        "runtime_controls": {
            "network_mode": "none",
            "read_only_rootfs": True,
            "run_as_user": f"{os.getuid()}:{os.getgid()}",
            "cap_drop_all": True,
            "no_new_privileges": True,
            "pids_limit": 4096,
            "single_visible_workspace_mount": True,
            "container_native_read_scope": True,
            "codex_dependency": False,
        },
        "toolchain_artifacts": artifacts,
        "checks": {**image_checks, **runtime_checks},
        "diagnostic": diagnostic,
        "secrets_detected": False,
        "scan_passed": True,
    }
    scan = {**base, "security_scan_id": content_hash(base)}
    lock = build_hwe_command_image_lock(
        task_id=identity.task_id,
        task_hash=identity.task_hash,
        source_hash=identity.source_hash,
        verifier_base_image_id=identity.verifier_base_image_id,
        derived_command_image_id=image_id,
        rg_sha256=rg_sha256,
        rg_release_archive_sha256=receipt["rg_release_archive_sha256"],
        toolchain_profile_id=profile.toolchain_profile_id,
        allowlisted_artifacts=artifacts,
        source_whiteout_path=profile.source_whiteout_path,
        security_scan_id=scan["security_scan_id"],
    )
    security_output.parent.mkdir(parents=True, exist_ok=True)
    lock_output.parent.mkdir(parents=True, exist_ok=True)
    atomic_dump_json(security_output, scan)
    atomic_dump_json(lock_output, lock.model_dump(mode="json"))
    return scan, lock


def main() -> int:
    arguments = _parser().parse_args()
    scan, lock = scan_and_lock(
        receipt_path=arguments.receipt,
        identity_lock_path=arguments.identity_lock,
        security_output=arguments.security_scan_output,
        lock_output=arguments.lock_output,
        repository_profile=arguments.repository_profile,
        runtime_scratch_parent=arguments.runtime_scratch_parent,
    )
    print(
        json.dumps(
            {
                "task_id": lock.task_id,
                "derived_command_image_id": lock.derived_command_image_id,
                "security_scan_id": scan["security_scan_id"],
                "lock_hash": lock.lock_hash,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
