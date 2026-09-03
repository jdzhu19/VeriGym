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
    HweAdmissionPlanes,
    HweOfflineTaskLock,
    inspect_offline_image_archive,
    load_v81_execution_scaffold_manifest,
    load_v83_execution_scaffold_manifest,
    load_v85_official_matrix_manifest,
    load_v87_fresh_scaffold_manifest,
    load_v90_fresh_scaffold_manifest,
    load_v92_official_matrix_manifest,
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
