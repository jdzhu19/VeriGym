#!/usr/bin/env python3
"""Materialize the five-task scaffold with inventory bound to the inner Docker socket."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
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

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v115_explicit_nested_docker_socket_scaffold as v115,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    load_v115_explicit_nested_docker_socket_scaffold_manifest,
    load_v118_explicit_inner_inventory_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.runtimes.docker.engine import (  # noqa: E402
    DockerCliEngine,
    validate_local_docker_host,
)
from verigym.runtimes.docker.runtime import DockerRuntime  # noqa: E402

v112 = v115.v112
v94 = v115.v94
v92 = v115.v92
v69 = v115.v69

IDENTITY = "deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V118_EXPLICIT_INNER_INVENTORY_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold_v1.json"
)
V115_MANIFEST = _REPOSITORY / (
    "configs/training/"
    "qwen35_hwe_deepseek_harness_v115_explicit_nested_docker_socket_scaffold_v1.json"
)
V115_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v115_explicit_nested_docker_socket_scaffold.py"
)
V115_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v115-explicit-nested-docker-socket-authorization.md"
)
V115_ENGINE = _REPOSITORY / "src/verigym/runtimes/docker/engine.py"
V115_PROCESS = _REPOSITORY / (
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/process.py"
)
V115_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1"
)
V115_REPORT = V115_ROOT / "execution-scaffold-report.json"
V115_PROGRESS = V115_ROOT / "execution-scaffold-progress.json"
V115_HEADROOM = V115_ROOT / "headroom-preflight.json"
V115_TASK_MATERIALIZATION = V115_ROOT / "task-materialization-set.json"
V115_INVENTORY = V115_ROOT / "execution-inventory.json"
V115_RUNTIME_RECEIPT = V115_ROOT / "dind-runtime-receipt.json"
V115_TRANSFER_SET = V115_ROOT / "image-transfer-set.json"
V115_CLEANUP = V115_ROOT / "dind-cleanup-receipt.json"
V116_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v116-v115-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v118")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v118-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v118-runtime")
_V115_RUNTIME_PATHS = (
    Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket"),
    Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v115-control"),
    Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v115-runtime"),
)
_REQUIRED_MERGED_PATHS = (
    *v115._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-04_deepseek-harness-v116-v115-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v118-explicit-inner-inventory-authorization.md",
    "scripts/materialize_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold.py",
    "integrations/verigym-deepseek-harness/tests/test_v118_explicit_inner_inventory_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "src/verigym/runtimes/docker/engine.py",
    "tests/unit/test_docker_engine.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)
_EXPECTED_COMMAND_IMAGES = {
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465": (
        "sha256:a99d74f8057cb1cdc31981d65c3ae9808959802f1c6653398d4cd575795889ac"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135": (
        "sha256:9a26021c90b55c7d179b7ecec8b2a1499a4135c4a8ed31c2e59eb41ce8a8d9aa"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780": (
        "sha256:d634ef837643a2b667292f285e85c8ee5c41f075ea6d31a6a8ccde5706e553d6"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017": (
        "sha256:841fdfdc8befc8e53ca947d31e89358bc5832826dbe597d9114c5e585f9ac857"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711": (
        "sha256:503583b4401582c4f79dcbe89b437d92f8ac18a80ea294fac6038466a4d36f6e"
    ),
}
_EXPECTED_LOCK_HASHES = {
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465": (
        "9865e7a6e766f44802de9cbf4929b40e283fb40e46153ab4931cf4125da5ff07"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135": (
        "9578e3ba96eddebbe5a4f39443ba5fc0e551c1f83699336cb493e0320015f9b9"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780": (
        "169b2710b5ebd21a2a190d9f85f1a44e8067303267046afea5324d04c678d814"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017": (
        "0b12a96dbc19de1874b5595b56e0abe963c42af571b460a0052c83a7b100a4c3"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711": (
        "ef2c86f1751b28a71883b24d765920a7d7ca33ab9094177d3e3d523ba203fa00"
    ),
}
_EXPECTED_SCAN_IDS = {
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465": (
        "5b3b794631dbb4e93ed27c5bf135e7d847107577a06ffbb04ab7e7b83b7c52b5"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135": (
        "562776474f52a5ded8ff8b7bf5a80303693c19684bdd9489903d4c40189bc02b"
    ),
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780": (
        "0cb2f442dd7e97fa26c28332e4ae7da3466728177f26634c5b8c5191e8c75366"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017": (
        "8991cb48478c29af8fdce2b36faede7516aa453115ed76cd84d5911742ac53f0"
    ),
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711": (
        "9a61d333dccbf979620538629e6c263243d9cd4510ddcb76e62e82aa605e52f1"
    ),
}

_V115_CONFIGURATION_NAMES = (
    "IDENTITY",
    "OPT_IN_ENV",
    "MANIFEST",
    "OUTPUT_ROOT",
    "DIND_PARENT",
    "DIND_DATA_BACKING",
    "DIND_SOCKET_BACKING",
    "CONTROL_ROOT",
    "RUNTIME_TMP",
    "_REQUIRED_MERGED_PATHS",
    "_load_composed_manifest",
    "_write_progress",
    "_data2_control_headroom",
    "_transfer_images",
    "_validated_nested_docker_host",
    "_runtime_prepare_preflight",
    "_harness_initialize_preflight",
    "_inventory",
    "_runtime_receipt",
    "_clean_socket_volume",
    "_validate_static_bindings",
    "_v115_materialize_task",
    "_materialize_tasks",
    "_scaffold_contract",
    "_require_clean_merged_main",
)
_V115_PREDECESSOR_BINDINGS = {name: getattr(v115, name) for name in _V115_CONFIGURATION_NAMES}
_V115_LOAD_COMPOSED_MANIFEST = v115._load_composed_manifest  # noqa: SLF001
_V115_WRITE_PROGRESS = v115._V94_WRITE_PROGRESS  # noqa: SLF001
_V115_DATA2_CONTROL_HEADROOM = v115._data2_control_headroom  # noqa: SLF001
_V115_TRANSFER_IMAGES = v115._transfer_images  # noqa: SLF001
_V115_HARNESS_INITIALIZE_PREFLIGHT = v115._harness_initialize_preflight  # noqa: SLF001
_V115_INVENTORY = v115._inventory  # noqa: SLF001
_V115_RUNTIME_RECEIPT = v115._runtime_receipt  # noqa: SLF001
_V115_CLEAN_SOCKET_VOLUME = v115._clean_socket_volume  # noqa: SLF001
_V115_VALIDATE_STATIC_BINDINGS = v115._validate_static_bindings  # noqa: SLF001
_V115_MATERIALIZE_TASKS = v115._materialize_tasks  # noqa: SLF001
_V115_SCAFFOLD_CONTRACT = v115._scaffold_contract  # noqa: SLF001
_V115_REQUIRE_CLEAN_MERGED_MAIN = v115._require_clean_merged_main  # noqa: SLF001
_V69_MATERIALIZE_TASK = v115._V69_MATERIALIZE_TASK  # noqa: SLF001


def _parser() -> argparse.ArgumentParser:
    parser = v115._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the audited v115 workflow under fresh v118 paths and bindings."""

    with _v118_configuration():
        return v115.materialize(arguments)


@contextlib.contextmanager
def _v118_configuration() -> Iterator[None]:
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
        "_load_composed_manifest": _load_composed_manifest,
        "_write_progress": _write_progress,
        "_data2_control_headroom": _data2_control_headroom,
        "_transfer_images": _transfer_images,
        "_validated_nested_docker_host": _validated_nested_docker_host,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_v115_materialize_task": _v118_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v115, name) for name in replacements}
    network_replacements = {
        "_create_internal_preflight_network": _create_internal_preflight_network,
        "_remove_internal_preflight_network": _remove_internal_preflight_network,
        "_require_preflight_network_absent": _require_preflight_network_absent,
    }
    network_previous = {name: getattr(v94, name) for name in network_replacements}
    try:
        for name, value in replacements.items():
            setattr(v115, name, value)
        for name, value in network_replacements.items():
            setattr(v94, name, value)
        yield
    finally:
        for name, value in network_previous.items():
            setattr(v94, name, value)
        for name, value in previous.items():
            setattr(v115, name, value)


@contextlib.contextmanager
def _v115_predecessor_configuration() -> Iterator[None]:
    current = {name: getattr(v115, name) for name in _V115_PREDECESSOR_BINDINGS}
    try:
        for name, value in _V115_PREDECESSOR_BINDINGS.items():
            setattr(v115, name, value)
        yield
    finally:
        for name, value in current.items():
            setattr(v115, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v118_explicit_inner_inventory_scaffold_manifest(path)
    with _v115_predecessor_configuration():
        predecessor = _V115_LOAD_COMPOSED_MANIFEST(V115_MANIFEST)
    values = vars(predecessor).copy()
    values.update(purpose.model_dump(mode="python"))
    values.update(
        {
            "schedule": predecessor.schedule,
            "dind_data_backing": purpose.dind_data_backing,
            "dind_socket_backing": purpose.dind_socket_backing,
            "control_headroom_root": purpose.control_headroom_root,
            "runtime_scratch_root": purpose.runtime_scratch_root,
            "nested_docker_host": purpose.nested_docker_host,
            "provider_successor_identity": purpose.provider_successor_identity,
            "manifest_hash": purpose.manifest_hash,
        }
    )
    return SimpleNamespace(**values)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v118 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v118_scaffold_progress_v1",
            "v115_manifest_hash": (
                "d851e4c0b2831865161f5ada6bf217d1df115dde03303925fece17e63fd4202c"
            ),
            "v115_report_hash": (
                "2116016b0b27d1ad4993a0694609194e2edc7ca7a39043e823e06c0d35b6e168"
            ),
            "v116_audit_commit": "7faf47a4ba49139bf9e93200e104b8b9e9cbfea2",
            "v116_post_merge_main_run_id": 33815411217,
            "inner_inventory_transport_policy": "explicit-bound-engine-all-resources-v1",
            "inner_network_transport_policy": "explicit-bound-engine-v1",
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "v115_data_volume_reused": False,
            "v117_identity_retired": True,
        }
    )
    if value.get("status") == "completed_pending_independent_v116_audit":
        value["status"] = "completed_pending_independent_v119_audit"
    _V115_WRITE_PROGRESS(root, value)


def _reseal(value: Mapping[str, Any], *, hash_field: str, format_id: str) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    base.pop(hash_field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, hash_field: content_hash(base)}


def _data2_control_headroom(**kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _V115_DATA2_CONTROL_HEADROOM(**kwargs),
        hash_field="preflight_hash",
        format_id="verigym_deepseek_harness_hwe_v118_data2_control_headroom_v1",
    )


def _transfer_images(
    dind_name: str,
    manifest: Any,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V115_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v118_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v118 image transfer receipt inventory is not exactly two")
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
        format_id="verigym_deepseek_harness_hwe_v118_image_transfer_set_v1",
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
        raise ConfigurationError("v118 nested Docker scope or manifest endpoint changed")
    try:
        return validate_local_docker_host(expected)
    except ValueError as exc:
        raise ConfigurationError("v118 nested Docker endpoint is unsafe") from exc


def _require_empty_bound_inner_inventory(engine: DockerCliEngine) -> None:
    containers = engine.list_all_containers()
    volumes = engine.list_all_volumes()
    if containers or volumes:
        raise ConfigurationError("v118 explicit inner Docker inventory is not empty")


def _new_bound_inner_engine(manifest: Any) -> DockerCliEngine:
    expected = f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
    if manifest.nested_docker_host != expected:
        raise ConfigurationError("v118 inner network endpoint changed")
    try:
        return DockerCliEngine(docker_host=validate_local_docker_host(expected))
    except ValueError as exc:
        raise ConfigurationError("v118 inner network endpoint is unsafe") from exc


def _require_preflight_network_absent(dind_name: str, manifest: Any) -> None:
    del dind_name
    engine = _new_bound_inner_engine(manifest)
    try:
        if engine.inspect_network(manifest.preflight_inner_network) is not None:
            raise ConfigurationError("v118 internal preflight network already exists")
    finally:
        engine.close()


def _create_internal_preflight_network(dind_name: str, manifest: Any) -> None:
    del dind_name
    engine = _new_bound_inner_engine(manifest)
    try:
        if engine.inspect_network(manifest.preflight_inner_network) is not None:
            raise ConfigurationError("v118 internal preflight network already exists")
        engine.create_internal_network(manifest.preflight_inner_network)
        value = engine.inspect_network(manifest.preflight_inner_network)
        if (
            value is None
            or value.get("Name") != manifest.preflight_inner_network
            or value.get("Driver") != "bridge"
            or value.get("Internal") is not True
            or value.get("Scope") != "local"
        ):
            raise ConfigurationError("v118 internal preflight network differs from policy")
    finally:
        engine.close()


def _remove_internal_preflight_network(dind_name: str, manifest: Any) -> None:
    del dind_name
    engine = _new_bound_inner_engine(manifest)
    try:
        engine.remove_network(manifest.preflight_inner_network)
        if engine.inspect_network(manifest.preflight_inner_network) is not None:
            raise ConfigurationError("v118 internal preflight network cleanup failed")
    finally:
        engine.close()


def _runtime_prepare_preflight(
    manifest: Any,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    del dind_name
    docker_host = _validated_nested_docker_host(manifest)
    completed: list[str] = []
    inventory_checks = 0
    for binding in manifest.schedule:
        engine = DockerCliEngine(docker_host=docker_host)
        runtime = DockerRuntime(v92._runtime_config(locks[binding.task_id]), engine=engine)  # noqa: SLF001
        try:
            runtime.prepare(f"v118-preflight-pr-{binding.pr_number}")
            _require_empty_bound_inner_inventory(engine)
            inventory_checks += 1
        finally:
            runtime.close()
        completed.append(binding.task_id)
    if len(completed) != manifest.runtime_prepare_task_count:
        raise ConfigurationError("v118 runtime prepare did not cover all five tasks")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v118_runtime_prepare_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "completed_task_ids": completed,
        "task_count": len(completed),
        "inventory_check_count": inventory_checks,
        "workspace_runtime_image_id": manifest.workspace_runtime_image_id,
        "task_network": manifest.task_network,
        "docker_host_binding_policy": manifest.docker_host_binding_policy,
        "inner_inventory_transport_policy": manifest.inner_inventory_transport_policy,
        "nested_docker_host": docker_host,
        "docker_cli_explicit_binding": True,
        "host_sidecar_inventory_for_inner_used": False,
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
    value = _V115_HARNESS_INITIALIZE_PREFLIGHT(
        manifest,
        controller_receipt_hash=controller_receipt_hash,
        root=root,
    )
    value.update(
        {
            "inner_inventory_transport_policy": manifest.inner_inventory_transport_policy,
            "inner_network_transport_policy": manifest.inner_network_transport_policy,
            "streaming_attach_explicit_binding_required": True,
            "host_sidecar_inventory_for_inner_used": False,
            "host_sidecar_network_control_for_inner_used": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v118_harness_initialize_preflight_v1",
    )


def _inventory(dind_name: str, manifest: Any) -> dict[str, Any]:
    return _reseal(
        _V115_INVENTORY(dind_name, manifest),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v118_execution_inventory_v1",
    )


def _runtime_receipt(
    manifest: Any,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V115_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value.update(
        {
            "v115_data_volume_reused": False,
            "inner_inventory_transport_policy": manifest.inner_inventory_transport_policy,
            "inner_network_transport_policy": manifest.inner_network_transport_policy,
            "host_sidecar_inventory_for_inner_allowed": False,
            "host_sidecar_network_control_for_inner_allowed": False,
            "streaming_attach_explicit_binding_required": True,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v118_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    result = _reseal(
        _V115_CLEAN_SOCKET_VOLUME(manifest, root=root),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v118_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _hash_git_file(commit: str, path: Path) -> str:
    relative = path.relative_to(_REPOSITORY).as_posix()
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0 or result.stderr:
        raise ConfigurationError("v118 could not read frozen v115 source")
    return hashlib.sha256(result.stdout).hexdigest()


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    purpose = load_v118_explicit_inner_inventory_scaffold_manifest(MANIFEST)
    predecessor_view = SimpleNamespace(**vars(manifest))
    predecessor_view.manifest_hash = purpose.v115_manifest_hash
    current_manifest = v115.MANIFEST
    try:
        v115.MANIFEST = V115_MANIFEST
        _V115_VALIDATE_STATIC_BINDINGS(
            predecessor_view,
            v92_manifest,
            v92_report,
            v92_manifest_path=v92_manifest_path,
            v92_report_path=v92_report_path,
        )
    finally:
        v115.MANIFEST = current_manifest
    report = v94._load_json(V115_REPORT)  # noqa: SLF001
    progress = v94._load_json(V115_PROGRESS)  # noqa: SLF001
    headroom = v94._load_json(V115_HEADROOM)  # noqa: SLF001
    tasks = v94._load_json(V115_TASK_MATERIALIZATION)  # noqa: SLF001
    inventory = v94._load_json(V115_INVENTORY)  # noqa: SLF001
    runtime = v94._load_json(V115_RUNTIME_RECEIPT)  # noqa: SLF001
    transfer = v94._load_json(V115_TRANSFER_SET)  # noqa: SLF001
    cleanup = v94._load_json(V115_CLEANUP)  # noqa: SLF001
    entries = list(V115_ROOT.rglob("*"))
    directories = 1 + sum(path.is_dir() and not path.is_symlink() for path in entries)
    files = sum(path.is_file() and not path.is_symlink() for path in entries)
    symlinks = sum(path.is_symlink() for path in entries)
    task_rows = {
        item.get("task_id"): item
        for item in tasks.get("task_receipts", [])
        if isinstance(item, dict) and isinstance(item.get("task_id"), str)
    }
    source_commit = purpose.v115_authorization_commit
    if (
        _hash_git_file(source_commit, V115_MANIFEST) != purpose.v115_manifest_sha256
        or purpose.v115_manifest_hash
        != load_v115_explicit_nested_docker_socket_scaffold_manifest(V115_MANIFEST).manifest_hash
        or _hash_git_file(source_commit, V115_RUNNER) != purpose.v115_runner_sha256
        or _hash_git_file(source_commit, V115_AUTHORIZATION) != purpose.v115_authorization_sha256
        or _hash_git_file(source_commit, V115_ENGINE) != purpose.v115_engine_sha256
        or _hash_git_file(source_commit, V115_PROCESS) != purpose.v115_process_sha256
        or v69._hash_file(V115_REPORT) != purpose.v115_report_sha256  # noqa: SLF001
        or v69._hash_file(V115_PROGRESS) != purpose.v115_report_sha256  # noqa: SLF001
        or v94._canonical_hash(report, "report_hash") != purpose.v115_report_hash  # noqa: SLF001
        or v94._canonical_hash(progress, "report_hash") != purpose.v115_report_hash  # noqa: SLF001
        or v69._hash_file(V115_HEADROOM) != purpose.v115_headroom_sha256  # noqa: SLF001
        or v94._canonical_hash(headroom, "preflight_hash") != purpose.v115_headroom_hash  # noqa: SLF001
        or v69._hash_file(V115_TASK_MATERIALIZATION)  # noqa: SLF001
        != purpose.v115_task_materialization_sha256
        or v94._canonical_hash(tasks, "receipt_hash")  # noqa: SLF001
        != purpose.v115_task_materialization_hash
        or v69._hash_file(V115_INVENTORY) != purpose.v115_inventory_sha256  # noqa: SLF001
        or v94._canonical_hash(inventory, "inventory_hash") != purpose.v115_inventory_hash  # noqa: SLF001
        or v69._hash_file(V115_RUNTIME_RECEIPT)  # noqa: SLF001
        != purpose.v115_runtime_receipt_sha256
        or v94._canonical_hash(runtime, "receipt_hash")  # noqa: SLF001
        != purpose.v115_runtime_receipt_hash
        or v69._hash_file(V115_TRANSFER_SET) != purpose.v115_transfer_set_sha256  # noqa: SLF001
        or v94._canonical_hash(transfer, "receipt_hash")  # noqa: SLF001
        != purpose.v115_transfer_set_hash
        or v69._hash_file(V115_CLEANUP) != purpose.v115_cleanup_sha256  # noqa: SLF001
        or v94._canonical_hash(cleanup, "receipt_hash") != purpose.v115_cleanup_hash  # noqa: SLF001
        or v69._hash_file(V116_AUDIT) != purpose.v116_audit_sha256  # noqa: SLF001
        or directories != purpose.v115_evidence_directory_count
        or files != purpose.v115_evidence_regular_file_count
        or symlinks != purpose.v115_evidence_symlink_count
    ):
        raise ConfigurationError("v118 audited v115 evidence binding changed")
    if (
        report != progress
        or report.get("identity")
        != "deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1"
        or report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "RuntimeError"
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
        or (V115_ROOT / "preflight/runtime-prepare.json").exists()
        or (V115_ROOT / "preflight/harness-initialize.json").exists()
        or (V115_ROOT / "final-execution-inventory.json").exists()
        or (V115_ROOT / "execution-scaffold-contract.json").exists()
    ):
        raise ConfigurationError("v118 requires the exact audited v115 provider-free stop")
    if (
        headroom.get("status") != "passed"
        or tasks.get("completed_task_ids") != purpose.schedule_task_ids
        or tasks.get("all_base_failed_reference_passed") is not True
        or tasks.get("all_command_images_v2_scanned") is not True
        or inventory.get("required_images_present") is not True
        or inventory.get("required_image_count") != 12
        or inventory.get("fresh_command_image_count") != 5
        or inventory.get("observed_image_count") != 17
        or inventory.get("inner_container_inventory_empty") is not True
        or inventory.get("inner_volume_inventory_empty") is not True
        or cleanup.get("socket_volume_removed") is not True
        or cleanup.get("socket_backing_empty") is not True
    ):
        raise ConfigurationError("v118 requires the audited v115 qualification and cleanup state")
    if set(task_rows) != set(purpose.schedule_task_ids) or any(
        row.get("base_failed") is not True
        or row.get("base_infrastructure_error") is not False
        or row.get("reference_passed") is not True
        or row.get("agent_command_image") != _EXPECTED_COMMAND_IMAGES[task_id]
        or row.get("agent_command_image_lock_hash") != _EXPECTED_LOCK_HASHES[task_id]
        or row.get("security_scan_id") != _EXPECTED_SCAN_IDS[task_id]
        or row.get("verifier_network") != "none"
        or row.get("agent_command_network") != "none"
        or row.get("provider_calls") != 0
        or row.get("model_process_count") != 0
        for task_id, row in task_rows.items()
    ):
        raise ConfigurationError("v118 requires all five exact audited v115 task results")
    v115_data = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v115/data")
    if (
        v115_data.is_symlink()
        or not v115_data.is_dir()
        or any(
            path.is_symlink() or not path.is_dir() or next(path.iterdir(), None) is not None
            for path in _V115_RUNTIME_PATHS
        )
    ):
        raise ConfigurationError("v118 requires frozen v115 data and empty runtime paths")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", purpose.v116_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v118 requires the merged v116 audit")
    if (
        manifest.manifest_hash != purpose.manifest_hash
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.control_headroom_root != str(CONTROL_ROOT)
        or manifest.runtime_scratch_root != str(RUNTIME_TMP)
        or manifest.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or purpose.inner_inventory_transport_policy != "explicit-bound-engine-all-resources-v1"
        or purpose.inner_network_transport_policy != "explicit-bound-engine-v1"
        or purpose.host_sidecar_inventory_for_inner_allowed is not False
        or purpose.host_sidecar_network_control_for_inner_allowed is not False
        or purpose.v115_data_volume_reused is not False
        or purpose.v117_identity_retired is not True
        or purpose.provider_credentials_available is not False
        or purpose.registry_access_allowed is not False
    ):
        raise ConfigurationError("v118 purpose-bound identity changed")


def _v118_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v118 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v118"
    return _V69_MATERIALIZE_TASK(*args, **kwargs)


def _materialize_tasks(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    value, locks = _V115_MATERIALIZE_TASKS(manifest, v92_manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected_task_ids = [item.task_id for item in manifest.schedule]
    if not isinstance(receipts, list) or len(receipts) != len(expected_task_ids):
        raise ConfigurationError("v118 task receipt inventory is incomplete")
    for task_id, receipt in zip(expected_task_ids, receipts, strict=True):
        if not isinstance(receipt, dict) or receipt.get("task_id") != task_id:
            raise ConfigurationError("v118 task receipt ordering changed")
        receipt.pop("task_receipt_hash", None)
        receipt.update(
            {
                "format_id": "verigym_deepseek_harness_hwe_v118_task_materialization_receipt_v1",
                "identity": IDENTITY,
                "inner_inventory_transport_policy": manifest.inner_inventory_transport_policy,
                "inner_network_transport_policy": manifest.inner_network_transport_policy,
                "v115_data_volume_reused": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v118_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [receipt["task_receipt_hash"] for receipt in receipts],
            "inner_inventory_transport_policy": manifest.inner_inventory_transport_policy,
            "inner_network_transport_policy": manifest.inner_network_transport_policy,
            "v115_data_volume_reused": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v118 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V115_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("v115_tasks_materialized_from_completed_local_archives", None)
    base.pop("requires_independent_v116_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v118_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v115_manifest_hash": manifest.v115_manifest_hash,
            "v115_report_hash": manifest.v115_report_hash,
            "v116_audit_commit": manifest.v116_audit_commit,
            "v116_post_merge_main_run_id": manifest.v116_post_merge_main_run_id,
            "v116_audit_completed": True,
            "v118_tasks_materialized_from_completed_local_archives": True,
            "inner_inventory_transport_policy": manifest.inner_inventory_transport_policy,
            "inner_network_transport_policy": manifest.inner_network_transport_policy,
            "all_inner_containers_queried_through_bound_engine": True,
            "all_inner_volumes_queried_through_bound_engine": True,
            "host_sidecar_inventory_for_inner_used": False,
            "inner_network_managed_through_bound_engine": True,
            "host_sidecar_network_control_for_inner_used": False,
            "streaming_attach_explicit_binding_required": True,
            "v115_data_volume_reused": False,
            "v117_identity_retired": True,
            "requires_independent_v119_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    head = _V115_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v116_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v118 requires clean merged origin/main after v116")
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
