#!/usr/bin/env python3
"""Verify one local CVA6 HWE v2 image and seal its task-keyed lock."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweAgentImageLock, build_hwe_agent_image_lock

_MAX_JSON_BYTES = 16 * 1024 * 1024
_EXPECTED_IMAGE_ENVIRONMENT = [
    "PATH=/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME=/tmp/verigym-home",
    "LANG=C.UTF-8",
    "LC_ALL=C.UTF-8",
    "TMPDIR=/tmp",
]
_EXPECTED_RUNTIME_ENVIRONMENT = [
    *_EXPECTED_IMAGE_ENVIRONMENT[:2],
    "CODEX_HOME=/tmp/verigym-codex-home",
    *_EXPECTED_IMAGE_ENVIRONMENT[2:],
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--legacy-identity-lock", type=Path, required=True)
    parser.add_argument("--security-scan-output", type=Path, required=True)
    parser.add_argument("--lock-output", type=Path, required=True)
    return parser


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"unsafe HWE image JSON input: {path.name}")
    resolved = path.resolve(strict=True)
    if resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError(f"unsafe HWE image JSON input: {path.name}")
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"HWE image JSON input is not an object: {path.name}")
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
        raise RuntimeError("Docker returned malformed HWE image inspection data")
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
    codex_sha256: str,
    rg_sha256: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, bool]:
    codex_check = (
        f'test "$(sha256sum /usr/local/lib/codex/bin/codex | cut -c1-64)" = "{codex_sha256}"'
    )
    rg_check = (
        f'test "$(sha256sum /usr/local/lib/codex/codex-path/rg | cut -c1-64)" = "{rg_sha256}"'
    )
    artifact_checks = "\n".join(
        f'test "$(sha256sum {item["path"]} | cut -d" " -f1)" = "{item["sha256"]}"'
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
            "test ! -e /root/.codex/auth.json",
            "if touch /verigym-rootfs-write 2>/dev/null; then exit 41; fi",
            "touch /workspace/repository/workspace-proof",
            "touch /tmp/ephemeral-proof",
            "find .. -maxdepth 2 -print >/tmp/parent-read",
            "grep -q ../repository /tmp/parent-read",
            "sed -n '1p' /etc/os-release >/tmp/absolute-read",
            codex_check,
            rg_check,
            'test "$(codex --version 2>/tmp/codex-version-stderr)" = "codex-cli 0.147.0"',
            "rg --version >/tmp/rg-version",
            "make --version >/tmp/make-version",
            "/tools/verilator/bin/verilator_bin --version >/tmp/verilator-bin-version",
            "VERILATOR_ROOT=/tools/verilator verilator --version >/tmp/verilator-version",
            artifact_checks,
        )
    )
    scratch_parent = Path("/data/jzhu484/Agent/.verigym-tmp")
    scratch_parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="hwe-image-scan.", dir=scratch_parent))
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
        for entry in _EXPECTED_RUNTIME_ENVIRONMENT:
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
                len(config["Env"]) == len(_EXPECTED_RUNTIME_ENVIRONMENT)
                and _environment_map(config["Env"])
                == _environment_map(_EXPECTED_RUNTIME_ENVIRONMENT)
            ),
            "non_root_identity": config["User"] == user,
        }
        if not all(checks.values()):
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            raise RuntimeError(
                f"HWE agent container effective controls differ from the lock: {failed}"
            )
        started = _run(["docker", "start", "--attach", container_id], timeout=180)
        if started.stdout or started.stderr:
            raise RuntimeError("HWE image scan unexpectedly emitted public command output")
        state_values = json.loads(
            _run(["docker", "container", "inspect", container_id], timeout=30).stdout
        )
        if state_values[0]["State"]["ExitCode"] != 0:
            raise RuntimeError("HWE agent image diagnostic scan failed")
        if not (workspace / "workspace-proof").is_file():
            raise RuntimeError("HWE agent image workspace was not writable")
        checks.update(
            {
                "source_whiteout_empty": True,
                "container_native_parent_read": True,
                "container_native_absolute_read": True,
                "codex_hash_exact": True,
                "codex_version_exact": True,
                "rg_hash_exact": True,
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
    legacy_lock_path: Path,
    security_output: Path,
    lock_output: Path,
) -> tuple[dict[str, Any], HweAgentImageLock]:
    if security_output.exists() or lock_output.exists():
        raise ValueError("HWE v2 scan and lock outputs must be new paths")
    receipt = _load_json(receipt_path)
    legacy = HweAgentImageLock.model_validate(_load_json(legacy_lock_path))
    if legacy.format_id != "verigym_hwe_agent_image_lock_v1":
        raise ValueError("HWE v2 identity source must be an explicit legacy v1 lock")
    if (
        receipt.get("format_id") != "verigym_hwe_agent_image_build_receipt_v2"
        or receipt.get("collection_profile_id") != "hwe_standard_v2"
        or receipt.get("tool_contract_id") != "hwe_native_shell_v2"
        or receipt.get("task_id") != legacy.task_id
        or receipt.get("verifier_base_image_id") != legacy.verifier_base_image_id
        or receipt.get("agent_codex_sha256") != legacy.agent_codex_sha256
        or receipt.get("agent_rg_sha256") != legacy.agent_rg_sha256
        or receipt.get("exact_image_environment") != _EXPECTED_IMAGE_ENVIRONMENT
    ):
        raise ValueError("HWE v2 receipt differs from the frozen task identity")

    image_id = str(receipt["derived_agent_image_id"])
    unsanitized_id = str(receipt["unsanitized_agent_image_id"])
    image = _inspect(image_id)
    unsanitized = _inspect(unsanitized_id)
    labels = image["Config"].get("Labels") or {}
    required_labels = {
        "org.verigym.collection.profile": "hwe_standard_v2",
        "org.verigym.tool.contract": "hwe_native_shell_v2",
        "org.verigym.codex.version": "0.147.0",
        "org.verigym.codex.binary.sha256": legacy.agent_codex_sha256,
        "org.verigym.codex.rg.sha256": legacy.agent_rg_sha256,
        "org.verigym.hwe.task_id": legacy.task_id,
        "org.verigym.cva6.verifier_base_image_id": legacy.verifier_base_image_id,
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
        "required_labels": all(labels.get(key) == value for key, value in required_labels.items()),
    }
    if not all(image_checks.values()):
        raise RuntimeError("HWE v2 image configuration scan failed")
    artifacts = [item.model_dump(mode="json") for item in legacy.allowlisted_artifacts]
    runtime_checks = _container_scan(
        image_id,
        user=f"{os.getuid()}:{os.getgid()}",
        codex_sha256=legacy.agent_codex_sha256,
        rg_sha256=legacy.agent_rg_sha256,
        artifacts=artifacts,
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_agent_image_security_scan_v2",
        "scanner_profile_id": "cva6-hwe-container-native-offline-v2",
        "task_id": legacy.task_id,
        "verifier_base_image_id": legacy.verifier_base_image_id,
        "derived_agent_image_id": image_id,
        "unsanitized_agent_image_id": unsanitized_id,
        "configuration_sanitizer_sha256": receipt["configuration_sanitizer_sha256"],
        "exact_image_environment": _EXPECTED_IMAGE_ENVIRONMENT,
        "exact_runtime_environment": _EXPECTED_RUNTIME_ENVIRONMENT,
        "runtime_controls": {
            "network_mode": "none",
            "read_only_rootfs": True,
            "run_as_user": f"{os.getuid()}:{os.getgid()}",
            "cap_drop_all": True,
            "no_new_privileges": True,
            "pids_limit": 4096,
            "single_visible_workspace_mount": True,
            "container_native_read_scope": True,
        },
        "toolchain_artifacts": artifacts,
        "checks": {**image_checks, **runtime_checks},
        "secrets_detected": False,
        "scan_passed": True,
    }
    scan = {**base, "security_scan_id": content_hash(base)}
    lock = build_hwe_agent_image_lock(
        task_id=legacy.task_id,
        task_hash=legacy.task_hash,
        source_hash=legacy.source_hash,
        verifier_base_image_id=legacy.verifier_base_image_id,
        derived_agent_image_id=image_id,
        host_codex_sha256=legacy.host_codex_sha256,
        agent_codex_sha256=legacy.agent_codex_sha256,
        agent_rg_sha256=legacy.agent_rg_sha256,
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
        legacy_lock_path=arguments.legacy_identity_lock,
        security_output=arguments.security_scan_output,
        lock_output=arguments.lock_output,
    )
    print(
        json.dumps(
            {
                "task_id": lock.task_id,
                "derived_agent_image_id": lock.derived_agent_image_id,
                "security_scan_id": scan["security_scan_id"],
                "lock_hash": lock.lock_hash,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
