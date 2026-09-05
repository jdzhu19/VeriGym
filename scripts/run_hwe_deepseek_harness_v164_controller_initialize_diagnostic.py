#!/usr/bin/env python3
"""Diagnose the v162 Harness initialization boundary without provider access."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import secrets
import subprocess
import sys
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
    DEEPSEEK_HARNESS_SOURCE_ROOT,
    resolve_settings,
)
from verigym_deepseek_harness.process import (  # noqa: E402
    DeepSeekHarnessProcessError,
    run_harness_helper,
)

from scripts import collect_hwe_deepseek_harness_v162_official_matrix as v162  # noqa: E402
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_directory  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness import DEEPSEEK_HARNESS_MODEL  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    V164_CONTROLLER_DIAGNOSTIC_CATEGORIES,
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
    load_v162_official_matrix_manifest,
    load_v164_controller_initialize_diagnostic_manifest,
)
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID  # noqa: E402
from verigym.runtimes.docker.engine import DockerCliEngine  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v164-controller-initialize-diagnostic-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V164_CONTROLLER_INITIALIZE_DIAGNOSTIC"
CHILD_BOUNDARY_ENV = "VERIGYM_DEEPSEEK_HARNESS_V164_ZERO_PROVIDER_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v164_controller_initialize_diagnostic_v1.json"
)
V162_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v162_official_matrix_v1.json"
)
V162_RUNNER = _REPOSITORY / "scripts/collect_hwe_deepseek_harness_v162_official_matrix.py"
V162_LAUNCHER = _REPOSITORY / "scripts/launch_hwe_deepseek_harness_v162_official_matrix.py"
V162_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v162-official-matrix-authorization.md"
)
V163_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v163-v162-result.md"
PROCESS_MODULE = _REPOSITORY / (
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/process.py"
)
HELPER_MODULE = _REPOSITORY / (
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/helper.py"
)
V162_ROOT = Path("/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v162-official-matrix-v1")
V162_REPORT = V162_ROOT / "matrix-report.json"
V162_ATTEMPT = V162_ROOT / "attempts/pr-465.json"
V162_CLEANUP = V162_ROOT / "dind-cleanup-receipt.json"
V158_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v158-explicit-endpoint-scaffold-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v164-controller-initialize-diagnostic-v1"
)
DIND_DATA_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v158/data")
DIND_SOCKET_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v164/socket")
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v164-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v164-runtime")
REPORT_FORMAT = "verigym_deepseek_harness_hwe_v164_controller_diagnostic_result_v1"
PROGRESS_FORMAT = "verigym_deepseek_harness_hwe_v164_controller_diagnostic_progress_v1"
_DOCKER_ENDPOINT_ENV_NAMES = ("DOCKER_CONTEXT", "DOCKER_HOST")
_MAX_JSON_BYTES = 64 * 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v162_official_matrix_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v164_controller_initialize_diagnostic_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v162-official-matrix-authorization.md",
    "docs/audits/2026-09-05_deepseek-harness-v163-v162-result.md",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/helper.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/process.py",
    "integrations/verigym-deepseek-harness/tests/test_process.py",
    "integrations/verigym-deepseek-harness/tests/test_v164_controller_initialize_diagnostic.py",
    "scripts/collect_hwe_deepseek_harness_v162_official_matrix.py",
    "scripts/launch_hwe_deepseek_harness_v162_official_matrix.py",
    "scripts/launch_hwe_deepseek_harness_v164_controller_initialize_diagnostic.py",
    "scripts/run_hwe_deepseek_harness_v164_controller_initialize_diagnostic.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
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
    """Run exactly one synthetic initialize diagnostic and publish a sanitized receipt."""

    _require_execution_boundary(arguments)
    manifest = load_v164_controller_initialize_diagnostic_manifest(
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
    reopen_count = 1
    try:
        with _v164_bindings():
            headroom = _reformat_receipt(
                v162._host_headroom_receipt(manifest),  # noqa: SLF001
                "verigym_deepseek_harness_hwe_v164_host_root_headroom_v1",
            )
            atomic_dump_json(root / "host-root-headroom-before-docker.json", headroom)
            progress.update(
                {"status": "host_runtime_preflight", "host_headroom_hash": headroom["receipt_hash"]}
            )
            _write_progress(root, progress)
            if headroom["status"] != "passed":
                raise ConfigurationError("v164 host root has insufficient absolute headroom")
            _validate_host_runtime(manifest)
            v162._prepare_socket_backing(manifest)  # noqa: SLF001
            dind._create_bind_backed_volume(  # noqa: SLF001
                manifest.dind_socket_volume,
                owner=manifest.runtime_resource_owner,
                role="socket",
                backing=DIND_SOCKET_BACKING,
            )
            dind_name = f"verigym-dind-v164-{secrets.token_hex(10)}"
            metadata = v162._start_provider_dind(  # noqa: SLF001
                name=dind_name,
                manifest=manifest,
                root=root,
            )
            reopen_count = 2
            runtime_receipt = _reformat_receipt(
                v162._provider_runtime_receipt(  # noqa: SLF001
                    manifest,
                    dind_name=dind_name,
                    metadata=metadata,
                ),
                "verigym_deepseek_harness_hwe_v164_dind_runtime_receipt_v1",
            )
            atomic_dump_json(root / "dind-runtime-receipt.json", runtime_receipt)
            _validate_inner_controller_inventory(dind_name, manifest)
            v162._create_inner_provider_network(dind_name, manifest)  # noqa: SLF001
            inner_network_created = True
            network_receipt = _reformat_receipt(
                v162._network_receipt(dind_name, manifest),  # noqa: SLF001
                "verigym_deepseek_harness_hwe_v164_network_receipt_v1",
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
                diagnostic = _harness_initialize_probe(manifest, root=root)
            else:
                diagnostic = _seal(
                    {
                        "schema_version": "1.0",
                        "format_id": (
                            "verigym_deepseek_harness_hwe_v164_harness_initialize_diagnostic_v1"
                        ),
                        "identity": IDENTITY,
                        "status": "observed",
                        "diagnostic_category": "direct_container_probe_failed",
                        "harness_initialize_started": False,
                        "provider_request_started": False,
                        "provider_calls": 0,
                        "synthetic_provider_values_only": True,
                        "raw_exception_persisted": False,
                        "raw_stderr_persisted": False,
                    },
                    "diagnostic_hash",
                )
            atomic_dump_json(root / "harness-initialize-diagnostic.json", diagnostic)

            v162._clean_inner_resources(dind_name)  # noqa: SLF001
            v162._remove_inner_provider_network(dind_name, manifest)  # noqa: SLF001
            inner_network_created = False
            dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
            if not dind._remove_container(dind_name):  # noqa: SLF001
                raise ConfigurationError("v164 provider DinD sidecar cleanup failed")
            dind_name = None
            cleanup = _v164_socket_cleanup(manifest, root=root)
            cleanup_confirmed = True
            cleanup_hash = str(cleanup["receipt_hash"])
    except Exception as exc:
        with _v164_bindings():
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
        return report

    assert diagnostic is not None
    if not cleanup_confirmed:
        raise ConfigurationError("v164 cleanup must finish before result publication")
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
    return report


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(CHILD_BOUNDARY_ENV) != "1":
        raise ConfigurationError("v164 requires its one-use zero-provider child boundary")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v164 requires a non-root host identity")
    blocked = (*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, *_DOCKER_ENDPOINT_ENV_NAMES)
    if any(name in os.environ for name in blocked):
        raise ConfigurationError("v164 zero-provider child environment is contaminated")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v164 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v164 requires a positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v164 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    upstream = _git("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v163_audit_merge, head],
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
        raise ConfigurationError("v164 requires clean merged origin/main after v163")
    return head


def _validate_predecessor(
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
) -> dict[str, Any]:
    v162_manifest = load_v162_official_matrix_manifest(V162_MANIFEST)
    report = _load_json(V162_REPORT)
    attempt = _load_json(V162_ATTEMPT)
    cleanup = _load_json(V162_CLEANUP)
    if (
        _hash_file(V162_MANIFEST) != manifest.v162_manifest_sha256
        or v162_manifest.manifest_hash != manifest.v162_manifest_hash
        or _hash_file(V162_RUNNER) != manifest.v162_runner_sha256
        or _hash_file(V162_LAUNCHER) != manifest.v162_launcher_sha256
        or _hash_file(V162_AUTHORIZATION) != manifest.v162_authorization_sha256
        or _hash_file(V162_REPORT) != manifest.v162_report_sha256
        or _canonical_hash(report, "report_hash") != manifest.v162_report_hash
        or _hash_file(V162_ATTEMPT) != manifest.v162_attempt_sha256
        or _canonical_hash(attempt, "attempt_hash") != manifest.v162_attempt_hash
        or _hash_file(V162_CLEANUP) != manifest.v162_cleanup_sha256
        or _canonical_hash(cleanup, "receipt_hash") != manifest.v162_cleanup_hash
        or hash_directory(V162_ROOT) != manifest.v162_evidence_tree_hash
        or _hash_file(V163_AUDIT) != manifest.v163_audit_sha256
        or _hash_file(PROCESS_MODULE) != manifest.process_module_sha256
        or _hash_file(HELPER_MODULE) != manifest.helper_module_sha256
    ):
        raise ConfigurationError("v164 predecessor identity changed")
    directories, files, symlinks = _tree_inventory(V162_ROOT)
    state = report.get("matrix_state")
    attempts = state.get("attempts") if isinstance(state, dict) else None
    if (
        directories != manifest.v162_evidence_directory_count
        or files != manifest.v162_evidence_regular_file_count
        or symlinks != manifest.v162_evidence_symlink_count
        or report.get("status") != "stopped_pending_independent_v163_audit"
        or report.get("stop_reason") != "pre_provider_infrastructure_failure"
        or report.get("exception_type") != "RuntimeError"
        or report.get("provider_episode_count") != 0
        or report.get("provider_call_count") != 0
        or report.get("provider_total_tokens") != 0
        or report.get("dind_cleanup_confirmed") is not True
        or report.get("v158_data_volume_reopen_count") != 1
        or not isinstance(attempts, list)
        or len(attempts) != 1
        or attempt.get("outcome") != "infrastructure_failure"
        or attempt.get("provider_marker") != "not_started"
        or attempt.get("provider_call_count") != 0
        or cleanup.get("cleanup_confirmed") is not True
        or any(
            report.get(name) is not False
            for name in (
                "formal_collection_allowed",
                "formal_collection_started",
                "collection_started",
                "training_started",
                "production_training_ready",
            )
        )
    ):
        raise ConfigurationError("v164 predecessor result boundary changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v164_predecessor_receipt_v1",
        "identity": IDENTITY,
        "v162_manifest_hash": v162_manifest.manifest_hash,
        "v162_report_hash": report["report_hash"],
        "v162_attempt_hash": attempt["attempt_hash"],
        "v162_cleanup_hash": cleanup["receipt_hash"],
        "v162_evidence_tree_hash": manifest.v162_evidence_tree_hash,
        "v163_audit_sha256": manifest.v163_audit_sha256,
        "v162_provider_consumed": False,
        "v162_data_volume_reopen_count": 1,
        "provider_calls": 0,
        "provider_values_read": False,
    }
    return _seal(base, "receipt_hash")


def _validate_host_runtime(
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
) -> None:
    if (
        Path(manifest.dind_data_backing) != DIND_DATA_BACKING
        or Path(manifest.dind_socket_backing) != DIND_SOCKET_BACKING
        or Path(manifest.control_headroom_root) != CONTROL_ROOT
        or Path(manifest.runtime_scratch_root) != RUNTIME_TMP
        or Path(manifest.output_root) != OUTPUT_ROOT
        or manifest.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or manifest.runtime_resource_owner != IDENTITY
        or manifest.v158_data_volume_reopen_count_before != 1
        or manifest.v158_data_volume_reopen_budget != 2
    ):
        raise ConfigurationError("v164 runtime path or ownership binding changed")
    dind._dind_image(manifest.dind_image_id)  # noqa: SLF001
    dind_image = dind._inspect("image", manifest.dind_image_id)  # noqa: SLF001
    if not any(
        isinstance(item, str) and item.endswith(f"@{manifest.dind_repository_digest}")
        for item in dind_image.get("RepoDigests", [])
    ):
        raise ConfigurationError("v164 DinD repository digest changed")
    data = dind._bind_backed_volume(  # noqa: SLF001
        manifest.dind_data_volume,
        owner=manifest.predecessor_data_volume_owner,
        role="data",
        backing=DIND_DATA_BACKING,
    )
    if data != DIND_DATA_BACKING.resolve(strict=True):
        raise ConfigurationError("v164 retained DinD data backing changed")
    users = dind._run(  # noqa: SLF001
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            f"volume={manifest.dind_data_volume}",
        ],
        timeout_s=30,
    )
    socket_volume = dind._run(  # noqa: SLF001
        ["docker", "volume", "inspect", manifest.dind_socket_volume], timeout_s=30
    )
    owned = dind._run(  # noqa: SLF001
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            f"label=verigym.owner={manifest.runtime_resource_owner}",
        ],
        timeout_s=30,
    )
    if (
        users.returncode != 0
        or users.stdout.strip()
        or socket_volume.returncode == 0
        or owned.returncode != 0
        or owned.stdout.strip()
    ):
        raise ConfigurationError("v164 refuses busy or stale Docker resources")
    network = dind._inspect("network", manifest.provider_outer_network)  # noqa: SLF001
    controller = dind._inspect("image", manifest.controller_image_tag)  # noqa: SLF001
    if (
        network.get("Name") != manifest.provider_outer_network
        or network.get("Driver") != "bridge"
        or network.get("Internal") is not False
        or network.get("Scope") != "local"
        or controller.get("Id") != manifest.controller_image_id
        or not any(
            isinstance(item, str)
            and item.endswith(f"@{manifest.controller_image_repository_digest}")
            for item in controller.get("RepoDigests", [])
        )
    ):
        raise ConfigurationError("v164 host network or controller identity changed")


def _validate_inner_controller_inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
) -> None:
    dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
    controller = dind._inner(  # noqa: SLF001
        ["image", "inspect", manifest.controller_image_tag, "--format", "{{json .}}"],
        container=dind_name,
        timeout_s=30,
    )
    network = dind._inner(  # noqa: SLF001
        ["network", "inspect", manifest.provider_inner_network],
        container=dind_name,
        timeout_s=30,
    )
    try:
        value = json.loads(controller.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v164 inner controller metadata is malformed") from exc
    if (
        controller.returncode != 0
        or value.get("Id") != manifest.controller_image_id
        or value.get("RepoTags") != [manifest.controller_image_tag]
        or value.get("RepoDigests") != []
        or network.returncode == 0
    ):
        raise ConfigurationError("v164 inner controller or network inventory changed")


def _direct_container_probe(
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    session_root = root / "direct-session"
    broker_root = root / "direct-broker"
    session_root.mkdir(mode=0o700)
    broker_root.mkdir(mode=0o700)
    runtime_assets_root = PROCESS_MODULE.parent / "runtime"
    container_id: str | None = None
    engine = DockerCliEngine(docker_host=manifest.nested_docker_host)
    status = "failed"
    output_within_bound = False
    removed = True
    image_identity_valid = False
    network_valid = False
    read_only_root = False
    non_root = False
    cap_drop_all = False
    no_new_privileges = False
    private_pid_ipc = False
    resource_limits_present = False
    tmpfs_valid = False
    mounts_valid = False
    provider_environment_present = False
    try:
        script = (
            "const fs=require('fs');"
            "fs.accessSync('/workspace/package.json',fs.constants.R_OK);"
            "fs.accessSync('/workspace/examples/jsonrpc-agent/cordis.yml',fs.constants.R_OK);"
            "for(const p of ['/sessions/.v164-probe','/broker/.v164-probe']){"
            "fs.writeFileSync(p,'ok',{mode:0o600});fs.unlinkSync(p)}"
        )
        container_id = engine.create_container(
            [
                "--name",
                f"verigym-v164-direct-{secrets.token_hex(8)}",
                "--label",
                "org.verigym.managed=true",
                "--label",
                f"verigym.owner={IDENTITY}",
                "--label",
                "verigym.role=controller-direct-probe",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--init",
                "--pids-limit",
                "512",
                "--memory",
                "2g",
                "--cpus",
                "2",
                "--network",
                manifest.provider_inner_network,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--workdir",
                "/workspace",
                "--mount",
                (f"type=bind,source={DEEPSEEK_HARNESS_SOURCE_ROOT},target=/workspace,readonly"),
                "--mount",
                (
                    f"type=bind,source={runtime_assets_root},"
                    "target=/workspace/examples/jsonrpc-agent,readonly"
                ),
                "--mount",
                f"type=bind,source={session_root},target=/sessions",
                "--mount",
                f"type=bind,source={broker_root},target=/broker",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=268435456,mode=1777",
                manifest.controller_image_id,
                "node",
                "-e",
                script,
            ]
        )
        metadata = engine.inspect_container(container_id)
        config = metadata.get("Config") or {}
        host = metadata.get("HostConfig") or {}
        mounts = metadata.get("Mounts") or []
        environment_names = {
            item.partition("=")[0] for item in config.get("Env", []) if isinstance(item, str)
        }
        labels = config.get("Labels") or {}
        security_options = host.get("SecurityOpt") or []
        by_destination = {
            item.get("Destination"): item for item in mounts if isinstance(item, dict)
        }
        expected_mounts = {
            "/workspace": (str(DEEPSEEK_HARNESS_SOURCE_ROOT), False),
            "/workspace/examples/jsonrpc-agent": (str(runtime_assets_root), False),
            "/sessions": (str(session_root), True),
            "/broker": (str(broker_root), True),
        }
        image_identity_valid = config.get("Image") == manifest.controller_image_id
        network_valid = host.get("NetworkMode") == manifest.provider_inner_network
        read_only_root = host.get("ReadonlyRootfs") is True
        non_root = config.get("User") == f"{os.getuid()}:{os.getgid()}"
        cap_drop_all = set(host.get("CapDrop") or []) == {"ALL"}
        no_new_privileges = any(
            isinstance(item, str) and item.startswith("no-new-privileges")
            for item in security_options
        )
        private_pid_ipc = host.get("PidMode") in (None, "") and host.get("IpcMode") == "private"
        resource_limits_present = (
            host.get("PidsLimit") == 512
            and host.get("Memory") == 2 * 1024**3
            and host.get("NanoCpus") == 2 * 10**9
            and host.get("Init") is True
        )
        tmpfs_valid = host.get("Tmpfs") == {
            "/tmp": "rw,noexec,nosuid,nodev,size=268435456,mode=1777"
        }
        mounts_valid = (
            set(expected_mounts) <= set(by_destination)
            and set(by_destination)
            <= {
                *expected_mounts,
                "/tmp",
            }
            and all(
                item.get("Source") == source and item.get("RW") is writable
                for destination, (source, writable) in expected_mounts.items()
                for item in (by_destination[destination],)
            )
        )
        provider_environment_present = bool(
            set(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES).intersection(environment_names)
            or {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"}.intersection(environment_names)
        )
        metadata_valid = (
            image_identity_valid
            and network_valid
            and read_only_root
            and non_root
            and cap_drop_all
            and no_new_privileges
            and private_pid_ipc
            and resource_limits_present
            and tmpfs_valid
            and mounts_valid
            and not provider_environment_present
            and labels.get("org.verigym.managed") == "true"
            and labels.get("verigym.owner") == IDENTITY
            and labels.get("verigym.role") == "controller-direct-probe"
        )
        started = engine.start_container(container_id)
        waited = engine.wait_container(
            container_id,
            timeout_s=manifest.direct_container_probe_timeout_seconds,
        )
        logs = engine.logs_container(
            container_id,
            max_output_bytes=manifest.maximum_diagnostic_output_bytes,
        )
        output_within_bound = not logs.output_truncated
        status = (
            "passed"
            if metadata_valid
            and started.exit_code == 0
            and not started.timed_out
            and waited.exit_code == 0
            and not waited.timed_out
            and waited.stdout.strip() == "0"
            and logs.exit_code == 0
            and output_within_bound
            and not logs.stdout
            and not logs.stderr
            else "failed"
        )
    except Exception:
        status = "failed"
    finally:
        try:
            if container_id is not None:
                removal = engine.remove_container(container_id)
                removed = removal.exit_code == 0 and not removal.timed_out
        finally:
            engine.close()
    if not removed:
        raise ConfigurationError("v164 direct probe container cleanup failed")
    if (
        next(session_root.iterdir(), None) is not None
        or next(broker_root.iterdir(), None) is not None
    ):
        raise ConfigurationError("v164 direct probe left private artifacts")
    session_root.rmdir()
    broker_root.rmdir()
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v164_direct_container_probe_v1",
        "identity": IDENTITY,
        "status": status,
        "explicit_nested_docker_endpoint": True,
        "controller_image_id": manifest.controller_image_id,
        "network": manifest.provider_inner_network,
        "image_identity_valid": image_identity_valid,
        "network_valid": network_valid,
        "read_only_root": read_only_root,
        "non_root": non_root,
        "cap_drop_all": cap_drop_all,
        "no_new_privileges": no_new_privileges,
        "private_pid_ipc": private_pid_ipc,
        "resource_limits_present": resource_limits_present,
        "tmpfs_valid": tmpfs_valid,
        "same_path_mounts_valid": mounts_valid,
        "writable_session_and_broker_valid": mounts_valid,
        "provider_environment_present": provider_environment_present,
        "output_within_bound": output_within_bound,
        "raw_output_persisted": False,
        "output_hashed": False,
        "container_removed": True,
        "provider_calls": 0,
    }
    return _seal(base, "probe_hash")


def _harness_initialize_probe(
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
    *,
    root: Path,
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
            "controller_image_source_receipt_hash": (manifest.controller_image_source_receipt_hash),
            "controller_docker_host": manifest.nested_docker_host,
            "whole_episode_retries": 0,
        },
        task_wall_time_s=manifest.harness_initialize_timeout_seconds,
    )
    synthetic_key = "v164-offline-" + secrets.token_urlsafe(48)
    synthetic_url = "http://127.0.0.1:9/v1"
    category = "passed"
    helper_status = "passed"
    try:
        os.environ[API_KEY_ENV] = synthetic_key
        os.environ[BASE_URL_ENV] = synthetic_url
        try:
            result = run_harness_helper(
                settings,
                mode="initialize",
                prompt="",
                system_prompt="VeriGym v164 synthetic zero-provider initialization diagnostic.",
                session_id="v164-controller-initialize-diagnostic",
                session_root=session_root,
                broker_root=broker_root,
                docker_host=settings.docker_host,
            )
        except DeepSeekHarnessProcessError as exc:
            helper_status = "failed"
            category = exc.category
            result = None
        except Exception:
            helper_status = "failed"
            category = "helper_unclassified_error"
            result = None
    finally:
        os.environ.pop(API_KEY_ENV, None)
        os.environ.pop(BASE_URL_ENV, None)
    values = (synthetic_key, synthetic_url)
    marker = session_root / "provider-request-started-v1.json"
    provider_started = marker.exists() or (result is not None and result.provider_request_started)
    if provider_started:
        _purge_probe_roots(root, values, required=True)
        raise ConfigurationError("v164 synthetic initialize crossed the provider boundary")
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
    purge = _purge_probe_roots(root, values, required=True)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v164_harness_initialize_diagnostic_v1",
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
        "harness_initialize_started": True,
        "provider_request_started": False,
        "provider_calls": 0,
        "synthetic_provider_values_only": True,
        "synthetic_value_count": 2,
        "synthetic_value_hits": 0,
        "private_artifact_file_count_removed": purge["file_count_removed"],
        "private_artifact_byte_count_removed": purge["byte_count_removed"],
        "raw_exception_persisted": False,
        "raw_stderr_persisted": False,
        "synthetic_values_persisted_or_hashed": False,
    }
    return _seal(base, "diagnostic_hash")


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
                raise ConfigurationError("v164 private diagnostic root disappeared")
            continue
        if target.is_symlink() or not target.is_dir():
            raise ConfigurationError("v164 private diagnostic root is unsafe")
        paths = sorted(
            target.rglob("*"),
            key=lambda path: (len(path.relative_to(target).parts), path.as_posix()),
            reverse=True,
        )
        for path in paths:
            if path.is_symlink():
                raise ConfigurationError("v164 private diagnostic tree contains a symlink")
            if path.is_file():
                payload = path.read_bytes()
                file_count += 1
                byte_count += len(payload)
                hit_count += sum(value.encode() in payload for value in values)
                path.unlink()
            elif path.is_dir():
                path.rmdir()
            else:
                raise ConfigurationError("v164 private diagnostic tree contains a special file")
        target.rmdir()
    if hit_count:
        raise ConfigurationError("v164 synthetic provider value reached private artifacts")
    return {"file_count_removed": file_count, "byte_count_removed": byte_count}


@contextlib.contextmanager
def _v164_bindings() -> Iterator[None]:
    replacements = {
        "IDENTITY": IDENTITY,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "CONTROL_ROOT": CONTROL_ROOT,
        "RUNTIME_TMP": RUNTIME_TMP,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
    }
    previous = {name: getattr(v162, name) for name in _PATCH_NAMES}
    try:
        for name, value in replacements.items():
            setattr(v162, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v162, name, value)


def _v164_socket_cleanup(
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    value = v162._clean_socket_volume(manifest, root=root)  # noqa: SLF001
    receipt = _reformat_receipt(
        value,
        "verigym_deepseek_harness_hwe_v164_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", receipt)
    return receipt


def _best_effort_cleanup(
    *,
    dind_name: str | None,
    inner_network_created: bool,
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
    root: Path,
) -> tuple[bool, str | None]:
    confirmed, _old_hash = v162._best_effort_cleanup(  # noqa: SLF001
        dind_name=dind_name,
        inner_network_created=inner_network_created,
        manifest=manifest,
        root=root,
    )
    path = root / "dind-cleanup-receipt.json"
    if confirmed and path.is_file():
        value = _load_json(path)
        receipt = _reformat_receipt(
            value,
            "verigym_deepseek_harness_hwe_v164_socket_cleanup_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        return True, str(receipt["receipt_hash"])
    return confirmed, None


def _base_progress(
    manifest: DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
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
        "v158_data_volume_reopen_count": 1,
        "diagnostic_category": None,
        "provider_request_started": False,
        "provider_calls": 0,
        "provider_tokens": 0,
        "task_execution_started": False,
        "base_reference_verification_started": False,
        "official_verifier_started": False,
        "raw_exception_persisted": False,
        "raw_stderr_persisted": False,
        "synthetic_values_persisted_or_hashed": False,
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
        diagnosis = "v162_initialize_failure_not_reproduced_with_synthetic_values"
    elif category == "direct_container_probe_failed":
        diagnosis = "controller_container_prerequisite_probe_failed"
    elif isinstance(category, str):
        diagnosis = f"v162_initialize_failure_reproduced_as_{category}"
    else:
        diagnosis = "diagnostic_infrastructure_failure"
    base = {
        **dict(copy.deepcopy(progress)),
        "format_id": REPORT_FORMAT,
        "status": (
            "diagnosed_pending_independent_v165_audit"
            if diagnosed
            else "stopped_pending_independent_v165_audit"
        ),
        "diagnosis": diagnosis,
        "diagnosis_confirmed": diagnosed,
        "requires_independent_v165_audit": True,
        "replacement_provider_matrix_authorized": False,
        "benchmark_score_claimed": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "provider_tokens": 0,
        **_closed_flags(),
    }
    return _seal(base, "report_hash")


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    atomic_dump_json(root / "diagnostic-progress.json", dict(value))


def _new_output(path: Path) -> Path:
    if path != OUTPUT_ROOT or path.exists() or path.is_symlink():
        raise ConfigurationError("v164 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"v164 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_file():
        raise ConfigurationError(f"v164 {label} identity changed")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v164 JSON input is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v164 JSON input is malformed") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v164 JSON input is not an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v164 predecessor canonical hash changed")
    return observed


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_inventory(root: Path) -> tuple[int, int, int]:
    paths = [root, *root.rglob("*")]
    return (
        sum(path.is_dir() and not path.is_symlink() for path in paths),
        sum(path.is_file() and not path.is_symlink() for path in paths),
        sum(path.is_symlink() for path in paths),
    )


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
    return 0 if report["status"] == "diagnosed_pending_independent_v165_audit" else 1


if __name__ == "__main__":
    raise SystemExit(main())
