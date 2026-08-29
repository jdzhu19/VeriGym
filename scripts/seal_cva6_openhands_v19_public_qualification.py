#!/usr/bin/env python3
"""Seal the sanitized OpenHands v19 reserve split and static canary contract."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_CANARY_VALIDATION_BINDING,
    OPENHANDS_V19_CANARY_VALIDATION_TASK,
    build_v19_canary_contract,
    seal_v19_qualification_receipt,
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
OPENHANDS_V19_AGENT_IMAGE_BUILD_FORMAT = _images.OPENHANDS_V19_AGENT_IMAGE_BUILD_FORMAT
_validated_qualification_progress = _images._validated_qualification_progress

OPENHANDS_V19_QUALIFICATION_SEAL_FORMAT = "verigym_openhands_hwe_v19_public_qualification_seal_v1"
_MAX_JSON_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--agent-image-root", type=Path, required=True)
    parser.add_argument("--validation-image-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def seal_v19_public_qualification(
    *,
    qualification_root: Path,
    agent_image_root: Path,
    validation_image_lock: Path,
    output: Path,
) -> dict[str, Any]:
    """Bind the five new reserves and historical PR-3204 validation image exactly."""

    expanded_qualification = qualification_root.expanduser()
    expanded_image_root = agent_image_root.expanduser()
    if expanded_qualification.is_symlink() or not expanded_qualification.is_dir():
        raise ConfigurationError("OpenHands v19 qualification root is unsafe")
    if expanded_image_root.is_symlink() or not expanded_image_root.is_dir():
        raise ConfigurationError("OpenHands v19 agent image root is unsafe")
    qualification = expanded_qualification.resolve(strict=True)
    image_root = expanded_image_root.resolve(strict=True)
    qualification_progress = _validated_qualification_progress(
        _load_json(qualification / "qualification-progress.json")
    )
    task_ids = [
        *qualification_progress["training_reserve_task_ids"],
        *qualification_progress["validation_reserve_task_ids"],
    ]
    image_progress = _validated_image_progress(
        _load_json(image_root / "agent-image-progress.json"),
        qualification_progress_hash=qualification_progress["progress_hash"],
        expected_task_ids=task_ids,
    )
    locks: dict[str, HweAgentImageLock] = {}
    for task_id in task_ids:
        item = image_progress["locks"].get(task_id)
        if not isinstance(item, dict) or not isinstance(item.get("lock"), str):
            raise ConfigurationError("OpenHands v19 agent image progress lacks a lock")
        unresolved_lock_path = image_root / item["lock"]
        if unresolved_lock_path.is_symlink():
            raise ConfigurationError("OpenHands v19 agent image lock is a symlink")
        lock_path = unresolved_lock_path.resolve(strict=True)
        if not lock_path.is_relative_to(image_root):
            raise ConfigurationError("OpenHands v19 agent image lock escaped its root")
        lock = HweAgentImageLock.model_validate(_load_json(lock_path))
        expected = qualification_progress["qualified_bindings"][task_id]
        if (
            lock.format_id != "verigym_hwe_agent_image_lock_v2"
            or lock.task_id != task_id
            or lock.task_hash != expected["task_hash"]
            or lock.source_hash != expected["source_hash"]
            or lock.verifier_base_image_id != expected["verifier_image"]
            or lock.lock_hash != item.get("lock_hash")
            or lock.derived_agent_image_id != item.get("agent_image")
            or not lock.security_scan_passed
        ):
            raise ConfigurationError("OpenHands v19 agent image binding changed before sealing")
        locks[task_id] = lock
    if len({lock.derived_agent_image_id for lock in locks.values()}) != len(locks):
        raise ConfigurationError("OpenHands v19 reserve tasks reused an agent image")

    validation_lock = HweAgentImageLock.model_validate(_load_json(validation_image_lock))
    validation_binding = _binding(validation_lock)
    if (
        validation_lock.task_id != OPENHANDS_V19_CANARY_VALIDATION_TASK
        or validation_binding != OPENHANDS_V19_CANARY_VALIDATION_BINDING
        or not validation_lock.security_scan_passed
    ):
        raise ConfigurationError("OpenHands v19 historical PR-3204 binding changed")

    bindings = {task_id: _binding(lock) for task_id, lock in locks.items()}
    receipt = seal_v19_qualification_receipt(
        qualification_progress["outcomes"],
        bindings=bindings,
    )
    contract = build_v19_canary_contract(
        receipt,
        validation_binding=validation_binding,
    )
    root = _new_directory(output)
    receipt_path = root / "qualification-receipt.json"
    contract_path = root / "canary-contract.json"
    atomic_dump_json(receipt_path, receipt)
    atomic_dump_json(contract_path, contract)
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V19_QUALIFICATION_SEAL_FORMAT,
        "status": "completed",
        "qualification_progress_hash": qualification_progress["progress_hash"],
        "agent_image_progress_hash": image_progress["progress_hash"],
        "qualification_receipt_hash": receipt["receipt_hash"],
        "qualification_receipt_sha256": hash_bytes(receipt_path.read_bytes()),
        "canary_contract_hash": contract["contract_hash"],
        "canary_contract_sha256": hash_bytes(contract_path.read_bytes()),
        "training_reserve_task_ids": receipt["training_reserve_task_ids"],
        "validation_reserve_task_ids": receipt["validation_reserve_task_ids"],
        "heldout_task_ids_loaded": [],
        "model_process_count": 0,
        "verifier_network": "none",
        "provider_calls": 0,
        "sft_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    report = {**base, "seal_hash": content_hash(base)}
    atomic_dump_json(root / "qualification-seal.json", report)
    return report


def _binding(lock: HweAgentImageLock) -> dict[str, str]:
    return {
        "task_hash": lock.task_hash,
        "source_hash": lock.source_hash,
        "image_lock_hash": lock.lock_hash,
        "agent_image": lock.derived_agent_image_id,
        "verifier_image": lock.verifier_base_image_id,
    }


def _validated_image_progress(
    value: dict[str, Any],
    *,
    qualification_progress_hash: str,
    expected_task_ids: list[str],
) -> dict[str, Any]:
    expected_hash = value.pop("progress_hash", None)
    if not isinstance(expected_hash, str) or content_hash(value) != expected_hash:
        raise ConfigurationError("OpenHands v19 agent image progress identity changed")
    value["progress_hash"] = expected_hash
    locks = value.get("locks")
    task_ids = value.get("task_ids")
    if (
        value.get("format_id") != OPENHANDS_V19_AGENT_IMAGE_BUILD_FORMAT
        or value.get("status") != "completed"
        or value.get("qualification_progress_hash") != qualification_progress_hash
        or value.get("build_network") != "none"
        or value.get("runtime_network") != "none"
        or value.get("active_task_id") is not None
        or not isinstance(task_ids, list)
        or task_ids != expected_task_ids
        or not isinstance(locks, dict)
        or set(locks) != set(task_ids)
    ):
        raise ConfigurationError("OpenHands v19 agent image progress is incomplete")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError(f"unsafe OpenHands v19 JSON input: {expanded.name}")
    resolved = expanded.resolve(strict=True)
    if resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError(f"unsafe OpenHands v19 JSON input: {resolved.name}")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v19 JSON input: {resolved.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v19 JSON input is not an object: {resolved.name}")
    return value


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("OpenHands v19 qualification seal output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def main() -> int:
    arguments = _parser().parse_args()
    report = seal_v19_public_qualification(
        qualification_root=arguments.qualification_root,
        agent_image_root=arguments.agent_image_root,
        validation_image_lock=arguments.validation_image_lock,
        output=arguments.output,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
