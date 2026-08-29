#!/usr/bin/env python3
"""Run the authorized no-candidate safety preflight for daemonless HWE image transfer."""

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

OPENHANDS_V20_PREFLIGHT_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V20_DAEMONLESS_PREFLIGHT"
OPENHANDS_V20_APPROVAL_FORMAT = "verigym_openhands_hwe_v20_daemonless_preflight_authorization_v1"
OPENHANDS_V20_PREFLIGHT_FORMAT = "verigym_openhands_hwe_v20_daemonless_preflight_report_v1"
OPENHANDS_V20_APPROVAL_HASH = "1741352e5a2664191f594d975c798279e4bb19b4ef0c9f1815e2e2a6e17b9898"
OPENHANDS_V20_NETWORK = "verigym-hwe-net"
OPENHANDS_V20_TOOL_CACHE = Path("/data/jzhu484/Agent/.verigym-tmp/openhands-v20-crane-v0.22.0")
OPENHANDS_V20_CANDIDATE_REFERENCES = tuple(
    f"ghcr.io/pku-liang/openhwgroup_m_cva6:pr-{number}"
    for number in (2330, 3226, 2844, 3231, 2989, 1482, 3059)
)

_REPOSITORY = Path(__file__).resolve().parents[1]
_BOOTSTRAP_HELPER = _REPOSITORY / "scripts/fetch_pinned_crane_release.py"
_SCRATCH_PARENT = Path("/data/jzhu484/Agent/.verigym-tmp")
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MEMORY_BYTES = 512 * 1024 * 1024
_PIDS_LIMIT = 128
_TMPFS = "rw,noexec,nosuid,nodev,size=67108864,mode=1777"
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def run_v20_daemonless_preflight(*, approval_path: Path, output: Path) -> dict[str, Any]:
    """Bootstrap pinned crane and prove the daemonless effective controls without candidates."""

    if os.environ.get(OPENHANDS_V20_PREFLIGHT_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V20_PREFLIGHT_OPT_IN_ENV}=1 is required")
    approved = _validated_authorization(_load_json(approval_path))
    _validate_network()
    bootstrap_image = _validate_local_image(approved["bootstrap_image"])
    execution_image = _validate_local_image(approved["execution_image"])
    if _count_host_candidate_images() != 0:
        raise ConfigurationError("OpenHands v20 preflight found a candidate image already present")

    root = _new_directory(output)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V20_PREFLIGHT_FORMAT,
        "status": "running",
        "identity": approved["identity"],
        "authorization_hash": approved["authorization_hash"],
        "predecessor_v19_status": approved["predecessor"]["v19_status"],
        "network": OPENHANDS_V20_NETWORK,
        "candidate_references": list(OPENHANDS_V20_CANDIDATE_REFERENCES),
        "candidate_downloads_authorized": False,
        "candidate_downloads_started": False,
        "candidate_images_imported": 0,
        "host_candidate_images_present": 0,
        "qualification_started": False,
        "provider_calls": 0,
        "heldout_task_ids_loaded": [],
    }
    _write_progress(root, progress)
    failure: BaseException | None = None
    try:
        cache, bootstrap = _bootstrap_crane(
            approved,
            bootstrap_image_id=bootstrap_image["image_id"],
        )
        crane_receipt = _validated_crane_cache(cache, approved=approved)
        version_output, version_control = _run_controlled_container(
            image_id=execution_image["image_id"],
            source=cache,
            mount_read_only=True,
            network="none",
            path="/download/crane",
            arguments=["version"],
            expected_environment=_EXECUTION_IMAGE_ENVIRONMENT,
            label_role="crane-version",
        )
        expected_version = f"{approved['crane_release']['release_tag']}\n".encode()
        if version_output != expected_version:
            raise ConfigurationError("OpenHands v20 crane version output changed")
        probe_output, probe_control = _run_controlled_container(
            image_id=execution_image["image_id"],
            source=cache,
            mount_read_only=True,
            network=OPENHANDS_V20_NETWORK,
            path="/download/crane",
            arguments=["digest", approved["probe"]["reference"]],
            expected_environment=_EXECUTION_IMAGE_ENVIRONMENT,
            label_role="crane-digest-probe",
        )
        expected_digest = f"{approved['probe']['expected_manifest_digest']}\n".encode()
        if probe_output != expected_digest:
            raise ConfigurationError("OpenHands v20 registered digest probe changed")
        if _count_host_candidate_images() != 0:
            raise ConfigurationError("OpenHands v20 preflight imported a candidate image")
        progress.update(
            {
                "status": "preflight_passed",
                "crane_release_tag": approved["crane_release"]["release_tag"],
                "crane_sha256": crane_receipt["crane_sha256"],
                "bootstrap_control_hash": bootstrap["control_hash"],
                "version_control_hash": version_control["control_hash"],
                "probe_control_hash": probe_control["control_hash"],
                "probe_manifest_digest": approved["probe"]["expected_manifest_digest"],
                "release_asset_download_count": 3,
                "registry_probe_count": 1,
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
        raise ConfigurationError("OpenHands v20 daemonless preflight failed") from failure
    return _sealed(progress)


def _bootstrap_crane(
    approved: dict[str, Any], *, bootstrap_image_id: str
) -> tuple[Path, dict[str, Any]]:
    if OPENHANDS_V20_TOOL_CACHE.exists() or OPENHANDS_V20_TOOL_CACHE.is_symlink():
        raise ConfigurationError("OpenHands v20 crane cache must be new for the preflight")
    _SCRATCH_PARENT.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="openhands-v20-crane-building.", dir=_SCRATCH_PARENT))
    try:
        helper = temporary / _BOOTSTRAP_HELPER.name
        shutil.copyfile(_BOOTSTRAP_HELPER, helper)
        helper.chmod(0o400)
        release = approved["crane_release"]
        output, control = _run_controlled_container(
            image_id=bootstrap_image_id,
            source=temporary,
            mount_read_only=False,
            network=OPENHANDS_V20_NETWORK,
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
            ],
            expected_environment=_BOOTSTRAP_IMAGE_ENVIRONMENT,
            label_role="crane-bootstrap",
        )
        if output:
            raise ConfigurationError("OpenHands v20 crane bootstrap emitted output")
        _validated_crane_cache(temporary, approved=approved)
        os.replace(temporary, OPENHANDS_V20_TOOL_CACHE)
        return OPENHANDS_V20_TOOL_CACHE, control
    finally:
        if temporary.exists():
            if not temporary.is_relative_to(_SCRATCH_PARENT):
                raise ConfigurationError("OpenHands v20 crane scratch path escaped")
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
) -> tuple[bytes, dict[str, Any]]:
    resolved_source = source.resolve(strict=True)
    container_name = f"verigym-hwe-v20-{label_role}-{os.getpid()}-{secrets.token_hex(4)}"
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
        "org.verigym.owner=openhands-hwe-v20-daemonless-preflight-v1",
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
    container_id: str | None = None
    try:
        created = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        container_id = created.stdout.strip()
        if not container_id:
            raise ConfigurationError("OpenHands v20 Docker create returned no container ID")
        values = _docker_json(["docker", "container", "inspect", container_id])
        if len(values) != 1:
            raise ConfigurationError("OpenHands v20 container inspection is malformed")
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
        if len(started.stdout) > 4096 or len(started.stderr) > 4096:
            raise ConfigurationError("OpenHands v20 controlled container output exceeded its bound")
        if started.returncode != 0 or started.stderr:
            raise ConfigurationError("OpenHands v20 controlled container command failed")
        return started.stdout, control
    finally:
        _remove_container(container_name)


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
    ):
        raise ConfigurationError("OpenHands v20 effective container controls are malformed")
    if not isinstance(mounts, list):
        raise ConfigurationError("OpenHands v20 effective mounts are malformed")
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
        and labels.get("org.verigym.owner") == "openhands-hwe-v20-daemonless-preflight-v1"
        and labels.get("org.verigym.role") == label_role
        and network_settings.get("Ports") in (None, {})
    )
    if not valid:
        raise ConfigurationError("OpenHands v20 effective container controls changed")
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
        observed_hash != OPENHANDS_V20_APPROVAL_HASH
        or content_hash(value) != OPENHANDS_V20_APPROVAL_HASH
    ):
        raise ConfigurationError("OpenHands v20 preflight authorization identity changed")
    value["authorization_hash"] = observed_hash
    actions = value.get("authorized_actions")
    controls = value.get("required_controls")
    release = value.get("crane_release")
    if (
        value.get("format_id") != OPENHANDS_V20_APPROVAL_FORMAT
        or value.get("status") != "authorized_pending_preflight"
        or value.get("identity") != "openhands-hwe-v20-daemonless-prewarm-preflight-v1"
        or value.get("network") != OPENHANDS_V20_NETWORK
        or value.get("failure_policy") != "stop_immediately"
        or value.get("production_training_ready") is not False
        or value.get("benchmark_score_claimed") is not False
        or not isinstance(actions, dict)
        or actions.get("download_pinned_crane_release") is not True
        or actions.get("run_crane_version_network_none") is not True
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
        or _sha256_file(_BOOTSTRAP_HELPER) != release.get("bootstrap_script_sha256")
    ):
        raise ConfigurationError("OpenHands v20 preflight authorization scope changed")
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
    }


def _validated_crane_cache(cache: Path, *, approved: dict[str, Any]) -> dict[str, Any]:
    resolved = cache.resolve(strict=True)
    if cache.is_symlink() or not resolved.is_dir() or not resolved.is_relative_to(_SCRATCH_PARENT):
        raise ConfigurationError("OpenHands v20 crane cache path is unsafe")
    expected_names = {
        _BOOTSTRAP_HELPER.name,
        "go-containerregistry_Linux_x86_64.tar.gz",
        "checksums.txt",
        "multiple.intoto.jsonl",
        "crane",
        "bootstrap-receipt.json",
    }
    paths = list(resolved.iterdir())
    if {path.name for path in paths} != expected_names:
        raise ConfigurationError("OpenHands v20 crane cache inventory changed")
    for path in paths:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ConfigurationError("OpenHands v20 crane cache contains an unsafe entry")
    release = approved["crane_release"]
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
    }
    for name, (expected_hash, expected_size) in expected_files.items():
        path = resolved / name
        if _sha256_file(path) != expected_hash or (
            expected_size is not None and path.stat().st_size != expected_size
        ):
            raise ConfigurationError("OpenHands v20 crane cache file identity changed")
    crane = resolved / "crane"
    if not os.access(crane, os.X_OK) or not 1 <= crane.stat().st_size <= 128 * 1024 * 1024:
        raise ConfigurationError("OpenHands v20 crane binary is unsafe")
    receipt = _load_json(resolved / "bootstrap-receipt.json")
    receipt_hash = receipt.pop("receipt_hash", None)
    if (
        not isinstance(receipt_hash, str)
        or content_hash(receipt) != receipt_hash
        or receipt.get("format_id") != "verigym_openhands_hwe_v20_crane_bootstrap_receipt_v1"
        or receipt.get("release_tag") != release["release_tag"]
        or receipt.get("asset_sha256") != release["asset_sha256"]
        or receipt.get("checksums_sha256") != release["checksums_sha256"]
        or receipt.get("provenance_sha256") != release["provenance_sha256"]
        or receipt.get("crane_sha256") != _sha256_file(crane)
    ):
        raise ConfigurationError("OpenHands v20 crane bootstrap receipt changed")
    receipt["receipt_hash"] = receipt_hash
    return receipt


def _validate_local_image(binding: Any) -> dict[str, Any]:
    if not isinstance(binding, dict):
        raise ConfigurationError("OpenHands v20 local image binding is malformed")
    reference = binding.get("reference")
    image_id = binding.get("image_id")
    manifest = binding.get("manifest_digest")
    if (
        not isinstance(reference, str)
        or not isinstance(image_id, str)
        or not isinstance(manifest, str)
    ):
        raise ConfigurationError("OpenHands v20 local image binding is incomplete")
    values = _docker_json(["docker", "image", "inspect", reference])
    if len(values) != 1 or values[0].get("Id") != image_id:
        raise ConfigurationError("OpenHands v20 local image identity changed")
    digests = values[0].get("RepoDigests")
    observed = {
        value.rsplit("@", 1)[1]
        for value in digests or []
        if isinstance(value, str) and "@sha256:" in value
    }
    if observed != {manifest}:
        raise ConfigurationError("OpenHands v20 local image manifest changed")
    config = values[0].get("Config")
    if not isinstance(config, dict) or config.get("ExposedPorts") not in (None, {}):
        raise ConfigurationError("OpenHands v20 local image exposes a port")
    return {"reference": reference, "image_id": image_id, "manifest_digest": manifest}


def _validate_network() -> None:
    values = _docker_json(["docker", "network", "inspect", OPENHANDS_V20_NETWORK])
    if len(values) != 1:
        raise ConfigurationError("OpenHands v20 network inspection is malformed")
    network = values[0]
    if (
        network.get("Name") != OPENHANDS_V20_NETWORK
        or network.get("Driver") != "bridge"
        or network.get("Internal") is not False
        or network.get("Scope") != "local"
    ):
        raise ConfigurationError("OpenHands v20 dedicated download network is unavailable")


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
        raise ConfigurationError("OpenHands v20 image inspection is malformed") from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ConfigurationError("OpenHands v20 image inspection is malformed")
    return values[0]


def _count_host_candidate_images() -> int:
    return sum(
        _inspect_host_image(reference) is not None
        for reference in OPENHANDS_V20_CANDIDATE_REFERENCES
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
        raise ConfigurationError("OpenHands v20 temporary container cleanup failed")


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
        raise ConfigurationError("OpenHands v20 Docker inspection failed") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConfigurationError("OpenHands v20 Docker inspection returned malformed data")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigurationError("OpenHands v20 JSON input contains a duplicate key")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError(f"unsafe OpenHands v20 JSON input: {expanded.name}")
    resolved = expanded.resolve(strict=True)
    if resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError(f"oversized OpenHands v20 JSON input: {resolved.name}")
    try:
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v20 JSON input: {resolved.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v20 JSON input is not an object: {resolved.name}")
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
            raise ConfigurationError("OpenHands v20 preflight output must be new or empty")
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
    report = run_v20_daemonless_preflight(
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
