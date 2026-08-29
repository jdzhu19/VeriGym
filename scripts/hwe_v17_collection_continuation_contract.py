"""Frozen v17 formal continuation contract and PR-2282 recovery evidence."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from verigym_openhands import hwe_v17_collection as _v1

from verigym.core.hashing import content_hash, hash_bytes
from verigym.plugin_api import JsonValue
from verigym.schemas.evolution import AgentVersionManifest, TaskSplitManifest

OPENHANDS_V17_CONTINUATION_FORMAT = "verigym_openhands_hwe_v17_formal_continuation_v2"
OPENHANDS_V17_CONTINUATION_REPORT_FORMAT = "verigym_openhands_hwe_v17_formal_continuation_report_v2"
OPENHANDS_V17_CONTINUATION_GATE_FORMAT = "verigym_openhands_hwe_v17_formal_continuation_gate_v2"
OPENHANDS_V17_CONTINUATION_CAMPAIGN_ID = "openhands-hwe-v17-formal-continuation-v2"
OPENHANDS_V17_CONTINUATION_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V17_FORMAL_CONTINUATION_V2"
OPENHANDS_V17_CONTINUATION_CONTRACT_FILE = (
    "qwen35_hwe_openhands_v17_collection_continuation_v2.json"
)
OPENHANDS_V17_RECOVERY_TASK = _v1.OPENHANDS_V17_FORMAL_TRAINING_ORDER[0]
OPENHANDS_V17_REMAINING_FORMAL_TASKS = (
    *_v1.OPENHANDS_V17_FORMAL_TRAINING_ORDER[1:],
    *_v1.OPENHANDS_V17_FORMAL_VALIDATION_ORDER,
)
OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT = "2980f6c9900d4d5b9d609adb3f50ac213d6f5426"
OPENHANDS_V17_FROZEN_AGENT_VERSION_HASH = (
    "4203ffe35823ba6ba83fa5ab5c351b19dc3a58cd4265c22cdb07883975bbe521"
)

_V1_CONTRACT_FILE_SHA256 = "ddcdb4c0181b6af8b2c3623f0337b3f9b784967311f610d4583d1f0e6caa4b12"
_RECOVERY_ROOT_FILES = {
    "agent-version.json": "3297824b8c1709763ddcb284d53bb1195592e1cef7e0851f5a0c875085120e23",
    "image-lock-receipt.json": ("7ee4027f676b276e1cd829b8988d68c27e80122ae4230434dd8eba3460c9c12b"),
    "preregistration.json": "2f7cce3e57cdc30d295e923e196ee8b4eacdf6a748792edbd56fd6eeb2c00b3d",
    "campaign-progress.json": ("2f7cce3e57cdc30d295e923e196ee8b4eacdf6a748792edbd56fd6eeb2c00b3d"),
}
_RECOVERY_RUN_FILES = {
    "runs/training-pr2282-s487/scorecard.json": (
        "1d3c1ec74b909fbadf346349666f5c190f16ea4c86129d981ec51aee4ad786be"
    ),
    "runs/training-pr2282-s487/artifact_manifest.json": (
        "9c519785bf24fafadc7d7bdfe349c357f83005f9cbdfe97c6d4bfccccdd0048f"
    ),
    "runs/training-pr2282-s487/artifacts/openhands_sdk/accounting.json": (
        "341f9b5cd171554bad39c16809dd70b5a759edde198410f602a59e6b9089afa0"
    ),
    "runs/training-pr2282-s487/artifacts/openhands_sdk/broker.json": (
        "8b559b844f9b1539d21672a9ced0883af19b7555aada2ed21eba20a53689e400"
    ),
    "runs/training-pr2282-s487/artifacts/openhands_sdk/summary.json": (
        "d9cf8552fa779a7a773fdad6dec819639871c19cdb0e0a8a588e9dc61eeffd59"
    ),
    "runs/training-pr2282-s487/artifacts/openhands_sdk/training-trajectory.json": (
        "2b1322e65a137635ccf0931808ab1e33c8a273bf1039d28657e0b3526ce2ad8f"
    ),
    "security-scans/training-pr2282-s487.json": (
        "8834d6925e2f7f8e92cf59a58c4f74011721010ffad9c10018805d81f9cde025"
    ),
    "trajectory-records/training-pr2282-s487.jsonl": (
        "cc31dcece94a7f37c3db6af2c7648c1213800891c5a7192f80f82a628028db8e"
    ),
}
_RECOVERY_RECEIPT = {
    "task_id": OPENHANDS_V17_RECOVERY_TASK,
    "episode_id": "training-pr2282-s487",
    "seed": _v1.OPENHANDS_V17_COLLECTION_SEED,
    "sample_index": _v1.OPENHANDS_V17_COLLECTION_SAMPLE_INDEX,
    "source_commit": OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
    "agent_version_id": _v1.OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
    "agent_version_hash": OPENHANDS_V17_FROZEN_AGENT_VERSION_HASH,
    "run_hash": "4970a9ba6ce338991faf3bdf5417cb5411e1aafa7b9deb4261d3c9a8933ae3e9",
    "candidate_hash": "7c9eac4c3ba6ac08ace5c78e833ce601338caa7c56bd3feda365b17b50f1f41c",
    "verifier_hash": "780dab01e7e9ad19a253b0d0838a90497c9c5dd5d8770c4819b847eaaca4fab8",
    "trajectory_file_sha256": _RECOVERY_RUN_FILES[
        "runs/training-pr2282-s487/artifacts/openhands_sdk/training-trajectory.json"
    ],
    "transcript_hash": "6461692703555a11cc93e43ce0f69e92b3d7bbf96b6ca5b0882d5a63137e9740",
    "assistant_decision_count": 32,
    "materialized_record_count": 32,
    "max_materialized_record_tokens": 42_915,
    "partial_records_sha256": _RECOVERY_RUN_FILES["trajectory-records/training-pr2282-s487.jsonl"],
    "security_report_hash": ("28727d0135ede7a2e310648a4834ffef7c2a17d89e227068df5ccb749a0b4721"),
    "crash_boundary": "trajectory_record_manifest_before_campaign_progress",
    "provider_episode_retry_allowed": False,
}


def expected_v17_continuation_contract() -> dict[str, Any]:
    """Return the exact continuation contract without changing the frozen agent."""

    parent = _v1.expected_v17_collection_contract()
    collection = copy.deepcopy(parent["collection"])
    collection.update(
        {
            "recovery_import_task_id": OPENHANDS_V17_RECOVERY_TASK,
            "provider_training_attempt_order": list(_v1.OPENHANDS_V17_FORMAL_TRAINING_ORDER[1:]),
            "provider_validation_attempt_order": list(_v1.OPENHANDS_V17_FORMAL_VALIDATION_ORDER),
            "recovery_task_reexecution_allowed": False,
        }
    )
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_CONTINUATION_FORMAT,
        "scope": "exact_64k_development_sft_formal_collection_continuation",
        "parent_formal": {
            "contract_file": _v1.OPENHANDS_V17_COLLECTION_CONTRACT_FILE,
            "contract_file_sha256": _V1_CONTRACT_FILE_SHA256,
            "contract_hash": parent["contract_hash"],
            "campaign_id": _v1.OPENHANDS_V17_COLLECTION_CAMPAIGN_ID,
            "crashed_before_campaign_report": True,
        },
        "frozen_agent": {
            "agent_version_id": _v1.OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
            "agent_version_hash": OPENHANDS_V17_FROZEN_AGENT_VERSION_HASH,
            "source_commit": OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
            "agent_behavior_changed": False,
        },
        "recovery_root_files": copy.deepcopy(_RECOVERY_ROOT_FILES),
        "recovery_run_files": copy.deepcopy(_RECOVERY_RUN_FILES),
        "recovery_import": copy.deepcopy(_RECOVERY_RECEIPT),
        "source": copy.deepcopy(parent["source"]),
        "teacher": copy.deepcopy(parent["teacher"]),
        "task_bindings": copy.deepcopy(parent["task_bindings"]),
        "canary_imports": copy.deepcopy(parent["canary_imports"]),
        "collection": collection,
        "student": copy.deepcopy(parent["student"]),
        "dataset": copy.deepcopy(parent["dataset"]),
        "heldout_task_ids_loaded": [],
        "benchmark_score_claimed": False,
        "production_training_ready": False,
    }
    return {**base, "contract_hash": content_hash(base)}


def expected_v17_continuation_overlay() -> dict[str, Any]:
    """Return the compact checked-in continuation identity."""

    contract = expected_v17_continuation_contract()
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_CONTINUATION_FORMAT,
        "scope": contract["scope"],
        "parent_formal_contract_file": contract["parent_formal"]["contract_file"],
        "parent_formal_contract_file_sha256": contract["parent_formal"]["contract_file_sha256"],
        "parent_formal_contract_hash": contract["parent_formal"]["contract_hash"],
        "continuation_contract_hash": contract["contract_hash"],
    }
    return {**base, "overlay_hash": content_hash(base)}


def load_v17_continuation_contract(path: Path) -> dict[str, Any]:
    """Load only the exact v2 continuation contract."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 512 * 1024:
        raise ValueError("OpenHands v17 continuation contract must be a small regular file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value != expected_v17_continuation_overlay():
        raise ValueError("OpenHands v17 continuation contract identity changed")
    return expected_v17_continuation_contract()


def validate_v17_continuation_source(
    contract: Mapping[str, Any],
    *,
    split: TaskSplitManifest,
    task_split_path: Path,
    qualification_progress_path: Path,
) -> TaskSplitManifest:
    """Delegate source validation to the unchanged formal task universe."""

    if dict(contract) != expected_v17_continuation_contract():
        raise ValueError("OpenHands v17 continuation contract identity changed")
    return _v1.validate_v17_collection_source(
        _v1.expected_v17_collection_contract(),
        split=split,
        task_split_path=task_split_path,
        qualification_progress_path=qualification_progress_path,
    )


def validate_v17_continuation_image_locks(
    contract: Mapping[str, Any], image_locks: Mapping[str, Any]
) -> None:
    """Retain the exact v1 task/image and isolation bindings."""

    if dict(contract) != expected_v17_continuation_contract():
        raise ValueError("OpenHands v17 continuation contract identity changed")
    _v1.validate_v17_collection_image_locks(_v1.expected_v17_collection_contract(), image_locks)


def build_v17_continuation_agent_version(*, image_locks: Mapping[str, Any]) -> AgentVersionManifest:
    """Rebuild the exact v1 agent identity from its original source commit."""

    version = _v1.build_v17_collection_agent_version(
        source_commit=OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
        image_locks=image_locks,
    )
    if version.version_hash != OPENHANDS_V17_FROZEN_AGENT_VERSION_HASH:
        raise ValueError("OpenHands v17 continuation frozen agent identity changed")
    return version


def build_v17_continuation_agent_options(
    *, seed: int, agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Use the unchanged v1 provider-visible options."""

    options: dict[str, JsonValue] = _v1.build_v17_collection_agent_options(
        seed=seed,
        agent_version=agent_version,
    )
    return options


def evaluate_v17_continuation_gate(
    attempts: Sequence[Mapping[str, Any]],
) -> _v1.V17CollectionGate:
    """Apply the original order/capacity gate, including the imported PR-2282 attempt."""

    return _v1.evaluate_v17_collection_gate(attempts)


def validate_v17_recovery_root(root: Path, contract: Mapping[str, Any]) -> Path:
    """Validate the crashed v1 root and return only its verifier-passed trajectory."""

    if dict(contract) != expected_v17_continuation_contract():
        raise ValueError("OpenHands v17 continuation contract identity changed")
    if root.is_symlink():
        raise ValueError("OpenHands v17 recovery root is unsafe")
    directory = root.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("OpenHands v17 recovery root is unsafe")
    for relative, expected in {
        **contract["recovery_root_files"],
        **contract["recovery_run_files"],
    }.items():
        path = directory / relative
        component = directory
        symlinked = False
        for part in Path(relative).parts:
            component /= part
            symlinked = symlinked or component.is_symlink()
        if symlinked or not path.is_file() or hash_bytes(path.read_bytes()) != expected:
            raise ValueError("OpenHands v17 recovery evidence changed")
    for relative in (
        "campaign-report.json",
        "data-gate.json",
        "trajectory-records/training-pr2282-s487.manifest.json",
    ):
        if (directory / relative).exists() or (directory / relative).is_symlink():
            raise ValueError("OpenHands v17 recovery crash boundary changed")

    progress = json.loads((directory / "campaign-progress.json").read_bytes())
    if (
        progress.get("status") != "formal_collection_running"
        or progress.get("campaign_id") != _v1.OPENHANDS_V17_COLLECTION_CAMPAIGN_ID
        or progress.get("source_commit") != OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT
        or progress.get("agent_version_hash") != OPENHANDS_V17_FROZEN_AGENT_VERSION_HASH
        or [item.get("episode_id") for item in progress.get("attempts", [])]
        != ["training-pr2944-s486", "training-pr2248-s486"]
    ):
        raise ValueError("OpenHands v17 recovery progress boundary changed")
    agent = json.loads((directory / "agent-version.json").read_bytes())
    if (
        agent.get("agent_version_id") != _v1.OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID
        or agent.get("version_hash") != OPENHANDS_V17_FROZEN_AGENT_VERSION_HASH
        or agent.get("source_commit") != OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT
    ):
        raise ValueError("OpenHands v17 recovery agent identity changed")

    receipt = contract["recovery_import"]
    scorecard = json.loads((directory / "runs/training-pr2282-s487/scorecard.json").read_bytes())
    reproducibility = scorecard.get("reproducibility")
    if (
        scorecard.get("run_id") != receipt["episode_id"]
        or scorecard.get("task_id") != receipt["task_id"]
        or scorecard.get("resolved") is not True
        or scorecard.get("failure") is not None
        or not isinstance(reproducibility, dict)
        or reproducibility.get("candidate_hash") != receipt["candidate_hash"]
        or reproducibility.get("verifier_hash") != receipt["verifier_hash"]
        or content_hash({"run_id": receipt["episode_id"], "scorecard": scorecard})
        != receipt["run_hash"]
    ):
        raise ValueError("OpenHands v17 recovery scorecard changed")
    trajectory_path = (
        directory / "runs/training-pr2282-s487/artifacts/openhands_sdk/training-trajectory.json"
    )
    trajectory = json.loads(trajectory_path.read_bytes())
    if (
        trajectory.get("task_id") != receipt["task_id"]
        or trajectory.get("transcript_hash") != receipt["transcript_hash"]
        or trajectory.get("assistant_decision_count") != receipt["assistant_decision_count"]
        or trajectory.get("verifier_resolved") is not True
        or trajectory.get("sft_eligible") is not True
        or trajectory.get("typed_finish_observed") is not True
        or trajectory.get("exact_model_visible_context") is not True
        or trajectory.get("raw_host_paths_exported") is not False
        or trajectory.get("credential_values_exported") is not False
    ):
        raise ValueError("OpenHands v17 recovery trajectory changed")
    scan = json.loads((directory / "security-scans/training-pr2282-s487.json").read_bytes())
    if scan.get("gate") != "pass" or scan.get("report_hash") != receipt["security_report_hash"]:
        raise ValueError("OpenHands v17 recovery security scan changed")
    return trajectory_path


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V17_")] + [
    "build_v17_continuation_agent_options",
    "build_v17_continuation_agent_version",
    "evaluate_v17_continuation_gate",
    "expected_v17_continuation_contract",
    "expected_v17_continuation_overlay",
    "load_v17_continuation_contract",
    "validate_v17_continuation_image_locks",
    "validate_v17_continuation_source",
    "validate_v17_recovery_root",
]
