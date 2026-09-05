#!/usr/bin/env python3
"""Repair and atomically publish the fully qualified v158 scaffold contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
_SOURCE_ROOTS = (
    _REPOSITORY,
    _REPOSITORY / "src",
    _REPOSITORY / "integrations/verigym-hwe-bench/src",
    _REPOSITORY / "integrations/verigym-deepseek-harness/src",
)
for _source_root in reversed(_SOURCE_ROOTS):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v158_explicit_endpoint_scaffold as v158,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_directory  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV160ContractRepairManifest,
    load_v158_explicit_endpoint_scaffold_manifest,
    load_v160_contract_repair_manifest,
)

IDENTITY = "deepseek-harness-hwe-v160-contract-repair-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V160_CONTRACT_REPAIR"
CHILD_BOUNDARY_ENV = "VERIGYM_V160_ZERO_PROVIDER_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v160_contract_repair_v1.json"
)
V158_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v158_explicit_endpoint_scaffold_v1.json"
)
V158_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v158_explicit_endpoint_scaffold.py"
)
V158_LAUNCHER = _REPOSITORY / (
    "scripts/launch_hwe_deepseek_harness_v158_explicit_endpoint_scaffold.py"
)
V158_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v158-explicit-endpoint-scaffold-authorization.md"
)
V159_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v159-v158-result.md"
V160_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v160-contract-repair-authorization.md"
)
V158_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v158-explicit-endpoint-scaffold-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v160-contract-repair-v1"
)
_DOCKER_ENDPOINT_ENV_NAMES = ("DOCKER_CONTEXT", "DOCKER_HOST")
_MAX_JSON_BYTES = 64 * 1024 * 1024
_MAX_DOCKER_OUTPUT_BYTES = 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_deepseek_harness_v158_explicit_endpoint_scaffold_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v160_contract_repair_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v158-explicit-endpoint-scaffold-authorization.md",
    "docs/audits/2026-09-05_deepseek-harness-v159-v158-result.md",
    "docs/audits/2026-09-05_deepseek-harness-v160-contract-repair-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v158_explicit_endpoint_scaffold.py",
    "integrations/verigym-deepseek-harness/tests/test_v160_contract_repair.py",
    "scripts/launch_hwe_deepseek_harness_v158_explicit_endpoint_scaffold.py",
    "scripts/launch_hwe_deepseek_harness_v160_contract_repair.py",
    "scripts/materialize_hwe_deepseek_harness_v158_explicit_endpoint_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v160_contract_repair.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "SECURITY.md",
)
_CLOSED_FLAGS = (
    "formal_collection_allowed",
    "formal_collection_started",
    "collection_started",
    "training_started",
    "production_training_ready",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_git_file(commit: str, path: Path) -> str:
    try:
        relative = path.relative_to(_REPOSITORY).as_posix()
    except ValueError as exc:
        raise ConfigurationError("v160 frozen Git path escaped the repository") from exc
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v160 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v160 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v160 predecessor JSON must be an object")
    return value


def _require_canonical_hash(
    value: Mapping[str, Any], *, field: str, expected: str, label: str
) -> None:
    base = copy.deepcopy(dict(value))
    observed = base.pop(field, None)
    if observed != expected or content_hash(base) != expected:
        raise ConfigurationError(f"v160 predecessor {label} canonical hash changed")


def _git_text(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(CHILD_BOUNDARY_ENV) != "1":
        raise ConfigurationError("v160 requires its one-use zero-provider child boundary")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v160 requires a non-root host identity")
    blocked = (*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, *_DOCKER_ENDPOINT_ENV_NAMES)
    if any(name in os.environ for name in blocked):
        raise ConfigurationError("v160 zero-provider child environment is contaminated")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v160 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v160 requires a positive post-merge main run ID")
    if OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink():
        raise ConfigurationError("v160 output identity has already been consumed")


def _require_clean_merged_main(manifest: DeepSeekHarnessV160ContractRepairManifest) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git_text("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v160 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v159_audit_merge, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if (
        branch != "main"
        or head != upstream
        or len(head) != 40
        or ancestor.returncode != 0
        or ancestor.stdout
        or ancestor.stderr
    ):
        raise ConfigurationError("v160 requires clean merged origin/main after v159")
    return head


def _validate_tree(manifest: DeepSeekHarnessV160ContractRepairManifest) -> None:
    if V158_ROOT.is_symlink() or not V158_ROOT.is_dir():
        raise ConfigurationError("v160 v158 evidence root is unsafe")
    directories = 0
    regular_files = 0
    symlinks = 0
    directory_modes: dict[int, int] = {}
    file_modes: dict[int, int] = {}
    for path in (V158_ROOT, *V158_ROOT.rglob("*")):
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            symlinks += 1
        elif path.is_dir():
            directories += 1
            directory_modes[mode] = directory_modes.get(mode, 0) + 1
        elif stat.S_ISREG(metadata.st_mode):
            regular_files += 1
            file_modes[mode] = file_modes.get(mode, 0) + 1
        else:
            raise ConfigurationError("v160 v158 evidence contains an unsafe file type")
    if (
        directories != manifest.v158_evidence_directory_count
        or regular_files != manifest.v158_evidence_regular_file_count
        or symlinks != manifest.v158_evidence_symlink_count
        or directory_modes != {0o700: 20, 0o755: 1766}
        or file_modes != {0o600: 65, 0o644: 10427}
        or hash_directory(V158_ROOT) != manifest.v158_evidence_tree_hash
    ):
        raise ConfigurationError("v160 v158 evidence tree changed")


def _validate_all_self_hashes() -> None:
    recognized = 0
    unsealed = 0
    for path in sorted(V158_ROOT.rglob("*.json")):
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            continue
        try:
            value = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            raise ConfigurationError("v160 mode-0600 predecessor JSON is not an object")
        matches = 0
        for field, observed in value.items():
            if not field.endswith("_hash") or not isinstance(observed, str) or len(observed) != 64:
                continue
            base = copy.deepcopy(value)
            base.pop(field)
            matches += int(content_hash(base) == observed)
        if matches > 1:
            raise ConfigurationError("v160 predecessor JSON has ambiguous canonical self-hashes")
        if matches == 1:
            recognized += 1
        else:
            unsealed += 1
    if recognized != 45 or unsealed != 20:
        raise ConfigurationError("v160 predecessor canonical JSON inventory changed")


def _validate_static_files(manifest: DeepSeekHarnessV160ContractRepairManifest) -> None:
    v158_manifest = load_v158_explicit_endpoint_scaffold_manifest(V158_MANIFEST)
    if (
        _hash_file(V158_MANIFEST) != manifest.v158_manifest_sha256
        or v158_manifest.manifest_hash != manifest.v158_manifest_hash
        or _hash_file(V158_RUNNER) != manifest.v158_runner_sha256
        or _hash_file(V158_LAUNCHER) != manifest.v158_launcher_sha256
        or _hash_file(V158_AUTHORIZATION) != manifest.v158_authorization_sha256
        or _hash_file(V159_AUDIT) != manifest.v159_audit_sha256
        or _hash_git_file(manifest.v158_source_commit, V158_MANIFEST)
        != manifest.v158_manifest_sha256
        or _hash_git_file(manifest.v158_source_commit, V158_RUNNER) != manifest.v158_runner_sha256
        or _hash_git_file(manifest.v158_source_commit, V158_LAUNCHER)
        != manifest.v158_launcher_sha256
        or _hash_git_file(manifest.v158_source_commit, V158_AUTHORIZATION)
        != manifest.v158_authorization_sha256
        or _hash_git_file(manifest.v159_audit_commit, V159_AUDIT) != manifest.v159_audit_sha256
        or tuple(v158_manifest.schedule_task_ids) != tuple(manifest.schedule_task_ids)
        or v158_manifest.seed != manifest.seed
        or v158_manifest.sample_index != manifest.sample_index
    ):
        raise ConfigurationError("v160 frozen implementation or audit binding changed")


def _validate_predecessor(
    manifest: DeepSeekHarnessV160ContractRepairManifest,
) -> dict[str, dict[str, Any]]:
    _validate_tree(manifest)
    _validate_all_self_hashes()
    paths = {
        "report": V158_ROOT / "execution-scaffold-report.json",
        "progress": V158_ROOT / "execution-scaffold-progress.json",
        "task_set": V158_ROOT / "task-materialization-set.json",
        "inventory": V158_ROOT / "execution-inventory.json",
        "final_inventory": V158_ROOT / "final-execution-inventory.json",
        "runtime_preflight": V158_ROOT / "preflight/runtime-prepare.json",
        "harness_preflight": V158_ROOT / "preflight/harness-initialize.json",
        "command_probe": V158_ROOT / "command-image-probe-diagnostics/attempt-1.json",
        "runtime": V158_ROOT / "dind-runtime-receipt.json",
        "transfer": V158_ROOT / "image-transfer-set.json",
        "cleanup": V158_ROOT / "dind-cleanup-receipt.json",
    }
    values = {name: _load_json(path) for name, path in paths.items()}
    if paths["report"].read_bytes() != paths["progress"].read_bytes():
        raise ConfigurationError("v160 v158 terminal report and progress differ")
    file_hashes = {
        "report": manifest.v158_report_sha256,
        "progress": manifest.v158_report_sha256,
        "task_set": manifest.v158_task_set_sha256,
        "inventory": manifest.v158_inventory_sha256,
        "final_inventory": manifest.v158_inventory_sha256,
        "runtime_preflight": manifest.v158_runtime_preflight_sha256,
        "harness_preflight": manifest.v158_harness_preflight_sha256,
        "command_probe": manifest.v158_command_probe_sha256,
        "cleanup": manifest.v158_cleanup_sha256,
    }
    if any(_hash_file(paths[name]) != expected for name, expected in file_hashes.items()):
        raise ConfigurationError("v160 v158 sealed evidence file changed")
    canonical = {
        "report": ("report_hash", manifest.v158_report_hash),
        "progress": ("report_hash", manifest.v158_report_hash),
        "task_set": ("receipt_hash", manifest.v158_task_set_hash),
        "inventory": ("inventory_hash", manifest.v158_inventory_hash),
        "final_inventory": ("inventory_hash", manifest.v158_inventory_hash),
        "runtime_preflight": ("receipt_hash", manifest.v158_runtime_preflight_hash),
        "harness_preflight": ("receipt_hash", manifest.v158_harness_preflight_hash),
        "command_probe": ("diagnostic_hash", manifest.v158_command_probe_hash),
        "cleanup": ("receipt_hash", manifest.v158_cleanup_hash),
    }
    for name, (field, expected) in canonical.items():
        _require_canonical_hash(values[name], field=field, expected=expected, label=name)

    report = values["report"]
    task_set = values["task_set"]
    inventory = values["inventory"]
    runtime_preflight = values["runtime_preflight"]
    harness_preflight = values["harness_preflight"]
    cleanup = values["cleanup"]
    task_receipts = task_set.get("task_receipts")
    expected_schedule = list(manifest.schedule_task_ids)
    if (
        report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "ConfigurationError"
        or report.get("provider_execution_scaffold_published") is not False
        or report.get("provider_execution_authorized") is not False
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or report.get("dind_cleanup_confirmed") is not True
        or report.get("dind_cleanup_receipt_hash") is not None
        or any(report.get(field) is not False for field in _CLOSED_FLAGS)
        or task_set.get("completed_task_ids") != expected_schedule
        or task_set.get("task_count") != 5
        or task_set.get("all_reference_patches_compatible") is not True
        or task_set.get("all_base_failed_reference_passed") is not True
        or task_set.get("all_command_images_v2_scanned") is not True
        or task_set.get("registry_accessed") is not False
        or task_set.get("partial_archive_used") is not False
        or not isinstance(task_receipts, list)
        or len(task_receipts) != 5
        or [item.get("task_id") for item in task_receipts if isinstance(item, dict)]
        != expected_schedule
        or any(
            not isinstance(item, dict)
            or item.get("base_failed") is not True
            or item.get("base_infrastructure_error") is not False
            or item.get("reference_passed") is not True
            or item.get("verifier_network") != "none"
            or item.get("agent_command_network") != "none"
            or item.get("provider_calls") != 0
            or item.get("model_process_count") != 0
            for item in task_receipts
        )
        or inventory.get("required_images_present") is not True
        or inventory.get("required_image_count") != 12
        or inventory.get("workspace_runtime_image_present") is not True
        or inventory.get("inner_container_inventory_empty") is not True
        or inventory.get("inner_volume_inventory_empty") is not True
        or values["final_inventory"] != inventory
        or runtime_preflight.get("status") != "passed"
        or runtime_preflight.get("completed_task_ids") != expected_schedule
        or runtime_preflight.get("task_count") != 5
        or runtime_preflight.get("fresh_engine_count") != 5
        or runtime_preflight.get("distinct_engine_count") != 5
        or runtime_preflight.get("docker_cli_explicit_binding") is not True
        or runtime_preflight.get("ambient_docker_endpoint_used") is not False
        or harness_preflight.get("status") != "passed"
        or harness_preflight.get("provider_request_started") is not False
        or harness_preflight.get("provider_call_count") != 0
        or harness_preflight.get("settings_endpoint_bound") is not True
        or harness_preflight.get("ambient_docker_endpoint_used") is not False
        or harness_preflight.get("synthetic_provider_values_only") is not True
        or "provider_values_persisted_or_hashed" in harness_preflight
        or not isinstance(harness_preflight.get("synthetic_value_scan"), dict)
        or harness_preflight["synthetic_value_scan"].get("match_count") != 0
        or harness_preflight["synthetic_value_scan"].get("values_persisted") is not False
        or harness_preflight["synthetic_value_scan"].get("values_hashed") is not False
        or values["command_probe"].get("status") != "passed"
        or values["command_probe"].get("completed_task_ids") != expected_schedule
        or cleanup.get("socket_volume_removed") is not True
        or cleanup.get("socket_backing_empty") is not True
        or cleanup.get("failed_data_volume_policy") != "freeze-exact-owned-volume"
        or (V158_ROOT / "execution-scaffold-contract.json").exists()
    ):
        raise ConfigurationError("v160 v158 predecessor semantics changed")
    _require_canonical_hash(
        values["runtime"],
        field="receipt_hash",
        expected=report["dind_runtime_receipt_hash"],
        label="runtime",
    )
    _require_canonical_hash(
        values["transfer"],
        field="receipt_hash",
        expected=report["image_transfer_receipt_hash"],
        label="transfer",
    )
    return values


def _docker_read(
    arguments: list[str], *, accept_failure: bool = False
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["docker", *arguments],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if (
        len(completed.stdout.encode()) > _MAX_DOCKER_OUTPUT_BYTES
        or len(completed.stderr.encode()) > _MAX_DOCKER_OUTPUT_BYTES
        or (completed.returncode != 0 and not accept_failure)
    ):
        raise ConfigurationError("v160 bounded Docker metadata query failed")
    return completed


def _validate_frozen_volume(
    manifest: DeepSeekHarnessV160ContractRepairManifest,
) -> dict[str, Any]:
    completed = _docker_read(["volume", "inspect", manifest.v158_data_volume])
    try:
        values = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v160 Docker volume metadata is invalid") from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ConfigurationError("v160 Docker volume metadata inventory changed")
    volume = values[0]
    labels = volume.get("Labels")
    options = volume.get("Options")
    backing = Path(manifest.v158_data_backing)
    try:
        backing_metadata = backing.lstat()
    except OSError as exc:
        raise ConfigurationError("v160 frozen data-volume backing is unavailable") from exc
    if (
        volume.get("Name") != manifest.v158_data_volume
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or not isinstance(labels, dict)
        or labels.get("verigym.owner") != manifest.v158_data_volume_owner
        or labels.get("verigym.role") != "data"
        or options != {"device": manifest.v158_data_backing, "o": "bind", "type": "none"}
        or backing.is_symlink()
        or not stat.S_ISDIR(backing_metadata.st_mode)
        or stat.S_IMODE(backing_metadata.st_mode) != 0o710
        or backing_metadata.st_uid != 0
        or backing_metadata.st_gid != 0
    ):
        raise ConfigurationError("v160 frozen data-volume binding changed")
    users = _docker_read(
        [
            "ps",
            "-a",
            "--filter",
            f"volume={manifest.v158_data_volume}",
            "--format",
            "{{.ID}}",
        ]
    )
    socket = _docker_read(
        [
            "volume",
            "ls",
            "--filter",
            "name=^verigym-deepseek-harness-v158-dind-socket$",
            "--format",
            "{{.Name}}",
        ]
    )
    if users.stdout.strip() or socket.stdout.strip():
        raise ConfigurationError("v160 frozen volume is in use or the socket volume remains")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v160_volume_metadata_receipt_v1",
        "identity": IDENTITY,
        "status": "passed",
        "volume_name": manifest.v158_data_volume,
        "volume_owner": manifest.v158_data_volume_owner,
        "volume_role": "data",
        "volume_backing": manifest.v158_data_backing,
        "volume_driver": "local",
        "volume_scope": "local",
        "volume_content_mounted": False,
        "volume_content_inspected": False,
        "volume_mutated": False,
        "container_user_count": 0,
        "socket_volume_present": False,
        "raw_docker_output_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _repair_harness_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    old_hash = base.pop("receipt_hash", None)
    scan = base.get("synthetic_value_scan")
    if (
        not isinstance(old_hash, str)
        or content_hash(base) != old_hash
        or "provider_values_persisted_or_hashed" in base
        or not isinstance(scan, dict)
        or scan.get("match_count") != 0
        or scan.get("values_persisted") is not False
        or scan.get("values_hashed") is not False
        or base.get("provider_request_started") is not False
        or base.get("provider_call_count") != 0
    ):
        raise ConfigurationError("v160 cannot derive the legacy provider-value aggregate")
    base["provider_values_persisted_or_hashed"] = False
    repaired = {**base, "receipt_hash": content_hash(base)}
    if repaired["receipt_hash"] == old_hash:
        raise ConfigurationError("v160 repaired Harness receipt identity did not change")
    return repaired


def _reconstruct_v158_contract(
    manifest: DeepSeekHarnessV160ContractRepairManifest,
    values: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    composed = v158._load_composed_manifest(V158_MANIFEST)  # noqa: SLF001
    task_materialization = copy.deepcopy(dict(values["task_set"]))
    inventory = copy.deepcopy(dict(values["inventory"]))
    schedule = list(manifest.schedule_task_ids)
    for field in (
        "final_inventory_fresh_command_images",
        "final_inventory_fresh_command_image_lock_hashes",
    ):
        unordered = task_materialization.get(field)
        if not isinstance(unordered, dict) or set(unordered) != set(schedule):
            raise ConfigurationError("v160 persisted v158 task inventory is incomplete")
        task_materialization[field] = {task_id: unordered[task_id] for task_id in schedule}
    unordered_images = inventory.get("fresh_command_images_by_task")
    if not isinstance(unordered_images, dict) or set(unordered_images) != set(schedule):
        raise ConfigurationError("v160 persisted v158 final inventory is incomplete")
    inventory["fresh_command_images_by_task"] = {
        task_id: unordered_images[task_id] for task_id in schedule
    }
    repaired_harness = _repair_harness_receipt(values["harness_preflight"])
    contract = v158._scaffold_contract(  # noqa: SLF001
        composed,
        source_commit=manifest.v158_source_commit,
        post_merge_main_run_id=manifest.v158_post_merge_main_run_id,
        runtime_receipt=values["runtime"],
        transfer=values["transfer"],
        task_materialization=task_materialization,
        inventory=inventory,
        runtime_preflight=values["runtime_preflight"],
        harness_preflight=repaired_harness,
        cleanup=values["cleanup"],
    )
    expected = contract.get("contract_hash")
    base = copy.deepcopy(contract)
    base.pop("contract_hash", None)
    if (
        not isinstance(expected, str)
        or content_hash(base) != expected
        or contract.get("provider_execution_scaffold_published") is not True
        or contract.get("provider_execution_authorized") is not False
        or contract.get("provider_request_started") is not False
        or contract.get("provider_calls") != 0
        or contract.get("task_count") != 5
        or contract.get("dind_cleanup_receipt_hash") != values["cleanup"].get("receipt_hash")
    ):
        raise ConfigurationError("v160 reconstructed v158 contract is invalid")
    return contract, repaired_harness


def _build_v160_contract(
    manifest: DeepSeekHarnessV160ContractRepairManifest,
    reconstructed: Mapping[str, Any],
    *,
    predecessor_validation_hash: str,
    repair_receipt_hash: str,
    volume_metadata_hash: str,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    base = copy.deepcopy(dict(reconstructed))
    reconstructed_hash = base.pop("contract_hash", None)
    base.pop("requires_independent_v159_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v160_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "manifest_hash": manifest.manifest_hash,
            "v158_manifest_hash": manifest.v158_manifest_hash,
            "v158_report_hash": manifest.v158_report_hash,
            "v158_evidence_tree_hash": manifest.v158_evidence_tree_hash,
            "v158_reconstructed_contract_hash": reconstructed_hash,
            "v159_audit_merge": manifest.v159_audit_merge,
            "v159_post_merge_main_run_id": manifest.v159_post_merge_main_run_id,
            "source_commit": source_commit,
            "post_merge_main_run_id": post_merge_main_run_id,
            "post_merge_main_all_eight_classes_passed": True,
            "predecessor_validation_hash": predecessor_validation_hash,
            "contract_repair_receipt_hash": repair_receipt_hash,
            "volume_metadata_receipt_hash": volume_metadata_hash,
            "compatibility_field": manifest.compatibility_field,
            "compatibility_value": manifest.compatibility_value,
            "compatibility_derivation": manifest.compatibility_derivation,
            "predecessor_data_volume": manifest.v158_data_volume,
            "predecessor_data_backing": manifest.v158_data_backing,
            "predecessor_data_volume_owner": manifest.v158_data_volume_owner,
            "predecessor_volume_metadata_inspected": True,
            "predecessor_volume_content_mounted": False,
            "predecessor_volume_content_inspected": False,
            "predecessor_volume_mutated": False,
            "provider_successor_identity": manifest.provider_successor_identity,
            "provider_successor_reopen_budget": manifest.provider_successor_reopen_budget,
            "provider_successor_reopen_count": 0,
            "provider_environment_boundary": "exact-sanitized-child-v1",
            "provider_environment_name_count": manifest.provider_environment_name_count,
            "provider_environment_values_read": False,
            "provider_environment_values_printed": False,
            "provider_environment_values_persisted": False,
            "provider_environment_values_hashed": False,
            "registry_accessed": False,
            "partial_archive_used": False,
            "requires_independent_v161_audit": True,
        }
    )
    for field in _CLOSED_FLAGS:
        base[field] = False
    return {**base, "contract_hash": content_hash(base)}


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_execution_boundary(arguments)
    manifest = load_v160_contract_repair_manifest(arguments.manifest)
    source_commit = _require_clean_merged_main(manifest)
    _validate_static_files(manifest)
    values = _validate_predecessor(manifest)
    volume = _validate_frozen_volume(manifest)
    reconstructed, repaired_harness = _reconstruct_v158_contract(manifest, values)
    predecessor_base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v160_predecessor_validation_receipt_v1",
        "identity": IDENTITY,
        "status": "passed",
        "v158_manifest_hash": manifest.v158_manifest_hash,
        "v158_report_hash": manifest.v158_report_hash,
        "v158_task_set_hash": manifest.v158_task_set_hash,
        "v158_inventory_hash": manifest.v158_inventory_hash,
        "v158_evidence_tree_hash": manifest.v158_evidence_tree_hash,
        "v158_evidence_directory_count": manifest.v158_evidence_directory_count,
        "v158_evidence_regular_file_count": manifest.v158_evidence_regular_file_count,
        "v158_evidence_symlink_count": manifest.v158_evidence_symlink_count,
        "canonical_self_hash_count": 45,
        "unsealed_semantic_json_count": 20,
        "terminal_report_progress_identical": True,
        "v158_execution_contract_present": False,
        "all_five_tasks_qualified": True,
        "all_explicit_endpoint_preflights_passed": True,
        "legacy_aggregate_missing_confirmed": True,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "registry_accessed": False,
        "partial_archive_used": False,
    }
    predecessor = {**predecessor_base, "receipt_hash": content_hash(predecessor_base)}
    repair_base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v160_contract_repair_receipt_v1",
        "identity": IDENTITY,
        "status": "passed",
        "compatibility_field": manifest.compatibility_field,
        "compatibility_value": manifest.compatibility_value,
        "compatibility_derivation": manifest.compatibility_derivation,
        "original_harness_receipt_hash": manifest.v158_harness_preflight_hash,
        "repaired_harness_receipt_hash": repaired_harness["receipt_hash"],
        "reconstructed_v158_contract_hash": reconstructed["contract_hash"],
        "in_memory_only": True,
        "v158_evidence_mutated": False,
        "provider_request_started": False,
        "provider_calls": 0,
    }
    repair = {**repair_base, "receipt_hash": content_hash(repair_base)}
    contract = _build_v160_contract(
        manifest,
        reconstructed,
        predecessor_validation_hash=predecessor["receipt_hash"],
        repair_receipt_hash=repair["receipt_hash"],
        volume_metadata_hash=volume["receipt_hash"],
        source_commit=source_commit,
        post_merge_main_run_id=arguments.post_merge_main_run_id,
    )
    report_base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v160_contract_repair_report_v1",
        "identity": IDENTITY,
        "status": "completed_pending_independent_v161_audit",
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "v158_report_hash": manifest.v158_report_hash,
        "v158_evidence_tree_hash": manifest.v158_evidence_tree_hash,
        "v159_audit_merge": manifest.v159_audit_merge,
        "v159_post_merge_main_run_id": manifest.v159_post_merge_main_run_id,
        "predecessor_validation_hash": predecessor["receipt_hash"],
        "volume_metadata_receipt_hash": volume["receipt_hash"],
        "contract_repair_receipt_hash": repair["receipt_hash"],
        "execution_scaffold_contract_hash": contract["contract_hash"],
        "provider_execution_scaffold_published": True,
        "provider_execution_authorized": False,
        "provider_successor_identity": manifest.provider_successor_identity,
        "provider_successor_reopen_budget": manifest.provider_successor_reopen_budget,
        "provider_successor_reopen_count": 0,
        "predecessor_volume_metadata_inspected": True,
        "predecessor_volume_content_mounted": False,
        "predecessor_volume_content_inspected": False,
        "predecessor_volume_mutated": False,
        "v158_evidence_mutated": False,
        "provider_environment_boundary": "exact-sanitized-child-v1",
        "provider_environment_name_count": manifest.provider_environment_name_count,
        "provider_environment_values_read": False,
        "provider_environment_values_printed": False,
        "provider_environment_values_persisted": False,
        "provider_environment_values_hashed": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "registry_accessed": False,
        "partial_archive_used": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    report = {**report_base, "report_hash": content_hash(report_base)}

    staging = OUTPUT_ROOT.with_name(f".{OUTPUT_ROOT.name}.staging-{os.getpid()}")
    if staging.exists() or staging.is_symlink():
        raise ConfigurationError("v160 staging identity already exists")
    staging.mkdir(mode=0o700, parents=False)
    try:
        atomic_dump_json(staging / "predecessor-validation.json", predecessor)
        atomic_dump_json(staging / "volume-metadata.json", volume)
        atomic_dump_json(staging / "repaired-harness-initialize.json", repaired_harness)
        atomic_dump_json(staging / "contract-repair.json", repair)
        atomic_dump_json(staging / "execution-scaffold-contract.json", contract)
        atomic_dump_json(staging / "execution-scaffold-report.json", report)
        atomic_dump_json(staging / "execution-scaffold-progress.json", report)
        os.replace(staging, OUTPUT_ROOT)
    finally:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
    return report


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "provider_execution_scaffold_published": report[
                    "provider_execution_scaffold_published"
                ],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
