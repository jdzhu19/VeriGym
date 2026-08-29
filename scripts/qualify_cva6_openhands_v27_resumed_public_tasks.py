#!/usr/bin/env python3
"""Resume public qualification from sealed v26 evidence without retrying prior tasks."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import re
import secrets
import shutil
import subprocess
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
    frozen_v19_candidate_inventory,
)

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

_v19 = importlib.import_module("scripts.qualify_cva6_openhands_v19_public_tasks")
_v26 = importlib.import_module("scripts.qualify_cva6_openhands_v26_streamed_public_tasks")

OPENHANDS_V27_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V27_RESUMED_QUALIFICATION"
OPENHANDS_V27_APPROVAL_FORMAT = "verigym_openhands_hwe_v27_resumed_qualification_authorization_v1"
OPENHANDS_V27_PROGRESS_FORMAT = "verigym_openhands_hwe_v27_resumed_qualification_progress_v1"
OPENHANDS_V27_APPROVAL_HASH = "627d4debd68503ab879c2478d50d875871d00a88465f8d87086a90b825295626"
OPENHANDS_V27_IDENTITY = "openhands-hwe-v27-resumed-public-qualification-v1"
OPENHANDS_V27_NETWORK = "verigym-hwe-net"
OPENHANDS_V27_SCRATCH = Path(
    "/data/jzhu484/Agent/.verigym-tmp/openhands-v27-resumed-public-qualification-v1"
)
OPENHANDS_V27_CONTINUATION_NUMBERS = (3231, 2989, 1482, 3059)
OPENHANDS_V27_CONTINUATION_REFERENCES = tuple(
    f"ghcr.io/pku-liang/openhwgroup_m_cva6:pr-{number}"
    for number in OPENHANDS_V27_CONTINUATION_NUMBERS
)
OPENHANDS_V27_ERROR_CATEGORIES = (
    "archive_writer",
    "cache_filesystem",
    "dns_resolution",
    "registry_http_4xx",
    "registry_http_5xx",
    "resource_exhaustion",
    "tls_verification",
    "transport_connection",
    "transport_timeout",
    "unknown",
)

_PREDECESSOR_PROGRESS_HASH = "386941d45755c3c023c7a075b0ef0441437bdd823bc886ad33d7711a67006a76"
_PREDECESSOR_FILE_SHA256 = "751ad6ced84f445794bf3cf23ed300170f0dcdbd657789cf8340a1a891f411b5"
_PREDECESSOR_FAILURE_HASH = "0b856e05a7b778fb264a65545c19d77b4f0805eab58889b346df2bc2b43a9327"
_PREDECESSOR_AUDIT_COMMIT = "f9d25e52724506b575b3f9d71f3aaae63be27df4"
_V26_APPROVAL_FILE = Path(
    "configs/training/qwen35_hwe_openhands_v26_streamed_qualification_v1.json"
)
_MAX_DIAGNOSTIC_BYTES = 16 * 1024
_MAX_CONFIG_BYTES = 16 * 1024 * 1024
_MEMORY_BYTES = 1024 * 1024 * 1024
_PIDS_LIMIT = 128
_TMPFS = "rw,noexec,nosuid,nodev,size=67108864,mode=1777"
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class _StageFailure(ConfigurationError):
    def __init__(self, message: str, *, diagnostic: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostic = copy.deepcopy(diagnostic)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def qualify_v27_resumed_public_tasks(
    *, approval_path: Path, predecessor_path: Path, dataset: Path, output: Path
) -> dict[str, Any]:
    """Import two sealed passes and stream only the four never-attempted candidates."""

    if os.environ.get(OPENHANDS_V27_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V27_OPT_IN_ENV}=1 is required")
    approved = _validated_authorization(_v26._load_json(approval_path))
    v26_approved = _v26._validated_authorization(_v26._load_json(_V26_APPROVAL_FILE))
    resolved_dataset = _v26._validated_dataset(dataset, approved=v26_approved)
    inventory = frozen_v19_candidate_inventory(resolved_dataset)
    if inventory != v26_approved["candidate_inventory"]:
        raise ConfigurationError("OpenHands v27 frozen candidate inventory changed")
    predecessor = _validated_predecessor(predecessor_path, approved["predecessor"])
    _validate_predecessor_images(predecessor)
    _v26._validate_network()
    execution_image = _v26._validate_local_image(v26_approved["execution_image"])
    tool_cache = _v26._validated_tool_cache(v26_approved["tool_cache"])
    if _v26._inspect_host_image(_sentinel_reference()) is not None:
        raise ConfigurationError("OpenHands v27 digest sentinel already exists")

    root = _v26._new_directory(output)
    scratch = _new_scratch_directory()
    outcomes = copy.deepcopy(predecessor["outcomes"])
    outcomes.append(_predecessor_failure_outcome(inventory[2], predecessor))
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V27_PROGRESS_FORMAT,
        "status": "running",
        "identity": OPENHANDS_V27_IDENTITY,
        "authorization_hash": approved["authorization_hash"],
        "predecessor_v26_progress_hash": predecessor["progress_hash"],
        "predecessor_v26_file_sha256": approved["predecessor"]["progress_file_sha256"],
        "predecessor_attempted_task_ids": approved["predecessor"]["attempted_task_ids"],
        "historical_attempts_retried": False,
        "official_dataset_sha256": v26_approved["dataset"]["sha256"],
        "official_dataset_revision": v26_approved["dataset"]["revision"],
        "official_source_commit": v26_approved["dataset"]["source_commit"],
        "candidate_order": list(OPENHANDS_V19_QUALIFICATION_CANDIDATES),
        "continuation_candidate_numbers": list(OPENHANDS_V27_CONTINUATION_NUMBERS),
        "network": OPENHANDS_V27_NETWORK,
        "verifier_network": "none",
        "implicit_image_pulls_allowed": False,
        "streamed_transfer_and_qualification": True,
        "shared_layer_cache_enabled": True,
        "safe_error_categories": list(OPENHANDS_V27_ERROR_CATEGORIES),
        "raw_command_output_persisted": False,
        "automatic_retry": False,
        "model_process_count": 0,
        "provider_calls": 0,
        "heldout_task_ids_loaded": [],
        "active_task_id": None,
        "active_pull_receipt": None,
        "outcomes": outcomes,
        "qualified_bindings": copy.deepcopy(predecessor["qualified_bindings"]),
        "predecessor_image_transfers": copy.deepcopy(predecessor["image_transfers"]),
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
                "OpenHands v27 CA precheck emitted output",
                diagnostic={**ca_receipt, "failure_stage": "ca_bundle_precheck_output"},
            )
        progress["ca_bundle_precheck_passed"] = True
        progress["ca_bundle_control_hash"] = ca_control["control_hash"]
        progress["ca_bundle_command_receipt"] = ca_receipt
        _write_progress(root, progress)

        for number in OPENHANDS_V27_CONTINUATION_NUMBERS:
            state = _qualification_state(progress["outcomes"])
            if state["satisfied"] or state["capacity_impossible"]:
                if state["capacity_impossible"]:
                    progress["status"] = "stopped_insufficient_capacity"
                    progress["stop_reason"] = "fewer_than_five_qualified_tasks"
                break
            candidate = inventory[len(progress["outcomes"])]
            reference = f"ghcr.io/pku-liang/openhwgroup_m_cva6:pr-{number}"
            task_id = str(candidate["task_id"])
            if candidate["number"] != number or task_id != state["next_task_id"]:
                raise ConfigurationError("OpenHands v27 qualification schedule changed")
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
            _qualify_transferred_candidate(
                candidate=candidate,
                reference=reference,
                transfer=transfer,
                dataset=resolved_dataset,
                dataset_revision=v26_approved["dataset"]["revision"],
                source_commit=v26_approved["dataset"]["source_commit"],
                root=root,
                progress=progress,
            )

        state = _qualification_state(progress["outcomes"])
        progress["active_task_id"] = None
        progress["qualified_task_ids"] = state["qualified_task_ids"]
        progress["training_reserve_task_ids"] = state["qualified_task_ids"][:3]
        progress["validation_reserve_task_ids"] = state["qualified_task_ids"][3:5]
        if state["satisfied"]:
            progress["status"] = "qualified_pending_agent_images"
        elif progress["status"] == "running":
            progress["status"] = "stopped_insufficient_capacity"
            progress["stop_reason"] = "fewer_than_five_qualified_tasks"
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
            failure = failure or exc
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
        raise ConfigurationError("OpenHands v27 resumed qualification failed") from failure
    return _sealed(progress)


def _qualify_transferred_candidate(
    *,
    candidate: dict[str, Any],
    reference: str,
    transfer: dict[str, Any],
    dataset: Path,
    dataset_revision: str,
    source_commit: str,
    root: Path,
    progress: dict[str, Any],
) -> None:
    task_id = str(candidate["task_id"])
    source_relative = f"sources/pr-{candidate['number']}"
    smoke_relative = f"smokes/pr-{candidate['number']}"
    source = root / source_relative
    smoke = root / smoke_relative
    binding: dict[str, str] | None = None
    report: dict[str, Any] | None = None
    task_failure: Exception | None = None
    try:
        prepare_source(
            dataset=dataset,
            output=source,
            selected_tasks=[str(candidate["instance_id"])],
            pull=False,
            official_dataset_revision=dataset_revision,
            official_source_commit=source_commit,
            imported_image_bindings={
                reference: {
                    "image_id": transfer["image_id"],
                    "manifest_digest": transfer["manifest_digest"],
                }
            },
        )
        binding = _v19._source_binding(source, expected_task_id=task_id)
        if (
            binding["verifier_image"] != transfer["image_id"]
            or binding["verifier_manifest_digest"] != transfer["manifest_digest"]
        ):
            raise ConfigurationError("OpenHands v27 prepared source transfer binding changed")
        report = run_zero_model_smoke(source=source, output=smoke)
    except Exception as exc:
        task_failure = exc
        report = _v26._load_optional_report(smoke / "smoke-report.json")
    if report is None or not zero_model_infrastructure_valid(report) or binding is None:
        progress["status"] = "stopped_infrastructure_invalid"
        diagnostic = {
            "failure_stage": "zero_model_qualification",
            "failure_type": type(task_failure).__name__ if task_failure else "UnknownError",
        }
        progress["failure_diagnostic"] = diagnostic
        _write_progress(root, progress)
        raise _StageFailure(
            f"OpenHands v27 infrastructure-invalid {task_id}", diagnostic=diagnostic
        ) from task_failure
    outcome = _v19._completed_outcome(candidate=candidate, binding=binding, report=report)
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


def _qualification_state(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    if len(outcomes) > len(OPENHANDS_V19_QUALIFICATION_CANDIDATES):
        raise ConfigurationError("OpenHands v27 has too many outcomes")
    qualified: list[str] = []
    for index, outcome in enumerate(outcomes):
        task_id = str(outcome.get("task_id"))
        if task_id != OPENHANDS_V19_QUALIFICATION_CANDIDATES[index]:
            raise ConfigurationError("OpenHands v27 outcomes are out of order")
        predecessor_failure = index == 2 and outcome.get("status") == "predecessor_transfer_failed"
        if predecessor_failure:
            if outcome.get("predecessor_terminal_evidence") is not True:
                raise ConfigurationError("OpenHands v27 predecessor failure marker changed")
            continue
        if outcome.get("infrastructure_valid") is not True:
            raise ConfigurationError("OpenHands v27 current infrastructure outcome is invalid")
        if outcome.get("base_failed") is True and outcome.get("reference_passed") is True:
            qualified.append(task_id)
    remaining = len(OPENHANDS_V19_QUALIFICATION_CANDIDATES) - len(outcomes)
    return {
        "qualified_task_ids": qualified,
        "satisfied": len(qualified) >= OPENHANDS_V19_QUALIFIED_TASK_TARGET,
        "capacity_impossible": len(qualified) + remaining < OPENHANDS_V19_QUALIFIED_TASK_TARGET,
        "next_task_id": (
            OPENHANDS_V19_QUALIFICATION_CANDIDATES[len(outcomes)]
            if len(outcomes) < len(OPENHANDS_V19_QUALIFICATION_CANDIDATES)
            else None
        ),
    }


def _predecessor_failure_outcome(
    candidate: dict[str, Any], predecessor: dict[str, Any]
) -> dict[str, Any]:
    return {
        "task_id": candidate["task_id"],
        "instance_id": candidate["instance_id"],
        "changed_line_count": candidate["changed_line_count"],
        "modified_file_count": candidate["modified_file_count"],
        "infrastructure_valid": False,
        "verifier_network": "none",
        "verifier_image": None,
        "model_process_count": 0,
        "base_failed": False,
        "reference_passed": False,
        "status": "predecessor_transfer_failed",
        "predecessor_terminal_evidence": True,
        "predecessor_progress_hash": predecessor["progress_hash"],
        "failure_diagnostic_hash": _PREDECESSOR_FAILURE_HASH,
    }


def _transfer_candidate(
    *,
    reference: str,
    image_id: str,
    tool_cache: Path,
    scratch: Path,
    pull_receipt_sink: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    if reference not in OPENHANDS_V27_CONTINUATION_REFERENCES:
        raise ConfigurationError("OpenHands v27 transfer reference is not frozen")
    if _v26._inspect_host_image(reference) is not None:
        raise ConfigurationError("OpenHands v27 candidate appeared before transfer")
    digest_output, digest_control, digest_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V27_NETWORK,
        path="/tools/crane",
        arguments=["digest", reference],
        label_role="candidate-digest",
        timeout=300,
        output_bound=_MAX_DIAGNOSTIC_BYTES,
    )
    try:
        manifest_digest = digest_output.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise ConfigurationError("OpenHands v27 candidate digest is not ASCII") from exc
    if not _SHA256_DIGEST.fullmatch(manifest_digest):
        raise ConfigurationError("OpenHands v27 candidate digest is malformed")
    immutable_reference = f"{reference.rsplit(':', 1)[0]}@{manifest_digest}"
    config_output, config_control, config_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V27_NETWORK,
        path="/tools/crane",
        arguments=["config", immutable_reference],
        label_role="candidate-config",
        timeout=300,
        output_bound=_MAX_CONFIG_BYTES,
    )
    if not config_output:
        raise ConfigurationError("OpenHands v27 candidate config is empty")
    expected_image_id = f"sha256:{hashlib.sha256(config_output).hexdigest()}"
    archive = scratch / "candidate-image.tar"
    if archive.exists() or archive.is_symlink():
        raise ConfigurationError("OpenHands v27 candidate archive path is not empty")
    pull_output, pull_control, pull_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V27_NETWORK,
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
    observation = {
        **pull_receipt,
        "stdout_empty": not pull_output,
        "stderr_bounded": 0 <= int(pull_receipt["stderr_bytes"]) <= _MAX_DIAGNOSTIC_BYTES,
        "raw_output_persisted": False,
    }
    pull_receipt_sink(observation)
    if pull_output or not observation["stderr_bounded"]:
        raise _StageFailure(
            "OpenHands v27 crane pull output policy failed",
            diagnostic={**observation, "failure_stage": "candidate_pull_output_policy"},
        )
    archive_receipt = _v26._validated_crane_tarball(
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
        "stderr_sha256": hashlib.sha256(loaded.stderr).hexdigest(),
        "error_category": _safe_error_category(loaded.stderr) if loaded.returncode else None,
        "raw_output_persisted": False,
    }
    if loaded.returncode != 0 or any(
        value > _MAX_DIAGNOSTIC_BYTES for value in (len(loaded.stdout), len(loaded.stderr))
    ):
        raise _StageFailure(
            "OpenHands v27 Docker image load failed",
            diagnostic={**load_receipt, "failure_stage": "candidate_image_load"},
        )
    sentinel = _v26._inspect_host_image(_sentinel_reference())
    if sentinel is None or sentinel.get("Id") != expected_image_id:
        raise ConfigurationError("OpenHands v27 loaded image identity changed")
    tagged = subprocess.run(
        ["docker", "image", "tag", expected_image_id, reference],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if tagged.returncode != 0 or tagged.stdout or tagged.stderr:
        raise ConfigurationError("OpenHands v27 candidate tag failed")
    imported = _v26._inspect_host_image(reference)
    if imported is None or imported.get("Id") != expected_image_id:
        raise ConfigurationError("OpenHands v27 candidate import identity changed")
    removed = subprocess.run(
        ["docker", "image", "rm", _sentinel_reference()],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if removed.returncode != 0 or _v26._inspect_host_image(_sentinel_reference()) is not None:
        raise ConfigurationError("OpenHands v27 sentinel cleanup failed")
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
        "raw_output_persisted": False,
        "temporary_archive_removed": True,
        "sentinel_tag_removed": True,
    }
    return {**base, "transfer_receipt_hash": content_hash(base)}


def _safe_error_category(stderr: bytes) -> str:
    """Classify bounded diagnostics without returning or persisting diagnostic content."""

    text = stderr.decode("utf-8", errors="replace").lower()
    if any(token in text for token in ("no space left", "out of memory", "too many open files")):
        return "resource_exhaustion"
    if re.search(r"(?:status(?: code)?|response status)[:= ]+4\d\d\b", text):
        return "registry_http_4xx"
    if re.search(r"(?:status(?: code)?|response status)[:= ]+5\d\d\b", text):
        return "registry_http_5xx"
    if any(token in text for token in ("x509", "tls handshake", "certificate verify")):
        return "tls_verification"
    if any(token in text for token in ("no such host", "server misbehaving", "dns lookup")):
        return "dns_resolution"
    if any(token in text for token in ("deadline exceeded", "i/o timeout", "timed out", "timeout")):
        return "transport_timeout"
    if any(
        token in text
        for token in (
            "connection refused",
            "connection reset",
            "network is unreachable",
            "unexpected eof",
            "broken pipe",
            "stream error",
        )
    ):
        return "transport_connection"
    if "cache" in text and any(
        token in text
        for token in ("permission denied", "file exists", "no such file", "read-only", "rename")
    ):
        return "cache_filesystem"
    if any(token in text for token in ("tarball", "tar writer", "writing tar", "multisave")):
        return "archive_writer"
    return "unknown"


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
    container_name = f"verigym-hwe-v27-{label_role}-{os.getpid()}-{secrets.token_hex(4)}"
    command = [
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        container_name,
        "--label",
        f"org.verigym.owner={OPENHANDS_V27_IDENTITY}",
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
        "format_id": "verigym_openhands_hwe_v27_command_receipt_v1",
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
        "error_category": None,
        "raw_output_persisted": False,
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
            diagnostic["error_category"] = _safe_error_category(created.stderr)
            raise ConfigurationError("OpenHands v27 Docker create failed or exceeded its bound")
        container_id = created.stdout.decode("ascii", errors="strict").strip()
        values = _v26._docker_json(["docker", "container", "inspect", container_id])
        if not container_id or len(values) != 1:
            raise ConfigurationError("OpenHands v27 container inspection is malformed")
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
        try:
            started = subprocess.run(
                ["docker", "start", "--attach", container_id],
                check=False,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
            stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
            diagnostic.update(
                {
                    "stdout_bytes": len(stdout),
                    "stderr_bytes": len(stderr),
                    "stderr_present": bool(stderr),
                    "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                    "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                    "error_category": "transport_timeout",
                    "control_hash": control["control_hash"],
                }
            )
            raise ConfigurationError("OpenHands v27 controlled command timed out") from exc
        diagnostic.update(
            {
                "exit_code": started.returncode,
                "stdout_bytes": len(started.stdout),
                "stderr_bytes": len(started.stderr),
                "stderr_present": bool(started.stderr),
                "stdout_sha256": hashlib.sha256(started.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(started.stderr).hexdigest(),
                "error_category": (
                    _safe_error_category(started.stderr) if started.returncode != 0 else None
                ),
                "control_hash": control["control_hash"],
            }
        )
        if (
            started.returncode != 0
            or len(started.stdout) > output_bound
            or len(started.stderr) > _MAX_DIAGNOSTIC_BYTES
        ):
            diagnostic["error_category"] = diagnostic["error_category"] or "unknown"
            raise ConfigurationError(
                "OpenHands v27 controlled command failed or exceeded its bound"
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
        diagnostic["error_category"] = diagnostic["error_category"] or "unknown"
        if diagnostic["error_category"] not in OPENHANDS_V27_ERROR_CATEGORIES:
            diagnostic["error_category"] = "unknown"
        raise _StageFailure(
            "OpenHands v27 controlled container stage failed", diagnostic=diagnostic
        ) from failure
    if result is None:
        raise _StageFailure(
            "OpenHands v27 controlled container returned no result", diagnostic=diagnostic
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
    if not all(
        isinstance(value, dict) for value in (host, config, network_settings)
    ) or not isinstance(mounts, list):
        raise ConfigurationError("OpenHands v27 effective controls are malformed")
    assert isinstance(host, dict)
    assert isinstance(config, dict)
    assert isinstance(network_settings, dict)
    mount_map = {str(item.get("Destination")): item for item in mounts if isinstance(item, dict)}
    environment = _v26._environment_map(config.get("Env"))
    expected_environment = _v26._environment_map(list(_v26._EXECUTION_IMAGE_ENVIRONMENT))
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
        and labels.get("org.verigym.owner") == OPENHANDS_V27_IDENTITY
        and labels.get("org.verigym.role") == label_role
        and network_settings.get("Ports") in (None, {})
    )
    if not valid:
        raise ConfigurationError("OpenHands v27 effective container controls changed")
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


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    observed_hash = value.pop("authorization_hash", None)
    if observed_hash != OPENHANDS_V27_APPROVAL_HASH or content_hash(value) != observed_hash:
        raise ConfigurationError("OpenHands v27 authorization identity changed")
    value["authorization_hash"] = observed_hash
    predecessor = value.get("predecessor")
    controls = value.get("required_controls")
    actions = value.get("authorized_actions")
    false_actions = (
        "invoke_provider",
        "build_agent_images",
        "materialize_canary_contract",
        "start_collection",
        "start_training",
        "load_heldout_tasks",
    )
    if (
        value.get("schema_version") != "1.0"
        or value.get("format_id") != OPENHANDS_V27_APPROVAL_FORMAT
        or value.get("status") != "authorized_pending_qualification"
        or value.get("identity") != OPENHANDS_V27_IDENTITY
        or value.get("network") != OPENHANDS_V27_NETWORK
        or value.get("continuation_candidate_numbers") != list(OPENHANDS_V27_CONTINUATION_NUMBERS)
        or value.get("safe_error_categories") != list(OPENHANDS_V27_ERROR_CATEGORIES)
        or value.get("qualification_target") != 5
        or value.get("training_reserve_count") != 3
        or value.get("validation_reserve_count") != 2
        or value.get("failure_policy") != "stop_immediately_no_retry"
        or value.get("production_training_ready") is not False
        or value.get("benchmark_score_claimed") is not False
        or not isinstance(predecessor, dict)
        or predecessor.get("identity") != _v26.OPENHANDS_V26_IDENTITY
        or predecessor.get("progress_hash") != _PREDECESSOR_PROGRESS_HASH
        or predecessor.get("progress_file_sha256") != _PREDECESSOR_FILE_SHA256
        or predecessor.get("authorization_hash") != _v26.OPENHANDS_V26_APPROVAL_HASH
        or predecessor.get("status") != "stopped_security_or_infrastructure_invalid"
        or predecessor.get("audit_commit") != _PREDECESSOR_AUDIT_COMMIT
        or predecessor.get("failure_diagnostic_hash") != _PREDECESSOR_FAILURE_HASH
        or predecessor.get("imported_qualified_task_ids")
        != list(OPENHANDS_V19_QUALIFICATION_CANDIDATES[:2])
        or predecessor.get("attempted_task_ids") != list(OPENHANDS_V19_QUALIFICATION_CANDIDATES[:3])
        or predecessor.get("failure_task_id") != OPENHANDS_V19_QUALIFICATION_CANDIDATES[2]
        or not isinstance(controls, dict)
        or any(controls.get(key) is not expected for key, expected in _required_controls().items())
        or not isinstance(actions, dict)
        or any(
            actions.get(key) is not True
            for key in (
                "import_sealed_v26_qualified_evidence",
                "continue_unattempted_public_candidates",
                "resolve_candidate_digests",
                "download_candidate_images",
                "load_candidate_images",
                "run_zero_model_qualification",
            )
        )
        or any(actions.get(key) is not False for key in false_actions)
    ):
        raise ConfigurationError("OpenHands v27 authorization scope changed")
    return value


def _required_controls() -> dict[str, bool]:
    return {
        "exact_predecessor_hash": True,
        "historical_attempts_retried": False,
        "historical_qualified_bindings_relabelled": False,
        "raw_command_output_persisted": False,
        "allowlisted_error_category_only": True,
        "automatic_retry": False,
        "privileged": False,
        "docker_socket_mount": False,
        "read_only_rootfs": True,
        "non_root_user": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "default_bridge_used": False,
        "proxy_values_forwarded": False,
        "tls_verification_disabled": False,
        "networkless_verifier": True,
        "digest_qualified_candidate_pull": True,
        "tarball_inventory_validation": True,
        "atomic_progress": True,
        "streamed_capacity_recomputation": True,
    }


def _validated_predecessor(path: Path, binding: dict[str, Any]) -> dict[str, Any]:
    unresolved = path.expanduser()
    if (
        unresolved.is_symlink()
        or not unresolved.is_file()
        or unresolved.stat().st_size > _MAX_CONFIG_BYTES
        or _v26._sha256_file(unresolved) != _PREDECESSOR_FILE_SHA256
    ):
        raise ConfigurationError("OpenHands v27 predecessor file identity changed")
    value = _v26._load_json(unresolved)
    expected_hash = value.pop("progress_hash", None)
    if expected_hash != _PREDECESSOR_PROGRESS_HASH or content_hash(value) != expected_hash:
        raise ConfigurationError("OpenHands v27 predecessor progress identity changed")
    value["progress_hash"] = expected_hash
    return _validated_predecessor_value(value)


def _validated_predecessor_value(value: dict[str, Any]) -> dict[str, Any]:
    outcomes = value.get("outcomes")
    bindings = value.get("qualified_bindings")
    transfers = value.get("image_transfers")
    failure = value.get("failure_diagnostic")
    expected_tasks = list(OPENHANDS_V19_QUALIFICATION_CANDIDATES[:2])
    if (
        value.get("format_id") != _v26.OPENHANDS_V26_PROGRESS_FORMAT
        or value.get("identity") != _v26.OPENHANDS_V26_IDENTITY
        or value.get("authorization_hash") != _v26.OPENHANDS_V26_APPROVAL_HASH
        or value.get("status") != "stopped_security_or_infrastructure_invalid"
        or value.get("progress_hash") != _PREDECESSOR_PROGRESS_HASH
        or value.get("active_task_id") != OPENHANDS_V19_QUALIFICATION_CANDIDATES[2]
        or value.get("active_pull_receipt") is not None
        or value.get("provider_calls") != 0
        or value.get("heldout_task_ids_loaded") != []
        or value.get("model_process_count") != 0
        or value.get("temporary_transfer_scratch_removed") is not True
        or value.get("temporary_containers_removed") is not True
        or not isinstance(outcomes, list)
        or [item.get("task_id") for item in outcomes] != expected_tasks
        or any(
            item.get("status") != "qualified"
            or item.get("infrastructure_valid") is not True
            or item.get("base_failed") is not True
            or item.get("reference_passed") is not True
            for item in outcomes
        )
        or not isinstance(bindings, dict)
        or set(bindings) != set(expected_tasks)
        or not isinstance(transfers, dict)
        or set(transfers) != set(expected_tasks)
        or not isinstance(failure, dict)
        or content_hash(failure) != _PREDECESSOR_FAILURE_HASH
        or failure.get("failure_stage") != "candidate-pull"
        or failure.get("exit_code") != 1
        or failure.get("stdout_bytes") != 0
        or failure.get("temporary_container_removed") is not True
    ):
        raise ConfigurationError("OpenHands v27 predecessor evidence is incomplete")
    for task_id in expected_tasks:
        task_binding = bindings[task_id]
        transfer = transfers[task_id]
        if (
            not isinstance(task_binding, dict)
            or not isinstance(transfer, dict)
            or task_binding.get("verifier_image") != transfer.get("image_id")
            or task_binding.get("verifier_manifest_digest") != transfer.get("manifest_digest")
            or task_binding.get("transfer_receipt_hash") != transfer.get("transfer_receipt_hash")
        ):
            raise ConfigurationError("OpenHands v27 predecessor binding changed")
    return value


def _validate_predecessor_images(predecessor: dict[str, Any]) -> None:
    transfers = predecessor["image_transfers"]
    references = _v26.OPENHANDS_V26_CANDIDATE_REFERENCES
    for index, reference in enumerate(references):
        observed = _v26._inspect_host_image(reference)
        if index < 2:
            task_id = OPENHANDS_V19_QUALIFICATION_CANDIDATES[index]
            if observed is None or observed.get("Id") != transfers[task_id]["image_id"]:
                raise ConfigurationError("OpenHands v27 predecessor image evidence changed")
        elif observed is not None:
            raise ConfigurationError("OpenHands v27 unattempted candidate image is already present")


def _sentinel_reference() -> str:
    # go-containerregistry assigns this fixed placeholder when saving a digest-only Docker tarball.
    return "ghcr.io/pku-liang/openhwgroup_m_cva6:i-was-a-digest"


def _count_host_candidate_images() -> int:
    return sum(
        _v26._inspect_host_image(reference) is not None
        for reference in _v26.OPENHANDS_V26_CANDIDATE_REFERENCES
    )


def _count_temporary_containers() -> int:
    result = subprocess.run(
        ["docker", "container", "ls", "--all", "--quiet", "--filter", "name=verigym-hwe-v27-"],
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
        raise ConfigurationError("OpenHands v27 temporary container cleanup failed")


def _new_scratch_directory() -> Path:
    if OPENHANDS_V27_SCRATCH.exists() or OPENHANDS_V27_SCRATCH.is_symlink():
        raise ConfigurationError("OpenHands v27 transfer scratch must be new")
    OPENHANDS_V27_SCRATCH.mkdir(parents=True)
    return OPENHANDS_V27_SCRATCH.resolve(strict=True)


def _cleanup_scratch(path: Path) -> None:
    resolved_parent = Path("/data/jzhu484/Agent/.verigym-tmp").resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved != OPENHANDS_V27_SCRATCH or not resolved.is_relative_to(resolved_parent):
        raise ConfigurationError("OpenHands v27 scratch cleanup path changed")
    shutil.rmtree(resolved)


def _sealed(progress: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(progress)
    base.pop("progress_hash", None)
    return {**base, "progress_hash": content_hash(base)}


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "qualification-progress.json", _sealed(progress))


def main() -> int:
    arguments = _parser().parse_args()
    progress = qualify_v27_resumed_public_tasks(
        approval_path=arguments.authorization,
        predecessor_path=arguments.predecessor,
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
