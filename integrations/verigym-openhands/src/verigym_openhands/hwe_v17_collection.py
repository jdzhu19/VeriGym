"""Frozen v17 formal collection identity, schedule, and fail-closed capacity gate."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.memory import build_agent_version, validate_agent_version
from verigym.plugin_api import JsonValue
from verigym.schemas.evolution import AgentVersionManifest, TaskSplitManifest
from verigym.schemas.options import validate_plugin_options

from . import hwe_v17_canary_v4 as _canary

OPENHANDS_V17_COLLECTION_FORMAT = "verigym_openhands_hwe_v17_formal_collection_v1"
OPENHANDS_V17_COLLECTION_REPORT_FORMAT = "verigym_openhands_hwe_v17_formal_collection_report_v1"
OPENHANDS_V17_COLLECTION_GATE_FORMAT = "verigym_openhands_hwe_v17_formal_collection_gate_v1"
OPENHANDS_V17_COLLECTION_CAMPAIGN_ID = "openhands-hwe-v17-formal-collection-v1"
OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-v17-formal-collection-v1"
)
OPENHANDS_V17_COLLECTION_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V17_FORMAL_COLLECTION_V1"
OPENHANDS_V17_COLLECTION_CONTRACT_FILE = "qwen35_hwe_openhands_v17_collection_v1.json"
OPENHANDS_V17_COLLECTION_SEED = 487
OPENHANDS_V17_COLLECTION_SAMPLE_INDEX = 3

OPENHANDS_V17_COLLECTION_MODEL = _canary.OPENHANDS_V17_CANARY_MODEL
OPENHANDS_V17_COLLECTION_MODEL_IDENTITY = _canary.OPENHANDS_V17_CANARY_MODEL_IDENTITY
OPENHANDS_V17_COLLECTION_BASE_URL_ENV = _canary.OPENHANDS_V17_CANARY_BASE_URL_ENV
OPENHANDS_V17_COLLECTION_API_KEY_ENV = _canary.OPENHANDS_V17_CANARY_API_KEY_ENV
OPENHANDS_V17_COLLECTION_SDK_VERSION = _canary.OPENHANDS_V17_CANARY_SDK_VERSION
OPENHANDS_V17_COLLECTION_LITELLM_VERSION = _canary.OPENHANDS_V17_CANARY_LITELLM_VERSION
OPENHANDS_V17_COLLECTION_TIKTOKEN_VERSION = _canary.OPENHANDS_V17_CANARY_TIKTOKEN_VERSION
OPENHANDS_V17_COLLECTION_TOOL_CHOICE_POLICY = _canary.OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY
OPENHANDS_V17_COLLECTION_MAX_ITERATIONS = _canary.OPENHANDS_V17_CANARY_MAX_ITERATIONS
OPENHANDS_V17_COLLECTION_MAX_OUTPUT_TOKENS = _canary.OPENHANDS_V17_CANARY_MAX_OUTPUT_TOKENS
OPENHANDS_V17_COLLECTION_MAX_CONTEXT_TOKENS = _canary.OPENHANDS_V17_CANARY_MAX_CONTEXT_TOKENS

OPENHANDS_V17_IMPORTED_TRAINING_TASKS = (
    _canary.OPENHANDS_V17_CANARY_PR2944,
    _canary.OPENHANDS_V17_CANARY_PR2248,
)
OPENHANDS_V17_FORMAL_TRAINING_ORDER = _canary.OPENHANDS_V17_FORMAL_TRAINING_ORDER
OPENHANDS_V17_FORMAL_VALIDATION_ORDER = _canary.OPENHANDS_V17_FORMAL_VALIDATION_ORDER
OPENHANDS_V17_FORMAL_TASKS = (
    *OPENHANDS_V17_FORMAL_TRAINING_ORDER,
    *OPENHANDS_V17_FORMAL_VALIDATION_ORDER,
)
OPENHANDS_V17_ALL_COLLECTION_TASKS = (
    *OPENHANDS_V17_IMPORTED_TRAINING_TASKS,
    *OPENHANDS_V17_FORMAL_TASKS,
)
OPENHANDS_V17_IDENTITY_TASKS = (*_canary.OPENHANDS_V17_CANARY_TASKS, *OPENHANDS_V17_FORMAL_TASKS)
OPENHANDS_V17_TRAINING_TARGET = _canary.OPENHANDS_V17_TRAINING_TARGET
OPENHANDS_V17_VALIDATION_TARGET = _canary.OPENHANDS_V17_VALIDATION_TARGET

_CANARY_CONTRACT_FILE_SHA256 = "70f1dbf3b773a26bf03a79efbe614066c509c84491ff03a08806aa00fe3f3fdc"
_CANARY_REPORT_SHA256 = "6b5b8f6016d5be59c012a55c651dbdba31e417cc19e9477338fbfa181952232f"
_CANARY_GATE_SHA256 = "2ca11c0474125b2ca1459dcc93feca63b7d69cf653f4f5f2289e79665d282a2c"
_CANARY_AGENT_VERSION_SHA256 = "d992d1bfbadec0ee20fd38053661b4b2212346b56ae766884b4f4429ab9a4925"
_CANARY_REPORT_HASH = "33619e73dd87a9085ba92445f856839de750b54d8bf6653e93c14717a6a37676"
_CANARY_AGENT_VERSION_HASH = "30fb666319eef0edbc3737ac7242b438f58c211d4b434871ec5284e33dfb4cdd"

_FORMAL_BINDINGS: dict[str, dict[str, str]] = {
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2282": {
        "task_hash": "d046e56c1e9a3220ee539293a749700c0a1c027278fbdf9c7d3e99903c07a19c",
        "source_hash": "64ea8e0015201d69f0041b0b1e158a2caf95bd4c3e81f91d056e292258762d02",
        "image_lock_hash": "20af2370c1d2c51b8822d69b5bba3c11c40ded25bab85f97073deab3a58309d6",
        "agent_image": "sha256:12730dadba82de5ebff96309617ec98498ce527c9a31bccaa51c3e8f379c134f",
        "verifier_image": "sha256:7eceb407426165b867b062ce4f6ac9744eb0ea91ea4b94b1910d8ca119aea85e",
    },
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2468": {
        "task_hash": "3f53ef8b7dcc7ffe1b6d219a69ada3feb7042c6bbd0808bbc4c5eca88bdcba45",
        "source_hash": "061abb1550c2889b819e78995d1a937921b7c111d0fc1cc00788a46ec7953260",
        "image_lock_hash": "e6bc37a107ce0a0d1eaf55c00023fd0375e8bd21da6933d8013e27bf0425daad",
        "agent_image": "sha256:5ec46fd9eedc6231540027df11a7ee3c854a81d8df89e5c0341b934a8fde4565",
        "verifier_image": "sha256:714df51cce00608a73ea0a16b84e482fab89b171b98187a8e17b210afbb055af",
    },
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2469": {
        "task_hash": "2c90d93d3516bc8308b045de42cc177ec6820e98953f4a28e502a96bbc97f56e",
        "source_hash": "faf37d7a51fc87cf706afe6609e6bfd21cc63a90128be154b08a51c380784f00",
        "image_lock_hash": "a237392f6dacf52f89b5b446d7455e3aa9f627fad149f84212fd2124da51f0db",
        "agent_image": "sha256:30eb9e93a79ad33b15ac0b5573d33700ebe29ede93938b25ebb66b0680d6268c",
        "verifier_image": "sha256:42d986a58b6c12855c04d83ed0feef7a3a4506d0cc83dfa7cd98049cb31fc7e0",
    },
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549": {
        "task_hash": "d594eaa3d87441dd5ad034682486f0c410c923f75372ef4d2caa654e2ab212f9",
        "source_hash": "50a08b2358ddb7b939fa77ac7d726e1baf0735fa863d891c4325a3d204c5eaa0",
        "image_lock_hash": "dfbca8971466d121a1df3274fb4dc46daad0459872edaaf6f57826c28632358c",
        "agent_image": "sha256:2c713d28aa075180bf95ba61bcc18237f1cf82896da5cee2d76bf69900eb224f",
        "verifier_image": "sha256:a43f709fa63c987f4b8c894c19dcd3fc9c34269a45cfb3def0fbd5432fde4b40",
    },
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2589": {
        "task_hash": "91c26c78f842736087f506f0bb9dbd56e731b0dc480e011901086c9747a6a77c",
        "source_hash": "9f0ba1df91d237c38eb7e43302e5af540e1a22770671de5e7a1eeab0d312516b",
        "image_lock_hash": "a673d691410de742b6432059c7b5b6e40dc071e82ee89a91925c26c28e63d734",
        "agent_image": "sha256:8d2ed1347f28b639775903cc8e7551bc1c9aad783ff590c10ec833df48ccdfe0",
        "verifier_image": "sha256:65ad3e4242c400b9f28802eed6e3511546edb8abc8c97b28badceb401c8ef266",
    },
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2802": {
        "task_hash": "e9bfb9718e9fe66ef83494aac697baabda2ad4aad62d4c61735fdd33f3a62e30",
        "source_hash": "51d5b7c6cdb5cb064cee20f9bfea993594b7744ffaf679ca53505ec059129757",
        "image_lock_hash": "23d6a68ff227d7781e7dda834272279f97c847acdd9d99e833de444ff812af12",
        "agent_image": "sha256:6fe007db875611a047eb1e0a653fc755f50d2bda0505cc5a039ebbd69d46ad5c",
        "verifier_image": "sha256:88246baf91e53c45f266ef078bf62939329197366b8ac077f36cbdc1f8e05cdb",
    },
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2916": {
        "task_hash": "cf633dddaea257f8932e60323275e272a1988e27284309326f21894ece5b029f",
        "source_hash": "b3728d76776306d83e530fa90f6e70cfa4f15a5089ec76d0369c069e47bacbe2",
        "image_lock_hash": "6f755d70cae3b51ea82716dd983168bf4276903174e02aa925c457d925157f2b",
        "agent_image": "sha256:ffb992b1e19bb7f64af9bc747bb09d6531d0837de2a4b733617c077f9f7ca2f1",
        "verifier_image": "sha256:5f3327d0d9edb261177c9610b03a5328d66dba202719d081cda3970d8106ce71",
    },
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204": {
        "task_hash": "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86",
        "source_hash": "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f",
        "image_lock_hash": "b3fe6732fe4d9b52a6444cda90b25add311665af537acf6b389ad1fdafa1933b",
        "agent_image": "sha256:2713ee1efe1d83a655b5dbee775b8c59b3af3614b4233346b779df3a63f5e276",
        "verifier_image": "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64",
    },
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3168": {
        "task_hash": "8a383a76e03dbd993b4693338593964173c0e62e8166e870e0762bb2b0a8180b",
        "source_hash": "5d8f91eeb92d0e5b84156f4de6b2edbc7706f07ca1faab80e2f7d4bbda3eb638",
        "image_lock_hash": "72f932fafec74a77b5895a1d04c217f6c76ff854b17e7420036f1de12403b141",
        "agent_image": "sha256:4708fc16a8c3847fc07de4475e419c3c98291b2a8953b38033a79ff3c9d09d8a",
        "verifier_image": "sha256:e316c14c583e9f17b32d10e7cc7dc12410eea47f002d1a565db391c5e43b2fe4",
    },
}

_CANARY_IMPORTS = {
    _canary.OPENHANDS_V17_CANARY_PR2944: {
        "episode_id": "training-pr2944-s486",
        "run_hash": "115c4ca54cfc6402addf21e7de0d63493756b2eb84c4fe018e46f8e9f26b5ade",
        "candidate_hash": "2c3a35dcca9ac1e0389801f608c80a112f374a280bba0352d2083e0eba4aa2bc",
        "verifier_hash": "3327dcaddcc590212f60deb5b573dc0f56e1dee7d0cf48dc5fcb14f611eb718f",
        "trajectory_file_sha256": (
            "c1ed33da089ab637fb36e8278bfa4952b8a7ea01da66e6daa5ef90759d6a4371"
        ),
        "transcript_hash": "d9dcabd90f186f6c2768e6e35d292c6d30e40b9bf722e070bc327127bb1129ec",
        "assistant_decision_count": 19,
    },
    _canary.OPENHANDS_V17_CANARY_PR2248: {
        "episode_id": "training-pr2248-s486",
        "run_hash": "ed99dc80400944c86a039ce39d21e2b5f696965abb467d9343da038878f3f895",
        "candidate_hash": "461072594689b2aa6a74e7b117a09d0f73fa4e4be3269a159600cdd3c8f0a2da",
        "verifier_hash": "8c9430c2fd87cf99dd2e36979676f3392bf3c767e1e9f8c98ff568ecc6f35fb8",
        "trajectory_file_sha256": (
            "b39478423ea72f38c18abfc8b29affe1bca8ce17f40190675756a2921c19a9dc"
        ),
        "transcript_hash": "4185716256cefe619440960db3a2e2abc51e4f570fd97e777383cabb8064b761",
        "assistant_decision_count": 13,
    },
}


@dataclass(frozen=True)
class V17CollectionGate:
    """Capacity result after every atomic task attempt."""

    satisfied: bool
    possible: bool
    next_role: str | None
    reason: str
    training_pass_count: int
    validation_pass_count: int
    remaining_training_task_count: int
    remaining_validation_task_count: int
    maximum_training_pass_count: int
    maximum_validation_pass_count: int


def expected_v17_collection_contract() -> dict[str, Any]:
    """Return the exact formal collection overlay."""

    parent = _canary.expected_v17_canary_contract()
    imported_bindings = {
        task_id: copy.deepcopy(parent["task_bindings"][task_id])
        for task_id in _canary.OPENHANDS_V17_CANARY_TASKS
    }
    task_bindings = {**imported_bindings, **copy.deepcopy(_FORMAL_BINDINGS)}
    for task_id in OPENHANDS_V17_FORMAL_TRAINING_ORDER:
        task_bindings[task_id]["role"] = "training"
    for task_id in OPENHANDS_V17_FORMAL_VALIDATION_ORDER:
        task_bindings[task_id]["role"] = "validation"
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_COLLECTION_FORMAT,
        "scope": "exact_64k_development_sft_formal_collection",
        "parent_canary": {
            "contract_file": _canary.OPENHANDS_V17_CANARY_CONTRACT_FILE,
            "contract_file_sha256": _CANARY_CONTRACT_FILE_SHA256,
            "contract_hash": parent["contract_hash"],
            "report_sha256": _CANARY_REPORT_SHA256,
            "report_hash": _CANARY_REPORT_HASH,
            "gate_sha256": _CANARY_GATE_SHA256,
            "agent_version_sha256": _CANARY_AGENT_VERSION_SHA256,
            "agent_version_hash": _CANARY_AGENT_VERSION_HASH,
            "formal_collection_allowed": True,
        },
        "source": copy.deepcopy(parent["source"]),
        "teacher": copy.deepcopy(parent["teacher"]),
        "task_bindings": task_bindings,
        "canary_imports": copy.deepcopy(_CANARY_IMPORTS),
        "collection": {
            "seed": OPENHANDS_V17_COLLECTION_SEED,
            "sample_index": OPENHANDS_V17_COLLECTION_SAMPLE_INDEX,
            "training_attempt_order": list(OPENHANDS_V17_FORMAL_TRAINING_ORDER),
            "validation_attempt_order": list(OPENHANDS_V17_FORMAL_VALIDATION_ORDER),
            "training_target_distinct_tasks": OPENHANDS_V17_TRAINING_TARGET,
            "validation_target_distinct_tasks": OPENHANDS_V17_VALIDATION_TARGET,
            "stop_at_target": True,
            "capacity_recalculated_after_each_attempt": True,
            "task_retries": 0,
            "provider_request_retries": 0,
            "prior_task_ids_excluded": [_canary.OPENHANDS_V17_CANARY_PR2032],
            "heldout_tasks_eligible": False,
        },
        "student": {
            "base_model": "Qwen3.5-9B",
            "base_model_snapshot_hash": (
                "fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156"
            ),
            "tokenizer_hash": ("440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e"),
        },
        "dataset": {
            "max_length": 65536,
            "truncation": "error",
            "complete_messages_and_tool_schema": True,
            "exact_token_receipts": True,
            "decision_only_loss_mask": True,
            "objective_id": "trajectory_balanced_decision_target_token_mean_batch1_v1",
            "equal_trajectory_weight": True,
            "deterministic_decision_schedule": True,
            "separate_training_validation_manifests": True,
        },
        "heldout_task_ids_loaded": [],
        "benchmark_score_claimed": False,
        "production_training_ready": False,
    }
    return {**base, "contract_hash": content_hash(base)}


def expected_v17_collection_overlay() -> dict[str, Any]:
    """Return the compact file identity for the code-frozen formal contract."""

    contract = expected_v17_collection_contract()
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_COLLECTION_FORMAT,
        "scope": contract["scope"],
        "parent_canary_contract_file": contract["parent_canary"]["contract_file"],
        "parent_canary_contract_file_sha256": contract["parent_canary"]["contract_file_sha256"],
        "parent_canary_contract_hash": contract["parent_canary"]["contract_hash"],
        "formal_contract_hash": contract["contract_hash"],
    }
    return {**base, "overlay_hash": content_hash(base)}


def load_v17_collection_contract(path: Path) -> dict[str, Any]:
    """Load only the exact formal collection contract."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 512 * 1024:
        raise ValueError("OpenHands v17 formal contract must be a small regular file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value != expected_v17_collection_overlay():
        raise ValueError("OpenHands v17 formal collection contract identity changed")
    return expected_v17_collection_contract()


def validate_v17_collection_source(
    contract: Mapping[str, Any],
    *,
    split: TaskSplitManifest,
    task_split_path: Path,
    qualification_progress_path: Path,
) -> TaskSplitManifest:
    """Bind all public formal tasks while preserving the held-out boundary."""

    if dict(contract) != expected_v17_collection_contract():
        raise ValueError("OpenHands v17 formal collection contract identity changed")
    _canary.validate_v17_canary_source(
        _canary.expected_v17_canary_contract(),
        split=split,
        task_split_path=task_split_path,
        qualification_progress_path=qualification_progress_path,
    )
    derived = _canary.derive_v17_v3_task_split(split)
    entries = {entry.task_id: entry for entry in (*derived.training, *derived.validation)}
    roles = {
        entry.task_id: role
        for role, values in (("training", derived.training), ("validation", derived.validation))
        for entry in values
    }
    for task_id, binding in contract["task_bindings"].items():
        entry = entries.get(task_id)
        if (
            entry is None
            or entry.task_hash != binding["task_hash"]
            or entry.source_hash != binding["source_hash"]
            or roles.get(task_id) != binding["role"]
        ):
            raise ValueError("OpenHands v17 formal task/source/role binding changed")
    return derived


def validate_v17_collection_image_locks(
    contract: Mapping[str, Any], image_locks: Mapping[str, Any]
) -> None:
    """Reject any task/image or isolation drift."""

    if set(image_locks) != set(OPENHANDS_V17_IDENTITY_TASKS):
        raise ValueError("OpenHands v17 formal collection image-lock set changed")
    for task_id, lock in image_locks.items():
        binding = contract["task_bindings"][task_id]
        if (
            getattr(lock, "task_id", None) != task_id
            or getattr(lock, "task_hash", None) != binding["task_hash"]
            or getattr(lock, "source_hash", None) != binding["source_hash"]
            or getattr(lock, "lock_hash", None) != binding["image_lock_hash"]
            or getattr(lock, "derived_agent_image_id", None) != binding["agent_image"]
            or getattr(lock, "verifier_base_image_id", None) != binding["verifier_image"]
            or getattr(lock, "runtime_network", None) != "none"
            or getattr(lock, "hidden_assets_present", True)
            or getattr(lock, "reference_patch_present", True)
            or getattr(lock, "provider_credentials_present", True)
            or getattr(lock, "verifier_payload_present", True)
            or not getattr(lock, "security_scan_passed", False)
        ):
            raise ValueError("OpenHands v17 formal image-lock binding changed")


def build_v17_collection_agent_version(
    *, source_commit: str, image_locks: Mapping[str, Any]
) -> AgentVersionManifest:
    """Create a distinct formal identity without relabeling the canary agent."""

    contract = expected_v17_collection_contract()
    validate_v17_collection_image_locks(contract, image_locks)
    canary_locks = {task_id: image_locks[task_id] for task_id in _canary.OPENHANDS_V17_CANARY_TASKS}
    template = _canary.build_v17_canary_agent_version(
        source_commit=source_commit,
        image_locks=canary_locks,
    )
    values = template.model_dump(mode="json", exclude={"version_hash"})
    values.update(
        {
            "agent_version_id": OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
            "runtime_identity_hash": content_hash(
                {
                    "parent_runtime_identity_hash": template.runtime_identity_hash,
                    "formal_contract_hash": contract["contract_hash"],
                    "formal_task_image_lock_hashes": {
                        task_id: contract["task_bindings"][task_id]["image_lock_hash"]
                        for task_id in OPENHANDS_V17_IDENTITY_TASKS
                    },
                    "seed": OPENHANDS_V17_COLLECTION_SEED,
                    "sample_index": OPENHANDS_V17_COLLECTION_SAMPLE_INDEX,
                    "task_retries": 0,
                    "provider_request_retries": 0,
                }
            ),
            "image_hashes": {
                f"pr{task_id.rsplit('-', 1)[-1]}-{kind}": binding[field].removeprefix("sha256:")
                for task_id, binding in contract["task_bindings"].items()
                for kind, field in (("agent", "agent_image"), ("verifier", "verifier_image"))
            },
        }
    )
    return validate_agent_version(build_agent_version(**values))


def build_v17_collection_agent_options(
    *, seed: int, agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Build formal v18 options with no provider or episode retry."""

    version = validate_agent_version(agent_version)
    if (
        seed != OPENHANDS_V17_COLLECTION_SEED
        or version.agent_version_id != OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != OPENHANDS_V17_COLLECTION_MODEL
    ):
        raise ValueError("OpenHands v17 formal options require the frozen identity")
    return validate_plugin_options(
        {
            "model_id": OPENHANDS_V17_COLLECTION_MODEL,
            "base_url_env": OPENHANDS_V17_COLLECTION_BASE_URL_ENV,
            "api_key_env": OPENHANDS_V17_COLLECTION_API_KEY_ENV,
            "max_iterations": OPENHANDS_V17_COLLECTION_MAX_ITERATIONS,
            "max_process_time_s": 3_600,
            "max_output_tokens": OPENHANDS_V17_COLLECTION_MAX_OUTPUT_TOKENS,
            "max_context_tokens": OPENHANDS_V17_COLLECTION_MAX_CONTEXT_TOKENS,
            "seed": seed,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "expected_sdk_version": OPENHANDS_V17_COLLECTION_SDK_VERSION,
            "campaign_role": "training",
            "capture_training_transcript": True,
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": json.dumps(
                version.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ),
            "collection_profile_id": "hwe_production_native_shell_v2",
            "tool_choice_policy": OPENHANDS_V17_COLLECTION_TOOL_CHOICE_POLICY,
        }
    )


def evaluate_v17_collection_gate(attempts: Sequence[Mapping[str, Any]]) -> V17CollectionGate:
    """Recompute distinct pass capacity after every attempt and stop at the target."""

    allowed = set(OPENHANDS_V17_ALL_COLLECTION_TASKS)
    seen: set[str] = set()
    passed: dict[str, set[str]] = {"training": set(), "validation": set()}
    attempted: dict[str, set[str]] = {"training": set(), "validation": set()}
    for position, item in enumerate(attempts):
        task_id = item.get("task_id")
        role = item.get("role")
        if task_id not in allowed or task_id in seen or role not in passed:
            raise ValueError("OpenHands v17 formal attempts are duplicated or out of scope")
        if position < len(OPENHANDS_V17_IMPORTED_TRAINING_TASKS):
            if task_id != OPENHANDS_V17_IMPORTED_TRAINING_TASKS[position] or role != "training":
                raise ValueError("OpenHands v17 canary import order changed")
        elif role == "training":
            training_index = len(attempted["training"]) - len(OPENHANDS_V17_IMPORTED_TRAINING_TASKS)
            if (
                attempted["validation"]
                or len(passed["training"]) >= OPENHANDS_V17_TRAINING_TARGET
                or training_index >= len(OPENHANDS_V17_FORMAL_TRAINING_ORDER)
                or task_id != OPENHANDS_V17_FORMAL_TRAINING_ORDER[training_index]
            ):
                raise ValueError("OpenHands v17 formal training order or stop target changed")
        else:
            validation_index = len(attempted["validation"])
            if (
                len(passed["training"]) < OPENHANDS_V17_TRAINING_TARGET
                or len(passed["validation"]) >= OPENHANDS_V17_VALIDATION_TARGET
                or validation_index >= len(OPENHANDS_V17_FORMAL_VALIDATION_ORDER)
                or task_id != OPENHANDS_V17_FORMAL_VALIDATION_ORDER[validation_index]
            ):
                raise ValueError("OpenHands v17 formal validation order or role boundary changed")
        seen.add(str(task_id))
        attempted[str(role)].add(str(task_id))
        if (
            item.get("infrastructure_valid") is not True
            or item.get("security_scan_passed") is not True
            or item.get("truncation_applied") is not False
        ):
            return _gate(
                False,
                False,
                None,
                "infrastructure_or_security_invalid",
                passed,
                attempted,
            )
        if item.get("exact_64k_eligible") is True:
            if (
                item.get("ordinary_verifier_resolved") is not True
                or item.get("fresh_exact_trajectory") is not True
            ):
                raise ValueError("OpenHands v17 formal eligible attempt lacks exact verifier proof")
            passed[str(role)].add(str(task_id))
    training_done = len(passed["training"]) >= OPENHANDS_V17_TRAINING_TARGET
    validation_done = len(passed["validation"]) >= OPENHANDS_V17_VALIDATION_TARGET
    remaining_training = set(OPENHANDS_V17_FORMAL_TRAINING_ORDER) - attempted["training"]
    remaining_validation = set(OPENHANDS_V17_FORMAL_VALIDATION_ORDER) - attempted["validation"]
    training_possible = (
        len(passed["training"]) + len(remaining_training) >= OPENHANDS_V17_TRAINING_TARGET
    )
    validation_possible = (
        len(passed["validation"]) + len(remaining_validation) >= OPENHANDS_V17_VALIDATION_TARGET
    )
    if not training_possible:
        return _gate(False, False, None, "training_capacity_exhausted", passed, attempted)
    if training_done and not validation_possible:
        return _gate(False, False, None, "validation_capacity_exhausted", passed, attempted)
    if training_done and validation_done:
        return _gate(True, True, None, "targets_satisfied", passed, attempted)
    return _gate(
        False,
        True,
        "validation" if training_done else "training",
        "continue_validation" if training_done else "continue_training",
        passed,
        attempted,
    )


def seal_v17_collection_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal one report without hashing credential values."""

    base = copy.deepcopy(dict(value))
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def validate_canary_import_root(root: Path, contract: Mapping[str, Any]) -> dict[str, Path]:
    """Validate the sealed canary root and return exactly two trajectory paths."""

    directory = root.resolve(strict=True)
    expected_files = {
        "canary-report.json": _CANARY_REPORT_SHA256,
        "canary-gate.json": _CANARY_GATE_SHA256,
        "agent-version.json": _CANARY_AGENT_VERSION_SHA256,
    }
    for name, expected in expected_files.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or hash_bytes(path.read_bytes()) != expected:
            raise ValueError("OpenHands v17 canary sealed evidence changed")
    report = json.loads((directory / "canary-report.json").read_bytes())
    if (
        report.get("report_hash") != contract["parent_canary"]["report_hash"]
        or report.get("formal_collection_allowed") is not True
        or report.get("production_training_ready") is not False
    ):
        raise ValueError("OpenHands v17 canary did not authorize formal collection")
    trajectories: dict[str, Path] = {}
    for task_id, receipt in contract["canary_imports"].items():
        path = (
            directory
            / "runs"
            / receipt["episode_id"]
            / "artifacts"
            / "openhands_sdk"
            / "training-trajectory.json"
        )
        if (
            path.is_symlink()
            or not path.is_file()
            or hash_bytes(path.read_bytes()) != receipt["trajectory_file_sha256"]
        ):
            raise ValueError("OpenHands v17 imported canary trajectory changed")
        trajectories[task_id] = path
    return trajectories


def _gate(
    satisfied: bool,
    possible: bool,
    next_role: str | None,
    reason: str,
    passed: Mapping[str, set[str]],
    attempted: Mapping[str, set[str]],
) -> V17CollectionGate:
    remaining_training = len(set(OPENHANDS_V17_FORMAL_TRAINING_ORDER) - attempted["training"])
    remaining_validation = len(set(OPENHANDS_V17_FORMAL_VALIDATION_ORDER) - attempted["validation"])
    return V17CollectionGate(
        satisfied=satisfied,
        possible=possible,
        next_role=next_role,
        reason=reason,
        training_pass_count=len(passed["training"]),
        validation_pass_count=len(passed["validation"]),
        remaining_training_task_count=remaining_training,
        remaining_validation_task_count=remaining_validation,
        maximum_training_pass_count=len(passed["training"]) + remaining_training,
        maximum_validation_pass_count=len(passed["validation"]) + remaining_validation,
    )


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V17_")] + [
    "V17CollectionGate",
    "build_v17_collection_agent_options",
    "build_v17_collection_agent_version",
    "evaluate_v17_collection_gate",
    "expected_v17_collection_contract",
    "expected_v17_collection_overlay",
    "load_v17_collection_contract",
    "seal_v17_collection_report",
    "validate_canary_import_root",
    "validate_v17_collection_image_locks",
    "validate_v17_collection_source",
]
