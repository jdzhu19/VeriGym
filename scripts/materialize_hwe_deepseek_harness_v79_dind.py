#!/usr/bin/env python3
"""Retry after v77 with an exact PR-2017 runtime-baseline lock and fresh DinD storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
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

from verigym_hwe_bench.adapter import HweBenchSuite  # noqa: E402
from verigym_hwe_bench.models import ImageLockV2, repository_profile  # noqa: E402
from verigym_hwe_bench.prepare import load_selected_instances  # noqa: E402

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV69Manifest,
    DeepSeekHarnessV79DindSuccessorManifest,
    HweOfflineTaskLock,
    inspect_offline_image_archive,
    load_v69_manifest,
    load_v79_dind_successor_manifest,
)
from verigym.hwe.materialization_preflight import (  # noqa: E402
    MaterializationHeadroomError,
    require_materialization_headroom,
)
from verigym.schemas.suite import SuiteSourceConfig  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v79-dind-zero-provider-successor-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V79_DIND_ZERO_PROVIDER"
SUCCESSOR_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v79_dind_zero_provider_successor_v1.json"
)
UPSTREAM_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)
PREDECESSOR_REPORT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v77-dind-zero-provider-successor-v1/zero-provider-report.json"
)
PREDECESSOR_AUDIT = _REPOSITORY / (
    "docs/audits/2026-09-03_deepseek-harness-v78-v77-dind-materialization-stop.md"
)
PREDECESSOR_PR_2017_SOURCE_LOCK = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v77-dind-zero-provider-successor-v1/"
    "sources/pr-2017/image-lock.json"
)
ARCHIVE_ROOT = v69.ARCHIVE_ROOT
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v79-dind-zero-provider-successor-v1"
)
SCRATCH_ROOT = v69.SCRATCH_ROOT
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v79")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
MAX_COMMAND_DIAGNOSTIC_BYTES = 32 * 1024 * 1024
MAX_CLEANUP_OUTPUT_BYTES = 1024 * 1024
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CLEANUP_PATHS = (
    "/verigym-socket/docker.sock",
    "/verigym-socket/docker.pid",
    "/verigym-socket/docker",
    "/verigym-socket/containerd",
    "/verigym-socket/runc",
    "/verigym-socket/xtables.lock",
)
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v79_dind_zero_provider_successor_v1.json",
    "docs/audits/2026-09-03_deepseek-harness-v78-v77-dind-materialization-stop.md",
    "docs/audits/2026-09-03_deepseek-harness-v79-runtime-baseline-authorization.md",
    "docs/hwe_deepseek_harness_collection.md",
    "docs/hwe_dind_runtime.md",
    "integrations/verigym-hwe-bench/src/verigym_hwe_bench/models.py",
    "integrations/verigym-hwe-bench/src/verigym_hwe_bench/prepare.py",
    "integrations/verigym-hwe-bench/tests/test_prepare.py",
    "integrations/verigym-hwe-bench/tests/test_profiles.py",
    "integrations/verigym-deepseek-harness/tests/test_v69_multitask_materialization.py",
    "integrations/verigym-deepseek-harness/tests/test_v79_dind_materialization.py",
    "scripts/materialize_hwe_deepseek_harness_v69.py",
    "scripts/materialize_hwe_deepseek_harness_v79_dind.py",
    "scripts/run_repository_rollout_dind_controller.py",
    "scripts/scan_and_lock_cva6_hwe_command_image.py",
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
    """Run one fresh successor attempt and publish only a complete, cleaned contract."""

    _require_execution_boundary(arguments)
    successor = load_v79_dind_successor_manifest(
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
        "command-diagnostics",
        "image-receipts",
        "image-locks",
        "patch-compatibility",
        "qualification",
        "security-scans",
        "scan-workspaces",
        "source-image-locks",
        "sources",
    ):
        (root / directory).mkdir(mode=0o700)
    empty_home = root / "dind-empty-home"
    empty_home.mkdir(mode=0o700)
    scan_workspace = _scanner_workspace(successor, root=root)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v79_dind_progress_v1",
        "identity": IDENTITY,
        "successor_manifest_hash": successor.manifest_hash,
        "upstream_manifest_hash": upstream.manifest_hash,
        "predecessor_report_hash": successor.predecessor_report_hash,
        "predecessor_audit_sha256": successor.predecessor_audit_sha256,
        "scanner_workspace_policy": successor.scanner_workspace_policy,
        "scanner_workspace_relative_path": successor.scanner_workspace_relative_path,
        "source_profile_repair": successor.source_profile_repair,
        "cva6_repository_profile_id": successor.cva6_repository_profile_id,
        "cva6_repository_profile_hash": successor.cva6_repository_profile_hash,
        "cva6_workspace_tool_bridge_exclusion": (successor.cva6_workspace_tool_bridge_exclusion),
        "escaping_symlink_policy": successor.escaping_symlink_policy,
        "runtime_baseline_repair": successor.runtime_baseline_repair,
        "runtime_baseline_policy": successor.runtime_baseline_policy,
        "runtime_base_commit_overrides": successor.runtime_base_commit_overrides,
        "tasks_without_runtime_override_match_dataset_base": (
            successor.tasks_without_runtime_override_match_dataset_base
        ),
        "predecessor_prepared_source_image_lock_sha256": (
            successor.predecessor_prepared_source_image_lock_sha256
        ),
        "predecessor_pr_2017_source_hash": successor.predecessor_pr_2017_source_hash,
        "predecessor_pr_2017_task_bundle_hash": (successor.predecessor_pr_2017_task_bundle_hash),
        "pr_2711_offline_archive_receipt_hash": (successor.pr_2711_offline_archive_receipt_hash),
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "completed_task_ids": [],
        "task_receipts": [],
        "headroom_preflight_hash": None,
        "dind_runtime_receipt_hash": None,
        "dind_cleanup_receipt_hash": None,
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
        dind_name = f"verigym-dind-v79-{secrets.token_hex(10)}"
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
                diagnostic_path = root / "command-diagnostics" / f"pr-{task_lock.pr_number}.json"

                def build_command_runner(
                    command: list[str],
                    timeout: int,
                    *,
                    output: Path = diagnostic_path,
                ) -> dict[str, Any]:
                    return _content_free_bounded_command(
                        command,
                        timeout=timeout,
                        receipt_path=output,
                    )

                def source_binding_runner(
                    source: Path,
                    task: HweOfflineTaskLock,
                ) -> dict[str, str]:
                    return _source_binding(
                        source,
                        task,
                        successor=successor,
                        upstream=upstream,
                    )

                receipt = v69._materialize_task(  # noqa: SLF001
                    task_lock,
                    instance=instances[task_lock.task_id],
                    archive_root=archive_root,
                    rg_binary=rg_binary,
                    rg_archive=rg_archive,
                    root=root,
                    campaign_identity=IDENTITY,
                    command_tag_version="v79",
                    build_command_runner=build_command_runner,
                    source_binding_runner=source_binding_runner,
                    scan_scratch_parent=scan_workspace,
                )
                receipt = _runtime_bound_task_receipt(receipt, task_lock, successor=successor)
                _require_empty_scan_workspace(scan_workspace)
                progress["completed_task_ids"].append(task_lock.task_id)
                progress["task_receipts"].append(receipt)
                _write_progress(root, progress)
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        if progress["completed_task_ids"] != [task.task_id for task in upstream.primary_tasks]:
            raise ConfigurationError("v79 did not complete its exact inherited primary schedule")

        if not dind._remove_container(dind_name):  # noqa: SLF001
            raise ConfigurationError("v79 isolated DinD daemon cleanup failed")
        dind_name = None
        cleanup_receipt = _clean_socket_volume(successor, root=root)
        progress["dind_cleanup_receipt_hash"] = cleanup_receipt["receipt_hash"]
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
            dind_cleanup_receipt_hash=cleanup_receipt["receipt_hash"],
        )
        atomic_dump_json(root / "provider-contract.json", contract)
        progress.update(
            {
                "status": "completed_pending_independent_v80_audit",
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
                "next_required_identity": "deepseek-harness-hwe-v80-v79-dind-result-audit-v1",
            }
        )
        atomic_dump_json(root / "zero-provider-report.json", report)
        return report
    except (Exception, KeyboardInterrupt) as exc:
        cleanup_confirmed, cleanup_hash = _best_effort_cleanup(
            dind_name=dind_name,
            successor=successor,
            root=root,
        )
        stopped = _seal(
            {
                **progress,
                "status": "stopped_without_provider_contract",
                "stop_reason": type(exc).__name__,
                "provider_contract_published": False,
                "provider_execution_authorized": False,
                "dind_cleanup_confirmed": cleanup_confirmed,
                "dind_cleanup_receipt_hash": (
                    cleanup_hash or progress.get("dind_cleanup_receipt_hash")
                ),
                "raw_exception_persisted": False,
            }
        )
        _write_progress(root, stopped)
        atomic_dump_json(root / "zero-provider-report.json", stopped)
        raise


def _content_free_bounded_command(
    command: list[str],
    *,
    timeout: int,
    receipt_path: Path,
    maximum_output_bytes: int = MAX_COMMAND_DIAGNOSTIC_BYTES,
) -> dict[str, Any]:
    """Run one trusted build command while persisting only bounded output metadata."""

    if (
        timeout <= 0
        or maximum_output_bytes <= 0
        or receipt_path.exists()
        or receipt_path.is_symlink()
    ):
        raise ConfigurationError("v79 build-command diagnostic boundary is invalid")
    stdout = b""
    stderr = b""
    returncode: int | None = None
    timed_out = False
    spawn_succeeded = False
    try:
        result = subprocess.run(
            command,
            cwd=_REPOSITORY,
            check=False,
            capture_output=True,
            shell=False,
            timeout=timeout,
        )
        stdout = result.stdout
        stderr = result.stderr
        returncode = result.returncode
        spawn_succeeded = True
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        timed_out = True
        spawn_succeeded = True
    except OSError:
        pass
    within_bound = len(stdout) <= maximum_output_bytes and len(stderr) <= maximum_output_bytes
    passed = spawn_succeeded and not timed_out and returncode == 0 and within_bound
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_content_free_bounded_command_diagnostic_v1",
        "identity": IDENTITY,
        "command_role": "task_specific_command_image_build",
        "executable_name": Path(command[0]).name if command else None,
        "argument_count": len(command),
        "timeout_seconds": timeout,
        "maximum_output_bytes": maximum_output_bytes,
        "spawn_succeeded": spawn_succeeded,
        "timed_out": timed_out,
        "returncode": returncode,
        "stdout_bytes": len(stdout),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_bytes": len(stderr),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "output_within_bound": within_bound,
        "diagnostic_passed": passed,
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "provider_values_persisted": False,
    }
    receipt = {**base, "diagnostic_hash": content_hash(base)}
    atomic_dump_json(receipt_path, receipt)
    if not passed:
        raise ConfigurationError("v79 bounded build command failed")
    return receipt


def _source_binding(
    source: Path,
    task: HweOfflineTaskLock,
    *,
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    upstream: DeepSeekHarnessV69Manifest,
) -> dict[str, str]:
    """Bind the public dataset base and digest-locked runtime base separately."""

    lock_path = source / "image-lock.json"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ConfigurationError("v79 prepared source lacks a safe image lock")
    lock = ImageLockV2.model_validate_json(lock_path.read_bytes())
    if len(lock.entries) != 1 or lock.official_dataset_sha256 != task.dataset_sha256:
        raise ConfigurationError("v79 prepared source image-lock inventory changed")
    entry = lock.entries[0]
    dataset = v69._contained_file(  # noqa: SLF001
        ARCHIVE_ROOT,
        task.dataset_relpath,
        512 * 1024 * 1024,
    )
    selected = load_selected_instances(dataset, {task.instance_id})
    if (
        v69._hash_file(dataset) != task.dataset_sha256  # noqa: SLF001
        or v69._selected_row_hash(dataset, task.instance_id)  # noqa: SLF001
        != task.selected_row_sha256
        or len(selected) != 1
    ):
        raise ConfigurationError("v79 prepared source public record inventory changed")
    instance = selected[0]
    suite = HweBenchSuite().with_source(
        SuiteSourceConfig(source_root=source, variant="repo-repair-v1")
    )
    references = list(suite.discover())
    if len(references) != 1:
        raise ConfigurationError("v79 prepared source exposed multiple tasks")
    loaded = suite.load_task(references[0])
    source_image_lock_sha256 = hash_bytes(lock_path.read_bytes())
    runtime_base_commit = _expected_runtime_base_commit(task, successor=successor)
    profile = repository_profile(instance.repository_id)
    if (
        loaded.id != task.task_id
        or instance.instance_id != task.instance_id
        or instance.base_commit != task.source_commit
        or hash_bytes(instance.fix_patch.encode("utf-8")) != entry.reference_patch_hash
        or entry.instance_id != task.instance_id
        or entry.image_reference != task.registry_reference
        or entry.image_id != task.official_verifier_image
        or entry.manifest_digest != task.registry_manifest_digest
        or entry.base_commit != runtime_base_commit
        or entry.repository_profile_hash != profile.profile_hash
        or loaded.source.commit != runtime_base_commit
        or loaded.source.content_hash != entry.repository_hash
    ):
        raise ConfigurationError("v79 prepared source binding changed")
    _require_runtime_baseline_evidence(
        successor,
        upstream,
        task,
        runtime_base_commit=entry.base_commit,
        source_hash=entry.repository_hash,
        source_image_lock_sha256=source_image_lock_sha256,
        task_bundle_hash=entry.task_bundle_hash,
    )
    return {
        "task_hash": content_hash(loaded),
        "source_hash": entry.repository_hash,
        "source_image_lock_sha256": source_image_lock_sha256,
        "runtime_base_commit": runtime_base_commit,
    }


def _expected_runtime_base_commit(
    task: HweOfflineTaskLock,
    *,
    successor: DeepSeekHarnessV79DindSuccessorManifest,
) -> str:
    return successor.runtime_base_commit_overrides.get(task.task_id, task.source_commit)


def _require_runtime_baseline_evidence(
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    upstream: DeepSeekHarnessV69Manifest,
    task: HweOfflineTaskLock,
    *,
    runtime_base_commit: str,
    source_hash: str,
    source_image_lock_sha256: str,
    task_bundle_hash: str,
) -> None:
    tasks = {item.task_id: item for item in upstream.primary_tasks}
    expected_runtime = _expected_runtime_base_commit(task, successor=successor)
    overridden = task.task_id in successor.runtime_base_commit_overrides
    if (
        tasks.get(task.task_id) != task
        or runtime_base_commit != expected_runtime
        or (not overridden and runtime_base_commit != task.source_commit)
    ):
        raise ConfigurationError("v79 runtime baseline binding changed")
    if overridden and (
        task.task_id != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017"
        or task.source_commit != "90d780eb14bb99624ad9a377b5140f1781647a33"
        or runtime_base_commit != "d87707a81fe8926dda2deff844797a491811983a"
        or source_hash != successor.predecessor_pr_2017_source_hash
        or source_image_lock_sha256 != successor.predecessor_prepared_source_image_lock_sha256
        or task_bundle_hash != successor.predecessor_pr_2017_task_bundle_hash
    ):
        raise ConfigurationError("v79 PR-2017 runtime baseline evidence changed")


def _runtime_bound_task_receipt(
    receipt: dict[str, Any],
    task: HweOfflineTaskLock,
    *,
    successor: DeepSeekHarnessV79DindSuccessorManifest,
) -> dict[str, Any]:
    base = dict(receipt)
    observed_hash = base.pop("task_receipt_hash", None)
    if observed_hash != content_hash(base) or base.get("source_commit") != task.source_commit:
        raise ConfigurationError("v79 inherited task receipt changed before runtime binding")
    base.update(
        {
            "dataset_base_commit": task.source_commit,
            "runtime_base_commit": _expected_runtime_base_commit(task, successor=successor),
            "runtime_base_commit_override_applied": (
                task.task_id in successor.runtime_base_commit_overrides
            ),
            "runtime_baseline_policy": successor.runtime_baseline_policy,
        }
    )
    return {**base, "task_receipt_hash": content_hash(base)}


def _validate_static_bindings(
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    upstream: DeepSeekHarnessV69Manifest,
    *,
    upstream_path: Path,
) -> None:
    if (
        v69._hash_file(upstream_path) != successor.upstream_manifest_sha256  # noqa: SLF001
        or upstream.manifest_hash != successor.upstream_manifest_hash
    ):
        raise ConfigurationError("v79 upstream v69 manifest binding changed")
    report_path = v69._exact_file(  # noqa: SLF001
        PREDECESSOR_REPORT,
        PREDECESSOR_REPORT,
        "predecessor report",
    )
    if v69._hash_file(report_path) != successor.predecessor_report_sha256:  # noqa: SLF001
        raise ConfigurationError("v79 predecessor report file changed")
    try:
        predecessor = json.loads(report_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v79 predecessor report is invalid") from exc
    if (
        predecessor.get("identity") != successor.predecessor_identity
        or predecessor.get("report_hash") != successor.predecessor_report_hash
        or predecessor.get("status") != "stopped_without_provider_contract"
        or predecessor.get("stop_reason") != "ConfigurationError"
        or predecessor.get("provider_contract_published") is not False
        or predecessor.get("provider_calls") != 0
        or predecessor.get("model_process_count") != 0
        or predecessor.get("completed_task_ids")
        != [task.task_id for task in upstream.primary_tasks[:3]]
        or predecessor.get("source_profile_repair") != successor.source_profile_repair
        or predecessor.get("cva6_repository_profile_hash") != successor.cva6_repository_profile_hash
        or predecessor.get("dind_cleanup_confirmed") is not True
        or predecessor.get("raw_exception_persisted") is not False
    ):
        raise ConfigurationError("v79 predecessor did not stop at the frozen pre-provider gate")
    if v69._hash_file(PREDECESSOR_AUDIT) != successor.predecessor_audit_sha256:  # noqa: SLF001
        raise ConfigurationError("v79 predecessor audit changed")
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
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v79 predecessor audit is not merged into the execution commit")
    if (
        len({str(successor.retired_dind_data_volume), str(successor.dind_data_volume)}) != 2
        or len({str(successor.retired_dind_data_backing), str(successor.dind_data_backing)}) != 2
        or successor.command_diagnostic_max_bytes != MAX_COMMAND_DIAGNOSTIC_BYTES
        or successor.scanner_workspace_policy != "successor-output-root-only-v1"
        or successor.scanner_workspace_relative_path != "scan-workspaces"
    ):
        raise ConfigurationError("v79 clean-room DinD identity changed")
    _validate_source_profile(successor)
    _validate_runtime_baseline_policy(successor, upstream)


def _validate_source_profile(successor: DeepSeekHarnessV79DindSuccessorManifest) -> None:
    cva6_profile = repository_profile("openhwgroup/cva6")
    if (
        successor.source_profile_repair != "cva6-task-image-tool-bridge-exclusion-v1"
        or successor.cva6_repository_profile_id != cva6_profile.profile_id
        or successor.cva6_repository_profile_hash != cva6_profile.profile_hash
        or successor.cva6_workspace_tool_bridge_exclusion != ".hwe_tools"
        or cva6_profile.workspace_excluded_paths
        != [".hwe_tools", "verif/core-v-verif/vendor/riscv/riscv-isa-sim/build"]
        or successor.escaping_symlink_policy != "reject-unlisted-v1"
    ):
        raise ConfigurationError("v79 CVA6 source-profile repair identity changed")


def _validate_runtime_baseline_policy(
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    upstream: DeepSeekHarnessV69Manifest,
) -> None:
    tasks = {task.task_id: task for task in upstream.primary_tasks}
    pr_2017_id = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017"
    pr_2711_id = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711"
    pr_2017 = tasks.get(pr_2017_id)
    pr_2711 = tasks.get(pr_2711_id)
    cva6_profile = repository_profile("openhwgroup/cva6")
    expected_override = {pr_2017_id: "d87707a81fe8926dda2deff844797a491811983a"}
    if (
        successor.runtime_baseline_repair != "pr-2017-digest-locked-runtime-marker-v1"
        or successor.runtime_baseline_policy != "exact-task-override-otherwise-dataset-base-v1"
        or successor.runtime_base_commit_overrides != expected_override
        or successor.tasks_without_runtime_override_match_dataset_base is not True
        or pr_2017 is None
        or pr_2017.source_commit != "90d780eb14bb99624ad9a377b5140f1781647a33"
        or pr_2711 is None
        or pr_2711.source_commit != "5518a41c08a1949c606d54b9ac631e8f7635e7f3"
        or cva6_profile.baseline_identity_policy != "digest_locked_runtime_marker"
    ):
        raise ConfigurationError("v79 runtime baseline policy identity changed")

    predecessor_lock_path = v69._exact_file(  # noqa: SLF001
        PREDECESSOR_PR_2017_SOURCE_LOCK,
        PREDECESSOR_PR_2017_SOURCE_LOCK,
        "predecessor PR-2017 source image lock",
    )
    if (
        v69._hash_file(predecessor_lock_path)  # noqa: SLF001
        != successor.predecessor_prepared_source_image_lock_sha256
    ):
        raise ConfigurationError("v79 predecessor PR-2017 source image lock changed")
    lock = ImageLockV2.model_validate_json(predecessor_lock_path.read_bytes())
    if len(lock.entries) != 1:
        raise ConfigurationError("v79 predecessor PR-2017 source image lock inventory changed")
    entry = lock.entries[0]
    if (
        lock.official_dataset_sha256 != pr_2017.dataset_sha256
        or entry.instance_id != pr_2017.instance_id
        or entry.base_commit != expected_override[pr_2017_id]
        or entry.image_id != pr_2017.official_verifier_image
        or entry.manifest_digest != pr_2017.registry_manifest_digest
        or entry.repository_profile_hash != successor.cva6_repository_profile_hash
        or entry.repository_hash != successor.predecessor_pr_2017_source_hash
        or entry.task_bundle_hash != successor.predecessor_pr_2017_task_bundle_hash
    ):
        raise ConfigurationError("v79 predecessor PR-2017 runtime evidence changed")

    pr_2711_archive = inspect_offline_image_archive(pr_2711, archive_root=ARCHIVE_ROOT)
    if (
        pr_2711_archive.get("receipt_hash") != successor.pr_2711_offline_archive_receipt_hash
        or pr_2711_archive.get("registry_accessed") is not False
        or pr_2711_archive.get("partial_archive_used") is not False
    ):
        raise ConfigurationError("v79 PR-2711 offline archive evidence changed")


def _validate_dind_image(successor: DeepSeekHarnessV79DindSuccessorManifest) -> None:
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
        raise ConfigurationError("v79 DinD repository or version identity changed")


def _create_dind_backings(successor: DeepSeekHarnessV79DindSuccessorManifest) -> None:
    if (
        Path(successor.dind_data_backing) != DIND_DATA_BACKING
        or Path(successor.dind_socket_backing) != DIND_SOCKET_BACKING
        or DIND_PARENT.exists()
        or DIND_PARENT.is_symlink()
    ):
        raise ConfigurationError("v79 DinD backing identity must be new and exact")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    for path in (DIND_PARENT, DIND_DATA_BACKING, DIND_SOCKET_BACKING):
        path.chmod(0o700)


def _validate_outer_sidecar(
    name: str,
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    *,
    root: Path,
) -> None:
    value = dind._inspect("container", name)  # noqa: SLF001
    host = value.get("HostConfig")
    config = value.get("Config")
    mounts = value.get("Mounts")
    if not isinstance(host, dict) or not isinstance(config, dict) or not isinstance(mounts, list):
        raise ConfigurationError("v79 outer DinD inspection is malformed")
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
        raise ConfigurationError("v79 outer DinD isolation controls changed")


def _dind_runtime_receipt(
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    *,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v79_dind_runtime_receipt_v1",
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
        "retired_v77_data_volume_reused": False,
        "source_profile_repair": successor.source_profile_repair,
        "cva6_repository_profile_id": successor.cva6_repository_profile_id,
        "cva6_repository_profile_hash": successor.cva6_repository_profile_hash,
        "cva6_workspace_tool_bridge_exclusion": (successor.cva6_workspace_tool_bridge_exclusion),
        "escaping_symlink_policy": successor.escaping_symlink_policy,
        "runtime_baseline_repair": successor.runtime_baseline_repair,
        "runtime_baseline_policy": successor.runtime_baseline_policy,
        "runtime_base_commit_overrides": successor.runtime_base_commit_overrides,
        "tasks_without_runtime_override_match_dataset_base": (
            successor.tasks_without_runtime_override_match_dataset_base
        ),
        "task_and_verifier_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_command_output_persisted": False,
        "scanner_workspace_policy": successor.scanner_workspace_policy,
        "scanner_workspace_relative_path": successor.scanner_workspace_relative_path,
    }
    if (
        base["storage_driver"] != successor.dind_storage_driver
        or base["default_runtime"] != successor.dind_default_runtime
        or base["docker_root_dir"] != "/var/lib/docker"
    ):
        raise ConfigurationError("v79 isolated DinD metadata differs from policy")
    return {**base, "receipt_hash": content_hash(base)}


@contextmanager
def _nested_docker(socket: Path) -> Iterator[None]:
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v79 host Docker routing changed before nested execution")
    if socket.is_symlink() or not socket.exists() or not socket.is_socket():
        raise ConfigurationError("v79 nested Docker socket is unavailable or unsafe")
    os.environ["DOCKER_HOST"] = f"unix://{socket}"
    try:
        yield
    finally:
        os.environ.pop("DOCKER_HOST", None)


def _scanner_workspace(
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    *,
    root: Path,
) -> Path:
    workspace = root / successor.scanner_workspace_relative_path
    expected = root / "scan-workspaces"
    if (
        successor.scanner_workspace_policy != "successor-output-root-only-v1"
        or workspace != expected
        or workspace.is_symlink()
        or not workspace.is_dir()
        or workspace.resolve(strict=True) != expected.resolve(strict=True)
    ):
        raise ConfigurationError("v79 scanner workspace escaped its successor output root")
    metadata = workspace.stat()
    if (
        metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ConfigurationError("v79 scanner workspace identity or mode changed")
    _require_empty_scan_workspace(workspace)
    return workspace


def _require_empty_scan_workspace(workspace: Path) -> None:
    if workspace.is_symlink() or not workspace.is_dir():
        raise ConfigurationError("v79 scanner workspace cleanup was not confirmed")
    metadata = workspace.stat()
    if (
        metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or any(workspace.iterdir())
    ):
        raise ConfigurationError("v79 scanner workspace cleanup was not confirmed")


def _clean_socket_volume(
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    """Clear the exact transient volume and verify its bind backing before removal."""

    dind._bind_backed_volume(  # noqa: SLF001
        successor.dind_socket_volume,
        owner=dind._DIND_OWNER,  # noqa: SLF001
        role="socket",
        backing=DIND_SOCKET_BACKING,
    )
    name = f"verigym-dind-v79-socket-cleanup-{secrets.token_hex(10)}"
    script = (
        "rm -rf -- "
        + " ".join(_CLEANUP_PATHS)
        + f"; chown {os.getuid()}:{os.getgid()} /verigym-socket"
        + "; chmod 0700 /verigym-socket"
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--label",
        f"verigym.owner={dind._DIND_OWNER}",  # noqa: SLF001
        "--label",
        "verigym.role=socket_cleanup",
        "--network",
        "none",
        "--read-only",
        "--user",
        "0:0",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "CHOWN",
        "--cap-add",
        "DAC_OVERRIDE",
        "--cap-add",
        "FOWNER",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "0.25",
        "--volume",
        f"{successor.dind_socket_volume}:/verigym-socket:rw",
        "--entrypoint",
        "/bin/sh",
        successor.dind_image_id,
        "-euc",
        script,
    ]
    completed = dind._run(command, timeout_s=60)  # noqa: SLF001
    output_bounded = (
        len(completed.stdout) <= MAX_CLEANUP_OUTPUT_BYTES
        and len(completed.stderr) <= MAX_CLEANUP_OUTPUT_BYTES
    )
    removed_container = (
        dind._run(["docker", "container", "inspect", name], timeout_s=30).returncode != 0  # noqa: SLF001
    )
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v79_socket_cleanup_receipt_v1",
        "identity": IDENTITY,
        "strategy": successor.socket_cleanup_strategy,
        "socket_volume": successor.dind_socket_volume,
        "socket_backing": successor.dind_socket_backing,
        "cleanup_image_id": successor.dind_image_id,
        "network": "none",
        "read_only_root": True,
        "user": "0:0",
        "cap_drop": ["ALL"],
        "cap_add": ["CHOWN", "DAC_OVERRIDE", "FOWNER"],
        "no_new_privileges": True,
        "mount_count": 1,
        "known_cleanup_paths": list(_CLEANUP_PATHS),
        "returncode": completed.returncode,
        "stdout_bytes": len(completed.stdout),
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_bytes": len(completed.stderr),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
        "output_within_bound": output_bounded,
        "raw_output_persisted": False,
        "cleanup_container_removed": removed_container,
        "socket_volume_removed": False,
        "socket_backing_empty": False,
        "socket_backing_identity_restored": False,
        "cleanup_confirmed": False,
    }
    if completed.returncode != 0 or not output_bounded or not removed_container:
        _write_cleanup_attempt(root, base)
        raise ConfigurationError("v79 socket cleanup container failed")
    if not dind._remove_volume(successor.dind_socket_volume):  # noqa: SLF001
        _write_cleanup_attempt(root, base)
        raise ConfigurationError("v79 isolated DinD socket-volume cleanup failed")
    base["socket_volume_removed"] = True
    try:
        _require_empty_socket_backing()
    except ConfigurationError:
        _write_cleanup_attempt(root, base)
        raise
    base.update(
        {
            "socket_backing_empty": True,
            "socket_backing_identity_restored": True,
            "cleanup_confirmed": True,
        }
    )
    receipt = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "dind-cleanup-receipt.json", receipt)
    return receipt


def _write_cleanup_attempt(root: Path, base: dict[str, Any]) -> None:
    receipt = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "dind-cleanup-attempt.json", receipt)


def _require_empty_socket_backing() -> None:
    if DIND_SOCKET_BACKING.is_symlink() or not DIND_SOCKET_BACKING.is_dir():
        raise ConfigurationError("v79 DinD socket backing changed during cleanup")
    metadata = DIND_SOCKET_BACKING.stat()
    if (
        next(DIND_SOCKET_BACKING.iterdir(), None) is not None
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
    ):
        raise ConfigurationError("v79 DinD socket backing cleanup was not confirmed")


def _provider_contract(
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    upstream: DeepSeekHarnessV69Manifest,
    receipts: list[dict[str, Any]],
    *,
    source_commit: str,
    post_merge_main_run_id: int,
    dind_runtime_receipt_hash: str,
    dind_cleanup_receipt_hash: str,
) -> dict[str, Any]:
    if len(receipts) != len(upstream.primary_tasks):
        raise ConfigurationError("v79 refuses a partial provider contract")
    expected = [task.task_id for task in upstream.primary_tasks]
    if [receipt.get("task_id") for receipt in receipts] != expected:
        raise ConfigurationError("v79 provider contract task order changed")
    for receipt, task in zip(receipts, upstream.primary_tasks, strict=True):
        _require_eligible_task(receipt, task, successor=successor)
    if (
        _HASH.fullmatch(dind_runtime_receipt_hash) is None
        or _HASH.fullmatch(dind_cleanup_receipt_hash) is None
    ):
        raise ConfigurationError("v79 DinD receipt hash is invalid")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v79_dind_provider_contract_v1",
        "identity": IDENTITY,
        "successor_manifest_hash": successor.manifest_hash,
        "upstream_manifest_hash": upstream.manifest_hash,
        "predecessor_report_hash": successor.predecessor_report_hash,
        "predecessor_audit_sha256": successor.predecessor_audit_sha256,
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
        "all_build_commands_have_content_free_diagnostics": True,
        "dind_runtime_receipt_hash": dind_runtime_receipt_hash,
        "dind_cleanup_receipt_hash": dind_cleanup_receipt_hash,
        "dind_image_id": successor.dind_image_id,
        "dind_data_volume": successor.dind_data_volume,
        "dind_data_backing": successor.dind_data_backing,
        "dind_cleanup_confirmed": True,
        "retired_v77_data_volume_reused": False,
        "scanner_workspace_policy": successor.scanner_workspace_policy,
        "scanner_workspace_relative_path": successor.scanner_workspace_relative_path,
        "scanner_workspace_cleanup_confirmed": True,
        "source_profile_repair": successor.source_profile_repair,
        "cva6_repository_profile_id": successor.cva6_repository_profile_id,
        "cva6_repository_profile_hash": successor.cva6_repository_profile_hash,
        "cva6_workspace_tool_bridge_exclusion": (successor.cva6_workspace_tool_bridge_exclusion),
        "escaping_symlink_policy": successor.escaping_symlink_policy,
        "runtime_baseline_repair": successor.runtime_baseline_repair,
        "runtime_baseline_policy": successor.runtime_baseline_policy,
        "runtime_base_commit_overrides": successor.runtime_base_commit_overrides,
        "tasks_without_runtime_override_match_dataset_base": (
            successor.tasks_without_runtime_override_match_dataset_base
        ),
        "predecessor_prepared_source_image_lock_sha256": (
            successor.predecessor_prepared_source_image_lock_sha256
        ),
        "predecessor_pr_2017_source_hash": successor.predecessor_pr_2017_source_hash,
        "predecessor_pr_2017_task_bundle_hash": (successor.predecessor_pr_2017_task_bundle_hash),
        "pr_2711_offline_archive_receipt_hash": (successor.pr_2711_offline_archive_receipt_hash),
        "host_docker_root_used_for_task_layers": False,
        "verifier_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "partial_authorization_published": False,
        "provider_execution_authorized": False,
        "requires_independent_v80_audit": True,
        **_closed_training_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


def _require_eligible_task(
    receipt: dict[str, Any],
    task: HweOfflineTaskLock,
    *,
    successor: DeepSeekHarnessV79DindSuccessorManifest,
) -> None:
    receipt_without_hash = dict(receipt)
    observed_hash = receipt_without_hash.pop("task_receipt_hash", None)
    expected_runtime_base_commit = _expected_runtime_base_commit(task, successor=successor)
    override_applied = task.task_id in successor.runtime_base_commit_overrides
    if (
        not isinstance(observed_hash, str)
        or _HASH.fullmatch(observed_hash) is None
        or observed_hash != content_hash(receipt_without_hash)
        or receipt.get("task_id") != task.task_id
        or receipt.get("source_commit") != task.source_commit
        or receipt.get("dataset_base_commit") != task.source_commit
        or receipt.get("runtime_base_commit") != expected_runtime_base_commit
        or receipt.get("runtime_base_commit_override_applied") is not override_applied
        or receipt.get("runtime_baseline_policy") != successor.runtime_baseline_policy
        or receipt.get("base_failed") is not True
        or receipt.get("base_infrastructure_error") is not False
        or receipt.get("reference_passed") is not True
        or receipt.get("verifier_network") != "none"
        or receipt.get("provider_calls") != 0
        or receipt.get("model_process_count") != 0
        or receipt.get("agent_toolchain_id") != task.agent_toolchain_id
        or receipt.get("official_verifier_image") != task.official_verifier_image
        or not isinstance(receipt.get("command_diagnostic_hash"), str)
        or _HASH.fullmatch(receipt["command_diagnostic_hash"]) is None
    ):
        raise ConfigurationError("v79 task is not eligible for atomic publication")


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v79 requires a non-root host identity")
    if any(name in os.environ for name in v69._PROVIDER_ENV_NAMES):  # noqa: SLF001
        raise ConfigurationError("v79 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v79 requires the default host Docker connection")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v79 requires a positive post-merge main run ID")


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
            raise ConfigurationError("v79 required merged path is not tracked")
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
        raise ConfigurationError("v79 requires clean merged origin/main")
    return head


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink() or path != OUTPUT_ROOT:
        raise ConfigurationError("v79 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _best_effort_cleanup(
    *,
    dind_name: str | None,
    successor: DeepSeekHarnessV79DindSuccessorManifest,
    root: Path,
) -> tuple[bool, str | None]:
    try:
        if dind_name is not None:
            existing = dind._run(  # noqa: SLF001
                ["docker", "container", "inspect", dind_name],
                timeout_s=30,
            )
            if existing.returncode == 0 and not dind._remove_container(dind_name):  # noqa: SLF001
                return False, None
        volume = dind._run(  # noqa: SLF001
            ["docker", "volume", "inspect", successor.dind_socket_volume],
            timeout_s=30,
        )
        if volume.returncode == 0:
            receipt = _clean_socket_volume(successor, root=root)
            return True, receipt["receipt_hash"]
        _require_empty_socket_backing()
        return True, None
    except Exception:
        return False, None


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
