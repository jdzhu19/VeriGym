#!/usr/bin/env python3
"""Materialize the five-task scaffold after exact bounded DinD readiness."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
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
    materialize_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold as v118,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    load_v118_explicit_inner_inventory_scaffold_manifest,
    load_v125_bounded_dind_readiness_probe_manifest,
    load_v127_readiness_gated_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.runtimes.docker.engine import DockerCliEngine  # noqa: E402
from verigym.runtimes.docker.runtime import DockerRuntime  # noqa: E402

v94 = v118.v94
v92 = v118.v92
v69 = v118.v69
dind = v94.dind

IDENTITY = "deepseek-harness-hwe-v127-readiness-gated-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V127_READINESS_GATED_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v127_readiness_gated_scaffold_v1.json"
)
V118_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold_v1.json"
)
V118_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold.py"
)
V118_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v118-explicit-inner-inventory-authorization.md"
)
V119_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v119-v118-result.md"
V125_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v125_bounded_dind_readiness_probe_v1.json"
)
V125_RUNNER = _REPOSITORY / (
    "scripts/run_hwe_deepseek_harness_v125_bounded_dind_readiness_probe.py"
)
V125_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v125-bounded-dind-readiness-probe-authorization.md"
)
V126_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v126-v125-result.md"
V125_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1"
)
V125_FILES = {
    "cleanup": V125_ROOT / "cleanup-receipt.json",
    "headroom": V125_ROOT / "headroom-preflight.json",
    "host_image": V125_ROOT / "host-image-identity.json",
    "predecessor": V125_ROOT / "predecessor-preflight.json",
    "progress": V125_ROOT / "readiness-probe-progress.json",
    "probe": V125_ROOT / "readiness-probe-receipt.json",
    "report": V125_ROOT / "readiness-probe-report.json",
    "volume_setup": V125_ROOT / "volume-setup-receipt.json",
}
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v127-readiness-gated-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v127")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v127-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v127-runtime")

_REQUIRED_MERGED_PATHS = (
    *v118._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-04_deepseek-harness-v119-v118-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v125_bounded_dind_readiness_probe_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v125-bounded-dind-readiness-probe-authorization.md",
    "scripts/run_hwe_deepseek_harness_v125_bounded_dind_readiness_probe.py",
    "integrations/verigym-deepseek-harness/tests/test_v125_bounded_dind_readiness_probe.py",
    "docs/audits/2026-09-04_deepseek-harness-v126-v125-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v127_readiness_gated_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v127-readiness-gated-scaffold-authorization.md",
    "scripts/materialize_hwe_deepseek_harness_v127_readiness_gated_scaffold.py",
    "integrations/verigym-deepseek-harness/tests/test_v127_readiness_gated_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)
_V125_FILE_BINDINGS = {
    "cleanup": (
        "0006e7c1d66404aa48dd0b36a0a5bd446cfbd27a8995e15081047adc5fbe71af",
        "receipt_hash",
        "3c6d805971c794b1c30c04c61f7a26b0a422e2f43c4d077c9e7d9532e2c3b1c8",
    ),
    "headroom": (
        "6b4975525dd44695355f0cd07ef0061ef800b5e8a5911636537106c44f673b04",
        "preflight_hash",
        "20aa1801f60fe36698dcb1f2e0a8517e969c2b76d1e189ecfe3f11163092e3b6",
    ),
    "host_image": (
        "8ebd2a52e7c0b907fddbb2a8dbff375910d1fcc212b33f2309f2d98f59097a99",
        "receipt_hash",
        "99dbb43543c20b702213b5fe700eb942695146be6bc103479775d37c70e64678",
    ),
    "predecessor": (
        "5cfc3ba33881b599c068a02d29a903ba4ab40c2c81fba8611f1a0d61dfd27d18",
        "receipt_hash",
        "dbf54ae4d2a7d536ed2b52b35957e3e04dffbe26d8b1dd1f2b46094addc7bfc6",
    ),
    "progress": (
        "a168356b7289d1e306ef915835f6cf2c42d164b8317aa0d758fc98ee1f6a9976",
        "report_hash",
        "6da2ba5dcff5aa424aea2bc1af02157c703fedd12fa6ae11897b3fad0ba9b7de",
    ),
    "probe": (
        "b5102f595d1353ad12111cdf026c1c0d10434ba240d6d2204c688fd398820afc",
        "receipt_hash",
        "23fc06716d775e4f132e30b8cc0fdf79e3c246f39f632b78f77703cd414160fc",
    ),
    "report": (
        "a168356b7289d1e306ef915835f6cf2c42d164b8317aa0d758fc98ee1f6a9976",
        "report_hash",
        "6da2ba5dcff5aa424aea2bc1af02157c703fedd12fa6ae11897b3fad0ba9b7de",
    ),
    "volume_setup": (
        "a0b52260aa6409229d3997bcd58301ee3d015c5756872fd5378264cbc21838eb",
        "receipt_hash",
        "43c08c8d86321a45b92cec31a5d02b5108bab9323c210770158b587eb08b3250",
    ),
}
_EXPECTED_READINESS = ("23.0.6", "vfs", "runc")
_SUCCESS_STATUS_NAMES = {
    "completed_pending_independent_v95_audit",
    "completed_pending_independent_v98_audit",
    "completed_pending_independent_v101_audit",
    "completed_pending_independent_v104_audit",
    "completed_pending_independent_v107_audit",
    "completed_pending_independent_v110_audit",
    "completed_pending_independent_v113_audit",
    "completed_pending_independent_v116_audit",
    "completed_pending_independent_v119_audit",
}

_V118_CONFIGURATION_NAMES = (
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
    "_runtime_prepare_preflight",
    "_harness_initialize_preflight",
    "_inventory",
    "_runtime_receipt",
    "_clean_socket_volume",
    "_validate_static_bindings",
    "_v118_materialize_task",
    "_materialize_tasks",
    "_scaffold_contract",
    "_require_clean_merged_main",
)
_V118_PREDECESSOR_BINDINGS = {name: getattr(v118, name) for name in _V118_CONFIGURATION_NAMES}
_V118_LOAD_COMPOSED_MANIFEST = v118._load_composed_manifest  # noqa: SLF001
_V118_WRITE_PROGRESS = v118._V115_WRITE_PROGRESS  # noqa: SLF001
_V118_DATA2_CONTROL_HEADROOM = v118._data2_control_headroom  # noqa: SLF001
_V118_TRANSFER_IMAGES = v118._transfer_images  # noqa: SLF001
_V118_HARNESS_INITIALIZE_PREFLIGHT = v118._harness_initialize_preflight  # noqa: SLF001
_V118_INVENTORY = v118._inventory  # noqa: SLF001
_V118_RUNTIME_RECEIPT = v118._runtime_receipt  # noqa: SLF001
_V118_CLEAN_SOCKET_VOLUME = v118._clean_socket_volume  # noqa: SLF001
_V118_MATERIALIZE_TASKS = v118._materialize_tasks  # noqa: SLF001
_V118_SCAFFOLD_CONTRACT = v118._scaffold_contract  # noqa: SLF001
_V118_REQUIRE_CLEAN_MERGED_MAIN = v118._require_clean_merged_main  # noqa: SLF001
_V69_MATERIALIZE_TASK = v118._V69_MATERIALIZE_TASK  # noqa: SLF001
_DIND_START = dind._start_dind  # noqa: SLF001
_DIND_OWNER = dind._DIND_OWNER  # noqa: SLF001


def _parser() -> argparse.ArgumentParser:
    parser = v118._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the frozen five-task workflow under the v127 readiness gate."""

    with _v127_configuration():
        return v118.materialize(arguments)


@contextlib.contextmanager
def _v127_configuration() -> Iterator[None]:
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
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_v118_materialize_task": _v127_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v118, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v118, name, value)
        dind._start_dind = _start_dind  # noqa: SLF001
        dind._DIND_OWNER = IDENTITY  # noqa: SLF001
        yield
    finally:
        dind._DIND_OWNER = _DIND_OWNER  # noqa: SLF001
        dind._start_dind = _DIND_START  # noqa: SLF001
        for name, value in previous.items():
            setattr(v118, name, value)


@contextlib.contextmanager
def _v118_predecessor_configuration() -> Iterator[None]:
    current = {name: getattr(v118, name) for name in _V118_PREDECESSOR_BINDINGS}
    try:
        for name, value in _V118_PREDECESSOR_BINDINGS.items():
            setattr(v118, name, value)
        yield
    finally:
        for name, value in current.items():
            setattr(v118, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v127_readiness_gated_scaffold_manifest(path)
    with _v118_predecessor_configuration():
        predecessor = _V118_LOAD_COMPOSED_MANIFEST(V118_MANIFEST)
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
        raise ConfigurationError("v127 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v127_scaffold_progress_v1",
            "identity": IDENTITY,
            "v118_manifest_hash": (
                "c646f65d13b19096cf46ed4a9e3ab24a79c94382cd1d1ea9ab36c36c667bf72d"
            ),
            "v119_audit_commit": "c22066916ba51e8c74678be2b0af6ac8d438ac9a",
            "v125_manifest_hash": (
                "76de583642c6614d80a4b4bac1b95a4f2bd533e3be42a6b5caac3f9fd6ad07c0"
            ),
            "v125_report_hash": (
                "6da2ba5dcff5aa424aea2bc1af02157c703fedd12fa6ae11897b3fad0ba9b7de"
            ),
            "v125_probe_hash": ("23fc06716d775e4f132e30b8cc0fdf79e3c246f39f632b78f77703cd414160fc"),
            "v126_audit_commit": "084afb7c6e690f222d8274871c4fcc51ecf1a56a",
            "readiness_probe_policy": "explicit-three-field-exact-monotonic-deadline-v1",
            "readiness_timeout_seconds": 120,
            "readiness_command_timeout_seconds": 5,
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    if value.get("status") in _SUCCESS_STATUS_NAMES:
        value["status"] = "completed_pending_independent_v128_audit"
    _V118_WRITE_PROGRESS(root, value)


def _reseal(value: Mapping[str, Any], *, hash_field: str, format_id: str) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    base.pop(hash_field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, hash_field: content_hash(base)}


def _data2_control_headroom(**kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _V118_DATA2_CONTROL_HEADROOM(**kwargs),
        hash_field="preflight_hash",
        format_id="verigym_deepseek_harness_hwe_v127_data2_control_headroom_v1",
    )


def _transfer_images(
    dind_name: str,
    manifest: Any,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V118_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v127_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v127 image transfer receipt inventory is not exactly two")
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
        format_id="verigym_deepseek_harness_hwe_v127_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(
    manifest: Any,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    del dind_name
    docker_host = v118._validated_nested_docker_host(manifest)  # noqa: SLF001
    completed: list[str] = []
    inventory_checks = 0
    for binding in manifest.schedule:
        engine = DockerCliEngine(docker_host=docker_host)
        runtime = DockerRuntime(v92._runtime_config(locks[binding.task_id]), engine=engine)  # noqa: SLF001
        try:
            runtime.prepare(f"v127-preflight-pr-{binding.pr_number}")
            v118._require_empty_bound_inner_inventory(engine)  # noqa: SLF001
            inventory_checks += 1
        finally:
            runtime.close()
        completed.append(binding.task_id)
    if len(completed) != manifest.runtime_prepare_task_count:
        raise ConfigurationError("v127 runtime prepare did not cover all five tasks")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v127_runtime_prepare_preflight_v1",
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
    value = _V118_HARNESS_INITIALIZE_PREFLIGHT(
        manifest,
        controller_receipt_hash=controller_receipt_hash,
        root=root,
    )
    value.update(
        {
            "readiness_probe_policy": manifest.readiness_probe_policy,
            "v125_readiness_qualified": True,
            "v126_audit_commit": manifest.v126_audit_commit,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v127_harness_initialize_preflight_v1",
    )


def _inventory(dind_name: str, manifest: Any) -> dict[str, Any]:
    return _reseal(
        _V118_INVENTORY(dind_name, manifest),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v127_execution_inventory_v1",
    )


def _runtime_receipt(
    manifest: Any,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V118_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value.update(
        {
            "server_version": metadata.get("ServerVersion"),
            "readiness_poll_count": metadata.get("v127_readiness_poll_count"),
            "readiness_probe_policy": manifest.readiness_probe_policy,
            "readiness_timeout_seconds": manifest.readiness_timeout_seconds,
            "readiness_command_timeout_seconds": manifest.readiness_command_timeout_seconds,
            "json_info_readiness_used": False,
            "fixed_poll_count_cap_used": False,
            "v125_manifest_hash": manifest.v125_manifest_hash,
            "v125_report_hash": manifest.v125_report_hash,
            "v125_probe_hash": manifest.v125_probe_hash,
            "v126_audit_commit": manifest.v126_audit_commit,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v127_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    value = _V118_CLEAN_SOCKET_VOLUME(manifest, root=root)
    value.update(
        {
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v127_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _start_dind(
    *,
    name: str,
    image_id: str,
    socket_volume: str,
    data_volume: str,
    source_volume: str | None,
    scratch_volume: str | None,
    empty_home: Path,
    same_path_mounts: list[str],
    startup_timeout_s: int,
    on_container_started: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if startup_timeout_s != 120:
        raise RuntimeError("isolated DinD readiness policy changed")
    project_volumes: list[str] = []
    if source_volume is not None:
        project_volumes.extend(["--volume", f"{source_volume}:/verigym-source:ro"])
    if scratch_volume is not None:
        project_volumes.extend(["--volume", f"{scratch_volume}:/verigym-scratch:rw"])
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        f"verigym.owner={IDENTITY}",
        "--label",
        "verigym.role=daemon",
        "--privileged",
        "--network",
        "none",
        "--pids-limit",
        "32768",
        "--env",
        "DOCKER_TLS_CERTDIR=",
        "--volume",
        f"{socket_volume}:/var/run:rw",
        "--volume",
        f"{data_volume}:/var/lib/docker:rw",
        *project_volumes,
        "--mount",
        f"type=bind,src={empty_home},dst=/verigym-host-sentinel,readonly",
        *same_path_mounts,
        image_id,
        "--storage-driver=vfs",
        "--iptables=false",
        "--ip6tables=false",
        "--bridge=none",
        f"--group={os.getgid()}",
    ]
    started = dind._run(command, timeout_s=60)  # noqa: SLF001
    if started.returncode != 0:
        raise RuntimeError("isolated DinD daemon container failed to start")
    if on_container_started is not None:
        on_container_started()
    deadline = time.monotonic() + 120
    poll_count = 0
    while time.monotonic() < deadline:
        poll_count += 1
        try:
            ready = dind._run(  # noqa: SLF001
                [
                    "docker",
                    "exec",
                    name,
                    "docker",
                    "info",
                    "--format",
                    "{{.ServerVersion}}\t{{.Driver}}\t{{.DefaultRuntime}}",
                ],
                timeout_s=5,
            )
        except subprocess.TimeoutExpired:
            ready = None
        if ready is not None and ready.returncode == 0 and not ready.stderr:
            try:
                values = ready.stdout.decode().rstrip("\r\n").split("\t")
            except UnicodeDecodeError:
                values = []
            if len(values) == 3:
                if tuple(values) != _EXPECTED_READINESS:
                    raise RuntimeError("isolated DinD daemon identity differs from policy")
                break
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1.0, remaining))
    else:
        raise RuntimeError("isolated DinD daemon did not become ready")
    try:
        root = dind._run(  # noqa: SLF001
            ["docker", "exec", name, "docker", "info", "--format", "{{.DockerRootDir}}"],
            timeout_s=5,
        )
        socket_gid = dind._run(  # noqa: SLF001
            ["docker", "exec", name, "stat", "-c", "%g", "/var/run/docker.sock"],
            timeout_s=5,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("isolated DinD daemon controls differ from policy") from exc
    if (
        root.returncode != 0
        or root.stderr
        or root.stdout.decode(errors="replace").strip() != "/var/lib/docker"
        or socket_gid.returncode != 0
        or socket_gid.stderr
        or socket_gid.stdout.decode(errors="replace").strip() != str(os.getgid())
    ):
        raise RuntimeError("isolated DinD daemon controls differ from policy")
    return {
        "ServerVersion": _EXPECTED_READINESS[0],
        "Driver": _EXPECTED_READINESS[1],
        "DefaultRuntime": _EXPECTED_READINESS[2],
        "DockerRootDir": "/var/lib/docker",
        "v127_readiness_poll_count": poll_count,
        "v127_readiness_probe_policy": "explicit-three-field-exact-monotonic-deadline-v1",
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_v125_evidence() -> dict[str, dict[str, Any]]:
    values = {name: v94._load_json(path) for name, path in V125_FILES.items()}  # noqa: SLF001
    entries = list(V125_ROOT.rglob("*"))
    directories = 1 + sum(path.is_dir() and not path.is_symlink() for path in entries)
    files = sum(path.is_file() and not path.is_symlink() for path in entries)
    symlinks = sum(path.is_symlink() for path in entries)
    if directories != 1 or files != 8 or symlinks != 0:
        raise ConfigurationError("v127 audited v125 evidence inventory changed")
    if V125_ROOT.is_symlink() or V125_ROOT.stat().st_mode & 0o777 != 0o700:
        raise ConfigurationError("v127 audited v125 evidence root permissions changed")
    for name, (sha256, hash_field, canonical) in _V125_FILE_BINDINGS.items():
        path = V125_FILES[name]
        if (
            path.is_symlink()
            or path.stat().st_mode & 0o777 != 0o600
            or _hash_file(path) != sha256
            or v94._canonical_hash(values[name], hash_field) != canonical  # noqa: SLF001
        ):
            raise ConfigurationError("v127 audited v125 evidence binding changed")
    return values


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    del v92_report, v92_manifest_path, v92_report_path
    purpose = load_v127_readiness_gated_scaffold_manifest(MANIFEST)
    predecessor = load_v118_explicit_inner_inventory_scaffold_manifest(V118_MANIFEST)
    readiness = load_v125_bounded_dind_readiness_probe_manifest(V125_MANIFEST)
    values = _load_v125_evidence()
    report = values["report"]
    probe = values["probe"]
    cleanup = values["cleanup"]
    if (
        _hash_file(V118_MANIFEST) != purpose.v118_manifest_sha256
        or predecessor.manifest_hash != purpose.v118_manifest_hash
        or _hash_file(V118_RUNNER) != purpose.v118_runner_sha256
        or _hash_file(V118_AUTHORIZATION) != purpose.v118_authorization_sha256
        or _hash_file(V119_AUDIT) != purpose.v119_audit_sha256
        or _hash_file(V125_MANIFEST) != purpose.v125_manifest_sha256
        or readiness.manifest_hash != purpose.v125_manifest_hash
        or _hash_file(V125_RUNNER) != purpose.v125_runner_sha256
        or _hash_file(V125_AUTHORIZATION) != purpose.v125_authorization_sha256
        or _hash_file(V126_AUDIT) != purpose.v126_audit_sha256
        or manifest.schedule != v92_manifest.schedule
        or [item.task_id for item in manifest.schedule] != purpose.schedule_task_ids
        or manifest.seed != purpose.seed
        or manifest.sample_index != purpose.sample_index
        or manifest.manifest_hash != purpose.manifest_hash
    ):
        raise ConfigurationError("v127 predecessor or immutable schedule binding changed")
    if (
        report != values["progress"]
        or report.get("identity") != "deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1"
        or report.get("status") != "completed_pending_independent_v126_audit"
        or report.get("source_commit") != purpose.v125_source_commit
        or report.get("post_merge_main_run_id") != purpose.v125_post_merge_main_run_id
        or report.get("manifest_hash") != purpose.v125_manifest_hash
        or report.get("diagnostic_complete") is not True
        or report.get("diagnostic_category") != "dind_identity_qualified"
        or report.get("dind_identity_qualified") is not True
        or report.get("cleanup_confirmed") is not True
        or report.get("startup_attempt_count") != 1
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or any(report.get(name) is not False for name in v94._closed_training_flags())  # noqa: SLF001
        or probe.get("status") != "passed"
        or probe.get("daemon_ready") is not True
        or probe.get("identity_qualified") is not True
        or probe.get("readiness_poll_count") != purpose.v125_readiness_poll_count
        or probe.get("readiness_last_category") != "complete_identity"
        or probe.get("readiness_exit_code") != 0
        or probe.get("readiness_stderr_bytes") != 0
        or probe.get("readiness_value_count") != 3
        or probe.get("json_info_readiness_used") is not False
        or probe.get("fixed_poll_count_cap_used") is not False
        or any(
            probe.get(name) is not True
            for name in (
                "readiness_server_version_equal",
                "readiness_driver_equal",
                "readiness_default_runtime_equal",
            )
        )
        or cleanup.get("status") != "passed"
        or cleanup.get("main_container_removed") is not True
        or cleanup.get("data_volume_removed") is not True
        or cleanup.get("socket_volume_removed") is not True
        or cleanup.get("data_backing_empty_and_ownership_restored") is not True
        or cleanup.get("socket_backing_empty_and_ownership_restored") is not True
        or cleanup.get("predecessor_volumes_inspected") is not False
        or cleanup.get("predecessor_volumes_mutated") is not False
    ):
        raise ConfigurationError("v127 requires the exact audited v125 terminal state")
    if (
        manifest.dind_image_id != purpose.dind_image_id
        or manifest.dind_repository_digest != purpose.dind_repository_digest
        or manifest.dind_server_version != _EXPECTED_READINESS[0]
        or manifest.dind_storage_driver != _EXPECTED_READINESS[1]
        or manifest.dind_default_runtime != _EXPECTED_READINESS[2]
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.dind_data_volume != "verigym-deepseek-harness-v127-dind-data"
        or manifest.dind_socket_volume != "verigym-deepseek-harness-v127-dind-socket"
        or manifest.control_headroom_root != str(CONTROL_ROOT)
        or manifest.runtime_scratch_root != str(RUNTIME_TMP)
        or purpose.output_root != str(OUTPUT_ROOT)
        or manifest.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or purpose.dind_owner != IDENTITY
        or purpose.startup_attempt_limit != 1
        or purpose.startup_command_timeout_seconds != 60
        or purpose.readiness_timeout_seconds != 120
        or purpose.readiness_command_timeout_seconds != 5
        or purpose.readiness_poll_interval_seconds != 1
        or purpose.readiness_probe_policy != "explicit-three-field-exact-monotonic-deadline-v1"
        or purpose.json_info_readiness_allowed is not False
        or purpose.fixed_poll_count_cap_allowed is not False
        or purpose.explicit_readiness_requires_empty_stderr is not True
        or purpose.explicit_readiness_requires_three_values is not True
        or purpose.explicit_readiness_requires_exact_identity is not True
        or purpose.docker_host_binding_policy != "explicit-canonical-local-unix-socket-v1"
        or purpose.docker_cli_explicit_binding_required is not True
        or purpose.harness_helper_explicit_binding_required is not True
        or purpose.inherited_docker_environment_allowed is not False
        or purpose.remote_docker_endpoint_allowed is not False
        or purpose.inner_inventory_transport_policy != "explicit-bound-engine-all-resources-v1"
        or purpose.inner_inventory_all_containers_required is not True
        or purpose.inner_inventory_all_volumes_required is not True
        or purpose.host_sidecar_inventory_for_inner_allowed is not False
        or purpose.inner_network_transport_policy != "explicit-bound-engine-v1"
        or purpose.host_sidecar_network_control_for_inner_allowed is not False
        or purpose.streaming_attach_explicit_binding_required is not True
        or purpose.fresh_bind_backed_volumes_required is not True
        or purpose.predecessor_volume_inspection_allowed is not False
        or purpose.predecessor_volume_mutation_allowed is not False
        or purpose.provider_successor_identity != "deepseek-harness-hwe-v129-official-matrix-v1"
        or purpose.provider_successor_reopen_budget != 1
        or purpose.registry_access_allowed is not False
        or purpose.partial_archive_allowed is not False
        or purpose.provider_credentials_available is not False
        or purpose.requires_independent_v128_audit is not True
        or purpose.v126_post_merge_main_all_eight_classes_passed is not True
        or any(getattr(purpose, name) is not False for name in v94._closed_training_flags())  # noqa: SLF001
    ):
        raise ConfigurationError("v127 purpose-bound readiness or isolation policy changed")
    for commit in (purpose.v119_audit_commit, purpose.v126_audit_commit):
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=_REPOSITORY,
            check=False,
            capture_output=True,
            text=True,
        )
        if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
            raise ConfigurationError("v127 requires both independent audits merged")


def _v127_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v127 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v127"
    return _V69_MATERIALIZE_TASK(*args, **kwargs)


def _materialize_tasks(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    value, locks = _V118_MATERIALIZE_TASKS(manifest, v92_manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected_task_ids = [item.task_id for item in manifest.schedule]
    if not isinstance(receipts, list) or len(receipts) != len(expected_task_ids):
        raise ConfigurationError("v127 task receipt inventory is incomplete")
    for task_id, receipt in zip(expected_task_ids, receipts, strict=True):
        if not isinstance(receipt, dict) or receipt.get("task_id") != task_id:
            raise ConfigurationError("v127 task receipt ordering changed")
        receipt.pop("task_receipt_hash", None)
        receipt.update(
            {
                "format_id": "verigym_deepseek_harness_hwe_v127_task_materialization_receipt_v1",
                "identity": IDENTITY,
                "readiness_probe_policy": manifest.readiness_probe_policy,
                "v125_readiness_qualified": True,
                "predecessor_volumes_inspected": False,
                "predecessor_volumes_mutated": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v127_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [receipt["task_receipt_hash"] for receipt in receipts],
            "readiness_probe_policy": manifest.readiness_probe_policy,
            "v125_readiness_qualified": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v127 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V118_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    for key in (
        "v118_tasks_materialized_from_completed_local_archives",
        "requires_independent_v119_audit",
    ):
        base.pop(key, None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v127_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v118_manifest_hash": manifest.v118_manifest_hash,
            "v119_audit_commit": manifest.v119_audit_commit,
            "v125_manifest_hash": manifest.v125_manifest_hash,
            "v125_report_hash": manifest.v125_report_hash,
            "v125_probe_hash": manifest.v125_probe_hash,
            "v125_readiness_poll_count": manifest.v125_readiness_poll_count,
            "v126_audit_commit": manifest.v126_audit_commit,
            "v126_post_merge_main_run_id": manifest.v126_post_merge_main_run_id,
            "v126_audit_completed": True,
            "v127_tasks_materialized_from_completed_local_archives": True,
            "readiness_probe_policy": manifest.readiness_probe_policy,
            "readiness_timeout_seconds": manifest.readiness_timeout_seconds,
            "readiness_command_timeout_seconds": manifest.readiness_command_timeout_seconds,
            "json_info_readiness_used": False,
            "fixed_poll_count_cap_used": False,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "requires_independent_v128_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    head = _V118_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v126_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v127 requires clean merged origin/main after v126")
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
