"""V54 zero-provider successor bound to the frozen v53 transfer evidence."""

from __future__ import annotations

import copy
import os
import re
import secrets
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

from . import hwe_v52_materialization as _v52
from . import hwe_v53_materialization as _v53
from .hwe_v23_protocol import OPENHANDS_V23_TOOL_CHOICE_POLICY

OPENHANDS_V54_OPT_IN_ENV = "VERIGYM_MATERIALIZE_OPENHANDS_HWE_V54_V23_CANARY"
OPENHANDS_V54_AUTHORIZATION_FORMAT = (
    "verigym_openhands_hwe_v54_v23_canary_materialization_authorization_v1"
)
OPENHANDS_V54_PROGRESS_FORMAT = "verigym_openhands_hwe_v54_v23_materialization_progress_v1"
OPENHANDS_V54_CONTRACT_FORMAT = "verigym_openhands_hwe_v54_v23_canary_contract_v1"
OPENHANDS_V54_IDENTITY = "openhands-hwe-v54-v23-canary-materialization-v1"
OPENHANDS_V55_CAMPAIGN_ID = "openhands-hwe-v55-v23-provider-canary-v1"
OPENHANDS_V55_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v55-v23-canary-v1"
OPENHANDS_V54_PERSISTENT_LAYER_CACHE = _v53.OPENHANDS_V53_PERSISTENT_LAYER_CACHE

_HASH = re.compile(r"^[0-9a-f]{64}$")
_STAGE_ORDER = (
    "pr2728_image_transfer",
    "pr2728_public_qualification",
    "pr2728_v2_security_scan",
    "pr2728_command_image_lock",
    "pr3204_v33_lock_revalidation",
    "v23_canary_contract",
)
_V53_FAILURE_BINDING = {
    "identity": "openhands-hwe-v53-v23-canary-materialization-v1",
    "status": "frozen_zero_provider_materialization_failed",
    "failure_stage": "pr2728_image_transfer",
    "failure_type": "_CommandFailure",
    "failure_file_sha256": "e809bf3e843669ce67ae02a78ffcab18e21b10b3c6ddb2dbf8ced082dcb707b3",
    "failure_receipt_hash": "aab9f0397db9383a5bab905079a5689ab3204bc7db308ea9441e0a694629f814",
    "transfer_error_family": "unknown",
    "transfer_stderr_bytes": 192,
    "transfer_stderr_sha256": "3b1989f565aa82c8afc920e54e89f22692e8bfb6cf59d62e5fcd52ad5f8e5409",
    "verified_layer_count": 15,
    "verified_layer_bytes": 774_127_158,
    "output_published": False,
    "provider_calls": 0,
    "model_process_count": 0,
    "behavior_failure_count": 0,
    "stopped_audit_merge_commit": "3835aaedc3d38df5af62f385d1c5b5e249c77d2f",
    "post_merge_main_run_id": 33587409723,
    "post_merge_main_all_eight_classes_passed": True,
}
_V54_MATERIALIZATION_INPUTS: dict[str, Any] = copy.deepcopy(_v53._V53_MATERIALIZATION_INPUTS)
_V54_MATERIALIZATION_INPUTS["v53_failure"] = copy.deepcopy(_V53_FAILURE_BINDING)

Stage = Callable[[Path], Mapping[str, Any]]


@dataclass(frozen=True)
class V54Stages:
    """The five executable zero-provider stages supplied by the v54 CLI."""

    pr2728_image_transfer: Stage
    pr2728_public_qualification: Stage
    pr2728_v2_security_scan: Stage
    pr2728_command_image_lock: Stage
    pr3204_v33_lock_revalidation: Stage


def run_v54_zero_provider(
    *,
    authorization: Mapping[str, Any],
    stages: V54Stages,
    output: Path,
) -> dict[str, Any]:
    """Run v54 once and atomically publish only a complete v23 contract."""

    if os.environ.get(OPENHANDS_V54_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V54_OPT_IN_ENV}=1 is required")
    approved = validate_v54_authorization(authorization)
    if output.exists() or output.is_symlink():
        raise ConfigurationError("OpenHands v54 output already exists")
    parent = output.parent.resolve(strict=True)
    staging = parent / f".{output.name}.v54-staging-{os.getpid()}-{secrets.token_hex(6)}"
    staging.mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V54_PROGRESS_FORMAT,
        "identity": OPENHANDS_V54_IDENTITY,
        "status": "running",
        "authorization_hash": approved["authorization_hash"],
        "stage_order": list(_STAGE_ORDER),
        "completed_stages": [],
        "active_stage": None,
        "stage_receipt_hashes": {},
        "provider_calls": 0,
        "model_process_count": 0,
        "canary_executed": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    try:
        receipts: dict[str, dict[str, Any]] = {}
        functions: tuple[tuple[str, Stage], ...] = (
            (_STAGE_ORDER[0], stages.pr2728_image_transfer),
            (_STAGE_ORDER[1], stages.pr2728_public_qualification),
            (_STAGE_ORDER[2], stages.pr2728_v2_security_scan),
            (_STAGE_ORDER[3], stages.pr2728_command_image_lock),
            (_STAGE_ORDER[4], stages.pr3204_v33_lock_revalidation),
        )
        for name, function in functions:
            progress["active_stage"] = name
            receipt = _v52._validate_stage(name, function(staging))
            receipts[name] = receipt
            atomic_dump_json(staging / f"{name}.json", receipt)
            progress["completed_stages"].append(name)
            progress["stage_receipt_hashes"][name] = receipt["receipt_hash"]
            atomic_dump_json(staging / "materialization-progress.json", _sealed(progress))

        _v52._validate_v52_stage_bindings(receipts)
        progress["active_stage"] = _STAGE_ORDER[5]
        contract = build_v54_canary_contract(
            training_lock=receipts[_STAGE_ORDER[3]],
            validation_lock=receipts[_STAGE_ORDER[4]],
        )
        atomic_dump_json(staging / "canary-contract.json", contract)
        progress["completed_stages"].append(_STAGE_ORDER[5])
        progress["stage_receipt_hashes"][_STAGE_ORDER[5]] = contract["contract_hash"]
        progress.update(
            {
                "active_stage": None,
                "status": "completed_v23_canary_contract_materialized",
                "canary_contract_hash": contract["contract_hash"],
            }
        )
        result = _sealed(progress)
        atomic_dump_json(staging / "materialization-progress.json", result)
        staging.rename(output)
        _fsync_directory(parent)
        return result
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_v54_canary_contract(
    *,
    training_lock: Mapping[str, Any],
    validation_lock: Mapping[str, Any],
) -> dict[str, Any]:
    """Shift the unmaterialized provider identity to v55 after the v53 stop."""

    previous = _v53.build_v53_canary_contract(
        training_lock=training_lock,
        validation_lock=validation_lock,
    )
    base = {key: copy.deepcopy(value) for key, value in previous.items() if key != "contract_hash"}
    base.update(
        {
            "format_id": OPENHANDS_V54_CONTRACT_FORMAT,
            "campaign_id": OPENHANDS_V55_CAMPAIGN_ID,
            "agent_version_id": OPENHANDS_V55_AGENT_VERSION_ID,
            "v53_boundary": {
                "identity_frozen": True,
                "output_published": False,
                "provider_called": False,
                "behavior_failure_count": 0,
                "failure_file_sha256": _V53_FAILURE_BINDING["failure_file_sha256"],
                "failure_receipt_hash": _V53_FAILURE_BINDING["failure_receipt_hash"],
                "verified_layer_count": _V53_FAILURE_BINDING["verified_layer_count"],
                "verified_layer_bytes": _V53_FAILURE_BINDING["verified_layer_bytes"],
            },
        }
    )
    return validate_v54_canary_contract({**base, "contract_hash": content_hash(base)})


def validate_v54_canary_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _validated_hash(value, "contract_hash", "canary contract")
    boundary = {
        "identity_frozen": True,
        "output_published": False,
        "provider_called": False,
        "behavior_failure_count": 0,
        "failure_file_sha256": _V53_FAILURE_BINDING["failure_file_sha256"],
        "failure_receipt_hash": _V53_FAILURE_BINDING["failure_receipt_hash"],
        "verified_layer_count": _V53_FAILURE_BINDING["verified_layer_count"],
        "verified_layer_bytes": _V53_FAILURE_BINDING["verified_layer_bytes"],
    }
    if (
        result.get("format_id") != OPENHANDS_V54_CONTRACT_FORMAT
        or result.get("campaign_id") != OPENHANDS_V55_CAMPAIGN_ID
        or result.get("agent_version_id") != OPENHANDS_V55_AGENT_VERSION_ID
        or result.get("behavior_protocol") != OPENHANDS_V23_TOOL_CHOICE_POLICY
        or result.get("v53_boundary") != boundary
    ):
        raise ConfigurationError("OpenHands v54 canary contract identity changed")
    compatible = copy.deepcopy(result)
    compatible.pop("contract_hash")
    compatible.pop("v53_boundary")
    compatible.update(
        {
            "format_id": _v53.OPENHANDS_V53_CONTRACT_FORMAT,
            "campaign_id": _v53.OPENHANDS_V54_CAMPAIGN_ID,
            "agent_version_id": _v53.OPENHANDS_V54_AGENT_VERSION_ID,
        }
    )
    _v53.validate_v53_canary_contract({**compatible, "contract_hash": content_hash(compatible)})
    return result


def validate_v54_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _validated_hash(value, "authorization_hash", "authorization")
    expected_controls = {
        "persistent_content_addressed_layer_cache": True,
        "verified_v53_cache_entries_reused": True,
        "task_specific_download_staging": True,
        "linux_amd64_manifest_frozen": True,
        "manifest_digest_and_layer_bound_validated": True,
        "per_layer_single_download": True,
        "per_layer_digest_and_size_before_atomic_rename": True,
        "per_layer_published_before_next_download": True,
        "assembly_uses_complete_verified_cache": True,
        "bounded_digest_size_hit_inventory_only": True,
        "raw_stderr_temporary_only": True,
        "redacted_error_family_only": True,
        "single_temporary_archive_cleanup": True,
        "base_fail_reference_pass": True,
        "scanner_profile_v2": True,
        "codex_absent": True,
        "credentials_absent": True,
        "hidden_assets_absent": True,
        "runtime_network_none": True,
        "pr3204_v33_lock_revalidated": True,
        "atomic_final_contract_publication": True,
        "failure_publishes_no_partial_contract": True,
        "automatic_retry": False,
    }
    expected_actions = {
        "resolve_pr2728_platform_manifest": True,
        "download_pr2728_cache_misses": True,
        "assemble_pr2728_image": True,
        "qualify_pr2728_public_task": True,
        "build_and_run_v2_scanner": True,
        "build_pr2728_command_image_lock": True,
        "revalidate_pr3204_v33_lock": True,
        "materialize_v23_canary_contract": True,
        "invoke_provider": False,
        "run_canary": False,
        "start_formal_collection": False,
        "start_training": False,
    }
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V54_AUTHORIZATION_FORMAT
        or result.get("status") != "authorized_pending_zero_provider_materialization"
        or result.get("identity") != OPENHANDS_V54_IDENTITY
        or result.get("predecessor_v53") != _V53_FAILURE_BINDING
        or result.get("stage_order") != list(_STAGE_ORDER)
        or result.get("persistent_layer_cache") != str(OPENHANDS_V54_PERSISTENT_LAYER_CACHE)
        or result.get("materialization_inputs") != _V54_MATERIALIZATION_INPUTS
        or result.get("training_task_id") != _v52._TRAINING_TASK
        or result.get("validation_task_id") != _v52._VALIDATION_TASK
        or result.get("validation_v33_binding") != _v52._V33_PR3204_LOCK
        or result.get("model") != "openai/deepseek-v4-flash"
        or result.get("seed") != 498
        or result.get("sample_index") != 14
        or result.get("behavior_protocol") != OPENHANDS_V23_TOOL_CHOICE_POLICY
        or result.get("provider_hidden_thinking") != "disabled"
        or result.get("provider_calls") != 0
        or result.get("model_process_count") != 0
        or result.get("required_controls") != expected_controls
        or result.get("authorized_actions") != expected_actions
        or result.get("failure_policy")
        != "freeze_v54_keep_verified_layers_and_advance_identity_without_partial_authorization"
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
        raise ConfigurationError("OpenHands v54 authorization policy changed")
    return result


def _validated_hash(value: Mapping[str, Any], field: str, label: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    observed = result.pop(field, None)
    if not isinstance(observed, str) or not _HASH.fullmatch(observed):
        raise ConfigurationError(f"OpenHands v54 {label} identity is malformed")
    if content_hash(result) != observed:
        raise ConfigurationError(f"OpenHands v54 {label} identity changed")
    result[field] = observed
    return result


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    return {**base, "receipt_hash": content_hash(base)}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "OPENHANDS_V54_AUTHORIZATION_FORMAT",
    "OPENHANDS_V54_CONTRACT_FORMAT",
    "OPENHANDS_V54_IDENTITY",
    "OPENHANDS_V54_OPT_IN_ENV",
    "OPENHANDS_V54_PERSISTENT_LAYER_CACHE",
    "OPENHANDS_V54_PROGRESS_FORMAT",
    "OPENHANDS_V55_AGENT_VERSION_ID",
    "OPENHANDS_V55_CAMPAIGN_ID",
    "V54Stages",
    "build_v54_canary_contract",
    "run_v54_zero_provider",
    "validate_v54_authorization",
    "validate_v54_canary_contract",
]
