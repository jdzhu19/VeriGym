#!/usr/bin/env python3
"""Materialize the audited five-task provider execution scaffold on fresh /data2 storage."""

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
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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
    CONTROLLER_IMAGE_ID,
    CONTROLLER_IMAGE_REPO_DIGEST,
)
from verigym_hwe_bench.adapter import HweBenchSuite  # noqa: E402
from verigym_hwe_bench.models import ImageLockV2, repository_profile  # noqa: E402
from verigym_hwe_bench.prepare import load_selected_instances  # noqa: E402

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v79_dind as v79  # noqa: E402
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV69Manifest,
    DeepSeekHarnessV79DindSuccessorManifest,
    DeepSeekHarnessV81ExecutionScaffoldManifest,
    HweOfflineTaskLock,
    load_v69_manifest,
    load_v79_dind_successor_manifest,
    load_v81_execution_scaffold_manifest,
)
from verigym.hwe.materialization_preflight import (  # noqa: E402
    MaterializationHeadroomError,
    require_materialization_headroom,
)
from verigym.schemas.suite import SuiteSourceConfig  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v81-provider-execution-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V81_EXECUTION_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v81_provider_execution_scaffold_v1.json"
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
V80_AUDIT = _REPOSITORY / (
    "docs/audits/2026-09-03_deepseek-harness-v80-v79-dind-materialization-success.md"
)
ARCHIVE_ROOT = v69.ARCHIVE_ROOT
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v81-provider-execution-scaffold-v1"
)
SCRATCH_ROOT = v69.SCRATCH_ROOT
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v81")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_CLEANUP_OUTPUT_BYTES = 1024 * 1024
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
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
    "configs/training/qwen35_hwe_deepseek_harness_v81_provider_execution_scaffold_v1.json",
    "docs/audits/2026-09-03_deepseek-harness-v80-v79-dind-materialization-success.md",
    "docs/audits/2026-09-03_deepseek-harness-v81-provider-execution-scaffold-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v81_execution_scaffold.py",
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
    """Run the credential-free scaffold exactly once and retain its purpose-bound data volume."""

    _require_execution_boundary(arguments)
    manifest = load_v81_execution_scaffold_manifest(
        v69._exact_file(arguments.manifest, MANIFEST, "v81 manifest")  # noqa: SLF001
    )
    upstream_path = v69._exact_file(  # noqa: SLF001
        arguments.upstream_manifest, UPSTREAM_MANIFEST, "upstream manifest"
    )
    upstream = load_v69_manifest(upstream_path)
    v79_manifest = load_v79_dind_successor_manifest(
        v69._exact_file(arguments.v79_manifest, V79_MANIFEST, "v79 manifest")  # noqa: SLF001
    )
    contract_path = v69._exact_file(  # noqa: SLF001
        arguments.v79_provider_contract,
        V79_PROVIDER_CONTRACT,
        "v79 provider contract",
    )
    v79_contract = _load_json(contract_path)
    _validate_static_bindings(
        manifest,
        upstream,
        v79_manifest,
        v79_contract,
        upstream_path=upstream_path,
        contract_path=contract_path,
    )
    source_commit = _require_clean_merged_main()
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
    scan_workspace = root / "scan-workspaces"
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v81_execution_scaffold_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "v79_provider_contract_hash": manifest.v79_provider_contract_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "completed_task_ids": [],
        "task_receipts": [],
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
        instances = v69._patch_preflight(upstream, archive_root=archive_root, root=root)  # noqa: SLF001
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

        _validate_host_images(manifest)
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
        dind_name = f"verigym-dind-v81-{secrets.token_hex(10)}"
        metadata = dind._start_dind(  # noqa: SLF001
            name=dind_name,
            image_id=manifest.dind_image_id,
            socket_volume=manifest.dind_socket_volume,
            data_volume=manifest.dind_data_volume,
            source_volume=None,
            scratch_volume=None,
            empty_home=empty_home,
            same_path_mounts=dind._same_path_mounts({root: "rw"}),  # noqa: SLF001
            startup_timeout_s=60,
        )
        _validate_outer_sidecar(dind_name, manifest, root=root)
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        runtime_receipt = _runtime_receipt(
            manifest,
            dind_name=dind_name,
            metadata=metadata,
        )
        atomic_dump_json(root / "dind-runtime-receipt.json", runtime_receipt)
        progress.update(
            {
                "status": "offline_execution_scaffold_materialization",
                "dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
            }
        )
        _write_progress(root, progress)

        with _nested_docker(DIND_SOCKET_BACKING / "docker.sock"):
            for task in upstream.primary_tasks:
                expected_binding = _contract_binding(v79_contract, task.task_id)
                diagnostic_path = root / "command-diagnostics" / f"pr-{task.pr_number}.json"

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
                    task_lock: HweOfflineTaskLock,
                ) -> dict[str, str]:
                    return _source_binding(
                        source,
                        task_lock,
                        v79_manifest=v79_manifest,
                        expected_binding=_contract_binding(v79_contract, task_lock.task_id),
                    )

                receipt = v69._materialize_task(  # noqa: SLF001
                    task,
                    instance=instances[task.task_id],
                    archive_root=archive_root,
                    rg_binary=rg_binary,
                    rg_archive=rg_archive,
                    root=root,
                    campaign_identity=IDENTITY,
                    command_tag_version="v81",
                    build_command_runner=build_command_runner,
                    source_binding_runner=source_binding_runner,
                    scan_scratch_parent=scan_workspace,
                )
                receipt = v79._runtime_bound_task_receipt(  # noqa: SLF001
                    receipt,
                    task,
                    successor=v79_manifest,
                )
                _validate_execution_receipt(receipt, expected_binding, task, v79_manifest)
                progress["completed_task_ids"].append(task.task_id)
                progress["task_receipts"].append(receipt)
                _write_progress(root, progress)

        controller_receipt = _provision_controller_image(dind_name, manifest)
        atomic_dump_json(root / "controller-image-receipt.json", controller_receipt)
        inventory = _inner_inventory(
            dind_name,
            manifest,
            receipts=progress["task_receipts"],
        )
        atomic_dump_json(root / "execution-inventory.json", inventory)
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001

        if not dind._remove_container(dind_name):  # noqa: SLF001
            raise ConfigurationError("v81 isolated DinD daemon cleanup failed")
        dind_name = None
        cleanup = _clean_socket_volume(manifest, root=root)
        cleanup_confirmed = True
        contract = _scaffold_contract(
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
        atomic_dump_json(root / "execution-scaffold-contract.json", contract)
        progress.update(
            {
                "status": "completed_pending_independent_v82_audit",
                "provider_execution_scaffold_published": True,
                "execution_scaffold_contract_hash": contract["contract_hash"],
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
        raise ConfigurationError("v81 cleanup must complete before scaffold publication")
    report = _seal(progress)
    atomic_dump_json(root / "execution-scaffold-report.json", report)
    return report


def _validate_static_bindings(
    manifest: DeepSeekHarnessV81ExecutionScaffoldManifest,
    upstream: DeepSeekHarnessV69Manifest,
    v79_manifest: DeepSeekHarnessV79DindSuccessorManifest,
    contract: Mapping[str, Any],
    *,
    upstream_path: Path,
    contract_path: Path,
) -> None:
    contract_without_hash = dict(contract)
    observed_contract_hash = contract_without_hash.pop("contract_hash", None)
    if (
        v69._hash_file(upstream_path) != manifest.upstream_manifest_sha256  # noqa: SLF001
        or upstream.manifest_hash != manifest.upstream_manifest_hash
        or v69._hash_file(contract_path) != manifest.v79_provider_contract_sha256  # noqa: SLF001
        or observed_contract_hash != manifest.v79_provider_contract_hash
        or content_hash(contract_without_hash) != observed_contract_hash
        or v69._hash_file(V80_AUDIT) != manifest.v80_audit_sha256  # noqa: SLF001
        or manifest.v80_audit_commit != "d522b1d451bace29e80b2af60ad31a4ba74774ec"
        or manifest.v80_post_merge_main_run_id != 33_735_930_859
    ):
        raise ConfigurationError("v81 predecessor evidence binding changed")
    expected_schedule = [task.task_id for task in upstream.primary_tasks]
    if (
        contract.get("format_id") != "verigym_deepseek_harness_hwe_v79_dind_provider_contract_v1"
        or contract.get("identity") != v79.IDENTITY
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
        raise ConfigurationError("v81 v79 provider contract is not eligible")
    bindings = contract.get("task_bindings")
    if (
        not isinstance(bindings, list)
        or len(bindings) != len(expected_schedule)
        or [item.get("task_id") for item in bindings if isinstance(item, dict)] != expected_schedule
    ):
        raise ConfigurationError("v81 v79 task binding inventory changed")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v80_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v81 requires the merged v80 audit")
    if (
        manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.dind_data_volume == v79_manifest.dind_data_volume
        or manifest.dind_data_backing == v79_manifest.dind_data_backing
        or manifest.dind_image_id != v79_manifest.dind_image_id
        or manifest.dind_repository_digest != v79_manifest.dind_repository_digest
        or manifest.dind_server_version != v79_manifest.dind_server_version
        or manifest.v79_data_volume_reused is not False
        or manifest.host_docker_root_used_for_task_layers is not False
        or manifest.provider_successor_reopen_budget != 1
    ):
        raise ConfigurationError("v81 fresh purpose-bound DinD identity changed")


def _source_binding(
    source: Path,
    task: HweOfflineTaskLock,
    *,
    v79_manifest: DeepSeekHarnessV79DindSuccessorManifest,
    expected_binding: Mapping[str, Any],
) -> dict[str, str]:
    lock_path = source / "image-lock.json"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ConfigurationError("v81 prepared source lacks a safe image lock")
    lock = ImageLockV2.model_validate_json(lock_path.read_bytes())
    dataset = v69._contained_file(  # noqa: SLF001
        ARCHIVE_ROOT, task.dataset_relpath, 512 * 1024 * 1024
    )
    selected = load_selected_instances(dataset, {task.instance_id})
    if (
        len(lock.entries) != 1
        or lock.official_dataset_sha256 != task.dataset_sha256
        or v69._hash_file(dataset) != task.dataset_sha256  # noqa: SLF001
        or v69._selected_row_hash(dataset, task.instance_id)  # noqa: SLF001
        != task.selected_row_sha256
        or len(selected) != 1
    ):
        raise ConfigurationError("v81 prepared source public record inventory changed")
    instance = selected[0]
    entry = lock.entries[0]
    suite = HweBenchSuite().with_source(
        SuiteSourceConfig(source_root=source, variant="repo-repair-v1")
    )
    references = list(suite.discover())
    if len(references) != 1:
        raise ConfigurationError("v81 prepared source exposed multiple tasks")
    loaded = suite.load_task(references[0])
    source_lock_sha256 = hash_bytes(lock_path.read_bytes())
    runtime_base = v79_manifest.runtime_base_commit_overrides.get(task.task_id, task.source_commit)
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
        or entry.base_commit != runtime_base
        or entry.repository_profile_hash != profile.profile_hash
        or loaded.source.commit != runtime_base
        or loaded.source.content_hash != entry.repository_hash
        or content_hash(loaded) != expected_binding.get("task_hash")
        or entry.repository_hash != expected_binding.get("source_hash")
        or source_lock_sha256 != expected_binding.get("prepared_source_image_lock_sha256")
        or runtime_base != expected_binding.get("runtime_base_commit")
    ):
        raise ConfigurationError("v81 source or audited runtime binding changed")
    return {
        "task_hash": content_hash(loaded),
        "source_hash": entry.repository_hash,
        "source_image_lock_sha256": source_lock_sha256,
        "runtime_base_commit": runtime_base,
    }


def _validate_execution_receipt(
    receipt: Mapping[str, Any],
    expected: Mapping[str, Any],
    task: HweOfflineTaskLock,
    v79_manifest: DeepSeekHarnessV79DindSuccessorManifest,
) -> None:
    receipt_without_hash = dict(receipt)
    receipt_hash = receipt_without_hash.pop("task_receipt_hash", None)
    fields = (
        "task_id",
        "task_hash",
        "source_hash",
        "source_commit",
        "dataset_base_commit",
        "runtime_base_commit",
        "runtime_base_commit_override_applied",
        "official_verifier_image",
        "agent_toolchain_id",
        "toolchain_profile_id",
    )
    if (
        receipt_hash != content_hash(receipt_without_hash)
        or any(receipt.get(field) != expected.get(field) for field in fields)
        or receipt.get("base_failed") is not True
        or receipt.get("base_infrastructure_error") is not False
        or receipt.get("reference_passed") is not True
        or receipt.get("verifier_network") != "none"
        or receipt.get("agent_command_network") != "none"
        or receipt.get("provider_calls") != 0
        or receipt.get("model_process_count") != 0
    ):
        raise ConfigurationError("v81 execution receipt differs from audited task binding")
    v79._require_eligible_task(  # noqa: SLF001
        dict(receipt), task, successor=v79_manifest
    )


def _contract_binding(contract: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    bindings = contract.get("task_bindings")
    if not isinstance(bindings, list):
        raise ConfigurationError("v81 contract binding inventory is malformed")
    matches = [
        item for item in bindings if isinstance(item, dict) and item.get("task_id") == task_id
    ]
    if len(matches) != 1:
        raise ConfigurationError("v81 contract does not contain one exact task binding")
    return dict(matches[0])


def _content_free_bounded_command(
    command: list[str],
    *,
    timeout: int,
    receipt_path: Path,
) -> dict[str, Any]:
    if timeout <= 0 or timeout > 3600 or not command:
        raise ConfigurationError("v81 build-command diagnostic boundary is invalid")
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
        len(stdout) <= v79.MAX_COMMAND_DIAGNOSTIC_BYTES
        and len(stderr) <= v79.MAX_COMMAND_DIAGNOSTIC_BYTES
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
        "maximum_output_bytes": v79.MAX_COMMAND_DIAGNOSTIC_BYTES,
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
        raise ConfigurationError("v81 bounded build command failed")
    return receipt


def _validate_host_images(manifest: DeepSeekHarnessV81ExecutionScaffoldManifest) -> None:
    v79._validate_dind_image(  # noqa: SLF001
        load_v79_dind_successor_manifest(V79_MANIFEST)
    )
    completed = subprocess.run(
        ["docker", "image", "inspect", manifest.controller_image_id, "--format", "{{json .}}"],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    try:
        image = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v81 controller image inspection is malformed") from exc
    expected_repo_digest = "node@" + manifest.controller_image_repository_digest
    if (
        completed.returncode != 0
        or manifest.controller_image_id != CONTROLLER_IMAGE_ID
        or expected_repo_digest != CONTROLLER_IMAGE_REPO_DIGEST
        or image.get("Id") != manifest.controller_image_id
        or expected_repo_digest not in image.get("RepoDigests", [])
    ):
        raise ConfigurationError("v81 host controller image identity changed")


def _provision_controller_image(
    dind_name: str,
    manifest: DeepSeekHarnessV81ExecutionScaffoldManifest,
) -> dict[str, Any]:
    before = dind._inner(  # noqa: SLF001
        ["image", "inspect", manifest.controller_image_id],
        container=dind_name,
        timeout_s=30,
    )
    if before.returncode == 0:
        raise ConfigurationError("v81 inner controller image was not provisioned from fresh state")
    stdout, stderr = dind._pipe_image(  # noqa: SLF001
        container=dind_name,
        image_id=manifest.controller_image_id,
        timeout_s=1800,
    )
    transfer_output_bounded = (
        len(stdout) <= MAX_CLEANUP_OUTPUT_BYTES and len(stderr) <= MAX_CLEANUP_OUTPUT_BYTES
    )
    if not transfer_output_bounded:
        raise ConfigurationError("v81 controller transfer output exceeded its bound")
    inspected = dind._inner(  # noqa: SLF001
        ["image", "inspect", manifest.controller_image_id, "--format", "{{json .}}"],
        container=dind_name,
        timeout_s=30,
    )
    try:
        image = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v81 inner controller image inspection is malformed") from exc
    expected_repo_digest = "node@" + manifest.controller_image_repository_digest
    repo_digests = image.get("RepoDigests")
    if (
        inspected.returncode != 0
        or image.get("Id") != manifest.controller_image_id
        or image.get("RepoTags") != ["node:22.19.0-bookworm-slim"]
        or not isinstance(repo_digests, list)
        or any(item != expected_repo_digest for item in repo_digests)
    ):
        raise ConfigurationError("v81 inner controller image identity changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v81_controller_image_receipt_v1",
        "identity": IDENTITY,
        "controller_image_id": manifest.controller_image_id,
        "controller_image_repository_digest": manifest.controller_image_repository_digest,
        "transfer": manifest.controller_transfer,
        "outer_source_image_read_only": True,
        "outer_source_repository_digest_verified": True,
        "inner_image_id_verified": True,
        "inner_repository_tag": "node:22.19.0-bookworm-slim",
        "inner_repository_digest_metadata_preserved": bool(repo_digests),
        "transfer_archive_persisted": False,
        "transfer_stdout_bytes": len(stdout),
        "transfer_stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "transfer_stderr_bytes": len(stderr),
        "transfer_stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "transfer_output_bounded": True,
        "raw_transfer_output_persisted": False,
        "provider_environment_present": False,
        "registry_accessed": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _inner_inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV81ExecutionScaffoldManifest,
    *,
    receipts: list[dict[str, Any]],
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
            *(str(item["official_verifier_image"]) for item in receipts),
            *(str(item["agent_command_image"]) for item in receipts),
        }
    )
    if (
        result.returncode != 0
        or any(_DIGEST.fullmatch(item) is None for item in observed)
        or not set(required).issubset(observed)
    ):
        raise ConfigurationError("v81 inner image inventory is incomplete or malformed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v81_execution_inventory_v1",
        "identity": IDENTITY,
        "required_image_ids": required,
        "observed_image_ids": observed,
        "required_images_present": True,
        "provider_inner_network": manifest.provider_inner_network,
        "provider_inner_network_created": False,
        "inner_container_inventory_empty": True,
        "inner_volume_inventory_empty": True,
        "provider_calls": 0,
        "model_process_count": 0,
    }
    return {**base, "inventory_hash": content_hash(base)}


def _runtime_receipt(
    manifest: DeepSeekHarnessV81ExecutionScaffoldManifest,
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
        raise ConfigurationError("v81 /data2 DinD runtime identity changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v81_dind_runtime_receipt_v1",
        "identity": IDENTITY,
        "dind_image_id": manifest.dind_image_id,
        "storage_driver": metadata.get("Driver"),
        "default_runtime": metadata.get("DefaultRuntime"),
        "docker_root_dir": metadata.get("DockerRootDir"),
        "data_volume": manifest.dind_data_volume,
        "data_backing": manifest.dind_data_backing,
        "host_and_inner_data_root_identity": expected_identity,
        "host_and_inner_data_root_same_inode": True,
        "outer_network": "none",
        "inner_bridge_disabled_during_scaffold": True,
        "host_docker_root_used_for_task_layers": False,
        "v79_data_volume_reused": False,
        "provider_calls": 0,
        "model_process_count": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _validate_outer_sidecar(
    name: str,
    manifest: DeepSeekHarnessV81ExecutionScaffoldManifest,
    *,
    root: Path,
) -> None:
    value = dind._inspect("container", name)  # noqa: SLF001
    host = value.get("HostConfig")
    config = value.get("Config")
    mounts = value.get("Mounts")
    if not isinstance(host, dict) or not isinstance(config, dict) or not isinstance(mounts, list):
        raise ConfigurationError("v81 outer DinD inspection is malformed")
    environment = config.get("Env")
    by_destination = {item.get("Destination"): item for item in mounts if isinstance(item, dict)}
    if (
        host.get("Privileged") is not True
        or host.get("NetworkMode") != "none"
        or set(by_destination)
        != {
            "/var/lib/docker",
            "/var/run",
            str(root),
            "/verigym-host-sentinel",
        }
        or by_destination["/var/lib/docker"].get("Name") != manifest.dind_data_volume
        or by_destination["/var/run"].get("Name") != manifest.dind_socket_volume
        or not isinstance(environment, list)
        or any(
            item.partition("=")[0] in v69._PROVIDER_ENV_NAMES  # noqa: SLF001
            for item in environment
            if isinstance(item, str)
        )
        or "/var/run/docker.sock" in by_destination
    ):
        raise ConfigurationError("v81 outer DinD isolation controls changed")


def _create_dind_backings(manifest: DeepSeekHarnessV81ExecutionScaffoldManifest) -> None:
    if (
        Path(manifest.dind_data_backing) != DIND_DATA_BACKING
        or Path(manifest.dind_socket_backing) != DIND_SOCKET_BACKING
        or DIND_PARENT.exists()
        or DIND_PARENT.is_symlink()
    ):
        raise ConfigurationError("v81 DinD backing identity must be new and exact")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    for path in (DIND_PARENT, DIND_DATA_BACKING, DIND_SOCKET_BACKING):
        path.chmod(0o700)


@contextmanager
def _nested_docker(socket: Path) -> Iterator[None]:
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v81 host Docker routing changed before nested execution")
    if socket.is_symlink() or not socket.exists() or not socket.is_socket():
        raise ConfigurationError("v81 nested Docker socket is unavailable or unsafe")
    os.environ["DOCKER_HOST"] = f"unix://{socket}"
    try:
        yield
    finally:
        os.environ.pop("DOCKER_HOST", None)


def _clean_socket_volume(
    manifest: DeepSeekHarnessV81ExecutionScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    dind._bind_backed_volume(  # noqa: SLF001
        manifest.dind_socket_volume,
        owner=dind._DIND_OWNER,  # noqa: SLF001
        role="socket",
        backing=DIND_SOCKET_BACKING,
    )
    name = f"verigym-dind-v81-socket-cleanup-{secrets.token_hex(10)}"
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
    bounded = (
        len(completed.stdout) <= MAX_CLEANUP_OUTPUT_BYTES
        and len(completed.stderr) <= MAX_CLEANUP_OUTPUT_BYTES
    )
    if (
        completed.returncode != 0
        or not bounded
        or not dind._remove_volume(  # noqa: SLF001
            manifest.dind_socket_volume
        )
    ):
        raise ConfigurationError("v81 socket cleanup failed")
    metadata = DIND_SOCKET_BACKING.stat()
    if (
        next(DIND_SOCKET_BACKING.iterdir(), None) is not None
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
    ):
        raise ConfigurationError("v81 socket backing cleanup was not confirmed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v81_socket_cleanup_receipt_v1",
        "identity": IDENTITY,
        "socket_volume": manifest.dind_socket_volume,
        "socket_backing": manifest.dind_socket_backing,
        "network": "none",
        "read_only_root": True,
        "cap_drop": ["ALL"],
        "cap_add": ["CHOWN", "DAC_OVERRIDE", "FOWNER"],
        "returncode": completed.returncode,
        "stdout_bytes": len(completed.stdout),
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_bytes": len(completed.stderr),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
        "raw_output_persisted": False,
        "socket_volume_removed": True,
        "socket_backing_identity_restored": True,
        "cleanup_confirmed": True,
    }
    receipt = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "dind-cleanup-receipt.json", receipt)
    return receipt


def _scaffold_contract(
    manifest: DeepSeekHarnessV81ExecutionScaffoldManifest,
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
    if len(receipts) != 5 or [item.get("task_id") for item in receipts] != schedule:
        raise ConfigurationError("v81 refuses a partial execution scaffold contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v81_execution_scaffold_contract_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "v79_provider_contract_hash": manifest.v79_provider_contract_hash,
        "v80_audit_commit": manifest.v80_audit_commit,
        "v80_post_merge_main_run_id": manifest.v80_post_merge_main_run_id,
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
        "execution_inventory_hash": inventory["inventory_hash"],
        "dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
        "dind_cleanup_receipt_hash": cleanup["receipt_hash"],
        "dind_cleanup_confirmed": True,
        "dind_data_volume": manifest.dind_data_volume,
        "dind_data_backing": manifest.dind_data_backing,
        "host_docker_root_used_for_task_layers": False,
        "v79_data_volume_reused": False,
        "provider_successor_identity": manifest.provider_successor_identity,
        "provider_successor_reopen_budget": 1,
        "provider_successor_reopen_count": 0,
        "provider_outer_network": manifest.provider_outer_network,
        "provider_inner_network": manifest.provider_inner_network,
        "provider_inner_network_created": False,
        "provider_execution_scaffold_published": True,
        "provider_execution_authorized": False,
        "requires_independent_v82_audit": True,
        "provider_calls": 0,
        "model_process_count": 0,
        **_closed_training_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v81 requires a non-root host identity")
    if any(name in os.environ for name in v69._PROVIDER_ENV_NAMES):  # noqa: SLF001
        raise ConfigurationError("v81 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v81 requires the default host Docker connection")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v81 requires a positive post-merge main run ID")


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
            raise ConfigurationError("v81 required merged path is not tracked")
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
        raise ConfigurationError("v81 requires clean merged origin/main")
    return head


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink() or path != OUTPUT_ROOT:
        raise ConfigurationError("v81 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON_BYTES:
        raise ConfigurationError("v81 JSON input is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v81 JSON input is malformed") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v81 JSON input is not an object")
    return value


def _best_effort_cleanup(
    *,
    dind_name: str | None,
    manifest: DeepSeekHarnessV81ExecutionScaffoldManifest,
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
            return True, receipt["receipt_hash"]
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


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(value)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
