#!/usr/bin/env python3
"""Materialize a fresh runtime-complete five-task scaffold without a provider call."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
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

from verigym_deepseek_harness.config import (  # noqa: E402
    API_KEY_ENV,
    BASE_URL_ENV,
    CONTROLLER_IMAGE_REPO_DIGEST,
    DEEPSEEK_HARNESS_SOURCE_ROOT,
    resolve_settings,
)
from verigym_deepseek_harness.process import run_harness_helper  # noqa: E402

from scripts import collect_hwe_deepseek_harness_v92_official_matrix as v92  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v79_dind as v79  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v81_execution_scaffold as v81,
)
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID  # noqa: E402
from verigym.hwe.deepseek_harness import DEEPSEEK_HARNESS_MODEL  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    HweOfflineTaskLock,
    load_v69_manifest,
    load_v79_dind_successor_manifest,
    load_v92_official_matrix_manifest,
    load_v94_runtime_complete_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.hwe.materialization_preflight import (  # noqa: E402
    MaterializationHeadroomError,
    require_materialization_headroom,
)
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID  # noqa: E402
from verigym.runtimes.docker.runtime import DockerRuntime  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v94-runtime-complete-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V94_RUNTIME_COMPLETE_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v94_runtime_complete_scaffold_v1.json"
)
V92_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v92_official_matrix_v1.json"
)
V93_AUDIT = _REPOSITORY / "docs/audits/2026-09-03_deepseek-harness-v93-v92-result.md"
V90_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v90-fresh-scaffold-timeout-successor-v1"
)
V92_ROOT = Path("/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v92-official-matrix-v1")
V92_REPORT = V92_ROOT / "matrix-report.json"
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
ARCHIVE_ROOT = v69.ARCHIVE_ROOT
SCRATCH_ROOT = v69.SCRATCH_ROOT
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v94-runtime-complete-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v94")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v94-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v94-runtime")
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_TRANSFER_OUTPUT_BYTES = 1024 * 1024
MAX_COMMAND_DIAGNOSTIC_BYTES = v79.MAX_COMMAND_DIAGNOSTIC_BYTES
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CLEANUP_PATHS = v92._CLEANUP_PATHS  # noqa: SLF001
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v79_dind_zero_provider_successor_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v90_fresh_scaffold_timeout_successor_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v92_official_matrix_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v94_runtime_complete_scaffold_v1.json",
    "docs/audits/2026-09-03_deepseek-harness-v93-v92-result.md",
    "docs/audits/2026-09-03_deepseek-harness-v94-runtime-complete-scaffold-authorization.md",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/config.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/helper.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/process.py",
    "integrations/verigym-deepseek-harness/tests/test_v94_runtime_complete_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v94_runtime_complete_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v69.py",
    "scripts/materialize_hwe_deepseek_harness_v79_dind.py",
    "scripts/materialize_hwe_deepseek_harness_v81_execution_scaffold.py",
    "scripts/run_repository_rollout_dind_controller.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--v92-manifest", type=Path, default=V92_MANIFEST)
    parser.add_argument("--v90-root", type=Path, default=V90_ROOT)
    parser.add_argument("--v92-report", type=Path, default=V92_REPORT)
    parser.add_argument("--upstream-manifest", type=Path, default=UPSTREAM_MANIFEST)
    parser.add_argument("--v79-manifest", type=Path, default=V79_MANIFEST)
    parser.add_argument("--v79-provider-contract", type=Path, default=V79_PROVIDER_CONTRACT)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument("--rg-binary", type=Path, default=v69.RG_BINARY)
    parser.add_argument("--rg-release-archive", type=Path, default=v69.RG_ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Transfer all frozen images, run zero-provider preflights, and seal one contract."""

    _require_execution_boundary(arguments)
    manifest = load_v94_runtime_complete_scaffold_manifest(
        _exact_file(arguments.manifest, MANIFEST, "v94 manifest")
    )
    v92_manifest_path = _exact_file(arguments.v92_manifest, V92_MANIFEST, "v92 manifest")
    v92_manifest = load_v92_official_matrix_manifest(v92_manifest_path)
    v90_root = _exact_directory(arguments.v90_root, V90_ROOT, "v90 evidence root")
    v92_report_path = _exact_file(arguments.v92_report, V92_REPORT, "v92 report")
    v92_report = _load_json(v92_report_path)
    _validate_static_bindings(
        manifest,
        v92_manifest,
        v92_report,
        v92_manifest_path=v92_manifest_path,
        v92_report_path=v92_report_path,
    )
    source_commit = _require_clean_merged_main(manifest)
    v92._validate_predecessor(v92_manifest, v90_root=v90_root)  # noqa: SLF001
    v92._validate_task_bindings(v92_manifest, v90_root=v90_root)  # noqa: SLF001
    upstream_path = _exact_file(arguments.upstream_manifest, UPSTREAM_MANIFEST, "upstream manifest")
    upstream = load_v69_manifest(upstream_path)
    v79_path = _exact_file(arguments.v79_manifest, V79_MANIFEST, "v79 manifest")
    v79_manifest = load_v79_dind_successor_manifest(v79_path)
    v79_contract_path = _exact_file(
        arguments.v79_provider_contract,
        V79_PROVIDER_CONTRACT,
        "v79 provider contract",
    )
    v79_contract = _load_json(v79_contract_path)
    archive_root = _exact_directory(arguments.archive_root, ARCHIVE_ROOT, "archive root")
    rg_binary = v69._validated_tool(  # noqa: SLF001
        arguments.rg_binary, v69.RG_BINARY, v69.RG_SHA256, executable=True
    )
    rg_archive = v69._validated_tool(  # noqa: SLF001
        arguments.rg_release_archive,
        v69.RG_ARCHIVE,
        v69.RG_ARCHIVE_SHA256,
        executable=False,
    )
    host_images = _validate_host_images(manifest)
    root = _new_output(arguments.output)
    for directory in (
        "archive-receipts",
        "command-diagnostics",
        "image-receipts",
        "image-locks",
        "patch-compatibility",
        "preflight",
        "qualification",
        "scan-workspaces",
        "security-scans",
        "source-image-locks",
        "sources",
        "transfer-receipts",
    ):
        (root / directory).mkdir(mode=0o700)
    empty_home = root / "dind-empty-home"
    empty_home.mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_scaffold_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "v92_report_hash": manifest.v92_report_hash,
        "v93_audit_commit": manifest.v93_audit_commit,
        "v93_post_merge_main_run_id": manifest.v93_post_merge_main_run_id,
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "completed_stages": [],
        "provider_execution_scaffold_published": False,
        "provider_execution_authorized": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "dind_cleanup_confirmed": False,
        **_closed_training_flags(),
    }
    _write_progress(root, progress)
    dind_name: str | None = None
    inner_network_created = False
    cleanup_confirmed = False
    cleanup_hash: str | None = None
    try:
        instances = v69._patch_preflight(  # noqa: SLF001
            upstream, archive_root=archive_root, root=root
        )
        _create_runtime_paths(manifest)
        try:
            headroom = require_materialization_headroom(
                control_root=Path("/"),
                docker_root=DIND_DATA_BACKING,
                scratch_root=_exact_directory(SCRATCH_ROOT, SCRATCH_ROOT, "scratch root"),
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
        dind_name = f"verigym-dind-v94-{secrets.token_hex(10)}"
        same_paths = dind._same_path_mounts(  # noqa: SLF001
            {
                _REPOSITORY.resolve(strict=True): "ro",
                v90_root: "ro",
                DEEPSEEK_HARNESS_SOURCE_ROOT.resolve(strict=True): "ro",
                CONTROL_ROOT.resolve(strict=True): "rw",
                RUNTIME_TMP.resolve(strict=True): "rw",
                root.resolve(strict=True): "rw",
            }
        )
        metadata = dind._start_dind(  # noqa: SLF001
            name=dind_name,
            image_id=manifest.dind_image_id,
            socket_volume=manifest.dind_socket_volume,
            data_volume=manifest.dind_data_volume,
            source_volume=None,
            scratch_volume=None,
            empty_home=empty_home,
            same_path_mounts=same_paths,
            startup_timeout_s=120,
        )
        _validate_outer_sidecar(dind_name, manifest, root=root)
        _require_empty_fresh_inner(dind_name)
        runtime_receipt = _runtime_receipt(manifest, dind_name=dind_name, metadata=metadata)
        atomic_dump_json(root / "dind-runtime-receipt.json", runtime_receipt)

        transfer = _transfer_images(
            dind_name,
            manifest,
            host_images=host_images,
            root=root,
        )
        progress["completed_stages"].append("controller_and_workspace_runtime_transferred")
        with _nested_runtime(DIND_SOCKET_BACKING / "docker.sock"):
            task_materialization, locks = _materialize_tasks(
                manifest,
                v92_manifest,
                upstream=upstream,
                v79_manifest=v79_manifest,
                v79_contract=v79_contract,
                instances=instances,
                archive_root=archive_root,
                rg_binary=rg_binary,
                rg_archive=rg_archive,
                root=root,
            )
        progress["completed_stages"].append("five_task_offline_materialization")
        progress["completed_task_ids"] = task_materialization["completed_task_ids"]
        inventory = _inventory(dind_name, manifest)
        atomic_dump_json(root / "execution-inventory.json", inventory)
        progress.update(
            {
                "status": "zero_provider_preflight",
                "dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
                "image_transfer_receipt_hash": transfer["receipt_hash"],
                "task_materialization_receipt_hash": task_materialization["receipt_hash"],
                "execution_inventory_hash": inventory["inventory_hash"],
            }
        )
        _write_progress(root, progress)

        with _nested_runtime(DIND_SOCKET_BACKING / "docker.sock"):
            runtime_preflight = _runtime_prepare_preflight(
                manifest,
                locks=locks,
                dind_name=dind_name,
            )
            atomic_dump_json(root / "preflight/runtime-prepare.json", runtime_preflight)
            progress["completed_stages"].append("five_task_runtime_prepare")
            _create_internal_preflight_network(dind_name, manifest)
            inner_network_created = True
            try:
                harness_preflight = _harness_initialize_preflight(
                    manifest,
                    controller_receipt_hash=str(transfer["controller_receipt_hash"]),
                    root=root,
                )
            finally:
                _remove_internal_preflight_network(dind_name, manifest)
                inner_network_created = False
            atomic_dump_json(root / "preflight/harness-initialize.json", harness_preflight)
            progress["completed_stages"].append("network_isolated_harness_initialize")
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        _require_preflight_network_absent(dind_name, manifest)
        final_inventory = _inventory(dind_name, manifest)
        if final_inventory["required_image_ids"] != inventory["required_image_ids"]:
            raise ConfigurationError("v94 final image inventory changed during preflight")
        atomic_dump_json(root / "final-execution-inventory.json", final_inventory)
        progress.update(
            {
                "status": "cleanup",
                "runtime_prepare_receipt_hash": runtime_preflight["receipt_hash"],
                "harness_initialize_receipt_hash": harness_preflight["receipt_hash"],
                "final_execution_inventory_hash": final_inventory["inventory_hash"],
            }
        )
        _write_progress(root, progress)

        if not dind._remove_container(dind_name):  # noqa: SLF001
            raise ConfigurationError("v94 isolated DinD daemon cleanup failed")
        dind_name = None
        cleanup = _clean_socket_volume(manifest, root=root)
        cleanup_confirmed = True
        cleanup_hash = str(cleanup["receipt_hash"])
        contract = _scaffold_contract(
            manifest,
            source_commit=source_commit,
            post_merge_main_run_id=arguments.post_merge_main_run_id,
            runtime_receipt=runtime_receipt,
            transfer=transfer,
            task_materialization=task_materialization,
            inventory=final_inventory,
            runtime_preflight=runtime_preflight,
            harness_preflight=harness_preflight,
            cleanup=cleanup,
        )
        atomic_dump_json(root / "execution-scaffold-contract.json", contract)
        progress.update(
            {
                "status": "completed_pending_independent_v95_audit",
                "provider_execution_scaffold_published": True,
                "execution_scaffold_contract_hash": contract["contract_hash"],
                "dind_cleanup_confirmed": True,
                "dind_cleanup_receipt_hash": cleanup_hash,
            }
        )
        _write_progress(root, progress)
    except Exception as exc:
        cleanup_confirmed, cleanup_hash = _best_effort_cleanup(
            dind_name=dind_name,
            inner_network_created=inner_network_created,
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
                "provider_request_started": False,
                "provider_calls": 0,
                "model_process_count": 0,
                "dind_cleanup_confirmed": cleanup_confirmed,
                "dind_cleanup_receipt_hash": cleanup_hash,
            }
        )
        report = _seal(progress)
        atomic_dump_json(root / "execution-scaffold-report.json", report)
        _write_progress(root, progress)
        raise
    if not cleanup_confirmed:
        raise ConfigurationError("v94 cleanup must complete before scaffold publication")
    report = _seal(progress)
    atomic_dump_json(root / "execution-scaffold-report.json", report)
    return report


def _validate_static_bindings(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    if (
        v69._hash_file(v92_manifest_path) != manifest.v92_manifest_sha256  # noqa: SLF001
        or v92_manifest.manifest_hash != manifest.v92_manifest_hash
        or v69._hash_file(v92_report_path) != manifest.v92_report_sha256  # noqa: SLF001
        or _canonical_hash(report, "report_hash") != manifest.v92_report_hash
        or v69._hash_file(V93_AUDIT) != manifest.v93_audit_sha256  # noqa: SLF001
        or manifest.schedule != v92_manifest.schedule
        or manifest.workspace_runtime_image_id != HWE_WORKSPACE_RUNTIME_IMAGE_ID
        or manifest.controller_image_id != v92_manifest.controller_image_id
        or manifest.controller_image_repository_digest
        != v92_manifest.controller_image_repository_digest
        or manifest.dind_image_id != v92_manifest.dind_image_id
        or manifest.dind_repository_digest != v92_manifest.dind_repository_digest
    ):
        raise ConfigurationError("v94 predecessor or fixed-image binding changed")
    state = report.get("matrix_state")
    attempts = report.get("attempts")
    first = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
    if (
        report.get("identity") != "deepseek-harness-hwe-v92-official-matrix-v1"
        or report.get("status") != "stopped_pending_independent_v93_audit"
        or report.get("stop_reason") != "pre_provider_infrastructure_failure"
        or report.get("v90_data_volume_reopen_count") != 1
        or report.get("v90_data_volume_reopen_budget") != 1
        or report.get("provider_episode_count") != 0
        or report.get("provider_call_count") != 0
        or report.get("provider_total_tokens") != 0
        or report.get("dind_cleanup_confirmed") is not True
        or report.get("raw_exception_persisted") is not False
        or not isinstance(state, dict)
        or state.get("stop_reason") != "pre_provider_infrastructure_failure"
        or not isinstance(first, dict)
        or first.get("task_id") != manifest.schedule[0].task_id
        or first.get("provider_marker") != "not_started"
        or first.get("provider_call_count") != 0
        or first.get("outcome") != "infrastructure_failure"
        or any(report.get(key) is not False for key in _closed_training_flags())
    ):
        raise ConfigurationError("v94 requires the exact audited v92 pre-provider stop")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v93_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v94 requires the merged v93 audit")
    if (
        manifest.v90_evidence_root != str(V90_ROOT)
        or manifest.v92_evidence_root != str(V92_ROOT)
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.v90_data_volume_reused is not False
        or manifest.v92_data_volume_reused is not False
        or manifest.provider_credentials_available is not False
        or manifest.registry_access_allowed is not False
    ):
        raise ConfigurationError("v94 fresh purpose-bound DinD identity changed")


def _validate_host_images(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
) -> list[dict[str, str]]:
    dind._dind_image(manifest.dind_image_id)  # noqa: SLF001
    controller = dind._inspect("image", manifest.controller_image_tag)  # noqa: SLF001
    runtime = dind._image(manifest.workspace_runtime_image_id, role="workspace runtime")  # noqa: SLF001
    expected_controller_digest = "node@" + manifest.controller_image_repository_digest
    if (
        controller.get("Id") != manifest.controller_image_id
        or manifest.controller_image_tag not in controller.get("RepoTags", [])
        or expected_controller_digest not in controller.get("RepoDigests", [])
        or CONTROLLER_IMAGE_REPO_DIGEST != expected_controller_digest
        or runtime.get("RepoTags") != manifest.workspace_runtime_host_repo_tags
    ):
        raise ConfigurationError("v94 host controller or workspace runtime identity changed")
    images: list[dict[str, str]] = [
        {
            "role": "controller",
            "source": manifest.controller_image_tag,
            "image_id": manifest.controller_image_id,
        },
        {
            "role": "workspace_runtime",
            "source": manifest.workspace_runtime_image_id,
            "image_id": manifest.workspace_runtime_image_id,
        },
    ]
    if len(images) != 2 or len({item["image_id"] for item in images}) != 2:
        raise ConfigurationError("v94 host bootstrap image set is not exactly two unique IDs")
    return images


def _materialize_tasks(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    *,
    upstream: Any,
    v79_manifest: Any,
    v79_contract: Mapping[str, Any],
    instances: Mapping[str, Any],
    archive_root: Path,
    rg_binary: Path,
    rg_archive: Path,
    root: Path,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    receipts: list[dict[str, Any]] = []
    locks: dict[str, HweCommandImageLock] = {}
    if [task.task_id for task in upstream.primary_tasks] != [
        item.task_id for item in manifest.schedule
    ]:
        raise ConfigurationError("v94 upstream task order differs from the frozen schedule")
    for task, binding in zip(upstream.primary_tasks, v92_manifest.schedule, strict=True):
        expected = v81._contract_binding(v79_contract, task.task_id)  # noqa: SLF001
        diagnostic = root / "command-diagnostics" / f"pr-{task.pr_number}.json"

        def build_command_runner(
            command: list[str],
            timeout: int,
            *,
            output: Path = diagnostic,
        ) -> dict[str, Any]:
            return _content_free_bounded_command(command, timeout=timeout, receipt_path=output)

        def source_binding_runner(
            source: Path,
            task_lock: HweOfflineTaskLock,
        ) -> dict[str, str]:
            return v81._source_binding(  # noqa: SLF001
                source,
                task_lock,
                v79_manifest=v79_manifest,
                expected_binding=v81._contract_binding(  # noqa: SLF001
                    v79_contract, task_lock.task_id
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
            command_tag_version="v94",
            build_command_runner=build_command_runner,
            source_binding_runner=source_binding_runner,
            scan_scratch_parent=root / "scan-workspaces",
            docker_control_timeout_s=300,
        )
        receipt = v79._runtime_bound_task_receipt(  # noqa: SLF001
            receipt, task, successor=v79_manifest
        )
        v81._validate_execution_receipt(receipt, expected, task, v79_manifest)  # noqa: SLF001
        lock_path = root / "image-locks" / f"pr-{task.pr_number}.json"
        lock = HweCommandImageLock.model_validate_json(lock_path.read_bytes())
        if (
            receipt.get("task_hash") != binding.task_hash
            or receipt.get("source_hash") != binding.source_hash
            or receipt.get("prepared_source_image_lock_sha256")
            != binding.prepared_source_image_lock_sha256
            or receipt.get("agent_command_image") != binding.command_image
            or receipt.get("agent_command_image_lock_hash") != binding.command_image_lock_hash
            or receipt.get("security_scan_id") != binding.security_scan_id
            or receipt.get("official_verifier_image") != binding.official_verifier_image
            or lock.lock_hash != binding.command_image_lock_hash
            or lock.derived_command_image_id != binding.command_image
        ):
            raise ConfigurationError(
                "v94 rebuilt task artifact differs from the frozen v92 binding"
            )
        receipts.append(receipt)
        locks[task.task_id] = lock
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_task_materialization_set_v1",
        "identity": IDENTITY,
        "completed_task_ids": [item["task_id"] for item in receipts],
        "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
        "task_count": len(receipts),
        "all_reference_patches_compatible": True,
        "all_base_failed_reference_passed": True,
        "all_command_images_v2_scanned": True,
        "source_preparation_docker_control_timeout_seconds": 300,
        "registry_accessed": False,
        "partial_archive_used": False,
        "provider_calls": 0,
        "task_receipts": receipts,
    }
    if len(receipts) != 5:
        raise ConfigurationError("v94 refuses partial task materialization")
    value = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "task-materialization-set.json", value)
    return value, locks


def _content_free_bounded_command(
    command: list[str],
    *,
    timeout: int,
    receipt_path: Path,
) -> dict[str, Any]:
    if timeout <= 0 or timeout > 3600 or not command:
        raise ConfigurationError("v94 build-command diagnostic boundary is invalid")
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
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
        spawn_succeeded = True
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        timed_out = True
        spawn_succeeded = True
    except OSError:
        pass
    within_bound = (
        len(stdout) <= MAX_COMMAND_DIAGNOSTIC_BYTES and len(stderr) <= MAX_COMMAND_DIAGNOSTIC_BYTES
    )
    passed = spawn_succeeded and not timed_out and returncode == 0 and within_bound
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_content_free_bounded_command_diagnostic_v1",
        "identity": IDENTITY,
        "command_role": "task_specific_command_image_build",
        "executable_name": Path(command[0]).name,
        "argument_count": len(command),
        "timeout_seconds": timeout,
        "maximum_output_bytes": MAX_COMMAND_DIAGNOSTIC_BYTES,
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
        raise ConfigurationError("v94 bounded build command failed")
    return receipt


def _transfer_images(
    dind_name: str,
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    *,
    host_images: Sequence[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    for ordinal, item in enumerate(host_images, 1):
        image_id = item["image_id"]
        before = dind._inner(  # noqa: SLF001
            ["image", "inspect", image_id], container=dind_name, timeout_s=30
        )
        if before.returncode == 0:
            raise ConfigurationError("v94 image transfer did not start from fresh state")
        stdout, stderr = dind._pipe_image(  # noqa: SLF001
            container=dind_name,
            image_id=item["source"],
            timeout_s=1800,
        )
        if len(stdout) > MAX_TRANSFER_OUTPUT_BYTES or len(stderr) > MAX_TRANSFER_OUTPUT_BYTES:
            raise ConfigurationError("v94 image transfer diagnostic exceeded its bound")
        inspected = dind._inner(  # noqa: SLF001
            ["image", "inspect", image_id, "--format", "{{json .}}"],
            container=dind_name,
            timeout_s=30,
        )
        try:
            value = json.loads(inspected.stdout)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("v94 transferred image metadata is malformed") from exc
        if inspected.returncode != 0 or value.get("Id") != image_id:
            raise ConfigurationError("v94 transferred image identity changed")
        if item["role"] == "controller" and (
            value.get("RepoTags") != [manifest.controller_image_tag]
            or value.get("RepoDigests") != []
        ):
            raise ConfigurationError("v94 offline controller tag identity changed")
        receipt_base = {
            "schema_version": "1.0",
            "format_id": "verigym_deepseek_harness_hwe_v94_image_transfer_receipt_v1",
            "identity": IDENTITY,
            "ordinal": ordinal,
            "role": item["role"],
            "image_id": image_id,
            "outer_source_read_only": True,
            "inner_image_id_verified": True,
            "transfer_archive_persisted": False,
            "transfer_stdout_bytes": len(stdout),
            "transfer_stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "transfer_stderr_bytes": len(stderr),
            "transfer_stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "raw_transfer_output_persisted": False,
            "provider_environment_present": False,
            "registry_accessed": False,
        }
        receipt = {**receipt_base, "receipt_hash": content_hash(receipt_base)}
        atomic_dump_json(root / "transfer-receipts" / f"{ordinal:02d}-{item['role']}.json", receipt)
        receipts.append(receipt)
    controller_receipt = receipts[0]
    runtime_receipt = receipts[1]
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_image_transfer_set_v1",
        "identity": IDENTITY,
        "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
        "bootstrap_image_count": len(receipts),
        "all_inner_image_ids_verified": True,
        "controller_receipt_hash": controller_receipt["receipt_hash"],
        "workspace_runtime_receipt_hash": runtime_receipt["receipt_hash"],
        "workspace_runtime_image_id": manifest.workspace_runtime_image_id,
        "registry_accessed": False,
        "provider_environment_present": False,
    }
    value = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "image-transfer-set.json", value)
    return value


def _runtime_prepare_preflight(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    completed: list[str] = []
    for binding in manifest.schedule:
        runtime = DockerRuntime(v92._runtime_config(locks[binding.task_id]))  # noqa: SLF001
        try:
            runtime.prepare(f"v94-preflight-pr-{binding.pr_number}")
        finally:
            runtime.close()
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        completed.append(binding.task_id)
    if len(completed) != manifest.runtime_prepare_task_count:
        raise ConfigurationError("v94 runtime prepare did not cover all five tasks")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_runtime_prepare_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "completed_task_ids": completed,
        "task_count": len(completed),
        "workspace_runtime_image_id": manifest.workspace_runtime_image_id,
        "task_network": manifest.task_network,
        "inner_container_inventory_empty": True,
        "inner_volume_inventory_empty": True,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _harness_initialize_preflight(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    session_root = root / "preflight/harness-session"
    broker_root = root / "preflight/harness-broker"
    session_root.mkdir(mode=0o700)
    broker_root.mkdir(mode=0o700)
    settings = resolve_settings(
        {
            "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
            "model_id": DEEPSEEK_HARNESS_MODEL,
            "max_process_time_s": 300,
            "max_output_bytes": 32 * 1024 * 1024,
            "controller_image_id": manifest.controller_image_id,
            "controller_image_offline_load": True,
            "controller_image_source_receipt_hash": controller_receipt_hash,
            "whole_episode_retries": 0,
        },
        task_wall_time_s=300,
    )
    synthetic_key = "v94-offline-" + secrets.token_urlsafe(32)
    synthetic_url = "http://127.0.0.1:9/v1"
    prior_key = os.environ.get(API_KEY_ENV)
    prior_url = os.environ.get(BASE_URL_ENV)
    if prior_key is not None or prior_url is not None:
        raise ConfigurationError("v94 refuses a real provider environment during initialize")
    try:
        os.environ[API_KEY_ENV] = synthetic_key
        os.environ[BASE_URL_ENV] = synthetic_url
        result = run_harness_helper(
            settings,
            mode="initialize",
            prompt="",
            system_prompt="VeriGym v94 network-isolated zero-provider initialization preflight.",
            session_id="v94-zero-provider-preflight",
            session_root=session_root,
            broker_root=broker_root,
        )
    finally:
        os.environ.pop(API_KEY_ENV, None)
        os.environ.pop(BASE_URL_ENV, None)
    scan = _scan_synthetic_values(root, values=(synthetic_key, synthetic_url))
    if (
        result.events
        or result.provider_request_started
        or result.finish_reason is not None
        or result.final_response
        or result.format_repairs
        or result.run_interval_count != 0
        or (session_root / "provider-request-started-v1.json").exists()
        or scan["match_count"] != 0
    ):
        raise ConfigurationError("v94 Harness initialize crossed the provider boundary")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_harness_initialize_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "harness_configuration_fingerprint": settings.configuration_fingerprint,
        "controller_image_id": settings.controller_image_id,
        "controller_image_provenance": settings.controller_image_provenance,
        "controller_image_source_receipt_hash": controller_receipt_hash,
        "outer_network": manifest.scaffold_outer_network,
        "inner_network": manifest.preflight_inner_network,
        "inner_network_internal": manifest.preflight_inner_network_internal,
        "synthetic_provider_values_only": True,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_call_count": 0,
        "provider_values_persisted_or_hashed": False,
        "synthetic_value_scan": scan,
        "raw_exception_persisted": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _create_internal_preflight_network(
    dind_name: str,
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
) -> None:
    _require_preflight_network_absent(dind_name, manifest)
    created = dind._inner(  # noqa: SLF001
        [
            "network",
            "create",
            "--driver",
            "bridge",
            "--internal",
            manifest.preflight_inner_network,
        ],
        container=dind_name,
        timeout_s=30,
    )
    inspected = dind._inner(  # noqa: SLF001
        ["network", "inspect", manifest.preflight_inner_network, "--format", "{{json .}}"],
        container=dind_name,
        timeout_s=30,
    )
    try:
        value = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v94 internal preflight network metadata is malformed") from exc
    if (
        created.returncode != 0
        or not created.stdout.strip()
        or inspected.returncode != 0
        or value.get("Name") != manifest.preflight_inner_network
        or value.get("Driver") != "bridge"
        or value.get("Internal") is not True
        or value.get("Scope") != "local"
    ):
        raise ConfigurationError("v94 internal preflight network differs from policy")


def _remove_internal_preflight_network(
    dind_name: str,
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
) -> None:
    removed = dind._inner(  # noqa: SLF001
        ["network", "rm", manifest.preflight_inner_network],
        container=dind_name,
        timeout_s=30,
    )
    if removed.returncode != 0:
        raise ConfigurationError("v94 internal preflight network cleanup failed")
    _require_preflight_network_absent(dind_name, manifest)


def _require_preflight_network_absent(
    dind_name: str,
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
) -> None:
    inspected = dind._inner(  # noqa: SLF001
        ["network", "inspect", manifest.preflight_inner_network],
        container=dind_name,
        timeout_s=30,
    )
    if inspected.returncode == 0:
        raise ConfigurationError("v94 internal preflight network already exists")


def _inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
) -> dict[str, Any]:
    result = dind._inner(  # noqa: SLF001
        ["image", "ls", "--all", "--no-trunc", "--format", "{{.ID}}"],
        container=dind_name,
        timeout_s=30,
    )
    observed = sorted(set(result.stdout.decode().splitlines()))
    required = sorted(
        {
            manifest.controller_image_id,
            manifest.workspace_runtime_image_id,
            *(item.command_image for item in manifest.schedule),
            *(item.official_verifier_image for item in manifest.schedule),
        }
    )
    if (
        result.returncode != 0
        or len(required) != manifest.required_inner_image_count
        or any(_DIGEST.fullmatch(item) is None for item in observed)
        or not set(required).issubset(observed)
    ):
        raise ConfigurationError("v94 inner image inventory is incomplete or malformed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_execution_inventory_v1",
        "identity": IDENTITY,
        "required_image_ids": required,
        "observed_image_ids": observed,
        "required_image_count": len(required),
        "required_images_present": True,
        "workspace_runtime_image_present": manifest.workspace_runtime_image_id in observed,
        "preflight_inner_network_removed": True,
        "inner_container_inventory_empty": True,
        "inner_volume_inventory_empty": True,
        "provider_calls": 0,
        "model_process_count": 0,
    }
    return {**base, "inventory_hash": content_hash(base)}


def _runtime_receipt(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    host_stat = DIND_DATA_BACKING.stat()
    inner = dind._run(  # noqa: SLF001
        ["docker", "exec", dind_name, "stat", "-c", "%d:%i", "/var/lib/docker"],
        timeout_s=30,
    )
    expected_identity = f"{host_stat.st_dev}:{host_stat.st_ino}"
    if (
        metadata.get("Driver") != manifest.dind_storage_driver
        or metadata.get("DefaultRuntime") != manifest.dind_default_runtime
        or metadata.get("DockerRootDir") != "/var/lib/docker"
        or inner.returncode != 0
        or inner.stdout.decode().strip() != expected_identity
    ):
        raise ConfigurationError("v94 /data2 DinD runtime identity changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_dind_runtime_receipt_v1",
        "identity": IDENTITY,
        "dind_image_id": manifest.dind_image_id,
        "storage_driver": metadata.get("Driver"),
        "default_runtime": metadata.get("DefaultRuntime"),
        "docker_root_dir": metadata.get("DockerRootDir"),
        "data_volume": manifest.dind_data_volume,
        "data_backing": manifest.dind_data_backing,
        "host_and_inner_data_root_identity": expected_identity,
        "host_and_inner_data_root_same_inode": True,
        "outer_network": manifest.scaffold_outer_network,
        "host_docker_root_used_for_task_layers": False,
        "v90_data_volume_reused": False,
        "v92_data_volume_reused": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _validate_outer_sidecar(
    name: str,
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    *,
    root: Path,
) -> None:
    value = dind._inspect("container", name)  # noqa: SLF001
    host = value.get("HostConfig")
    config = value.get("Config")
    mounts = value.get("Mounts")
    if not isinstance(host, dict) or not isinstance(config, dict) or not isinstance(mounts, list):
        raise ConfigurationError("v94 outer sidecar metadata is malformed")
    destinations = {item.get("Destination"): item for item in mounts if isinstance(item, dict)}
    required = {
        "/var/lib/docker": (manifest.dind_data_volume, True),
        "/var/run": (manifest.dind_socket_volume, True),
        "/verigym-host-sentinel": (str((root / "dind-empty-home").resolve()), False),
        str(_REPOSITORY.resolve(strict=True)): (str(_REPOSITORY.resolve(strict=True)), False),
        str(V90_ROOT.resolve(strict=True)): (str(V90_ROOT.resolve(strict=True)), False),
        str(DEEPSEEK_HARNESS_SOURCE_ROOT.resolve(strict=True)): (
            str(DEEPSEEK_HARNESS_SOURCE_ROOT.resolve(strict=True)),
            False,
        ),
        str(CONTROL_ROOT.resolve(strict=True)): (str(CONTROL_ROOT.resolve(strict=True)), True),
        str(RUNTIME_TMP.resolve(strict=True)): (str(RUNTIME_TMP.resolve(strict=True)), True),
        str(root.resolve(strict=True)): (str(root.resolve(strict=True)), True),
    }
    labels = config.get("Labels")
    command = config.get("Cmd")
    if (
        host.get("Privileged") is not True
        or host.get("NetworkMode") != "none"
        or host.get("PortBindings") not in (None, {})
        or not isinstance(labels, dict)
        or labels.get("verigym.owner") != dind._DIND_OWNER  # noqa: SLF001
        or labels.get("verigym.role") != "daemon"
        or not isinstance(command, list)
        or "--storage-driver=vfs" not in command
        or "--bridge=none" not in command
        or "--iptables=false" not in command
        or any(destination not in destinations for destination in required)
        or any(
            (destinations[destination].get("Name") or destinations[destination].get("Source"))
            != source
            or destinations[destination].get("RW") is not writable
            for destination, (source, writable) in required.items()
        )
        or any(item.get("Destination") == "/var/run/docker.sock" for item in mounts)
        or any(
            name in {API_KEY_ENV, BASE_URL_ENV, "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"}
            for name in v92._environment_names(config.get("Env"))  # noqa: SLF001
        )
    ):
        raise ConfigurationError("v94 outer sidecar violates its isolation contract")


@contextlib.contextmanager
def _nested_runtime(socket_path: Path) -> Iterator[None]:
    if socket_path.is_symlink():
        raise ConfigurationError("v94 nested Docker socket path is unsafe")
    metadata = socket_path.stat()
    if not stat.S_ISSOCK(metadata.st_mode):
        raise ConfigurationError("v94 nested Docker socket is unavailable")
    previous = {
        "DOCKER_HOST": os.environ.get("DOCKER_HOST"),
        "DOCKER_CONTEXT": os.environ.get("DOCKER_CONTEXT"),
        "TMPDIR": os.environ.get("TMPDIR"),
    }
    previous_tempdir = tempfile.tempdir
    os.environ["DOCKER_HOST"] = f"unix://{socket_path}"
    os.environ.pop("DOCKER_CONTEXT", None)
    os.environ["TMPDIR"] = str(RUNTIME_TMP)
    tempfile.tempdir = str(RUNTIME_TMP)
    try:
        yield
    finally:
        tempfile.tempdir = previous_tempdir
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _scaffold_contract(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
    runtime_receipt: Mapping[str, Any],
    transfer: Mapping[str, Any],
    task_materialization: Mapping[str, Any],
    inventory: Mapping[str, Any],
    runtime_preflight: Mapping[str, Any],
    harness_preflight: Mapping[str, Any],
    cleanup: Mapping[str, Any],
) -> dict[str, Any]:
    schedule = [item.task_id for item in manifest.schedule]
    task_receipts = task_materialization.get("task_receipts")
    if (
        inventory.get("required_image_count") != 12
        or inventory.get("workspace_runtime_image_present") is not True
        or task_materialization.get("completed_task_ids") != schedule
        or task_materialization.get("task_count") != 5
        or task_materialization.get("all_base_failed_reference_passed") is not True
        or task_materialization.get("all_command_images_v2_scanned") is not True
        or not isinstance(task_receipts, list)
        or [item.get("task_id") for item in task_receipts if isinstance(item, dict)] != schedule
        or runtime_preflight.get("completed_task_ids") != schedule
        or runtime_preflight.get("task_count") != 5
        or harness_preflight.get("provider_request_started") is not False
        or harness_preflight.get("provider_call_count") != 0
        or harness_preflight.get("provider_values_persisted_or_hashed") is not False
    ):
        raise ConfigurationError("v94 refuses a partial or provider-crossing scaffold contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_execution_scaffold_contract_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "v92_manifest_hash": manifest.v92_manifest_hash,
        "v92_report_hash": manifest.v92_report_hash,
        "v93_audit_commit": manifest.v93_audit_commit,
        "v93_post_merge_main_run_id": manifest.v93_post_merge_main_run_id,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "schedule": schedule,
        "task_bindings": task_receipts,
        "task_count": len(schedule),
        "v90_task_qualification_reused_as_expected_binding": True,
        "v94_tasks_materialized_from_completed_local_archives": True,
        "all_base_failed_reference_passed": True,
        "all_command_images_v2_scanned": True,
        "controller_and_workspace_runtime_transferred": True,
        "required_inner_image_count": manifest.required_inner_image_count,
        "workspace_runtime_image_id": manifest.workspace_runtime_image_id,
        "workspace_runtime_transfer_receipt_hash": transfer["workspace_runtime_receipt_hash"],
        "controller_transfer_receipt_hash": transfer["controller_receipt_hash"],
        "image_transfer_set_hash": transfer["receipt_hash"],
        "task_materialization_receipt_hash": task_materialization["receipt_hash"],
        "execution_inventory_hash": inventory["inventory_hash"],
        "runtime_prepare_receipt_hash": runtime_preflight["receipt_hash"],
        "harness_initialize_receipt_hash": harness_preflight["receipt_hash"],
        "dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
        "dind_cleanup_receipt_hash": cleanup["receipt_hash"],
        "dind_cleanup_confirmed": True,
        "dind_data_volume": manifest.dind_data_volume,
        "dind_data_backing": manifest.dind_data_backing,
        "scaffold_outer_network": manifest.scaffold_outer_network,
        "preflight_inner_network_was_internal": True,
        "preflight_inner_network_removed": True,
        "task_network": manifest.task_network,
        "verifier_network": manifest.verifier_network,
        "host_docker_root_used_for_task_layers": False,
        "v90_data_volume_reused": False,
        "v92_data_volume_reused": False,
        "provider_successor_identity": manifest.provider_successor_identity,
        "provider_successor_reopen_budget": manifest.provider_successor_reopen_budget,
        "provider_successor_reopen_count": 0,
        "provider_execution_scaffold_published": True,
        "provider_execution_authorized": False,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "requires_independent_v95_audit": True,
        **_closed_training_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


def _create_runtime_paths(manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest) -> None:
    if (
        Path(manifest.dind_data_backing) != DIND_DATA_BACKING
        or Path(manifest.dind_socket_backing) != DIND_SOCKET_BACKING
        or DIND_PARENT.exists()
        or DIND_PARENT.is_symlink()
    ):
        raise ConfigurationError("v94 DinD backing identity must be new and exact")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    for path in (DIND_PARENT, DIND_DATA_BACKING, DIND_SOCKET_BACKING, CONTROL_ROOT, RUNTIME_TMP):
        if path.is_symlink():
            raise ConfigurationError("v94 runtime path is unsafe")
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.chmod(0o700)
    if (
        next(CONTROL_ROOT.iterdir(), None) is not None
        or next(RUNTIME_TMP.iterdir(), None) is not None
    ):
        raise ConfigurationError("v94 control and runtime scratch paths must start empty")


def _require_empty_fresh_inner(dind_name: str) -> None:
    dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
    images = dind._inner(  # noqa: SLF001
        ["image", "ls", "--all", "--quiet"], container=dind_name, timeout_s=30
    )
    if images.returncode != 0 or images.stdout.strip():
        raise ConfigurationError("v94 fresh DinD image inventory is not empty")


def _clean_socket_volume(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    dind._bind_backed_volume(  # noqa: SLF001
        manifest.dind_socket_volume,
        owner=dind._DIND_OWNER,  # noqa: SLF001
        role="socket",
        backing=DIND_SOCKET_BACKING,
    )
    name = f"verigym-dind-v94-socket-cleanup-{secrets.token_hex(10)}"
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
        f"{manifest.dind_socket_volume}:/verigym-socket:rw",
        "--entrypoint",
        "/bin/sh",
        manifest.dind_image_id,
        "-euc",
        script,
    ]
    completed = dind._run(command, timeout_s=60)  # noqa: SLF001
    if (
        completed.returncode != 0
        or len(completed.stdout) > MAX_TRANSFER_OUTPUT_BYTES
        or len(completed.stderr) > MAX_TRANSFER_OUTPUT_BYTES
        or not dind._remove_volume(manifest.dind_socket_volume)  # noqa: SLF001
    ):
        raise ConfigurationError("v94 socket cleanup failed")
    metadata = DIND_SOCKET_BACKING.stat()
    if (
        next(DIND_SOCKET_BACKING.iterdir(), None) is not None
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
    ):
        raise ConfigurationError("v94 socket backing cleanup was not confirmed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v94_socket_cleanup_receipt_v1",
        "identity": IDENTITY,
        "socket_volume_removed": True,
        "socket_backing_empty": True,
        "socket_backing_mode": "0700",
        "socket_backing_owner_restored": True,
        "cleanup_stdout_bytes": len(completed.stdout),
        "cleanup_stderr_bytes": len(completed.stderr),
        "raw_cleanup_output_persisted": False,
    }
    value = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "dind-cleanup-receipt.json", value)
    return value


def _best_effort_cleanup(
    *,
    dind_name: str | None,
    inner_network_created: bool,
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    root: Path,
) -> tuple[bool, str | None]:
    try:
        if dind_name is not None:
            existing = dind._run(  # noqa: SLF001
                ["docker", "container", "inspect", dind_name], timeout_s=30
            )
            if existing.returncode == 0:
                if inner_network_created:
                    _remove_internal_preflight_network(dind_name, manifest)
                if not dind._remove_container(dind_name):  # noqa: SLF001
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


def _scan_synthetic_values(root: Path, *, values: Sequence[str]) -> dict[str, Any]:
    needles = tuple(value.encode() for value in values)
    file_count = 0
    total_bytes = 0
    matches = 0
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ConfigurationError("v94 preflight output contains a symlink")
        if not stat.S_ISREG(metadata.st_mode):
            continue
        if metadata.st_size > MAX_JSON_BYTES:
            raise ConfigurationError("v94 preflight output exceeds the scan bound")
        data = path.read_bytes()
        file_count += 1
        total_bytes += len(data)
        matches += sum(data.count(needle) for needle in needles)
    return {
        "regular_file_count": file_count,
        "total_bytes": total_bytes,
        "scanned_value_count": len(needles),
        "match_count": matches,
        "values_persisted": matches != 0,
        "values_hashed": False,
        "values_printed": False,
    }


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v94 requires a non-root host identity")
    if any(name in os.environ for name in v69._PROVIDER_ENV_NAMES):  # noqa: SLF001
        raise ConfigurationError("v94 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v94 requires the default host Docker connection")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v94 requires a positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=_REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tracked != relative:
            raise ConfigurationError("v94 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v93_audit_commit, head],
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
        raise ConfigurationError("v94 requires clean merged origin/main after v93")
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
        raise ConfigurationError("v94 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path != expected or path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"v94 {label} path is unsafe")
    return path.resolve(strict=True)


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path != expected or path.is_symlink() or not path.is_dir():
        raise ConfigurationError(f"v94 {label} path is unsafe")
    return path.resolve(strict=True)


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON_BYTES:
        raise ConfigurationError("v94 JSON input is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v94 JSON input is malformed") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v94 JSON input is not an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str | None:
    base = dict(copy.deepcopy(value))
    observed = base.pop(field, None)
    if not isinstance(observed, str) or content_hash(base) != observed:
        return None
    return observed


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
