#!/usr/bin/env python3
"""Build five reserve images and seal the v19 canary contract without provider calls."""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V19_CANARY_CAMPAIGN_ID,
    OPENHANDS_V19_CANARY_SAMPLE_INDEX,
    OPENHANDS_V19_CANARY_SEED,
    OPENHANDS_V19_CANARY_VALIDATION_BINDING,
    OPENHANDS_V19_CANARY_VALIDATION_TASK,
    OPENHANDS_V19_QUALIFICATION_CANDIDATES,
    OPENHANDS_V19_QUALIFICATION_FORMAT,
    build_v19_canary_contract,
    validate_v19_qualification_receipt,
)

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweAgentImageLock

_images = importlib.import_module(
    "scripts.build_and_lock_cva6_openhands_v19_agent_images"
    if __package__
    else "build_and_lock_cva6_openhands_v19_agent_images"
)
_v28 = importlib.import_module(
    "scripts.qualify_cva6_openhands_v28_reference_patch_preflight_resume"
    if __package__
    else "qualify_cva6_openhands_v28_reference_patch_preflight_resume"
)

OPENHANDS_V29_OPT_IN_ENV = "VERIGYM_MATERIALIZE_OPENHANDS_HWE_V29_V19_CANARY"
OPENHANDS_V29_APPROVAL_FORMAT = (
    "verigym_openhands_hwe_v29_v19_canary_materialization_authorization_v1"
)
OPENHANDS_V29_PROGRESS_FORMAT = "verigym_openhands_hwe_v29_v19_canary_materialization_progress_v1"
OPENHANDS_V29_SOURCE_CATALOG_FORMAT = "verigym_openhands_hwe_v29_v19_canary_source_catalog_v1"
OPENHANDS_V29_IDENTITY = "openhands-hwe-v29-v19-canary-materialization-v1"
OPENHANDS_V29_APPROVAL_HASH = "7bc664e303c44cb7bc522c3c3963b4ea0ce2e9fe09b9318dbde19317265ea63a"
OPENHANDS_V29_QUALIFICATION_PROGRESS_HASH = (
    "c631e93fd7c002dc47aff45894d24701baabbad599da405b57d5516f8d6ce119"
)
OPENHANDS_V29_QUALIFICATION_FILE_SHA256 = (
    "f44e11ae449d9c6836c3a86b112492a65b03446039a5d8a38c2b9403231abc70"
)
OPENHANDS_V29_IDENTITY_TEMPLATE_SHA256 = (
    "e20a122839686607f5a39c1cc422872bd6339bbb59afb5b8c6dc6c00fb546a41"
)
OPENHANDS_V29_VALIDATION_LOCK_SHA256 = (
    "55ff6b4efb9675a0a6d512b32d0b33d7778d93d81159086c7485b9f3ebe92a6b"
)
OPENHANDS_V29_QUALIFICATION_AUDIT_MERGE = "93881a75d272ce9fcf5dffbe7b7e495b09d6b60a"

_TRAINING_RESERVES = tuple(OPENHANDS_V19_QUALIFICATION_CANDIDATES[index] for index in (0, 1, 3))
_VALIDATION_RESERVES = tuple(OPENHANDS_V19_QUALIFICATION_CANDIDATES[index] for index in (4, 6))
_QUALIFIED_TASKS = (*_TRAINING_RESERVES, *_VALIDATION_RESERVES)
_SOURCE_ORIGINS = {
    _QUALIFIED_TASKS[0]: "v26",
    _QUALIFIED_TASKS[1]: "v26",
    _QUALIFIED_TASKS[2]: "v27",
    _QUALIFIED_TASKS[3]: "v27",
    _QUALIFIED_TASKS[4]: "v28",
}
_MAX_JSON_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--v26-root", type=Path, required=True)
    parser.add_argument("--v27-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--identity-template", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--validation-image-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def materialize_v29_v19_canary(arguments: argparse.Namespace) -> dict[str, Any]:
    """Perform the authorized offline image build and static contract materialization."""

    if os.environ.get(OPENHANDS_V29_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V29_OPT_IN_ENV}=1 is required")
    approval_path = _safe_file(arguments.authorization)
    approved = _validated_authorization(_load_json(approval_path))
    source_commit = _merged_source_commit()
    qualification_root = _safe_directory(arguments.qualification_root, "qualification")
    progress_path = _safe_child(qualification_root, "qualification-progress.json")
    if (
        hash_bytes(progress_path.read_bytes())
        != approved["qualification_evidence"]["progress_file_sha256"]
    ):
        raise ConfigurationError("OpenHands v29 qualification progress file changed")
    qualification = _validated_qualification_progress(_load_json(progress_path), approved=approved)
    source_catalog = _validated_source_catalog(
        qualification,
        roots={
            "v26": _safe_directory(arguments.v26_root, "v26 source"),
            "v27": _safe_directory(arguments.v27_root, "v27 source"),
            "v28": qualification_root,
        },
    )
    template_path = _safe_file(arguments.identity_template)
    if (
        hash_bytes(template_path.read_bytes())
        != approved["image_inputs"]["identity_template_sha256"]
    ):
        raise ConfigurationError("OpenHands v29 image identity template changed")
    template = _images._validated_template(
        HweAgentImageLock.model_validate(_load_json(template_path))
    )
    codex_binary = _safe_executable(arguments.codex_binary)
    if hash_bytes(codex_binary.read_bytes()) != approved["image_inputs"]["codex_binary_sha256"]:
        raise ConfigurationError("OpenHands v29 Codex binary changed")
    validation_lock_path = _safe_file(arguments.validation_image_lock)
    if (
        hash_bytes(validation_lock_path.read_bytes())
        != approved["historical_validation"]["image_lock_file_sha256"]
    ):
        raise ConfigurationError("OpenHands v29 historical validation lock file changed")
    validation_lock = HweAgentImageLock.model_validate(_load_json(validation_lock_path))
    if (
        _binding(validation_lock) != OPENHANDS_V19_CANARY_VALIDATION_BINDING
        or not validation_lock.security_scan_passed
    ):
        raise ConfigurationError("OpenHands v29 historical PR-3204 binding changed")

    root = _new_directory(arguments.output)
    for name in ("image-receipts", "legacy-identities", "security-scans", "image-locks"):
        (root / name).mkdir(mode=0o700)
    atomic_dump_json(root / "source-catalog.json", source_catalog)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V29_PROGRESS_FORMAT,
        "identity": OPENHANDS_V29_IDENTITY,
        "status": "materialization_running",
        "authorization_hash": approved["authorization_hash"],
        "source_commit": source_commit,
        "qualification_progress_hash": qualification["progress_hash"],
        "qualification_progress_file_sha256": hash_bytes(progress_path.read_bytes()),
        "source_catalog_hash": source_catalog["catalog_hash"],
        "task_ids": list(_QUALIFIED_TASKS),
        "training_reserve_task_ids": list(_TRAINING_RESERVES),
        "validation_reserve_task_ids": list(_VALIDATION_RESERVES),
        "build_network": "none",
        "runtime_network": "none",
        "active_task_id": None,
        "locks": {},
        "provider_calls": 0,
        "model_process_count": 0,
        "heldout_task_ids_loaded": [],
        "canary_executed": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    _write_progress(root, progress)
    for task_id in _QUALIFIED_TASKS:
        progress["active_task_id"] = task_id
        _write_progress(root, progress)
        try:
            lock = _build_one(
                root=root,
                repository=Path(__file__).resolve().parents[1],
                task_id=task_id,
                binding=qualification["qualified_bindings"][task_id],
                template=template,
                codex_binary=codex_binary,
                tag_namespace=approved["image_inputs"]["tag_namespace"],
            )
        except (Exception, KeyboardInterrupt) as exc:
            progress.update(
                {
                    "status": "stopped_security_or_infrastructure_invalid",
                    "active_task_id": None,
                    "failure_task_id": task_id,
                    "failure_type": type(exc).__name__,
                }
            )
            _write_progress(root, progress)
            raise ConfigurationError(
                f"OpenHands v29 image materialization stopped on {task_id}"
            ) from exc
        suffix = task_id.rsplit("-", 1)[-1]
        progress["locks"][task_id] = {
            "lock": f"image-locks/pr-{suffix}.json",
            "lock_hash": lock.lock_hash,
            "agent_image": lock.derived_agent_image_id,
            "verifier_image": lock.verifier_base_image_id,
            "security_scan_id": lock.security_scan_id,
        }
        progress["active_task_id"] = None
        _write_progress(root, progress)

    agent_images = [item["agent_image"] for item in progress["locks"].values()]
    if len(set(agent_images)) != len(_QUALIFIED_TASKS):
        progress["status"] = "stopped_security_invalid"
        _write_progress(root, progress)
        raise ConfigurationError("OpenHands v29 reserve tasks reused an agent image")
    locks = {
        task_id: HweAgentImageLock.model_validate(
            _load_json(root / str(progress["locks"][task_id]["lock"]))
        )
        for task_id in _QUALIFIED_TASKS
    }
    receipt = _qualification_receipt(qualification, locks=locks)
    contract = build_v19_canary_contract(
        receipt,
        validation_binding=_binding(validation_lock),
    )
    atomic_dump_json(root / "qualification-receipt.json", receipt)
    atomic_dump_json(root / "canary-contract.json", contract)
    progress.update(
        {
            "status": "completed_canary_contract_materialized",
            "qualification_receipt_hash": receipt["receipt_hash"],
            "canary_contract_hash": contract["contract_hash"],
        }
    )
    _write_progress(root, progress)
    return _sealed(progress)


def _build_one(
    *,
    root: Path,
    repository: Path,
    task_id: str,
    binding: dict[str, Any],
    template: HweAgentImageLock,
    codex_binary: Path,
    tag_namespace: str,
) -> HweAgentImageLock:
    suffix = task_id.rsplit("-", 1)[-1]
    receipt_path = root / "image-receipts" / f"pr-{suffix}.json"
    identity_path = root / "legacy-identities" / f"pr-{suffix}.json"
    scan_path = root / "security-scans" / f"pr-{suffix}.json"
    lock_path = root / "image-locks" / f"pr-{suffix}.json"
    image_tag = f"{tag_namespace}-pr-{suffix}:0.147.0-sanitized-v1"
    subprocess.run(
        [
            str(repository / "scripts/build_cva6_hwe_agent_image.sh"),
            str(codex_binary),
            str(binding["verifier_image"]),
            task_id,
            image_tag,
            str(receipt_path),
        ],
        cwd=repository,
        check=True,
        timeout=1_800,
    )
    receipt = _load_json(receipt_path)
    identity = _images._legacy_identity(
        template=template,
        binding={**binding, "task_id": task_id},
        receipt=receipt,
    )
    atomic_dump_json(identity_path, identity.model_dump(mode="json"))
    subprocess.run(
        [
            sys.executable,
            str(repository / "scripts/scan_and_lock_cva6_hwe_agent_image.py"),
            "--receipt",
            str(receipt_path),
            "--legacy-identity-lock",
            str(identity_path),
            "--security-scan-output",
            str(scan_path),
            "--lock-output",
            str(lock_path),
        ],
        cwd=repository,
        check=True,
        timeout=600,
    )
    lock = HweAgentImageLock.model_validate(_load_json(lock_path))
    _images._validate_final_lock(lock, task_id=task_id, binding=binding)
    return lock


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    observed = value.pop("authorization_hash", None)
    if observed != OPENHANDS_V29_APPROVAL_HASH or content_hash(value) != observed:
        raise ConfigurationError("OpenHands v29 authorization identity changed")
    value["authorization_hash"] = observed
    evidence = value.get("qualification_evidence")
    image_inputs = value.get("image_inputs")
    historical = value.get("historical_validation")
    canary = value.get("canary_contract")
    controls = value.get("required_controls")
    actions = value.get("authorized_actions")
    if (
        value.get("schema_version") != "1.0"
        or value.get("format_id") != OPENHANDS_V29_APPROVAL_FORMAT
        or value.get("status") != "authorized_pending_materialization"
        or value.get("identity") != OPENHANDS_V29_IDENTITY
        or value.get("failure_policy") != "stop_immediately_no_retry"
        or value.get("production_training_ready") is not False
        or value.get("benchmark_score_claimed") is not False
        or not all(
            isinstance(item, dict)
            for item in (evidence, image_inputs, historical, canary, controls, actions)
        )
    ):
        raise ConfigurationError("OpenHands v29 authorization is malformed")
    assert isinstance(evidence, dict)
    assert isinstance(image_inputs, dict)
    assert isinstance(historical, dict)
    assert isinstance(canary, dict)
    assert isinstance(controls, dict)
    assert isinstance(actions, dict)
    if (
        evidence.get("identity") != _v28.OPENHANDS_V28_IDENTITY
        or evidence.get("format_id") != _v28.OPENHANDS_V28_PROGRESS_FORMAT
        or evidence.get("status") != "qualified_pending_agent_images"
        or evidence.get("progress_hash") != OPENHANDS_V29_QUALIFICATION_PROGRESS_HASH
        or evidence.get("progress_file_sha256") != OPENHANDS_V29_QUALIFICATION_FILE_SHA256
        or evidence.get("authorization_hash") != _v28.OPENHANDS_V28_APPROVAL_HASH
        or evidence.get("audit_merge_commit") != OPENHANDS_V29_QUALIFICATION_AUDIT_MERGE
        or evidence.get("qualified_task_ids") != list(_QUALIFIED_TASKS)
        or evidence.get("training_reserve_task_ids") != list(_TRAINING_RESERVES)
        or evidence.get("validation_reserve_task_ids") != list(_VALIDATION_RESERVES)
        or image_inputs.get("identity_template_sha256") != OPENHANDS_V29_IDENTITY_TEMPLATE_SHA256
        or image_inputs.get("codex_binary_sha256") != _images._EXPECTED_AGENT_CODEX_SHA256
        or image_inputs.get("agent_rg_sha256") != _images._EXPECTED_AGENT_RG_SHA256
        or image_inputs.get("image_count") != 5
        or image_inputs.get("build_network") != "none"
        or image_inputs.get("runtime_network") != "none"
        or image_inputs.get("tag_namespace") != "verigym/cva6-openhands-v19-v29"
        or historical.get("task_id") != OPENHANDS_V19_CANARY_VALIDATION_TASK
        or historical.get("image_lock_file_sha256") != OPENHANDS_V29_VALIDATION_LOCK_SHA256
        or historical.get("image_lock_hash")
        != OPENHANDS_V19_CANARY_VALIDATION_BINDING["image_lock_hash"]
        or historical.get("agent_image") != OPENHANDS_V19_CANARY_VALIDATION_BINDING["agent_image"]
        or historical.get("verifier_image")
        != OPENHANDS_V19_CANARY_VALIDATION_BINDING["verifier_image"]
        or canary.get("campaign_id") != OPENHANDS_V19_CANARY_CAMPAIGN_ID
        or canary.get("agent_version_id") != OPENHANDS_V19_CANARY_AGENT_VERSION_ID
        or canary.get("training_task_id") != _TRAINING_RESERVES[0]
        or canary.get("validation_task_id") != OPENHANDS_V19_CANARY_VALIDATION_TASK
        or canary.get("seed") != OPENHANDS_V19_CANARY_SEED
        or canary.get("sample_index") != OPENHANDS_V19_CANARY_SAMPLE_INDEX
        or canary.get("provider_calls_during_materialization") != 0
        or controls
        != {
            "clean_merged_source_commit": True,
            "exact_qualification_file": True,
            "historical_attempts_retried": False,
            "historical_evidence_relabelled": False,
            "one_distinct_agent_image_per_reserve": True,
            "task_source_verifier_binding_exact": True,
            "build_network_none": True,
            "runtime_network_none": True,
            "image_security_scan_required": True,
            "atomic_progress": True,
            "provider_credentials_required": False,
            "heldout_tasks_loaded": False,
        }
        or actions
        != {
            "consume_sealed_v28_qualification": True,
            "build_reserve_agent_images": True,
            "scan_reserve_agent_images": True,
            "materialize_v19_qualification_receipt": True,
            "materialize_v19_canary_contract": True,
            "invoke_provider": False,
            "execute_canary": False,
            "start_collection": False,
            "start_training": False,
            "load_heldout_tasks": False,
        }
    ):
        raise ConfigurationError("OpenHands v29 authorization policy changed")
    return value


def _validated_qualification_progress(
    value: dict[str, Any], *, approved: dict[str, Any]
) -> dict[str, Any]:
    observed = value.pop("progress_hash", None)
    if not isinstance(observed, str) or content_hash(value) != observed:
        raise ConfigurationError("OpenHands v29 qualification progress identity changed")
    value["progress_hash"] = observed
    evidence = approved["qualification_evidence"]
    outcomes = value.get("outcomes")
    bindings = value.get("qualified_bindings")
    if not isinstance(outcomes, list) or not isinstance(bindings, dict):
        raise ConfigurationError("OpenHands v29 qualification evidence is incomplete")
    state = _v28._qualification_state(outcomes)
    if (
        observed != evidence["progress_hash"]
        or value.get("format_id") != evidence["format_id"]
        or value.get("identity") != evidence["identity"]
        or value.get("authorization_hash") != evidence["authorization_hash"]
        or value.get("status") != evidence["status"]
        or value.get("candidate_order") != list(OPENHANDS_V19_QUALIFICATION_CANDIDATES)
        or value.get("qualified_task_ids") != list(_QUALIFIED_TASKS)
        or value.get("training_reserve_task_ids") != list(_TRAINING_RESERVES)
        or value.get("validation_reserve_task_ids") != list(_VALIDATION_RESERVES)
        or state.get("qualified_task_ids") != list(_QUALIFIED_TASKS)
        or state.get("satisfied") is not True
        or set(bindings) != set(_QUALIFIED_TASKS)
        or value.get("historical_attempts_retried") is not False
        or value.get("model_process_count") != 0
        or value.get("provider_calls") != 0
        or value.get("heldout_task_ids_loaded") != []
        or value.get("verifier_network") != "none"
        or value.get("implicit_image_pulls_allowed") is not False
        or value.get("raw_command_output_persisted") is not False
        or value.get("temporary_containers_removed") is not True
        or value.get("temporary_transfer_scratch_removed") is not True
        or value.get("privileged_container_used") is not False
        or value.get("docker_socket_mounted") is not False
        or value.get("tcp_api_listener_present") is not False
    ):
        raise ConfigurationError("OpenHands v29 qualification evidence changed")
    for task_id, binding in bindings.items():
        suffix = task_id.rsplit("-", 1)[-1]
        if (
            not isinstance(binding, dict)
            or binding.get("source") != f"sources/pr-{suffix}"
            or binding.get("smoke") != f"smokes/pr-{suffix}"
            or not _hash(binding.get("task_hash"))
            or not _hash(binding.get("source_hash"))
            or not _hash(binding.get("source_image_lock_sha256"))
            or not _digest(binding.get("verifier_image"))
            or not _digest(binding.get("verifier_manifest_digest"))
        ):
            raise ConfigurationError("OpenHands v29 qualified binding is malformed")
    return value


def _validated_source_catalog(
    qualification: dict[str, Any], *, roots: dict[str, Path]
) -> dict[str, Any]:
    tasks: dict[str, dict[str, str]] = {}
    for task_id in _QUALIFIED_TASKS:
        binding = qualification["qualified_bindings"][task_id]
        origin = _SOURCE_ORIGINS[task_id]
        source = _safe_child(roots[origin], str(binding["source"]))
        if not source.is_dir() or source.is_symlink():
            raise ConfigurationError("OpenHands v29 qualified source is unsafe or missing")
        lock_path = _safe_child(source, "image-lock.json")
        if hash_bytes(lock_path.read_bytes()) != binding["source_image_lock_sha256"]:
            raise ConfigurationError("OpenHands v29 qualified source lock changed")
        source_lock = _load_json(lock_path)
        entries = source_lock.get("entries")
        entry = entries[0] if isinstance(entries, list) and len(entries) == 1 else None
        if (
            source_lock.get("format_id") != "verigym_hwe_bench_source_v2"
            or not isinstance(entry, dict)
            or entry.get("repository_hash") != binding["source_hash"]
            or entry.get("image_id") != binding["verifier_image"]
            or entry.get("manifest_digest") != binding["verifier_manifest_digest"]
        ):
            raise ConfigurationError("OpenHands v29 qualified source binding changed")
        tasks[task_id] = {
            "origin": origin,
            "source": str(binding["source"]),
            "source_image_lock_sha256": str(binding["source_image_lock_sha256"]),
        }
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V29_SOURCE_CATALOG_FORMAT,
        "qualification_progress_hash": qualification["progress_hash"],
        "tasks": tasks,
    }
    return {**base, "catalog_hash": content_hash(base)}


def _qualification_receipt(
    qualification: dict[str, Any], *, locks: dict[str, HweAgentImageLock]
) -> dict[str, Any]:
    outcomes = {
        str(item.get("task_id")): item
        for item in qualification["outcomes"]
        if isinstance(item, dict)
    }
    tasks: list[dict[str, Any]] = []
    for index, task_id in enumerate(_QUALIFIED_TASKS):
        outcome = outcomes.get(task_id)
        lock = locks.get(task_id)
        if (
            not isinstance(outcome, dict)
            or lock is None
            or outcome.get("infrastructure_valid") is not True
            or outcome.get("verifier_network") != "none"
            or outcome.get("verifier_image") != lock.verifier_base_image_id
            or outcome.get("model_process_count") != 0
            or outcome.get("base_failed") is not True
            or outcome.get("reference_passed") is not True
            or lock.task_id != task_id
            or not lock.security_scan_passed
        ):
            raise ConfigurationError("OpenHands v29 cannot seal an unqualified reserve")
        safe_outcome = {
            "task_id": task_id,
            "infrastructure_valid": True,
            "verifier_network": "none",
            "verifier_image": lock.verifier_base_image_id,
            "model_process_count": 0,
            "base_failed": True,
            "reference_passed": True,
        }
        tasks.append(
            {
                "task_id": task_id,
                "role": "training_reserve" if index < 3 else "validation_reserve",
                **_binding(lock),
                "qualification_outcome_hash": content_hash(safe_outcome),
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V19_QUALIFICATION_FORMAT,
        "candidate_order": list(OPENHANDS_V19_QUALIFICATION_CANDIDATES),
        "qualified_task_count": 5,
        "tasks": tasks,
        "training_reserve_task_ids": list(_TRAINING_RESERVES),
        "validation_reserve_task_ids": list(_VALIDATION_RESERVES),
        "heldout_task_ids_loaded": [],
        "model_process_count": 0,
        "verifier_network": "none",
    }
    try:
        return validate_v19_qualification_receipt({**base, "receipt_hash": content_hash(base)})
    except ValueError as exc:
        raise ConfigurationError("OpenHands v29 v19 qualification receipt is invalid") from exc


def _binding(lock: HweAgentImageLock) -> dict[str, str]:
    return {
        "task_hash": lock.task_hash,
        "source_hash": lock.source_hash,
        "image_lock_hash": lock.lock_hash,
        "agent_image": lock.derived_agent_image_id,
        "verifier_image": lock.verifier_base_image_id,
    }


def _merged_source_commit() -> str:
    repository = Path(__file__).resolve().parents[1]
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise ConfigurationError("OpenHands v29 materialization requires clean tracked files")
    head = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    upstream = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "origin/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if len(head) != 40 or head != upstream:
        raise ConfigurationError("OpenHands v29 materialization requires merged origin/main")
    return head


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_dir():
        raise ConfigurationError(f"OpenHands v29 {label} root is unsafe")
    return expanded.resolve(strict=True)


def _safe_file(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError(f"unsafe OpenHands v29 input: {expanded.name}")
    resolved = expanded.resolve(strict=True)
    if resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError(f"oversized OpenHands v29 input: {resolved.name}")
    return resolved


def _safe_executable(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file() or not os.access(expanded, os.X_OK):
        raise ConfigurationError("OpenHands v29 Codex binary is unsafe")
    return expanded.resolve(strict=True)


def _safe_child(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ConfigurationError("OpenHands v29 input path is not relative")
    candidate = root
    for part in relative_path.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ConfigurationError("OpenHands v29 input path contains a symlink")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ConfigurationError("OpenHands v29 input escaped its root")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    resolved = _safe_file(path)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v29 JSON input: {resolved.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v29 JSON input is not an object: {resolved.name}")
    return value


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("OpenHands v29 output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _hash(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _digest(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and _hash(value[7:])


def _sealed(progress: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(progress)
    base.pop("progress_hash", None)
    return {**base, "progress_hash": content_hash(base)}


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "materialization-progress.json", _sealed(progress))


def main() -> int:
    progress = materialize_v29_v19_canary(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": progress["status"],
                "image_count": len(progress["locks"]),
                "provider_calls": progress["provider_calls"],
                "canary_contract_hash": progress["canary_contract_hash"],
                "progress_hash": progress["progress_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
