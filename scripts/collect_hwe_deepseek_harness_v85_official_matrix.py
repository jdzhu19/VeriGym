#!/usr/bin/env python3
"""Run the authorized five-task v85 DeepSeek Harness official matrix exactly once."""

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
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, cast

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

from verigym_deepseek_harness import (  # noqa: E402
    __version__ as VERIGYM_DEEPSEEK_HARNESS_VERSION,
)
from verigym_deepseek_harness.config import (  # noqa: E402
    API_KEY_ENV,
    BASE_URL_ENV,
    CONTROLLER_IMAGE_REPO_DIGEST,
    DEEPSEEK_HARNESS_SOURCE_ROOT,
    DEEPSEEK_HARNESS_VERSION,
    resolve_settings,
)
from verigym_deepseek_harness.process import run_harness_helper  # noqa: E402

from scripts import collect_ibex_hwe_deepseek_harness_v67_provider_canary as v67  # noqa: E402
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.api import VeriGym  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.core.security_scanner import (  # noqa: E402
    require_security_scan_pass,
    scan_artifact_roots,
)
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID  # noqa: E402
from verigym.hwe.deepseek_harness import (  # noqa: E402
    DEEPSEEK_HARNESS_MODEL,
    validate_deepseek_harness_transcript_v3,
)
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessMatrixAttempt,
    DeepSeekHarnessMatrixState,
    DeepSeekHarnessV85OfficialMatrixManifest,
    DeepSeekHarnessV85TaskBinding,
    HweAdmissionPlanes,
    ProviderMarker,
    load_v85_official_matrix_manifest,
    migration_conclusions,
    new_matrix_state,
    record_matrix_attempt,
    require_toolchain_verifier_binding,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID  # noqa: E402
from verigym.hwe.qwen_action_tokenizer import (  # noqa: E402
    QwenDecisionExampleTokenizer,
    dry_run_decision_record_v4,
    exact_decision_token_receipt,
)
from verigym.runtimes.docker.runtime import DockerRuntime  # noqa: E402
from verigym.schemas.common import InteractionMode  # noqa: E402
from verigym.schemas.run import RunConfig  # noqa: E402
from verigym.schemas.runtime import (  # noqa: E402
    DockerCommandImageRuntimeConfig,
    DockerRuntimeConfig,
)
from verigym.schemas.suite import SuiteSourceConfig  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v85-official-matrix-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V85_OFFICIAL_MATRIX"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v85_official_matrix_v1.json"
)
V83_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v83_controller_tag_successor_v1.json"
)
V84_AUDIT = _REPOSITORY / ("docs/audits/2026-09-03_deepseek-harness-v84-v83-scaffold-success.md")
V83_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v83-controller-tag-successor-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v85-official-matrix-v1"
)
TOKENIZER_ROOT = Path("/data2/jiadongzhu/Agent/datasets/Qwen3.5-9B-tokenizer-v1")
BASE_MODEL_LOCK = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "openhands-hwe-v58-ibex-pr54-provider-canary-inputs-v1/base-model-lock.json"
)
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v85-runtime")
DIND_DATA_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/data")
DIND_SOCKET_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/socket")
REPORT_FORMAT = "verigym_deepseek_harness_hwe_v85_official_matrix_result_v1"
PROGRESS_FORMAT = "verigym_deepseek_harness_hwe_v85_official_matrix_progress_v1"
ATTEMPT_FORMAT = "verigym_deepseek_harness_hwe_v85_official_matrix_attempt_v1"
DECISION_FORMAT = "verigym_deepseek_harness_hwe_v85_decision_64k_v1"
DATASET_FORMAT = "verigym_deepseek_harness_hwe_v85_candidate_dataset_64k_v1"
COMMAND_EXECUTION_BACKEND: Literal["episode_container_exec_v1"] = "episode_container_exec_v1"
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_CLEANUP_OUTPUT_BYTES = 1024 * 1024
_CLEANUP_PATHS = (
    "/verigym-socket/docker.sock",
    "/verigym-socket/docker.pid",
    "/verigym-socket/docker",
    "/verigym-socket/containerd",
    "/verigym-socket/runc",
    "/verigym-socket/xtables.lock",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v83_controller_tag_successor_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v85_official_matrix_v1.json",
    "docs/audits/2026-09-03_deepseek-harness-v84-v83-scaffold-success.md",
    "docs/audits/2026-09-03_deepseek-harness-v85-official-matrix-authorization.md",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/agent.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/config.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/helper.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/process.py",
    "integrations/verigym-deepseek-harness/tests/test_v85_official_matrix.py",
    "scripts/collect_hwe_deepseek_harness_v85_official_matrix.py",
    "scripts/run_repository_rollout_dind_controller.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--v83-root", type=Path, default=V83_ROOT)
    parser.add_argument("--tokenizer-root", type=Path, default=TOKENIZER_ROOT)
    parser.add_argument("--base-model-lock", type=Path, default=BASE_MODEL_LOCK)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the manifest in order and seal every task disposition atomically."""

    _require_opt_in()
    manifest = load_v85_official_matrix_manifest(
        _exact_file(arguments.manifest, MANIFEST, "manifest")
    )
    if arguments.post_merge_main_run_id <= 0:
        raise ConfigurationError("v85 requires its positive post-merge main run ID")
    source_commit = _require_clean_merged_main(manifest)
    v83_root = _exact_directory(arguments.v83_root, V83_ROOT, "v83 evidence root")
    tokenizer_root = _exact_directory(arguments.tokenizer_root, TOKENIZER_ROOT, "tokenizer root")
    base_model_lock = _exact_file(arguments.base_model_lock, BASE_MODEL_LOCK, "base-model lock")
    _validate_predecessor(manifest, v83_root=v83_root)
    locks = _validate_task_bindings(manifest, v83_root=v83_root)
    exact_tokenizer, transformers_version = _load_exact_tokenizer(
        manifest,
        tokenizer_root=tokenizer_root,
        base_model_lock=base_model_lock,
    )
    _validate_host_runtime(manifest)

    root = _new_output(arguments.output)
    for directory in (
        "attempts",
        "candidate-datasets",
        "preflight",
        "security-scans",
        "tasks",
        "trajectory-records",
    ):
        (root / directory).mkdir(mode=0o700)
    state = new_matrix_state([item.task_id for item in manifest.schedule])
    details: list[dict[str, Any]] = []
    progress = _base_progress(
        manifest,
        state,
        source_commit=source_commit,
        post_merge_main_run_id=arguments.post_merge_main_run_id,
        transformers_version=transformers_version,
    )
    _write_progress(root, progress)

    dind_name: str | None = None
    inner_network_created = False
    reopen_count = 0
    cleanup_confirmed = False
    cleanup_receipt_hash: str | None = None
    active_binding: DeepSeekHarnessV85TaskBinding | None = manifest.schedule[0]
    try:
        _prepare_socket_backing(manifest)
        dind._create_bind_backed_volume(  # noqa: SLF001
            manifest.dind_socket_volume,
            owner=dind._DIND_OWNER,  # noqa: SLF001
            role="socket",
            backing=DIND_SOCKET_BACKING,
        )
        dind_name = f"verigym-dind-v85-{secrets.token_hex(10)}"
        metadata = _start_provider_dind(
            name=dind_name,
            manifest=manifest,
            root=root,
        )
        reopen_count = 1
        runtime_receipt = _provider_runtime_receipt(
            manifest,
            dind_name=dind_name,
            metadata=metadata,
        )
        atomic_dump_json(root / "provider-dind-runtime-receipt.json", runtime_receipt)
        _validate_inner_inventory(dind_name, manifest)
        _create_inner_provider_network(dind_name, manifest)
        inner_network_created = True
        network_receipt = _network_receipt(dind_name, manifest)
        atomic_dump_json(root / "provider-network-receipt.json", network_receipt)

        with _nested_runtime(DIND_SOCKET_BACKING / "docker.sock"):
            preflight = _zero_provider_preflight(
                manifest,
                locks=locks,
                root=root,
                dind_name=dind_name,
            )
            atomic_dump_json(root / "preflight/zero-provider-preflight.json", preflight)
            progress.update(
                {
                    "status": "running",
                    "v83_data_volume_reopen_count": 1,
                    "provider_dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
                    "provider_network_receipt_hash": network_receipt["receipt_hash"],
                    "zero_provider_preflight_hash": preflight["receipt_hash"],
                }
            )
            _write_progress(root, progress)

            service = v67._service()  # noqa: SLF001
            for binding in manifest.schedule:
                if state.status != "running":
                    break
                active_binding = binding
                detail = _execute_one(
                    service=service,
                    manifest=manifest,
                    binding=binding,
                    lock=locks[binding.task_id],
                    source_root=v83_root / "sources" / f"pr-{binding.pr_number}",
                    tokenizer=exact_tokenizer,
                    root=root,
                )
                next_state = record_matrix_attempt(state, _state_attempt(detail))
                atomic_dump_json(root / "attempts" / f"pr-{binding.pr_number}.json", detail)
                details.append(detail)
                state = next_state
                progress.update(
                    {
                        "matrix_state": state.model_dump(mode="json"),
                        "attempts": copy.deepcopy(details),
                        "provider_episode_count": sum(
                            item["provider_marker"] != "not_started" for item in details
                        ),
                        "provider_call_count": sum(
                            int(item["provider_call_count"] or 0) for item in details
                        ),
                        "provider_total_tokens": sum(
                            int(item["provider_total_tokens"] or 0) for item in details
                        ),
                        "status": state.status,
                        "stop_reason": state.stop_reason,
                    }
                )
                _write_progress(root, progress)
                active_binding = (
                    manifest.schedule[state.next_index] if state.status == "running" else None
                )

        if inner_network_created:
            _remove_inner_provider_network(dind_name, manifest)
            inner_network_created = False
        dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
        if not dind._remove_container(dind_name):  # noqa: SLF001
            raise ConfigurationError("v85 provider DinD sidecar cleanup failed")
        dind_name = None
        cleanup = _clean_socket_volume(manifest, root=root)
        cleanup_confirmed = True
        cleanup_receipt_hash = str(cleanup["receipt_hash"])
    except Exception as exc:
        binding_pending = (
            active_binding is not None
            and state.status == "running"
            and state.next_index < len(state.schedule)
            and state.schedule[state.next_index] == active_binding.task_id
        )
        if binding_pending:
            assert active_binding is not None
            binding = active_binding
            marker, _valid = _provider_marker_for_binding(root, binding)
            detail = _exception_attempt(
                binding,
                marker=marker,
                exception=exc,
            )
            atomic_dump_json(
                root / "attempts" / f"pr-{binding.pr_number}.json",
                detail,
            )
            details.append(detail)
            state = record_matrix_attempt(state, _state_attempt(detail))
        cleanup_confirmed, cleanup_receipt_hash = _best_effort_cleanup(
            dind_name=dind_name,
            inner_network_created=inner_network_created,
            manifest=manifest,
            root=root,
        )
        progress.update(
            {
                "matrix_state": state.model_dump(mode="json"),
                "attempts": copy.deepcopy(details),
                "status": "stopped",
                "stop_reason": state.stop_reason or "campaign_infrastructure_failure",
                "raw_exception_persisted": False,
                "exception_type": type(exc).__name__,
                "v83_data_volume_reopen_count": reopen_count,
                "dind_cleanup_confirmed": cleanup_confirmed,
                "dind_cleanup_receipt_hash": cleanup_receipt_hash,
            }
        )
        final = _final_report(manifest, progress, details)
        atomic_dump_json(root / "matrix-progress.json", final)
        atomic_dump_json(root / "matrix-report.json", final)
        _assert_no_provider_values(root)
        return final

    if not cleanup_confirmed:
        raise ConfigurationError("v85 cleanup must complete before result publication")
    progress.update(
        {
            "matrix_state": state.model_dump(mode="json"),
            "attempts": copy.deepcopy(details),
            "status": state.status,
            "stop_reason": state.stop_reason,
            "v83_data_volume_reopen_count": reopen_count,
            "dind_cleanup_confirmed": True,
            "dind_cleanup_receipt_hash": cleanup_receipt_hash,
        }
    )
    final = _final_report(manifest, progress, details)
    atomic_dump_json(root / "matrix-progress.json", final)
    atomic_dump_json(root / "matrix-report.json", final)
    _assert_no_provider_values(root)
    return final


def _base_progress(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    state: DeepSeekHarnessMatrixState,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
    transformers_version: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": PROGRESS_FORMAT,
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "v84_audit_commit": manifest.v84_audit_commit,
        "v84_post_merge_main_run_id": manifest.v84_post_merge_main_run_id,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "provider": manifest.provider,
        "model": manifest.model,
        "harness_version": manifest.harness_version,
        "integration_version": manifest.integration_version,
        "transformers_version": transformers_version,
        "seed": manifest.seed,
        "sample_index": manifest.sample_index,
        "matrix_state": state.model_dump(mode="json"),
        "attempts": [],
        "status": "provider_dind_preflight",
        "stop_reason": None,
        "provider_episode_count": 0,
        "provider_call_count": 0,
        "provider_total_tokens": 0,
        "v83_data_volume_reopen_budget": 1,
        "v83_data_volume_reopen_count": 0,
        "dind_cleanup_confirmed": False,
        "benchmark_score_claimed": False,
        **_closed_training_flags(),
    }


def _validate_predecessor(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    *,
    v83_root: Path,
) -> None:
    paths = {
        V83_MANIFEST: manifest.v83_manifest_sha256,
        V84_AUDIT: manifest.v84_audit_sha256,
        v83_root / "execution-scaffold-report.json": manifest.v83_report_sha256,
        v83_root / "execution-scaffold-contract.json": manifest.v83_contract_sha256,
        v83_root / "execution-inventory.json": manifest.v83_inventory_sha256,
        v83_root / "controller-image-receipt.json": manifest.v83_controller_receipt_sha256,
        v83_root / "dind-runtime-receipt.json": manifest.v83_runtime_receipt_sha256,
        v83_root / "dind-cleanup-receipt.json": manifest.v83_cleanup_receipt_sha256,
    }
    for path, expected in paths.items():
        if path.is_symlink() or _hash_file(path) != expected:
            raise ConfigurationError(f"v85 predecessor evidence changed: {path.name}")
    values = {
        "report": _load_json(v83_root / "execution-scaffold-report.json"),
        "contract": _load_json(v83_root / "execution-scaffold-contract.json"),
        "inventory": _load_json(v83_root / "execution-inventory.json"),
        "controller": _load_json(v83_root / "controller-image-receipt.json"),
        "runtime": _load_json(v83_root / "dind-runtime-receipt.json"),
        "cleanup": _load_json(v83_root / "dind-cleanup-receipt.json"),
    }
    expected_hashes = {
        "report": ("report_hash", manifest.v83_report_hash),
        "contract": ("contract_hash", manifest.v83_contract_hash),
        "inventory": ("inventory_hash", manifest.v83_inventory_hash),
        "controller": ("receipt_hash", manifest.v83_controller_receipt_hash),
        "runtime": ("receipt_hash", manifest.v83_runtime_receipt_hash),
        "cleanup": ("receipt_hash", manifest.v83_cleanup_receipt_hash),
    }
    for label, (field, expected) in expected_hashes.items():
        value = dict(values[label])
        observed = value.pop(field, None)
        if observed != expected or content_hash(value) != expected:
            raise ConfigurationError(f"v85 predecessor {label} hash changed")
    report = values["report"]
    contract = values["contract"]
    inventory = values["inventory"]
    controller = values["controller"]
    cleanup = values["cleanup"]
    if (
        report.get("status") != "completed_pending_independent_v84_audit"
        or report.get("provider_execution_scaffold_published") is not True
        or report.get("provider_execution_authorized") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or contract.get("provider_successor_identity") != IDENTITY
        or contract.get("provider_successor_reopen_budget") != 1
        or contract.get("provider_successor_reopen_count") != 0
        or contract.get("provider_execution_authorized") is not False
        or contract.get("provider_calls") != 0
        or contract.get("all_tasks_materialized") is not True
        or contract.get("all_base_failed_reference_passed") is not True
        or contract.get("all_command_images_v2_scanned") is not True
        or inventory.get("required_images_present") is not True
        or inventory.get("provider_inner_network_created") is not False
        or inventory.get("inner_container_inventory_empty") is not True
        or inventory.get("inner_volume_inventory_empty") is not True
        or controller.get("controller_image_id") != manifest.controller_image_id
        or controller.get("controller_image_tag") != manifest.controller_image_tag
        or controller.get("inner_repository_digest_metadata_preserved") is not False
        or controller.get("inner_repository_digest_not_required_after_offline_load") is not True
        or controller.get("outer_source_repository_digest_verified") is not True
        or cleanup.get("cleanup_confirmed") is not True
    ):
        raise ConfigurationError("v85 predecessor scaffold is not eligible")


def _validate_task_bindings(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    *,
    v83_root: Path,
) -> dict[str, HweCommandImageLock]:
    contract = _load_json(v83_root / "execution-scaffold-contract.json")
    receipts = contract.get("task_receipts")
    if not isinstance(receipts, list) or len(receipts) != len(manifest.schedule):
        raise ConfigurationError("v85 predecessor task receipt inventory changed")
    by_task = {
        item.get("task_id"): item
        for item in receipts
        if isinstance(item, dict) and isinstance(item.get("task_id"), str)
    }
    locks: dict[str, HweCommandImageLock] = {}
    for binding in manifest.schedule:
        receipt = by_task.get(binding.task_id)
        if not isinstance(receipt, dict):
            raise ConfigurationError("v85 task receipt is missing")
        pr = binding.pr_number
        lock_path = v83_root / "image-locks" / f"pr-{pr}.json"
        scan_path = v83_root / "security-scans" / f"pr-{pr}.json"
        source_lock_path = v83_root / "sources" / f"pr-{pr}" / "image-lock.json"
        if (
            _hash_file(lock_path) != binding.command_image_lock_file_sha256
            or _hash_file(scan_path) != binding.security_scan_file_sha256
            or _hash_file(source_lock_path) != binding.prepared_source_image_lock_sha256
        ):
            raise ConfigurationError("v85 task evidence file changed")
        lock = HweCommandImageLock.model_validate_json(lock_path.read_bytes())
        scan = _load_json(scan_path)
        expected_receipt = {
            "task_id": binding.task_id,
            "repository": binding.repository,
            "task_hash": binding.task_hash,
            "source_hash": binding.source_hash,
            "task_receipt_hash": binding.task_receipt_hash,
            "prepared_source_image_lock_sha256": binding.prepared_source_image_lock_sha256,
            "agent_command_image_lock_hash": binding.command_image_lock_hash,
            "agent_command_image": binding.command_image,
            "security_scan_id": binding.security_scan_id,
            "official_verifier_image": binding.official_verifier_image,
            "agent_toolchain_id": binding.agent_toolchain_id,
            "toolchain_profile_id": binding.toolchain_profile_id,
            "base_failed": True,
            "base_infrastructure_error": False,
            "reference_passed": True,
            "verifier_network": "none",
            "agent_command_network": "none",
            "provider_calls": 0,
            "model_process_count": 0,
        }
        if (
            any(receipt.get(key) != value for key, value in expected_receipt.items())
            or lock.task_id != binding.task_id
            or lock.task_hash != binding.task_hash
            or lock.source_hash != binding.source_hash
            or lock.lock_hash != binding.command_image_lock_hash
            or lock.derived_command_image_id != binding.command_image
            or lock.verifier_base_image_id != binding.official_verifier_image
            or lock.security_scan_id != binding.security_scan_id
            or lock.toolchain_profile_id != binding.toolchain_profile_id
            or lock.runtime_network != "none"
            or lock.security_scan_passed is not True
            or scan.get("scan_passed") is not True
            or scan.get("secrets_detected") is not False
            or scan.get("security_scan_id") != binding.security_scan_id
        ):
            raise ConfigurationError("v85 task/source/image binding changed")
        locks[binding.task_id] = lock
    return locks


def _load_exact_tokenizer(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    *,
    tokenizer_root: Path,
    base_model_lock: Path,
) -> tuple[QwenDecisionExampleTokenizer, str]:
    if _hash_file(base_model_lock) != manifest.base_model_lock_sha256:
        raise ConfigurationError("v85 base-model lock changed")
    model_lock = v67._base._base_model_lock(base_model_lock, tokenizer_root)  # noqa: SLF001
    if (
        model_lock["snapshot_hash"] != manifest.base_model_snapshot_hash
        or model_lock["tokenizer_hash"] != manifest.exact_tokenizer_hash
    ):
        raise ConfigurationError("v85 exact tokenizer binding changed")
    tokenizer, transformers_version = v67._base._load_tokenizer(tokenizer_root)  # noqa: SLF001
    exact = QwenDecisionExampleTokenizer(tokenizer, tokenizer_root=tokenizer_root)
    if exact.tokenizer_hash != manifest.exact_tokenizer_hash:
        raise ConfigurationError("v85 exact tokenizer identity changed")
    return exact, transformers_version


def _validate_host_runtime(manifest: DeepSeekHarnessV85OfficialMatrixManifest) -> None:
    dind._dind_image(manifest.dind_image_id)  # noqa: SLF001
    image = dind._inspect("image", manifest.dind_image_id)  # noqa: SLF001
    if not any(
        isinstance(item, str) and item.endswith(f"@{manifest.dind_repository_digest}")
        for item in image.get("RepoDigests", [])
    ):
        raise ConfigurationError("v85 DinD repository digest changed")
    data = dind._bind_backed_volume(  # noqa: SLF001
        manifest.dind_data_volume,
        owner=dind._DIND_OWNER,  # noqa: SLF001
        role="data",
        backing=DIND_DATA_BACKING,
    )
    if data != DIND_DATA_BACKING.resolve(strict=True):
        raise ConfigurationError("v85 DinD data backing changed")
    socket_volume = dind._run(  # noqa: SLF001
        ["docker", "volume", "inspect", manifest.dind_socket_volume], timeout_s=30
    )
    if socket_volume.returncode == 0:
        raise ConfigurationError("v85 fixed socket volume must not pre-exist")
    existing_sidecars = dind._run(  # noqa: SLF001
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            f"label=verigym.owner={dind._DIND_OWNER}",  # noqa: SLF001
        ],
        timeout_s=30,
    )
    if existing_sidecars.returncode != 0 or existing_sidecars.stdout.strip():
        raise ConfigurationError("v85 refuses stale campaign-owned DinD sidecars")
    network = dind._inspect("network", manifest.provider_outer_network)  # noqa: SLF001
    if (
        network.get("Name") != manifest.provider_outer_network
        or network.get("Driver") != "bridge"
        or network.get("Internal") is not False
        or network.get("Scope") != "local"
    ):
        raise ConfigurationError("v85 host provider network differs from policy")
    controller = dind._inspect("image", manifest.controller_image_tag)  # noqa: SLF001
    if controller.get(
        "Id"
    ) != manifest.controller_image_id or CONTROLLER_IMAGE_REPO_DIGEST not in controller.get(
        "RepoDigests", []
    ):
        raise ConfigurationError("v85 host controller provenance changed")


def _prepare_socket_backing(manifest: DeepSeekHarnessV85OfficialMatrixManifest) -> None:
    if (
        Path(manifest.dind_socket_backing) != DIND_SOCKET_BACKING
        or DIND_SOCKET_BACKING.is_symlink()
        or not DIND_SOCKET_BACKING.is_dir()
    ):
        raise ConfigurationError("v85 socket backing identity changed")
    metadata = DIND_SOCKET_BACKING.stat()
    if (
        next(DIND_SOCKET_BACKING.iterdir(), None) is not None
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
    ):
        raise ConfigurationError("v85 socket backing is not empty and owner-only")
    for path in (CONTROL_ROOT, RUNTIME_TMP):
        if path.is_symlink():
            raise ConfigurationError("v85 control or runtime scratch path is unsafe")
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.chmod(0o700)
    if next(RUNTIME_TMP.iterdir(), None) is not None:
        raise ConfigurationError("v85 runtime scratch must be empty before execution")


def _start_provider_dind(
    *,
    name: str,
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    root: Path,
) -> dict[str, Any]:
    empty_home = V83_ROOT / "dind-empty-home"
    if empty_home.is_symlink() or not empty_home.is_dir() or next(empty_home.iterdir(), None):
        raise ConfigurationError("v85 v83 empty-home sentinel changed")
    same_paths = dind._same_path_mounts(  # noqa: SLF001
        {
            _REPOSITORY.resolve(strict=True): "ro",
            V83_ROOT.resolve(strict=True): "ro",
            DEEPSEEK_HARNESS_SOURCE_ROOT.resolve(strict=True): "ro",
            CONTROL_ROOT.resolve(strict=True): "rw",
            RUNTIME_TMP.resolve(strict=True): "rw",
            root.resolve(strict=True): "rw",
        }
    )
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        f"verigym.owner={dind._DIND_OWNER}",  # noqa: SLF001
        "--label",
        "verigym.role=provider-daemon",
        "--privileged",
        "--network",
        manifest.provider_outer_network,
        "--pids-limit",
        "32768",
        "--env",
        "DOCKER_TLS_CERTDIR=",
        "--volume",
        f"{manifest.dind_socket_volume}:/var/run:rw",
        "--volume",
        f"{manifest.dind_data_volume}:/var/lib/docker:rw",
        "--mount",
        f"type=bind,src={empty_home},dst=/verigym-host-sentinel,readonly",
        *same_paths,
        manifest.dind_image_id,
        "--storage-driver=vfs",
        f"--group={os.getgid()}",
    ]
    started = dind._run(command, timeout_s=60)  # noqa: SLF001
    if started.returncode != 0:
        raise ConfigurationError("v85 provider DinD sidecar failed to start")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready = dind._run(  # noqa: SLF001
            ["docker", "exec", name, "docker", "info"], timeout_s=15
        )
        if ready.returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise ConfigurationError("v85 provider DinD daemon did not become ready")
    version = dind._run(  # noqa: SLF001
        ["docker", "exec", name, "docker", "version", "--format", "{{.Server.Version}}"],
        timeout_s=30,
    )
    info = dind._run(  # noqa: SLF001
        ["docker", "exec", name, "docker", "info", "--format", "{{json .}}"],
        timeout_s=30,
    )
    socket_gid = dind._run(  # noqa: SLF001
        ["docker", "exec", name, "stat", "-c", "%g", "/var/run/docker.sock"],
        timeout_s=30,
    )
    try:
        metadata = json.loads(info.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v85 provider DinD metadata is malformed") from exc
    if (
        version.returncode != 0
        or version.stdout.decode().strip() != manifest.dind_server_version
        or info.returncode != 0
        or not isinstance(metadata, dict)
        or metadata.get("Driver") != manifest.dind_storage_driver
        or metadata.get("DefaultRuntime") != manifest.dind_default_runtime
        or socket_gid.stdout.decode().strip() != str(os.getgid())
    ):
        raise ConfigurationError("v85 provider DinD controls differ from policy")
    _validate_outer_provider_sidecar(name, manifest, root=root)
    return metadata


def _validate_outer_provider_sidecar(
    name: str,
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    *,
    root: Path,
) -> None:
    value = dind._inspect("container", name)  # noqa: SLF001
    host = value.get("HostConfig")
    config = value.get("Config")
    mounts = value.get("Mounts")
    networks = (value.get("NetworkSettings") or {}).get("Networks")
    if not isinstance(host, dict) or not isinstance(config, dict) or not isinstance(mounts, list):
        raise ConfigurationError("v85 outer sidecar metadata is malformed")
    destinations = {item.get("Destination"): item for item in mounts if isinstance(item, dict)}
    required = {
        "/var/lib/docker": (manifest.dind_data_volume, True),
        "/var/run": (manifest.dind_socket_volume, True),
        "/verigym-host-sentinel": (str((V83_ROOT / "dind-empty-home").resolve()), False),
        str(_REPOSITORY.resolve(strict=True)): (str(_REPOSITORY.resolve(strict=True)), False),
        str(V83_ROOT.resolve(strict=True)): (str(V83_ROOT.resolve(strict=True)), False),
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
        or host.get("NetworkMode") != manifest.provider_outer_network
        or host.get("PortBindings") not in (None, {})
        or not isinstance(networks, dict)
        or set(networks) != {manifest.provider_outer_network}
        or not isinstance(labels, dict)
        or labels.get("verigym.owner") != dind._DIND_OWNER  # noqa: SLF001
        or labels.get("verigym.role") != "provider-daemon"
        or not isinstance(command, list)
        or "--storage-driver=vfs" not in command
        or "--bridge=none" in command
        or "--iptables=false" in command
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
            for name in _environment_names(config.get("Env"))
        )
    ):
        raise ConfigurationError("v85 outer provider sidecar violates its isolation contract")


def _create_inner_provider_network(
    dind_name: str,
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
) -> None:
    existing = dind._inner(  # noqa: SLF001
        ["network", "inspect", manifest.provider_inner_network],
        container=dind_name,
        timeout_s=30,
    )
    if existing.returncode == 0:
        raise ConfigurationError("v85 inner provider network already exists")
    created = dind._inner(  # noqa: SLF001
        ["network", "create", "--driver", "bridge", manifest.provider_inner_network],
        container=dind_name,
        timeout_s=30,
    )
    if created.returncode != 0 or not created.stdout.strip():
        raise ConfigurationError("v85 inner provider network creation failed")


def _network_receipt(
    dind_name: str,
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
) -> dict[str, Any]:
    inspected = dind._inner(  # noqa: SLF001
        ["network", "inspect", manifest.provider_inner_network, "--format", "{{json .}}"],
        container=dind_name,
        timeout_s=30,
    )
    try:
        value = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v85 inner provider network metadata is malformed") from exc
    if (
        inspected.returncode != 0
        or not isinstance(value, dict)
        or value.get("Name") != manifest.provider_inner_network
        or value.get("Driver") != "bridge"
        or value.get("Internal") is not False
        or value.get("Scope") != "local"
    ):
        raise ConfigurationError("v85 inner provider network differs from policy")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v85_provider_network_receipt_v1",
        "identity": IDENTITY,
        "outer_network": manifest.provider_outer_network,
        "outer_network_driver": "bridge",
        "outer_network_internal": False,
        "inner_network": manifest.provider_inner_network,
        "inner_network_driver": "bridge",
        "inner_network_internal": False,
        "task_network": "none",
        "verifier_network": "none",
        "provider_values_persisted": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _remove_inner_provider_network(
    dind_name: str,
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
) -> None:
    removed = dind._inner(  # noqa: SLF001
        ["network", "rm", manifest.provider_inner_network],
        container=dind_name,
        timeout_s=30,
    )
    inspected = dind._inner(  # noqa: SLF001
        ["network", "inspect", manifest.provider_inner_network],
        container=dind_name,
        timeout_s=30,
    )
    if removed.returncode != 0 or inspected.returncode == 0:
        raise ConfigurationError("v85 inner provider network cleanup failed")


def _provider_runtime_receipt(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
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
        raise ConfigurationError("v85 /data2 DinD runtime identity changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v85_provider_dind_runtime_receipt_v1",
        "identity": IDENTITY,
        "dind_image_id": manifest.dind_image_id,
        "storage_driver": metadata.get("Driver"),
        "default_runtime": metadata.get("DefaultRuntime"),
        "docker_root_dir": metadata.get("DockerRootDir"),
        "data_volume": manifest.dind_data_volume,
        "data_backing": manifest.dind_data_backing,
        "host_and_inner_data_root_identity": expected_identity,
        "host_and_inner_data_root_same_inode": True,
        "outer_network": manifest.provider_outer_network,
        "inner_bridge_enabled_for_provider_controller_only": True,
        "host_docker_root_used_for_task_layers": False,
        "v83_data_volume_reopen_count": 1,
        "provider_values_persisted": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _validate_inner_inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
) -> None:
    dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
    images = dind._inner(  # noqa: SLF001
        ["image", "ls", "--all", "--no-trunc", "--format", "{{.ID}}"],
        container=dind_name,
        timeout_s=30,
    )
    observed = set(images.stdout.decode().splitlines())
    required = {
        HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        manifest.controller_image_id,
        *(item.command_image for item in manifest.schedule),
        *(item.official_verifier_image for item in manifest.schedule),
    }
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
        controller_value = json.loads(controller.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v85 inner controller metadata is malformed") from exc
    if (
        images.returncode != 0
        or any(_DIGEST.fullmatch(item) is None for item in observed)
        or not required.issubset(observed)
        or controller.returncode != 0
        or controller_value.get("Id") != manifest.controller_image_id
        or controller_value.get("RepoTags") != [manifest.controller_image_tag]
        or controller_value.get("RepoDigests") != []
        or network.returncode == 0
    ):
        raise ConfigurationError("v85 inner image or network inventory differs from policy")


@contextlib.contextmanager
def _nested_runtime(socket_path: Path) -> Iterator[None]:
    if socket_path.is_symlink():
        raise ConfigurationError("v85 nested Docker socket path is unsafe")
    metadata = socket_path.stat()
    if not stat.S_ISSOCK(metadata.st_mode):
        raise ConfigurationError("v85 nested Docker socket is unavailable")
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


def _zero_provider_preflight(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    *,
    locks: Mapping[str, HweCommandImageLock],
    root: Path,
    dind_name: str,
) -> dict[str, Any]:
    completed: list[str] = []
    for binding in manifest.schedule:
        stage = f"runtime_pr_{binding.pr_number}"
        runtime = DockerRuntime(_runtime_config(locks[binding.task_id]))
        try:
            runtime.prepare(f"v85-preflight-pr-{binding.pr_number}")
        finally:
            runtime.close()
        completed.append(stage)

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
            "controller_image_source_receipt_hash": manifest.v83_controller_receipt_hash,
            "whole_episode_retries": 0,
        },
        task_wall_time_s=300,
    )
    result = run_harness_helper(
        settings,
        mode="initialize",
        prompt="",
        system_prompt="VeriGym v85 credential-bearing controller initialization preflight.",
        session_id="v85-zero-provider-preflight",
        session_root=session_root,
        broker_root=broker_root,
    )
    if (
        result.events
        or result.provider_request_started
        or result.finish_reason is not None
        or result.final_response
        or result.format_repairs
        or result.run_interval_count != 0
        or (session_root / "provider-request-started-v1.json").exists()
    ):
        raise ConfigurationError("v85 harness initialization crossed the provider boundary")
    dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
    provider_scan = _scan_provider_values(root)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v85_zero_provider_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "completed_stages": [*completed, "harness_initialize"],
        "task_runtime_count": len(completed),
        "harness_configuration_fingerprint": settings.configuration_fingerprint,
        "controller_image_id": settings.controller_image_id,
        "controller_image_provenance": settings.controller_image_provenance,
        "controller_image_source_receipt_hash": settings.controller_image_source_receipt_hash,
        "provider_episode_count": 0,
        "provider_call_count": 0,
        "provider_request_started": False,
        "provider_values_persisted_or_hashed": False,
        "provider_value_scan": provider_scan,
        "raw_exception_persisted": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _runtime_config(lock: HweCommandImageLock) -> DockerRuntimeConfig:
    runtime_user = f"{os.getuid()}:{os.getgid()}"
    if lock.source_whiteout_path == "/home/ibex":
        runtime_role = "hwe-ibex-command"
        verifier_label = "org.verigym.ibex.verifier_base_image_id"
    elif lock.source_whiteout_path == "/home/cva6":
        runtime_role = "hwe-cva6-command"
        verifier_label = "org.verigym.cva6.verifier_base_image_id"
    else:  # pragma: no cover - rejected by HweCommandImageLock
        raise ConfigurationError("v85 command-image repository role changed")
    labels = {
        "org.verigym.runtime.role": runtime_role,
        "org.verigym.collection.profile": lock.collection_profile_id,
        "org.verigym.tool.contract": lock.tool_contract_id,
        "org.verigym.command.protocol": lock.command_protocol,
        "org.verigym.command.rg.version": lock.rg_version,
        "org.verigym.command.rg.sha256": lock.rg_sha256,
        "org.verigym.command.rg.release_archive.sha256": lock.rg_release_archive_sha256,
        "org.verigym.hwe.task_id": lock.task_id,
        verifier_label: lock.verifier_base_image_id,
        "org.verigym.codex.present": "absent",
        "org.verigym.provider_credentials": "absent",
        "org.verigym.hidden_assets": "absent",
        "org.verigym.reference_patch": "absent",
        "org.verigym.verifier_payload": "absent",
    }
    return DockerRuntimeConfig(
        image=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        expected_image_id=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        pull_policy="never",
        network_mode="none",
        run_as_user=runtime_user,
        memory_bytes=16 * 1024**3,
        cpus=4,
        pids_limit=4096,
        max_command_time_s=900,
        command_image=DockerCommandImageRuntimeConfig(
            image=lock.derived_command_image_id,
            expected_image_id=lock.derived_command_image_id,
            expected_rg_version=lock.rg_version,
            expected_rg_sha256=lock.rg_sha256,
            protocol=lock.command_protocol,
            execution_backend=COMMAND_EXECUTION_BACKEND,
            required_image_labels=labels,
            run_as_user=runtime_user,
            memory_bytes=16 * 1024**3,
            cpus=4,
            pids_limit=4096,
            max_command_time_s=3600,
            max_output_bytes=32 * 1024 * 1024,
        ),
    )


def _execute_one(
    *,
    service: VeriGym,
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    binding: DeepSeekHarnessV85TaskBinding,
    lock: HweCommandImageLock,
    source_root: Path,
    tokenizer: QwenDecisionExampleTokenizer,
    root: Path,
) -> dict[str, Any]:
    task_root = root / "tasks" / f"pr-{binding.pr_number}"
    task_root.mkdir(mode=0o700)
    runs_root = task_root / "runs"
    runs_root.mkdir(mode=0o700)
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(binding.task_id, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != binding.task_hash
        or task.source.content_hash != binding.source_hash
    ):
        raise ConfigurationError("v85 task/source binding changed before provider execution")
    episode_id = f"official-{binding.repository}-pr{binding.pr_number}-s502-v85"
    started = time.monotonic()
    result = service.run(
        RunConfig(
            task_id=binding.task_id,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=binding.task_hash,
            expected_source_hash=binding.source_hash,
            mode=InteractionMode.AGENT,
            agent="deepseek-harness-hwe-agent-v4",
            agent_options={
                "model_id": DEEPSEEK_HARNESS_MODEL,
                "max_process_time_s": 3600,
                "max_output_bytes": 32 * 1024 * 1024,
                "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                "command_image_lock_hash": lock.lock_hash,
                "controller_image_id": manifest.controller_image_id,
                "controller_image_offline_load": True,
                "controller_image_source_receipt_hash": manifest.v83_controller_receipt_hash,
                "whole_episode_retries": 0,
            },
            runtime="docker",
            docker_config=_runtime_config(lock),
            seed=manifest.seed,
            sample_index=manifest.sample_index,
            output=runs_root,
            run_id=episode_id,
            experiment_id=IDENTITY,
            plan_item_id=episode_id,
            system_id="deepseek-harness-hwe-native-shell-v4",
            base_seed=manifest.seed,
        )
    )
    scorecard = result.scorecard
    run_dir = Path(result.run_dir).resolve(strict=True)
    if run_dir.is_symlink() or not run_dir.is_relative_to(runs_root.resolve(strict=True)):
        raise ConfigurationError("v85 run directory escaped its task output")

    marker, marker_valid = _provider_marker_state(task_root)
    infrastructure_valid = not v67._base._infrastructure_invalid(scorecard)  # noqa: SLF001
    if marker != "started_valid":
        infrastructure_valid = False
    evidence_root = run_dir / "artifacts/deepseek_harness"
    evidence: dict[str, Any] | None = None
    transcript: dict[str, Any] | None = None
    protocol_valid = False
    try:
        evidence = _load_json(evidence_root / "collection_evidence.json")
        v67._validate_collection_evidence(evidence)  # noqa: SLF001
        transcript = validate_deepseek_harness_transcript_v3(
            _load_json(evidence_root / "deepseek_harness_teacher_transcript_v3.json")
        )
        protocol_valid = infrastructure_valid and marker_valid
    except (OSError, KeyError, TypeError, ValueError, ConfigurationError):
        evidence = None
        transcript = None

    first_modification = _first_effective_modification(transcript)
    records: list[dict[str, Any]] = []
    dry_runs: list[dict[str, Any]] = []
    trajectory_materialization_error: str | None = None
    if protocol_valid and transcript is not None and first_modification is not None:
        try:
            records, dry_runs = _materialize_exact_records(
                transcript,
                binding=binding,
                scorecard=scorecard,
                episode_id=episode_id,
                tokenizer=tokenizer,
            )
        except (KeyError, TypeError, ValueError) as exc:
            trajectory_materialization_error = type(exc).__name__
    record_root: Path | None = None
    if records:
        record_root = root / "trajectory-records" / episode_id
        record_root.mkdir(mode=0o700)
        _atomic_jsonl(record_root / "decisions.jsonl", records)
        atomic_dump_json(
            record_root / "loader-dry-run.json",
            _loader_receipt(dry_runs),
        )

    scan_roots = [path for path in (evidence_root, record_root) if path is not None]
    if not scan_roots:
        scan_root = task_root / "empty-security-scan-root"
        scan_root.mkdir(mode=0o700)
        scan_roots = [scan_root]
    security_report = scan_artifact_roots(
        scan_roots,
        report_id=f"deepseek-harness-hwe-v85-{episode_id}",
        proxy_values=_provider_values(),
        forbidden_host_roots=(
            str(source_root),
            str(_REPOSITORY.resolve(strict=True)),
            str(DEEPSEEK_HARNESS_SOURCE_ROOT.resolve(strict=True)),
            str(TOKENIZER_ROOT.resolve(strict=True)),
        ),
    )
    atomic_dump_json(root / "security-scans" / f"{episode_id}.json", security_report)
    security_valid = security_report.gate == "pass" and marker not in {"invalid", "unreadable"}
    if security_valid:
        require_security_scan_pass(security_report)
    provider_scan = _scan_provider_values(root)
    security_valid = security_valid and provider_scan["passed"] is True

    provider_calls, provider_input, provider_output, provider_total = _provider_accounting(
        scorecard, evidence, marker
    )
    exact_64k = bool(records) and all(int(item["token_count"]) <= 65_536 for item in records)
    trajectory_eligible = bool(
        protocol_valid
        and records
        and first_modification is not None
        and infrastructure_valid
        and security_valid
        and exact_64k
    )
    sft_admitted = bool(scorecard.resolved and trajectory_eligible)
    candidate_root: Path | None = None
    if sft_admitted:
        candidate_root = root / "candidate-datasets" / episode_id
        candidate_root.mkdir(mode=0o700)
        _atomic_jsonl(candidate_root / "train.jsonl", records)
        atomic_dump_json(
            candidate_root / "dataset-manifest.json",
            _dataset_receipt(binding, transcript, records),
        )
        _assert_no_provider_values(candidate_root)
    planes = HweAdmissionPlanes(
        benchmark_verifier_pass=scorecard.resolved,
        agent_protocol_valid=protocol_valid,
        trajectory_eligible=trajectory_eligible,
        infrastructure_valid=infrastructure_valid,
        security_valid=security_valid,
        sft_admitted=sft_admitted,
    )
    outcome = _attempt_outcome(
        scorecard_resolved=scorecard.resolved,
        infrastructure_valid=infrastructure_valid,
        security_valid=security_valid,
        protocol_valid=protocol_valid,
        first_modification=first_modification,
        evidence=evidence,
        trajectory_records_valid=bool(records),
    )
    reproducibility = scorecard.reproducibility
    detail_base = {
        "schema_version": "1.0",
        "format_id": ATTEMPT_FORMAT,
        "identity": IDENTITY,
        "episode_id": episode_id,
        "task_id": binding.task_id,
        "repository": binding.repository,
        "pr_number": binding.pr_number,
        "seed": binding.seed,
        "sample_index": binding.sample_index,
        "task_hash": binding.task_hash,
        "source_hash": binding.source_hash,
        "agent_toolchain_id": binding.agent_toolchain_id,
        "agent_diagnostic_result_role": "agent_only_non_authoritative",
        "official_verifier_image": binding.official_verifier_image,
        "official_verifier_executed": bool(
            scorecard.verifier_results and _SHA256.fullmatch(reproducibility.verifier_hash)
        ),
        "official_verifier_result_role": "benchmark_authoritative",
        "official_verifier_receipt_hash": reproducibility.verifier_hash,
        "agent_diagnostic_receipt_hash": lock.lock_hash,
        "provider_marker": marker,
        "provider_marker_valid": marker_valid,
        "provider_call_count": provider_calls,
        "provider_input_tokens": provider_input,
        "provider_output_tokens": provider_output,
        "provider_total_tokens": provider_total,
        "provider_budget_valid": (
            provider_calls <= manifest.max_provider_calls_per_task
            and provider_total <= manifest.max_provider_tokens_per_task
        ),
        "first_effective_modification_action": first_modification,
        "outcome": outcome,
        "planes": planes.model_dump(mode="json"),
        "exact_64k_eligible": exact_64k and trajectory_eligible,
        "maximum_decision_tokens": (
            max(int(item["token_count"]) for item in records) if records else None
        ),
        "decision_record_count": len(records),
        "trajectory_materialization_error_type": trajectory_materialization_error,
        "truncation_applied": False,
        "decision_only_loss_mask": bool(records),
        "transcript_hash": transcript.get("transcript_hash") if transcript else None,
        "assistant_decision_count": (
            transcript.get("assistant_decision_count") if transcript else None
        ),
        "supervised_decision_count": (
            transcript.get("supervised_decision_count") if transcript else None
        ),
        "public_rationale_supervised": any(
            item.get("public_assistant_text_exported") is True for item in records
        ),
        "sibling_calls_preserved": any(int(item["tool_action_count"]) > 1 for item in records),
        "failed_decisions_supervised": False,
        "content_only_recovery_supervised": False,
        "security_scan_hash": security_report.report_hash,
        "provider_value_scan": provider_scan,
        "runtime_command_image": lock.derived_command_image_id,
        "command_execution_backend": COMMAND_EXECUTION_BACKEND,
        "task_network": "none",
        "verifier_network": "none",
        "controller_network": manifest.provider_inner_network,
        "wall_seconds": time.monotonic() - started,
        "run_hash": content_hash(
            {"episode_id": episode_id, "scorecard": scorecard.model_dump(mode="json")}
        ),
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "credential_values_persisted_or_hashed": False,
        **_closed_training_flags(),
    }
    detail = {**detail_base, "attempt_hash": content_hash(detail_base)}
    require_toolchain_verifier_binding(
        attempt=detail,
        expected_agent_toolchain_id=binding.agent_toolchain_id,
        expected_official_verifier_image=binding.official_verifier_image,
    )
    _state_attempt(detail)
    return detail


def _materialize_exact_records(
    transcript: Mapping[str, Any],
    *,
    binding: DeepSeekHarnessV85TaskBinding,
    scorecard: Any,
    episode_id: str,
    tokenizer: QwenDecisionExampleTokenizer,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validated = validate_deepseek_harness_transcript_v3(transcript)
    messages = validated["messages"]
    tools = validated["tools"]
    reproducibility = scorecard.reproducibility
    sample_id = content_hash(
        {
            "identity": IDENTITY,
            "episode_id": episode_id,
            "scorecard": scorecard.model_dump(mode="json"),
        }
    )
    records: list[dict[str, Any]] = []
    dry_runs: list[dict[str, Any]] = []
    for decision in validated["assistant_decisions"]:
        if decision["supervised_target"] is not True:
            continue
        target_index = int(decision["message_index"])
        target = copy.deepcopy(messages[target_index])
        input_messages = copy.deepcopy(messages[:target_index])
        receipt = exact_decision_token_receipt(
            tokenizer=tokenizer,
            tools=tools,
            input_messages=input_messages,
            target_message=target,
        )
        if int(receipt["token_count"]) > 65_536:
            raise ValueError("v85 decision exceeds exact 64K")
        base = {
            "schema_version": "1.0",
            "format_id": DECISION_FORMAT,
            "sample_id": sample_id,
            "task_id": binding.task_id,
            "task_hash": binding.task_hash,
            "source_hash": binding.source_hash,
            "candidate_hash": reproducibility.candidate_hash,
            "verifier_hash": reproducibility.verifier_hash,
            "transcript_hash": validated["transcript_hash"],
            "decision_index": decision["decision_index"],
            "target_message_index": target_index,
            "call_ids": decision["call_ids"],
            "action_names": decision["action_names"],
            "tool_action_count": len(decision["call_ids"]),
            "trajectory_assistant_decision_count": validated["assistant_decision_count"],
            "trajectory_accepted_tool_action_count": validated["accepted_tool_action_count"],
            "trajectory_masked_policy_error_decision_count": validated[
                "masked_policy_error_decision_count"
            ],
            "trajectory_masked_format_error_decision_count": validated[
                "masked_format_error_decision_count"
            ],
            "trajectory_format_repair_count": validated["format_repair_count"],
            "tools": copy.deepcopy(tools),
            "tool_schema_hash": content_hash(tools),
            "input_messages": input_messages,
            "target_message": target,
            **receipt,
            "max_length": 65_536,
            "truncation": "error",
            "eligible": True,
            "supervised_target_kind": "complete_assistant_decision",
            "supervised_roles": ["assistant"],
            "input_loss_masked": True,
            "failed_tool_decisions_loss_masked": True,
            "format_error_decisions_loss_masked": True,
            "exact_model_visible_context": True,
            "context_transformed_after_collection": False,
            "nap_required": False,
            "verifier_resolved": scorecard.resolved,
            "infrastructure_valid": True,
            "candidate_sft_eligible": scorecard.resolved,
            "public_assistant_text_exported": bool(target.get("content")),
            "raw_provider_events_exported": False,
            "raw_observations_exported": False,
            "private_reasoning_exported": False,
            "hidden_assets_exported": False,
            "reference_solutions_exported": False,
            "credential_values_exported": False,
            "raw_host_paths_exported": False,
        }
        record = {**base, "record_hash": content_hash(base)}
        dry_run = dry_run_decision_record_v4(record, tokenizer=tokenizer)
        records.append(record)
        dry_runs.append(dry_run)
    return records, dry_runs


def _loader_receipt(dry_runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v85_qwen_loader_dry_run_v1",
        "record_count": len(dry_runs),
        "record_hashes": [str(item["record_hash"]) for item in dry_runs],
        "maximum_token_count": max(int(item["token_count"]) for item in dry_runs),
        "overlength_record_count": 0,
        "truncation_applied": False,
        "decision_only_loss_mask": True,
        "records": [dict(copy.deepcopy(item)) for item in dry_runs],
    }
    return {**base, "dry_run_hash": content_hash(base)}


def _dataset_receipt(
    binding: DeepSeekHarnessV85TaskBinding,
    transcript: Mapping[str, Any] | None,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not records or transcript is None:
        raise ConfigurationError("v85 candidate dataset cannot be empty")
    base = {
        "schema_version": "1.0",
        "format_id": DATASET_FORMAT,
        "identity": IDENTITY,
        "task_ids": [binding.task_id],
        "record_count": len(records),
        "record_hashes": [str(item["record_hash"]) for item in records],
        "transcript_hash": transcript["transcript_hash"],
        "supervised_decision_count": len(records),
        "supervised_tool_action_count": sum(int(item["tool_action_count"]) for item in records),
        "max_observed_token_count": max(int(item["token_count"]) for item in records),
        "max_length": 65_536,
        "truncation": "error",
        "truncation_applied": False,
        "exact_token_receipts": True,
        "decision_only_loss_mask": True,
        "failed_decisions_supervised": False,
        "content_only_recovery_supervised": False,
        "loader_ready": True,
        **_closed_training_flags(),
    }
    return {**base, "dataset_hash": content_hash(base)}


def _first_effective_modification(transcript: Mapping[str, Any] | None) -> int | None:
    if transcript is None:
        return None
    events = transcript.get("normalized_events")
    if not isinstance(events, list):
        return None
    for ordinal, event in enumerate(events, start=1):
        if isinstance(event, Mapping) and event.get("changed_paths"):
            return ordinal
    return None


def _attempt_outcome(
    *,
    scorecard_resolved: bool,
    infrastructure_valid: bool,
    security_valid: bool,
    protocol_valid: bool,
    first_modification: int | None,
    evidence: Mapping[str, Any] | None,
    trajectory_records_valid: bool,
) -> str:
    if not infrastructure_valid:
        return "infrastructure_failure"
    if not security_valid:
        return "security_failure"
    progress = evidence.get("progress_receipt") if isinstance(evidence, Mapping) else None
    if isinstance(progress, Mapping) and progress.get("no_progress_terminated") is True:
        return "no_progress"
    if not protocol_valid:
        return "trajectory_structure_failure"
    if first_modification is None:
        return "no_effective_modification"
    if not trajectory_records_valid:
        return "trajectory_structure_failure"
    if not scorecard_resolved:
        return "verifier_rejection"
    return "passed"


def _provider_accounting(
    scorecard: Any,
    evidence: Mapping[str, Any] | None,
    marker: str,
) -> tuple[int, int, int, int]:
    efficiency = scorecard.efficiency
    calls = efficiency.external_model_call_count
    input_tokens = efficiency.external_input_tokens
    output_tokens = efficiency.external_output_tokens
    total_tokens = efficiency.external_total_tokens
    if isinstance(evidence, Mapping):
        calls = evidence.get("observed_provider_calls", calls)
        input_tokens = evidence.get("observed_provider_input_tokens", input_tokens)
        output_tokens = evidence.get("observed_provider_output_tokens", output_tokens)
        total_tokens = evidence.get("observed_provider_total_tokens", total_tokens)
    values = [calls, input_tokens, output_tokens, total_tokens]
    normalized = [value if isinstance(value, int) and value >= 0 else 0 for value in values]
    if marker != "not_started" and normalized[0] == 0:
        normalized[0] = 1
    if normalized[3] == 0 and normalized[1] + normalized[2] > 0:
        normalized[3] = normalized[1] + normalized[2]
    return cast(tuple[int, int, int, int], tuple(normalized))


def _provider_marker_state(task_root: Path) -> tuple[ProviderMarker, bool]:
    try:
        observed, valid = v67._provider_boundary_state(task_root)  # noqa: SLF001
    except (OSError, TypeError, ValueError, ConfigurationError):
        return "unreadable", False
    if observed and not valid:
        return "invalid", False
    return ("started_valid", True) if observed else ("not_started", True)


def _provider_marker_for_binding(
    root: Path,
    binding: DeepSeekHarnessV85TaskBinding,
) -> tuple[ProviderMarker, bool]:
    task_root = root / "tasks" / f"pr-{binding.pr_number}"
    if not task_root.exists():
        return "not_started", True
    if task_root.is_symlink() or not task_root.is_dir():
        return "unreadable", False
    return _provider_marker_state(task_root)


def _state_attempt(detail: Mapping[str, Any]) -> DeepSeekHarnessMatrixAttempt:
    return DeepSeekHarnessMatrixAttempt(
        task_id=str(detail["task_id"]),
        repository=str(detail["repository"]),  # type: ignore[arg-type]
        agent_toolchain_id=str(detail["agent_toolchain_id"]),
        official_verifier_image=str(detail["official_verifier_image"]),
        provider_marker=str(detail["provider_marker"]),  # type: ignore[arg-type]
        provider_call_count=int(detail["provider_call_count"]),
        provider_total_tokens=int(detail["provider_total_tokens"]),
        first_effective_modification_action=detail.get("first_effective_modification_action"),
        outcome=str(detail["outcome"]),  # type: ignore[arg-type]
        planes=HweAdmissionPlanes.model_validate(detail["planes"]),
        exact_64k_eligible=bool(detail["exact_64k_eligible"]),
        maximum_decision_tokens=detail.get("maximum_decision_tokens"),
        truncation_applied=False,
        decision_only_loss_mask=bool(detail["decision_only_loss_mask"]),
    )


def _exception_attempt(
    binding: DeepSeekHarnessV85TaskBinding,
    *,
    marker: ProviderMarker,
    exception: Exception,
) -> dict[str, Any]:
    planes = HweAdmissionPlanes(
        benchmark_verifier_pass=False,
        agent_protocol_valid=False,
        trajectory_eligible=False,
        infrastructure_valid=False,
        security_valid=False,
        sft_admitted=False,
    )
    base = {
        "schema_version": "1.0",
        "format_id": ATTEMPT_FORMAT,
        "identity": IDENTITY,
        "episode_id": f"official-{binding.repository}-pr{binding.pr_number}-s502-v85",
        "task_id": binding.task_id,
        "repository": binding.repository,
        "pr_number": binding.pr_number,
        "seed": binding.seed,
        "sample_index": binding.sample_index,
        "agent_toolchain_id": binding.agent_toolchain_id,
        "official_verifier_image": binding.official_verifier_image,
        "provider_marker": marker,
        "provider_call_count": 0 if marker == "not_started" else 1,
        "provider_total_tokens": 0,
        "first_effective_modification_action": None,
        "outcome": "infrastructure_failure",
        "planes": planes.model_dump(mode="json"),
        "exact_64k_eligible": False,
        "maximum_decision_tokens": None,
        "truncation_applied": False,
        "decision_only_loss_mask": False,
        "exception_type": type(exception).__name__,
        "raw_exception_persisted": False,
        "credential_values_persisted_or_hashed": False,
        **_closed_training_flags(),
    }
    detail = {**base, "attempt_hash": content_hash(base)}
    _state_attempt(detail)
    return detail


def _provider_started_in_details_or_runs(
    details: Sequence[Mapping[str, Any]],
    root: Path,
) -> bool:
    if any(item.get("provider_marker") != "not_started" for item in details):
        return True
    tasks = root / "tasks"
    if not tasks.exists():
        return False
    for task_root in tasks.iterdir():
        if not task_root.is_dir() or task_root.is_symlink():
            return True
        marker, _valid = _provider_marker_state(task_root)
        if marker != "not_started":
            return True
    return False


def _clean_inner_resources(dind_name: str) -> None:
    containers = dind._inner(  # noqa: SLF001
        ["container", "ls", "--all", "--quiet"], container=dind_name, timeout_s=30
    )
    volumes = dind._inner(  # noqa: SLF001
        ["volume", "ls", "--quiet"], container=dind_name, timeout_s=30
    )
    if containers.returncode != 0 or volumes.returncode != 0:
        raise ConfigurationError("v85 inner cleanup inventory is unavailable")
    container_ids = containers.stdout.decode().splitlines()
    volume_ids = volumes.stdout.decode().splitlines()
    if container_ids:
        removed = dind._inner(  # noqa: SLF001
            ["rm", "--force", *container_ids], container=dind_name, timeout_s=120
        )
        if removed.returncode != 0:
            raise ConfigurationError("v85 inner task container cleanup failed")
    if volume_ids:
        removed = dind._inner(  # noqa: SLF001
            ["volume", "rm", *volume_ids], container=dind_name, timeout_s=120
        )
        if removed.returncode != 0:
            raise ConfigurationError("v85 inner task volume cleanup failed")


def _best_effort_cleanup(
    *,
    dind_name: str | None,
    inner_network_created: bool,
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    root: Path,
) -> tuple[bool, str | None]:
    try:
        if dind_name is not None:
            existing = dind._run(  # noqa: SLF001
                ["docker", "container", "inspect", dind_name], timeout_s=30
            )
            if existing.returncode == 0:
                _clean_inner_resources(dind_name)
                network = dind._inner(  # noqa: SLF001
                    ["network", "inspect", manifest.provider_inner_network],
                    container=dind_name,
                    timeout_s=30,
                )
                if inner_network_created or network.returncode == 0:
                    _remove_inner_provider_network(dind_name, manifest)
                dind._require_empty_inner_inventory(dind_name)  # noqa: SLF001
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


def _clean_socket_volume(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    dind._bind_backed_volume(  # noqa: SLF001
        manifest.dind_socket_volume,
        owner=dind._DIND_OWNER,  # noqa: SLF001
        role="socket",
        backing=DIND_SOCKET_BACKING,
    )
    name = f"verigym-dind-v85-socket-cleanup-{secrets.token_hex(10)}"
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
        or not dind._remove_volume(manifest.dind_socket_volume)  # noqa: SLF001
    ):
        raise ConfigurationError("v85 socket cleanup failed")
    metadata = DIND_SOCKET_BACKING.stat()
    if (
        next(DIND_SOCKET_BACKING.iterdir(), None) is not None
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
    ):
        raise ConfigurationError("v85 socket backing cleanup was not confirmed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v85_socket_cleanup_receipt_v1",
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


def _final_report(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
    progress: Mapping[str, Any],
    details: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    attempts = [_state_attempt(item) for item in details]
    conclusions = migration_conclusions(attempts)
    state = DeepSeekHarnessMatrixState.model_validate(progress["matrix_state"])
    execution_completed = (
        state.status == "completed"
        and progress.get("status") != "stopped"
        and progress.get("dind_cleanup_confirmed") is True
    )
    candidates = [item.task_id for item in attempts if item.planes.sft_admitted]
    research = [
        item.task_id
        for item in attempts
        if item.planes.trajectory_eligible and not item.planes.sft_admitted
    ]
    base = {
        **dict(copy.deepcopy(progress)),
        "format_id": REPORT_FORMAT,
        "status": (
            "completed_pending_independent_v86_audit"
            if execution_completed
            else "stopped_pending_independent_v86_audit"
        ),
        "matrix_status": state.status,
        "matrix_completed": execution_completed,
        "stop_reason": (
            None
            if execution_completed
            else state.stop_reason or str(progress.get("stop_reason") or "campaign_failure")
        ),
        "attempt_count": len(attempts),
        "provider_episode_count": sum(item.provider_marker != "not_started" for item in attempts),
        "provider_call_count": sum(item.provider_call_count for item in attempts),
        "provider_total_tokens": sum(item.provider_total_tokens for item in attempts),
        "migration_conclusions": conclusions,
        "trajectory_collection_migratable": conclusions["trajectory_collection_migratable"],
        "sft_path_migratable": conclusions["sft_path_migratable"],
        "candidate_sft_task_ids": candidates,
        "research_context_task_ids": research,
        "audit_only_task_ids": [
            item.task_id for item in attempts if item.task_id not in candidates
        ],
        "candidate_sft_import_authorized": False,
        "failed_trajectories_retained_as_audit_context_only": True,
        "requires_independent_v86_audit": True,
        "v83_data_volume_reopen_budget": manifest.v83_data_volume_reopen_budget,
        "benchmark_score_claimed": False,
        "formal_collection_authorized": False,
        "provider_values_persisted_or_hashed": False,
        **_closed_training_flags(),
    }
    return _seal(base)


def _require_opt_in() -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v85 requires a non-root host identity")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v85 requires the default host Docker connection")
    if not os.environ.get(API_KEY_ENV) or not os.environ.get(BASE_URL_ENV):
        raise ConfigurationError("v85 provider environment is incomplete")
    if VERIGYM_DEEPSEEK_HARNESS_VERSION != "0.5.0" or DEEPSEEK_HARNESS_VERSION != "0.1.1-rc.2":
        raise ConfigurationError("v85 Harness integration identity changed")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV85OfficialMatrixManifest,
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
            raise ConfigurationError("v85 required merged path is not tracked")
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
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v84_audit_commit, head],
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
        raise ConfigurationError("v85 requires clean merged origin/main after the v84 gate")
    return head


def _hash_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"v85 file is unsafe: {path.name}")
    return hash_bytes(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON_BYTES:
        raise ConfigurationError(f"v85 JSON input is unsafe: {path.name}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"v85 JSON input is malformed: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"v85 JSON input is not an object: {path.name}")
    return value


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"v85 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_file():
        raise ConfigurationError(f"v85 {label} identity changed")
    return resolved


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"v85 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_dir():
        raise ConfigurationError(f"v85 {label} identity changed")
    return resolved


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink() or path != OUTPUT_ROOT:
        raise ConfigurationError("v85 output identity must be new and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _environment_names(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {
        item.partition("=")[0]
        for item in values
        if isinstance(item, str) and item.partition("=")[0]
    }


def _provider_values() -> tuple[str, str]:
    return os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV]


def _assert_no_provider_values(root: Path) -> tuple[int, int]:
    values = tuple(value.encode() for value in _provider_values())
    files = 0
    bytes_scanned = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("v85 artifact tree contains a symlink")
        if not path.is_file():
            continue
        payload = path.read_bytes()
        files += 1
        bytes_scanned += len(payload)
        if any(value in payload for value in values):
            raise ConfigurationError("provider value reached v85 artifacts")
    return files, bytes_scanned


def _scan_provider_values(root: Path) -> dict[str, Any]:
    files, bytes_scanned = _assert_no_provider_values(root)
    return {
        "passed": True,
        "provider_value_count_scanned": 2,
        "file_count_scanned": files,
        "byte_count_scanned": bytes_scanned,
        "provider_value_hit_count": 0,
        "provider_values_persisted_or_hashed": False,
    }


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
    atomic_dump_json(root / "matrix-progress.json", _seal(value))


def _atomic_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    v67._atomic_jsonl(path, values)  # noqa: SLF001


def main() -> int:
    report = collect(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "matrix_status": report["matrix_status"],
                "attempt_count": report["attempt_count"],
                "trajectory_collection_migratable": report["trajectory_collection_migratable"],
                "sft_path_migratable": report["sft_path_migratable"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report.get("matrix_completed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
