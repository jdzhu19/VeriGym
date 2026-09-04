from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    V69_CVA6_FALLBACK_TASK_IDS,
    V69_IBEX_FALLBACK_TASK_IDS,
    V69_OPEN_TOOL_TASK_ID,
    V69_PRIMARY_TASK_IDS,
    DeepSeekHarnessMatrixAttempt,
    DeepSeekHarnessV69Manifest,
    DeepSeekHarnessV71DindSuccessorManifest,
    DeepSeekHarnessV73DindSuccessorManifest,
    DeepSeekHarnessV77DindSuccessorManifest,
    DeepSeekHarnessV79DindSuccessorManifest,
    DeepSeekHarnessV81ExecutionScaffoldManifest,
    DeepSeekHarnessV83ExecutionScaffoldManifest,
    DeepSeekHarnessV85OfficialMatrixManifest,
    DeepSeekHarnessV87FreshScaffoldManifest,
    DeepSeekHarnessV90FreshScaffoldManifest,
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    DeepSeekHarnessV115ExplicitNestedDockerSocketScaffoldManifest,
    DeepSeekHarnessV118ExplicitInnerInventoryScaffoldManifest,
    DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
    DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
    DeepSeekHarnessV127ReadinessGatedScaffoldManifest,
    DeepSeekHarnessV130BoundedCommandScanProbeManifest,
    DeepSeekHarnessV132BoundedScanScaffoldManifest,
    DeepSeekHarnessV136CommandRuntimeDiagnosticManifest,
    DeepSeekHarnessV138FreshExplicitScaffoldManifest,
    HweAdmissionPlanes,
    HweOfflineTaskLock,
    inspect_offline_image_archive,
    load_v81_execution_scaffold_manifest,
    load_v83_execution_scaffold_manifest,
    load_v85_official_matrix_manifest,
    load_v87_fresh_scaffold_manifest,
    load_v90_fresh_scaffold_manifest,
    load_v92_official_matrix_manifest,
    load_v94_runtime_complete_scaffold_manifest,
    load_v97_rebuild_identity_scaffold_manifest,
    load_v100_inventory_timeout_scaffold_manifest,
    load_v103_inspect_output_bound_scaffold_manifest,
    load_v106_fresh_inventory_binding_scaffold_manifest,
    load_v109_progress_writer_scaffold_manifest,
    load_v112_data2_control_headroom_scaffold_manifest,
    load_v115_explicit_nested_docker_socket_scaffold_manifest,
    load_v118_explicit_inner_inventory_scaffold_manifest,
    load_v121_bounded_dind_start_diagnostic_manifest,
    load_v123_bounded_dind_identity_probe_manifest,
    load_v125_bounded_dind_readiness_probe_manifest,
    load_v127_readiness_gated_scaffold_manifest,
    load_v130_bounded_command_scan_probe_manifest,
    load_v132_bounded_scan_scaffold_manifest,
    load_v136_command_runtime_diagnostic_manifest,
    load_v138_fresh_explicit_scaffold_manifest,
    migration_conclusions,
    new_matrix_state,
    record_matrix_attempt,
    require_toolchain_verifier_binding,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_V85_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v85_official_matrix_v1.json"
)
_V87_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v87_fresh_scaffold_successor_v1.json"
)
_V90_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v90_fresh_scaffold_timeout_successor_v1.json"
)
_V92_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v92_official_matrix_v1.json"
)
_V103_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v103_inspect_output_bound_scaffold_v1.json"
)
_V94_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v94_runtime_complete_scaffold_v1.json"
)
_V97_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v97_rebuild_identity_scaffold_v1.json"
)
_V100_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v100_inventory_timeout_scaffold_v1.json"
)
_V106_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold_v1.json"
)
_V109_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v109_progress_writer_scaffold_v1.json"
)
_V112_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v112_data2_control_headroom_scaffold_v1.json"
)
_V115_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/"
    "qwen35_hwe_deepseek_harness_v115_explicit_nested_docker_socket_scaffold_v1.json"
)
_V136_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v136_command_runtime_diagnostic_v1.json"
)
_V138_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v138_fresh_explicit_scaffold_v1.json"
)
_V118_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold_v1.json"
)
_V121_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v121_bounded_dind_start_diagnostic_v1.json"
)
_V123_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v123_bounded_dind_identity_probe_v1.json"
)
_V125_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v125_bounded_dind_readiness_probe_v1.json"
)
_V127_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v127_readiness_gated_scaffold_v1.json"
)
_V130_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v130_bounded_command_scan_create_probe_v1.json"
)
_V132_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v132_bounded_scan_scaffold_v1.json"
)


def _repository_parts(task_id: str) -> tuple[str, str, int]:
    pr = int(task_id.rsplit("-", 1)[1])
    if "lowRISC__ibex" in task_id:
        return "ibex", "lowRISC/ibex", pr
    return "cva6", "openhwgroup/cva6", pr


def _task_lock(task_id: str) -> dict[str, object]:
    repository, instance_repository, pr = _repository_parts(task_id)
    slug = "lowrisc_m_ibex" if repository == "ibex" else "openhwgroup_m_cva6"
    digest = "sha256:" + ("1" if repository == "ibex" else "2") * 64
    return {
        "task_id": task_id,
        "instance_id": f"{instance_repository}:pr-{pr}",
        "repository": repository,
        "pr_number": pr,
        "dataset_relpath": (
            "datasets/lowRISC__ibex.jsonl"
            if repository == "ibex"
            else "datasets/openhwgroup__cva6.jsonl"
        ),
        "dataset_sha256": "3" * 64,
        "selected_row_sha256": "4" * 64,
        "source_commit": "5" * 40,
        "archive_relpath": f"docker-tar-archives/{slug}/pr-{pr}.tar",
        "archive_sha256_relpath": f"docker-tar-archives/{slug}/pr-{pr}.tar.sha256",
        "archive_sha256": "6" * 64,
        "registry_digest_relpath": f"digest-locks/{slug}/pr-{pr}.digest",
        "registry_reference": f"ghcr.io/pku-liang/{slug}:pr-{pr}",
        "registry_manifest_digest": "sha256:" + "7" * 64,
        "image_config_digest": digest,
        "archive_repository_tag": f"ghcr.io/pku-liang/{slug}:i-was-a-digest",
        "official_verifier_image": digest,
        "agent_toolchain_id": "hwe-official-task-toolchain-v1",
    }


def _manifest_payload() -> dict[str, object]:
    available = [
        *[(task_id, "planned_primary") for task_id in V69_PRIMARY_TASK_IDS],
        *[(task_id, "zero_provider_fallback") for task_id in V69_IBEX_FALLBACK_TASK_IDS],
        *[(task_id, "archive_incomplete_fallback") for task_id in V69_CVA6_FALLBACK_TASK_IDS],
        (V69_OPEN_TOOL_TASK_ID, "alternative_toolchain_reserved"),
    ]
    base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v69_manifest_v1",
        "identity": "deepseek-harness-hwe-v69-multitask-zero-provider-v1",
        "primary_tasks": [_task_lock(task_id) for task_id in V69_PRIMARY_TASK_IDS],
        "ibex_fallback_order": list(V69_IBEX_FALLBACK_TASK_IDS),
        "cva6_fallback_order": list(V69_CVA6_FALLBACK_TASK_IDS),
        "alternative_toolchain_task_id": V69_OPEN_TOOL_TASK_ID,
        "task_ledger": [
            {
                "task_id": task_id,
                "disposition": disposition,
                "provider_boundary_crossed": False,
                "provider_consumed": False,
            }
            for task_id, disposition in available
        ]
        + [
            {
                "task_id": "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-166",
                "disposition": "provider_consumed",
                "provider_boundary_crossed": True,
                "provider_consumed": True,
            }
        ],
        "provider_clients_available": False,
        "registry_access_allowed": False,
        "partial_archive_allowed": False,
        "atomic_provider_contract": True,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    return {**base, "manifest_hash": content_hash(base)}


def test_v69_manifest_freezes_task_and_fallback_order() -> None:
    manifest = DeepSeekHarnessV69Manifest.model_validate(_manifest_payload())
    assert tuple(item.task_id for item in manifest.primary_tasks) == V69_PRIMARY_TASK_IDS

    changed = _manifest_payload()
    tasks = list(changed["primary_tasks"])
    tasks[0], tasks[1] = tasks[1], tasks[0]
    changed["primary_tasks"] = tasks
    changed["manifest_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError, match="primary task order"):
        DeepSeekHarnessV69Manifest.model_validate(changed)


def test_v69_manifest_rejects_historical_or_consumed_primary() -> None:
    changed = _manifest_payload()
    ledger = list(changed["task_ledger"])
    ledger[0] = {
        "task_id": V69_PRIMARY_TASK_IDS[0],
        "disposition": "provider_consumed",
        "provider_boundary_crossed": True,
        "provider_consumed": True,
    }
    changed["task_ledger"] = ledger
    changed["manifest_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError, match="planned task dispositions"):
        DeepSeekHarnessV69Manifest.model_validate(changed)


def test_v71_dind_successor_manifest_freezes_data2_storage_and_closed_flags() -> None:
    base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v71_dind_successor_manifest_v1",
        "identity": "deepseek-harness-hwe-v71-dind-zero-provider-successor-v1",
        "upstream_manifest_sha256": "1" * 64,
        "upstream_manifest_hash": "2" * 64,
        "predecessor_identity": "deepseek-harness-hwe-v69-multitask-zero-provider-v1",
        "predecessor_report_sha256": "3" * 64,
        "predecessor_report_hash": "4" * 64,
        "predecessor_audit_sha256": "5" * 64,
        "predecessor_audit_commit": "6" * 40,
        "dind_image_id": "sha256:" + "7" * 64,
        "dind_repository_digest": "sha256:" + "8" * 64,
        "dind_server_version": "23.0.6",
        "dind_storage_driver": "vfs",
        "dind_default_runtime": "runc",
        "dind_data_volume": "verigym-deepseek-harness-v71-dind-data",
        "dind_socket_volume": "verigym-deepseek-harness-v71-dind-socket",
        "dind_data_backing": "/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/data",
        "dind_socket_backing": "/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/socket",
        "outer_dind_network": "none",
        "host_docker_root_used_for_task_layers": False,
        "provider_clients_available": False,
        "registry_access_allowed": False,
        "partial_archive_allowed": False,
        "atomic_provider_contract": True,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    manifest = DeepSeekHarnessV71DindSuccessorManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.host_docker_root_used_for_task_layers is False
    assert manifest.provider_clients_available is False

    changed = dict(base)
    changed["dind_data_backing"] = "/data/docker"
    with pytest.raises(ValueError, match="literal"):
        DeepSeekHarnessV71DindSuccessorManifest.model_validate(
            {**changed, "manifest_hash": content_hash(changed)}
        )


def test_v73_dind_successor_manifest_forbids_v71_storage_reuse() -> None:
    base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v73_dind_successor_manifest_v1",
        "identity": "deepseek-harness-hwe-v73-dind-zero-provider-successor-v1",
        "upstream_manifest_sha256": "1" * 64,
        "upstream_manifest_hash": "2" * 64,
        "predecessor_identity": "deepseek-harness-hwe-v71-dind-zero-provider-successor-v1",
        "predecessor_report_sha256": "3" * 64,
        "predecessor_report_hash": "4" * 64,
        "predecessor_audit_sha256": "5" * 64,
        "predecessor_audit_commit": "6" * 40,
        "retired_dind_data_volume": "verigym-deepseek-harness-v71-dind-data",
        "retired_dind_data_backing": ("/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/data"),
        "dind_image_id": "sha256:" + "7" * 64,
        "dind_repository_digest": "sha256:" + "8" * 64,
        "dind_server_version": "23.0.6",
        "dind_storage_driver": "vfs",
        "dind_default_runtime": "runc",
        "dind_data_volume": "verigym-deepseek-harness-v73-dind-data",
        "dind_socket_volume": "verigym-deepseek-harness-v73-dind-socket",
        "dind_data_backing": "/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/data",
        "dind_socket_backing": "/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/socket",
        "command_diagnostic_max_bytes": 33554432,
        "socket_cleanup_strategy": "networkless-readonly-fixed-path-v1",
        "outer_dind_network": "none",
        "host_docker_root_used_for_task_layers": False,
        "provider_clients_available": False,
        "registry_access_allowed": False,
        "partial_archive_allowed": False,
        "atomic_provider_contract": True,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    manifest = DeepSeekHarnessV73DindSuccessorManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )
    assert manifest.dind_data_volume != manifest.retired_dind_data_volume
    assert manifest.dind_data_backing != manifest.retired_dind_data_backing
    assert manifest.command_diagnostic_max_bytes == 32 * 1024 * 1024

    changed = dict(base)
    changed["dind_data_volume"] = "verigym-deepseek-harness-v71-dind-data"
    with pytest.raises(ValueError, match="literal"):
        DeepSeekHarnessV73DindSuccessorManifest.model_validate(
            {**changed, "manifest_hash": content_hash(changed)}
        )


def test_v77_dind_successor_binds_exact_cva6_profile_repair_and_fresh_storage() -> None:
    base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v77_dind_successor_manifest_v1",
        "identity": "deepseek-harness-hwe-v77-dind-zero-provider-successor-v1",
        "upstream_manifest_sha256": "1" * 64,
        "upstream_manifest_hash": "2" * 64,
        "predecessor_identity": "deepseek-harness-hwe-v75-dind-zero-provider-successor-v1",
        "predecessor_report_sha256": "3" * 64,
        "predecessor_report_hash": "4" * 64,
        "predecessor_audit_sha256": "5" * 64,
        "predecessor_audit_commit": "6" * 40,
        "retired_dind_data_volume": "verigym-deepseek-harness-v75-dind-data",
        "retired_dind_data_backing": ("/data2/jiadongzhu/docker/deepseek-harness-hwe-v75/data"),
        "dind_image_id": "sha256:" + "7" * 64,
        "dind_repository_digest": "sha256:" + "8" * 64,
        "dind_server_version": "23.0.6",
        "dind_storage_driver": "vfs",
        "dind_default_runtime": "runc",
        "dind_data_volume": "verigym-deepseek-harness-v77-dind-data",
        "dind_socket_volume": "verigym-deepseek-harness-v77-dind-socket",
        "dind_data_backing": "/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/data",
        "dind_socket_backing": "/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/socket",
        "scanner_workspace_policy": "successor-output-root-only-v1",
        "scanner_workspace_relative_path": "scan-workspaces",
        "source_profile_repair": "cva6-task-image-tool-bridge-exclusion-v1",
        "cva6_repository_profile_id": "hwe-openhwgroup-cva6-v1",
        "cva6_repository_profile_hash": "9" * 64,
        "cva6_workspace_tool_bridge_exclusion": ".hwe_tools",
        "escaping_symlink_policy": "reject-unlisted-v1",
        "command_diagnostic_max_bytes": 33554432,
        "socket_cleanup_strategy": "networkless-readonly-fixed-path-v2",
        "outer_dind_network": "none",
        "host_docker_root_used_for_task_layers": False,
        "provider_clients_available": False,
        "registry_access_allowed": False,
        "partial_archive_allowed": False,
        "atomic_provider_contract": True,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    manifest = DeepSeekHarnessV77DindSuccessorManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )
    assert manifest.dind_data_volume != manifest.retired_dind_data_volume
    assert manifest.cva6_workspace_tool_bridge_exclusion == ".hwe_tools"
    assert manifest.escaping_symlink_policy == "reject-unlisted-v1"

    changed = dict(base)
    changed["cva6_workspace_tool_bridge_exclusion"] = "tools"
    with pytest.raises(ValueError, match="literal"):
        DeepSeekHarnessV77DindSuccessorManifest.model_validate(
            {**changed, "manifest_hash": content_hash(changed)}
        )


def test_v79_dind_successor_binds_only_pr_2017_runtime_override() -> None:
    base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v79_dind_successor_manifest_v1",
        "identity": "deepseek-harness-hwe-v79-dind-zero-provider-successor-v1",
        "upstream_manifest_sha256": "1" * 64,
        "upstream_manifest_hash": "2" * 64,
        "predecessor_identity": "deepseek-harness-hwe-v77-dind-zero-provider-successor-v1",
        "predecessor_report_sha256": "3" * 64,
        "predecessor_report_hash": "4" * 64,
        "predecessor_audit_sha256": "5" * 64,
        "predecessor_audit_commit": "6" * 40,
        "predecessor_prepared_source_image_lock_sha256": "7" * 64,
        "predecessor_pr_2017_source_hash": "8" * 64,
        "predecessor_pr_2017_task_bundle_hash": "9" * 64,
        "pr_2711_offline_archive_receipt_hash": "a" * 64,
        "retired_dind_data_volume": "verigym-deepseek-harness-v77-dind-data",
        "retired_dind_data_backing": ("/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/data"),
        "dind_image_id": "sha256:" + "b" * 64,
        "dind_repository_digest": "sha256:" + "c" * 64,
        "dind_server_version": "23.0.6",
        "dind_storage_driver": "vfs",
        "dind_default_runtime": "runc",
        "dind_data_volume": "verigym-deepseek-harness-v79-dind-data",
        "dind_socket_volume": "verigym-deepseek-harness-v79-dind-socket",
        "dind_data_backing": "/data2/jiadongzhu/docker/deepseek-harness-hwe-v79/data",
        "dind_socket_backing": "/data2/jiadongzhu/docker/deepseek-harness-hwe-v79/socket",
        "scanner_workspace_policy": "successor-output-root-only-v1",
        "scanner_workspace_relative_path": "scan-workspaces",
        "source_profile_repair": "cva6-task-image-tool-bridge-exclusion-v1",
        "cva6_repository_profile_id": "hwe-openhwgroup-cva6-v1",
        "cva6_repository_profile_hash": "d" * 64,
        "cva6_workspace_tool_bridge_exclusion": ".hwe_tools",
        "escaping_symlink_policy": "reject-unlisted-v1",
        "runtime_baseline_repair": "pr-2017-digest-locked-runtime-marker-v1",
        "runtime_baseline_policy": "exact-task-override-otherwise-dataset-base-v1",
        "runtime_base_commit_overrides": {
            "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017": (
                "d87707a81fe8926dda2deff844797a491811983a"
            )
        },
        "tasks_without_runtime_override_match_dataset_base": True,
        "command_diagnostic_max_bytes": 33554432,
        "socket_cleanup_strategy": "networkless-readonly-fixed-path-v2",
        "outer_dind_network": "none",
        "host_docker_root_used_for_task_layers": False,
        "provider_clients_available": False,
        "registry_access_allowed": False,
        "partial_archive_allowed": False,
        "atomic_provider_contract": True,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    manifest = DeepSeekHarnessV79DindSuccessorManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )
    assert manifest.dind_data_volume != manifest.retired_dind_data_volume
    assert list(manifest.runtime_base_commit_overrides) == [
        "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017"
    ]

    changed = dict(base)
    changed["runtime_base_commit_overrides"] = {
        "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711": (
            "5518a41c08a1949c606d54b9ac631e8f7635e7f3"
        )
    }
    with pytest.raises(ValueError, match="exact PR-2017 runtime override"):
        DeepSeekHarnessV79DindSuccessorManifest.model_validate(
            {**changed, "manifest_hash": content_hash(changed)}
        )


def test_checked_in_v81_scaffold_manifest_is_hash_bound_and_purpose_limited() -> None:
    path = _REPOSITORY_ROOT / (
        "configs/training/qwen35_hwe_deepseek_harness_v81_provider_execution_scaffold_v1.json"
    )
    manifest = load_v81_execution_scaffold_manifest(path)
    assert isinstance(manifest, DeepSeekHarnessV81ExecutionScaffoldManifest)
    assert manifest.dind_data_backing.startswith("/data2/jiadongzhu/docker/")
    assert manifest.v79_data_volume_reused is False
    assert manifest.provider_successor_reopen_budget == 1
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v83-official-matrix-v1"
    assert manifest.provider_clients_available is False
    assert manifest.formal_collection_allowed is False

    value = manifest.model_dump(mode="json")
    with pytest.raises(ValueError, match="content hash changed"):
        DeepSeekHarnessV81ExecutionScaffoldManifest.model_validate(
            {**value, "v80_audit_sha256": "0" * 64}
        )


def test_checked_in_v83_scaffold_successor_is_hash_bound_and_fresh() -> None:
    path = _REPOSITORY_ROOT / (
        "configs/training/qwen35_hwe_deepseek_harness_v83_controller_tag_successor_v1.json"
    )
    manifest = load_v83_execution_scaffold_manifest(path)
    assert isinstance(manifest, DeepSeekHarnessV83ExecutionScaffoldManifest)
    assert manifest.dind_data_backing.startswith("/data2/jiadongzhu/docker/")
    assert manifest.dind_data_backing.endswith("deepseek-harness-hwe-v83/data")
    assert manifest.v79_data_volume_reused is False
    assert manifest.v81_data_volume_reused is False
    assert manifest.controller_image_tag == "node:22.19.0-bookworm-slim"
    assert manifest.controller_transfer.endswith("canonical_tag_pipe_v2")
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v85-official-matrix-v1"
    assert manifest.provider_successor_reopen_budget == 1
    assert manifest.provider_clients_available is False
    assert manifest.formal_collection_allowed is False

    value = manifest.model_dump(mode="json")
    with pytest.raises(ValueError, match="content hash changed"):
        DeepSeekHarnessV83ExecutionScaffoldManifest.model_validate(
            {**value, "v81_report_sha256": "0" * 64}
        )


def _offline_archive(tmp_path: Path) -> tuple[HweOfflineTaskLock, Path]:
    root = tmp_path / "archive-root"
    archive_relative = Path("docker-tar-archives/lowrisc_m_ibex/pr-465.tar")
    archive = root / archive_relative
    archive.parent.mkdir(parents=True)
    config = json.dumps({"config": {"WorkingDir": "/home/ibex"}}).encode()
    config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
    layer_name = "a" * 64 + ".tar.gz"
    manifest = json.dumps(
        [
            {
                "Config": config_digest,
                "RepoTags": ["ghcr.io/pku-liang/lowrisc_m_ibex:i-was-a-digest"],
                "Layers": [layer_name],
            }
        ],
        separators=(",", ":"),
    ).encode()
    with tarfile.open(archive, "w:") as tar:
        for name, payload in (
            (config_digest, config),
            (layer_name, b"layer"),
            ("manifest.json", manifest),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".tar.sha256").write_text(
        f"{archive_sha256}  {archive.name}\n", encoding="utf-8"
    )
    digest_path = root / "digest-locks/lowrisc_m_ibex/pr-465.digest"
    digest_path.parent.mkdir(parents=True)
    manifest_digest = "sha256:" + "b" * 64
    digest_path.write_text(f"{manifest_digest}\n", encoding="utf-8")
    lock = HweOfflineTaskLock.model_validate(
        {
            **_task_lock(V69_PRIMARY_TASK_IDS[0]),
            "archive_sha256": archive_sha256,
            "registry_manifest_digest": manifest_digest,
            "image_config_digest": config_digest,
            "official_verifier_image": config_digest,
        }
    )
    return lock, root


def test_offline_archive_binds_checksum_manifest_config_and_repository(tmp_path: Path) -> None:
    lock, root = _offline_archive(tmp_path)
    receipt = inspect_offline_image_archive(lock, archive_root=root)
    assert receipt["archive_sha256_sidecar_valid"] is True
    assert receipt["docker_archive_manifest_valid"] is True
    assert receipt["image_config_digest_valid"] is True
    assert receipt["repository_base"] == "/home/ibex"
    assert receipt["registry_accessed"] is False


def test_offline_archive_rejects_checksum_or_repository_drift(tmp_path: Path) -> None:
    lock, root = _offline_archive(tmp_path)
    sidecar = root / lock.archive_sha256_relpath
    sidecar.write_text(f"{'0' * 64}  pr-465.tar\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="sidecar"):
        inspect_offline_image_archive(lock, archive_root=root)


def _planes(
    *,
    verifier: bool,
    protocol: bool = True,
    trajectory: bool = True,
    infrastructure: bool = True,
    security: bool = True,
) -> HweAdmissionPlanes:
    return HweAdmissionPlanes(
        benchmark_verifier_pass=verifier,
        agent_protocol_valid=protocol,
        trajectory_eligible=trajectory,
        infrastructure_valid=infrastructure,
        security_valid=security,
        sft_admitted=verifier and protocol and trajectory and infrastructure and security,
    )


def _attempt(
    task_id: str,
    *,
    outcome: str,
    planes: HweAdmissionPlanes,
    marker: str = "started_valid",
    first_modification: int | None = 3,
) -> DeepSeekHarnessMatrixAttempt:
    return DeepSeekHarnessMatrixAttempt.model_validate(
        {
            "task_id": task_id,
            "repository": "ibex" if "ibex" in task_id else "cva6",
            "agent_toolchain_id": "hwe-official-task-toolchain-v1",
            "official_verifier_image": "sha256:" + "9" * 64,
            "provider_marker": marker,
            "provider_call_count": 0 if marker == "not_started" else 1,
            "provider_total_tokens": 0 if marker == "not_started" else 100,
            "first_effective_modification_action": first_modification,
            "outcome": outcome,
            "planes": planes,
            "exact_64k_eligible": planes.trajectory_eligible,
            "maximum_decision_tokens": 100 if planes.trajectory_eligible else None,
            "truncation_applied": False,
            "decision_only_loss_mask": planes.trajectory_eligible,
        }
    )


def test_matrix_stops_pre_provider_without_consuming_task() -> None:
    state = new_matrix_state(V69_PRIMARY_TASK_IDS[:2])
    attempt = _attempt(
        V69_PRIMARY_TASK_IDS[0],
        outcome="infrastructure_failure",
        planes=_planes(verifier=False, trajectory=False, infrastructure=False),
        marker="not_started",
        first_modification=None,
    )
    stopped = record_matrix_attempt(state, attempt)
    assert stopped.status == "stopped"
    assert stopped.stop_reason == "pre_provider_infrastructure_failure"
    assert stopped.attempts[0]["provider_consumed"] is False


def test_matrix_continues_verifier_failure_and_stops_after_two_no_progress() -> None:
    state = new_matrix_state(V69_PRIMARY_TASK_IDS[:3])
    state = record_matrix_attempt(
        state,
        _attempt(
            V69_PRIMARY_TASK_IDS[0],
            outcome="no_effective_modification",
            planes=_planes(verifier=False, trajectory=False),
            first_modification=None,
        ),
    )
    assert state.status == "running"
    state = record_matrix_attempt(
        state,
        _attempt(
            V69_PRIMARY_TASK_IDS[1],
            outcome="no_progress",
            planes=_planes(verifier=False, trajectory=False),
            first_modification=None,
        ),
    )
    assert state.status == "stopped"
    assert state.stop_reason == "two_consecutive_no_progress_or_trajectory_failures"

    separate = new_matrix_state(V69_PRIMARY_TASK_IDS[:2])
    separate = record_matrix_attempt(
        separate,
        _attempt(
            V69_PRIMARY_TASK_IDS[0],
            outcome="verifier_rejection",
            planes=_planes(verifier=False),
        ),
    )
    assert separate.status == "running"
    assert separate.consecutive_no_progress == 0


def test_migration_conclusions_keep_trajectory_and_sft_claims_separate() -> None:
    attempts = [
        _attempt(task_id, outcome="passed", planes=_planes(verifier=True))
        for task_id in (
            V69_PRIMARY_TASK_IDS[0],
            V69_PRIMARY_TASK_IDS[1],
            V69_PRIMARY_TASK_IDS[3],
        )
    ]
    conclusions = migration_conclusions(attempts)
    assert conclusions["trajectory_collection_migratable"] is True
    assert conclusions["sft_path_migratable"] is True

    trajectory_only = [
        _attempt(task_id, outcome="verifier_rejection", planes=_planes(verifier=False))
        for task_id in (
            V69_PRIMARY_TASK_IDS[0],
            V69_PRIMARY_TASK_IDS[1],
            V69_PRIMARY_TASK_IDS[3],
        )
    ]
    conclusions = migration_conclusions(trajectory_only)
    assert conclusions["trajectory_collection_migratable"] is True
    assert conclusions["sft_path_migratable"] is False


def test_agent_toolchain_cannot_impersonate_official_verifier() -> None:
    valid = {
        "agent_toolchain_id": "verigym-open-rtl-tools-v1",
        "official_verifier_image": "sha256:" + "9" * 64,
        "official_verifier_executed": True,
        "agent_diagnostic_result_role": "agent_only_non_authoritative",
        "official_verifier_result_role": "benchmark_authoritative",
        "agent_diagnostic_receipt_hash": "1" * 64,
        "official_verifier_receipt_hash": "2" * 64,
    }
    require_toolchain_verifier_binding(
        attempt=valid,
        expected_agent_toolchain_id="verigym-open-rtl-tools-v1",
        expected_official_verifier_image="sha256:" + "9" * 64,
    )
    with pytest.raises(ConfigurationError, match="identities are confused"):
        require_toolchain_verifier_binding(
            attempt={**valid, "official_verifier_receipt_hash": "1" * 64},
            expected_agent_toolchain_id="verigym-open-rtl-tools-v1",
            expected_official_verifier_image="sha256:" + "9" * 64,
        )


def test_v85_manifest_freezes_official_order_storage_and_closed_flags() -> None:
    manifest = load_v85_official_matrix_manifest(_V85_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV85OfficialMatrixManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert [item.repository for item in manifest.schedule] == [
        "ibex",
        "ibex",
        "ibex",
        "cva6",
        "cva6",
    ]
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.v83_data_volume_reopen_budget == 1
    assert manifest.task_network == "none"
    assert manifest.verifier_network == "none"
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False


def test_v85_manifest_rejects_reordered_tasks_even_with_a_recomputed_hash() -> None:
    changed = json.loads(_V85_MANIFEST.read_text(encoding="utf-8"))
    changed["schedule"][0], changed["schedule"][1] = (
        changed["schedule"][1],
        changed["schedule"][0],
    )
    changed["manifest_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError, match="schedule changed"):
        DeepSeekHarnessV85OfficialMatrixManifest.model_validate(changed)


def test_v87_manifest_freezes_fresh_storage_and_timeout_accounting() -> None:
    manifest = load_v87_fresh_scaffold_manifest(_V87_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV87FreshScaffoldManifest)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert "v87" in manifest.dind_data_backing
    assert manifest.v83_data_volume_reused is False
    assert manifest.v85_data_volume_reused is False
    assert manifest.physical_volume_open_accounting == "immediate_after_container_start_v1"
    assert manifest.readiness_probe_timeout_retryable is True
    assert manifest.provider_successor_reopen_budget == 1
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False


def test_v90_manifest_freezes_new_storage_and_bounded_control_timeout() -> None:
    manifest = load_v90_fresh_scaffold_manifest(_V90_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV90FreshScaffoldManifest)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert "v90" in manifest.dind_data_backing
    assert manifest.source_preparation_docker_control_timeout_seconds == 300
    assert manifest.v83_data_volume_reused is False
    assert manifest.v85_data_volume_reused is False
    assert manifest.v87_data_volume_reused is False
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v92-official-matrix-v1"
    assert manifest.provider_successor_reopen_budget == 1
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False


def test_v92_manifest_freezes_v90_receipts_order_and_closed_flags() -> None:
    manifest = load_v92_official_matrix_manifest(_V92_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV92OfficialMatrixManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert manifest.v91_audit_commit == "15919391354ddecdf29996893f4c745835101f17"
    assert manifest.v91_post_merge_main_run_id == 33762766907
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v90-dind-data"
    assert manifest.source_preparation_docker_control_timeout_seconds == 300
    assert all(
        item.source_preparation_docker_control_timeout_seconds == 300 for item in manifest.schedule
    )
    assert manifest.v90_data_volume_reopen_budget == 1
    assert manifest.v90_data_volume_reopen_count_before == 0
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False


def test_v92_manifest_rejects_reordered_tasks_even_with_a_recomputed_hash() -> None:
    changed = json.loads(_V92_MANIFEST.read_text(encoding="utf-8"))
    changed["schedule"][0], changed["schedule"][1] = (
        changed["schedule"][1],
        changed["schedule"][0],
    )
    changed["manifest_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError, match="schedule changed"):
        DeepSeekHarnessV92OfficialMatrixManifest.model_validate(changed)


def test_v94_manifest_freezes_runtime_complete_fresh_scaffold() -> None:
    manifest = load_v94_runtime_complete_scaffold_manifest(_V94_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV94RuntimeCompleteScaffoldManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert manifest.v93_audit_commit == "04ce5601446078db6084c90ac0eb812807807d0b"
    assert manifest.v93_post_merge_main_run_id == 33766642633
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v94-dind-data"
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.required_inner_image_count == 12
    assert manifest.runtime_prepare_task_count == 5
    assert manifest.harness_initialize_required is True
    assert manifest.v90_data_volume_reused is False
    assert manifest.v92_data_volume_reused is False
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v96-official-matrix-v1"
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False


def test_v94_manifest_rejects_missing_workspace_runtime_transfer() -> None:
    changed = json.loads(_V94_MANIFEST.read_text(encoding="utf-8"))
    changed["workspace_runtime_host_repo_tags"].reverse()
    changed["manifest_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError, match="runtime tags changed"):
        DeepSeekHarnessV94RuntimeCompleteScaffoldManifest.model_validate(changed)


def test_v97_manifest_freezes_fresh_storage_and_build_identity_policy() -> None:
    manifest = load_v97_rebuild_identity_scaffold_manifest(_V97_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV97RebuildIdentityScaffoldManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert manifest.v95_audit_commit == "57cf77be8d9992e5fcc2e5833ec64ff458365d00"
    assert manifest.v95_post_merge_main_run_id == 33776059453
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v97-dind-data"
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.cross_build_command_image_identity_policy == "fresh-materialization-lock-v1"
    assert manifest.historical_derived_image_identity_required is False
    assert manifest.historical_task_semantics_required is True
    assert manifest.v94_data_volume_reused is False
    assert manifest.v96_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v99-official-matrix-v1"
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False


def test_v97_manifest_rejects_historical_image_identity_as_a_gate() -> None:
    changed = json.loads(_V97_MANIFEST.read_text(encoding="utf-8"))
    changed["historical_derived_image_identity_required"] = True
    changed["manifest_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError, match="historical_derived_image_identity_required"):
        DeepSeekHarnessV97RebuildIdentityScaffoldManifest.model_validate(changed)


def test_v100_manifest_freezes_fresh_storage_and_bounded_inventory_controls() -> None:
    manifest = load_v100_inventory_timeout_scaffold_manifest(_V100_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV100InventoryTimeoutScaffoldManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert manifest.v98_audit_commit == "a766cc9d564f89c96170b1e451852e29e107388e"
    assert manifest.v98_post_merge_main_run_id == 33782913003
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v100-dind-data"
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.toolchain_inventory_create_timeout_seconds == 300
    assert manifest.toolchain_inventory_inspect_timeout_seconds == 300
    assert manifest.toolchain_inventory_execute_timeout_seconds == 120
    assert manifest.toolchain_inventory_remove_timeout_seconds == 300
    assert manifest.v97_data_volume_reused is False
    assert manifest.v99_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v102-official-matrix-v1"
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False


def test_v100_manifest_rejects_unbounded_inventory_timeout() -> None:
    changed = json.loads(_V100_MANIFEST.read_text(encoding="utf-8"))
    changed["toolchain_inventory_create_timeout_seconds"] = 0
    changed["manifest_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError, match="toolchain_inventory_create_timeout_seconds"):
        DeepSeekHarnessV100InventoryTimeoutScaffoldManifest.model_validate(changed)


def test_v103_manifest_freezes_fresh_storage_and_dedicated_inspect_bound() -> None:
    manifest = load_v103_inspect_output_bound_scaffold_manifest(_V103_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV103InspectOutputBoundScaffoldManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert manifest.v101_audit_commit == "3546e64c00b80f570334781a228ed521d5a601e8"
    assert manifest.v101_post_merge_main_run_id == 33789571225
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v103-dind-data"
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.v100_failed_inspect_output_bound_bytes == 4096
    assert manifest.toolchain_inventory_inspect_output_bound_bytes == 1024 * 1024
    assert manifest.v100_data_volume_reused is False
    assert manifest.v102_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v105-official-matrix-v1"
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False


def test_v103_manifest_rejects_the_failed_inspect_output_bound() -> None:
    changed = json.loads(_V103_MANIFEST.read_text(encoding="utf-8"))
    changed["toolchain_inventory_inspect_output_bound_bytes"] = 4096
    changed["manifest_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError, match="toolchain_inventory_inspect_output_bound_bytes"):
        DeepSeekHarnessV103InspectOutputBoundScaffoldManifest.model_validate(changed)


def test_v106_manifest_freezes_fresh_lock_derived_inventory() -> None:
    manifest = load_v106_fresh_inventory_binding_scaffold_manifest(_V106_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert manifest.v104_audit_commit == "95b9a11dbb3833fd57fc5b0a43bcd8708bc25865"
    assert manifest.v104_post_merge_main_run_id == 33795946043
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v106-dind-data"
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.final_inventory_command_image_source == "fresh-materialization-locks"
    assert manifest.final_inventory_fresh_command_image_count == 5
    assert manifest.required_inner_image_count == 12
    assert manifest.v103_data_volume_reused is False
    assert manifest.v105_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v108-official-matrix-v1"
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("final_inventory_command_image_source", "historical-schedule-command-images"),
        ("final_inventory_fresh_command_image_count", 4),
    ],
)
def test_v106_manifest_rejects_non_fresh_or_incomplete_inventory_binding(
    field: str, value: object
) -> None:
    changed = json.loads(_V106_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest.model_validate(changed)


def test_v109_manifest_freezes_direct_progress_writer_and_fresh_storage() -> None:
    manifest = load_v109_progress_writer_scaffold_manifest(_V109_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV109ProgressWriterScaffoldManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert manifest.v107_audit_commit == "96111d6073e4fe0944035a1a9a4b480e3f08d811"
    assert manifest.v107_post_merge_main_run_id == 33800282289
    assert manifest.progress_writer_source == "v97-captured-v94-base-writer"
    assert manifest.v106_evidence_directory_count == 14
    assert manifest.v106_evidence_regular_file_count == 0
    assert manifest.v106_evidence_symlink_count == 0
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v109-dind-data"
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.final_inventory_command_image_source == "fresh-materialization-locks"
    assert manifest.v106_data_volume_reused is False
    assert manifest.v108_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v111-official-matrix-v1"
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


def test_v109_manifest_rejects_an_indirect_progress_writer() -> None:
    changed = json.loads(_V109_MANIFEST.read_text(encoding="utf-8"))
    changed["progress_writer_source"] = "v106-indirect-writer"
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV109ProgressWriterScaffoldManifest.model_validate(changed)


def test_v112_manifest_freezes_the_real_data2_control_headroom_root() -> None:
    manifest = load_v112_data2_control_headroom_scaffold_manifest(_V112_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest)
    assert tuple(item.task_id for item in manifest.schedule) == V69_PRIMARY_TASK_IDS
    assert manifest.v110_audit_commit == "557e11ffbca95175352e5221e2ee9d8c994588bf"
    assert manifest.v110_post_merge_main_run_id == 33804279053
    assert manifest.inherited_control_headroom_root == "/"
    assert manifest.control_headroom_root.startswith("/data2/")
    assert manifest.system_root_headroom_required is False
    assert manifest.all_campaign_writable_roots_under_data2 is True
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v112-dind-data"
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.v109_data_volume_reused is False
    assert manifest.v111_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v114-official-matrix-v1"
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("control_headroom_root", "/"),
        ("system_root_headroom_required", True),
        ("all_campaign_writable_roots_under_data2", False),
    ],
)
def test_v112_manifest_rejects_a_changed_control_headroom_binding(
    field: str, value: object
) -> None:
    changed = json.loads(_V112_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest.model_validate(changed)


def test_v115_manifest_freezes_the_explicit_nested_docker_socket() -> None:
    manifest = load_v115_explicit_nested_docker_socket_scaffold_manifest(_V115_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV115ExplicitNestedDockerSocketScaffoldManifest)
    assert tuple(manifest.schedule_task_ids) == V69_PRIMARY_TASK_IDS
    assert manifest.v113_audit_commit == "9f79f54725c365bd0ab9ba9389f2ac421db1b155"
    assert manifest.v113_post_merge_main_run_id == 33810326256
    assert manifest.nested_docker_host == (
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket/docker.sock"
    )
    assert manifest.docker_cli_explicit_binding_required is True
    assert manifest.harness_helper_explicit_binding_required is True
    assert manifest.inherited_docker_environment_allowed is False
    assert manifest.remote_docker_endpoint_allowed is False
    assert manifest.v112_data_volume_reused is False
    assert manifest.v114_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v117-official-matrix-v1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("nested_docker_host", "tcp://127.0.0.1:2375"),
        ("docker_cli_explicit_binding_required", False),
        ("historical_command_image_id_required", True),
        ("historical_command_image_semantics_required", False),
        ("harness_helper_explicit_binding_required", False),
        ("inherited_docker_environment_allowed", True),
        ("remote_docker_endpoint_allowed", True),
        ("v112_data_volume_reused", True),
    ],
)
def test_v115_manifest_rejects_a_changed_socket_binding(field: str, value: object) -> None:
    changed = json.loads(_V115_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV115ExplicitNestedDockerSocketScaffoldManifest.model_validate(changed)


def test_v118_manifest_freezes_explicit_all_resource_inner_inventory() -> None:
    manifest = load_v118_explicit_inner_inventory_scaffold_manifest(_V118_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV118ExplicitInnerInventoryScaffoldManifest)
    assert tuple(manifest.schedule_task_ids) == V69_PRIMARY_TASK_IDS
    assert manifest.v115_authorization_commit == "48bc47f0dbb020e41f330bf5350bad621d01df1c"
    assert manifest.v116_audit_commit == "7faf47a4ba49139bf9e93200e104b8b9e9cbfea2"
    assert manifest.v116_post_merge_main_run_id == 33815411217
    assert manifest.nested_docker_host == (
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v118/socket/docker.sock"
    )
    assert manifest.inner_inventory_transport_policy == "explicit-bound-engine-all-resources-v1"
    assert manifest.inner_inventory_all_containers_required is True
    assert manifest.inner_inventory_all_volumes_required is True
    assert manifest.host_sidecar_inventory_for_inner_allowed is False
    assert manifest.inner_network_transport_policy == "explicit-bound-engine-v1"
    assert manifest.host_sidecar_network_control_for_inner_allowed is False
    assert manifest.streaming_attach_explicit_binding_required is True
    assert manifest.v115_data_volume_reused is False
    assert manifest.v117_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v120-official-matrix-v1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inner_inventory_transport_policy", "host-sidecar-exec"),
        ("inner_inventory_all_containers_required", False),
        ("inner_inventory_all_volumes_required", False),
        ("host_sidecar_inventory_for_inner_allowed", True),
        ("inner_network_transport_policy", "host-sidecar-exec"),
        ("host_sidecar_network_control_for_inner_allowed", True),
        ("streaming_attach_explicit_binding_required", False),
        ("v115_data_volume_reused", True),
        ("v117_identity_retired", False),
    ],
)
def test_v118_manifest_rejects_a_changed_inventory_binding(field: str, value: object) -> None:
    changed = json.loads(_V118_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV118ExplicitInnerInventoryScaffoldManifest.model_validate(changed)


def test_v121_manifest_freezes_one_provider_free_startup_attempt() -> None:
    manifest = load_v121_bounded_dind_start_diagnostic_manifest(_V121_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV121BoundedDindStartDiagnosticManifest)
    assert manifest.v119_audit_commit == "c22066916ba51e8c74678be2b0af6ac8d438ac9a"
    assert manifest.v119_post_merge_main_run_id == 33820413201
    assert manifest.startup_attempt_limit == 1
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v121-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v121-dind-socket"
    assert manifest.v118_volume_inspection_allowed is False
    assert manifest.v118_volume_mutation_allowed is False
    assert manifest.raw_docker_output_persisted is False
    assert manifest.container_identity_persisted is False
    assert manifest.task_archive_access_allowed is False
    assert manifest.task_materialization_allowed is False
    assert manifest.base_reference_verification_allowed is False
    assert manifest.harness_controller_allowed is False
    assert manifest.docker_network_creation_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.provider_credentials_available is False
    assert manifest.provider_request_started is False
    assert manifest.provider_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("startup_attempt_limit", 2),
        ("v118_volume_inspection_allowed", True),
        ("v118_volume_mutation_allowed", True),
        ("raw_docker_output_persisted", True),
        ("task_archive_access_allowed", True),
        ("task_materialization_allowed", True),
        ("harness_controller_allowed", True),
        ("docker_network_creation_allowed", True),
        ("registry_access_allowed", True),
        ("provider_credentials_available", True),
        ("provider_calls", 1),
        ("formal_collection_allowed", True),
    ],
)
def test_v121_manifest_rejects_a_broadened_diagnostic(field: str, value: object) -> None:
    changed = json.loads(_V121_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV121BoundedDindStartDiagnosticManifest.model_validate(changed)


def test_v123_manifest_freezes_one_provider_free_identity_probe() -> None:
    manifest = load_v123_bounded_dind_identity_probe_manifest(_V123_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV123BoundedDindIdentityProbeManifest)
    assert manifest.v122_audit_commit == "34a2854afcaa64a6de8a0fbca94ffd50dbb168db"
    assert manifest.v122_post_merge_main_run_id == 33823592366
    assert manifest.startup_attempt_limit == 1
    assert manifest.identity_probe_policy == ("explicit-info-fields-and-legacy-classification-v1")
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v123-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v123-dind-socket"
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.raw_docker_output_persisted is False
    assert manifest.raw_docker_output_hashed is False
    assert manifest.task_archive_access_allowed is False
    assert manifest.task_materialization_allowed is False
    assert manifest.base_reference_verification_allowed is False
    assert manifest.harness_controller_allowed is False
    assert manifest.docker_network_creation_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.provider_credentials_available is False
    assert manifest.provider_request_started is False
    assert manifest.provider_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("startup_attempt_limit", 2),
        ("predecessor_volume_inspection_allowed", True),
        ("predecessor_volume_mutation_allowed", True),
        ("identity_probe_policy", "raw-output-v1"),
        ("raw_docker_output_persisted", True),
        ("raw_docker_output_hashed", True),
        ("task_archive_access_allowed", True),
        ("task_materialization_allowed", True),
        ("harness_controller_allowed", True),
        ("docker_network_creation_allowed", True),
        ("registry_access_allowed", True),
        ("provider_credentials_available", True),
        ("provider_calls", 1),
        ("formal_collection_allowed", True),
    ],
)
def test_v123_manifest_rejects_a_broadened_probe(field: str, value: object) -> None:
    changed = json.loads(_V123_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV123BoundedDindIdentityProbeManifest.model_validate(changed)


def test_v125_manifest_freezes_one_exact_provider_free_readiness_probe() -> None:
    manifest = load_v125_bounded_dind_readiness_probe_manifest(_V125_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV125BoundedDindReadinessProbeManifest)
    assert manifest.v124_audit_commit == "013154e899b4a0622dabf75f51d87a309d1b5b3b"
    assert manifest.v124_post_merge_main_run_id == 33826887799
    assert manifest.startup_attempt_limit == 1
    assert manifest.readiness_timeout_seconds == 120
    assert manifest.readiness_command_timeout_seconds == 5
    assert manifest.readiness_poll_interval_seconds == 1
    assert manifest.readiness_probe_policy == ("explicit-three-field-exact-monotonic-deadline-v1")
    assert manifest.json_info_readiness_allowed is False
    assert manifest.fixed_poll_count_cap_allowed is False
    assert manifest.explicit_readiness_requires_empty_stderr is True
    assert manifest.explicit_readiness_requires_three_values is True
    assert manifest.explicit_readiness_requires_exact_identity is True
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v125-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v125-dind-socket"
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.raw_docker_output_persisted is False
    assert manifest.raw_docker_output_hashed is False
    assert manifest.task_archive_access_allowed is False
    assert manifest.task_materialization_allowed is False
    assert manifest.harness_controller_allowed is False
    assert manifest.docker_network_creation_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.provider_credentials_available is False
    assert manifest.provider_request_started is False
    assert manifest.provider_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("startup_attempt_limit", 2),
        ("readiness_timeout_seconds", 6),
        ("readiness_command_timeout_seconds", 30),
        ("json_info_readiness_allowed", True),
        ("fixed_poll_count_cap_allowed", True),
        ("explicit_readiness_requires_empty_stderr", False),
        ("explicit_readiness_requires_three_values", False),
        ("explicit_readiness_requires_exact_identity", False),
        ("predecessor_volume_inspection_allowed", True),
        ("predecessor_volume_mutation_allowed", True),
        ("raw_docker_output_persisted", True),
        ("raw_docker_output_hashed", True),
        ("task_archive_access_allowed", True),
        ("task_materialization_allowed", True),
        ("harness_controller_allowed", True),
        ("docker_network_creation_allowed", True),
        ("registry_access_allowed", True),
        ("provider_credentials_available", True),
        ("provider_calls", 1),
        ("formal_collection_allowed", True),
    ],
)
def test_v125_manifest_rejects_a_broadened_probe(field: str, value: object) -> None:
    changed = json.loads(_V125_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV125BoundedDindReadinessProbeManifest.model_validate(changed)


def test_v127_manifest_freezes_the_readiness_gated_five_task_scaffold() -> None:
    manifest = load_v127_readiness_gated_scaffold_manifest(_V127_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV127ReadinessGatedScaffoldManifest)
    assert tuple(manifest.schedule_task_ids) == V69_PRIMARY_TASK_IDS
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.v125_readiness_poll_count == 16
    assert manifest.v126_audit_commit == "084afb7c6e690f222d8274871c4fcc51ecf1a56a"
    assert manifest.v126_post_merge_main_run_id == 33830266674
    assert manifest.startup_attempt_limit == 1
    assert manifest.startup_command_timeout_seconds == 60
    assert manifest.readiness_timeout_seconds == 120
    assert manifest.readiness_command_timeout_seconds == 5
    assert manifest.readiness_poll_interval_seconds == 1
    assert manifest.readiness_probe_policy == ("explicit-three-field-exact-monotonic-deadline-v1")
    assert manifest.json_info_readiness_allowed is False
    assert manifest.fixed_poll_count_cap_allowed is False
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v129-official-matrix-v1"
    assert manifest.requires_independent_v128_audit is True
    assert all(
        getattr(manifest, name) is False
        for name in (
            "formal_collection_allowed",
            "formal_collection_started",
            "collection_started",
            "training_started",
            "production_training_ready",
        )
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("startup_attempt_limit", 2),
        ("startup_command_timeout_seconds", 61),
        ("readiness_timeout_seconds", 60),
        ("readiness_command_timeout_seconds", 15),
        ("readiness_poll_interval_seconds", 2),
        ("json_info_readiness_allowed", True),
        ("fixed_poll_count_cap_allowed", True),
        ("explicit_readiness_requires_empty_stderr", False),
        ("explicit_readiness_requires_three_values", False),
        ("explicit_readiness_requires_exact_identity", False),
        ("predecessor_volume_inspection_allowed", True),
        ("predecessor_volume_mutation_allowed", True),
        ("registry_access_allowed", True),
        ("provider_credentials_available", True),
        ("formal_collection_allowed", True),
    ],
)
def test_v127_manifest_rejects_a_broadened_scaffold(field: str, value: object) -> None:
    changed = json.loads(_V127_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV127ReadinessGatedScaffoldManifest.model_validate(changed)


def test_v127_manifest_rejects_an_invalid_content_hash() -> None:
    changed = json.loads(_V127_MANIFEST.read_text(encoding="utf-8"))
    changed["manifest_hash"] = "0" * 64
    with pytest.raises(ValueError, match="content hash changed"):
        DeepSeekHarnessV127ReadinessGatedScaffoldManifest.model_validate(changed)


def test_v130_manifest_freezes_one_provider_free_bounded_create_probe() -> None:
    manifest = load_v130_bounded_command_scan_probe_manifest(_V130_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV130BoundedCommandScanProbeManifest)
    assert manifest.task_id == "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465"
    assert manifest.v128_audit_merge == "dafe5a4fd3a5b64690a9b352ffc93556abba7425"
    assert manifest.v128_post_merge_main_run_id == 33835870104
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v130-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v130-dind-socket"
    assert manifest.create_timeout_seconds == 300
    assert manifest.inspect_timeout_seconds == 60
    assert manifest.start_timeout_seconds == 180
    assert manifest.remove_timeout_seconds == 120
    assert manifest.overall_timeout_seconds == 720
    assert manifest.task_archive_access_allowed is True
    assert manifest.task_image_import_allowed is True
    assert manifest.command_image_build_allowed is True
    assert manifest.task_execution_allowed is False
    assert manifest.base_reference_verification_allowed is False
    assert manifest.harness_controller_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.provider_credentials_available is False
    assert manifest.provider_request_started is False
    assert manifest.provider_calls == 0
    assert all(
        getattr(manifest, name) is False
        for name in (
            "formal_collection_allowed",
            "formal_collection_started",
            "collection_started",
            "training_started",
            "production_training_ready",
        )
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("create_timeout_seconds", 60),
        ("inspect_timeout_seconds", 30),
        ("start_timeout_seconds", 181),
        ("remove_timeout_seconds", 30),
        ("overall_timeout_seconds", 900),
        ("startup_attempt_limit", 2),
        ("task_execution_allowed", True),
        ("base_reference_verification_allowed", True),
        ("harness_controller_allowed", True),
        ("registry_access_allowed", True),
        ("partial_archive_allowed", True),
        ("predecessor_volume_inspection_allowed", True),
        ("predecessor_volume_mutation_allowed", True),
        ("provider_credentials_available", True),
        ("provider_request_started", True),
        ("provider_calls", 1),
        ("formal_collection_allowed", True),
    ],
)
def test_v130_manifest_rejects_a_broadened_or_changed_probe(field: str, value: object) -> None:
    changed = json.loads(_V130_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV130BoundedCommandScanProbeManifest.model_validate(changed)


def test_v130_manifest_rejects_an_invalid_content_hash() -> None:
    changed = json.loads(_V130_MANIFEST.read_text(encoding="utf-8"))
    changed["manifest_hash"] = "0" * 64
    with pytest.raises(ValueError, match="content hash changed"):
        DeepSeekHarnessV130BoundedCommandScanProbeManifest.model_validate(changed)


def test_v132_manifest_freezes_the_bounded_scan_five_task_scaffold() -> None:
    manifest = load_v132_bounded_scan_scaffold_manifest(_V132_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV132BoundedScanScaffoldManifest)
    assert tuple(manifest.schedule_task_ids) == V69_PRIMARY_TASK_IDS
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.v130_security_scan_id == (
        "7e68ef3987f081e8e28af0b5d55f7e1aaeb6aa0336cff4547b62f8304e58d517"
    )
    assert manifest.v131_audit_merge == "5c0022521ffd513c726a4d0f8d0a6f02e94eaecf"
    assert manifest.v131_post_merge_main_run_id == 33846866494
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v132-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v132-dind-socket"
    assert manifest.scanner_create_timeout_seconds == 300
    assert manifest.scanner_inspect_timeout_seconds == 60
    assert manifest.scanner_start_timeout_seconds == 180
    assert manifest.scanner_remove_timeout_seconds == 120
    assert manifest.scanner_overall_timeout_seconds == 720
    assert manifest.scanner_all_five_tasks_required is True
    assert manifest.scanner_nonempty_output_hashing_allowed is False
    assert manifest.failed_data_volume_policy == "freeze-exact-owned-volume"
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v134-official-matrix-v1"
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.requires_independent_v133_audit is True
    assert all(
        getattr(manifest, name) is False
        for name in (
            "formal_collection_allowed",
            "formal_collection_started",
            "collection_started",
            "training_started",
            "production_training_ready",
        )
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scanner_create_timeout_seconds", 60),
        ("scanner_inspect_timeout_seconds", 30),
        ("scanner_start_timeout_seconds", 181),
        ("scanner_remove_timeout_seconds", 30),
        ("scanner_overall_timeout_seconds", 900),
        ("scanner_all_five_tasks_required", False),
        ("scanner_deterministic_owner_cleanup_required", False),
        ("scanner_nonempty_output_hashing_allowed", True),
        ("startup_attempt_limit", 2),
        ("predecessor_volume_inspection_allowed", True),
        ("predecessor_volume_mutation_allowed", True),
        ("registry_access_allowed", True),
        ("partial_archive_allowed", True),
        ("provider_credentials_available", True),
        ("formal_collection_allowed", True),
    ],
)
def test_v132_manifest_rejects_a_broadened_or_changed_scaffold(field: str, value: object) -> None:
    changed = json.loads(_V132_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV132BoundedScanScaffoldManifest.model_validate(changed)


def test_v132_manifest_rejects_an_invalid_content_hash() -> None:
    changed = json.loads(_V132_MANIFEST.read_text(encoding="utf-8"))
    changed["manifest_hash"] = "0" * 64
    with pytest.raises(ValueError, match="content hash changed"):
        DeepSeekHarnessV132BoundedScanScaffoldManifest.model_validate(changed)


def test_v136_manifest_freezes_the_command_runtime_transport_diagnostic() -> None:
    manifest = load_v136_command_runtime_diagnostic_manifest(_V136_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV136CommandRuntimeDiagnosticManifest)
    assert manifest.task_id == "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465"
    assert manifest.v135_audit_merge == "da971e808b8da441d01ce7f76445fe6284939cd7"
    assert manifest.v135_post_merge_main_run_id == 33856107497
    assert manifest.v132_command_lock_hash == (
        "45054a863ca9c736441206fcf973fe2522071b8fda3beddb9e32158dc9a2c9fa"
    )
    assert manifest.v132_security_scan_id == (
        "19da6e02194d1f22046e249b7582232be0c430d1ccd415556d92976849358f3e"
    )
    assert manifest.expected_inherited_environment_subreason == "image_missing"
    assert manifest.explicit_nested_engine_expected_pass is True
    assert manifest.docker_cli_explicit_binding_required is True
    assert manifest.historical_command_image_id_required is False
    assert manifest.historical_command_image_semantics_required is True
    assert manifest.requires_independent_v137_audit is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("create_timeout_seconds", 60),
        ("overall_timeout_seconds", 900),
        ("startup_attempt_limit", 2),
        ("inherited_environment_probe_count", 2),
        ("explicit_nested_engine_probe_count", 2),
        ("expected_inherited_environment_subreason", "invalid_image_id"),
        ("explicit_nested_engine_expected_pass", False),
        ("docker_cli_explicit_binding_required", False),
        ("fresh_bind_backed_volumes_required", False),
        ("host_command_image_expected_absent", False),
        ("task_execution_allowed", True),
        ("base_reference_verification_allowed", True),
        ("harness_controller_allowed", True),
        ("registry_access_allowed", True),
        ("partial_archive_allowed", True),
        ("v132_volume_inspection_allowed", True),
        ("v132_volume_mutation_allowed", True),
        ("provider_credentials_available", True),
        ("provider_request_started", True),
        ("provider_calls", 1),
        ("formal_collection_allowed", True),
    ],
)
def test_v136_manifest_rejects_a_broadened_or_changed_diagnostic(
    field: str,
    value: object,
) -> None:
    changed = json.loads(_V136_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV136CommandRuntimeDiagnosticManifest.model_validate(changed)


def test_v136_manifest_rejects_an_invalid_content_hash() -> None:
    changed = json.loads(_V136_MANIFEST.read_text(encoding="utf-8"))
    changed["manifest_hash"] = "0" * 64
    with pytest.raises(ValueError, match="content hash changed"):
        DeepSeekHarnessV136CommandRuntimeDiagnosticManifest.model_validate(changed)


def test_v138_manifest_freezes_the_fresh_explicit_scaffold() -> None:
    manifest = load_v138_fresh_explicit_scaffold_manifest(_V138_MANIFEST)

    assert isinstance(manifest, DeepSeekHarnessV138FreshExplicitScaffoldManifest)
    assert manifest.v137_audit_merge == "98c083b7dfc6cb378d0ee7239148370308f7c06f"
    assert manifest.v137_post_merge_main_run_id == 33861403120
    assert manifest.archive_import_timeout_seconds == 1800
    assert manifest.archive_import_explicit_endpoint_required is True
    assert manifest.archive_import_stage_diagnostic_required is True
    assert manifest.archive_import_raw_output_allowed is False
    assert manifest.archive_import_nonempty_output_hashing_allowed is False
    assert manifest.v132_volume_inspection_allowed is False
    assert manifest.v132_volume_mutation_allowed is False
    assert manifest.requires_independent_v139_audit is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("archive_import_timeout_seconds", 60),
        ("archive_import_explicit_endpoint_required", False),
        ("archive_import_stage_diagnostic_required", False),
        ("archive_import_raw_output_allowed", True),
        ("archive_import_nonempty_output_hashing_allowed", True),
        ("v132_volume_inspection_allowed", True),
        ("v132_volume_mutation_allowed", True),
        ("requires_independent_v139_audit", False),
        ("formal_collection_allowed", True),
    ],
)
def test_v138_manifest_rejects_a_broadened_or_changed_scaffold(
    field: str,
    value: object,
) -> None:
    changed = json.loads(_V138_MANIFEST.read_text(encoding="utf-8"))
    changed[field] = value
    changed["manifest_hash"] = content_hash(
        {key: item for key, item in changed.items() if key != "manifest_hash"}
    )
    with pytest.raises(ValueError):
        DeepSeekHarnessV138FreshExplicitScaffoldManifest.model_validate(changed)
