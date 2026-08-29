#!/usr/bin/env python3
"""Build and security-lock the five qualified OpenHands v19 CVA6 agent images."""

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
    OPENHANDS_V19_QUALIFICATION_CANDIDATES,
    OPENHANDS_V19_QUALIFIED_TASK_TARGET,
    evaluate_v19_qualification_gate,
)

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweAgentImageLock

_qualification = importlib.import_module(
    "scripts.qualify_cva6_openhands_v19_public_tasks"
    if __package__
    else "qualify_cva6_openhands_v19_public_tasks"
)
OPENHANDS_V19_PUBLIC_QUALIFICATION_FORMAT = _qualification.OPENHANDS_V19_PUBLIC_QUALIFICATION_FORMAT

OPENHANDS_V19_AGENT_IMAGE_BUILD_OPT_IN_ENV = "VERIGYM_BUILD_OPENHANDS_HWE_V19_AGENT_IMAGES"
OPENHANDS_V19_AGENT_IMAGE_BUILD_FORMAT = "verigym_openhands_hwe_v19_agent_image_build_progress_v1"
_EXPECTED_AGENT_CODEX_SHA256 = "cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40"
_EXPECTED_AGENT_RG_SHA256 = "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849"
_MAX_JSON_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--identity-template", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def build_and_lock_v19_agent_images(
    *,
    qualification_root: Path,
    identity_template: Path,
    codex_binary: Path,
    output: Path,
) -> dict[str, Any]:
    """Derive one independently scanned, network-none agent image per reserve task."""

    if os.environ.get(OPENHANDS_V19_AGENT_IMAGE_BUILD_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V19_AGENT_IMAGE_BUILD_OPT_IN_ENV}=1 is required")
    repository = Path(__file__).resolve().parents[1]
    expanded_qualification = qualification_root.expanduser()
    if expanded_qualification.is_symlink() or not expanded_qualification.is_dir():
        raise ConfigurationError("OpenHands v19 qualification root is unsafe")
    qualification = expanded_qualification.resolve(strict=True)
    qualification_progress = _validated_qualification_progress(
        _load_json(qualification / "qualification-progress.json")
    )
    template = _validated_template(HweAgentImageLock.model_validate(_load_json(identity_template)))
    expanded_codex = codex_binary.expanduser()
    if (
        expanded_codex.is_symlink()
        or not expanded_codex.is_file()
        or not os.access(expanded_codex, os.X_OK)
    ):
        raise ConfigurationError("OpenHands v19 agent Codex binary is unsafe")
    native_codex = expanded_codex.resolve(strict=True)
    root = _new_directory(output)
    receipts = root / "image-receipts"
    identities = root / "legacy-identities"
    scans = root / "security-scans"
    locks = root / "image-locks"
    for path in (receipts, identities, scans, locks):
        path.mkdir(mode=0o700)

    task_ids = [
        *qualification_progress["training_reserve_task_ids"],
        *qualification_progress["validation_reserve_task_ids"],
    ]
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V19_AGENT_IMAGE_BUILD_FORMAT,
        "status": "running",
        "qualification_progress_hash": qualification_progress["progress_hash"],
        "task_ids": task_ids,
        "build_network": "none",
        "runtime_network": "none",
        "active_task_id": None,
        "locks": {},
    }
    _write_progress(root, progress)

    for task_id in task_ids:
        suffix = task_id.rsplit("-", 1)[-1]
        raw_binding = qualification_progress["qualified_bindings"].get(task_id)
        if not isinstance(raw_binding, dict):
            raise ConfigurationError("OpenHands v19 qualified task binding is missing")
        binding = {**raw_binding, "task_id": task_id}
        receipt_path = receipts / f"pr-{suffix}.json"
        identity_path = identities / f"pr-{suffix}.json"
        scan_path = scans / f"pr-{suffix}.json"
        lock_path = locks / f"pr-{suffix}.json"
        image_tag = f"verigym/cva6-openhands-v19-pr-{suffix}:0.147.0-v2-sanitized-v1"
        progress["active_task_id"] = task_id
        _write_progress(root, progress)
        try:
            subprocess.run(
                [
                    str(repository / "scripts/build_cva6_hwe_agent_image.sh"),
                    str(native_codex),
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
            identity = _legacy_identity(template=template, binding=binding, receipt=receipt)
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
            _validate_final_lock(lock, task_id=task_id, binding=binding)
        except Exception as exc:
            progress["status"] = "stopped_security_or_infrastructure_invalid"
            progress["active_task_id"] = None
            progress["failure_task_id"] = task_id
            progress["failure_type"] = type(exc).__name__
            _write_progress(root, progress)
            raise ConfigurationError(
                f"OpenHands v19 agent image build stopped on {task_id}"
            ) from exc
        progress["locks"][task_id] = {
            "lock": f"image-locks/pr-{suffix}.json",
            "lock_hash": lock.lock_hash,
            "agent_image": lock.derived_agent_image_id,
            "verifier_image": lock.verifier_base_image_id,
            "security_scan_id": lock.security_scan_id,
        }
        progress["active_task_id"] = None
        _write_progress(root, progress)

    if len({item["agent_image"] for item in progress["locks"].values()}) != len(task_ids):
        raise ConfigurationError("OpenHands v19 reserve tasks reused an agent image")
    progress["status"] = "completed"
    _write_progress(root, progress)
    return _sealed_progress(progress)


def _legacy_identity(
    *,
    template: HweAgentImageLock,
    binding: dict[str, Any],
    receipt: dict[str, Any],
) -> HweAgentImageLock:
    task_id = binding.get("task_id") or receipt.get("task_id")
    base = template.model_dump(mode="json", exclude={"lock_hash"})
    base.update(
        {
            "task_id": task_id,
            "task_hash": binding.get("task_hash"),
            "source_hash": binding.get("source_hash"),
            "verifier_base_image_id": binding.get("verifier_image"),
            "derived_agent_image_id": receipt.get("derived_agent_image_id"),
            "security_scan_id": content_hash(
                {
                    "purpose": "temporary_v1_identity_for_v2_rescan",
                    "task_id": task_id,
                    "receipt": receipt,
                }
            ),
        }
    )
    return HweAgentImageLock.model_validate({**base, "lock_hash": content_hash(base)})


def _validated_template(template: HweAgentImageLock) -> HweAgentImageLock:
    if (
        template.format_id != "verigym_hwe_agent_image_lock_v1"
        or template.collection_profile_id != "hwe_standard_v1"
        or template.tool_contract_id != "hwe_native_shell_v1"
        or template.agent_codex_sha256 != _EXPECTED_AGENT_CODEX_SHA256
        or template.agent_rg_sha256 != _EXPECTED_AGENT_RG_SHA256
        or template.build_network != "none"
        or template.runtime_network != "none"
        or not template.security_scan_passed
        or template.provider_credentials_present
        or template.hidden_assets_present
        or template.verifier_payload_present
        or template.reference_patch_present
    ):
        raise ConfigurationError("OpenHands v19 agent image identity template is incompatible")
    return template


def _validate_final_lock(
    lock: HweAgentImageLock,
    *,
    task_id: str,
    binding: dict[str, Any],
) -> None:
    if (
        lock.format_id != "verigym_hwe_agent_image_lock_v2"
        or lock.task_id != task_id
        or lock.task_hash != binding.get("task_hash")
        or lock.source_hash != binding.get("source_hash")
        or lock.verifier_base_image_id != binding.get("verifier_image")
        or lock.build_network != "none"
        or lock.runtime_network != "none"
        or not lock.security_scan_passed
    ):
        raise ConfigurationError("OpenHands v19 agent image lock binding changed")


def _validated_qualification_progress(value: dict[str, Any]) -> dict[str, Any]:
    expected_hash = value.pop("progress_hash", None)
    if not isinstance(expected_hash, str) or content_hash(value) != expected_hash:
        raise ConfigurationError("OpenHands v19 qualification progress identity changed")
    value["progress_hash"] = expected_hash
    task_ids = [
        *value.get("training_reserve_task_ids", []),
        *value.get("validation_reserve_task_ids", []),
    ]
    outcomes = value.get("outcomes")
    if not isinstance(outcomes, list):
        raise ConfigurationError("OpenHands v19 qualification outcomes are missing")
    try:
        gate = evaluate_v19_qualification_gate(outcomes)
    except ValueError as exc:
        raise ConfigurationError("OpenHands v19 qualification outcomes changed") from exc
    if (
        value.get("format_id") != OPENHANDS_V19_PUBLIC_QUALIFICATION_FORMAT
        or value.get("status") != "qualified_pending_agent_images"
        or value.get("candidate_order") != list(OPENHANDS_V19_QUALIFICATION_CANDIDATES)
        or value.get("implicit_image_pulls_allowed") is not False
        or len(task_ids) != OPENHANDS_V19_QUALIFIED_TASK_TARGET
        or len(set(task_ids)) != OPENHANDS_V19_QUALIFIED_TASK_TARGET
        or not gate.satisfied
        or task_ids != [*gate.training_reserve_task_ids, *gate.validation_reserve_task_ids]
        or value.get("qualified_task_ids") != list(gate.qualified_task_ids)
        or value.get("heldout_task_ids_loaded") != []
        or value.get("model_process_count") != 0
        or value.get("verifier_network") != "none"
        or not isinstance(value.get("qualified_bindings"), dict)
        or set(value["qualified_bindings"]) != set(task_ids)
    ):
        raise ConfigurationError("OpenHands v19 qualification progress is incomplete")
    outcomes_by_task = {item.get("task_id"): item for item in outcomes if isinstance(item, dict)}
    for task_id, binding in value["qualified_bindings"].items():
        suffix = task_id.rsplit("-", 1)[-1]
        outcome = outcomes_by_task.get(task_id)
        if (
            not isinstance(binding, dict)
            or set(binding)
            != {
                "task_hash",
                "source_hash",
                "source_image_lock_sha256",
                "verifier_image",
                "verifier_manifest_digest",
                "source",
                "smoke",
            }
            or not isinstance(outcome, dict)
            or outcome.get("verifier_image") != binding.get("verifier_image")
            or binding.get("source") != f"sources/pr-{suffix}"
            or binding.get("smoke") != f"smokes/pr-{suffix}"
        ):
            raise ConfigurationError("OpenHands v19 qualification binding is malformed")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError(f"unsafe OpenHands v19 JSON input: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v19 JSON input: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v19 JSON input is not an object: {path.name}")
    return value


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("OpenHands v19 agent image output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _sealed_progress(progress: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(progress)
    base.pop("progress_hash", None)
    return {**base, "progress_hash": content_hash(base)}


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "agent-image-progress.json", _sealed_progress(progress))


def main() -> int:
    arguments = _parser().parse_args()
    progress = build_and_lock_v19_agent_images(
        qualification_root=arguments.qualification_root,
        identity_template=arguments.identity_template,
        codex_binary=arguments.codex_binary,
        output=arguments.output,
    )
    print(
        json.dumps(
            {
                "status": progress["status"],
                "lock_count": len(progress["locks"]),
                "progress_hash": progress["progress_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
