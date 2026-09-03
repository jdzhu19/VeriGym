#!/usr/bin/env python3
"""Materialize the atomic five-task DeepSeek Harness v69 provider contract offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
_SOURCE_ROOTS = (
    _REPOSITORY,
    _REPOSITORY / "src",
    _REPOSITORY / "integrations/verigym-hwe-bench/src",
)
for _source_root in reversed(_SOURCE_ROOTS):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from verigym_hwe_bench.adapter import HweBenchSuite  # noqa: E402
from verigym_hwe_bench.cva6_qualification import (  # noqa: E402
    run_zero_model_smoke,
    zero_model_fail_to_pass_eligible,
    zero_model_infrastructure_valid,
)
from verigym_hwe_bench.models import ImageLockV2  # noqa: E402
from verigym_hwe_bench.prepare import (  # noqa: E402
    load_selected_instances,
    prepare_source,
    reference_patch_compatibility,
)

from scripts.scan_and_lock_cva6_hwe_command_image import scan_and_lock  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV69Manifest,
    HweOfflineTaskLock,
    inspect_offline_image_archive,
    load_v69_manifest,
)
from verigym.hwe.image_lock import build_hwe_command_source_lock  # noqa: E402
from verigym.hwe.materialization_preflight import (  # noqa: E402
    MaterializationHeadroomError,
    discover_docker_root,
    require_materialization_headroom,
)
from verigym.schemas.suite import SuiteSourceConfig  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v69-multitask-zero-provider-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V69_ZERO_PROVIDER"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)
ARCHIVE_ROOT = Path("/data2/jiadongzhu/Agent/hwe-bench-public-images")
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v69-multitask-zero-provider-v1"
)
RG_ROOT = Path(
    "/data2/jiadongzhu/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl"
)
RG_BINARY = RG_ROOT / "rg"
RG_ARCHIVE = RG_ROOT.parent / "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz"
SCRATCH_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp")
RG_SHA256 = "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849"
RG_ARCHIVE_SHA256 = "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c"
_PROVIDER_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "VERIGYM_DEEPSEEK_API_BASE_URL",
        "VERIGYM_DEEPSEEK_API_KEY",
    }
)
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONTROL_OUTPUT = 4096
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json",
    "docs/audits/2026-09-03_deepseek-harness-v69-multitask-zero-provider-authorization.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v69_multitask_materialization.py",
    "integrations/verigym-hwe-bench/src/verigym_hwe_bench/prepare.py",
    "scripts/build_cva6_hwe_command_image.sh",
    "scripts/materialize_hwe_deepseek_harness_v69.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument("--rg-binary", type=Path, default=RG_BINARY)
    parser.add_argument("--rg-release-archive", type=Path, default=RG_ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the one-shot v69 qualification and publish only a complete contract."""

    _require_execution_boundary(arguments)
    manifest = load_v69_manifest(_exact_file(arguments.manifest, MANIFEST, "manifest"))
    source_commit = _require_clean_merged_main()
    archive_root = _exact_directory(arguments.archive_root, ARCHIVE_ROOT, "archive root")
    rg_binary = _validated_tool(arguments.rg_binary, RG_BINARY, RG_SHA256, executable=True)
    rg_archive = _validated_tool(
        arguments.rg_release_archive,
        RG_ARCHIVE,
        RG_ARCHIVE_SHA256,
        executable=False,
    )
    root = _new_output(arguments.output)
    for directory in (
        "archive-receipts",
        "image-receipts",
        "image-locks",
        "patch-compatibility",
        "qualification",
        "security-scans",
        "source-image-locks",
        "sources",
    ):
        (root / directory).mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v69_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "completed_task_ids": [],
        "task_receipts": [],
        "headroom_preflight_hash": None,
        "provider_contract_published": False,
        "provider_calls": 0,
        "model_process_count": 0,
        **_closed_training_flags(),
    }
    _write_progress(root, progress)
    try:
        instances = _patch_preflight(manifest, archive_root=archive_root, root=root)
        progress["status"] = "headroom_preflight"
        _write_progress(root, progress)
        try:
            headroom = require_materialization_headroom(
                control_root=Path("/"),
                docker_root=discover_docker_root(),
                scratch_root=_exact_directory(SCRATCH_ROOT, SCRATCH_ROOT, "scratch root"),
                output_parent=root.parent,
            )
        except MaterializationHeadroomError as exc:
            atomic_dump_json(root / "headroom-preflight.json", exc.receipt)
            progress.update(
                {
                    "headroom_preflight_hash": exc.receipt["preflight_hash"],
                    "failure_stage": "headroom_preflight",
                    "capacity_satisfied": False,
                }
            )
            raise
        atomic_dump_json(root / "headroom-preflight.json", headroom)
        progress.update(
            {
                "headroom_preflight_hash": headroom["preflight_hash"],
                "capacity_satisfied": True,
            }
        )
        progress["status"] = "offline_materialization"
        _write_progress(root, progress)
        for task_lock in manifest.primary_tasks:
            receipt = _materialize_task(
                task_lock,
                instance=instances[task_lock.task_id],
                archive_root=archive_root,
                rg_binary=rg_binary,
                rg_archive=rg_archive,
                root=root,
            )
            progress["completed_task_ids"].append(task_lock.task_id)
            progress["task_receipts"].append(receipt)
            _write_progress(root, progress)
        if progress["completed_task_ids"] != [task.task_id for task in manifest.primary_tasks]:
            raise ConfigurationError("v69 did not complete its exact primary schedule")
        contract = _provider_contract(
            manifest,
            progress["task_receipts"],
            source_commit=source_commit,
            post_merge_main_run_id=arguments.post_merge_main_run_id,
        )
        # The provider contract is the last file published. Earlier progress is never authority.
        atomic_dump_json(root / "provider-contract.json", contract)
        progress.update(
            {
                "status": "completed_pending_independent_v70_audit",
                "provider_contract_published": True,
                "provider_contract_hash": contract["contract_hash"],
            }
        )
        _write_progress(root, progress)
        report = _seal(
            {
                **progress,
                "provider_execution_authorized": False,
                "next_required_identity": "deepseek-harness-hwe-v70-v69-result-audit-v1",
            }
        )
        atomic_dump_json(root / "zero-provider-report.json", report)
        return report
    except (Exception, KeyboardInterrupt) as exc:
        stopped = _seal(
            {
                **progress,
                "status": "stopped_without_provider_contract",
                "stop_reason": type(exc).__name__,
                "provider_contract_published": False,
                "provider_execution_authorized": False,
                "raw_exception_persisted": False,
            }
        )
        _write_progress(root, stopped)
        atomic_dump_json(root / "zero-provider-report.json", stopped)
        raise


def _patch_preflight(
    manifest: DeepSeekHarnessV69Manifest,
    *,
    archive_root: Path,
    root: Path,
) -> dict[str, Any]:
    """Validate every selected patch before any Docker or archive image access."""

    dataset_hashes: dict[Path, str] = {}
    result: dict[str, Any] = {}
    for task in manifest.primary_tasks:
        dataset = _contained_file(archive_root, task.dataset_relpath, 512 * 1024 * 1024)
        if dataset not in dataset_hashes:
            dataset_hashes[dataset] = _hash_file(dataset)
        observed_dataset_hash = dataset_hashes[dataset]
        if observed_dataset_hash != task.dataset_sha256:
            raise ConfigurationError("v69 official dataset hash changed")
        if _selected_row_hash(dataset, task.instance_id) != task.selected_row_sha256:
            raise ConfigurationError("v69 selected public row hash changed")
        selected = load_selected_instances(dataset, {task.instance_id})
        if len(selected) != 1 or selected[0].base_commit != task.source_commit:
            raise ConfigurationError("v69 selected public source commit changed")
        compatibility = asdict(reference_patch_compatibility(selected[0]))
        if compatibility.get("compatible") is not True:
            raise ConfigurationError("v69 reference patch is incompatible")
        receipt = {
            "schema_version": "1.0",
            "format_id": "verigym_hwe_reference_patch_compatibility_receipt_v1",
            "task_id": task.task_id,
            **compatibility,
            "completed_before_archive_or_docker_access": True,
        }
        atomic_dump_json(root / "patch-compatibility" / f"pr-{task.pr_number}.json", receipt)
        result[task.task_id] = selected[0]
    return result


def _materialize_task(
    task: HweOfflineTaskLock,
    *,
    instance: Any,
    archive_root: Path,
    rg_binary: Path,
    rg_archive: Path,
    root: Path,
    campaign_identity: str = IDENTITY,
    command_tag_version: str = "v69",
    build_command_runner: Callable[[list[str], int], dict[str, Any]] | None = None,
    source_binding_runner: Callable[[Path, HweOfflineTaskLock], dict[str, str]] | None = None,
    scan_scratch_parent: Path | None = None,
) -> dict[str, Any]:
    archive_receipt = inspect_offline_image_archive(task, archive_root=archive_root)
    atomic_dump_json(root / "archive-receipts" / f"pr-{task.pr_number}.json", archive_receipt)
    _load_completed_archive(task, archive_root=archive_root)
    source = root / "sources" / f"pr-{task.pr_number}"
    dataset = _contained_file(archive_root, task.dataset_relpath, 512 * 1024 * 1024)
    prepare_source(
        dataset=dataset,
        output=source,
        selected_tasks=[task.instance_id],
        pull=False,
        imported_image_bindings={
            task.registry_reference: {
                "image_id": task.official_verifier_image,
                "manifest_digest": task.registry_manifest_digest,
            }
        },
    )
    binding = (
        _source_binding(source, task)
        if source_binding_runner is None
        else source_binding_runner(source, task)
    )
    smoke_root = root / "qualification" / f"pr-{task.pr_number}"
    smoke = run_zero_model_smoke(source=source, output=smoke_root)
    if not zero_model_infrastructure_valid(smoke) or not zero_model_fail_to_pass_eligible(smoke):
        raise ConfigurationError("v69 task did not reproduce base-FAIL/reference-PASS")
    artifacts = _inventory_toolchain(
        task,
        campaign_identity=campaign_identity,
        command_tag_version=command_tag_version,
    )
    profile_id = (
        "ibex-verilator-system-container-native-v1"
        if task.repository == "ibex"
        else "cva6-verilator-5.008-container-native-v2"
    )
    source_lock = build_hwe_command_source_lock(
        task_id=task.task_id,
        task_hash=binding["task_hash"],
        source_hash=binding["source_hash"],
        prepared_source_image_lock_sha256=binding["source_image_lock_sha256"],
        verifier_base_image_id=task.official_verifier_image,
        toolchain_profile_id=profile_id,
        allowlisted_artifacts=artifacts,
    )
    source_lock_path = root / "source-image-locks" / f"pr-{task.pr_number}.json"
    build_receipt_path = root / "image-receipts" / f"pr-{task.pr_number}.json"
    scan_path = root / "security-scans" / f"pr-{task.pr_number}.json"
    lock_path = root / "image-locks" / f"pr-{task.pr_number}.json"
    atomic_dump_json(source_lock_path, source_lock.model_dump(mode="json"))
    tag = f"verigym/{task.repository}-hwe-command:harness-{command_tag_version}-pr{task.pr_number}"
    build_script = (
        _REPOSITORY / "scripts/build_ibex_hwe_command_image.sh"
        if task.repository == "ibex"
        else _REPOSITORY / "scripts/build_cva6_hwe_command_image.sh"
    )
    command = [
        str(build_script),
        str(rg_binary),
        str(rg_archive),
        task.official_verifier_image,
        task.task_id,
        tag,
        str(build_receipt_path),
    ]
    if task.repository == "ibex":
        command.append("verilator")
    command_diagnostic = (
        build_command_runner(command, 1800) if build_command_runner is not None else None
    )
    if build_command_runner is None:
        _bounded_command(command, timeout=1800)
    scan, command_lock = scan_and_lock(
        receipt_path=build_receipt_path,
        identity_lock_path=source_lock_path,
        security_output=scan_path,
        lock_output=lock_path,
        repository_profile="ibex-verilator" if task.repository == "ibex" else "cva6",
        runtime_scratch_parent=scan_scratch_parent,
    )
    if scan.get("scan_passed") is not True or command_lock.security_scan_passed is not True:
        raise ConfigurationError("v69 task-specific command-image v2 scan failed")
    base: dict[str, Any] = {
        "task_id": task.task_id,
        "instance_id": instance.instance_id,
        "repository": task.repository,
        "task_hash": binding["task_hash"],
        "source_hash": binding["source_hash"],
        "source_commit": task.source_commit,
        "prepared_source_image_lock_sha256": binding["source_image_lock_sha256"],
        "archive_receipt_hash": archive_receipt["receipt_hash"],
        "registry_manifest_digest": task.registry_manifest_digest,
        "official_verifier_image": task.official_verifier_image,
        "agent_toolchain_id": task.agent_toolchain_id,
        "agent_command_image": command_lock.derived_command_image_id,
        "agent_command_image_lock_hash": command_lock.lock_hash,
        "security_scan_id": command_lock.security_scan_id,
        "toolchain_profile_id": command_lock.toolchain_profile_id,
        "base_failed": True,
        "base_infrastructure_error": False,
        "reference_passed": True,
        "verifier_network": "none",
        "agent_command_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
    }
    if command_diagnostic is not None:
        diagnostic_hash = command_diagnostic.get("diagnostic_hash")
        if not isinstance(diagnostic_hash, str) or _HASH.fullmatch(diagnostic_hash) is None:
            raise ConfigurationError("v69 build-command diagnostic hash is invalid")
        base["command_diagnostic_hash"] = diagnostic_hash
    return {**base, "task_receipt_hash": content_hash(base)}


def _source_binding(source: Path, task: HweOfflineTaskLock) -> dict[str, str]:
    lock_path = source / "image-lock.json"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ConfigurationError("v69 prepared source lacks a safe image lock")
    lock = ImageLockV2.model_validate_json(lock_path.read_bytes())
    if len(lock.entries) != 1:
        raise ConfigurationError("v69 prepared source must bind exactly one image")
    entry = lock.entries[0]
    suite = HweBenchSuite().with_source(
        SuiteSourceConfig(source_root=source, variant="repo-repair-v1")
    )
    references = list(suite.discover())
    if len(references) != 1:
        raise ConfigurationError("v69 prepared source exposed multiple tasks")
    loaded = suite.load_task(references[0])
    if (
        loaded.id != task.task_id
        or entry.instance_id != task.instance_id
        or entry.base_commit != task.source_commit
        or entry.image_id != task.official_verifier_image
        or entry.manifest_digest != task.registry_manifest_digest
        or loaded.source.content_hash is None
    ):
        raise ConfigurationError("v69 prepared source binding changed")
    return {
        "task_hash": content_hash(loaded),
        "source_hash": loaded.source.content_hash,
        "source_image_lock_sha256": hash_bytes(lock_path.read_bytes()),
    }


def _load_completed_archive(task: HweOfflineTaskLock, *, archive_root: Path) -> None:
    archive = _contained_file(archive_root, task.archive_relpath, 16 * 1024 * 1024 * 1024)
    _bounded_command(["docker", "load", "--input", str(archive)], timeout=1800)
    observed = _docker_image_id(task.official_verifier_image)
    if observed != task.official_verifier_image:
        raise ConfigurationError("v69 loaded image config identity changed")
    existing = _docker_image_id(task.registry_reference, required=False)
    if existing is not None and existing != task.official_verifier_image:
        raise ConfigurationError("v69 official task tag already names a different image")
    if existing is None:
        _bounded_command(
            ["docker", "image", "tag", task.official_verifier_image, task.registry_reference],
            timeout=30,
            require_empty=True,
        )
    if _docker_image_id(task.registry_reference) != task.official_verifier_image:
        raise ConfigurationError("v69 offline image tag binding changed")


def _inventory_toolchain(
    task: HweOfflineTaskLock,
    *,
    campaign_identity: str = IDENTITY,
    command_tag_version: str = "v69",
) -> list[dict[str, str]]:
    paths = (
        (
            ("/usr/bin/make", "build_tool"),
            ("/usr/bin/verilator", "simulator"),
            ("/usr/bin/verilator_bin", "simulator"),
        )
        if task.repository == "ibex"
        else (
            ("/usr/bin/make", "build_tool"),
            ("/tools/verilator/bin/verilator", "simulator"),
            ("/tools/verilator/bin/verilator_bin", "simulator"),
        )
    )
    name = f"verigym-hwe-{command_tag_version}-toolchain-{task.pr_number}-{secrets.token_hex(4)}"
    create = [
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        name,
        "--label",
        f"org.verigym.owner={campaign_identity}",
        "--label",
        "org.verigym.role=toolchain_inventory",
        "--network",
        "none",
        "--read-only",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--cpus",
        "0.5",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--entrypoint",
        "/usr/bin/sha256sum",
        task.official_verifier_image,
        "--",
        *[path for path, _role in paths],
    ]
    created = _bounded_command(create, timeout=30, return_stdout=True)
    container_id = created.decode("ascii", errors="strict").strip()
    try:
        inspection = _docker_inspect(container_id)
        host = inspection.get("HostConfig") or {}
        config = inspection.get("Config") or {}
        if (
            inspection.get("Mounts") not in (None, [])
            or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("CapAdd") not in (None, [])
            or host.get("CapDrop") != ["ALL"]
            or "no-new-privileges" not in (host.get("SecurityOpt") or [])
            or config.get("User") != f"{os.getuid()}:{os.getgid()}"
        ):
            raise ConfigurationError("v69 toolchain inventory controls are invalid")
        output = _bounded_command(
            ["docker", "start", "--attach", container_id],
            timeout=120,
            return_stdout=True,
        )
    finally:
        removed = _bounded_command(
            ["docker", "container", "rm", "--force", container_id],
            timeout=30,
            return_stdout=True,
        )
        if not removed.strip():
            raise ConfigurationError("v69 toolchain inventory cleanup was not confirmed")
    observed: dict[str, str] = {}
    for line in output.decode("ascii", errors="strict").splitlines():
        digest, separator, path = line.partition("  ")
        if not separator or _HASH.fullmatch(digest) is None or path in observed:
            raise ConfigurationError("v69 toolchain inventory output is malformed")
        observed[path] = digest
    if set(observed) != {path for path, _role in paths}:
        raise ConfigurationError("v69 toolchain inventory paths changed")
    return [{"path": path, "sha256": observed[path], "role": role} for path, role in paths]


def _provider_contract(
    manifest: DeepSeekHarnessV69Manifest,
    receipts: list[dict[str, Any]],
    *,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    if len(receipts) != len(manifest.primary_tasks):
        raise ConfigurationError("v69 refuses a partial provider contract")
    expected = [task.task_id for task in manifest.primary_tasks]
    if [receipt.get("task_id") for receipt in receipts] != expected:
        raise ConfigurationError("v69 provider contract task order changed")
    for receipt, task in zip(receipts, manifest.primary_tasks, strict=True):
        if (
            receipt.get("base_failed") is not True
            or receipt.get("base_infrastructure_error") is not False
            or receipt.get("reference_passed") is not True
            or receipt.get("verifier_network") != "none"
            or receipt.get("provider_calls") != 0
            or receipt.get("agent_toolchain_id") != task.agent_toolchain_id
            or receipt.get("official_verifier_image") != task.official_verifier_image
        ):
            raise ConfigurationError("v69 task is not eligible for atomic publication")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v69_provider_contract_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "schedule": expected,
        "task_bindings": receipts,
        "task_count": len(receipts),
        "all_tasks_materialized": True,
        "all_reference_patches_compatible": True,
        "all_base_failed_reference_passed": True,
        "all_command_images_v2_scanned": True,
        "verifier_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "partial_authorization_published": False,
        "provider_execution_authorized": False,
        "requires_independent_v70_audit": True,
        **_closed_training_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v69 requires a non-root host identity")
    if any(name in os.environ for name in _PROVIDER_ENV_NAMES):
        raise ConfigurationError("v69 refuses a provider configuration environment")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v69 requires a positive post-merge main run ID")


def _require_clean_merged_main() -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=_REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tracked != relative:
            raise ConfigurationError("v69 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    upstream = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if branch != "main" or head != upstream or len(head) != 40:
        raise ConfigurationError("v69 requires clean merged origin/main")
    return head


def _selected_row_hash(dataset: Path, instance_id: str) -> str:
    expected_org_repo, raw_pr = instance_id.rsplit(":pr-", 1)
    expected_org, expected_repo = expected_org_repo.split("/", 1)
    expected_pr = int(raw_pr)
    found: list[str] = []
    with dataset.open("rb") as stream:
        for raw in stream:
            if not raw or len(raw) > 16 * 1024 * 1024:
                raise ConfigurationError("v69 official dataset contains an invalid row")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ConfigurationError("v69 official dataset row is not an object")
            if (
                value.get("org") == expected_org
                and value.get("repo") == expected_repo
                and value.get("number") == expected_pr
            ):
                found.append(hashlib.sha256(raw).hexdigest())
    if len(found) != 1:
        raise ConfigurationError("v69 selected public row is not unique")
    return found[0]


def _docker_image_id(reference: str, *, required: bool = True) -> str | None:
    result = subprocess.run(
        ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        if required:
            raise ConfigurationError("v69 required local image is unavailable")
        return None
    if result.stderr or len(result.stdout) > 256:
        raise ConfigurationError("v69 Docker image inspection output is invalid")
    value = result.stdout.decode("ascii", errors="strict").strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ConfigurationError("v69 Docker image inspection identity is malformed")
    return value


def _docker_inspect(container_id: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "container", "inspect", container_id],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0 or result.stderr or len(result.stdout) > 1024 * 1024:
        raise ConfigurationError("v69 container inspection failed")
    value = json.loads(result.stdout)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ConfigurationError("v69 container inspection output is malformed")
    return value[0]


def _bounded_command(
    command: list[str],
    *,
    timeout: int,
    return_stdout: bool = False,
    require_empty: bool = False,
) -> bytes:
    result = subprocess.run(
        command,
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if (
        result.returncode != 0
        or len(result.stdout) > _MAX_CONTROL_OUTPUT
        or len(result.stderr) > _MAX_CONTROL_OUTPUT
        or (require_empty and (result.stdout or result.stderr))
        or (not return_stdout and result.stderr)
    ):
        raise ConfigurationError("v69 bounded local command failed")
    return result.stdout if return_stdout else b""


def _contained_file(root: Path, relative: str, maximum: int) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("v69 input is not a regular file")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not 0 < resolved.stat().st_size <= maximum:
        raise ConfigurationError("v69 input escaped or exceeded its bound")
    return resolved


def _validated_tool(
    path: Path,
    expected_path: Path,
    expected_hash: str,
    *,
    executable: bool,
) -> Path:
    resolved = _exact_file(path, expected_path, "tool")
    if (executable and not os.access(resolved, os.X_OK)) or _hash_file(resolved) != expected_hash:
        raise ConfigurationError("v69 public tool identity changed")
    return resolved


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"v69 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_dir():
        raise ConfigurationError(f"v69 {label} identity changed")
    return resolved


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"v69 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_file():
        raise ConfigurationError(f"v69 {label} identity changed")
    return resolved


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink() or path != OUTPUT_ROOT:
        raise ConfigurationError("v69 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _closed_training_flags() -> dict[str, bool]:
    return {
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    base = dict(value)
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _write_progress(root: Path, value: dict[str, Any]) -> None:
    atomic_dump_json(root / "materialization-progress.json", _seal(value))


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "provider_contract_published": report["provider_contract_published"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
