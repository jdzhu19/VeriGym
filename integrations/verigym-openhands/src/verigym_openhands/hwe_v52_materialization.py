"""Atomic zero-provider materialization for the OpenHands v23 canary."""

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

from .hwe_v23_protocol import (
    OPENHANDS_V23_MAX_CONTEXT_TOKENS,
    OPENHANDS_V23_MAX_OUTPUT_TOKENS,
    OPENHANDS_V23_MAX_PROVIDER_CALLS,
    OPENHANDS_V23_MAX_PROVIDER_TOKENS,
    OPENHANDS_V23_TOOL_CHOICE_POLICY,
)

OPENHANDS_V52_OPT_IN_ENV = "VERIGYM_MATERIALIZE_OPENHANDS_HWE_V52_V23_CANARY"
OPENHANDS_V52_AUTHORIZATION_FORMAT = (
    "verigym_openhands_hwe_v52_v23_canary_materialization_authorization_v1"
)
OPENHANDS_V52_PROGRESS_FORMAT = "verigym_openhands_hwe_v52_v23_materialization_progress_v1"
OPENHANDS_V52_CONTRACT_FORMAT = "verigym_openhands_hwe_v52_v23_canary_contract_v1"
OPENHANDS_V52_IDENTITY = "openhands-hwe-v52-v23-canary-materialization-v1"
OPENHANDS_V53_CAMPAIGN_ID = "openhands-hwe-v53-v23-provider-canary-v1"
OPENHANDS_V53_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v53-v23-canary-v1"
OPENHANDS_V52_PERSISTENT_LAYER_CACHE = Path(
    "/data/jzhu484/Agent/.verigym-tmp/openhands-v52-content-addressed-layer-cache-v1"
)

_TRAINING_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728"
_VALIDATION_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204"
_V33_PR3204_LOCK = {
    "task_hash": "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86",
    "source_hash": "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f",
    "verifier_image": "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64",
    "source_image_lock_file_sha256": (
        "55ff6b4efb9675a0a6d512b32d0b33d7778d93d81159086c7485b9f3ebe92a6b"
    ),
    "source_image_lock_hash": ("b3fe6732fe4d9b52a6444cda90b25add311665af537acf6b389ad1fdafa1933b"),
    "command_image": "sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784",
    "lock_file_sha256": "a3a29f4ad2515c9502b3716e8644806154c7f9a74d388f9cd9c741d81458dc22",
    "lock_hash": "4e6bcb561d1c631955dcf9b4a2475a0b09d5bb6bb6b98441cd20101f893400d7",
    "security_scan_file_sha256": (
        "6357976446539e526c15cf22a8e9616df650e4ac30117934898b7a40eb339ed1"
    ),
    "security_scan_id": "55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf",
}
_V52_MATERIALIZATION_INPUTS = {
    "dataset": {
        "sha256": "732c5dac910815c1c7ac72c8ccca88f66dbb7ed5d097806a5ddea611102f60f1",
        "revision": "1403afb57ce056c659c82b35e39c38c6a21ee635",
        "source_commit": "10c78a87e1f92695d78d15b1464a6107dcac8837",
        "candidate_record_sha256": (
            "42f3040a91af4e735e1107dd2536691c9fa3286b4e9441cc8ebb039e3d3c1a16"
        ),
        "reference_patch_compatibility_hash": (
            "cccec1b44901f1e3cd7d6694a5a825cd9716536e445a7678ff408cedcf6fe0d2"
        ),
    },
    "transfer": {
        "reference": "ghcr.io/pku-liang/openhwgroup_m_cva6:pr-2728",
        "execution_image": {
            "reference": "python:3.11.9-slim-bookworm",
            "image_id": ("sha256:65a6ce634d975b67ee77c8d0f59248cbcb9d8b8f229d584c3cf5d624038bf963"),
            "manifest_digest": (
                "sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317"
            ),
        },
        "network": "verigym-hwe-net",
        "crane_release": "v0.22.0",
        "crane_sha256": "771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94",
    },
    "command_image": {
        "ripgrep_version": "ripgrep 15.2.0 (rev e89fff89ac)",
        "ripgrep_binary_sha256": (
            "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849"
        ),
        "ripgrep_release_archive_sha256": (
            "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c"
        ),
        "scanner_profile_id": "cva6-hwe-command-container-native-offline-v2",
        "build_network": "none",
        "runtime_network": "none",
    },
    "v33_files": {
        "source_lock_file_sha256": (
            "55ff6b4efb9675a0a6d512b32d0b33d7778d93d81159086c7485b9f3ebe92a6b"
        ),
        "command_lock_file_sha256": (
            "a3a29f4ad2515c9502b3716e8644806154c7f9a74d388f9cd9c741d81458dc22"
        ),
        "security_scan_file_sha256": (
            "6357976446539e526c15cf22a8e9616df650e4ac30117934898b7a40eb339ed1"
        ),
    },
}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_STAGE_ORDER = (
    "pr2728_image_transfer",
    "pr2728_public_qualification",
    "pr2728_v2_security_scan",
    "pr2728_command_image_lock",
    "pr3204_v33_lock_revalidation",
    "v23_canary_contract",
)

Stage = Callable[[Path], Mapping[str, Any]]


@dataclass(frozen=True)
class V52Stages:
    """The exact six zero-provider stages, supplied by the materialization CLI."""

    pr2728_image_transfer: Stage
    pr2728_public_qualification: Stage
    pr2728_v2_security_scan: Stage
    pr2728_command_image_lock: Stage
    pr3204_v33_lock_revalidation: Stage


def run_v52_zero_provider(
    *,
    authorization: Mapping[str, Any],
    stages: V52Stages,
    output: Path,
) -> dict[str, Any]:
    """Run the exact stage order and publish nothing until the contract is complete."""

    if os.environ.get(OPENHANDS_V52_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V52_OPT_IN_ENV}=1 is required")
    approved = validate_v52_authorization(authorization)
    if output.exists() or output.is_symlink():
        raise ConfigurationError("OpenHands v52 output already exists")
    parent = output.parent.resolve(strict=True)
    staging = parent / f".{output.name}.v52-staging-{os.getpid()}-{secrets.token_hex(6)}"
    staging.mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V52_PROGRESS_FORMAT,
        "identity": OPENHANDS_V52_IDENTITY,
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
        stage_functions: tuple[tuple[str, Stage], ...] = (
            (_STAGE_ORDER[0], stages.pr2728_image_transfer),
            (_STAGE_ORDER[1], stages.pr2728_public_qualification),
            (_STAGE_ORDER[2], stages.pr2728_v2_security_scan),
            (_STAGE_ORDER[3], stages.pr2728_command_image_lock),
            (_STAGE_ORDER[4], stages.pr3204_v33_lock_revalidation),
        )
        for name, function in stage_functions:
            progress["active_stage"] = name
            receipt = _validate_stage(name, function(staging))
            receipts[name] = receipt
            atomic_dump_json(staging / f"{name}.json", receipt)
            progress["completed_stages"].append(name)
            progress["stage_receipt_hashes"][name] = receipt["receipt_hash"]
            atomic_dump_json(staging / "materialization-progress.json", _sealed(progress))

        _validate_v52_stage_bindings(receipts)
        progress["active_stage"] = _STAGE_ORDER[5]
        contract = build_v52_canary_contract(
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
        # A failed identity may retain external audit evidence, but it must not
        # publish a partial canary authorization at the requested output path.
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_v52_canary_contract(
    *,
    training_lock: Mapping[str, Any],
    validation_lock: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal the fixed PR-2728 -> PR-3204 v23 provider schedule."""

    training = _validate_command_lock(training_lock, task_id=_TRAINING_TASK)
    validation = _validate_command_lock(validation_lock, task_id=_VALIDATION_TASK)
    if training["command_image"] == validation["command_image"]:
        raise ConfigurationError("OpenHands v52 command images are not task-distinct")
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V52_CONTRACT_FORMAT,
        "campaign_id": OPENHANDS_V53_CAMPAIGN_ID,
        "agent_version_id": OPENHANDS_V53_AGENT_VERSION_ID,
        "behavior_protocol": OPENHANDS_V23_TOOL_CHOICE_POLICY,
        "schedule": [
            {"task_id": _TRAINING_TASK, "role": "training", "seed": 498, "sample_index": 14},
            {
                "task_id": _VALIDATION_TASK,
                "role": "validation",
                "seed": 498,
                "sample_index": 14,
            },
        ],
        "task_bindings": {
            _TRAINING_TASK: _contract_binding(training),
            _VALIDATION_TASK: _contract_binding(validation),
        },
        "teacher": {
            "model": "openai/deepseek-v4-flash",
            "model_identity": "deepseek-v4-flash",
            "openhands_sdk_version": "1.42.1",
            "litellm_version": "1.93.0",
            "tiktoken_version": "0.7.0",
            "tool_choice_ordinary": "provider_default_auto_omitted",
            "tool_choice_recovery": "required",
            "provider_hidden_thinking": "disabled",
            "temperature": 0,
            "max_provider_calls": OPENHANDS_V23_MAX_PROVIDER_CALLS,
            "max_provider_tokens": OPENHANDS_V23_MAX_PROVIDER_TOKENS,
            "max_context_tokens": OPENHANDS_V23_MAX_CONTEXT_TOKENS,
            "max_output_tokens": OPENHANDS_V23_MAX_OUTPUT_TOKENS,
            "provider_request_retries": 0,
            "whole_episode_retries": 0,
            "condenser": None,
        },
        "runtime": {
            "six_typed_tools": True,
            "sibling_prevalidation": "all_before_dispatch",
            "sibling_execution": "decision_order_serial",
            "tool_concurrency_limit": 1,
            "stuck_detection": True,
            "pre_edit_checkpoint_action": 16,
            "pre_edit_no_progress_action": 32,
            "command_execution_backend": "episode_container_exec_v1",
            "codex_present": False,
            "provider_credentials_in_command_container": False,
            "hidden_assets_present": False,
            "network": "none",
        },
        "gate": {
            "all_six_result_planes_required": True,
            "exact_64k_required": True,
            "truncation_allowed": False,
            "stop_validation_after_training_failure": True,
            "maximum_openhands_behavior_failures": 2,
            "second_canary_requires_offline_scaffold_reproduction": True,
            "second_canary_seed": 499,
            "second_canary_sample_index": 15,
            "second_canary_hidden_thinking": "disabled",
            "fallback_after_second_behavior_failure": "harness_v3_successor",
        },
        "v51_boundary": {
            "identity_frozen": True,
            "source_workspace_created": False,
            "verifier_executed": False,
            "provider_called": False,
            "pr2728_may_be_publicly_requalified_under_v52": True,
        },
        "provider_calls_during_materialization": 0,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    return validate_v52_canary_contract({**base, "contract_hash": content_hash(base)})


def validate_v52_canary_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _validated_hash(value, "contract_hash", "canary contract")
    schedule = result.get("schedule")
    bindings = result.get("task_bindings")
    teacher = result.get("teacher")
    runtime = result.get("runtime")
    gate = result.get("gate")
    if (
        result.get("format_id") != OPENHANDS_V52_CONTRACT_FORMAT
        or result.get("campaign_id") != OPENHANDS_V53_CAMPAIGN_ID
        or result.get("agent_version_id") != OPENHANDS_V53_AGENT_VERSION_ID
        or result.get("behavior_protocol") != OPENHANDS_V23_TOOL_CHOICE_POLICY
        or schedule
        != [
            {"task_id": _TRAINING_TASK, "role": "training", "seed": 498, "sample_index": 14},
            {
                "task_id": _VALIDATION_TASK,
                "role": "validation",
                "seed": 498,
                "sample_index": 14,
            },
        ]
        or not isinstance(bindings, dict)
        or set(bindings) != {_TRAINING_TASK, _VALIDATION_TASK}
        or not isinstance(teacher, dict)
        or teacher.get("provider_hidden_thinking") != "disabled"
        or teacher.get("openhands_sdk_version") != "1.42.1"
        or teacher.get("litellm_version") != "1.93.0"
        or teacher.get("tiktoken_version") != "0.7.0"
        or teacher.get("tool_choice_ordinary") != "provider_default_auto_omitted"
        or teacher.get("tool_choice_recovery") != "required"
        or teacher.get("max_provider_calls") != 64
        or teacher.get("max_provider_tokens") != 1_000_000
        or teacher.get("max_context_tokens") != 65_536
        or teacher.get("max_output_tokens") != 2_048
        or teacher.get("provider_request_retries") != 0
        or teacher.get("whole_episode_retries") != 0
        or teacher.get("condenser") is not None
        or not isinstance(runtime, dict)
        or runtime.get("network") != "none"
        or runtime.get("codex_present") is not False
        or runtime.get("provider_credentials_in_command_container") is not False
        or runtime.get("hidden_assets_present") is not False
        or runtime.get("sibling_prevalidation") != "all_before_dispatch"
        or runtime.get("sibling_execution") != "decision_order_serial"
        or runtime.get("stuck_detection") is not True
        or not isinstance(gate, dict)
        or gate.get("all_six_result_planes_required") is not True
        or gate.get("exact_64k_required") is not True
        or gate.get("truncation_allowed") is not False
        or gate.get("maximum_openhands_behavior_failures") != 2
        or result.get("provider_calls_during_materialization") != 0
        or any(
            result.get(name) is not False
            for name in (
                "formal_collection_allowed",
                "formal_collection_started",
                "collection_started",
                "training_started",
                "production_training_ready",
                "benchmark_score_claimed",
            )
        )
    ):
        raise ConfigurationError("OpenHands v52 canary contract policy changed")
    for task_id in (_TRAINING_TASK, _VALIDATION_TASK):
        binding = bindings[task_id]
        if not isinstance(binding, dict) or not all(
            _HASH.fullmatch(str(binding.get(name, "")))
            for name in (
                "task_hash",
                "source_hash",
                "source_image_lock_file_sha256",
                "source_image_lock_hash",
                "lock_file_sha256",
                "lock_hash",
                "security_scan_file_sha256",
                "security_scan_id",
            )
        ):
            raise ConfigurationError("OpenHands v52 canary binding changed")
        if not _DIGEST.fullmatch(str(binding.get("command_image", ""))) or not _DIGEST.fullmatch(
            str(binding.get("verifier_image", ""))
        ):
            raise ConfigurationError("OpenHands v52 canary image binding changed")
    return result


def validate_v52_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _validated_hash(value, "authorization_hash", "authorization")
    predecessor = result.get("predecessor_v51")
    controls = result.get("required_controls")
    actions = result.get("authorized_actions")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V52_AUTHORIZATION_FORMAT
        or result.get("status") != "authorized_pending_zero_provider_materialization"
        or result.get("identity") != OPENHANDS_V52_IDENTITY
        or result.get("stage_order") != list(_STAGE_ORDER)
        or result.get("persistent_layer_cache") != str(OPENHANDS_V52_PERSISTENT_LAYER_CACHE)
        or result.get("provider_calls") != 0
        or result.get("model_process_count") != 0
        or result.get("v51_identity_frozen") is not True
        or result.get("v51_source_workspace_created") is not False
        or result.get("v51_verifier_executed") is not False
        or result.get("v51_provider_called") is not False
        or result.get("pr2728_public_requalification_allowed") is not True
        or result.get("training_task_id") != _TRAINING_TASK
        or result.get("validation_task_id") != _VALIDATION_TASK
        or result.get("validation_v33_binding") != _V33_PR3204_LOCK
        or result.get("materialization_inputs") != _V52_MATERIALIZATION_INPUTS
        or result.get("model") != "openai/deepseek-v4-flash"
        or result.get("seed") != 498
        or result.get("sample_index") != 14
        or result.get("behavior_protocol") != OPENHANDS_V23_TOOL_CHOICE_POLICY
        or result.get("provider_hidden_thinking") != "disabled"
        or predecessor
        != {
            "identity": "openhands-hwe-v51-pr2728-public-qualification-v1",
            "status": "stopped_security_or_infrastructure_invalid",
            "identity_frozen": True,
            "source_workspace_created": False,
            "verifier_executed": False,
            "provider_called": False,
            "benchmark_disposition_created": False,
            "stopped_audit_merge_commit": "2921d04586a375fd2c15ff1a944034e576ab71c4",
            "post_merge_main_run_id": 33528870018,
            "post_merge_main_all_eight_classes_passed": True,
        }
        or controls
        != {
            "persistent_content_addressed_layer_cache": True,
            "task_specific_download_staging": True,
            "digest_and_size_before_atomic_rename": True,
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
        or actions
        != {
            "transfer_pr2728_image": True,
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
        or result.get("failure_policy")
        != "freeze_v52_and_advance_identity_without_partial_authorization"
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
        raise ConfigurationError("OpenHands v52 authorization policy changed")
    return result


def _validate_stage(name: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    result = _validated_hash(raw, "receipt_hash", name)
    if result.get("provider_calls") != 0 or result.get("model_process_count") != 0:
        raise ConfigurationError(f"OpenHands v52 {name} invoked a provider")
    if name == _STAGE_ORDER[0]:
        inventory = result.get("layer_inventory")
        if (
            result.get("task_id") != _TRAINING_TASK
            or not _DIGEST.fullmatch(str(result.get("verifier_image", "")))
            or not isinstance(inventory, list)
            or not inventory
            or len(inventory) > 512
            or result.get("temporary_archive_cleanup_count") != 1
            or result.get("raw_stderr_persisted") is not False
        ):
            raise ConfigurationError("OpenHands v52 transfer receipt changed")
        for item in inventory:
            if (
                not isinstance(item, dict)
                or not _DIGEST.fullmatch(str(item.get("digest", "")))
                or isinstance(item.get("size"), bool)
                or not isinstance(item.get("size"), int)
                or item["size"] <= 0
                or not isinstance(item.get("cache_hit"), bool)
            ):
                raise ConfigurationError("OpenHands v52 layer inventory changed")
    elif name == _STAGE_ORDER[1]:
        if (
            result.get("task_id") != _TRAINING_TASK
            or not _HASH.fullmatch(str(result.get("task_hash", "")))
            or not _HASH.fullmatch(str(result.get("source_hash", "")))
            or not _DIGEST.fullmatch(str(result.get("verifier_image", "")))
            or not _HASH.fullmatch(str(result.get("transfer_receipt_hash", "")))
            or result.get("infrastructure_valid") is not True
            or result.get("base_failed") is not True
            or result.get("reference_passed") is not True
            or result.get("verifier_network") != "none"
        ):
            raise ConfigurationError("OpenHands v52 public qualification failed")
    elif name == _STAGE_ORDER[2]:
        if (
            result.get("task_id") != _TRAINING_TASK
            or not _HASH.fullmatch(str(result.get("task_hash", "")))
            or not _HASH.fullmatch(str(result.get("source_hash", "")))
            or not _DIGEST.fullmatch(str(result.get("verifier_image", "")))
            or not _DIGEST.fullmatch(str(result.get("command_image", "")))
            or not _HASH.fullmatch(str(result.get("security_scan_file_sha256", "")))
            or not _HASH.fullmatch(str(result.get("security_scan_id", "")))
            or result.get("scanner_profile_id") != "cva6-hwe-command-container-native-offline-v2"
            or result.get("scan_passed") is not True
            or any(
                result.get(field) is not False
                for field in (
                    "codex_present",
                    "provider_credentials_present",
                    "hidden_assets_present",
                    "network_available",
                )
            )
        ):
            raise ConfigurationError("OpenHands v52 v2 security scan failed")
    elif name == _STAGE_ORDER[3]:
        _validate_command_lock(result, task_id=_TRAINING_TASK)
    elif name == _STAGE_ORDER[4]:
        _validate_command_lock(result, task_id=_VALIDATION_TASK)
        if result.get("source") != "sealed_v33_revalidated" or any(
            result.get(field) != expected for field, expected in _V33_PR3204_LOCK.items()
        ):
            raise ConfigurationError("OpenHands v52 v33 lock was not revalidated")
    else:
        raise ConfigurationError("OpenHands v52 stage name changed")
    return result


def _validate_command_lock(value: Mapping[str, Any], *, task_id: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    required_hashes = (
        "task_hash",
        "source_hash",
        "source_image_lock_file_sha256",
        "source_image_lock_hash",
        "lock_file_sha256",
        "lock_hash",
        "security_scan_file_sha256",
        "security_scan_id",
    )
    if (
        result.get("task_id") != task_id
        or any(not _HASH.fullmatch(str(result.get(name, ""))) for name in required_hashes)
        or not _DIGEST.fullmatch(str(result.get("command_image", "")))
        or not _DIGEST.fullmatch(str(result.get("verifier_image", "")))
        or result.get("scanner_profile_id") != "cva6-hwe-command-container-native-offline-v2"
        or result.get("security_scan_passed") is not True
        or result.get("codex_present") is not False
        or result.get("provider_credentials_present") is not False
        or result.get("hidden_assets_present") is not False
        or result.get("build_network") != "none"
        or result.get("runtime_network") != "none"
    ):
        raise ConfigurationError("OpenHands v52 command-image lock changed")
    return result


def _validate_v52_stage_bindings(receipts: Mapping[str, Mapping[str, Any]]) -> None:
    """Require every PR-2728 stage to describe the same frozen task and images."""

    transfer = receipts[_STAGE_ORDER[0]]
    qualification = receipts[_STAGE_ORDER[1]]
    scan = receipts[_STAGE_ORDER[2]]
    lock = receipts[_STAGE_ORDER[3]]
    if (
        qualification.get("transfer_receipt_hash") != transfer.get("receipt_hash")
        or qualification.get("verifier_image") != transfer.get("verifier_image")
        or any(
            qualification.get(field) != lock.get(field)
            for field in ("task_id", "task_hash", "source_hash", "verifier_image")
        )
        or any(
            scan.get(field) != lock.get(field)
            for field in (
                "task_id",
                "task_hash",
                "source_hash",
                "verifier_image",
                "command_image",
                "security_scan_file_sha256",
                "security_scan_id",
            )
        )
    ):
        raise ConfigurationError("OpenHands v52 PR-2728 stage identities differ")


def _contract_binding(lock: Mapping[str, Any]) -> dict[str, str]:
    return {
        name: str(lock[name])
        for name in (
            "task_hash",
            "source_hash",
            "verifier_image",
            "source_image_lock_file_sha256",
            "source_image_lock_hash",
            "command_image",
            "lock_file_sha256",
            "lock_hash",
            "security_scan_file_sha256",
            "security_scan_id",
        )
    }


def _validated_hash(value: Mapping[str, Any], field: str, label: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    observed = result.pop(field, None)
    if not isinstance(observed, str) or not _HASH.fullmatch(observed):
        raise ConfigurationError(f"OpenHands v52 {label} identity is malformed")
    if content_hash(result) != observed:
        raise ConfigurationError(f"OpenHands v52 {label} identity changed")
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
    "OPENHANDS_V52_AUTHORIZATION_FORMAT",
    "OPENHANDS_V52_CONTRACT_FORMAT",
    "OPENHANDS_V52_IDENTITY",
    "OPENHANDS_V52_OPT_IN_ENV",
    "OPENHANDS_V52_PERSISTENT_LAYER_CACHE",
    "OPENHANDS_V52_PROGRESS_FORMAT",
    "OPENHANDS_V53_AGENT_VERSION_ID",
    "OPENHANDS_V53_CAMPAIGN_ID",
    "V52Stages",
    "build_v52_canary_contract",
    "run_v52_zero_provider",
    "validate_v52_authorization",
    "validate_v52_canary_contract",
]
