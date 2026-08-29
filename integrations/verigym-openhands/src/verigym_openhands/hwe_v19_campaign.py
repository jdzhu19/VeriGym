"""Frozen v19 public-task qualification, canary, and collection gates."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash

from .hwe_v19 import (
    validate_v19_campaign_result,
    validate_v19_decision_receipt,
    validate_v19_protocol_receipt,
    validate_v19_trajectory_receipt,
)
from .hwe_v19_protocol import (
    OPENHANDS_V19_MAX_CONTEXT_TOKENS,
    OPENHANDS_V19_MAX_OUTPUT_TOKENS,
    OPENHANDS_V19_MAX_PROVIDER_CALLS,
    OPENHANDS_V19_MAX_PROVIDER_TOKENS,
    OPENHANDS_V19_TOOL_CHOICE_POLICY,
)

OPENHANDS_V19_QUALIFICATION_FORMAT = "verigym_openhands_hwe_v19_qualification_v1"
OPENHANDS_V19_CANARY_CONTRACT_FORMAT = "verigym_openhands_hwe_v19_canary_contract_v1"
OPENHANDS_V19_CANARY_CAMPAIGN_ID = "openhands-hwe-v19-required-tool-canary-v1"
OPENHANDS_V19_CANARY_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v19-canary-v1"
OPENHANDS_V19_COLLECTION_CAMPAIGN_ID = "openhands-hwe-v19-formal-collection-v1"
OPENHANDS_V19_COLLECTION_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-v19-formal-collection-v1"
)
OPENHANDS_V19_CANARY_SEED = 489
OPENHANDS_V19_CANARY_SAMPLE_INDEX = 5
OPENHANDS_V19_COLLECTION_SEED = 490
OPENHANDS_V19_COLLECTION_SAMPLE_INDEX = 6
OPENHANDS_V19_TRAINING_TARGET = 8
OPENHANDS_V19_VALIDATION_TARGET = 2
OPENHANDS_V19_QUALIFIED_TASK_TARGET = 5
OPENHANDS_V19_TRAINING_RESERVE_COUNT = 3
OPENHANDS_V19_VALIDATION_RESERVE_COUNT = 2


def _task(number: int) -> str:
    return f"hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-{number}"


OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS = (2330, 3226, 2844, 3231, 2989, 1482, 3059)
OPENHANDS_V19_QUALIFICATION_CANDIDATES = tuple(
    _task(number) for number in OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS
)
OPENHANDS_V19_PRIOR_TRAINING_PASSES = (_task(2944), _task(2248), _task(2282))
OPENHANDS_V19_HISTORICAL_ATTEMPTS = (_task(2032), _task(2468), _task(2469), _task(3191))
OPENHANDS_V19_EXISTING_TRAINING_VALIDATION = tuple(
    _task(number)
    for number in (2032, 2248, 2282, 2468, 2469, 2549, 2589, 2802, 2916, 2944, 3168, 3191, 3204)
)
OPENHANDS_V19_PR2170 = _task(2170)
OPENHANDS_V19_HELDOUT_TASKS = (
    "hwe-bench/repo-repair-v1/chipsalliance__rocket-chip__pr-3065",
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-222",
    _task(2374),
    _task(2945),
    _task(3107),
    _task(3171),
)
OPENHANDS_V19_FIXED_TRAINING_ORDER = tuple(_task(number) for number in (2549, 2589, 2802, 2916))
OPENHANDS_V19_FIXED_VALIDATION_ORDER = (_task(3168),)
OPENHANDS_V19_CANARY_VALIDATION_TASK = _task(3204)


@dataclass(frozen=True)
class V19QualificationGate:
    satisfied: bool
    stopped: bool
    reason: str | None
    next_task_id: str | None
    qualified_task_ids: tuple[str, ...]
    training_reserve_task_ids: tuple[str, ...]
    validation_reserve_task_ids: tuple[str, ...]


@dataclass(frozen=True)
class V19CollectionGate:
    satisfied: bool
    possible: bool
    stopped: bool
    reason: str | None
    next_role: str | None
    next_task_id: str | None
    training_pass_count: int
    validation_pass_count: int
    remaining_training_capacity: int
    remaining_validation_capacity: int


def frozen_v19_candidate_inventory(dataset: Path) -> list[dict[str, Any]]:
    """Read only the seven frozen public candidates and verify `(lines, PR)` order."""

    if dataset.is_symlink() or not dataset.is_file() or dataset.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("OpenHands v19 qualification dataset is not a bounded regular file")
    selected: dict[int, dict[str, Any]] = {}
    for line in dataset.read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("OpenHands v19 qualification dataset contains a non-object")
        number = raw.get("number")
        if number not in OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS:
            continue
        if (
            raw.get("org") != "openhwgroup"
            or raw.get("repo") != "cva6"
            or not isinstance(raw.get("fix_patch"), str)
            or not isinstance(raw.get("modified_files"), list)
            or any(not isinstance(item, str) for item in raw["modified_files"])
        ):
            raise ValueError("OpenHands v19 qualification candidate identity changed")
        changed = _changed_lines(raw["fix_patch"])
        selected[number] = {
            "number": number,
            "task_id": _task(number),
            "instance_id": f"openhwgroup/cva6:pr-{number}",
            "changed_line_count": changed,
            "modified_file_count": len(set(raw["modified_files"])),
        }
    if set(selected) != set(OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS):
        raise ValueError("OpenHands v19 qualification dataset lacks a frozen candidate")
    ordered = sorted(
        selected.values(), key=lambda item: (item["changed_line_count"], item["number"])
    )
    if [item["number"] for item in ordered] != list(OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS):
        raise ValueError("OpenHands v19 qualification candidate order changed")
    excluded = set(OPENHANDS_V19_EXISTING_TRAINING_VALIDATION) | {
        OPENHANDS_V19_PR2170,
        *OPENHANDS_V19_HISTORICAL_ATTEMPTS,
        *OPENHANDS_V19_HELDOUT_TASKS,
    }
    if any(item["task_id"] in excluded for item in ordered):
        raise ValueError("OpenHands v19 qualification candidate overlaps excluded evidence")
    return ordered


def evaluate_v19_qualification_gate(
    outcomes: Sequence[Mapping[str, Any]],
) -> V19QualificationGate:
    """Stop on infrastructure invalidity and require five ordered qualified tasks."""

    if len(outcomes) > len(OPENHANDS_V19_QUALIFICATION_CANDIDATES):
        raise ValueError("OpenHands v19 qualification has too many outcomes")
    qualified: list[str] = []
    for index, raw in enumerate(outcomes):
        task_id = raw.get("task_id")
        if task_id != OPENHANDS_V19_QUALIFICATION_CANDIDATES[index]:
            raise ValueError("OpenHands v19 qualification outcomes are out of order")
        if len(qualified) >= OPENHANDS_V19_QUALIFIED_TASK_TARGET:
            raise ValueError("OpenHands v19 qualification continued after reaching capacity")
        infrastructure_valid = raw.get("infrastructure_valid")
        if not isinstance(infrastructure_valid, bool):
            raise ValueError("OpenHands v19 qualification infrastructure state is missing")
        if not infrastructure_valid:
            return _qualification_gate(
                qualified,
                stopped=True,
                reason="infrastructure_invalid",
                next_task_id=None,
            )
        if (
            raw.get("verifier_network") != "none"
            or isinstance(raw.get("model_process_count"), bool)
            or raw.get("model_process_count") != 0
            or not _digest_image(raw.get("verifier_image"))
        ):
            return _qualification_gate(
                qualified,
                stopped=True,
                reason="qualification_security_invalid",
                next_task_id=None,
            )
        qualified_match = raw.get("base_failed") is True and raw.get("reference_passed") is True
        if qualified_match:
            qualified.append(str(task_id))
    if len(qualified) >= OPENHANDS_V19_QUALIFIED_TASK_TARGET:
        return _qualification_gate(qualified, stopped=False, reason=None, next_task_id=None)
    if len(outcomes) == len(OPENHANDS_V19_QUALIFICATION_CANDIDATES):
        return _qualification_gate(
            qualified,
            stopped=True,
            reason="fewer_than_five_qualified_tasks",
            next_task_id=None,
        )
    return _qualification_gate(
        qualified,
        stopped=False,
        reason="qualification_incomplete",
        next_task_id=OPENHANDS_V19_QUALIFICATION_CANDIDATES[len(outcomes)],
    )


def seal_v19_qualification_receipt(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Seal sanitized hashes and reserve roles; source trees remain outside Git."""

    gate = evaluate_v19_qualification_gate(outcomes)
    if not gate.satisfied:
        raise ValueError("OpenHands v19 qualification receipt requires five tasks")
    tasks: list[dict[str, Any]] = []
    outcomes_by_task = {str(item.get("task_id")): item for item in outcomes}
    for task_id in gate.qualified_task_ids:
        binding = bindings.get(task_id)
        if not isinstance(binding, Mapping):
            raise ValueError("OpenHands v19 qualified task binding is missing")
        sanitized_binding = _validated_qualification_binding(binding)
        outcome = outcomes_by_task[task_id]
        if outcome.get("verifier_image") != sanitized_binding["verifier_image"]:
            raise ValueError("OpenHands v19 qualification verifier binding changed")
        safe_outcome = {
            "task_id": task_id,
            "infrastructure_valid": True,
            "verifier_network": "none",
            "verifier_image": outcome["verifier_image"],
            "model_process_count": 0,
            "base_failed": True,
            "reference_passed": True,
        }
        tasks.append(
            {
                "task_id": task_id,
                "role": (
                    "training_reserve"
                    if task_id in gate.training_reserve_task_ids
                    else "validation_reserve"
                ),
                **sanitized_binding,
                "qualification_outcome_hash": content_hash(safe_outcome),
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V19_QUALIFICATION_FORMAT,
        "candidate_order": list(OPENHANDS_V19_QUALIFICATION_CANDIDATES),
        "qualified_task_count": len(tasks),
        "tasks": tasks,
        "training_reserve_task_ids": list(gate.training_reserve_task_ids),
        "validation_reserve_task_ids": list(gate.validation_reserve_task_ids),
        "heldout_task_ids_loaded": [],
        "model_process_count": 0,
        "verifier_network": "none",
    }
    return validate_v19_qualification_receipt({**base, "receipt_hash": content_hash(base)})


def validate_v19_qualification_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the sanitized five-task qualification and its fixed 3/2 roles."""

    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("receipt_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v19 qualification receipt identity changed")
    training = result.get("training_reserve_task_ids")
    validation = result.get("validation_reserve_task_ids")
    tasks = result.get("tasks")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V19_QUALIFICATION_FORMAT
        or result.get("candidate_order") != list(OPENHANDS_V19_QUALIFICATION_CANDIDATES)
        or result.get("qualified_task_count") != OPENHANDS_V19_QUALIFIED_TASK_TARGET
        or not isinstance(training, list)
        or len(training) != OPENHANDS_V19_TRAINING_RESERVE_COUNT
        or not isinstance(validation, list)
        or len(validation) != OPENHANDS_V19_VALIDATION_RESERVE_COUNT
        or not isinstance(tasks, list)
        or len(tasks) != OPENHANDS_V19_QUALIFIED_TASK_TARGET
        or result.get("heldout_task_ids_loaded") != []
        or isinstance(result.get("model_process_count"), bool)
        or result.get("model_process_count") != 0
        or result.get("verifier_network") != "none"
    ):
        raise ValueError("OpenHands v19 qualification receipt is malformed")
    task_ids = [item.get("task_id") if isinstance(item, Mapping) else None for item in tasks]
    if (
        task_ids != [*training, *validation]
        or len(set(task_ids)) != OPENHANDS_V19_QUALIFIED_TASK_TARGET
        or any(task_id not in OPENHANDS_V19_QUALIFICATION_CANDIDATES for task_id in task_ids)
    ):
        raise ValueError("OpenHands v19 qualification reserve roles changed")
    expected_keys = {
        "task_id",
        "role",
        "task_hash",
        "source_hash",
        "image_lock_hash",
        "agent_image",
        "verifier_image",
        "qualification_outcome_hash",
    }
    for index, item in enumerate(tasks):
        if not isinstance(item, Mapping) or set(item) != expected_keys:
            raise ValueError("OpenHands v19 qualification task binding is malformed")
        expected_role = (
            "training_reserve"
            if index < OPENHANDS_V19_TRAINING_RESERVE_COUNT
            else "validation_reserve"
        )
        if item.get("role") != expected_role:
            raise ValueError("OpenHands v19 qualification task role changed")
        _validated_qualification_binding(item, allow_extra=True)
        _require_hash(item.get("qualification_outcome_hash"), "qualification outcome hash")
    return copy.deepcopy(dict(value))


def build_v19_canary_contract(
    qualification: Mapping[str, Any],
    *,
    validation_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the static two-task canary identity from a sealed qualification receipt."""

    sealed = validate_v19_qualification_receipt(qualification)
    training = sealed["training_reserve_task_ids"]
    selected = next(item for item in sealed["tasks"] if item["task_id"] == training[0])
    validation = _validated_qualification_binding(validation_binding)
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V19_CANARY_CONTRACT_FORMAT,
        "campaign_id": OPENHANDS_V19_CANARY_CAMPAIGN_ID,
        "agent_version_id": OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
        "qualification_receipt_hash": sealed["receipt_hash"],
        "task_bindings": {
            training[0]: {
                key: selected[key]
                for key in (
                    "task_hash",
                    "source_hash",
                    "image_lock_hash",
                    "agent_image",
                    "verifier_image",
                )
            },
            OPENHANDS_V19_CANARY_VALIDATION_TASK: validation,
        },
        "schedule": [
            {
                "role": "training",
                "task_id": training[0],
                "seed": OPENHANDS_V19_CANARY_SEED,
                "sample_index": OPENHANDS_V19_CANARY_SAMPLE_INDEX,
            },
            {
                "role": "validation",
                "task_id": OPENHANDS_V19_CANARY_VALIDATION_TASK,
                "seed": OPENHANDS_V19_CANARY_SEED,
                "sample_index": OPENHANDS_V19_CANARY_SAMPLE_INDEX,
            },
        ],
        "teacher": {
            "model": "openai/deepseek-v4-flash",
            "model_identity": "deepseek-v4-flash",
            "openhands_sdk_version": "1.42.1",
            "litellm_version": "1.93.0",
            "tiktoken_version": "0.7.0",
            "tool_choice_policy": OPENHANDS_V19_TOOL_CHOICE_POLICY,
            "temperature": 0,
            "provider_request_retries": 0,
            "whole_episode_retries": 0,
            "max_provider_calls": OPENHANDS_V19_MAX_PROVIDER_CALLS,
            "max_provider_tokens": OPENHANDS_V19_MAX_PROVIDER_TOKENS,
            "max_context_tokens": OPENHANDS_V19_MAX_CONTEXT_TOKENS,
            "max_output_tokens": OPENHANDS_V19_MAX_OUTPUT_TOKENS,
        },
        "gate": {
            "all_six_result_planes_required": True,
            "decision_token_limit": OPENHANDS_V19_MAX_CONTEXT_TOKENS,
            "truncation_allowed": False,
            "automatic_next_identity_allowed": False,
            "infrastructure_or_security_failure_policy": "stop_immediately",
            "benchmark_or_trajectory_failure_policy": "canary_fail_closed",
        },
        "heldout_task_ids_loaded": [],
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    return validate_v19_canary_contract({**base, "contract_hash": content_hash(base)})


def validate_v19_canary_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the hash-bound, zero-fallback two-task v19 canary contract."""

    result = copy.deepcopy(dict(value))
    expected_hash = result.pop("contract_hash", None)
    if not isinstance(expected_hash, str) or content_hash(result) != expected_hash:
        raise ValueError("OpenHands v19 canary contract identity changed")
    schedule = result.get("schedule")
    bindings = result.get("task_bindings")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V19_CANARY_CONTRACT_FORMAT
        or result.get("campaign_id") != OPENHANDS_V19_CANARY_CAMPAIGN_ID
        or result.get("agent_version_id") != OPENHANDS_V19_CANARY_AGENT_VERSION_ID
        or not isinstance(schedule, list)
        or len(schedule) != 2
        or not isinstance(bindings, Mapping)
        or result.get("heldout_task_ids_loaded") != []
        or result.get("production_training_ready") is not False
        or result.get("benchmark_score_claimed") is not False
    ):
        raise ValueError("OpenHands v19 canary contract is malformed")
    task_ids = [item.get("task_id") if isinstance(item, Mapping) else None for item in schedule]
    if (
        task_ids[1] != OPENHANDS_V19_CANARY_VALIDATION_TASK
        or set(bindings) != set(task_ids)
        or [item.get("role") for item in schedule if isinstance(item, Mapping)]
        != ["training", "validation"]
        or any(
            item.get("seed") != OPENHANDS_V19_CANARY_SEED
            or item.get("sample_index") != OPENHANDS_V19_CANARY_SAMPLE_INDEX
            for item in schedule
            if isinstance(item, Mapping)
        )
    ):
        raise ValueError("OpenHands v19 canary schedule changed")
    for binding in bindings.values():
        if not isinstance(binding, Mapping):
            raise ValueError("OpenHands v19 canary task binding is malformed")
        _validated_qualification_binding(binding)
    teacher = result.get("teacher")
    gate = result.get("gate")
    if (
        not isinstance(teacher, Mapping)
        or teacher.get("model") != "openai/deepseek-v4-flash"
        or teacher.get("openhands_sdk_version") != "1.42.1"
        or teacher.get("litellm_version") != "1.93.0"
        or teacher.get("tiktoken_version") != "0.7.0"
        or teacher.get("tool_choice_policy") != OPENHANDS_V19_TOOL_CHOICE_POLICY
        or teacher.get("temperature") != 0
        or teacher.get("provider_request_retries") != 0
        or teacher.get("whole_episode_retries") != 0
        or teacher.get("max_provider_calls") != OPENHANDS_V19_MAX_PROVIDER_CALLS
        or teacher.get("max_provider_tokens") != OPENHANDS_V19_MAX_PROVIDER_TOKENS
        or teacher.get("max_context_tokens") != OPENHANDS_V19_MAX_CONTEXT_TOKENS
        or teacher.get("max_output_tokens") != OPENHANDS_V19_MAX_OUTPUT_TOKENS
        or not isinstance(gate, Mapping)
        or gate.get("truncation_allowed") is not False
        or gate.get("automatic_next_identity_allowed") is not False
    ):
        raise ValueError("OpenHands v19 canary runtime policy changed")
    _require_hash(result.get("qualification_receipt_hash"), "qualification receipt hash")
    return copy.deepcopy(dict(value))


def evaluate_v19_canary_gate(
    attempts: Sequence[Mapping[str, Any]],
    *,
    training_reserve_task_id: str,
) -> bool:
    expected = [training_reserve_task_id, OPENHANDS_V19_CANARY_VALIDATION_TASK]
    if [attempt.get("task_id") for attempt in attempts] != expected:
        raise ValueError("OpenHands v19 canary results are incomplete or out of order")
    for attempt in attempts:
        validated = _validate_v19_attempt_envelope(attempt, require_sft_evidence=True)
        if any(
            validated[key] is not True
            for key in (
                "benchmark_verifier_pass",
                "agent_protocol_valid",
                "trajectory_eligible",
                "infrastructure_valid",
                "security_valid",
                "sft_admitted",
            )
        ):
            return False
    return True


def evaluate_v19_collection_gate(
    attempts: Sequence[Mapping[str, Any]],
    *,
    training_reserves: Sequence[str],
    validation_reserves: Sequence[str],
) -> V19CollectionGate:
    """Recompute exact distinct pass capacity after every single-use attempt."""

    if len(training_reserves) != 3 or len(validation_reserves) != 2:
        raise ValueError("OpenHands v19 collection reserve capacity changed")
    if len(set(training_reserves) | set(validation_reserves)) != 5:
        raise ValueError("OpenHands v19 collection reserves are not distinct")
    training_order = (*OPENHANDS_V19_FIXED_TRAINING_ORDER, *training_reserves[1:])
    validation_order = (*OPENHANDS_V19_FIXED_VALIDATION_ORDER, *validation_reserves)
    passed_training = set(OPENHANDS_V19_PRIOR_TRAINING_PASSES) | {training_reserves[0]}
    passed_validation = {OPENHANDS_V19_CANARY_VALIDATION_TASK}
    attempted_training: set[str] = set()
    attempted_validation: set[str] = set()
    role = "training"
    for raw in attempts:
        result = _validate_v19_attempt_envelope(raw, require_sft_evidence=False)
        task_id = str(result.get("task_id", ""))
        observed_role = raw.get("role")
        if role == "training" and len(passed_training) >= OPENHANDS_V19_TRAINING_TARGET:
            role = "validation"
        order = training_order if role == "training" else validation_order
        attempted = attempted_training if role == "training" else attempted_validation
        expected_index = len(attempted)
        if (
            observed_role != role
            or expected_index >= len(order)
            or task_id != order[expected_index]
        ):
            raise ValueError("OpenHands v19 collection attempt order changed")
        if task_id in attempted:
            raise ValueError("OpenHands v19 collection retried a task")
        attempted.add(task_id)
        if result["infrastructure_valid"] is not True or result["security_valid"] is not True:
            return _collection_gate(
                passed_training,
                passed_validation,
                training_order,
                validation_order,
                attempted_training,
                attempted_validation,
                stopped=True,
                possible=False,
                reason="infrastructure_or_security_invalid",
                next_role=None,
                next_task_id=None,
            )
        if result["sft_admitted"] is True:
            (passed_training if role == "training" else passed_validation).add(task_id)
        training_possible = (
            len(passed_training) + len(set(training_order) - attempted_training)
            >= OPENHANDS_V19_TRAINING_TARGET
        )
        validation_possible = (
            len(passed_validation) + len(set(validation_order) - attempted_validation)
            >= OPENHANDS_V19_VALIDATION_TARGET
        )
        if not training_possible or not validation_possible:
            return _collection_gate(
                passed_training,
                passed_validation,
                training_order,
                validation_order,
                attempted_training,
                attempted_validation,
                stopped=True,
                possible=False,
                reason=(
                    "training_capacity_exhausted"
                    if not training_possible
                    else "validation_capacity_exhausted"
                ),
                next_role=None,
                next_task_id=None,
            )
    training_done = len(passed_training) >= OPENHANDS_V19_TRAINING_TARGET
    validation_done = len(passed_validation) >= OPENHANDS_V19_VALIDATION_TARGET
    if training_done and validation_done:
        return _collection_gate(
            passed_training,
            passed_validation,
            training_order,
            validation_order,
            attempted_training,
            attempted_validation,
            stopped=True,
            possible=True,
            reason=None,
            next_role=None,
            next_task_id=None,
        )
    next_role = "validation" if training_done else "training"
    order = validation_order if training_done else training_order
    attempted = attempted_validation if training_done else attempted_training
    return _collection_gate(
        passed_training,
        passed_validation,
        training_order,
        validation_order,
        attempted_training,
        attempted_validation,
        stopped=False,
        possible=True,
        reason="target_not_reached",
        next_role=next_role,
        next_task_id=order[len(attempted)],
    )


def _qualification_gate(
    qualified: Sequence[str],
    *,
    stopped: bool,
    reason: str | None,
    next_task_id: str | None,
) -> V19QualificationGate:
    tasks = tuple(qualified)
    satisfied = len(tasks) == OPENHANDS_V19_QUALIFIED_TASK_TARGET
    return V19QualificationGate(
        satisfied=satisfied,
        stopped=stopped or satisfied,
        reason=reason,
        next_task_id=next_task_id,
        qualified_task_ids=tasks,
        training_reserve_task_ids=tasks[:OPENHANDS_V19_TRAINING_RESERVE_COUNT],
        validation_reserve_task_ids=tasks[OPENHANDS_V19_TRAINING_RESERVE_COUNT:],
    )


def _collection_gate(
    passed_training: set[str],
    passed_validation: set[str],
    training_order: Sequence[str],
    validation_order: Sequence[str],
    attempted_training: set[str],
    attempted_validation: set[str],
    *,
    stopped: bool,
    possible: bool,
    reason: str | None,
    next_role: str | None,
    next_task_id: str | None,
) -> V19CollectionGate:
    return V19CollectionGate(
        satisfied=(
            len(passed_training) >= OPENHANDS_V19_TRAINING_TARGET
            and len(passed_validation) >= OPENHANDS_V19_VALIDATION_TARGET
        ),
        possible=possible,
        stopped=stopped,
        reason=reason,
        next_role=next_role,
        next_task_id=next_task_id,
        training_pass_count=len(passed_training),
        validation_pass_count=len(passed_validation),
        remaining_training_capacity=len(set(training_order) - attempted_training),
        remaining_validation_capacity=len(set(validation_order) - attempted_validation),
    )


def _changed_lines(patch: str) -> int:
    return sum(
        1
        for line in patch.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _digest_image(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        return False
    return all(character in "0123456789abcdef" for character in value.removeprefix("sha256:"))


def _validated_qualification_binding(
    value: Mapping[str, Any], *, allow_extra: bool = False
) -> dict[str, str]:
    required = {
        "task_hash",
        "source_hash",
        "image_lock_hash",
        "agent_image",
        "verifier_image",
    }
    if (not allow_extra and set(value) != required) or not required <= set(value):
        raise ValueError("OpenHands v19 qualification binding fields changed")
    result = {key: str(value.get(key, "")) for key in required}
    for key in ("task_hash", "source_hash", "image_lock_hash"):
        _require_hash(result[key], f"qualification {key}")
    if not _digest_image(result["agent_image"]) or not _digest_image(result["verifier_image"]):
        raise ValueError("OpenHands v19 image binding is invalid")
    return result


def _validate_v19_attempt_envelope(
    value: Mapping[str, Any], *, require_sft_evidence: bool
) -> dict[str, Any]:
    result_value = value.get("result")
    if not isinstance(result_value, Mapping):
        raise ValueError("OpenHands v19 attempt result is missing")
    result = validate_v19_campaign_result(result_value)
    if value.get("task_id") != result.get("task_id"):
        raise ValueError("OpenHands v19 attempt task binding changed")
    security_scan_hash = value.get("security_scan_hash")
    if result["security_valid"] is True:
        _require_hash(security_scan_hash, "security scan hash")
    admitted = result["sft_admitted"] is True
    if require_sft_evidence and not admitted:
        return result
    if not admitted:
        protocol_value = value.get("protocol_receipt")
        if protocol_value is not None:
            if not isinstance(protocol_value, Mapping):
                raise ValueError("OpenHands v19 attempt protocol receipt is malformed")
            validate_v19_protocol_receipt(protocol_value)
        if any(value.get(key) is not None for key in ("trajectory_receipt", "decision_receipt")):
            raise ValueError("OpenHands v19 ineligible attempt carries SFT-only receipts")
        return result
    protocol_value = value.get("protocol_receipt")
    trajectory_value = value.get("trajectory_receipt")
    decision_value = value.get("decision_receipt")
    if not all(
        isinstance(item, Mapping) for item in (protocol_value, trajectory_value, decision_value)
    ):
        raise ValueError("OpenHands v19 admitted attempt lacks exact receipts")
    assert isinstance(protocol_value, Mapping)
    assert isinstance(trajectory_value, Mapping)
    assert isinstance(decision_value, Mapping)
    protocol = validate_v19_protocol_receipt(protocol_value)
    trajectory = validate_v19_trajectory_receipt(trajectory_value)
    decision = validate_v19_decision_receipt(decision_value)
    if (
        trajectory["protocol_receipt_hash"] != protocol["receipt_hash"]
        or trajectory["campaign_result_hash"] != result["result_hash"]
        or decision["trajectory_receipt_hash"] != trajectory["receipt_hash"]
        or decision["transcript_hash"] != trajectory["transcript_hash"]
    ):
        raise ValueError("OpenHands v19 attempt receipt chain changed")
    return result


def _require_hash(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"OpenHands v19 {label} is invalid")


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V19_")] + [
    "V19CollectionGate",
    "V19QualificationGate",
    "build_v19_canary_contract",
    "evaluate_v19_canary_gate",
    "evaluate_v19_collection_gate",
    "evaluate_v19_qualification_gate",
    "frozen_v19_candidate_inventory",
    "seal_v19_qualification_receipt",
    "validate_v19_canary_contract",
    "validate_v19_qualification_receipt",
]
