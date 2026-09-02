"""Resumable, zero-provider PR-2728 environment provisioning for OpenHands."""

from __future__ import annotations

import copy
import os
import re
import secrets
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

from . import hwe_v53_materialization as _v53
from . import hwe_v54_materialization as _v54

OPENHANDS_V55_OPT_IN_ENV = "VERIGYM_PROVISION_OPENHANDS_HWE_V55_PR2728_ENVIRONMENT"
OPENHANDS_V55_AUTHORIZATION_FORMAT = (
    "verigym_openhands_hwe_v55_pr2728_environment_provisioning_authorization_v1"
)
OPENHANDS_V55_MANIFEST_FORMAT = "verigym_openhands_hwe_v55_pr2728_environment_manifest_v1"
OPENHANDS_V55_IDENTITY = "openhands-hwe-v55-pr2728-environment-provisioning-v1"
OPENHANDS_V55_ENVIRONMENT_ID = "hwe-cva6-pr2728-linux-amd64-command-environment-v1"
OPENHANDS_V55_PERSISTENT_LAYER_CACHE = _v54.OPENHANDS_V54_PERSISTENT_LAYER_CACHE
OPENHANDS_V55_MAXIMUM_SESSIONS = 3
OPENHANDS_V55_LAYER_MAXIMUM_ATTEMPTS = 3

_HASH = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FAILURE_STAGE = re.compile(r"^layer_[0-9]{3}_attempt_[0-9]{2}$")
_MAXIMUM_STDERR_BYTES = 32 * 1024 * 1024
_V54_FAILURE_BINDING = {
    "identity": "openhands-hwe-v54-v23-canary-materialization-v1",
    "status": "frozen_zero_provider_materialization_failed",
    "failure_stage": "pr2728_image_transfer",
    "failure_type": "_CommandFailure",
    "failure_file_sha256": "0d43725b76d25386b90f380f787d929f77533cfdfa777bdb2fdce6a5d65066f9",
    "failure_receipt_hash": "44ff66090d4559ccb66037b68d3b8742c2fe483fcde1dbef4e693b1f9f1f1013",
    "transfer_error_family": "unknown",
    "transfer_stderr_bytes": 192,
    "transfer_stderr_sha256": "3b1989f565aa82c8afc920e54e89f22692e8bfb6cf59d62e5fcd52ad5f8e5409",
    "verified_layer_count": 15,
    "verified_layer_bytes": 774_127_158,
    "output_published": False,
    "provider_calls": 0,
    "model_process_count": 0,
    "behavior_failure_count": 0,
    "stopped_audit_merge_commit": "e978cc503e232c8d86c244619d211157f9e288be",
    "post_merge_main_run_id": 33_590_506_108,
    "post_merge_main_all_eight_classes_passed": True,
}
_V55_PROVISIONING_INPUTS = copy.deepcopy(_v53._V53_MATERIALIZATION_INPUTS["transfer"])
_V55_PROVISIONING_INPUTS["per_layer_runner_retries"] = OPENHANDS_V55_LAYER_MAXIMUM_ATTEMPTS - 1

ProvisionStage = Callable[[Path], Mapping[str, Any]]


def run_v55_environment_provisioning(
    *,
    authorization: Mapping[str, Any],
    session_index: int,
    main_commit: str,
    provision: ProvisionStage,
    output: Path,
) -> dict[str, Any]:
    """Provision one immutable environment without allocating a provider task identity."""

    if os.environ.get(OPENHANDS_V55_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V55_OPT_IN_ENV}=1 is required")
    approved = validate_v55_authorization(authorization)
    _validate_session_index(session_index)
    if not _COMMIT.fullmatch(main_commit):
        raise ConfigurationError("OpenHands v55 merged main commit is invalid")
    if output.exists() or output.is_symlink():
        raise ConfigurationError("OpenHands v55 environment manifest already exists")
    parent = output.parent.resolve(strict=True)
    staging = parent / f".{output.name}.v55-staging-{os.getpid()}-{secrets.token_hex(6)}"
    staging.mkdir(mode=0o700)
    try:
        transfer = _validate_transfer_receipt(provision(staging))
        manifest = build_v55_environment_manifest(
            authorization=approved,
            transfer=transfer,
            session_index=session_index,
            main_commit=main_commit,
        )
        atomic_dump_json(output, manifest)
        _fsync_directory(parent)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def build_v55_environment_manifest(
    *,
    authorization: Mapping[str, Any],
    transfer: Mapping[str, Any],
    session_index: int,
    main_commit: str,
) -> dict[str, Any]:
    """Build the atomic handoff from provisioning to later public qualification."""

    approved = validate_v55_authorization(authorization)
    receipt = _validate_transfer_receipt(transfer)
    _validate_session_index(session_index)
    if not _COMMIT.fullmatch(main_commit):
        raise ConfigurationError("OpenHands v55 merged main commit is invalid")
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V55_MANIFEST_FORMAT,
        "status": "environment_provisioned_pending_public_qualification",
        "identity": OPENHANDS_V55_IDENTITY,
        "environment_id": OPENHANDS_V55_ENVIRONMENT_ID,
        "task_id": approved["task_id"],
        "authorization_hash": approved["authorization_hash"],
        "session_index": session_index,
        "merged_main_commit": main_commit,
        "transfer_receipt": copy.deepcopy(receipt),
        "provider_task_identity_allocated": False,
        "benchmark_task_consumed": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "public_qualification_completed": False,
        "security_scan_completed": False,
        "command_image_lock_published": False,
        "canary_contract_published": False,
        "canary_executed": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    return {**base, "manifest_hash": content_hash(base)}


def validate_v55_environment_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _validated_hash(value, "manifest_hash", "environment manifest")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V55_MANIFEST_FORMAT
        or result.get("status") != "environment_provisioned_pending_public_qualification"
        or result.get("identity") != OPENHANDS_V55_IDENTITY
        or result.get("environment_id") != OPENHANDS_V55_ENVIRONMENT_ID
        or result.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728"
        or result.get("provider_task_identity_allocated") is not False
        or result.get("benchmark_task_consumed") is not False
        or result.get("provider_calls") != 0
        or result.get("model_process_count") != 0
        or any(
            result.get(name) is not False
            for name in (
                "public_qualification_completed",
                "security_scan_completed",
                "command_image_lock_published",
                "canary_contract_published",
                "canary_executed",
                "formal_collection_allowed",
                "formal_collection_started",
                "collection_started",
                "training_started",
                "production_training_ready",
            )
        )
        or not isinstance(result.get("authorization_hash"), str)
        or not _HASH.fullmatch(str(result["authorization_hash"]))
        or not isinstance(result.get("merged_main_commit"), str)
        or not _COMMIT.fullmatch(str(result["merged_main_commit"]))
    ):
        raise ConfigurationError("OpenHands v55 environment manifest policy changed")
    _validate_session_index(result.get("session_index"))
    _validate_transfer_receipt(result.get("transfer_receipt"))
    return result


def validate_v55_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _validated_hash(value, "authorization_hash", "authorization")
    expected_controls = {
        "environment_provisioning_separate_from_qualification": True,
        "provider_identity_not_allocated": True,
        "persistent_content_addressed_layer_cache": True,
        "task_specific_download_staging": True,
        "linux_amd64_manifest_frozen": True,
        "per_layer_digest_and_size_before_atomic_rename": True,
        "retry_only_allowlisted_transport_failures": True,
        "bounded_layer_attempts": OPENHANDS_V55_LAYER_MAXIMUM_ATTEMPTS,
        "bounded_provisioning_sessions": OPENHANDS_V55_MAXIMUM_SESSIONS,
        "raw_stderr_temporary_only": True,
        "redacted_diagnostic_only": True,
        "assembly_uses_complete_verified_cache": True,
        "single_temporary_archive_cleanup": True,
        "atomic_environment_manifest_publication": True,
        "provider_retry_count": 0,
    }
    expected_actions = {
        "resolve_pr2728_platform_manifest": True,
        "download_pr2728_cache_misses": True,
        "assemble_pr2728_image": True,
        "publish_environment_manifest": True,
        "qualify_pr2728_public_task": False,
        "build_and_run_v2_scanner": False,
        "build_pr2728_command_image_lock": False,
        "materialize_v23_canary_contract": False,
        "invoke_provider": False,
        "run_canary": False,
        "start_formal_collection": False,
        "start_training": False,
    }
    forbidden_provider_identity_fields = {"model", "seed", "sample_index", "campaign_id"}
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V55_AUTHORIZATION_FORMAT
        or result.get("status") != "authorized_pending_environment_provisioning"
        or result.get("identity") != OPENHANDS_V55_IDENTITY
        or result.get("environment_id") != OPENHANDS_V55_ENVIRONMENT_ID
        or result.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728"
        or result.get("predecessor_v54") != _V54_FAILURE_BINDING
        or result.get("persistent_layer_cache") != str(OPENHANDS_V55_PERSISTENT_LAYER_CACHE)
        or result.get("provisioning_inputs") != _V55_PROVISIONING_INPUTS
        or result.get("maximum_provisioning_sessions") != OPENHANDS_V55_MAXIMUM_SESSIONS
        or result.get("layer_maximum_attempts") != OPENHANDS_V55_LAYER_MAXIMUM_ATTEMPTS
        or result.get("required_controls") != expected_controls
        or result.get("authorized_actions") != expected_actions
        or result.get("failure_policy")
        != "append_redacted_session_receipt_and_resume_same_environment_identity"
        or result.get("provider_task_identity_allocated") is not False
        or result.get("benchmark_task_consumed") is not False
        or result.get("provider_calls") != 0
        or result.get("model_process_count") != 0
        or forbidden_provider_identity_fields.intersection(result)
        or any(
            result.get(name) is not False
            for name in (
                "formal_collection_allowed",
                "formal_collection_started",
                "collection_started",
                "training_started",
                "production_training_ready",
            )
        )
    ):
        raise ConfigurationError("OpenHands v55 authorization policy changed")
    return result


def _validate_transfer_receipt(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError("OpenHands v55 transfer receipt is malformed")
    result = copy.deepcopy(dict(value))
    observed = result.pop("receipt_hash", None)
    attempts = result.get("layer_transfer_attempts")
    inventory = result.get("layer_inventory")
    if (
        not isinstance(observed, str)
        or not _HASH.fullmatch(observed)
        or content_hash(result) != observed
        or result.get("format_id") != "verigym_openhands_hwe_v55_pr2728_image_transfer_v2"
        or result.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728"
        or result.get("platform") != "linux/amd64"
        or not isinstance(result.get("manifest_digest"), str)
        or not _DIGEST.fullmatch(str(result["manifest_digest"]))
        or not isinstance(result.get("config_digest"), str)
        or not _DIGEST.fullmatch(str(result["config_digest"]))
        or result.get("verifier_image") != result.get("config_digest")
        or isinstance(result.get("manifest_size"), bool)
        or not isinstance(result.get("manifest_size"), int)
        or result["manifest_size"] <= 0
        or isinstance(result.get("config_size"), bool)
        or not isinstance(result.get("config_size"), int)
        or result["config_size"] <= 0
        or result.get("layer_runner_maximum_attempts") != OPENHANDS_V55_LAYER_MAXIMUM_ATTEMPTS
        or result.get("provider_retry_count") != 0
        or result.get("provider_calls") != 0
        or result.get("model_process_count") != 0
        or result.get("raw_stderr_persisted") is not False
        or result.get("all_layers_verified_before_assembly") is not True
        or result.get("assembly_source") != "verified_content_addressed_cache"
        or result.get("temporary_archive_cleanup_count") != 1
        or not isinstance(inventory, list)
        or not isinstance(attempts, list)
        or not 1 <= len(inventory) == len(attempts) <= 512
    ):
        raise ConfigurationError("OpenHands v55 transfer receipt policy changed")
    assert isinstance(inventory, list)
    assert isinstance(attempts, list)
    attempt_count = _validate_layer_attempts(inventory, attempts)
    if (
        result.get("layer_download_count") != sum(item["cache_hit"] is False for item in inventory)
        or result.get("layer_download_attempt_count") != attempt_count
    ):
        raise ConfigurationError("OpenHands v55 transfer accounting changed")
    return {**result, "receipt_hash": observed}


def _validate_layer_attempts(inventory: list[Any], attempts: list[Any]) -> int:
    total = 0
    for index, (layer, attempt) in enumerate(zip(inventory, attempts, strict=True)):
        if (
            not isinstance(layer, dict)
            or set(layer) != {"digest", "size", "cache_hit"}
            or not isinstance(layer.get("digest"), str)
            or not _DIGEST.fullmatch(layer["digest"])
            or isinstance(layer.get("size"), bool)
            or not isinstance(layer.get("size"), int)
            or layer["size"] <= 0
            or not isinstance(layer.get("cache_hit"), bool)
            or not isinstance(attempt, dict)
            or set(attempt)
            != {"digest", "size", "cache_hit", "attempt_count", "failed_attempts", "completed"}
            or attempt.get("digest") != layer["digest"]
            or attempt.get("size") != layer["size"]
            or attempt.get("cache_hit") is not layer["cache_hit"]
            or attempt.get("completed") is not True
            or isinstance(attempt.get("attempt_count"), bool)
            or not isinstance(attempt.get("attempt_count"), int)
            or not isinstance(attempt.get("failed_attempts"), list)
        ):
            raise ConfigurationError("OpenHands v55 layer attempt identity changed")
        count = attempt["attempt_count"]
        failures = attempt["failed_attempts"]
        if layer["cache_hit"] is True:
            if count != 0 or failures:
                raise ConfigurationError("OpenHands v55 cache-hit attempt accounting changed")
        else:
            if not 1 <= count <= OPENHANDS_V55_LAYER_MAXIMUM_ATTEMPTS or len(failures) != count - 1:
                raise ConfigurationError("OpenHands v55 layer retry accounting changed")
            for failure_index, failure in enumerate(failures, 1):
                _validate_retry_diagnostic(
                    failure,
                    expected_stage=f"layer_{index:03d}_attempt_{failure_index:02d}",
                )
        total += count
    return total


def _validate_retry_diagnostic(value: object, *, expected_stage: str) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("OpenHands v55 retry diagnostic is malformed")
    required = {
        "schema_version",
        "format_id",
        "stage",
        "error_family",
        "reason",
        "retryable",
        "stderr_bytes",
        "stderr_sha256",
        "raw_stderr_persisted",
    }
    expected_families = {
        "dns": "dns",
        "timeout": "timeout",
        "connection_reset": "transport",
        "unexpected_eof": "transport",
        "stream_error": "transport",
        "connection_closed": "transport",
        "connection_refused": "transport",
        "broken_pipe": "transport",
        "http_status": "http_status",
        "staged_size_mismatch": "checksum",
        "staged_checksum_mismatch": "checksum",
    }
    reason = value.get("reason")
    if (
        set(value) not in (required, required | {"http_status"})
        or value.get("schema_version") != "2.0"
        or value.get("format_id") != "verigym_hwe_redacted_transfer_failure_v2"
        or value.get("stage") != expected_stage
        or not _FAILURE_STAGE.fullmatch(expected_stage)
        or reason not in expected_families
        or value.get("error_family") != expected_families[reason]
        or value.get("retryable") is not True
        or isinstance(value.get("stderr_bytes"), bool)
        or not isinstance(value.get("stderr_bytes"), int)
        or not 0 <= value["stderr_bytes"] <= _MAXIMUM_STDERR_BYTES
        or not isinstance(value.get("stderr_sha256"), str)
        or not _HASH.fullmatch(value["stderr_sha256"])
        or value.get("raw_stderr_persisted") is not False
    ):
        raise ConfigurationError("OpenHands v55 retry diagnostic policy changed")
    status = value.get("http_status")
    if reason == "http_status":
        if status not in {408, 425, 429, 500, 502, 503, 504}:
            raise ConfigurationError("OpenHands v55 retry HTTP status changed")
    elif "http_status" in value:
        raise ConfigurationError("OpenHands v55 retry diagnostic status changed")


def _validated_hash(value: Mapping[str, Any], field: str, label: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    observed = result.pop(field, None)
    if not isinstance(observed, str) or not _HASH.fullmatch(observed):
        raise ConfigurationError(f"OpenHands v55 {label} identity is malformed")
    if content_hash(result) != observed:
        raise ConfigurationError(f"OpenHands v55 {label} identity changed")
    result[field] = observed
    return result


def _validate_session_index(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= OPENHANDS_V55_MAXIMUM_SESSIONS
    ):
        raise ConfigurationError("OpenHands v55 provisioning session index is invalid")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "OPENHANDS_V55_AUTHORIZATION_FORMAT",
    "OPENHANDS_V55_ENVIRONMENT_ID",
    "OPENHANDS_V55_IDENTITY",
    "OPENHANDS_V55_LAYER_MAXIMUM_ATTEMPTS",
    "OPENHANDS_V55_MANIFEST_FORMAT",
    "OPENHANDS_V55_MAXIMUM_SESSIONS",
    "OPENHANDS_V55_OPT_IN_ENV",
    "OPENHANDS_V55_PERSISTENT_LAYER_CACHE",
    "build_v55_environment_manifest",
    "run_v55_environment_provisioning",
    "validate_v55_authorization",
    "validate_v55_environment_manifest",
]
