#!/usr/bin/env python3
"""Stream, import, and zero-model qualify the frozen OpenHands v26 public reserve."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from verigym_hwe_bench.cva6_qualification import (
    run_zero_model_smoke,
    zero_model_fail_to_pass_eligible,
    zero_model_infrastructure_valid,
)
from verigym_hwe_bench.prepare import prepare_source
from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_QUALIFICATION_CANDIDATES,
    OPENHANDS_V19_QUALIFIED_TASK_TARGET,
    evaluate_v19_qualification_gate,
    frozen_v19_candidate_inventory,
)

from scripts.qualify_cva6_openhands_v19_public_tasks import (
    _completed_outcome,
    _source_binding,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

OPENHANDS_V26_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V26_STREAMED_QUALIFICATION"
OPENHANDS_V26_APPROVAL_FORMAT = "verigym_openhands_hwe_v26_streamed_qualification_authorization_v1"
OPENHANDS_V26_PROGRESS_FORMAT = "verigym_openhands_hwe_v26_streamed_qualification_progress_v1"
OPENHANDS_V26_APPROVAL_HASH = "570ac67b7c348a943030bea2e415a0aecc63cda31fe95465a4e913230ab501b8"
OPENHANDS_V26_IDENTITY = "openhands-hwe-v26-streamed-public-qualification-v1"
OPENHANDS_V26_NETWORK = "verigym-hwe-net"
OPENHANDS_V26_TOOL_CACHE = Path(
    "/data/jzhu484/Agent/.verigym-tmp/openhands-v24-crane-v0.22.0-slsa-v2.7.1"
)
OPENHANDS_V26_SCRATCH = Path(
    "/data/jzhu484/Agent/.verigym-tmp/openhands-v26-streamed-public-qualification-v1"
)
OPENHANDS_V26_CANDIDATE_REFERENCES = tuple(
    f"ghcr.io/pku-liang/openhwgroup_m_cva6:pr-{number}"
    for number in (2330, 3226, 2844, 3231, 2989, 1482, 3059)
)

_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_DIAGNOSTIC_BYTES = 16 * 1024
_MAX_CONFIG_BYTES = 16 * 1024 * 1024
_MAX_TARBALL_BYTES = 64 * 1024 * 1024 * 1024
_MAX_TARBALL_MEMBERS = 8_192
_MEMORY_BYTES = 1024 * 1024 * 1024
_PIDS_LIMIT = 128
_TMPFS = "rw,noexec,nosuid,nodev,size=67108864,mode=1777"
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CRANE_SHA256 = "771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94"
_EXECUTION_IMAGE_ENVIRONMENT = (
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


class _StageFailure(ConfigurationError):
    def __init__(self, message: str, *, diagnostic: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostic = copy.deepcopy(diagnostic)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def qualify_v26_streamed_public_tasks(
    *, approval_path: Path, dataset: Path, output: Path
) -> dict[str, Any]:
    """Transfer and qualify one candidate at a time, stopping at the exact five-task gate."""

    if os.environ.get(OPENHANDS_V26_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V26_OPT_IN_ENV}=1 is required")
    approved = _validated_authorization(_load_json(approval_path))
    resolved_dataset = _validated_dataset(dataset, approved=approved)
    inventory = frozen_v19_candidate_inventory(resolved_dataset)
    if inventory != approved["candidate_inventory"]:
        raise ConfigurationError("OpenHands v26 frozen candidate inventory changed")
    _validate_network()
    execution_image = _validate_local_image(approved["execution_image"])
    tool_cache = _validated_tool_cache(approved["tool_cache"])
    if (
        _count_host_candidate_images() != 0
        or _inspect_host_image(_sentinel_reference()) is not None
    ):
        raise ConfigurationError(
            "OpenHands v26 qualification requires an empty candidate inventory"
        )
    root = _new_directory(output)
    scratch = _new_scratch_directory()
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V26_PROGRESS_FORMAT,
        "status": "running",
        "identity": OPENHANDS_V26_IDENTITY,
        "authorization_hash": approved["authorization_hash"],
        "predecessor_v25_status": approved["predecessor"]["v25_status"],
        "predecessor_v25_progress_hash": approved["predecessor"]["v25_progress_hash"],
        "official_dataset_sha256": approved["dataset"]["sha256"],
        "official_dataset_revision": approved["dataset"]["revision"],
        "official_source_commit": approved["dataset"]["source_commit"],
        "candidate_order": list(OPENHANDS_V19_QUALIFICATION_CANDIDATES),
        "candidate_inventory": inventory,
        "network": OPENHANDS_V26_NETWORK,
        "verifier_network": "none",
        "implicit_image_pulls_allowed": False,
        "streamed_transfer_and_qualification": True,
        "shared_layer_cache_enabled": True,
        "bounded_pull_stderr_allowed": True,
        "model_process_count": 0,
        "provider_calls": 0,
        "heldout_task_ids_loaded": [],
        "active_task_id": None,
        "active_pull_receipt": None,
        "outcomes": [],
        "qualified_bindings": {},
        "image_transfers": {},
        "failure_diagnostic": None,
    }
    _write_progress(root, progress)
    failure: BaseException | None = None
    try:
        ca_output, ca_control, ca_receipt = _run_controlled_container(
            image_id=execution_image["image_id"],
            tool_cache=tool_cache,
            scratch=scratch,
            network="none",
            path="/usr/bin/test",
            arguments=["-s", "/etc/ssl/certs/ca-certificates.crt"],
            label_role="ca-bundle-precheck",
            timeout=300,
            output_bound=_MAX_DIAGNOSTIC_BYTES,
        )
        if ca_output or ca_receipt["stderr_bytes"] != 0:
            raise _StageFailure(
                "OpenHands v26 CA precheck emitted output",
                diagnostic={**ca_receipt, "failure_stage": "ca_bundle_precheck_output"},
            )
        progress["ca_bundle_precheck_passed"] = True
        progress["ca_bundle_control_hash"] = ca_control["control_hash"]
        progress["ca_bundle_command_receipt"] = ca_receipt
        _write_progress(root, progress)

        for candidate, reference in zip(inventory, OPENHANDS_V26_CANDIDATE_REFERENCES, strict=True):
            if _capacity_impossible(progress["outcomes"]):
                progress["status"] = "stopped_insufficient_capacity"
                progress["stop_reason"] = "fewer_than_five_qualified_tasks"
                break
            gate = evaluate_v19_qualification_gate(progress["outcomes"])
            if gate.satisfied:
                break
            task_id = str(candidate["task_id"])
            if task_id != gate.next_task_id:
                raise ConfigurationError("OpenHands v26 qualification schedule changed")
            progress["active_task_id"] = task_id
            _write_progress(root, progress)

            def persist_pull_receipt(receipt: dict[str, Any]) -> None:
                progress["active_pull_receipt"] = copy.deepcopy(receipt)
                _write_progress(root, progress)

            transfer = _transfer_candidate(
                reference=reference,
                image_id=execution_image["image_id"],
                tool_cache=tool_cache,
                scratch=scratch,
                pull_receipt_sink=persist_pull_receipt,
            )
            progress["image_transfers"][task_id] = transfer
            progress["active_pull_receipt"] = None
            _write_progress(root, progress)

            source_relative = f"sources/pr-{candidate['number']}"
            smoke_relative = f"smokes/pr-{candidate['number']}"
            source = root / source_relative
            smoke = root / smoke_relative
            binding: dict[str, str] | None = None
            report: dict[str, Any] | None = None
            task_failure: Exception | None = None
            try:
                prepare_source(
                    dataset=resolved_dataset,
                    output=source,
                    selected_tasks=[str(candidate["instance_id"])],
                    pull=False,
                    official_dataset_revision=approved["dataset"]["revision"],
                    official_source_commit=approved["dataset"]["source_commit"],
                    imported_image_bindings={
                        reference: {
                            "image_id": transfer["image_id"],
                            "manifest_digest": transfer["manifest_digest"],
                        }
                    },
                )
                binding = _source_binding(source, expected_task_id=task_id)
                if (
                    binding["verifier_image"] != transfer["image_id"]
                    or binding["verifier_manifest_digest"] != transfer["manifest_digest"]
                ):
                    raise ConfigurationError(
                        "OpenHands v26 prepared source transfer binding changed"
                    )
                report = run_zero_model_smoke(source=source, output=smoke)
            except Exception as exc:
                task_failure = exc
                report = _load_optional_report(smoke / "smoke-report.json")

            if report is not None and zero_model_infrastructure_valid(report):
                if binding is None:
                    try:
                        binding = _source_binding(source, expected_task_id=task_id)
                    except Exception as exc:
                        task_failure = exc
                if binding is not None:
                    outcome = _completed_outcome(
                        candidate=candidate,
                        binding=binding,
                        report=report,
                    )
                    progress["outcomes"].append(outcome)
                    if zero_model_fail_to_pass_eligible(report):
                        progress["qualified_bindings"][task_id] = {
                            **binding,
                            "source": source_relative,
                            "smoke": smoke_relative,
                            "transfer_receipt_hash": transfer["transfer_receipt_hash"],
                        }
                    progress["active_task_id"] = None
                    _write_progress(root, progress)
                    continue

            progress["outcomes"].append(
                {
                    "task_id": task_id,
                    "instance_id": candidate["instance_id"],
                    "changed_line_count": candidate["changed_line_count"],
                    "modified_file_count": candidate["modified_file_count"],
                    "infrastructure_valid": False,
                    "verifier_network": "none",
                    "verifier_image": transfer["image_id"],
                    "model_process_count": 0,
                    "base_failed": False,
                    "reference_passed": False,
                    "status": "infrastructure_invalid",
                    "failure_type": (
                        type(task_failure).__name__ if task_failure is not None else "UnknownError"
                    ),
                }
            )
            progress["active_task_id"] = None
            progress["status"] = "stopped_infrastructure_invalid"
            _write_progress(root, progress)
            raise ConfigurationError(
                f"OpenHands v26 qualification stopped on infrastructure-invalid {task_id}"
            ) from task_failure

        gate = evaluate_v19_qualification_gate(progress["outcomes"])
        progress["active_task_id"] = None
        progress["qualified_task_ids"] = list(gate.qualified_task_ids)
        progress["training_reserve_task_ids"] = list(gate.training_reserve_task_ids)
        progress["validation_reserve_task_ids"] = list(gate.validation_reserve_task_ids)
        if gate.satisfied:
            progress["status"] = "qualified_pending_agent_images"
        elif progress["status"] == "running":
            progress["status"] = "stopped_insufficient_capacity"
            progress["stop_reason"] = gate.reason
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
        if progress["status"] == "running":
            progress["status"] = "stopped_security_or_infrastructure_invalid"
        diagnostic = getattr(exc, "diagnostic", None)
        progress["failure_diagnostic"] = (
            diagnostic
            if isinstance(diagnostic, dict)
            else {
                "failure_stage": "qualification_orchestration",
                "failure_type": type(exc).__name__,
            }
        )
    finally:
        try:
            _cleanup_scratch(scratch)
            progress["temporary_transfer_scratch_removed"] = True
        except (Exception, KeyboardInterrupt) as exc:
            if failure is None:
                failure = exc
            progress["temporary_transfer_scratch_removed"] = False
            progress["status"] = "stopped_security_or_infrastructure_invalid"
            progress["failure_diagnostic"] = {
                "failure_stage": "transfer_scratch_cleanup",
                "failure_type": type(exc).__name__,
            }
        progress["host_candidate_images_present"] = _count_host_candidate_images()
        progress["temporary_containers_removed"] = _count_temporary_containers() == 0
        progress["docker_socket_mounted"] = False
        progress["privileged_container_used"] = False
        progress["tcp_api_listener_present"] = False
        _write_progress(root, progress)
    if failure is not None:
        raise ConfigurationError("OpenHands v26 streamed qualification failed") from failure
    return _sealed(progress)


def _transfer_candidate(
    *,
    reference: str,
    image_id: str,
    tool_cache: Path,
    scratch: Path,
    pull_receipt_sink: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    if reference not in OPENHANDS_V26_CANDIDATE_REFERENCES:
        raise ConfigurationError("OpenHands v26 transfer reference is not frozen")
    if _inspect_host_image(reference) is not None:
        raise ConfigurationError("OpenHands v26 candidate appeared before its transfer")
    digest_output, digest_control, digest_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V26_NETWORK,
        path="/tools/crane",
        arguments=["digest", reference],
        label_role="candidate-digest",
        timeout=300,
        output_bound=_MAX_DIAGNOSTIC_BYTES,
    )
    try:
        manifest_digest = digest_output.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise ConfigurationError("OpenHands v26 candidate digest is not ASCII") from exc
    if not _SHA256_DIGEST.fullmatch(manifest_digest):
        raise ConfigurationError("OpenHands v26 candidate digest is malformed")
    immutable_reference = f"{reference.rsplit(':', 1)[0]}@{manifest_digest}"
    config_output, config_control, config_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V26_NETWORK,
        path="/tools/crane",
        arguments=["config", immutable_reference],
        label_role="candidate-config",
        timeout=300,
        output_bound=_MAX_CONFIG_BYTES,
    )
    if not config_output:
        raise ConfigurationError("OpenHands v26 candidate config is empty")
    expected_image_id = f"sha256:{hashlib.sha256(config_output).hexdigest()}"
    archive = scratch / "candidate-image.tar"
    if archive.exists() or archive.is_symlink():
        raise ConfigurationError("OpenHands v26 candidate archive path is not empty")
    pull_output, pull_control, pull_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V26_NETWORK,
        path="/tools/crane",
        arguments=[
            "pull",
            immutable_reference,
            "/transfer/candidate-image.tar",
            "--format=tarball",
            "--cache_path=/transfer/layer-cache",
        ],
        label_role="candidate-pull",
        timeout=3_600,
        output_bound=_MAX_DIAGNOSTIC_BYTES,
    )
    stderr_bytes = pull_receipt.get("stderr_bytes")
    pull_observation = {
        **pull_receipt,
        "stdout_empty": not pull_output,
        "stderr_bounded": (
            isinstance(stderr_bytes, int) and 0 <= stderr_bytes <= _MAX_DIAGNOSTIC_BYTES
        ),
        "raw_output_persisted": False,
    }
    pull_receipt_sink(pull_observation)
    if not pull_observation["stderr_bounded"] or pull_output:
        raise _StageFailure(
            "OpenHands v26 crane pull output policy failed",
            diagnostic={**pull_observation, "failure_stage": "candidate_pull_output_policy"},
        )
    archive_receipt = _validated_crane_tarball(
        archive,
        expected_image_id=expected_image_id,
        expected_sentinel=_sentinel_reference(),
    )
    loaded = subprocess.run(
        ["docker", "image", "load", "--input", str(archive)],
        check=False,
        capture_output=True,
        timeout=3_600,
    )
    load_receipt = {
        "exit_code": loaded.returncode,
        "stdout_bytes": len(loaded.stdout),
        "stderr_bytes": len(loaded.stderr),
        "stdout_sha256": hashlib.sha256(loaded.stdout).hexdigest(),
        "stderr_present": bool(loaded.stderr),
    }
    if (
        loaded.returncode != 0
        or len(loaded.stdout) > _MAX_DIAGNOSTIC_BYTES
        or len(loaded.stderr) > _MAX_DIAGNOSTIC_BYTES
    ):
        raise _StageFailure(
            "OpenHands v26 Docker image load failed",
            diagnostic={**load_receipt, "failure_stage": "candidate_image_load"},
        )
    sentinel = _inspect_host_image(_sentinel_reference())
    if sentinel is None or sentinel.get("Id") != expected_image_id:
        raise ConfigurationError("OpenHands v26 loaded image config identity changed")
    tagged = subprocess.run(
        ["docker", "image", "tag", expected_image_id, reference],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if tagged.returncode != 0 or tagged.stdout or tagged.stderr:
        raise ConfigurationError("OpenHands v26 candidate image tag failed")
    imported = _inspect_host_image(reference)
    if imported is None or imported.get("Id") != expected_image_id:
        raise ConfigurationError("OpenHands v26 candidate image import identity changed")
    removed = subprocess.run(
        ["docker", "image", "rm", _sentinel_reference()],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if removed.returncode != 0 or _inspect_host_image(_sentinel_reference()) is not None:
        raise ConfigurationError("OpenHands v26 digest sentinel cleanup failed")
    archive.unlink()
    base = {
        "reference": reference,
        "manifest_digest": manifest_digest,
        "image_id": expected_image_id,
        "config_bytes": len(config_output),
        "config_sha256": hashlib.sha256(config_output).hexdigest(),
        "archive": archive_receipt,
        "digest_control_hash": digest_control["control_hash"],
        "config_control_hash": config_control["control_hash"],
        "pull_control_hash": pull_control["control_hash"],
        "command_receipts": {
            "digest": digest_receipt,
            "config": config_receipt,
            "pull": pull_receipt,
            "load": load_receipt,
        },
        "digest_qualified_pull": True,
        "shared_layer_cache_used": True,
        "pull_stdout_empty": True,
        "bounded_pull_stderr_allowed": True,
        "temporary_archive_removed": True,
        "sentinel_tag_removed": True,
    }
    return {**base, "transfer_receipt_hash": content_hash(base)}


def _run_controlled_container(
    *,
    image_id: str,
    tool_cache: Path,
    scratch: Path,
    network: str,
    path: str,
    arguments: list[str],
    label_role: str,
    timeout: int,
    output_bound: int,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    resolved_tools = tool_cache.resolve(strict=True)
    resolved_scratch = scratch.resolve(strict=True)
    container_name = f"verigym-hwe-v26-{label_role}-{os.getpid()}-{secrets.token_hex(4)}"
    command = [
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        container_name,
        "--label",
        f"org.verigym.owner={OPENHANDS_V26_IDENTITY}",
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
        "2",
        "--pids-limit",
        str(_PIDS_LIMIT),
        "--workdir",
        "/transfer",
        "--env",
        "HOME=/nonexistent",
        "--mount",
        f"type=bind,src={resolved_tools},dst=/tools,readonly",
        "--mount",
        f"type=bind,src={resolved_scratch},dst=/transfer",
        "--entrypoint",
        path,
        image_id,
        *arguments,
    ]
    diagnostic: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v26_command_receipt_v1",
        "role": label_role,
        "network": network,
        "create_exit_code": None,
        "create_stdout_bytes": 0,
        "create_stderr_bytes": 0,
        "exit_code": None,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "stderr_present": False,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "temporary_container_removed": False,
    }
    result: tuple[bytes, dict[str, Any]] | None = None
    failure: BaseException | None = None
    try:
        created = subprocess.run(command, check=False, capture_output=True, timeout=60)
        diagnostic.update(
            {
                "create_exit_code": created.returncode,
                "create_stdout_bytes": len(created.stdout),
                "create_stderr_bytes": len(created.stderr),
            }
        )
        if (
            created.returncode != 0
            or len(created.stdout) > _MAX_DIAGNOSTIC_BYTES
            or len(created.stderr) > _MAX_DIAGNOSTIC_BYTES
        ):
            raise ConfigurationError("OpenHands v26 Docker create failed or exceeded its bound")
        container_id = created.stdout.decode("ascii", errors="strict").strip()
        values = _docker_json(["docker", "container", "inspect", container_id])
        if not container_id or len(values) != 1:
            raise ConfigurationError("OpenHands v26 container inspection is malformed")
        control = _validate_container_inspection(
            values[0],
            image_id=image_id,
            tool_cache=resolved_tools,
            scratch=resolved_scratch,
            network=network,
            path=path,
            arguments=arguments,
            label_role=label_role,
        )
        started = subprocess.run(
            ["docker", "start", "--attach", container_id],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
        diagnostic.update(
            {
                "exit_code": started.returncode,
                "stdout_bytes": len(started.stdout),
                "stderr_bytes": len(started.stderr),
                "stderr_present": bool(started.stderr),
                "stdout_sha256": hashlib.sha256(started.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(started.stderr).hexdigest(),
                "control_hash": control["control_hash"],
            }
        )
        if (
            started.returncode != 0
            or len(started.stdout) > output_bound
            or len(started.stderr) > _MAX_DIAGNOSTIC_BYTES
        ):
            raise ConfigurationError(
                "OpenHands v26 controlled command failed or exceeded its bound"
            )
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
            "OpenHands v26 controlled container stage failed", diagnostic=diagnostic
        ) from failure
    if result is None:
        raise _StageFailure(
            "OpenHands v26 controlled container returned no result", diagnostic=diagnostic
        )
    return result[0], result[1], diagnostic


def _validate_container_inspection(
    container: dict[str, Any],
    *,
    image_id: str,
    tool_cache: Path,
    scratch: Path,
    network: str,
    path: str,
    arguments: list[str],
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
        raise ConfigurationError("OpenHands v26 effective controls are malformed")
    mount_map = {str(item.get("Destination")): item for item in mounts if isinstance(item, dict)}
    environment = _environment_map(config.get("Env"))
    expected_environment = _environment_map(list(_EXECUTION_IMAGE_ENVIRONMENT))
    security_options = host.get("SecurityOpt") or []
    tmpfs = host.get("Tmpfs") or {}
    labels = config.get("Labels") or {}
    tools_mount = mount_map.get("/tools")
    scratch_mount = mount_map.get("/transfer")
    valid = (
        container.get("Image") == image_id
        and container.get("Path") == path
        and container.get("Args") == arguments
        and host.get("NetworkMode") == network
        and host.get("IpcMode") == "none"
        and host.get("PidMode") in {"", None}
        and host.get("ReadonlyRootfs") is True
        and host.get("Privileged") is False
        and not (host.get("CapAdd") or [])
        and (host.get("CapDrop") or []) == ["ALL"]
        and not (host.get("Devices") or [])
        and any(str(value).startswith("no-new-privileges") for value in security_options)
        and host.get("Memory") == _MEMORY_BYTES
        and host.get("MemorySwap") == _MEMORY_BYTES
        and host.get("NanoCpus") == 2_000_000_000
        and host.get("PidsLimit") == _PIDS_LIMIT
        and host.get("PublishAllPorts") is False
        and host.get("PortBindings") in (None, {})
        and host.get("RestartPolicy", {}).get("Name") in {"", "no"}
        and host.get("AutoRemove") is False
        and isinstance(tmpfs, dict)
        and tmpfs.get("/tmp") == _TMPFS
        and len(mounts) == 2
        and isinstance(tools_mount, dict)
        and tools_mount.get("Source") == str(tool_cache)
        and tools_mount.get("RW") is False
        and isinstance(scratch_mount, dict)
        and scratch_mount.get("Source") == str(scratch)
        and scratch_mount.get("RW") is True
        and config.get("User") == f"{os.getuid()}:{os.getgid()}"
        and config.get("WorkingDir") == "/transfer"
        and config.get("ExposedPorts") in (None, {})
        and config.get("Volumes") in (None, {})
        and environment == expected_environment
        and labels.get("org.verigym.owner") == OPENHANDS_V26_IDENTITY
        and labels.get("org.verigym.role") == label_role
        and network_settings.get("Ports") in (None, {})
    )
    if not valid:
        raise ConfigurationError("OpenHands v26 effective container controls changed")
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
        "tool_cache_mount_read_only": True,
        "transfer_scratch_mount_read_write": True,
        "docker_socket_mounted": False,
        "published_ports": False,
        "environment_names": sorted(environment),
    }
    return {**base, "control_hash": content_hash(base)}


def _validated_crane_tarball(
    path: Path, *, expected_image_id: str, expected_sentinel: str
) -> dict[str, Any]:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= _MAX_TARBALL_BYTES
    ):
        raise ConfigurationError("OpenHands v26 candidate tarball is unsafe")
    with tarfile.open(path, mode="r:") as archive:
        members = archive.getmembers()
        if not 1 <= len(members) <= _MAX_TARBALL_MEMBERS:
            raise ConfigurationError("OpenHands v26 candidate tarball inventory is unbounded")
        names = [member.name for member in members]
        if len(names) != len(set(names)) or any(
            not member.isfile() or member.name.startswith(("/", "../")) or "/../" in member.name
            for member in members
        ):
            raise ConfigurationError("OpenHands v26 candidate tarball entries are unsafe")
        manifests = [member for member in members if member.name == "manifest.json"]
        if len(manifests) != 1 or not 1 <= manifests[0].size <= _MAX_JSON_BYTES:
            raise ConfigurationError("OpenHands v26 candidate tarball manifest is malformed")
        stream = archive.extractfile(manifests[0])
        if stream is None:
            raise ConfigurationError("OpenHands v26 candidate tarball manifest is unreadable")
        try:
            value = json.loads(stream.read())
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError("OpenHands v26 candidate tarball manifest is invalid") from exc
    if (
        not isinstance(value, list)
        or len(value) != 1
        or not isinstance(value[0], dict)
        or value[0].get("Config") != expected_image_id
        or value[0].get("RepoTags") != [expected_sentinel]
        or expected_image_id not in names
    ):
        raise ConfigurationError("OpenHands v26 candidate tarball identity changed")
    return {
        "size_bytes": metadata.st_size,
        "sha256": _sha256_file(path),
        "member_count": len(members),
        "config_image_id": expected_image_id,
        "sentinel_reference": expected_sentinel,
    }


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    observed_hash = value.pop("authorization_hash", None)
    if (
        observed_hash != OPENHANDS_V26_APPROVAL_HASH
        or content_hash(value) != OPENHANDS_V26_APPROVAL_HASH
    ):
        raise ConfigurationError("OpenHands v26 authorization identity changed")
    value["authorization_hash"] = observed_hash
    predecessor = value.get("predecessor")
    dataset = value.get("dataset")
    tool_cache = value.get("tool_cache")
    controls = value.get("required_controls")
    actions = value.get("authorized_actions")
    if (
        value.get("schema_version") != "1.0"
        or value.get("format_id") != OPENHANDS_V26_APPROVAL_FORMAT
        or value.get("status") != "authorized_pending_qualification"
        or value.get("identity") != OPENHANDS_V26_IDENTITY
        or value.get("network") != OPENHANDS_V26_NETWORK
        or value.get("candidate_inventory") is None
        or value.get("qualification_target") != 5
        or value.get("training_reserve_count") != 3
        or value.get("validation_reserve_count") != 2
        or value.get("failure_policy") != "stop_immediately"
        or value.get("production_training_ready") is not False
        or value.get("benchmark_score_claimed") is not False
        or not isinstance(predecessor, dict)
        or predecessor.get("v25_status") != "stopped_security_or_infrastructure_invalid"
        or predecessor.get("v25_progress_hash")
        != "f3fa6795b0db0e7592dc168d9dd15d842f80945c1df06fa969b14a3642be916b"
        or predecessor.get("v25_report_file_sha256")
        != "90a7d04a3cb16863b366757584859dfb7ae96c52bccef316a02573ef58a22594"
        or predecessor.get("v25_result_scan_hash")
        != "26febefa88a6942f9d7ff9463bbda9dfe35ab70828bea6e0220138a89320ff98"
        or predecessor.get("v25_audit_commit") != "ac9f9e77fa199bcc8e5df8bbfe1d334a1601839e"
        or not isinstance(dataset, dict)
        or dataset.get("sha256")
        != "732c5dac910815c1c7ac72c8ccca88f66dbb7ed5d097806a5ddea611102f60f1"
        or dataset.get("revision") != "1403afb57ce056c659c82b35e39c38c6a21ee635"
        or dataset.get("source_commit") != "10c78a87e1f92695d78d15b1464a6107dcac8837"
        or not isinstance(tool_cache, dict)
        or tool_cache.get("source_identity") != "openhands-hwe-v24-daemonless-prewarm-preflight-v1"
        or tool_cache.get("crane_release_tag") != "v0.22.0"
        or tool_cache.get("crane_sha256") != _CRANE_SHA256
        or tool_cache.get("bootstrap_receipt_hash")
        != "b44ecb1ceb8d750d6fb2b8ea32c82a1efc3aa437e274b022f660b332ca51407a"
        or tool_cache.get("bootstrap_progress_hash")
        != "1ae3817dc084d06330dac5402ac8c64c8a5d27f33c8e5bea338eeb4e719cd8f6"
        or not isinstance(controls, dict)
        or any(controls.get(key) is not expected for key, expected in _required_controls().items())
        or not isinstance(actions, dict)
        or actions.get("resolve_candidate_digests") is not True
        or actions.get("download_candidate_images") is not True
        or actions.get("load_candidate_images") is not True
        or actions.get("run_zero_model_qualification") is not True
        or any(
            actions.get(key) is not False
            for key in (
                "invoke_provider",
                "build_agent_images",
                "materialize_canary_contract",
                "start_collection",
                "start_training",
                "load_heldout_tasks",
            )
        )
    ):
        raise ConfigurationError("OpenHands v26 authorization scope changed")
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
        "two_exact_mounts": True,
        "default_bridge_used": False,
        "provider_or_registry_credentials_present": False,
        "proxy_values_forwarded": False,
        "tls_verification_disabled": False,
        "networkless_verifier": True,
        "digest_qualified_candidate_pull": True,
        "remote_config_to_local_image_id_binding": True,
        "tarball_inventory_validation": True,
        "atomic_progress": True,
        "shared_content_addressed_layer_cache": True,
        "streamed_capacity_recomputation": True,
        "pull_stdout_must_be_empty": True,
        "bounded_pull_stderr_allowed": True,
        "content_free_pull_receipt_persisted_before_policy": True,
        "automatic_retry": False,
    }


def _validated_dataset(path: Path, *, approved: dict[str, Any]) -> Path:
    expanded = path.expanduser()
    if (
        expanded.is_symlink()
        or not expanded.is_file()
        or expanded.stat().st_size > 512 * 1024 * 1024
    ):
        raise ConfigurationError("OpenHands v26 dataset is unsafe")
    resolved = expanded.resolve(strict=True)
    if _sha256_file(resolved) != approved["dataset"]["sha256"]:
        raise ConfigurationError("OpenHands v26 dataset identity changed")
    return resolved


def _validated_tool_cache(binding: dict[str, Any]) -> Path:
    resolved = OPENHANDS_V26_TOOL_CACHE.resolve(strict=True)
    if (
        OPENHANDS_V26_TOOL_CACHE.is_symlink()
        or not resolved.is_dir()
        or not resolved.is_relative_to(Path("/data/jzhu484/Agent/.verigym-tmp"))
    ):
        raise ConfigurationError("OpenHands v26 tool cache path is unsafe")
    files = binding.get("files")
    if not isinstance(files, dict) or set(files) != {path.name for path in resolved.iterdir()}:
        raise ConfigurationError("OpenHands v26 tool cache inventory changed")
    for name, expected in files.items():
        path = resolved / name
        metadata = path.lstat()
        if (
            not isinstance(expected, dict)
            or path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != expected.get("size")
            or _sha256_file(path) != expected.get("sha256")
        ):
            raise ConfigurationError("OpenHands v26 tool cache file identity changed")
    crane = resolved / "crane"
    if _sha256_file(crane) != _CRANE_SHA256 or not os.access(crane, os.X_OK):
        raise ConfigurationError("OpenHands v26 crane executable identity changed")
    receipt = _load_json(resolved / "bootstrap-receipt.json")
    receipt_hash = receipt.pop("receipt_hash", None)
    if (
        receipt_hash != binding.get("bootstrap_receipt_hash")
        or content_hash(receipt) != receipt_hash
        or receipt.get("format_id") != "verigym_openhands_hwe_v24_crane_bootstrap_receipt_v1"
        or receipt.get("release_tag") != binding.get("crane_release_tag")
        or receipt.get("crane_sha256") != _CRANE_SHA256
        or receipt.get("slsa_verification_passed") is not True
    ):
        raise ConfigurationError("OpenHands v26 bootstrap receipt identity changed")
    progress = _load_json(resolved / "bootstrap-progress.json")
    progress_hash = progress.pop("progress_hash", None)
    if (
        progress_hash != binding.get("bootstrap_progress_hash")
        or content_hash(progress) != progress_hash
        or progress.get("status") != "passed"
        or progress.get("current_stage") is not None
    ):
        raise ConfigurationError("OpenHands v26 bootstrap progress identity changed")
    return resolved


def _validate_local_image(binding: Any) -> dict[str, str]:
    if not isinstance(binding, dict):
        raise ConfigurationError("OpenHands v26 execution image binding is malformed")
    reference = binding.get("reference")
    image_id = binding.get("image_id")
    manifest = binding.get("manifest_digest")
    if not all(isinstance(item, str) for item in (reference, image_id, manifest)):
        raise ConfigurationError("OpenHands v26 execution image binding is incomplete")
    values = _docker_json(["docker", "image", "inspect", str(reference)])
    digests = values[0].get("RepoDigests") if len(values) == 1 else None
    observed = {
        value.rsplit("@", 1)[1]
        for value in digests or []
        if isinstance(value, str) and "@sha256:" in value
    }
    if len(values) != 1 or values[0].get("Id") != image_id or observed != {manifest}:
        raise ConfigurationError("OpenHands v26 execution image identity changed")
    config = values[0].get("Config")
    if not isinstance(config, dict) or config.get("ExposedPorts") not in (None, {}):
        raise ConfigurationError("OpenHands v26 execution image exposes a port")
    return {
        "reference": str(reference),
        "image_id": str(image_id),
        "manifest_digest": str(manifest),
    }


def _validate_network() -> None:
    values = _docker_json(["docker", "network", "inspect", OPENHANDS_V26_NETWORK])
    if len(values) != 1:
        raise ConfigurationError("OpenHands v26 network inspection is malformed")
    network = values[0]
    if (
        network.get("Name") != OPENHANDS_V26_NETWORK
        or network.get("Driver") != "bridge"
        or network.get("Internal") is not False
        or network.get("Scope") != "local"
    ):
        raise ConfigurationError("OpenHands v26 dedicated download network is unavailable")


def _capacity_impossible(outcomes: list[dict[str, Any]]) -> bool:
    qualified = sum(
        item.get("infrastructure_valid") is True
        and item.get("base_failed") is True
        and item.get("reference_passed") is True
        for item in outcomes
    )
    remaining = len(OPENHANDS_V19_QUALIFICATION_CANDIDATES) - len(outcomes)
    return qualified + remaining < OPENHANDS_V19_QUALIFIED_TASK_TARGET


def _sentinel_reference() -> str:
    return "ghcr.io/pku-liang/openhwgroup_m_cva6:i-was-a-digest"


def _inspect_host_image(reference: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["docker", "image", "inspect", reference],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("OpenHands v26 image inspection is malformed") from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ConfigurationError("OpenHands v26 image inspection is malformed")
    return values[0]


def _count_host_candidate_images() -> int:
    return sum(
        _inspect_host_image(reference) is not None
        for reference in OPENHANDS_V26_CANDIDATE_REFERENCES
    )


def _count_temporary_containers() -> int:
    result = subprocess.run(
        ["docker", "container", "ls", "--all", "--quiet", "--filter", "name=verigym-hwe-v26-"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return len(result.stdout.splitlines())


def _remove_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "container", "rm", "--force", container_name],
        check=False,
        capture_output=True,
        timeout=60,
    )
    remaining = subprocess.run(
        ["docker", "container", "ls", "--all", "--quiet", "--filter", f"name={container_name}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if remaining.stdout.strip():
        raise ConfigurationError("OpenHands v26 temporary container cleanup failed")


def _load_optional_report(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _new_scratch_directory() -> Path:
    if OPENHANDS_V26_SCRATCH.exists() or OPENHANDS_V26_SCRATCH.is_symlink():
        raise ConfigurationError("OpenHands v26 transfer scratch must be new")
    OPENHANDS_V26_SCRATCH.mkdir(parents=True)
    return OPENHANDS_V26_SCRATCH.resolve(strict=True)


def _cleanup_scratch(path: Path) -> None:
    resolved_parent = Path("/data/jzhu484/Agent/.verigym-tmp").resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved != OPENHANDS_V26_SCRATCH or not resolved.is_relative_to(resolved_parent):
        raise ConfigurationError("OpenHands v26 scratch cleanup path changed")
    shutil.rmtree(resolved)


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("OpenHands v26 output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


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
        raise ConfigurationError("OpenHands v26 Docker inspection failed") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConfigurationError("OpenHands v26 Docker inspection returned malformed data")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigurationError("OpenHands v26 JSON input contains a duplicate key")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file() or expanded.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError(f"unsafe OpenHands v26 JSON input: {expanded.name}")
    try:
        value = json.loads(expanded.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v26 JSON input: {expanded.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v26 JSON input is not an object: {expanded.name}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sealed(progress: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(progress)
    base.pop("progress_hash", None)
    return {**base, "progress_hash": content_hash(base)}


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "qualification-progress.json", _sealed(progress))


def main() -> int:
    arguments = _parser().parse_args()
    progress = qualify_v26_streamed_public_tasks(
        approval_path=arguments.authorization,
        dataset=arguments.dataset,
        output=arguments.output,
    )
    print(
        json.dumps(
            {
                "status": progress["status"],
                "qualified_task_ids": progress.get("qualified_task_ids", []),
                "progress_hash": progress["progress_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if progress["status"] == "qualified_pending_agent_images" else 2


if __name__ == "__main__":
    raise SystemExit(main())
