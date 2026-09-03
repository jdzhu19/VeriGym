#!/usr/bin/env python3
"""Materialize the v69 five-task schedule on isolated /data2-backed Docker storage."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
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

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV69Manifest,
    DeepSeekHarnessV71DindSuccessorManifest,
    HweOfflineTaskLock,
    load_v69_manifest,
    load_v71_dind_successor_manifest,
)
from verigym.hwe.materialization_preflight import (  # noqa: E402
    MaterializationHeadroomError,
    require_materialization_headroom,
)

IDENTITY = "deepseek-harness-hwe-v71-dind-zero-provider-successor-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V71_DIND_ZERO_PROVIDER"
SUCCESSOR_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v71_dind_zero_provider_successor_v1.json"
)
UPSTREAM_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)
PREDECESSOR_REPORT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v69-multitask-zero-provider-v1/zero-provider-report.json"
)
PREDECESSOR_AUDIT = _REPOSITORY / (
    "docs/audits/2026-09-03_deepseek-harness-v70-v69-capacity-stop.md"
)
ARCHIVE_ROOT = v69.ARCHIVE_ROOT
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v71-dind-zero-provider-successor-v1"
)
SCRATCH_ROOT = v69.SCRATCH_ROOT
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v71")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v71_dind_zero_provider_successor_v1.json",
    "docs/audits/2026-09-03_deepseek-harness-v70-v69-capacity-stop.md",
    "docs/audits/2026-09-03_deepseek-harness-v71-dind-materialization-authorization.md",
    "docs/hwe_deepseek_harness_collection.md",
    "docs/hwe_dind_runtime.md",
    "integrations/verigym-deepseek-harness/tests/test_v69_multitask_materialization.py",
    "integrations/verigym-deepseek-harness/tests/test_v71_dind_materialization.py",
    "scripts/materialize_hwe_deepseek_harness_v69.py",
    "scripts/materialize_hwe_deepseek_harness_v71_dind.py",
    "scripts/run_repository_rollout_dind_controller.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
    "tests/unit/test_rollout_dind_controller.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--successor-manifest", type=Path, default=SUCCESSOR_MANIFEST)
    parser.add_argument("--upstream-manifest", type=Path, default=UPSTREAM_MANIFEST)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument("--rg-binary", type=Path, default=v69.RG_BINARY)
    parser.add_argument("--rg-release-archive", type=Path, default=v69.RG_ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run one successor attempt and publish only a complete, cleaned contract."""

    _require_execution_boundary(arguments)
    successor = load_v71_dind_successor_manifest(
        v69._exact_file(  # noqa: SLF001
            arguments.successor_manifest,
            SUCCESSOR_MANIFEST,
            "successor manifest",
        )
    )
    upstream_path = v69._exact_file(  # noqa: SLF001
        arguments.upstream_manifest,
        UPSTREAM_MANIFEST,
        "upstream manifest",
    )
    upstream = load_v69_manifest(upstream_path)
    _validate_static_bindings(successor, upstream, upstream_path=upstream_path)
    source_commit = _require_clean_merged_main()
    archive_root = v69._exact_directory(  # noqa: SLF001
        arguments.archive_root,
        ARCHIVE_ROOT,
        "archive root",
    )
    rg_binary = v69._validated_tool(  # noqa: SLF001
        arguments.rg_binary,
        v69.RG_BINARY,
        v69.RG_SHA256,
        executable=True,
    )
    rg_archive = v69._validated_tool(  # noqa: SLF001
        arguments.rg_release_archive,
        v69.RG_ARCHIVE,
        v69.RG_ARCHIVE_SHA256,
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
    empty_home = root / "dind-empty-home"
    empty_home.mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v71_dind_progress_v1",
        "identity": IDENTITY,
        "successor_manifest_hash": successor.manifest_hash,
        "upstream_manifest_hash": upstream.manifest_hash,
        "predecessor_report_hash": successor.predecessor_report_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "completed_task_ids": [],
        "task_receipts": [],
        "headroom_preflight_hash": None,
        "dind_runtime_receipt_hash": None,
        "provider_contract_published": False,
        "provider_calls": 0,
        "model_process_count": 0,
        **_closed_training_flags(),
    }
    _write_progress(root, progress)
    dind_name: str | None = None
    cleanup_confirmed = False
    try:
        instances = v69._patch_preflight(  # noqa: SLF001
            upstream,
            archive_root=archive_root,
            root=root,
        )
        progress["status"] = "headroom_preflight"
        _write_progress(root, progress)
        _create_dind_backings(successor)
        try:
            headroom = require_materialization_headroom(
                control_root=Path("/"),
                docker_root=DIND_DATA_BACKING,
                scratch_root=v69._exact_directory(  # noqa: SLF001
                    SCRATCH_ROOT,
                    SCRATCH_ROOT,
                    "scratch root",
                ),
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
                "status": "isolated_dind_startup",
            }
        )
        _write_progress(root, progress)

        _validate_dind_image(successor)
        dind._create_bind_backed_volume(  # noqa: SLF001
            successor.dind_data_volume,
            owner=dind._DIND_OWNER,  # noqa: SLF001
            role="data",
            backing=DIND_DATA_BACKING,
        )
        dind._create_bind_backed_volume(  # noqa: SLF001
            successor.dind_socket_volume,
            owner=dind._DIND_OWNER,  # noqa: SLF001
            role="socket",
            backing=DIND_SOCKET_BACKING,
        )
        dind_name = f"verigym-dind-v71-{secrets.token_hex(10)}"
        metadata = dind._start_dind(  # noqa: SLF001
            name=dind_name,
            image_id=successor.dind_image_id,
            socket_volume=successor.dind_socket_volume,
            data_volume=successor.dind_data_volume,
            source_volume=None,
            scratch_volume=None,
            empty_home=empty_home,
            same_path_mounts=dind._same_path_mounts({root: "rw"}),  # noqa: SLF001
            startup_timeout_s=60,
        )
        _validate_outer_sidecar(dind_name, successor, root=root)
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        dind_receipt = _dind_runtime_receipt(successor, metadata=metadata)
        atomic_dump_json(root / "dind-runtime-receipt.json", dind_receipt)
        progress.update(
            {
                "dind_runtime_receipt_hash": dind_receipt["receipt_hash"],
                "status": "offline_materialization",
            }
        )
        _write_progress(root, progress)
        with _nested_docker(DIND_SOCKET_BACKING / "docker.sock"):
            for task_lock in upstream.primary_tasks:
                receipt = v69._materialize_task(  # noqa: SLF001
                    task_lock,
                    instance=instances[task_lock.task_id],
                    archive_root=archive_root,
                    rg_binary=rg_binary,
                    rg_archive=rg_archive,
                    root=root,
                    campaign_identity=IDENTITY,
                    command_tag_version="v71",
                )
                progress["completed_task_ids"].append(task_lock.task_id)
                progress["task_receipts"].append(receipt)
                _write_progress(root, progress)
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        if progress["completed_task_ids"] != [task.task_id for task in upstream.primary_tasks]:
            raise ConfigurationError("v71 did not complete its exact inherited primary schedule")

        if not dind._remove_container(dind_name):  # noqa: SLF001
            raise ConfigurationError("v71 isolated DinD daemon cleanup failed")
        dind_name = None
        if not dind._remove_volume(successor.dind_socket_volume):  # noqa: SLF001
            raise ConfigurationError("v71 isolated DinD socket-volume cleanup failed")
        _require_empty_socket_backing()
        dind._bind_backed_volume(  # noqa: SLF001
            successor.dind_data_volume,
            owner=dind._DIND_OWNER,  # noqa: SLF001
            role="data",
            backing=DIND_DATA_BACKING,
        )
        cleanup_confirmed = True
        contract = _provider_contract(
            successor,
            upstream,
            progress["task_receipts"],
            source_commit=source_commit,
            post_merge_main_run_id=arguments.post_merge_main_run_id,
            dind_runtime_receipt_hash=dind_receipt["receipt_hash"],
        )
        atomic_dump_json(root / "provider-contract.json", contract)
        progress.update(
            {
                "status": "completed_pending_independent_v72_audit",
                "dind_cleanup_confirmed": True,
                "provider_contract_published": True,
                "provider_contract_hash": contract["contract_hash"],
            }
        )
        _write_progress(root, progress)
        report = _seal(
            {
                **progress,
                "provider_execution_authorized": False,
                "next_required_identity": ("deepseek-harness-hwe-v72-v71-dind-result-audit-v1"),
            }
        )
        atomic_dump_json(root / "zero-provider-report.json", report)
        return report
    except (Exception, KeyboardInterrupt) as exc:
        cleanup_confirmed = _best_effort_cleanup(
            dind_name=dind_name,
            socket_volume=successor.dind_socket_volume,
        )
        stopped = _seal(
            {
                **progress,
                "status": "stopped_without_provider_contract",
                "stop_reason": type(exc).__name__,
                "provider_contract_published": False,
                "provider_execution_authorized": False,
                "dind_cleanup_confirmed": cleanup_confirmed,
                "raw_exception_persisted": False,
            }
        )
        _write_progress(root, stopped)
        atomic_dump_json(root / "zero-provider-report.json", stopped)
        raise


def _validate_static_bindings(
    successor: DeepSeekHarnessV71DindSuccessorManifest,
    upstream: DeepSeekHarnessV69Manifest,
    *,
    upstream_path: Path,
) -> None:
    if (
        v69._hash_file(upstream_path) != successor.upstream_manifest_sha256  # noqa: SLF001
        or upstream.manifest_hash != successor.upstream_manifest_hash
    ):
        raise ConfigurationError("v71 upstream v69 manifest binding changed")
    report_path = v69._exact_file(  # noqa: SLF001
        PREDECESSOR_REPORT,
        PREDECESSOR_REPORT,
        "predecessor report",
    )
    if v69._hash_file(report_path) != successor.predecessor_report_sha256:  # noqa: SLF001
        raise ConfigurationError("v71 predecessor report file changed")
    try:
        predecessor = json.loads(report_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v71 predecessor report is invalid") from exc
    if (
        predecessor.get("identity") != successor.predecessor_identity
        or predecessor.get("report_hash") != successor.predecessor_report_hash
        or predecessor.get("status") != "stopped_without_provider_contract"
        or predecessor.get("failure_stage") != "headroom_preflight"
        or predecessor.get("provider_contract_published") is not False
        or predecessor.get("provider_calls") != 0
        or predecessor.get("model_process_count") != 0
        or predecessor.get("completed_task_ids") != []
    ):
        raise ConfigurationError("v71 predecessor did not stop at the frozen pre-provider gate")
    if (
        v69._hash_file(PREDECESSOR_AUDIT)  # noqa: SLF001
        != successor.predecessor_audit_sha256
    ):
        raise ConfigurationError("v71 predecessor audit changed")
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            successor.predecessor_audit_commit,
            "HEAD",
        ],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v71 predecessor audit is not merged into the execution commit")


def _validate_dind_image(successor: DeepSeekHarnessV71DindSuccessorManifest) -> None:
    dind._dind_image(successor.dind_image_id)  # noqa: SLF001
    image = dind._inspect("image", successor.dind_image_id)  # noqa: SLF001
    repo_digests = image.get("RepoDigests")
    config = image.get("Config")
    environment = config.get("Env") if isinstance(config, dict) else None
    if (
        not isinstance(repo_digests, list)
        or f"docker@{successor.dind_repository_digest}" not in repo_digests
        or not isinstance(environment, list)
        or f"DOCKER_VERSION={successor.dind_server_version}" not in environment
    ):
        raise ConfigurationError("v71 DinD repository or version identity changed")


def _create_dind_backings(successor: DeepSeekHarnessV71DindSuccessorManifest) -> None:
    if (
        Path(successor.dind_data_backing) != DIND_DATA_BACKING
        or Path(successor.dind_socket_backing) != DIND_SOCKET_BACKING
        or DIND_PARENT.exists()
        or DIND_PARENT.is_symlink()
    ):
        raise ConfigurationError("v71 DinD backing identity must be new and exact")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    for path in (DIND_PARENT, DIND_DATA_BACKING, DIND_SOCKET_BACKING):
        path.chmod(0o700)


def _validate_outer_sidecar(
    name: str,
    successor: DeepSeekHarnessV71DindSuccessorManifest,
    *,
    root: Path,
) -> None:
    value = dind._inspect("container", name)  # noqa: SLF001
    host = value.get("HostConfig")
    config = value.get("Config")
    mounts = value.get("Mounts")
    if not isinstance(host, dict) or not isinstance(config, dict) or not isinstance(mounts, list):
        raise ConfigurationError("v71 outer DinD inspection is malformed")
    labels = config.get("Labels")
    environment = config.get("Env")
    by_destination = {item.get("Destination"): item for item in mounts if isinstance(item, dict)}
    data_mount = by_destination.get("/var/lib/docker")
    socket_mount = by_destination.get("/var/run")
    task_mount = by_destination.get(str(root))
    sentinel_mount = by_destination.get("/verigym-host-sentinel")
    expected_destinations = {
        "/var/lib/docker",
        "/var/run",
        str(root),
        "/verigym-host-sentinel",
    }
    if (
        host.get("Privileged") is not True
        or host.get("NetworkMode") != successor.outer_dind_network
        or host.get("Binds") is None
        or host.get("PortBindings") not in (None, {})
        or not isinstance(labels, dict)
        or labels.get("verigym.owner") != dind._DIND_OWNER  # noqa: SLF001
        or labels.get("verigym.role") != "daemon"
        or not isinstance(environment, list)
        or any(
            entry.partition("=")[0] in v69._PROVIDER_ENV_NAMES  # noqa: SLF001
            for entry in environment
            if isinstance(entry, str)
        )
        or set(by_destination) != expected_destinations
        or not isinstance(data_mount, dict)
        or data_mount.get("Type") != "volume"
        or data_mount.get("Name") != successor.dind_data_volume
        or not isinstance(socket_mount, dict)
        or socket_mount.get("Type") != "volume"
        or socket_mount.get("Name") != successor.dind_socket_volume
        or not isinstance(task_mount, dict)
        or task_mount.get("Type") != "bind"
        or task_mount.get("Source") != str(root)
        or not isinstance(sentinel_mount, dict)
        or sentinel_mount.get("Type") != "bind"
        or sentinel_mount.get("Source") != str(root / "dind-empty-home")
        or sentinel_mount.get("RW") is not False
        or "/var/run/docker.sock" in by_destination
    ):
        raise ConfigurationError("v71 outer DinD isolation controls changed")


def _dind_runtime_receipt(
    successor: DeepSeekHarnessV71DindSuccessorManifest,
    *,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v71_dind_runtime_receipt_v1",
        "identity": IDENTITY,
        "dind_image_id": successor.dind_image_id,
        "dind_repository_digest": successor.dind_repository_digest,
        "dind_server_version": successor.dind_server_version,
        "storage_driver": metadata.get("Driver"),
        "default_runtime": metadata.get("DefaultRuntime"),
        "docker_root_dir": metadata.get("DockerRootDir"),
        "data_volume": successor.dind_data_volume,
        "data_backing": successor.dind_data_backing,
        "socket_volume": successor.dind_socket_volume,
        "socket_backing": successor.dind_socket_backing,
        "outer_network": successor.outer_dind_network,
        "outer_privileged_sidecar_only": True,
        "host_docker_socket_mounted": False,
        "host_docker_root_used_for_task_layers": False,
        "task_and_verifier_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_command_output_persisted": False,
    }
    if (
        base["storage_driver"] != successor.dind_storage_driver
        or base["default_runtime"] != successor.dind_default_runtime
        or base["docker_root_dir"] != "/var/lib/docker"
    ):
        raise ConfigurationError("v71 isolated DinD metadata differs from policy")
    return {**base, "receipt_hash": content_hash(base)}


@contextmanager
def _nested_docker(socket: Path) -> Iterator[None]:
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v71 host Docker routing changed before nested execution")
    if socket.is_symlink() or not socket.exists() or not socket.is_socket():
        raise ConfigurationError("v71 nested Docker socket is unavailable or unsafe")
    os.environ["DOCKER_HOST"] = f"unix://{socket}"
    try:
        yield
    finally:
        os.environ.pop("DOCKER_HOST", None)


def _provider_contract(
    successor: DeepSeekHarnessV71DindSuccessorManifest,
    upstream: DeepSeekHarnessV69Manifest,
    receipts: list[dict[str, Any]],
    *,
    source_commit: str,
    post_merge_main_run_id: int,
    dind_runtime_receipt_hash: str,
) -> dict[str, Any]:
    if len(receipts) != len(upstream.primary_tasks):
        raise ConfigurationError("v71 refuses a partial provider contract")
    expected = [task.task_id for task in upstream.primary_tasks]
    if [receipt.get("task_id") for receipt in receipts] != expected:
        raise ConfigurationError("v71 provider contract task order changed")
    for receipt, task in zip(receipts, upstream.primary_tasks, strict=True):
        _require_eligible_task(receipt, task)
    if _HASH.fullmatch(dind_runtime_receipt_hash) is None:
        raise ConfigurationError("v71 DinD runtime receipt hash is invalid")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v71_dind_provider_contract_v1",
        "identity": IDENTITY,
        "successor_manifest_hash": successor.manifest_hash,
        "upstream_manifest_hash": upstream.manifest_hash,
        "predecessor_report_hash": successor.predecessor_report_hash,
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
        "dind_runtime_receipt_hash": dind_runtime_receipt_hash,
        "dind_image_id": successor.dind_image_id,
        "dind_data_volume": successor.dind_data_volume,
        "dind_data_backing": successor.dind_data_backing,
        "dind_cleanup_confirmed": True,
        "host_docker_root_used_for_task_layers": False,
        "verifier_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "partial_authorization_published": False,
        "provider_execution_authorized": False,
        "requires_independent_v72_audit": True,
        **_closed_training_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


def _require_eligible_task(receipt: dict[str, Any], task: HweOfflineTaskLock) -> None:
    if (
        receipt.get("base_failed") is not True
        or receipt.get("base_infrastructure_error") is not False
        or receipt.get("reference_passed") is not True
        or receipt.get("verifier_network") != "none"
        or receipt.get("provider_calls") != 0
        or receipt.get("agent_toolchain_id") != task.agent_toolchain_id
        or receipt.get("official_verifier_image") != task.official_verifier_image
    ):
        raise ConfigurationError("v71 task is not eligible for atomic publication")


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v71 requires a non-root host identity")
    if any(name in os.environ for name in v69._PROVIDER_ENV_NAMES):  # noqa: SLF001
        raise ConfigurationError("v71 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v71 requires the default host Docker connection")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v71 requires a positive post-merge main run ID")


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
            raise ConfigurationError("v71 required merged path is not tracked")
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
        raise ConfigurationError("v71 requires clean merged origin/main")
    return head


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink() or path != OUTPUT_ROOT:
        raise ConfigurationError("v71 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _require_empty_socket_backing() -> None:
    if DIND_SOCKET_BACKING.is_symlink() or not DIND_SOCKET_BACKING.is_dir():
        raise ConfigurationError("v71 DinD socket backing changed during cleanup")
    if next(DIND_SOCKET_BACKING.iterdir(), None) is not None:
        raise ConfigurationError("v71 DinD socket backing is not empty after cleanup")


def _best_effort_cleanup(*, dind_name: str | None, socket_volume: str | None) -> bool:
    container_clean = True
    volume_clean = True
    if dind_name is not None:
        existing = dind._run(["docker", "container", "inspect", dind_name], timeout_s=30)  # noqa: SLF001
        container_clean = existing.returncode != 0 or dind._remove_container(dind_name)  # noqa: SLF001
    if socket_volume is not None:
        existing = dind._run(  # noqa: SLF001
            ["docker", "volume", "inspect", socket_volume],
            timeout_s=30,
        )
        volume_clean = existing.returncode != 0 or dind._remove_volume(  # noqa: SLF001
            socket_volume
        )
    return container_clean and volume_clean


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
