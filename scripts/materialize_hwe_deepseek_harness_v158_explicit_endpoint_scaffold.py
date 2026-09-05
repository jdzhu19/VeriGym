#!/usr/bin/env python3
"""Materialize and qualify five fresh tasks over one explicitly bound nested Docker endpoint."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import secrets
import stat
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

from scripts import collect_ibex_hwe_deepseek_harness_v67_provider_canary as v67  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v148_cleanup_identity_scaffold as v148,
)
from scripts.scan_and_lock_cva6_hwe_command_image import (  # noqa: E402
    CommandImageScanRuntimePolicy,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness import DEEPSEEK_HARNESS_MODEL  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV92OfficialMatrixManifest,
    HweOfflineTaskLock,
    load_v158_explicit_endpoint_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID  # noqa: E402
from verigym.registry.base import PluginRegistry  # noqa: E402
from verigym.runtimes.docker.engine import DockerCliEngine  # noqa: E402
from verigym.runtimes.docker.runtime import DockerRuntime  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v158-explicit-endpoint-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V158_EXPLICIT_ENDPOINT_SCAFFOLD"
CHILD_BOUNDARY_ENV = "VERIGYM_V158_ZERO_PROVIDER_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v158_explicit_endpoint_scaffold_v1.json"
)
V148_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v148_cleanup_identity_scaffold_v1.json"
)
V148_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v148_cleanup_identity_scaffold.py"
)
V148_LAUNCHER = _REPOSITORY / (
    "scripts/launch_hwe_deepseek_harness_v148_cleanup_identity_scaffold.py"
)
V148_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v148-cleanup-identity-scaffold-authorization.md"
)
V156_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v156_command_runtime_diagnostic_v1.json"
)
V156_RUNNER = _REPOSITORY / "scripts/run_hwe_deepseek_harness_v156_command_runtime_diagnostic.py"
V156_LAUNCHER = _REPOSITORY / (
    "scripts/launch_hwe_deepseek_harness_v156_command_runtime_diagnostic.py"
)
V156_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v156-command-runtime-diagnostic-authorization.md"
)
V156_REPORT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v156-command-runtime-diagnostic-v1/command-runtime-report.json"
)
V157_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v157-v156-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v158-explicit-endpoint-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v158")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v158-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v158-runtime")
_TASK_PR_NUMBERS = frozenset({465, 1135, 1780, 2017, 2711})
_DOCKER_CONTROL_TIMEOUT_SECONDS = 300
_OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS = 900
_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS = 300
_COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS = 300

_REQUIRED_MERGED_PATHS = (
    *v148._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "configs/training/qwen35_hwe_deepseek_harness_v156_command_runtime_diagnostic_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v156-command-runtime-diagnostic-authorization.md",
    "scripts/launch_hwe_deepseek_harness_v156_command_runtime_diagnostic.py",
    "scripts/run_hwe_deepseek_harness_v156_command_runtime_diagnostic.py",
    "docs/audits/2026-09-05_deepseek-harness-v157-v156-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v158_explicit_endpoint_scaffold_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v158-explicit-endpoint-scaffold-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v158_explicit_endpoint_scaffold.py",
    "scripts/launch_hwe_deepseek_harness_v158_explicit_endpoint_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v158_explicit_endpoint_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "src/verigym/runtimes/docker/runtime.py",
    "tests/unit/test_docker_session.py",
)

_PATCH_NAMES = (
    "IDENTITY",
    "OPT_IN_ENV",
    "CHILD_BOUNDARY_ENV",
    "MANIFEST",
    "OUTPUT_ROOT",
    "DIND_PARENT",
    "DIND_DATA_BACKING",
    "DIND_SOCKET_BACKING",
    "CONTROL_ROOT",
    "RUNTIME_TMP",
    "_REQUIRED_MERGED_PATHS",
    "_require_v148_environment_boundary",
    "_load_composed_manifest",
    "_write_progress",
    "_transfer_images",
    "_runtime_prepare_preflight",
    "_harness_initialize_preflight",
    "_inventory",
    "_runtime_receipt",
    "_clean_socket_volume",
    "_write_cleanup_diagnostic",
    "_validate_static_bindings",
    "_bounded_scan_and_lock",
    "_write_import_diagnostic",
    "_v148_materialize_task",
    "_materialize_tasks",
    "_scaffold_contract",
    "_require_clean_merged_main",
)
_V148_BASELINE = {name: getattr(v148, name) for name in _PATCH_NAMES}


def _parser() -> argparse.ArgumentParser:
    parser = v148._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the fresh provider-free qualification with no predecessor-volume access."""

    _require_v158_environment_boundary()
    with _v158_configuration():
        return v148.materialize(arguments)


def _require_v158_environment_boundary() -> None:
    purpose = load_v158_explicit_endpoint_scaffold_manifest(MANIFEST)
    enforced = tuple(sorted(v148.v69._PROVIDER_ENV_NAMES))  # noqa: SLF001
    if (
        enforced != ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
        or tuple(purpose.provider_environment_names) != enforced
        or purpose.provider_environment_name_count != len(enforced)
        or purpose.provider_environment_values_read_allowed is not False
        or purpose.child_boundary_verified_before_resource_creation is not True
    ):
        raise ConfigurationError("v158 provider environment-name boundary changed")
    if os.environ.get(CHILD_BOUNDARY_ENV) != "1":
        raise ConfigurationError("v158 requires the verified provider-free child boundary")
    if any(name in os.environ for name in (*enforced, "DOCKER_HOST", "DOCKER_CONTEXT")):
        raise ConfigurationError("v158 provider-free child boundary is contaminated")


@contextlib.contextmanager
def _v158_configuration() -> Iterator[None]:
    replacements: dict[str, Any] = {
        "IDENTITY": IDENTITY,
        "OPT_IN_ENV": OPT_IN_ENV,
        "CHILD_BOUNDARY_ENV": CHILD_BOUNDARY_ENV,
        "MANIFEST": MANIFEST,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "DIND_PARENT": DIND_PARENT,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
        "CONTROL_ROOT": CONTROL_ROOT,
        "RUNTIME_TMP": RUNTIME_TMP,
        "_REQUIRED_MERGED_PATHS": _REQUIRED_MERGED_PATHS,
        "_require_v148_environment_boundary": _require_v158_environment_boundary,
        "_load_composed_manifest": _load_composed_manifest,
        "_write_progress": _write_progress,
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_write_cleanup_diagnostic": _write_cleanup_diagnostic,
        "_validate_static_bindings": _validate_static_bindings,
        "_bounded_scan_and_lock": _bounded_scan_and_lock,
        "_write_import_diagnostic": _write_import_diagnostic,
        "_v148_materialize_task": _v158_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v148, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v148, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v148, name, value)


@contextlib.contextmanager
def _v148_baseline() -> Iterator[None]:
    current = {name: getattr(v148, name) for name in _V148_BASELINE}
    try:
        for name, value in _V148_BASELINE.items():
            setattr(v148, name, value)
        yield
    finally:
        for name, value in current.items():
            setattr(v148, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v158_explicit_endpoint_scaffold_manifest(path)
    with _v148_baseline():
        predecessor = _V148_BASELINE["_load_composed_manifest"](V148_MANIFEST)
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


def _reseal(value: Mapping[str, Any], *, hash_field: str, format_id: str) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    base.pop(hash_field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, hash_field: content_hash(base)}


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v158 progress must remain mutable")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v158_scaffold_progress_v1",
            "identity": IDENTITY,
            "v156_report_hash": "8f5a984f24b15c34eb3e8978ec91aa2c26af8a575058233e2c867777fe700a05",
            "v157_audit_merge": "97cd9e2cd967f18627af209a1939e9fdbee2a346",
            "v157_post_merge_main_run_id": 33959974205,
            "provider_environment_boundary": "exact-sanitized-child-v1",
            "provider_environment_name_count": len(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES),
            "provider_environment_values_read": False,
            "provider_environment_values_printed": False,
            "provider_environment_values_persisted": False,
            "provider_environment_values_hashed": False,
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "runtime_template_transport_policy": (
                "fresh-docker-cli-engine-per-configure-explicit-canonical-unix-socket-v1"
            ),
            "controller_settings_transport_policy": (
                "explicit-canonical-unix-socket-fingerprint-and-launch-v1"
            ),
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    if value.get("status") in v148.v127._SUCCESS_STATUS_NAMES:  # noqa: SLF001
        value["status"] = "completed_pending_independent_v159_audit"
    v148.v132._V127_WRITE_PROGRESS(root, value)  # noqa: SLF001


def _transfer_images(
    dind_name: str,
    manifest: Any,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V148_BASELINE["_transfer_images"](
        dind_name, manifest, host_images=host_images, root=root
    )
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v148.v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v158_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v158 image transfer receipt inventory is not exactly two")
    value.update(
        {
            "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
            "controller_receipt_hash": receipts[0]["receipt_hash"],
            "workspace_runtime_receipt_hash": receipts[1]["receipt_hash"],
            "fresh_data_volume": True,
            "predecessor_volumes_inspected": False,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v158_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _bound_runtime_registry(docker_host: str) -> tuple[Any, DockerRuntime]:
    service = v67._service()  # noqa: SLF001
    runtimes: PluginRegistry[Any] = PluginRegistry("verigym.runtimes")
    template = DockerRuntime(docker_host=docker_host)
    for name, plugin in service.registries.runtimes.items():
        runtimes.register(
            template if name == "docker" else plugin,
            origin=service.registries.runtimes.origin(name),
        )
    service.registries.runtimes = runtimes
    if service.registries.runtimes.get("docker") is not template:
        raise ConfigurationError("v158 failed to replace the service Docker runtime template")
    return service, template


def _runtime_prepare_preflight(
    manifest: Any,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    del dind_name
    docker_host = v148.v127.v118._validated_nested_docker_host(manifest)  # noqa: SLF001
    service, template = _bound_runtime_registry(docker_host)
    completed: list[str] = []
    engines: list[object] = []
    for binding in manifest.schedule:
        configured = service.registries.runtimes.get("docker").configure(
            v148.v94.v92._runtime_config(locks[binding.task_id])  # noqa: SLF001
        )
        if not isinstance(configured, DockerRuntime):
            raise ConfigurationError("v158 service configured a non-Docker runtime")
        try:
            configured.prepare(f"v158-preflight-pr-{binding.pr_number}")
            if configured._engine is None:  # noqa: SLF001
                raise ConfigurationError("v158 configured runtime lacks its owned engine")
            engines.append(configured._engine)  # noqa: SLF001
        finally:
            configured.close()
        completed.append(binding.task_id)
    if len({id(engine) for engine in engines}) != len(manifest.schedule):
        raise ConfigurationError("v158 service runtimes shared a Docker engine")
    inventory_engine = DockerCliEngine(docker_host=docker_host)
    try:
        v148.v127.v118._require_empty_bound_inner_inventory(inventory_engine)  # noqa: SLF001
    finally:
        inventory_engine.close()
    diagnostic = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v158_command_image_probe_diagnostic_v1",
        "identity": IDENTITY,
        "status": "passed",
        "category": "all_command_image_probes_passed",
        "completed_task_ids": completed,
        "current_task_id": None,
        "raw_output_persisted": False,
        "nonempty_output_hashed": False,
        "provider_calls": 0,
    }
    diagnostic["diagnostic_hash"] = content_hash(diagnostic)
    directory = OUTPUT_ROOT / "command-image-probe-diagnostics"
    directory.mkdir(mode=0o700, exist_ok=True)
    atomic_dump_json(directory / "attempt-1.json", diagnostic)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v158_runtime_prepare_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "completed_task_ids": completed,
        "task_count": len(completed),
        "fresh_engine_count": len(engines),
        "distinct_engine_count": len({id(engine) for engine in engines}),
        "actual_service_runtime_path_qualified": True,
        "runtime_template_transport_policy": manifest.runtime_template_transport_policy,
        "nested_docker_host": docker_host,
        "docker_cli_explicit_binding": True,
        "ambient_docker_endpoint_used": False,
        "inner_container_inventory_empty": True,
        "inner_volume_inventory_empty": True,
        "command_image_probe_diagnostic_hash": diagnostic["diagnostic_hash"],
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _harness_initialize_preflight(
    manifest: Any,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    docker_host = v148.v127.v118._validated_nested_docker_host(manifest)  # noqa: SLF001
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
            "controller_docker_host": docker_host,
            "whole_episode_retries": 0,
        },
        task_wall_time_s=300,
    )
    synthetic_key = "v158-offline-" + secrets.token_urlsafe(32)
    synthetic_url = "http://127.0.0.1:9/v1"
    if os.environ.get(API_KEY_ENV) is not None or os.environ.get(BASE_URL_ENV) is not None:
        raise ConfigurationError("v158 refuses a real provider environment during initialize")
    try:
        os.environ[API_KEY_ENV] = synthetic_key
        os.environ[BASE_URL_ENV] = synthetic_url
        result = run_harness_helper(
            settings,
            mode="initialize",
            prompt="",
            system_prompt="VeriGym v158 explicit-endpoint zero-provider initialization.",
            session_id="v158-zero-provider-preflight",
            session_root=session_root,
            broker_root=broker_root,
            docker_host=settings.docker_host,
        )
    finally:
        os.environ.pop(API_KEY_ENV, None)
        os.environ.pop(BASE_URL_ENV, None)
    scan = v148.v94._scan_synthetic_values(  # noqa: SLF001
        root, values=(synthetic_key, synthetic_url)
    )
    if (
        settings.docker_host != docker_host
        or result.events
        or result.provider_request_started
        or result.finish_reason is not None
        or result.final_response
        or result.format_repairs
        or result.run_interval_count != 0
        or (session_root / "provider-request-started-v1.json").exists()
        or scan["match_count"] != 0
    ):
        raise ConfigurationError("v158 Harness initialization crossed its frozen boundary")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v158_harness_initialize_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "harness_configuration_fingerprint": settings.configuration_fingerprint,
        "controller_image_id": settings.controller_image_id,
        "controller_image_provenance": settings.controller_image_provenance,
        "controller_image_source_receipt_hash": controller_receipt_hash,
        "controller_settings_transport_policy": manifest.controller_settings_transport_policy,
        "nested_docker_host": docker_host,
        "settings_endpoint_bound": True,
        "agent_forwarding_equivalent_launch": True,
        "controller_initialized_on_inner_daemon": True,
        "ambient_docker_endpoint_used": False,
        "synthetic_provider_values_only": True,
        "provider_request_started": False,
        "provider_call_count": 0,
        "synthetic_value_scan": scan,
        "raw_exception_persisted": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _inventory(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V148_BASELINE["_inventory"](*args, **kwargs)
    value.update(
        {
            "fresh_data_volume": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    return _reseal(
        value,
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v158_execution_inventory_v1",
    )


def _runtime_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V148_BASELINE["_runtime_receipt"](*args, **kwargs)
    value.update(
        {
            "scanner_policy_id": "deepseek-harness-v158-bounded-command-scan-v1",
            "fresh_data_volume": True,
            "runtime_template_transport_policy": (
                "fresh-docker-cli-engine-per-configure-explicit-canonical-unix-socket-v1"
            ),
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v158_dind_runtime_receipt_v1",
    )


def _cleanup_metric(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
        "timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
    }


def _write_cleanup_diagnostic(
    root: Path,
    *,
    status: str,
    category: str,
    stages: Mapping[str, Any],
) -> dict[str, Any]:
    directory = root / "socket-cleanup-diagnostics"
    directory.mkdir(mode=0o700, exist_ok=True)
    attempt = len(tuple(directory.glob("attempt-*.json"))) + 1
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v158_socket_cleanup_diagnostic_v1",
        "identity": IDENTITY,
        "attempt": attempt,
        "status": status,
        "category": category,
        "socket_cleanup_control_timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        "stages": dict(stages),
        "raw_output_persisted": False,
        "nonempty_output_hashed": False,
        "raw_exception_persisted": False,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "provider_calls": 0,
    }
    result = {**base, "diagnostic_hash": content_hash(base)}
    atomic_dump_json(directory / f"attempt-{attempt}.json", result)
    return result


def _remove_cleanup_helper(name: str, stages: dict[str, Any]) -> None:
    try:
        removed = v148.dind._run(  # noqa: SLF001
            ["docker", "rm", "--force", name],
            timeout_s=_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        stages["helper_remove"] = {
            "status": "timeout",
            "timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        }
        return
    stages["helper_remove"] = _cleanup_metric(removed)


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    if (
        manifest.dind_socket_volume != "verigym-deepseek-harness-v158-dind-socket"
        or manifest.dind_owner != IDENTITY
        or Path(manifest.dind_socket_backing) != DIND_SOCKET_BACKING
    ):
        raise ConfigurationError("v158 socket cleanup identity changed")
    v148.dind._bind_backed_volume(  # noqa: SLF001
        manifest.dind_socket_volume,
        owner=manifest.dind_owner,
        role="socket",
        backing=DIND_SOCKET_BACKING,
    )
    name = f"verigym-dind-v158-socket-cleanup-{secrets.token_hex(10)}"
    script = (
        "rm -rf -- "
        + " ".join(v148.v94._CLEANUP_PATHS)  # noqa: SLF001
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
        f"verigym.owner={IDENTITY}",
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
    stages: dict[str, Any] = {"volume_binding": {"status": "passed"}}
    try:
        completed = v148.dind._run(  # noqa: SLF001
            command, timeout_s=_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        _remove_cleanup_helper(name, stages)
        _write_cleanup_diagnostic(
            root, status="failed", category="cleanup_helper_timeout", stages=stages
        )
        raise ConfigurationError("v158 socket cleanup helper timed out") from exc
    stages["cleanup_helper"] = _cleanup_metric(completed)
    if (
        completed.returncode != 0
        or len(completed.stdout) > v148.v94.MAX_TRANSFER_OUTPUT_BYTES
        or len(completed.stderr) > v148.v94.MAX_TRANSFER_OUTPUT_BYTES
    ):
        _remove_cleanup_helper(name, stages)
        _write_cleanup_diagnostic(
            root, status="failed", category="cleanup_helper_failed", stages=stages
        )
        raise ConfigurationError("v158 socket cleanup helper failed")
    try:
        removed = v148.dind._run(  # noqa: SLF001
            ["docker", "volume", "rm", manifest.dind_socket_volume],
            timeout_s=_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stages["volume_remove"] = {
            "status": "timeout",
            "timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        }
        _write_cleanup_diagnostic(
            root, status="failed", category="socket_volume_remove_timeout", stages=stages
        )
        raise ConfigurationError("v158 socket volume removal timed out") from exc
    stages["volume_remove"] = _cleanup_metric(removed)
    if removed.returncode != 0:
        _write_cleanup_diagnostic(
            root, status="failed", category="socket_volume_remove_failed", stages=stages
        )
        raise ConfigurationError("v158 socket volume removal failed")
    metadata = DIND_SOCKET_BACKING.stat()
    if (
        next(DIND_SOCKET_BACKING.iterdir(), None) is not None
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
    ):
        stages["backing_confirmation"] = {"status": "failed"}
        _write_cleanup_diagnostic(
            root, status="failed", category="socket_backing_not_restored", stages=stages
        )
        raise ConfigurationError("v158 socket backing cleanup was not confirmed")
    stages["backing_confirmation"] = {"status": "passed", "empty": True}
    diagnostic = _write_cleanup_diagnostic(
        root, status="passed", category="socket_cleanup_complete", stages=stages
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v158_socket_cleanup_receipt_v1",
        "identity": IDENTITY,
        "socket_volume_removed": True,
        "socket_backing_empty": True,
        "socket_backing_mode": "0700",
        "socket_backing_owner_restored": True,
        "cleanup_diagnostic_hash": diagnostic["diagnostic_hash"],
        "cleanup_exact_volume": manifest.dind_socket_volume,
        "cleanup_exact_owner": manifest.dind_owner,
        "cleanup_exact_backing": manifest.dind_socket_backing,
        "failed_data_volume_policy": "freeze-exact-owned-volume",
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
    }
    result = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError("v158 predecessor JSON path is unsafe")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ConfigurationError("v158 predecessor JSON must be an object")
    return value


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    purpose = load_v158_explicit_endpoint_scaffold_manifest(MANIFEST)
    with _v148_baseline():
        predecessor = _V148_BASELINE["_load_composed_manifest"](V148_MANIFEST)
        _V148_BASELINE["_validate_static_bindings"](
            predecessor,
            v92_manifest,
            v92_report,
            v92_manifest_path=v92_manifest_path,
            v92_report_path=v92_report_path,
        )
    v156_report = _load_json(V156_REPORT)
    if (
        _hash_file(V148_MANIFEST) != purpose.v148_manifest_sha256
        or _load_json(V148_MANIFEST).get("manifest_hash") != purpose.v148_manifest_hash
        or _hash_file(V148_RUNNER) != purpose.v148_runner_sha256
        or _hash_file(V148_LAUNCHER) != purpose.v148_launcher_sha256
        or _hash_file(V148_AUTHORIZATION) != purpose.v148_authorization_sha256
        or _hash_file(V156_MANIFEST) != purpose.v156_manifest_sha256
        or _load_json(V156_MANIFEST).get("manifest_hash") != purpose.v156_manifest_hash
        or _hash_file(V156_RUNNER) != purpose.v156_runner_sha256
        or _hash_file(V156_LAUNCHER) != purpose.v156_launcher_sha256
        or _hash_file(V156_AUTHORIZATION) != purpose.v156_authorization_sha256
        or _hash_file(V156_REPORT) != purpose.v156_report_sha256
        or v156_report.get("report_hash") != purpose.v156_report_hash
        or v156_report.get("diagnosis") != purpose.v156_diagnosis
        or v156_report.get("provider_calls") != 0
        or _hash_file(V157_AUDIT) != purpose.v157_audit_sha256
        or manifest.schedule != v92_manifest.schedule
        or [item.task_id for item in manifest.schedule] != purpose.schedule_task_ids
        or purpose.dind_data_backing != str(DIND_DATA_BACKING)
        or purpose.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or purpose.output_root != str(OUTPUT_ROOT)
        or purpose.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or purpose.dind_owner != IDENTITY
        or purpose.actual_service_runtime_path_qualified is not True
        or purpose.fresh_data_volume_required is not True
        or purpose.predecessor_volume_inspection_allowed is not False
        or purpose.predecessor_volume_mutation_allowed is not False
        or purpose.provider_credentials_available is not False
        or purpose.requires_independent_v159_audit is not True
        or any(getattr(purpose, name) is not False for name in v148.v94._closed_training_flags())  # noqa: SLF001
    ):
        raise ConfigurationError("v158 predecessor evidence or purpose changed")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", purpose.v157_audit_merge, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v158 requires the merged v157 audit")


def _bounded_scan_and_lock(**kwargs: Any) -> Any:
    if "runtime_policy" in kwargs:
        raise ConfigurationError("v158 refuses an externally supplied scanner policy")
    lock_path = kwargs.get("identity_lock_path")
    if not isinstance(lock_path, Path) or not lock_path.stem.startswith("pr-"):
        raise ConfigurationError("v158 scanner task identity is invalid")
    pr_number = int(lock_path.stem.removeprefix("pr-"))
    if pr_number not in _TASK_PR_NUMBERS:
        raise ConfigurationError("v158 scanner task is outside the frozen schedule")
    policy = CommandImageScanRuntimePolicy(
        policy_id="deepseek-harness-v158-bounded-command-scan-v1",
        create_timeout_seconds=300,
        inspect_timeout_seconds=60,
        start_timeout_seconds=180,
        remove_timeout_seconds=120,
        overall_timeout_seconds=720,
        container_name=f"verigym-hwe-v158-command-scan-pr-{pr_number}",
        owner_label=IDENTITY,
    )
    scan, lock = v148.v132._V69_SCAN_AND_LOCK(**kwargs, runtime_policy=policy)  # noqa: SLF001
    if scan.get("scan_passed") is not True or lock.security_scan_passed is not True:
        raise ConfigurationError("v158 bounded command-image scan did not pass")
    return scan, lock


def _write_import_diagnostic(
    root: Path,
    task: HweOfflineTaskLock,
    *,
    status: str,
    category: str,
    stages: Mapping[str, Any],
) -> None:
    directory = root / "archive-import-diagnostics"
    directory.mkdir(mode=0o700, exist_ok=True)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v158_archive_import_diagnostic_v1",
        "identity": IDENTITY,
        "task_id": task.task_id,
        "status": status,
        "category": category,
        "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
        "explicit_endpoint_binding": True,
        "stages": dict(stages),
        "raw_output_persisted": False,
        "registry_accessed": False,
        "partial_archive_used": False,
        "provider_calls": 0,
    }
    atomic_dump_json(
        directory / f"pr-{task.pr_number}.json",
        {**base, "diagnostic_hash": content_hash(base)},
    )


def _v158_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97" or not args:
        raise ConfigurationError("v158 refuses an unexpected task materialization call")
    task = args[0]
    root = kwargs.get("root")
    if not isinstance(task, HweOfflineTaskLock) or not isinstance(root, Path):
        raise ConfigurationError("v158 task materialization binding is invalid")
    manifest = _load_composed_manifest(MANIFEST)

    def load_completed_archive(bound: HweOfflineTaskLock, *, archive_root: Path) -> None:
        if bound != task:
            raise ConfigurationError("v158 archive import task binding changed")
        v148.v138._explicit_archive_import(  # noqa: SLF001
            bound,
            archive_root=archive_root,
            root=root,
            manifest=manifest,
        )

    previous = v148.v69._load_completed_archive  # noqa: SLF001
    try:
        v148.v69._load_completed_archive = load_completed_archive  # noqa: SLF001
        kwargs["command_tag_version"] = "v158"
        value = v148.v132._V127_BASE_MATERIALIZE_TASK(*args, **kwargs)  # noqa: SLF001
    finally:
        v148.v69._load_completed_archive = previous  # noqa: SLF001
    diagnostic = v148.v140._verifier_control_diagnostic(root, task)  # noqa: SLF001
    diagnostic = _reseal(
        diagnostic,
        hash_field="diagnostic_hash",
        format_id="verigym_deepseek_harness_hwe_v158_verifier_control_diagnostic_v1",
    )
    atomic_dump_json(
        root / "verifier-control-diagnostics" / f"pr-{task.pr_number}.json", diagnostic
    )
    base = copy.deepcopy(value)
    base.pop("task_receipt_hash", None)
    base.update(
        {
            "scanner_policy_id": "deepseek-harness-v158-bounded-command-scan-v1",
            "archive_import_explicit_endpoint": True,
            "verifier_control_diagnostic_hash": diagnostic["diagnostic_hash"],
            "fresh_data_volume": True,
            "predecessor_volumes_inspected": False,
            "requires_independent_v159_audit": True,
        }
    )
    return {**base, "task_receipt_hash": content_hash(base)}


def _materialize_tasks(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    value, locks = v148.v132._V127_MATERIALIZE_TASKS(  # noqa: SLF001
        manifest, v92_manifest, **kwargs
    )
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected = [item.task_id for item in manifest.schedule]
    if not isinstance(receipts, list) or len(receipts) != len(expected):
        raise ConfigurationError("v158 refuses partial task materialization")
    for task_id, receipt in zip(expected, receipts, strict=True):
        if not isinstance(receipt, dict) or receipt.get("task_id") != task_id:
            raise ConfigurationError("v158 task receipt identity changed")
        receipt.pop("task_receipt_hash", None)
        receipt.update(
            {
                "format_id": ("verigym_deepseek_harness_hwe_v158_task_materialization_receipt_v1"),
                "identity": IDENTITY,
                "scanner_policy_id": "deepseek-harness-v158-bounded-command-scan-v1",
                "fresh_data_volume": True,
                "predecessor_volumes_inspected": False,
                "predecessor_volumes_mutated": False,
                "requires_independent_v159_audit": True,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v158_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
            "scanner_policy_id": "deepseek-harness-v158-bounded-command-scan-v1",
            "scanner_all_five_tasks_required": True,
            "archive_import_all_five_explicit": True,
            "verifier_control_diagnostics_all_five_passed": True,
            "fresh_data_volume": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "requires_independent_v159_audit": True,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v158 task output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V148_BASELINE["_scaffold_contract"](manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v158_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v156_report_hash": "8f5a984f24b15c34eb3e8978ec91aa2c26af8a575058233e2c867777fe700a05",
            "v157_audit_merge": "97cd9e2cd967f18627af209a1939e9fdbee2a346",
            "runtime_template_transport_policy": manifest.runtime_template_transport_policy,
            "controller_settings_transport_policy": manifest.controller_settings_transport_policy,
            "actual_service_runtime_path_qualified": True,
            "harness_agent_endpoint_forwarding_required": True,
            "fresh_data_volume": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "requires_independent_v159_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    with _v148_baseline():
        predecessor = _V148_BASELINE["_load_composed_manifest"](V148_MANIFEST)
        head = _V148_BASELINE["_require_clean_merged_main"](predecessor)
    purpose = load_v158_explicit_endpoint_scaffold_manifest(MANIFEST)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", purpose.v157_audit_merge, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    tracked = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *_REQUIRED_MERGED_PATHS],
        cwd=_REPOSITORY,
        check=False,
    )
    missing = [path for path in _REQUIRED_MERGED_PATHS if not (_REPOSITORY / path).is_file()]
    invalid = ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr
    if invalid or tracked.returncode != 0 or missing:
        raise ConfigurationError("v158 requires clean merged main after v157")
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
