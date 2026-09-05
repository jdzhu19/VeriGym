#!/usr/bin/env python3
"""Diagnose the v166 Harness initialization boundary with real configuration and zero requests."""

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
from collections.abc import Iterator, Mapping, Sequence
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
from verigym_deepseek_harness.process import (  # noqa: E402
    DeepSeekHarnessProcessError,
    run_harness_helper,
)

from scripts import (  # noqa: E402
    run_hwe_deepseek_harness_v164_controller_initialize_diagnostic as v164,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_directory  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness import DEEPSEEK_HARNESS_MODEL  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    V164_CONTROLLER_DIAGNOSTIC_CATEGORIES,
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
    load_v168_real_config_initialize_diagnostic_manifest,
)
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v168-real-config-initialize-diagnostic-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V168_REAL_CONFIG_INITIALIZE_DIAGNOSTIC"
CHILD_BOUNDARY_ENV = "VERIGYM_DEEPSEEK_HARNESS_V168_REAL_CONFIG_ZERO_REQUEST_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v168_real_config_initialize_diagnostic_v1.json"
)
V164_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v164_controller_initialize_diagnostic_v1.json"
)
V164_RUNNER = _REPOSITORY / (
    "scripts/run_hwe_deepseek_harness_v164_controller_initialize_diagnostic.py"
)
V164_LAUNCHER = _REPOSITORY / (
    "scripts/launch_hwe_deepseek_harness_v164_controller_initialize_diagnostic.py"
)
V164_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v164-controller-initialize-diagnostic-authorization.md"
)
V165_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v165-v164-result.md"
V166_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v166_official_matrix_v1.json"
)
V166_RUNNER = _REPOSITORY / "scripts/collect_hwe_deepseek_harness_v166_official_matrix.py"
V166_LAUNCHER = _REPOSITORY / "scripts/launch_hwe_deepseek_harness_v166_official_matrix.py"
V166_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v166-official-matrix-authorization.md"
)
V167_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v167-v166-result.md"
V164_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v164-controller-initialize-diagnostic-v1"
)
V166_ROOT = Path("/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v166-official-matrix-v1")
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v168-real-config-initialize-diagnostic-v1"
)
DIND_DATA_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v158/data")
DIND_SOCKET_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v168/socket")
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v168-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v168-runtime")
REPORT_FORMAT = "verigym_deepseek_harness_hwe_v168_real_config_diagnostic_result_v1"
PROGRESS_FORMAT = "verigym_deepseek_harness_hwe_v168_real_config_diagnostic_progress_v1"
_DOCKER_ENDPOINT_ENV_NAMES = ("DOCKER_CONTEXT", "DOCKER_HOST")
_REQUIRED_PROVIDER_ENV_NAMES = (API_KEY_ENV, BASE_URL_ENV)
_MAX_JSON_BYTES = 64 * 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v168_real_config_initialize_diagnostic_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v167-v166-result.md",
    "docs/audits/2026-09-05_deepseek-harness-v168-real-config-diagnostic-authorization.md",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/helper.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/process.py",
    "integrations/verigym-deepseek-harness/tests/test_v168_real_config_initialize_diagnostic.py",
    "scripts/launch_hwe_deepseek_harness_v168_real_config_initialize_diagnostic.py",
    "scripts/run_hwe_deepseek_harness_v168_real_config_initialize_diagnostic.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
)
_PATCH_NAMES = (
    "IDENTITY",
    "OUTPUT_ROOT",
    "CONTROL_ROOT",
    "RUNTIME_TMP",
    "DIND_DATA_BACKING",
    "DIND_SOCKET_BACKING",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def diagnose(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the sole authorized real-config initialize diagnostic."""

    provider_values = _require_execution_boundary(arguments)
    manifest = load_v168_real_config_initialize_diagnostic_manifest(
        _exact_file(arguments.manifest, MANIFEST, "manifest")
    )
    source_commit = _require_clean_merged_main(manifest)
    predecessor = _validate_predecessor(manifest)
    root = _new_output(arguments.output)
    atomic_dump_json(root / "predecessor-receipt.json", predecessor)
    progress = _base_progress(
        manifest,
        source_commit=source_commit,
        post_merge_main_run_id=arguments.post_merge_main_run_id,
        predecessor_hash=str(predecessor["receipt_hash"]),
    )
    _write_progress(root, progress)
    dind_name: str | None = None
    inner_network_created = False
    cleanup_confirmed = False
    cleanup_hash: str | None = None
    diagnostic: dict[str, Any] | None = None
    reopen_count = 3
    try:
        with _v168_bindings():
            headroom = _reformat_receipt(
                v164.v162._host_headroom_receipt(manifest),  # noqa: SLF001
                "verigym_deepseek_harness_hwe_v168_host_root_headroom_v1",
            )
            atomic_dump_json(root / "host-root-headroom-before-docker.json", headroom)
            progress.update(
                {"status": "host_runtime_preflight", "host_headroom_hash": headroom["receipt_hash"]}
            )
            _write_progress(root, progress)
            if headroom["status"] != "passed":
                raise ConfigurationError("v168 host root has insufficient absolute headroom")
            _validate_host_runtime(manifest)
            v164.v162._prepare_socket_backing(manifest)  # noqa: SLF001
            v164.dind._create_bind_backed_volume(  # noqa: SLF001
                manifest.dind_socket_volume,
                owner=manifest.runtime_resource_owner,
                role="socket",
                backing=DIND_SOCKET_BACKING,
            )
            dind_name = f"verigym-dind-v168-{secrets.token_hex(10)}"
            metadata = v164.v162._start_provider_dind(  # noqa: SLF001
                name=dind_name,
                manifest=manifest,
                root=root,
            )
            reopen_count = 4
            runtime_receipt = _reformat_receipt(
                v164.v162._provider_runtime_receipt(  # noqa: SLF001
                    manifest,
                    dind_name=dind_name,
                    metadata=metadata,
                ),
                "verigym_deepseek_harness_hwe_v168_dind_runtime_receipt_v1",
            )
            atomic_dump_json(root / "dind-runtime-receipt.json", runtime_receipt)
            v164._validate_inner_controller_inventory(dind_name, manifest)  # noqa: SLF001
            v164.v162._create_inner_provider_network(dind_name, manifest)  # noqa: SLF001
            inner_network_created = True
            network_receipt = _reformat_receipt(
                v164.v162._network_receipt(dind_name, manifest),  # noqa: SLF001
                "verigym_deepseek_harness_hwe_v168_network_receipt_v1",
            )
            atomic_dump_json(root / "network-receipt.json", network_receipt)
            progress.update(
                {
                    "status": "controller_diagnostic",
                    "v158_data_volume_reopen_count": reopen_count,
                    "dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
                    "network_receipt_hash": network_receipt["receipt_hash"],
                }
            )
            _write_progress(root, progress)

            direct = _direct_container_probe(manifest, root=root)
            atomic_dump_json(root / "direct-container-probe.json", direct)
            if direct["status"] == "passed":
                diagnostic = _harness_initialize_probe(
                    manifest,
                    root=root,
                    provider_values=provider_values,
                )
            else:
                diagnostic = _seal(
                    {
                        "schema_version": "1.0",
                        "format_id": (
                            "verigym_deepseek_harness_hwe_v168_harness_initialize_diagnostic_v1"
                        ),
                        "identity": IDENTITY,
                        "status": "observed",
                        "diagnostic_category": "direct_container_probe_failed",
                        "harness_initialize_started": False,
                        "provider_request_started": False,
                        "provider_calls": 0,
                        "real_provider_configuration_used": False,
                        "raw_exception_persisted": False,
                        "raw_stderr_persisted": False,
                    },
                    "diagnostic_hash",
                )
            atomic_dump_json(root / "harness-initialize-diagnostic.json", diagnostic)
            _require_provider_values_absent(root, provider_values)

            v164.v162._clean_inner_resources(dind_name)  # noqa: SLF001
            v164.v162._remove_inner_provider_network(dind_name, manifest)  # noqa: SLF001
            inner_network_created = False
            v164.dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
            if not v164.dind._remove_container(dind_name):  # noqa: SLF001
                raise ConfigurationError("v168 provider DinD sidecar cleanup failed")
            dind_name = None
            cleanup = _v168_socket_cleanup(manifest, root=root)
            cleanup_confirmed = True
            cleanup_hash = str(cleanup["receipt_hash"])
    except Exception as exc:
        with _v168_bindings():
            cleanup_confirmed, cleanup_hash = _best_effort_cleanup(
                dind_name=dind_name,
                inner_network_created=inner_network_created,
                manifest=manifest,
                root=root,
            )
        progress.update(
            {
                "status": "stopped",
                "stop_reason": "diagnostic_infrastructure_failure",
                "exception_type": type(exc).__name__,
                "raw_exception_persisted": False,
                "dind_cleanup_confirmed": cleanup_confirmed,
                "dind_cleanup_receipt_hash": cleanup_hash,
                "v158_data_volume_reopen_count": reopen_count,
                "provider_request_started": False,
                "provider_calls": 0,
            }
        )
        report = _final_report(progress, diagnostic=diagnostic)
        atomic_dump_json(root / "diagnostic-progress.json", report)
        atomic_dump_json(root / "diagnostic-report.json", report)
        _require_provider_values_absent(root, provider_values)
        return report

    assert diagnostic is not None
    if not cleanup_confirmed:
        raise ConfigurationError("v168 cleanup must finish before result publication")
    progress.update(
        {
            "status": "diagnosed",
            "stop_reason": None,
            "diagnostic_hash": diagnostic["diagnostic_hash"],
            "diagnostic_category": diagnostic["diagnostic_category"],
            "dind_cleanup_confirmed": True,
            "dind_cleanup_receipt_hash": cleanup_hash,
            "provider_request_started": False,
            "provider_calls": 0,
        }
    )
    report = _final_report(progress, diagnostic=diagnostic)
    atomic_dump_json(root / "diagnostic-progress.json", report)
    atomic_dump_json(root / "diagnostic-report.json", report)
    _require_provider_values_absent(root, provider_values)
    return report


def _require_execution_boundary(arguments: argparse.Namespace) -> tuple[str, str]:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(CHILD_BOUNDARY_ENV) != "1":
        raise ConfigurationError("v168 requires its one-use real-config zero-request boundary")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v168 requires a non-root host identity")
    present = {name for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES if name in os.environ}
    if present != set(_REQUIRED_PROVIDER_ENV_NAMES) or any(
        name in os.environ for name in _DOCKER_ENDPOINT_ENV_NAMES
    ):
        raise ConfigurationError("v168 child environment identity is contaminated")
    values = tuple(os.environ[name] for name in _REQUIRED_PROVIDER_ENV_NAMES)
    if any(not value for value in values) or len(set(values)) != 2:
        raise ConfigurationError("v168 requires two distinct nonempty provider values")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v168 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v168 requires a positive post-merge main run ID")
    return values


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v168 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    upstream = _git("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v167_audit_merge, head],
        cwd=_REPOSITORY,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    if (
        branch != "main"
        or head != upstream
        or len(head) != 40
        or ancestor.returncode != 0
        or ancestor.stdout
        or ancestor.stderr
    ):
        raise ConfigurationError("v168 requires clean merged origin/main after v167")
    return head


def _validate_predecessor(
    manifest: DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
) -> dict[str, Any]:
    v164._validate_predecessor(manifest)  # noqa: SLF001
    static_paths = {
        V164_MANIFEST: (manifest.v164_manifest_sha256, manifest.v164_implementation_commit),
        V164_RUNNER: (manifest.v164_runner_sha256, manifest.v164_implementation_commit),
        V164_LAUNCHER: (manifest.v164_launcher_sha256, manifest.v164_implementation_commit),
        V164_AUTHORIZATION: (
            manifest.v164_authorization_sha256,
            manifest.v164_implementation_commit,
        ),
        V165_AUDIT: (manifest.v165_audit_sha256, manifest.v165_audit_commit),
        V166_MANIFEST: (manifest.v166_manifest_sha256, manifest.v166_implementation_commit),
        V166_RUNNER: (manifest.v166_runner_sha256, manifest.v166_implementation_commit),
        V166_LAUNCHER: (manifest.v166_launcher_sha256, manifest.v166_implementation_commit),
        V166_AUTHORIZATION: (
            manifest.v166_authorization_sha256,
            manifest.v166_implementation_commit,
        ),
        V167_AUDIT: (manifest.v167_audit_sha256, manifest.v167_audit_commit),
    }
    if any(
        _hash_file(path) != expected or _hash_git_file(commit, path) != expected
        for path, (expected, commit) in static_paths.items()
    ):
        raise ConfigurationError("v168 frozen implementation or audit binding changed")

    _validate_tree(
        V164_ROOT,
        expected_hash=manifest.v164_evidence_tree_hash,
        expected_directories=manifest.v164_evidence_directory_count,
        expected_files=manifest.v164_evidence_regular_file_count,
        expected_symlinks=manifest.v164_evidence_symlink_count,
        expected_directory_modes={0o700: 1},
        expected_file_modes={0o600: 9},
        label="v164 evidence",
    )
    _validate_tree(
        V166_ROOT,
        expected_hash=manifest.v166_evidence_tree_hash,
        expected_directories=manifest.v166_evidence_directory_count,
        expected_files=manifest.v166_evidence_regular_file_count,
        expected_symlinks=manifest.v166_evidence_symlink_count,
        expected_directory_modes={0o700: 9},
        expected_file_modes={0o600: 7},
        label="v166 evidence",
    )
    v164_report_path = V164_ROOT / "diagnostic-report.json"
    v164_initialize_path = V164_ROOT / "harness-initialize-diagnostic.json"
    v166_report_path = V166_ROOT / "matrix-report.json"
    v166_attempt_path = V166_ROOT / "attempts/pr-465.json"
    v166_cleanup_path = V166_ROOT / "dind-cleanup-receipt.json"
    v164_report = _load_json(v164_report_path)
    v164_initialize = _load_json(v164_initialize_path)
    v166_report = _load_json(v166_report_path)
    v166_attempt = _load_json(v166_attempt_path)
    v166_cleanup = _load_json(v166_cleanup_path)
    if (
        _hash_file(v164_report_path) != manifest.v164_report_sha256
        or _canonical_hash(v164_report, "report_hash") != manifest.v164_report_hash
        or _hash_file(v164_initialize_path) != manifest.v164_harness_initialize_sha256
        or _canonical_hash(v164_initialize, "diagnostic_hash")
        != manifest.v164_harness_initialize_hash
        or v164_report.get("diagnostic_category") != "passed"
        or v164_report.get("provider_calls") != 0
        or v164_report.get("dind_cleanup_confirmed") is not True
        or _hash_file(v166_report_path) != manifest.v166_report_sha256
        or _canonical_hash(v166_report, "report_hash") != manifest.v166_report_hash
        or _hash_file(v166_attempt_path) != manifest.v166_attempt_sha256
        or _canonical_hash(v166_attempt, "attempt_hash") != manifest.v166_attempt_hash
        or _hash_file(v166_cleanup_path) != manifest.v166_cleanup_sha256
        or _canonical_hash(v166_cleanup, "receipt_hash") != manifest.v166_cleanup_hash
        or v166_report.get("status") != "stopped_pending_independent_v167_audit"
        or v166_report.get("stop_reason") != "pre_provider_infrastructure_failure"
        or v166_report.get("provider_episode_count") != 0
        or v166_report.get("provider_call_count") != 0
        or v166_report.get("provider_total_tokens") != 0
        or v166_report.get("v158_data_volume_reopen_count") != 3
        or v166_report.get("dind_cleanup_confirmed") is not True
        or v166_attempt.get("provider_marker") != "not_started"
        or v166_attempt.get("provider_call_count") != 0
        or v166_attempt.get("outcome") != "infrastructure_failure"
        or v166_cleanup.get("cleanup_confirmed") is not True
        or any(
            report.get(name) is not False
            for report in (v164_report, v166_report)
            for name in (
                "formal_collection_allowed",
                "formal_collection_started",
                "collection_started",
                "training_started",
                "production_training_ready",
            )
        )
    ):
        raise ConfigurationError("v168 predecessor result boundary changed")
    return _seal(
        {
            "schema_version": "1.0",
            "format_id": "verigym_deepseek_harness_hwe_v168_predecessor_receipt_v1",
            "identity": IDENTITY,
            "v164_report_hash": manifest.v164_report_hash,
            "v164_initialize_hash": manifest.v164_harness_initialize_hash,
            "v164_evidence_tree_hash": manifest.v164_evidence_tree_hash,
            "v165_audit_sha256": manifest.v165_audit_sha256,
            "v166_report_hash": manifest.v166_report_hash,
            "v166_attempt_hash": manifest.v166_attempt_hash,
            "v166_cleanup_hash": manifest.v166_cleanup_hash,
            "v166_evidence_tree_hash": manifest.v166_evidence_tree_hash,
            "v167_audit_sha256": manifest.v167_audit_sha256,
            "v166_provider_consumed": False,
            "v158_data_volume_reopen_count_before": 3,
            "provider_calls": 0,
            "provider_values_persisted_or_hashed": False,
        },
        "receipt_hash",
    )


def _validate_host_runtime(
    manifest: DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
) -> None:
    if (
        Path(manifest.dind_data_backing) != DIND_DATA_BACKING
        or Path(manifest.dind_socket_backing) != DIND_SOCKET_BACKING
        or Path(manifest.control_headroom_root) != CONTROL_ROOT
        or Path(manifest.runtime_scratch_root) != RUNTIME_TMP
        or Path(manifest.output_root) != OUTPUT_ROOT
        or manifest.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or manifest.runtime_resource_owner != IDENTITY
        or manifest.v158_data_volume_reopen_count_before != 3
        or manifest.v158_data_volume_reopen_budget != 4
    ):
        raise ConfigurationError("v168 runtime path, ownership, or reopen binding changed")
    legacy = manifest.model_dump(mode="python")
    legacy["v158_data_volume_reopen_count_before"] = 1
    legacy["v158_data_volume_reopen_budget"] = 2
    v164._validate_host_runtime(SimpleNamespace(**legacy))  # noqa: SLF001


def _direct_container_probe(
    manifest: DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    value = v164._direct_container_probe(manifest, root=root)  # noqa: SLF001
    base = dict(value)
    base.pop("probe_hash", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v168_direct_container_probe_v1",
            "identity": IDENTITY,
            "real_provider_configuration_forwarded": False,
        }
    )
    return _seal(base, "probe_hash")


def _harness_initialize_probe(
    manifest: DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
    *,
    root: Path,
    provider_values: tuple[str, str],
) -> dict[str, Any]:
    session_root = root / "harness-session"
    broker_root = root / "harness-broker"
    session_root.mkdir(mode=0o700)
    broker_root.mkdir(mode=0o700)
    settings = resolve_settings(
        {
            "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
            "model_id": DEEPSEEK_HARNESS_MODEL,
            "max_process_time_s": manifest.harness_initialize_timeout_seconds,
            "max_output_bytes": 32 * 1024 * 1024,
            "controller_image_id": manifest.controller_image_id,
            "controller_image_offline_load": True,
            "controller_image_source_receipt_hash": manifest.controller_image_source_receipt_hash,
            "controller_docker_host": manifest.nested_docker_host,
            "whole_episode_retries": 0,
        },
        task_wall_time_s=manifest.harness_initialize_timeout_seconds,
    )
    category = "passed"
    helper_status = "passed"
    result = None
    try:
        result = run_harness_helper(
            settings,
            mode="initialize",
            prompt="",
            system_prompt="VeriGym v166 credential-bearing controller initialization preflight.",
            session_id="v166-zero-provider-preflight",
            session_root=session_root,
            broker_root=broker_root,
            docker_host=settings.docker_host,
        )
    except DeepSeekHarnessProcessError as exc:
        helper_status = "failed"
        category = exc.category
    except Exception:
        helper_status = "failed"
        category = "helper_unclassified_error"
    marker = session_root / "provider-request-started-v1.json"
    provider_started = marker.exists() or (result is not None and result.provider_request_started)
    if provider_started:
        _purge_probe_roots(root, provider_values, required=True)
        raise ConfigurationError("v168 initialize crossed the provider boundary")
    if result is not None and (
        result.events
        or result.finish_reason is not None
        or result.final_response
        or result.format_repairs
        or result.run_interval_count != 0
    ):
        helper_status = "failed"
        category = "helper_result_identity_changed"
    if category not in V164_CONTROLLER_DIAGNOSTIC_CATEGORIES:
        category = "helper_unclassified_error"
    purge = _purge_probe_roots(root, provider_values, required=True)
    return _seal(
        {
            "schema_version": "1.0",
            "format_id": "verigym_deepseek_harness_hwe_v168_harness_initialize_diagnostic_v1",
            "identity": IDENTITY,
            "status": "observed",
            "helper_status": helper_status,
            "diagnostic_category": category,
            "configuration_fingerprint": settings.configuration_fingerprint,
            "controller_image_id": settings.controller_image_id,
            "controller_image_provenance": settings.controller_image_provenance,
            "controller_image_source_receipt_hash": settings.controller_image_source_receipt_hash,
            "nested_docker_host": settings.docker_host,
            "settings_endpoint_bound": settings.docker_host == manifest.nested_docker_host,
            "v166_initialize_payload_reproduced": True,
            "harness_initialize_started": True,
            "provider_request_started": False,
            "provider_calls": 0,
            "real_provider_configuration_used": True,
            "real_provider_environment_value_count": 2,
            "provider_value_hits": 0,
            "private_artifact_file_count_removed": purge["file_count_removed"],
            "private_artifact_byte_count_removed": purge["byte_count_removed"],
            "raw_exception_persisted": False,
            "raw_stderr_persisted": False,
            "provider_values_printed": False,
            "provider_values_persisted_or_hashed": False,
        },
        "diagnostic_hash",
    )


def _purge_probe_roots(
    root: Path,
    values: Sequence[str],
    *,
    required: bool,
) -> dict[str, int]:
    file_count = 0
    byte_count = 0
    hit_count = 0
    for name in ("harness-session", "harness-broker"):
        target = root / name
        if not target.exists():
            if required:
                raise ConfigurationError("v168 private diagnostic root disappeared")
            continue
        if target.is_symlink() or not target.is_dir():
            raise ConfigurationError("v168 private diagnostic root is unsafe")
        paths = sorted(
            target.rglob("*"),
            key=lambda path: (len(path.relative_to(target).parts), path.as_posix()),
            reverse=True,
        )
        for path in paths:
            if path.is_symlink():
                raise ConfigurationError("v168 private diagnostic tree contains a symlink")
            if path.is_file():
                payload = path.read_bytes()
                file_count += 1
                byte_count += len(payload)
                hit_count += sum(value.encode() in payload for value in values)
                path.unlink()
            elif path.is_dir():
                path.rmdir()
            else:
                raise ConfigurationError("v168 private diagnostic tree contains a special file")
        target.rmdir()
    if hit_count:
        raise ConfigurationError("v168 provider value reached private artifacts")
    return {"file_count_removed": file_count, "byte_count_removed": byte_count}


def _require_provider_values_absent(root: Path, values: Sequence[str]) -> None:
    hits = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("v168 output contains a symlink")
        if path.is_file():
            payload = path.read_bytes()
            hits += sum(value.encode() in payload for value in values)
    if hits:
        raise ConfigurationError("v168 provider value reached published evidence")


@contextlib.contextmanager
def _v168_bindings() -> Iterator[None]:
    replacements = {
        "IDENTITY": IDENTITY,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "CONTROL_ROOT": CONTROL_ROOT,
        "RUNTIME_TMP": RUNTIME_TMP,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
    }
    previous = {name: getattr(v164, name) for name in _PATCH_NAMES}
    try:
        for name, value in replacements.items():
            setattr(v164, name, value)
        with v164._v164_bindings():  # noqa: SLF001
            yield
    finally:
        for name, value in previous.items():
            setattr(v164, name, value)


def _v168_socket_cleanup(
    manifest: DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    value = v164.v162._clean_socket_volume(manifest, root=root)  # noqa: SLF001
    receipt = _reformat_receipt(
        value,
        "verigym_deepseek_harness_hwe_v168_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", receipt)
    return receipt


def _best_effort_cleanup(
    *,
    dind_name: str | None,
    inner_network_created: bool,
    manifest: DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
    root: Path,
) -> tuple[bool, str | None]:
    confirmed, _old_hash = v164.v162._best_effort_cleanup(  # noqa: SLF001
        dind_name=dind_name,
        inner_network_created=inner_network_created,
        manifest=manifest,
        root=root,
    )
    path = root / "dind-cleanup-receipt.json"
    if confirmed and path.is_file():
        receipt = _reformat_receipt(
            _load_json(path),
            "verigym_deepseek_harness_hwe_v168_socket_cleanup_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        return True, str(receipt["receipt_hash"])
    return confirmed, None


def _base_progress(
    manifest: DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
    predecessor_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": PROGRESS_FORMAT,
        "identity": IDENTITY,
        "status": "initialized",
        "stop_reason": None,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "predecessor_receipt_hash": predecessor_hash,
        "v158_data_volume_reopen_count": 3,
        "diagnostic_category": None,
        "provider_request_started": False,
        "provider_calls": 0,
        "provider_tokens": 0,
        "task_execution_started": False,
        "base_reference_verification_started": False,
        "official_verifier_started": False,
        "real_provider_configuration_used_for_initialize_only": True,
        "provider_values_printed": False,
        "provider_values_persisted_or_hashed": False,
        "raw_exception_persisted": False,
        "raw_stderr_persisted": False,
        "replacement_provider_matrix_authorized": False,
        **_closed_flags(),
    }


def _final_report(
    progress: Mapping[str, Any],
    *,
    diagnostic: Mapping[str, Any] | None,
) -> dict[str, Any]:
    diagnosed = progress.get("status") == "diagnosed"
    category = diagnostic.get("diagnostic_category") if diagnostic else None
    if category == "passed":
        diagnosis = "v166_initialize_failure_not_reproduced_with_real_configuration"
    elif category == "direct_container_probe_failed":
        diagnosis = "controller_container_prerequisite_probe_failed"
    elif isinstance(category, str):
        diagnosis = f"v166_initialize_failure_reproduced_as_{category}"
    else:
        diagnosis = "diagnostic_infrastructure_failure"
    return _seal(
        {
            **dict(copy.deepcopy(progress)),
            "format_id": REPORT_FORMAT,
            "status": (
                "diagnosed_pending_independent_v169_audit"
                if diagnosed
                else "stopped_pending_independent_v169_audit"
            ),
            "diagnosis": diagnosis,
            "diagnosis_confirmed": diagnosed,
            "requires_independent_v169_audit": True,
            "replacement_provider_matrix_authorized": False,
            "benchmark_score_claimed": False,
            "provider_request_started": False,
            "provider_calls": 0,
            "provider_tokens": 0,
            "provider_values_printed": False,
            "provider_values_persisted_or_hashed": False,
            **_closed_flags(),
        },
        "report_hash",
    )


def _validate_tree(
    root: Path,
    *,
    expected_hash: str,
    expected_directories: int,
    expected_files: int,
    expected_symlinks: int,
    expected_directory_modes: Mapping[int, int],
    expected_file_modes: Mapping[int, int],
    label: str,
) -> None:
    directories = 0
    regular_files = 0
    symlinks = 0
    directory_modes: dict[int, int] = {}
    file_modes: dict[int, int] = {}
    for path in (root, *root.rglob("*")):
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            symlinks += 1
        elif path.is_dir():
            directories += 1
            directory_modes[mode] = directory_modes.get(mode, 0) + 1
        elif stat.S_ISREG(metadata.st_mode):
            regular_files += 1
            file_modes[mode] = file_modes.get(mode, 0) + 1
        else:
            raise ConfigurationError(f"v168 {label} contains an unsafe file type")
    if (
        directories != expected_directories
        or regular_files != expected_files
        or symlinks != expected_symlinks
        or directory_modes != dict(expected_directory_modes)
        or file_modes != dict(expected_file_modes)
        or hash_directory(root) != expected_hash
    ):
        raise ConfigurationError(f"v168 {label} tree changed")


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    atomic_dump_json(root / "diagnostic-progress.json", dict(value))


def _new_output(path: Path) -> Path:
    if path != OUTPUT_ROOT or path.exists() or path.is_symlink():
        raise ConfigurationError("v168 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"v168 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_file():
        raise ConfigurationError(f"v168 {label} identity changed")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v168 JSON input is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v168 JSON input is malformed") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v168 JSON input is not an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v168 predecessor canonical hash changed")
    return observed


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_git_file(commit: str, path: Path) -> str:
    relative = path.relative_to(_REPOSITORY)
    value = subprocess.run(
        ["git", "show", f"{commit}:{relative.as_posix()}"],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(value).hexdigest()


def _reformat_receipt(value: Mapping[str, Any], format_id: str) -> dict[str, Any]:
    base = dict(value)
    base.pop("receipt_hash", None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return _seal(base, "receipt_hash")


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    base = dict(copy.deepcopy(value))
    base.pop(field, None)
    return {**base, field: content_hash(base)}


def _closed_flags() -> dict[str, bool]:
    return {
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    report = diagnose(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnosis": report["diagnosis"],
                "diagnostic_category": report.get("diagnostic_category"),
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "diagnosed_pending_independent_v169_audit" else 1


if __name__ == "__main__":
    raise SystemExit(main())
