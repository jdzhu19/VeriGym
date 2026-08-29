#!/usr/bin/env python3
"""Run the v23 no-candidate daemonless bootstrap and network safety preflight."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

OPENHANDS_V23_PREFLIGHT_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V23_DAEMONLESS_PREFLIGHT"
OPENHANDS_V23_APPROVAL_FORMAT = "verigym_openhands_hwe_v23_daemonless_preflight_authorization_v1"
OPENHANDS_V23_PREFLIGHT_FORMAT = "verigym_openhands_hwe_v23_daemonless_preflight_report_v1"
OPENHANDS_V23_APPROVAL_HASH = "aa9b8bdc9c00a0c7eeb0bd39bc4febe4ea681b2a16d034f11d16c3359347bdc3"
OPENHANDS_V23_NETWORK = "verigym-hwe-net"
OPENHANDS_V23_TOOL_CACHE = Path(
    "/data/jzhu484/Agent/.verigym-tmp/openhands-v23-crane-v0.22.0-slsa-v2.7.1"
)
OPENHANDS_V23_CANDIDATE_REFERENCES = tuple(
    f"ghcr.io/pku-liang/openhwgroup_m_cva6:pr-{number}"
    for number in (2330, 3226, 2844, 3231, 2989, 1482, 3059)
)

_REPOSITORY = Path(__file__).resolve().parents[1]
_BOOTSTRAP_HELPER = _REPOSITORY / "scripts/fetch_pinned_crane_release_v23.py"
_SCRATCH_PARENT = Path("/data/jzhu484/Agent/.verigym-tmp")
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_COMMAND_OUTPUT_BYTES = 16 * 1024
_MEMORY_BYTES = 512 * 1024 * 1024
_PIDS_LIMIT = 128
_TMPFS = "rw,noexec,nosuid,nodev,size=67108864,mode=1777"
_OWNER_LABEL = "openhands-hwe-v23-daemonless-preflight-v1"
_BOOTSTRAP_IMAGE_ENVIRONMENT = (
    "PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG=C.UTF-8",
    "GPG_KEY=A035C8C19219BA821ECEA86B64E628F8D684696D",
    "PYTHON_VERSION=3.11.9",
    "PYTHON_PIP_VERSION=24.0",
    "PYTHON_SETUPTOOLS_VERSION=65.5.1",
    "PYTHON_GET_PIP_URL=https://github.com/pypa/get-pip/raw/"
    "def4aec84b261b939137dd1c69eff0aabb4a7bf4/public/get-pip.py",
    "PYTHON_GET_PIP_SHA256=bc37786ec99618416cc0a0ca32833da447f4d91ab51d2c138dd15b7af21e8e9a",
    "HOME=/nonexistent",
)
_EXECUTION_IMAGE_ENVIRONMENT = (
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME=/nonexistent",
)
_BOOTSTRAP_STAGES = [
    "download_crane_archive",
    "download_checksums",
    "download_provenance",
    "download_slsa_verifier",
    "validate_checksums",
    "validate_sigstore_bundle",
    "verify_slsa_signature",
    "extract_crane",
    "write_bootstrap_receipt",
]


class _StageFailure(ConfigurationError):
    def __init__(self, message: str, *, diagnostic: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostic = copy.deepcopy(diagnostic)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def run_v23_daemonless_preflight(*, approval_path: Path, output: Path) -> dict[str, Any]:
    """Bootstrap pinned, SLSA-verified crane without touching any HWE candidate."""

    if os.environ.get(OPENHANDS_V23_PREFLIGHT_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V23_PREFLIGHT_OPT_IN_ENV}=1 is required")
    approved = _validated_authorization(_load_json(approval_path))
    _validate_network()
    bootstrap_image = _validate_local_image(approved["bootstrap_image"])
    execution_image = _validate_local_image(approved["execution_image"])
    if _count_host_candidate_images() != 0:
        raise ConfigurationError("OpenHands v23 preflight found a candidate image already present")

    root = _new_directory(output)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V23_PREFLIGHT_FORMAT,
        "status": "running",
        "identity": approved["identity"],
        "authorization_hash": approved["authorization_hash"],
        "predecessor_v22_status": approved["predecessor"]["v22_status"],
        "predecessor_v22_report_hash": approved["predecessor"]["v22_report_hash"],
        "network": OPENHANDS_V23_NETWORK,
        "candidate_references": list(OPENHANDS_V23_CANDIDATE_REFERENCES),
        "candidate_downloads_authorized": False,
        "candidate_downloads_started": False,
        "candidate_images_imported": 0,
        "host_candidate_images_present": 0,
        "qualification_started": False,
        "provider_calls": 0,
        "heldout_task_ids_loaded": [],
        "failure_diagnostic": None,
    }
    _write_progress(root, progress)
    failure: BaseException | None = None
    try:
        cache, bootstrap_control, bootstrap_command, bootstrap_progress = _bootstrap_crane(
            approved,
            bootstrap_image_id=bootstrap_image["image_id"],
        )
        crane_receipt = _validated_crane_cache(cache, approved=approved)
        version_output, version_control, version_command = _run_controlled_container(
            image_id=execution_image["image_id"],
            source=cache,
            mount_read_only=True,
            network="none",
            path="/download/crane",
            arguments=["version"],
            expected_environment=_EXECUTION_IMAGE_ENVIRONMENT,
            label_role="crane-version",
        )
        expected_version = approved["crane_release"]["cli_version_output"].encode("ascii")
        if version_output != expected_version:
            raise _StageFailure(
                "OpenHands v23 crane version output changed",
                diagnostic={**version_command, "failure_stage": "crane_version_output"},
            )
        probe_output, probe_control, probe_command = _run_controlled_container(
            image_id=execution_image["image_id"],
            source=cache,
            mount_read_only=True,
            network=OPENHANDS_V23_NETWORK,
            path="/download/crane",
            arguments=["digest", approved["probe"]["reference"]],
            expected_environment=_EXECUTION_IMAGE_ENVIRONMENT,
            label_role="crane-digest-probe",
        )
        expected_digest = f"{approved['probe']['expected_manifest_digest']}\n".encode()
        if probe_output != expected_digest:
            raise _StageFailure(
                "OpenHands v23 registered digest probe changed",
                diagnostic={**probe_command, "failure_stage": "registry_digest_output"},
            )
        if _count_host_candidate_images() != 0:
            raise _StageFailure(
                "OpenHands v23 preflight imported a candidate image",
                diagnostic={"failure_stage": "postflight_candidate_inventory"},
            )
        progress.update(
            {
                "status": "preflight_passed",
                "crane_release_tag": approved["crane_release"]["release_tag"],
                "crane_sha256": crane_receipt["crane_sha256"],
                "crane_cli_version_output_bytes": len(expected_version),
                "crane_cli_version_output_sha256": approved["crane_release"][
                    "cli_version_output_sha256"
                ],
                "slsa_verifier_tag": approved["slsa_verifier"]["release_tag"],
                "slsa_verifier_sha256": approved["slsa_verifier"]["asset_sha256"],
                "slsa_verifier_executable_path": "/download/slsa-verifier-linux-amd64",
                "slsa_verification_passed": True,
                "sigstore_trust_metadata_refresh_authorized": True,
                "sigstore_tuf_repository": approved["slsa_verifier"]["sigstore_tuf_repository"],
                "bootstrap_control_hash": bootstrap_control["control_hash"],
                "version_control_hash": version_control["control_hash"],
                "probe_control_hash": probe_control["control_hash"],
                "bootstrap_progress_hash": bootstrap_progress["progress_hash"],
                "probe_manifest_digest": approved["probe"]["expected_manifest_digest"],
                "release_asset_download_count": 4,
                "registry_probe_count": 1,
                "command_receipts": {
                    "bootstrap": bootstrap_command,
                    "version": version_command,
                    "registry_probe": probe_command,
                },
                "temporary_containers_removed": True,
                "tcp_api_listener_present": False,
                "docker_daemon_process_present": False,
                "docker_socket_mounted": False,
                "privileged_container_used": False,
                "candidate_images_imported": 0,
                "host_candidate_images_present": 0,
            }
        )
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
        diagnostic = getattr(exc, "diagnostic", None)
        if isinstance(diagnostic, dict):
            progress["failure_diagnostic"] = diagnostic
        else:
            progress["failure_diagnostic"] = {
                "failure_stage": "preflight_orchestration",
                "failure_type": type(exc).__name__,
            }
        try:
            host_candidate_images_present: int | None = _count_host_candidate_images()
        except Exception:
            host_candidate_images_present = None
        progress.update(
            {
                "status": "stopped_security_or_infrastructure_invalid",
                "failure_type": type(exc).__name__,
                "candidate_downloads_started": False,
                "candidate_images_imported": 0,
                "host_candidate_images_present": host_candidate_images_present,
            }
        )
    _write_progress(root, progress)
    if failure is not None:
        raise ConfigurationError("OpenHands v23 daemonless preflight failed") from failure
    return _sealed(progress)


def _bootstrap_crane(
    approved: dict[str, Any], *, bootstrap_image_id: str
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    if OPENHANDS_V23_TOOL_CACHE.exists() or OPENHANDS_V23_TOOL_CACHE.is_symlink():
        raise ConfigurationError("OpenHands v23 crane cache must be new for the preflight")
    _SCRATCH_PARENT.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="openhands-v23-crane-building.", dir=_SCRATCH_PARENT))
    try:
        helper = temporary / _BOOTSTRAP_HELPER.name
        shutil.copyfile(_BOOTSTRAP_HELPER, helper)
        helper.chmod(0o400)
        release = approved["crane_release"]
        verifier = approved["slsa_verifier"]
        try:
            output, control, command = _run_controlled_container(
                image_id=bootstrap_image_id,
                source=temporary,
                mount_read_only=False,
                network=OPENHANDS_V23_NETWORK,
                path="/usr/local/bin/python",
                arguments=[
                    f"/download/{helper.name}",
                    "--release-tag",
                    release["release_tag"],
                    "--asset-url",
                    release["asset_url"],
                    "--asset-sha256",
                    release["asset_sha256"],
                    "--asset-size",
                    str(release["asset_size"]),
                    "--checksums-url",
                    release["checksums_url"],
                    "--checksums-sha256",
                    release["checksums_sha256"],
                    "--checksums-size",
                    str(release["checksums_size"]),
                    "--provenance-url",
                    release["provenance_url"],
                    "--provenance-sha256",
                    release["provenance_sha256"],
                    "--provenance-size",
                    str(release["provenance_size"]),
                    "--source-uri",
                    release["source_uri"],
                    "--source-commit",
                    release["source_commit"],
                    "--builder-id",
                    release["builder_id"],
                    "--build-type",
                    release["build_type"],
                    "--workflow-entrypoint",
                    release["workflow_entrypoint"],
                    "--slsa-verifier-tag",
                    verifier["release_tag"],
                    "--slsa-verifier-url",
                    verifier["asset_url"],
                    "--slsa-verifier-sha256",
                    verifier["asset_sha256"],
                    "--slsa-verifier-size",
                    str(verifier["asset_size"]),
                    "--sigstore-tuf-repository",
                    verifier["sigstore_tuf_repository"],
                ],
                expected_environment=_BOOTSTRAP_IMAGE_ENVIRONMENT,
                label_role="crane-bootstrap",
            )
        except _StageFailure as exc:
            bootstrap_progress = _read_bootstrap_progress(temporary, require_passed=False)
            diagnostic = copy.deepcopy(exc.diagnostic)
            diagnostic["failure_stage"] = "crane_bootstrap"
            if bootstrap_progress is not None:
                diagnostic["bootstrap_progress"] = bootstrap_progress
                diagnostic["failure_stage"] = bootstrap_progress.get(
                    "failure_stage", "crane_bootstrap"
                )
            raise _StageFailure(
                "OpenHands v23 crane bootstrap failed", diagnostic=diagnostic
            ) from exc
        if output:
            raise _StageFailure(
                "OpenHands v23 crane bootstrap emitted stdout",
                diagnostic={**command, "failure_stage": "crane_bootstrap_stdout"},
            )
        bootstrap_progress = _read_bootstrap_progress(temporary, require_passed=True)
        if bootstrap_progress is None:
            raise _StageFailure(
                "OpenHands v23 crane bootstrap progress is missing",
                diagnostic={**command, "failure_stage": "bootstrap_progress_validation"},
            )
        _validated_crane_cache(temporary, approved=approved)
        os.replace(temporary, OPENHANDS_V23_TOOL_CACHE)
        return OPENHANDS_V23_TOOL_CACHE, control, command, bootstrap_progress
    finally:
        if temporary.exists():
            if not temporary.is_relative_to(_SCRATCH_PARENT):
                raise ConfigurationError("OpenHands v23 crane scratch path escaped")
            shutil.rmtree(temporary)


def _run_controlled_container(
    *,
    image_id: str,
    source: Path,
    mount_read_only: bool,
    network: str,
    path: str,
    arguments: list[str],
    expected_environment: tuple[str, ...],
    label_role: str,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    resolved_source = source.resolve(strict=True)
    container_name = f"verigym-hwe-v23-{label_role}-{os.getpid()}-{secrets.token_hex(4)}"
    mount = f"type=bind,src={resolved_source},dst=/download"
    if mount_read_only:
        mount += ",readonly"
    command = [
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        container_name,
        "--label",
        f"org.verigym.owner={_OWNER_LABEL}",
        "--label",
        f"org.verigym.role={label_role}",
        "--network",
        network,
        "--ipc",
        "none",
        "--read-only",
        "--tmpfs",
        f"/tmp:{_TMPFS}",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        str(_MEMORY_BYTES),
        "--memory-swap",
        str(_MEMORY_BYTES),
        "--cpus",
        "1",
        "--pids-limit",
        str(_PIDS_LIMIT),
        "--workdir",
        "/download",
        "--env",
        "HOME=/nonexistent",
        "--mount",
        mount,
        "--entrypoint",
        path,
        image_id,
        *arguments,
    ]
    diagnostic: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v23_command_receipt_v1",
        "role": label_role,
        "network": network,
        "create_exit_code": None,
        "create_stdout_bytes": 0,
        "create_stderr_bytes": 0,
        "create_stderr_present": False,
        "exit_code": None,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "stderr_present": False,
        "temporary_container_removed": False,
    }
    result: tuple[bytes, dict[str, Any]] | None = None
    failure: BaseException | None = None
    try:
        created = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=60,
        )
        diagnostic.update(
            {
                "create_exit_code": created.returncode,
                "create_stdout_bytes": len(created.stdout),
                "create_stderr_bytes": len(created.stderr),
                "create_stderr_present": bool(created.stderr),
            }
        )
        if (
            len(created.stdout) > _MAX_COMMAND_OUTPUT_BYTES
            or len(created.stderr) > _MAX_COMMAND_OUTPUT_BYTES
        ):
            raise ConfigurationError("OpenHands v23 Docker create output exceeded its bound")
        if created.returncode != 0:
            raise ConfigurationError("OpenHands v23 Docker create failed")
        container_id = created.stdout.decode("ascii", errors="strict").strip()
        if not container_id:
            raise ConfigurationError("OpenHands v23 Docker create returned no container ID")
        values = _docker_json(["docker", "container", "inspect", container_id])
        if len(values) != 1:
            raise ConfigurationError("OpenHands v23 container inspection is malformed")
        control = _validate_container_inspection(
            values[0],
            image_id=image_id,
            source=resolved_source,
            mount_read_only=mount_read_only,
            network=network,
            path=path,
            arguments=arguments,
            expected_environment=expected_environment,
            label_role=label_role,
        )
        started = subprocess.run(
            ["docker", "start", "--attach", container_id],
            check=False,
            capture_output=True,
            timeout=300,
        )
        diagnostic.update(
            {
                "exit_code": started.returncode,
                "stdout_bytes": len(started.stdout),
                "stderr_bytes": len(started.stderr),
                "stderr_present": bool(started.stderr),
                "control_hash": control["control_hash"],
            }
        )
        if (
            len(started.stdout) > _MAX_COMMAND_OUTPUT_BYTES
            or len(started.stderr) > _MAX_COMMAND_OUTPUT_BYTES
        ):
            raise ConfigurationError("OpenHands v23 controlled output exceeded its bound")
        if started.returncode != 0:
            raise ConfigurationError("OpenHands v23 controlled container command failed")
        result = started.stdout, control
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
    try:
        _remove_container(container_name)
        diagnostic["temporary_container_removed"] = True
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
        diagnostic["failure_stage"] = "temporary_container_cleanup"
    if failure is not None:
        diagnostic.setdefault("failure_stage", label_role)
        diagnostic["failure_type"] = type(failure).__name__
        raise _StageFailure(
            "OpenHands v23 controlled container stage failed", diagnostic=diagnostic
        ) from failure
    if result is None:
        raise _StageFailure(
            "OpenHands v23 controlled container returned no result",
            diagnostic={**diagnostic, "failure_stage": label_role},
        )
    return result[0], result[1], diagnostic


def _validate_container_inspection(
    container: dict[str, Any],
    *,
    image_id: str,
    source: Path,
    mount_read_only: bool,
    network: str,
    path: str,
    arguments: list[str],
    expected_environment: tuple[str, ...],
    label_role: str,
) -> dict[str, Any]:
    host = container.get("HostConfig")
    config = container.get("Config")
    mounts = container.get("Mounts")
    network_settings = container.get("NetworkSettings")
    if (
        not isinstance(host, dict)
        or not isinstance(config, dict)
        or not isinstance(network_settings, dict)
        or not isinstance(mounts, list)
    ):
        raise ConfigurationError("OpenHands v23 effective container controls are malformed")
    security_options = host.get("SecurityOpt") or []
    cap_drop = host.get("CapDrop") or []
    devices = host.get("Devices") or []
    cap_add = host.get("CapAdd") or []
    tmpfs = host.get("Tmpfs") or {}
    labels = config.get("Labels") or {}
    environments = config.get("Env")
    environment_map = _environment_map(environments)
    expected_environment_map = _environment_map(list(expected_environment))
    exact_mount = (
        len(mounts) == 1
        and isinstance(mounts[0], dict)
        and mounts[0].get("Source") == str(source)
        and mounts[0].get("Destination") == "/download"
        and mounts[0].get("RW") is (not mount_read_only)
    )
    valid = (
        container.get("Image") == image_id
        and container.get("Path") == path
        and container.get("Args") == arguments
        and host.get("NetworkMode") == network
        and host.get("IpcMode") == "none"
        and host.get("PidMode") in {"", None}
        and host.get("ReadonlyRootfs") is True
        and host.get("Privileged") is False
        and not cap_add
        and cap_drop == ["ALL"]
        and not devices
        and any(str(value).startswith("no-new-privileges") for value in security_options)
        and host.get("Memory") == _MEMORY_BYTES
        and host.get("MemorySwap") == _MEMORY_BYTES
        and host.get("NanoCpus") == 1_000_000_000
        and host.get("PidsLimit") == _PIDS_LIMIT
        and host.get("PublishAllPorts") is False
        and host.get("PortBindings") in (None, {})
        and host.get("RestartPolicy", {}).get("Name") in {"", "no"}
        and host.get("AutoRemove") is False
        and isinstance(tmpfs, dict)
        and tmpfs.get("/tmp") == _TMPFS
        and exact_mount
        and config.get("User") == f"{os.getuid()}:{os.getgid()}"
        and config.get("WorkingDir") == "/download"
        and config.get("ExposedPorts") in (None, {})
        and config.get("Volumes") in (None, {})
        and isinstance(environments, list)
        and len(environments) == len(expected_environment)
        and environment_map == expected_environment_map
        and labels.get("org.verigym.owner") == _OWNER_LABEL
        and labels.get("org.verigym.role") == label_role
        and network_settings.get("Ports") in (None, {})
    )
    if not valid:
        raise ConfigurationError("OpenHands v23 effective container controls changed")
    base = {
        "network": network,
        "path": path,
        "arguments": arguments,
        "privileged": False,
        "read_only_rootfs": True,
        "non_root_user": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "ipc_mode": "none",
        "private_pid_namespace": True,
        "bounded_resources": True,
        "single_scratch_mount": True,
        "scratch_mount_read_only": mount_read_only,
        "docker_socket_mounted": False,
        "published_ports": False,
        "exposed_ports": False,
        "environment_names": sorted(environment_map),
    }
    return {**base, "control_hash": content_hash(base)}


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    observed_hash = value.pop("authorization_hash", None)
    if (
        observed_hash != OPENHANDS_V23_APPROVAL_HASH
        or content_hash(value) != OPENHANDS_V23_APPROVAL_HASH
    ):
        raise ConfigurationError("OpenHands v23 preflight authorization identity changed")
    value["authorization_hash"] = observed_hash
    actions = value.get("authorized_actions")
    controls = value.get("required_controls")
    release = value.get("crane_release")
    verifier = value.get("slsa_verifier")
    predecessor = value.get("predecessor")
    if (
        value.get("format_id") != OPENHANDS_V23_APPROVAL_FORMAT
        or value.get("status") != "authorized_pending_preflight"
        or value.get("identity") != "openhands-hwe-v23-daemonless-prewarm-preflight-v1"
        or value.get("network") != OPENHANDS_V23_NETWORK
        or value.get("failure_policy") != "stop_immediately"
        or value.get("production_training_ready") is not False
        or value.get("benchmark_score_claimed") is not False
        or not isinstance(predecessor, dict)
        or predecessor.get("v22_status") != "stopped_security_or_infrastructure_invalid"
        or predecessor.get("v22_report_hash")
        != "7506b9f12d0e66b53fc49272817da4f44753b0239f1dc85bb9def5bc530e83b9"
        or not isinstance(actions, dict)
        or actions.get("download_pinned_crane_release") is not True
        or actions.get("download_pinned_slsa_verifier") is not True
        or actions.get("verify_crane_slsa_provenance") is not True
        or actions.get("refresh_sigstore_tuf_trust_metadata") is not True
        or actions.get("resolve_registered_verifier_absolute_path") is not True
        or actions.get("run_crane_version_network_none") is not True
        or actions.get("verify_registered_crane_cli_version_output") is not True
        or actions.get("probe_registered_non_candidate_digest") is not True
        or any(
            actions.get(key) is not False
            for key in (
                "download_candidate_images",
                "load_candidate_images",
                "start_qualification",
                "invoke_provider",
                "start_training",
                "load_heldout_tasks",
            )
        )
        or not isinstance(controls, dict)
        or any(controls.get(key) is not expected for key, expected in _required_controls().items())
        or not isinstance(release, dict)
        or not isinstance(verifier, dict)
        or release.get("release_tag") != "v0.22.0"
        or release.get("cli_version_output") != "0.22.0\n"
        or release.get("cli_version_output") == f"{release.get('release_tag')}\n"
        or release.get("cli_version_output_sha256") != hashlib.sha256(b"0.22.0\n").hexdigest()
        or verifier.get("release_tag") != "v2.7.1"
        or verifier.get("sigstore_tuf_repository") != "https://tuf-repo-cdn.sigstore.dev"
        or _sha256_file(_BOOTSTRAP_HELPER) != release.get("bootstrap_script_sha256")
    ):
        raise ConfigurationError("OpenHands v23 preflight authorization scope changed")
    return value


def _required_controls() -> dict[str, bool]:
    return {
        "privileged": False,
        "docker_socket_mount": False,
        "docker_daemon_process": False,
        "tcp_api_listener": False,
        "read_only_rootfs": True,
        "non_root_user": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "single_scratch_mount": True,
        "default_bridge_used": False,
        "provider_or_registry_credentials_present": False,
        "proxy_values_forwarded": False,
        "cryptographic_slsa_verification": True,
        "bounded_content_free_diagnostics": True,
        "stderr_requires_nonzero_exit_to_fail": True,
        "fully_qualified_verifier_executable": True,
        "version_output_independent_from_release_tag": True,
    }


def _validated_crane_cache(cache: Path, *, approved: dict[str, Any]) -> dict[str, Any]:
    resolved = cache.resolve(strict=True)
    if cache.is_symlink() or not resolved.is_dir() or not resolved.is_relative_to(_SCRATCH_PARENT):
        raise ConfigurationError("OpenHands v23 crane cache path is unsafe")
    expected_names = {
        _BOOTSTRAP_HELPER.name,
        "go-containerregistry_Linux_x86_64.tar.gz",
        "checksums.txt",
        "multiple.intoto.jsonl",
        "slsa-verifier-linux-amd64",
        "crane",
        "bootstrap-receipt.json",
        "bootstrap-progress.json",
    }
    paths = list(resolved.iterdir())
    if {path.name for path in paths} != expected_names:
        raise ConfigurationError("OpenHands v23 crane cache inventory changed")
    for path in paths:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ConfigurationError("OpenHands v23 crane cache contains an unsafe entry")
    release = approved["crane_release"]
    verifier = approved["slsa_verifier"]
    expected_files = {
        _BOOTSTRAP_HELPER.name: (release["bootstrap_script_sha256"], None),
        "go-containerregistry_Linux_x86_64.tar.gz": (
            release["asset_sha256"],
            release["asset_size"],
        ),
        "checksums.txt": (release["checksums_sha256"], release["checksums_size"]),
        "multiple.intoto.jsonl": (
            release["provenance_sha256"],
            release["provenance_size"],
        ),
        "slsa-verifier-linux-amd64": (verifier["asset_sha256"], verifier["asset_size"]),
    }
    for name, (expected_hash, expected_size) in expected_files.items():
        path = resolved / name
        if _sha256_file(path) != expected_hash or (
            expected_size is not None and path.stat().st_size != expected_size
        ):
            raise ConfigurationError("OpenHands v23 crane cache file identity changed")
    for name in ("crane", "slsa-verifier-linux-amd64"):
        binary = resolved / name
        if not os.access(binary, os.X_OK) or not 1 <= binary.stat().st_size <= 128 * 1024 * 1024:
            raise ConfigurationError("OpenHands v23 bootstrap binary is unsafe")
    receipt = _load_json(resolved / "bootstrap-receipt.json")
    receipt_hash = receipt.pop("receipt_hash", None)
    if (
        not isinstance(receipt_hash, str)
        or content_hash(receipt) != receipt_hash
        or receipt.get("format_id") != "verigym_openhands_hwe_v23_crane_bootstrap_receipt_v1"
        or receipt.get("release_tag") != release["release_tag"]
        or receipt.get("asset_sha256") != release["asset_sha256"]
        or receipt.get("checksums_sha256") != release["checksums_sha256"]
        or receipt.get("provenance_sha256") != release["provenance_sha256"]
        or receipt.get("source_uri") != release["source_uri"]
        or receipt.get("source_commit") != release["source_commit"]
        or receipt.get("builder_id") != release["builder_id"]
        or receipt.get("build_type") != release["build_type"]
        or receipt.get("workflow_entrypoint") != release["workflow_entrypoint"]
        or receipt.get("slsa_verifier_tag") != verifier["release_tag"]
        or receipt.get("slsa_verifier_sha256") != verifier["asset_sha256"]
        or receipt.get("slsa_verifier_executable_path") != "/download/slsa-verifier-linux-amd64"
        or receipt.get("sigstore_tuf_repository") != verifier["sigstore_tuf_repository"]
        or receipt.get("sigstore_trust_root_mode") != "slsa_verifier_builtin_tuf"
        or receipt.get("slsa_verification_passed") is not True
        or receipt.get("crane_sha256") != _sha256_file(resolved / "crane")
    ):
        raise ConfigurationError("OpenHands v23 crane bootstrap receipt changed")
    if _read_bootstrap_progress(resolved, require_passed=True) is None:
        raise ConfigurationError("OpenHands v23 crane bootstrap progress changed")
    receipt["receipt_hash"] = receipt_hash
    return receipt


def _read_bootstrap_progress(root: Path, *, require_passed: bool) -> dict[str, Any] | None:
    path = root / "bootstrap-progress.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 64 * 1024:
        return None
    try:
        value = _load_json(path)
    except ConfigurationError:
        return None
    progress_hash = value.pop("progress_hash", None)
    stages = value.get("completed_stages")
    output = value.get("slsa_verifier_output")
    if (
        not isinstance(progress_hash, str)
        or content_hash(value) != progress_hash
        or value.get("format_id") != "verigym_openhands_hwe_v23_crane_bootstrap_progress_v1"
        or value.get("status") not in {"running", "failed", "passed"}
        or not isinstance(stages, list)
        or any(stage not in _BOOTSTRAP_STAGES for stage in stages)
        or len(stages) != len(set(stages))
        or value.get("sigstore_trust_root_mode") != "slsa_verifier_builtin_tuf"
        or value.get("slsa_verifier_executable_path") != "/download/slsa-verifier-linux-amd64"
    ):
        return None
    if require_passed:
        if (
            value.get("status") != "passed"
            or value.get("current_stage") is not None
            or stages != _BOOTSTRAP_STAGES
            or not isinstance(output, dict)
            or output.get("exit_code") != 0
            or not isinstance(output.get("stdout_bytes"), int)
            or not isinstance(output.get("stderr_bytes"), int)
            or not isinstance(output.get("stderr_present"), bool)
            or output["stdout_bytes"] > _MAX_COMMAND_OUTPUT_BYTES
            or output["stderr_bytes"] > _MAX_COMMAND_OUTPUT_BYTES
        ):
            return None
    value["progress_hash"] = progress_hash
    return value


def _validate_local_image(binding: Any) -> dict[str, Any]:
    if not isinstance(binding, dict):
        raise ConfigurationError("OpenHands v23 local image binding is malformed")
    reference = binding.get("reference")
    image_id = binding.get("image_id")
    manifest = binding.get("manifest_digest")
    if (
        not isinstance(reference, str)
        or not isinstance(image_id, str)
        or not isinstance(manifest, str)
    ):
        raise ConfigurationError("OpenHands v23 local image binding is incomplete")
    values = _docker_json(["docker", "image", "inspect", reference])
    if len(values) != 1 or values[0].get("Id") != image_id:
        raise ConfigurationError("OpenHands v23 local image identity changed")
    digests = values[0].get("RepoDigests")
    observed = {
        value.rsplit("@", 1)[1]
        for value in digests or []
        if isinstance(value, str) and "@sha256:" in value
    }
    if observed != {manifest}:
        raise ConfigurationError("OpenHands v23 local image manifest changed")
    config = values[0].get("Config")
    if not isinstance(config, dict) or config.get("ExposedPorts") not in (None, {}):
        raise ConfigurationError("OpenHands v23 local image exposes a port")
    return {"reference": reference, "image_id": image_id, "manifest_digest": manifest}


def _validate_network() -> None:
    values = _docker_json(["docker", "network", "inspect", OPENHANDS_V23_NETWORK])
    if len(values) != 1:
        raise ConfigurationError("OpenHands v23 network inspection is malformed")
    network = values[0]
    if (
        network.get("Name") != OPENHANDS_V23_NETWORK
        or network.get("Driver") != "bridge"
        or network.get("Internal") is not False
        or network.get("Scope") != "local"
    ):
        raise ConfigurationError("OpenHands v23 dedicated download network is unavailable")


def _inspect_host_image(reference: str) -> dict[str, Any] | None:
    inspected = subprocess.run(
        ["docker", "image", "inspect", reference],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if inspected.returncode != 0:
        return None
    try:
        values = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("OpenHands v23 image inspection is malformed") from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ConfigurationError("OpenHands v23 image inspection is malformed")
    return values[0]


def _count_host_candidate_images() -> int:
    return sum(
        _inspect_host_image(reference) is not None
        for reference in OPENHANDS_V23_CANDIDATE_REFERENCES
    )


def _remove_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "container", "rm", "--force", container_name],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    remaining = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            f"name={container_name}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if remaining.stdout.strip():
        raise ConfigurationError("OpenHands v23 temporary container cleanup failed")


def _environment_map(values: Any) -> dict[str, str]:
    if not isinstance(values, list):
        return {}
    result: dict[str, str] = {}
    for value in values:
        name, separator, content = str(value).partition("=")
        if not separator or name in result:
            return {}
        result[name] = content
    return result


def _docker_json(arguments: list[str]) -> list[dict[str, Any]]:
    try:
        value = json.loads(
            subprocess.run(
                arguments,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ConfigurationError("OpenHands v23 Docker inspection failed") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConfigurationError("OpenHands v23 Docker inspection returned malformed data")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigurationError("OpenHands v23 JSON input contains a duplicate key")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError(f"unsafe OpenHands v23 JSON input: {expanded.name}")
    resolved = expanded.resolve(strict=True)
    if resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError(f"oversized OpenHands v23 JSON input: {resolved.name}")
    try:
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v23 JSON input: {resolved.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v23 JSON input is not an object: {resolved.name}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("OpenHands v23 preflight output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _sealed(progress: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(progress)
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "preflight-report.json", _sealed(progress))


def main() -> int:
    arguments = _parser().parse_args()
    report = run_v23_daemonless_preflight(
        approval_path=arguments.authorization,
        output=arguments.output,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "authorization_hash": report["authorization_hash"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
