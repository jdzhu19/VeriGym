#!/usr/bin/env python3
"""Materialize the five-task scaffold through one explicit local DinD socket."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
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
    resolve_settings,
)
from verigym_deepseek_harness.process import run_harness_helper  # noqa: E402

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v112_data2_control_headroom_scaffold as v112,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness import DEEPSEEK_HARNESS_MODEL  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    load_v112_data2_control_headroom_scaffold_manifest,
    load_v115_explicit_nested_docker_socket_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID  # noqa: E402
from verigym.runtimes.docker.engine import (  # noqa: E402
    DockerCliEngine,
    validate_local_docker_host,
)
from verigym.runtimes.docker.runtime import DockerRuntime  # noqa: E402

v94 = v112.v109.v106.v103.v100.v97.v94
v92 = v94.v92
dind = v94.dind

IDENTITY = "deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V115_EXPLICIT_NESTED_DOCKER_SOCKET_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/"
    "qwen35_hwe_deepseek_harness_v115_explicit_nested_docker_socket_scaffold_v1.json"
)
V112_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v112_data2_control_headroom_scaffold_v1.json"
)
V112_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v112_data2_control_headroom_scaffold.py"
)
V112_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v112-data2-control-headroom-authorization.md"
)
V112_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1"
)
V112_REPORT = V112_ROOT / "execution-scaffold-report.json"
V112_PROGRESS = V112_ROOT / "execution-scaffold-progress.json"
V112_HEADROOM = V112_ROOT / "headroom-preflight.json"
V112_TASK_MATERIALIZATION = V112_ROOT / "task-materialization-set.json"
V112_INVENTORY = V112_ROOT / "execution-inventory.json"
V112_CLEANUP = V112_ROOT / "dind-cleanup-receipt.json"
V113_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v113-v112-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v115")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v115-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v115-runtime")
_V112_RUNTIME_PATHS = (
    Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v112/socket"),
    Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-control"),
    Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-runtime"),
)
_REQUIRED_MERGED_PATHS = (
    *v112._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-04_deepseek-harness-v113-v112-result.md",
    "configs/training/"
    "qwen35_hwe_deepseek_harness_v115_explicit_nested_docker_socket_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v115-explicit-nested-docker-socket-authorization.md",
    "integrations/verigym-deepseek-harness/tests/"
    "test_v115_explicit_nested_docker_socket_scaffold.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/process.py",
    "integrations/verigym-deepseek-harness/tests/test_process.py",
    "scripts/materialize_hwe_deepseek_harness_v115_explicit_nested_docker_socket_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "src/verigym/runtimes/docker/engine.py",
    "tests/unit/test_docker_engine.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)
_V112_EXPECTED_COMMAND_IMAGES = {
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465": (
        "sha256:0239b2b25561eb2725ade61b5977847201b9200219b5a325c22e6b7b71229187"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135": (
        "sha256:062eabe446499892946ab840e31232e27f26304b62e94ba57c5699c09a95ea93"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780": (
        "sha256:5c8b6a3702c1e5f50ec69211925133e26c67282d163f523bbaccf0a72ded4025"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017": (
        "sha256:92bc2064c0f7bfe62759f36d6225f22130df2ac08e4af4308f20623bcfa8652a"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711": (
        "sha256:2d2ce45bde8898084e8053399a43c6bb105ad9e66e13d74cc505a63a39995e45"
    ),
}
_V112_EXPECTED_LOCK_HASHES = {
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465": (
        "5121f698df469001c91b48241f2acb8960e7d83532f29b6bf1d9eb4074bcdd47"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135": (
        "d76051cd29974928e6ad56fb6de96ed3da24debe125a2deadd611b1119879a5b"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780": (
        "ae67f68013b4b48f847f366b0f57acd64393a5389ab59272279e1ed757f4d05a"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017": (
        "86680044891ef4bcac0bf9e88091e882b8546c6357b52f5a3739aa0367fa22ce"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711": (
        "702339a1f56c436a873fc1f5442f3587332939ee74289f8aaa6a1531e92c61cd"
    ),
}
_V112_EXPECTED_SCAN_IDS = {
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465": (
        "1d915d5ee92c9f7ed2406b447625255bdc1126310c9456fd0ad76f77948cfba0"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135": (
        "06ec109900008a22d4fc8609f39a7d5931f5d0dd22bfb44d9b6ed70a3f59fb14"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780": (
        "491a83d0df95c55903526cf782c9c7e269169fba24004bd411c211d0d0adcff1"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017": (
        "e0a7ec71ecdb695e07a694f2edddc84190f7b1580db01a99b7bfaa9491ac4d06"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711": (
        "30d44f857e9e6fcd745c5487e7ec22a3d06842fd5dd5dd5f3f2d27dafcfdedda"
    ),
}

_V94_WRITE_PROGRESS = v112._V94_WRITE_PROGRESS  # noqa: SLF001
_V112_DATA2_CONTROL_HEADROOM = v112._data2_control_headroom  # noqa: SLF001
_V112_TRANSFER_IMAGES = v112._transfer_images  # noqa: SLF001
_V112_INVENTORY = v112._inventory  # noqa: SLF001
_V112_RUNTIME_RECEIPT = v112._runtime_receipt  # noqa: SLF001
_V112_CLEAN_SOCKET_VOLUME = v112._clean_socket_volume  # noqa: SLF001
_V112_VALIDATE_STATIC_BINDINGS = v112._validate_static_bindings  # noqa: SLF001
_V112_MATERIALIZE_TASKS = v112._materialize_tasks  # noqa: SLF001
_V112_SCAFFOLD_CONTRACT = v112._scaffold_contract  # noqa: SLF001
_V112_REQUIRE_CLEAN_MERGED_MAIN = v112._require_clean_merged_main  # noqa: SLF001
_V69_MATERIALIZE_TASK = v112._V69_MATERIALIZE_TASK  # noqa: SLF001
_LOAD_V112_MANIFEST = load_v112_data2_control_headroom_scaffold_manifest


def _parser() -> argparse.ArgumentParser:
    parser = v112._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the v112 workflow under fresh v115 paths and explicit socket bindings."""

    with _v115_configuration():
        return v112.materialize(arguments)


@contextlib.contextmanager
def _v115_configuration() -> Iterator[None]:
    replacements: dict[str, Any] = {
        "IDENTITY": IDENTITY,
        "OPT_IN_ENV": OPT_IN_ENV,
        "MANIFEST": MANIFEST,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "DIND_PARENT": DIND_PARENT,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
        "CONTROL_ROOT": CONTROL_ROOT,
        "RUNTIME_TMP": RUNTIME_TMP,
        "_REQUIRED_MERGED_PATHS": _REQUIRED_MERGED_PATHS,
        "load_v112_data2_control_headroom_scaffold_manifest": _load_composed_manifest,
        "_write_progress": _write_progress,
        "_data2_control_headroom": _data2_control_headroom,
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_v112_materialize_task": _v115_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v112, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v112, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v112, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v115_explicit_nested_docker_socket_scaffold_manifest(path)
    predecessor = _LOAD_V112_MANIFEST(V112_MANIFEST)
    values = predecessor.model_dump(mode="python")
    values.update(purpose.model_dump(mode="python"))
    values.update(
        {
            "dind_image_id": predecessor.dind_image_id,
            "dind_repository_digest": predecessor.dind_repository_digest,
            "dind_server_version": predecessor.dind_server_version,
            "dind_storage_driver": predecessor.dind_storage_driver,
            "dind_default_runtime": predecessor.dind_default_runtime,
            "scaffold_outer_network": predecessor.scaffold_outer_network,
            "preflight_inner_network": predecessor.preflight_inner_network,
            "preflight_inner_network_internal": predecessor.preflight_inner_network_internal,
            "task_network": predecessor.task_network,
            "verifier_network": predecessor.verifier_network,
            "controller_image_tag": predecessor.controller_image_tag,
            "controller_image_id": predecessor.controller_image_id,
            "controller_image_repository_digest": predecessor.controller_image_repository_digest,
            "controller_transfer": predecessor.controller_transfer,
            "workspace_runtime_image_id": predecessor.workspace_runtime_image_id,
            "workspace_runtime_host_repo_tags": predecessor.workspace_runtime_host_repo_tags,
            "workspace_runtime_transfer": predecessor.workspace_runtime_transfer,
            "required_inner_image_count": predecessor.required_inner_image_count,
            "runtime_prepare_task_count": predecessor.runtime_prepare_task_count,
            "harness_initialize_required": predecessor.harness_initialize_required,
            "synthetic_provider_values_only": predecessor.synthetic_provider_values_only,
            "schedule": predecessor.schedule,
            "control_headroom_root": str(CONTROL_ROOT),
            "inherited_control_headroom_root": "/",
            "system_root_headroom_required": False,
            "all_campaign_writable_roots_under_data2": True,
            "dind_data_volume": purpose.dind_data_volume,
            "dind_socket_volume": purpose.dind_socket_volume,
            "dind_data_backing": purpose.dind_data_backing,
            "dind_socket_backing": purpose.dind_socket_backing,
            "provider_successor_identity": purpose.provider_successor_identity,
            "manifest_hash": purpose.manifest_hash,
        }
    )
    return SimpleNamespace(**values)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v115 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v115_scaffold_progress_v1",
            "v112_manifest_hash": (
                "762db692017a7286aa97cf8d44311ed64c85fe39d5cc120f6b975acfb1802703"
            ),
            "v112_report_hash": (
                "dd63f0945d93a29c2321d15f273a2f567504a2a954d78024212ad30ace3690d0"
            ),
            "v113_audit_commit": "9f79f54725c365bd0ab9ba9389f2ac421db1b155",
            "v113_post_merge_main_run_id": 33810326256,
            "docker_host_binding_policy": "explicit-canonical-local-unix-socket-v1",
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "v112_data_volume_reused": False,
            "v114_identity_retired": True,
        }
    )
    if value.get("status") in {
        "completed_pending_independent_v95_audit",
        "completed_pending_independent_v98_audit",
        "completed_pending_independent_v101_audit",
        "completed_pending_independent_v104_audit",
        "completed_pending_independent_v107_audit",
        "completed_pending_independent_v110_audit",
        "completed_pending_independent_v113_audit",
    }:
        value["status"] = "completed_pending_independent_v116_audit"
    _V94_WRITE_PROGRESS(root, value)


def _reseal(
    value: Mapping[str, Any],
    *,
    hash_field: str,
    format_id: str,
) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    base.pop(hash_field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, hash_field: content_hash(base)}


def _data2_control_headroom(**kwargs: Any) -> dict[str, Any]:
    value = _V112_DATA2_CONTROL_HEADROOM(**kwargs)
    return _reseal(
        value,
        hash_field="preflight_hash",
        format_id="verigym_deepseek_harness_hwe_v115_data2_control_headroom_v1",
    )


def _transfer_images(
    dind_name: str,
    manifest: Any,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V112_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v115_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v115 image transfer receipt inventory is not exactly two")
    value.update(
        {
            "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
            "controller_receipt_hash": receipts[0]["receipt_hash"],
            "workspace_runtime_receipt_hash": receipts[1]["receipt_hash"],
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v115_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _validated_nested_docker_host(manifest: Any) -> str:
    expected = f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
    if (
        manifest.nested_docker_host != expected
        or os.environ.get("DOCKER_HOST") != expected
        or "DOCKER_CONTEXT" in os.environ
    ):
        raise ConfigurationError("v115 nested Docker scope or manifest endpoint changed")
    try:
        return validate_local_docker_host(expected)
    except ValueError as exc:
        raise ConfigurationError("v115 nested Docker endpoint is unsafe") from exc


def _runtime_prepare_preflight(
    manifest: Any,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    docker_host = _validated_nested_docker_host(manifest)
    completed: list[str] = []
    for binding in manifest.schedule:
        engine = DockerCliEngine(docker_host=docker_host)
        runtime = DockerRuntime(v92._runtime_config(locks[binding.task_id]), engine=engine)  # noqa: SLF001
        try:
            runtime.prepare(f"v115-preflight-pr-{binding.pr_number}")
        finally:
            runtime.close()
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        completed.append(binding.task_id)
    if len(completed) != manifest.runtime_prepare_task_count:
        raise ConfigurationError("v115 runtime prepare did not cover all five tasks")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v115_runtime_prepare_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "completed_task_ids": completed,
        "task_count": len(completed),
        "workspace_runtime_image_id": manifest.workspace_runtime_image_id,
        "task_network": manifest.task_network,
        "docker_host_binding_policy": manifest.docker_host_binding_policy,
        "nested_docker_host": docker_host,
        "docker_cli_explicit_binding": True,
        "inherited_docker_environment_used": False,
        "remote_docker_endpoint_used": False,
        "inner_only_command_images_prepared": True,
        "inner_container_inventory_empty": True,
        "inner_volume_inventory_empty": True,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _harness_initialize_preflight(
    manifest: Any,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    docker_host = _validated_nested_docker_host(manifest)
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
    synthetic_key = "v115-offline-" + secrets.token_urlsafe(32)
    synthetic_url = "http://127.0.0.1:9/v1"
    if os.environ.get(API_KEY_ENV) is not None or os.environ.get(BASE_URL_ENV) is not None:
        raise ConfigurationError("v115 refuses a real provider environment during initialize")
    try:
        os.environ[API_KEY_ENV] = synthetic_key
        os.environ[BASE_URL_ENV] = synthetic_url
        result = run_harness_helper(
            settings,
            mode="initialize",
            prompt="",
            system_prompt="VeriGym v115 network-isolated zero-provider initialization preflight.",
            session_id="v115-zero-provider-preflight",
            session_root=session_root,
            broker_root=broker_root,
            docker_host=docker_host,
        )
    finally:
        os.environ.pop(API_KEY_ENV, None)
        os.environ.pop(BASE_URL_ENV, None)
    scan = v94._scan_synthetic_values(root, values=(synthetic_key, synthetic_url))  # noqa: SLF001
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
        raise ConfigurationError("v115 Harness initialize crossed the provider boundary")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v115_harness_initialize_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "harness_configuration_fingerprint": settings.configuration_fingerprint,
        "controller_image_id": settings.controller_image_id,
        "controller_image_provenance": settings.controller_image_provenance,
        "controller_image_source_receipt_hash": controller_receipt_hash,
        "outer_network": manifest.scaffold_outer_network,
        "inner_network": manifest.preflight_inner_network,
        "inner_network_internal": manifest.preflight_inner_network_internal,
        "docker_host_binding_policy": manifest.docker_host_binding_policy,
        "nested_docker_host": docker_host,
        "harness_helper_explicit_binding": True,
        "same_endpoint_as_runtime_prepare": True,
        "controller_initialized_on_inner_daemon": True,
        "inherited_docker_environment_used": False,
        "remote_docker_endpoint_used": False,
        "synthetic_provider_values_only": True,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_call_count": 0,
        "provider_values_persisted_or_hashed": False,
        "synthetic_value_scan": scan,
        "raw_exception_persisted": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _inventory(dind_name: str, manifest: Any) -> dict[str, Any]:
    return _reseal(
        _V112_INVENTORY(dind_name, manifest),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v115_execution_inventory_v1",
    )


def _runtime_receipt(
    manifest: Any,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V112_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value.update(
        {
            "v112_data_volume_reused": False,
            "docker_host_binding_policy": manifest.docker_host_binding_policy,
            "nested_docker_host": manifest.nested_docker_host,
            "docker_cli_explicit_binding_required": True,
            "harness_helper_explicit_binding_required": True,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v115_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    result = _reseal(
        _V112_CLEAN_SOCKET_VOLUME(manifest, root=root),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v115_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    _V112_VALIDATE_STATIC_BINDINGS(
        manifest,
        v92_manifest,
        v92_report,
        v92_manifest_path=v92_manifest_path,
        v92_report_path=v92_report_path,
    )
    purpose = load_v115_explicit_nested_docker_socket_scaffold_manifest(MANIFEST)
    predecessor = _LOAD_V112_MANIFEST(V112_MANIFEST)
    report = v94._load_json(V112_REPORT)  # noqa: SLF001
    progress = v94._load_json(V112_PROGRESS)  # noqa: SLF001
    headroom = v94._load_json(V112_HEADROOM)  # noqa: SLF001
    tasks = v94._load_json(V112_TASK_MATERIALIZATION)  # noqa: SLF001
    inventory = v94._load_json(V112_INVENTORY)  # noqa: SLF001
    cleanup = v94._load_json(V112_CLEANUP)  # noqa: SLF001
    entries = list(V112_ROOT.rglob("*"))
    directories = 1 + sum(path.is_dir() and not path.is_symlink() for path in entries)
    files = sum(path.is_file() and not path.is_symlink() for path in entries)
    symlinks = sum(path.is_symlink() for path in entries)
    task_rows = {
        item.get("task_id"): item
        for item in tasks.get("task_receipts", [])
        if isinstance(item, dict) and isinstance(item.get("task_id"), str)
    }
    if (
        v69._hash_file(V112_MANIFEST) != purpose.v112_manifest_sha256  # noqa: SLF001
        or predecessor.manifest_hash != purpose.v112_manifest_hash
        or v69._hash_file(V112_RUNNER) != purpose.v112_runner_sha256  # noqa: SLF001
        or v69._hash_file(V112_AUTHORIZATION) != purpose.v112_authorization_sha256  # noqa: SLF001
        or v69._hash_file(V112_REPORT) != purpose.v112_report_sha256  # noqa: SLF001
        or v69._hash_file(V112_PROGRESS) != purpose.v112_report_sha256  # noqa: SLF001
        or v94._canonical_hash(report, "report_hash") != purpose.v112_report_hash  # noqa: SLF001
        or v94._canonical_hash(progress, "report_hash") != purpose.v112_report_hash  # noqa: SLF001
        or v69._hash_file(V112_HEADROOM) != purpose.v112_headroom_sha256  # noqa: SLF001
        or v94._canonical_hash(headroom, "preflight_hash") != purpose.v112_headroom_hash  # noqa: SLF001
        or v69._hash_file(V112_TASK_MATERIALIZATION)  # noqa: SLF001
        != purpose.v112_task_materialization_sha256
        or v94._canonical_hash(tasks, "receipt_hash")  # noqa: SLF001
        != purpose.v112_task_materialization_hash
        or v69._hash_file(V112_INVENTORY) != purpose.v112_inventory_sha256  # noqa: SLF001
        or v94._canonical_hash(inventory, "inventory_hash") != purpose.v112_inventory_hash  # noqa: SLF001
        or v69._hash_file(V112_CLEANUP) != purpose.v112_cleanup_sha256  # noqa: SLF001
        or v94._canonical_hash(cleanup, "receipt_hash") != purpose.v112_cleanup_hash  # noqa: SLF001
        or v69._hash_file(V113_AUDIT) != purpose.v113_audit_sha256  # noqa: SLF001
        or directories != purpose.v112_evidence_directory_count
        or files != purpose.v112_evidence_regular_file_count
        or symlinks != purpose.v112_evidence_symlink_count
    ):
        raise ConfigurationError("v115 audited v112 evidence binding changed")
    if (
        report != progress
        or report.get("identity") != "deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1"
        or report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "DockerImageError"
        or report.get("completed_stages")
        != ["controller_and_workspace_runtime_transferred", "five_task_offline_materialization"]
        or report.get("provider_execution_scaffold_published") is not False
        or report.get("provider_execution_authorized") is not False
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or report.get("dind_cleanup_confirmed") is not True
        or report.get("raw_exception_persisted") is not False
        or any(report.get(key) is not False for key in v94._closed_training_flags())  # noqa: SLF001
        or (V112_ROOT / "preflight/runtime-prepare.json").exists()
        or (V112_ROOT / "preflight/harness-initialize.json").exists()
        or (V112_ROOT / "final-execution-inventory.json").exists()
        or (V112_ROOT / "execution-scaffold-contract.json").exists()
    ):
        raise ConfigurationError("v115 requires the exact audited v112 provider-free stop")
    if (
        headroom.get("status") != "passed"
        or headroom.get("control_headroom_root")
        != "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-control"
        or headroom.get("system_root_headroom_required") is not False
        or headroom.get("all_campaign_writable_roots_under_data2") is not True
        or headroom.get("thresholds_changed") is not False
        or tasks.get("completed_task_ids") != purpose.schedule_task_ids
        or tasks.get("all_base_failed_reference_passed") is not True
        or tasks.get("all_command_images_v2_scanned") is not True
        or inventory.get("required_images_present") is not True
        or inventory.get("required_image_count") != 12
        or inventory.get("fresh_command_image_count") != 5
        or inventory.get("observed_image_count") != 17
        or cleanup.get("socket_volume_removed") is not True
        or cleanup.get("socket_backing_empty") is not True
    ):
        raise ConfigurationError("v115 requires the audited v112 qualification and cleanup state")
    if set(task_rows) != set(purpose.schedule_task_ids) or any(
        row.get("base_failed") is not True
        or row.get("base_infrastructure_error") is not False
        or row.get("reference_passed") is not True
        or row.get("agent_command_image") != _V112_EXPECTED_COMMAND_IMAGES[task_id]
        or row.get("agent_command_image_lock_hash") != _V112_EXPECTED_LOCK_HASHES[task_id]
        or row.get("security_scan_id") != _V112_EXPECTED_SCAN_IDS[task_id]
        or row.get("verifier_network") != "none"
        or row.get("agent_command_network") != "none"
        or row.get("provider_calls") != 0
        or row.get("model_process_count") != 0
        for task_id, row in task_rows.items()
    ):
        raise ConfigurationError("v115 requires all five exact audited v112 task results")
    v112_data = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v112/data")
    if (
        v112_data.is_symlink()
        or not v112_data.is_dir()
        or any(
            path.is_symlink() or not path.is_dir() or next(path.iterdir(), None) is not None
            for path in _V112_RUNTIME_PATHS
        )
    ):
        raise ConfigurationError("v115 requires the frozen v112 data and empty runtime paths")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", purpose.v113_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v115 requires the merged v113 audit")
    if (
        manifest.manifest_hash != purpose.manifest_hash
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.control_headroom_root != str(CONTROL_ROOT)
        or manifest.runtime_scratch_root != str(RUNTIME_TMP)
        or manifest.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or purpose.v112_data_volume_reused is not False
        or purpose.v114_identity_retired is not True
        or purpose.provider_credentials_available is not False
        or purpose.registry_access_allowed is not False
    ):
        raise ConfigurationError("v115 purpose-bound identity changed")


def _v115_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v115 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v115"
    return _V69_MATERIALIZE_TASK(*args, **kwargs)


def _materialize_tasks(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    value, locks = _V112_MATERIALIZE_TASKS(manifest, v92_manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected_task_ids = [item.task_id for item in manifest.schedule]
    if not isinstance(receipts, list) or len(receipts) != len(expected_task_ids):
        raise ConfigurationError("v115 task receipt inventory is incomplete")
    for task_id, receipt in zip(expected_task_ids, receipts, strict=True):
        if not isinstance(receipt, dict) or receipt.get("task_id") != task_id:
            raise ConfigurationError("v115 task receipt ordering changed")
        receipt.pop("task_receipt_hash", None)
        receipt.update(
            {
                "format_id": ("verigym_deepseek_harness_hwe_v115_task_materialization_receipt_v1"),
                "identity": IDENTITY,
                "docker_host_binding_policy": manifest.docker_host_binding_policy,
                "nested_docker_host": manifest.nested_docker_host,
                "v112_data_volume_reused": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v115_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [receipt["task_receipt_hash"] for receipt in receipts],
            "docker_host_binding_policy": manifest.docker_host_binding_policy,
            "nested_docker_host": manifest.nested_docker_host,
            "v112_data_volume_reused": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v115 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V112_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("v112_tasks_materialized_from_completed_local_archives", None)
    base.pop("requires_independent_v113_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v115_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v112_manifest_hash": manifest.v112_manifest_hash,
            "v112_report_hash": manifest.v112_report_hash,
            "v113_audit_commit": manifest.v113_audit_commit,
            "v113_post_merge_main_run_id": manifest.v113_post_merge_main_run_id,
            "v113_audit_completed": True,
            "v115_tasks_materialized_from_completed_local_archives": True,
            "docker_host_binding_policy": manifest.docker_host_binding_policy,
            "nested_docker_host": manifest.nested_docker_host,
            "docker_cli_explicit_binding": True,
            "harness_helper_explicit_binding": True,
            "same_nested_daemon_for_runtime_and_controller": True,
            "inherited_docker_environment_used": False,
            "remote_docker_endpoint_used": False,
            "v112_data_volume_reused": False,
            "v114_identity_retired": True,
            "requires_independent_v116_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    head = _V112_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v113_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v115 requires clean merged origin/main after v113")
    return head


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
