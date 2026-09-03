#!/usr/bin/env python3
"""Materialize the v90 five-task zero-provider scaffold on fresh /data2 storage."""

from __future__ import annotations

import argparse
import copy
import json
import os
import secrets
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

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v79_dind as v79  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v81_execution_scaffold as v81,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v83_controller_tag_successor as v83,
)
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV69Manifest,
    DeepSeekHarnessV79DindSuccessorManifest,
    DeepSeekHarnessV90FreshScaffoldManifest,
    HweOfflineTaskLock,
    load_v69_manifest,
    load_v79_dind_successor_manifest,
    load_v90_fresh_scaffold_manifest,
)
from verigym.hwe.materialization_preflight import (  # noqa: E402
    MaterializationHeadroomError,
    require_materialization_headroom,
)

IDENTITY = "deepseek-harness-hwe-v90-fresh-scaffold-timeout-successor-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V90_FRESH_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v90_fresh_scaffold_timeout_successor_v1.json"
)
UPSTREAM_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)
V79_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v79_dind_zero_provider_successor_v1.json"
)
V79_PROVIDER_CONTRACT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v79-dind-zero-provider-successor-v1/provider-contract.json"
)
V87_REPORT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v87-fresh-scaffold-successor-v1/execution-scaffold-report.json"
)
V88_AUDIT = _REPOSITORY / ("docs/audits/2026-09-03_deepseek-harness-v88-v87-pre-provider-stop.md")
ARCHIVE_ROOT = v69.ARCHIVE_ROOT
SCRATCH_ROOT = v69.SCRATCH_ROOT
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v90-fresh-scaffold-timeout-successor-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v90")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
V83_DATA_VOLUME = "verigym-deepseek-harness-v83-dind-data"
V83_DATA_BACKING = "/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/data"
V87_DATA_VOLUME = "verigym-deepseek-harness-v87-dind-data"
V87_DATA_BACKING = "/data2/jiadongzhu/docker/deepseek-harness-hwe-v87/data"
MAX_JSON_BYTES = 64 * 1024 * 1024
_ORIGINAL_V83_IDENTITY = "deepseek-harness-hwe-v83-controller-tag-successor-v1"
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v79_dind_zero_provider_successor_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v90_fresh_scaffold_timeout_successor_v1.json",
    "docs/audits/2026-09-03_deepseek-harness-v88-v87-pre-provider-stop.md",
    "docs/audits/2026-09-03_deepseek-harness-v90-fresh-scaffold-authorization.md",
    "integrations/verigym-hwe-bench/src/verigym_hwe_bench/prepare.py",
    "integrations/verigym-hwe-bench/tests/test_prepare.py",
    "integrations/verigym-deepseek-harness/tests/test_v90_fresh_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v69.py",
    "scripts/materialize_hwe_deepseek_harness_v79_dind.py",
    "scripts/materialize_hwe_deepseek_harness_v81_execution_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v83_controller_tag_successor.py",
    "scripts/materialize_hwe_deepseek_harness_v90_fresh_scaffold.py",
    "scripts/run_repository_rollout_dind_controller.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
    "tests/unit/test_rollout_dind_controller.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--upstream-manifest", type=Path, default=UPSTREAM_MANIFEST)
    parser.add_argument("--v79-manifest", type=Path, default=V79_MANIFEST)
    parser.add_argument("--v79-provider-contract", type=Path, default=V79_PROVIDER_CONTRACT)
    parser.add_argument("--v87-report", type=Path, default=V87_REPORT)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument("--rg-binary", type=Path, default=v69.RG_BINARY)
    parser.add_argument("--rg-release-archive", type=Path, default=v69.RG_ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Build one fresh credential-free scaffold and seal its disposition."""

    _require_execution_boundary(arguments)
    manifest = load_v90_fresh_scaffold_manifest(
        v69._exact_file(arguments.manifest, MANIFEST, "v90 manifest")  # noqa: SLF001
    )
    upstream_path = v69._exact_file(  # noqa: SLF001
        arguments.upstream_manifest, UPSTREAM_MANIFEST, "upstream manifest"
    )
    upstream = load_v69_manifest(upstream_path)
    v79_path = v69._exact_file(arguments.v79_manifest, V79_MANIFEST, "v79 manifest")  # noqa: SLF001
    v79_manifest = load_v79_dind_successor_manifest(v79_path)
    contract_path = v69._exact_file(  # noqa: SLF001
        arguments.v79_provider_contract,
        V79_PROVIDER_CONTRACT,
        "v79 provider contract",
    )
    contract = _load_json(contract_path)
    v87_path = v69._exact_file(arguments.v87_report, V87_REPORT, "v87 report")  # noqa: SLF001
    v87_report = _load_json(v87_path)
    _validate_static_bindings(
        manifest,
        upstream,
        v79_manifest,
        contract,
        v87_report,
        upstream_path=upstream_path,
        v79_path=v79_path,
        contract_path=contract_path,
        v87_path=v87_path,
    )
    source_commit = _require_clean_merged_main(manifest)
    archive_root = v69._exact_directory(  # noqa: SLF001
        arguments.archive_root, ARCHIVE_ROOT, "archive root"
    )
    rg_binary = v69._validated_tool(  # noqa: SLF001
        arguments.rg_binary, v69.RG_BINARY, v69.RG_SHA256, executable=True
    )
    rg_archive = v69._validated_tool(  # noqa: SLF001
        arguments.rg_release_archive,
        v69.RG_ARCHIVE,
        v69.RG_ARCHIVE_SHA256,
        executable=False,
    )
    _configure_v83_helpers()
    root = _new_output(arguments.output)
    for directory in (
        "archive-receipts",
        "command-diagnostics",
        "image-receipts",
        "image-locks",
        "patch-compatibility",
        "qualification",
        "scan-workspaces",
        "security-scans",
        "source-image-locks",
        "sources",
    ):
        (root / directory).mkdir(mode=0o700)
    empty_home = root / "dind-empty-home"
    empty_home.mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v90_fresh_scaffold_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "v79_provider_contract_hash": manifest.v79_provider_contract_hash,
        "v87_report_hash": manifest.v87_report_hash,
        "v88_audit_commit": manifest.v88_audit_commit,
        "v88_post_merge_main_run_id": manifest.v88_post_merge_main_run_id,
        "source_preparation_docker_control_timeout_seconds": (
            manifest.source_preparation_docker_control_timeout_seconds
        ),
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "completed_task_ids": [],
        "task_receipts": [],
        "physical_data_volume_open_count": 0,
        "provider_execution_scaffold_published": False,
        "provider_execution_authorized": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "dind_cleanup_confirmed": False,
        **_closed_training_flags(),
    }
    _write_progress(root, progress)
    dind_name: str | None = None
    cleanup_confirmed = False
    try:
        instances = v69._patch_preflight(  # noqa: SLF001
            upstream, archive_root=archive_root, root=root
        )
        _create_dind_backings(manifest)
        try:
            headroom = require_materialization_headroom(
                control_root=Path("/"),
                docker_root=DIND_DATA_BACKING,
                scratch_root=v69._exact_directory(  # noqa: SLF001
                    SCRATCH_ROOT, SCRATCH_ROOT, "scratch root"
                ),
                output_parent=root.parent,
            )
        except MaterializationHeadroomError as exc:
            atomic_dump_json(root / "headroom-preflight.json", exc.receipt)
            raise
        atomic_dump_json(root / "headroom-preflight.json", headroom)
        progress.update(
            {
                "status": "isolated_dind_startup",
                "headroom_preflight_hash": headroom["preflight_hash"],
            }
        )
        _write_progress(root, progress)

        v83._validate_host_images(manifest)  # noqa: SLF001
        dind._create_bind_backed_volume(  # noqa: SLF001
            manifest.dind_data_volume,
            owner=dind._DIND_OWNER,  # noqa: SLF001
            role="data",
            backing=DIND_DATA_BACKING,
        )
        dind._create_bind_backed_volume(  # noqa: SLF001
            manifest.dind_socket_volume,
            owner=dind._DIND_OWNER,  # noqa: SLF001
            role="socket",
            backing=DIND_SOCKET_BACKING,
        )
        dind_name = f"verigym-dind-v90-{secrets.token_hex(10)}"

        def record_physical_open() -> None:
            progress.update(
                {
                    "status": "isolated_dind_readiness",
                    "physical_data_volume_open_count": 1,
                }
            )
            _write_progress(root, progress)

        metadata = dind._start_dind(  # noqa: SLF001
            name=dind_name,
            image_id=manifest.dind_image_id,
            socket_volume=manifest.dind_socket_volume,
            data_volume=manifest.dind_data_volume,
            source_volume=None,
            scratch_volume=None,
            empty_home=empty_home,
            same_path_mounts=dind._same_path_mounts({root: "rw"}),  # noqa: SLF001
            startup_timeout_s=120,
            on_container_started=record_physical_open,
        )
        v81._validate_outer_sidecar(dind_name, manifest, root=root)  # noqa: SLF001
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        runtime_receipt = _runtime_receipt(manifest, dind_name=dind_name, metadata=metadata)
        atomic_dump_json(root / "dind-runtime-receipt.json", runtime_receipt)
        progress.update(
            {
                "status": "offline_execution_scaffold_materialization",
                "dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
            }
        )
        _write_progress(root, progress)

        with v81._nested_docker(DIND_SOCKET_BACKING / "docker.sock"):  # noqa: SLF001
            for task in upstream.primary_tasks:
                expected = v81._contract_binding(contract, task.task_id)  # noqa: SLF001
                diagnostic = root / "command-diagnostics" / f"pr-{task.pr_number}.json"

                def build_command_runner(
                    command: list[str],
                    timeout: int,
                    *,
                    output: Path = diagnostic,
                ) -> dict[str, Any]:
                    return v83._content_free_bounded_command(  # noqa: SLF001
                        command,
                        timeout=timeout,
                        receipt_path=output,
                    )

                def source_binding_runner(
                    source: Path,
                    task_lock: HweOfflineTaskLock,
                ) -> dict[str, str]:
                    return v81._source_binding(  # noqa: SLF001
                        source,
                        task_lock,
                        v79_manifest=v79_manifest,
                        expected_binding=v81._contract_binding(  # noqa: SLF001
                            contract, task_lock.task_id
                        ),
                    )

                receipt = v69._materialize_task(  # noqa: SLF001
                    task,
                    instance=instances[task.task_id],
                    archive_root=archive_root,
                    rg_binary=rg_binary,
                    rg_archive=rg_archive,
                    root=root,
                    campaign_identity=IDENTITY,
                    command_tag_version="v90",
                    build_command_runner=build_command_runner,
                    source_binding_runner=source_binding_runner,
                    scan_scratch_parent=root / "scan-workspaces",
                    docker_control_timeout_s=(
                        manifest.source_preparation_docker_control_timeout_seconds
                    ),
                )
                receipt = v79._runtime_bound_task_receipt(  # noqa: SLF001
                    receipt, task, successor=v79_manifest
                )
                v81._validate_execution_receipt(receipt, expected, task, v79_manifest)  # noqa: SLF001
                progress["completed_task_ids"].append(task.task_id)
                progress["task_receipts"].append(receipt)
                _write_progress(root, progress)

        controller_receipt = _controller_receipt(dind_name, manifest, root=root)
        inventory = _inventory(
            dind_name,
            manifest,
            receipts=progress["task_receipts"],
            root=root,
        )
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        if not dind._remove_container(dind_name):  # noqa: SLF001
            raise ConfigurationError("v90 isolated DinD daemon cleanup failed")
        dind_name = None
        cleanup = _clean_socket_volume(manifest, root=root)
        cleanup_confirmed = True
        contract_receipt = _scaffold_contract(
            manifest,
            upstream,
            progress["task_receipts"],
            source_commit=source_commit,
            post_merge_main_run_id=arguments.post_merge_main_run_id,
            runtime_receipt=runtime_receipt,
            controller_receipt=controller_receipt,
            inventory=inventory,
            cleanup=cleanup,
        )
        atomic_dump_json(root / "execution-scaffold-contract.json", contract_receipt)
        progress.update(
            {
                "status": "completed_pending_independent_v91_audit",
                "provider_execution_scaffold_published": True,
                "execution_scaffold_contract_hash": contract_receipt["contract_hash"],
                "dind_cleanup_confirmed": True,
                "dind_cleanup_receipt_hash": cleanup["receipt_hash"],
            }
        )
        _write_progress(root, progress)
    except Exception as exc:
        cleanup_confirmed, cleanup_hash = _best_effort_cleanup(
            dind_name=dind_name,
            manifest=manifest,
            root=root,
        )
        progress.update(
            {
                "status": "stopped_without_execution_scaffold",
                "stop_reason": type(exc).__name__,
                "raw_exception_persisted": False,
                "provider_execution_scaffold_published": False,
                "provider_execution_authorized": False,
                "dind_cleanup_confirmed": cleanup_confirmed,
                "dind_cleanup_receipt_hash": cleanup_hash,
            }
        )
        report = _seal(progress)
        atomic_dump_json(root / "execution-scaffold-report.json", report)
        _write_progress(root, progress)
        raise
    if not cleanup_confirmed:
        raise ConfigurationError("v90 cleanup must complete before scaffold publication")
    report = _seal(progress)
    atomic_dump_json(root / "execution-scaffold-report.json", report)
    return report


def _validate_static_bindings(
    manifest: DeepSeekHarnessV90FreshScaffoldManifest,
    upstream: DeepSeekHarnessV69Manifest,
    v79_manifest: DeepSeekHarnessV79DindSuccessorManifest,
    contract: Mapping[str, Any],
    v87_report: Mapping[str, Any],
    *,
    upstream_path: Path,
    v79_path: Path,
    contract_path: Path,
    v87_path: Path,
) -> None:
    bindings = (
        (
            upstream_path,
            manifest.upstream_manifest_sha256,
            upstream.manifest_hash,
            manifest.upstream_manifest_hash,
        ),
        (
            v79_path,
            manifest.v79_manifest_sha256,
            v79_manifest.manifest_hash,
            manifest.v79_manifest_hash,
        ),
        (
            contract_path,
            manifest.v79_provider_contract_sha256,
            _canonical_hash(contract, "contract_hash"),
            manifest.v79_provider_contract_hash,
        ),
        (
            v87_path,
            manifest.v87_report_sha256,
            _canonical_hash(v87_report, "report_hash"),
            manifest.v87_report_hash,
        ),
    )
    if (
        any(
            v69._hash_file(path) != file_hash or observed != expected  # noqa: SLF001
            for path, file_hash, observed, expected in bindings
        )
        or v69._hash_file(V88_AUDIT) != manifest.v88_audit_sha256
    ):  # noqa: SLF001
        raise ConfigurationError("v90 predecessor evidence binding changed")
    expected_schedule = [task.task_id for task in upstream.primary_tasks]
    if (
        contract.get("identity") != v79.IDENTITY
        or contract.get("schedule") != expected_schedule
        or contract.get("task_count") != 5
        or contract.get("all_tasks_materialized") is not True
        or contract.get("all_base_failed_reference_passed") is not True
        or contract.get("all_command_images_v2_scanned") is not True
        or contract.get("provider_calls") != 0
        or contract.get("model_process_count") != 0
        or contract.get("provider_execution_authorized") is not False
        or contract.get("dind_cleanup_confirmed") is not True
        or contract.get("runtime_base_commit_overrides")
        != v79_manifest.runtime_base_commit_overrides
        or any(contract.get(key) is not False for key in _closed_training_flags())
    ):
        raise ConfigurationError("v90 v79 zero-provider contract is not eligible")
    if (
        v87_report.get("identity") != "deepseek-harness-hwe-v87-fresh-scaffold-successor-v1"
        or v87_report.get("status") != "stopped_without_execution_scaffold"
        or v87_report.get("stop_reason") != "ConfigurationError"
        or v87_report.get("physical_data_volume_open_count") != 1
        or v87_report.get("completed_task_ids") != []
        or v87_report.get("task_receipts") != []
        or v87_report.get("provider_calls") != 0
        or v87_report.get("model_process_count") != 0
        or v87_report.get("provider_execution_scaffold_published") is not False
        or v87_report.get("provider_execution_authorized") is not False
        or v87_report.get("dind_cleanup_confirmed") is not True
        or v87_report.get("raw_exception_persisted") is not False
        or any(v87_report.get(key) is not False for key in _closed_training_flags())
        or (v87_path.parent / "execution-scaffold-contract.json").exists()
    ):
        raise ConfigurationError("v90 requires the exact audited v87 pre-provider stop")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v88_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v90 requires the merged v88 audit")
    if (
        manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.dind_data_volume
        in {v79_manifest.dind_data_volume, V83_DATA_VOLUME, V87_DATA_VOLUME}
        or manifest.dind_data_backing
        in {v79_manifest.dind_data_backing, V83_DATA_BACKING, V87_DATA_BACKING}
        or manifest.dind_image_id != v79_manifest.dind_image_id
        or manifest.dind_repository_digest != v79_manifest.dind_repository_digest
        or manifest.dind_server_version != v79_manifest.dind_server_version
        or manifest.v83_data_volume_reused is not False
        or manifest.v85_data_volume_reused is not False
        or manifest.v87_data_volume_reused is not False
        or manifest.source_preparation_docker_control_timeout_seconds != 300
        or manifest.host_docker_root_used_for_task_layers is not False
    ):
        raise ConfigurationError("v90 fresh purpose-bound DinD identity changed")


def _configure_v83_helpers() -> None:
    if v83.IDENTITY not in {_ORIGINAL_V83_IDENTITY, IDENTITY}:
        raise ConfigurationError("v90 helper identity is not pristine")
    v83.IDENTITY = IDENTITY
    v83.OUTPUT_ROOT = OUTPUT_ROOT
    v83.DIND_PARENT = DIND_PARENT
    v83.DIND_DATA_BACKING = DIND_DATA_BACKING
    v83.DIND_SOCKET_BACKING = DIND_SOCKET_BACKING


def _runtime_receipt(
    manifest: DeepSeekHarnessV90FreshScaffoldManifest,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    raw = v83._runtime_receipt(manifest, dind_name=dind_name, metadata=metadata)  # noqa: SLF001
    return _retag(
        raw,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v90_dind_runtime_receipt_v1",
        extra={
            "physical_data_volume_open_count": 1,
            "physical_volume_open_accounting": manifest.physical_volume_open_accounting,
            "readiness_probe_timeout_retryable": True,
            "v83_data_volume_reused": False,
            "v85_data_volume_reused": False,
            "v87_data_volume_reused": False,
            "source_preparation_docker_control_timeout_seconds": (
                manifest.source_preparation_docker_control_timeout_seconds
            ),
        },
    )


def _controller_receipt(
    dind_name: str,
    manifest: DeepSeekHarnessV90FreshScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    raw = v83._provision_controller_image(dind_name, manifest)  # noqa: SLF001
    value = _retag(
        raw,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v90_controller_image_receipt_v1",
    )
    atomic_dump_json(root / "controller-image-receipt.json", value)
    return value


def _inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV90FreshScaffoldManifest,
    *,
    receipts: list[dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    raw = v83._inner_inventory(dind_name, manifest, receipts=receipts)  # noqa: SLF001
    value = _retag(
        raw,
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v90_execution_inventory_v1",
    )
    atomic_dump_json(root / "execution-inventory.json", value)
    return value


def _clean_socket_volume(
    manifest: DeepSeekHarnessV90FreshScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    raw = v83._clean_socket_volume(manifest, root=root)  # noqa: SLF001
    value = _retag(
        raw,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v90_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", value)
    return value


def _retag(
    value: Mapping[str, Any],
    *,
    hash_field: str,
    format_id: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(copy.deepcopy(value))
    base.pop(hash_field, None)
    base["format_id"] = format_id
    if extra is not None:
        base.update(copy.deepcopy(dict(extra)))
    return {**base, hash_field: content_hash(base)}


def _scaffold_contract(
    manifest: DeepSeekHarnessV90FreshScaffoldManifest,
    upstream: DeepSeekHarnessV69Manifest,
    receipts: list[dict[str, Any]],
    *,
    source_commit: str,
    post_merge_main_run_id: int,
    runtime_receipt: Mapping[str, Any],
    controller_receipt: Mapping[str, Any],
    inventory: Mapping[str, Any],
    cleanup: Mapping[str, Any],
) -> dict[str, Any]:
    schedule = [task.task_id for task in upstream.primary_tasks]
    if (
        len(receipts) != 5
        or [item.get("task_id") for item in receipts] != schedule
        or any(
            item.get("source_preparation_docker_control_timeout_seconds")
            != manifest.source_preparation_docker_control_timeout_seconds
            for item in receipts
        )
    ):
        raise ConfigurationError("v90 refuses a partial execution scaffold contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v90_execution_scaffold_contract_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "v79_provider_contract_hash": manifest.v79_provider_contract_hash,
        "v87_report_hash": manifest.v87_report_hash,
        "v88_audit_commit": manifest.v88_audit_commit,
        "v88_post_merge_main_run_id": manifest.v88_post_merge_main_run_id,
        "source_preparation_docker_control_timeout_seconds": (
            manifest.source_preparation_docker_control_timeout_seconds
        ),
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "schedule": schedule,
        "task_receipts": receipts,
        "task_count": len(receipts),
        "all_tasks_materialized": True,
        "all_base_failed_reference_passed": True,
        "all_command_images_v2_scanned": True,
        "controller_image_receipt_hash": controller_receipt["receipt_hash"],
        "controller_image_tag": manifest.controller_image_tag,
        "controller_source_repository_digest": manifest.controller_image_repository_digest,
        "execution_inventory_hash": inventory["inventory_hash"],
        "dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
        "dind_cleanup_receipt_hash": cleanup["receipt_hash"],
        "dind_cleanup_confirmed": True,
        "dind_data_volume": manifest.dind_data_volume,
        "dind_data_backing": manifest.dind_data_backing,
        "physical_data_volume_open_count": 1,
        "physical_volume_open_accounting": manifest.physical_volume_open_accounting,
        "readiness_probe_timeout_retryable": True,
        "host_docker_root_used_for_task_layers": False,
        "v83_data_volume_reused": False,
        "v85_data_volume_reused": False,
        "v87_data_volume_reused": False,
        "provider_successor_identity": manifest.provider_successor_identity,
        "provider_successor_reopen_budget": 1,
        "provider_successor_reopen_count": 0,
        "provider_outer_network": manifest.provider_outer_network,
        "provider_inner_network": manifest.provider_inner_network,
        "provider_inner_network_created": False,
        "provider_execution_scaffold_published": True,
        "provider_execution_authorized": False,
        "requires_independent_v91_audit": True,
        "provider_calls": 0,
        "model_process_count": 0,
        **_closed_training_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


def _create_dind_backings(manifest: DeepSeekHarnessV90FreshScaffoldManifest) -> None:
    if (
        Path(manifest.dind_data_backing) != DIND_DATA_BACKING
        or Path(manifest.dind_socket_backing) != DIND_SOCKET_BACKING
        or DIND_PARENT.exists()
        or DIND_PARENT.is_symlink()
    ):
        raise ConfigurationError("v90 DinD backing identity must be new and exact")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    for path in (DIND_PARENT, DIND_DATA_BACKING, DIND_SOCKET_BACKING):
        path.chmod(0o700)


def _best_effort_cleanup(
    *,
    dind_name: str | None,
    manifest: DeepSeekHarnessV90FreshScaffoldManifest,
    root: Path,
) -> tuple[bool, str | None]:
    try:
        if dind_name is not None:
            existing = dind._run(  # noqa: SLF001
                ["docker", "container", "inspect", dind_name], timeout_s=30
            )
            if existing.returncode == 0 and not dind._remove_container(dind_name):  # noqa: SLF001
                return False, None
        volume = dind._run(  # noqa: SLF001
            ["docker", "volume", "inspect", manifest.dind_socket_volume], timeout_s=30
        )
        if volume.returncode == 0:
            receipt = _clean_socket_volume(manifest, root=root)
            return True, str(receipt["receipt_hash"])
        return True, None
    except Exception:
        return False, None


def _canonical_hash(value: Mapping[str, Any], field: str) -> str | None:
    base = dict(copy.deepcopy(value))
    observed = base.pop(field, None)
    if not isinstance(observed, str) or content_hash(base) != observed:
        return None
    return observed


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v90 requires a non-root host identity")
    if any(name in os.environ for name in v69._PROVIDER_ENV_NAMES):  # noqa: SLF001
        raise ConfigurationError("v90 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v90 requires the default host Docker connection")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v90 requires a positive post-merge main run ID")


def _require_clean_merged_main(manifest: DeepSeekHarnessV90FreshScaffoldManifest) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=_REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tracked != relative:
            raise ConfigurationError("v90 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v88_audit_commit, head],
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
        raise ConfigurationError("v90 requires clean merged origin/main after v88")
    return head


def _git_text(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink() or path != OUTPUT_ROOT:
        raise ConfigurationError("v90 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON_BYTES:
        raise ConfigurationError("v90 JSON input is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v90 JSON input is malformed") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v90 JSON input is not an object")
    return value


def _closed_training_flags() -> dict[str, bool]:
    return {
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(copy.deepcopy(value))
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    atomic_dump_json(root / "execution-scaffold-progress.json", _seal(value))


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
    return 0 if report["provider_execution_scaffold_published"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
