#!/usr/bin/env python3
"""Verify a Codex-free CVA6 HWE command image and seal its task-keyed lock."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import (
    HweAgentImageLock,
    HweCommandImageLock,
    build_hwe_command_image_lock,
)

_MAX_JSON_BYTES = 16 * 1024 * 1024
_EXPECTED_IMAGE_ENVIRONMENT = [
    "PATH=/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME=/tmp/verigym-home",
    "LANG=C.UTF-8",
    "LC_ALL=C.UTF-8",
    "TMPDIR=/tmp",
]
_RG_VERSION = "ripgrep 15.2.0 (rev e89fff89ac)"
_RG_SOURCE = "github.com/BurntSushi/ripgrep/releases/15.2.0"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--identity-lock", type=Path, required=True)
    parser.add_argument("--security-scan-output", type=Path, required=True)
    parser.add_argument("--lock-output", type=Path, required=True)
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


def _container_scan(
    image_id: str,
    *,
    user: str,
    rg_sha256: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, bool]:
    artifact_checks = "\n".join(
        'test "$(sha256sum -- '
        f'{shlex.quote(str(item["path"]))} | cut -c1-64)" = '
        f"{shlex.quote(str(item['sha256']))}"
        for item in artifacts
    )
    command = "\n".join(
        (
            "set -eu",
            f'test "$(id -u):$(id -g)" = "{user}"',
            "test -d /home/cva6",
            'test -z "$(find /home/cva6 -mindepth 1 -maxdepth 1 -print -quit)"',
            "test ! -e /home/cva6_base_commit.txt",
            "test ! -e /workspace/verifier",
            "test ! -e /verigym-public",
            "test ! -e /hidden-verifier",
            "test ! -e /reference.patch",
            "test ! -e /usr/local/bin/codex",
            "test ! -e /usr/local/lib/codex",
            "test ! -e /root/.codex/auth.json",
            "if command -v codex >/dev/null 2>&1; then exit 42; fi",
            "if touch /verigym-rootfs-write 2>/dev/null; then exit 41; fi",
            "touch /workspace/repository/workspace-proof",
            "touch /tmp/ephemeral-proof",
            "find .. -maxdepth 2 -print >/tmp/parent-read",
            "grep -q ../repository /tmp/parent-read",
            "sed -n '1p' /etc/os-release >/tmp/absolute-read",
            f'test "$(sha256sum /usr/local/bin/rg | cut -c1-64)" = "{rg_sha256}"',
            f'test "$(rg --version | head -n 1)" = "{_RG_VERSION}"',
            "test -x /usr/bin/tail",
            "make --version >/tmp/make-version",
            "/tools/verilator/bin/verilator_bin --version >/tmp/verilator-bin-version",
            "VERILATOR_ROOT=/tools/verilator verilator --version >/tmp/verilator-version",
            artifact_checks,
        )
    )
    scratch_parent = Path("/data/jzhu484/Agent/.verigym-tmp")
    scratch_parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="hwe-command-image-scan.", dir=scratch_parent))
    container_id: str | None = None
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
        for entry in _EXPECTED_IMAGE_ENVIRONMENT:
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
        container_id = _run(create, timeout=60).stdout.strip()
        inspection_values = json.loads(
            _run(["docker", "container", "inspect", container_id], timeout=30).stdout
        )
        inspection = inspection_values[0]
        host = inspection["HostConfig"]
        config = inspection["Config"]
        mounts = inspection["Mounts"]
        checks = {
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
                len(config["Env"]) == len(_EXPECTED_IMAGE_ENVIRONMENT)
                and _environment_map(config["Env"]) == _environment_map(_EXPECTED_IMAGE_ENVIRONMENT)
            ),
            "non_root_identity": config["User"] == user,
        }
        if not all(checks.values()):
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            raise RuntimeError(f"HWE command container controls differ from the lock: {failed}")
        started = _run(["docker", "start", "--attach", container_id], timeout=180)
        if started.stdout or started.stderr:
            raise RuntimeError("HWE command-image scan unexpectedly emitted command output")
        state_values = json.loads(
            _run(["docker", "container", "inspect", container_id], timeout=30).stdout
        )
        if state_values[0]["State"]["ExitCode"] != 0:
            raise RuntimeError("HWE command-image diagnostic scan failed")
        if not (workspace / "workspace-proof").is_file():
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
                "verilator_available": True,
                "hidden_reference_verifier_assets_absent": True,
                "rootfs_write_rejected": True,
                "tmp_ephemeral": not (workspace / "ephemeral-proof").exists(),
            }
        )
        return checks
    finally:
        if container_id:
            subprocess.run(
                ["docker", "container", "rm", "--force", container_id],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        shutil.rmtree(workspace)


def scan_and_lock(
    *,
    receipt_path: Path,
    identity_lock_path: Path,
    security_output: Path,
    lock_output: Path,
) -> tuple[dict[str, Any], HweCommandImageLock]:
    if security_output.exists() or lock_output.exists():
        raise ValueError("HWE command-image scan and lock outputs must be new paths")
    receipt = _load_json(receipt_path)
    identity = HweAgentImageLock.model_validate(_load_json(identity_lock_path))
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
        "exact_image_environment": _EXPECTED_IMAGE_ENVIRONMENT,
    }
    if any(receipt.get(key) != value for key, value in expected_receipt.items()):
        raise ValueError("HWE command-image receipt differs from the frozen task identity")
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
        "org.verigym.runtime.role": "hwe-cva6-command",
        "org.verigym.collection.profile": "hwe_standard_v2",
        "org.verigym.tool.contract": "hwe_native_shell_v2",
        "org.verigym.command.protocol": "hwe_command_image_v1",
        "org.verigym.command.rg.version": _RG_VERSION,
        "org.verigym.command.rg.sha256": rg_sha256,
        "org.verigym.command.rg.release_archive.sha256": receipt["rg_release_archive_sha256"],
        "org.verigym.hwe.task_id": identity.task_id,
        "org.verigym.cva6.verifier_base_image_id": identity.verifier_base_image_id,
        "org.verigym.codex.present": "absent",
        "org.verigym.provider_credentials": "absent",
        "org.verigym.hidden_assets": "absent",
        "org.verigym.reference_patch": "absent",
        "org.verigym.verifier_payload": "absent",
    }
    image_checks = {
        "image_identity": image.get("Id") == image_id,
        "rootfs_layer_identity_preserved": image.get("RootFS") == unsanitized.get("RootFS"),
        "image_environment_exact": image["Config"].get("Env") == _EXPECTED_IMAGE_ENVIRONMENT,
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
    runtime_checks = _container_scan(
        image_id,
        user=f"{os.getuid()}:{os.getgid()}",
        rg_sha256=rg_sha256,
        artifacts=artifacts,
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_command_image_security_scan_v1",
        "scanner_profile_id": "cva6-hwe-command-container-native-offline-v1",
        "task_id": identity.task_id,
        "verifier_base_image_id": identity.verifier_base_image_id,
        "derived_command_image_id": image_id,
        "unsanitized_command_image_id": unsanitized_id,
        "configuration_sanitizer_sha256": receipt["configuration_sanitizer_sha256"],
        "rg_source": _RG_SOURCE,
        "rg_release_archive_sha256": receipt["rg_release_archive_sha256"],
        "exact_image_environment": _EXPECTED_IMAGE_ENVIRONMENT,
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
        toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
        allowlisted_artifacts=artifacts,
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
