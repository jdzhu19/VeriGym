from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.evolution.memory import validate_agent_version
from verigym.schemas.external_agent import ExternalAgentAccounting

from verigym_openhands.hwe_agent import (
    OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY,
    _bounded_iteration_limit_exhausted,
)
from verigym_openhands.hwe_v17_canary_v4 import (
    OPENHANDS_V17_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V17_CANARY_CAMPAIGN_ID,
    OPENHANDS_V17_CANARY_MAX_ITERATIONS,
    OPENHANDS_V17_CANARY_OPT_IN_ENV,
    OPENHANDS_V17_CANARY_PR2248,
    OPENHANDS_V17_CANARY_PR2944,
    OPENHANDS_V17_CANARY_PR3191,
    OPENHANDS_V17_CANARY_TASKS,
    build_v17_canary_agent_options,
    build_v17_canary_agent_version,
    evaluate_v17_canary_gate,
    load_v17_canary_contract,
    validate_v17_runtime_evidence,
)


@dataclass(frozen=True)
class _Lock:
    task_id: str
    task_hash: str
    source_hash: str
    lock_hash: str
    derived_agent_image_id: str
    verifier_base_image_id: str


def _root() -> Path:
    return Path(__file__).parents[3]


def _contract_path() -> Path:
    return _root() / "configs" / "training" / "qwen35_hwe_openhands_v17_canary_v4.json"


def _locks() -> dict[str, _Lock]:
    contract = load_v17_canary_contract(_contract_path())
    return {
        task_id: _Lock(
            task_id=task_id,
            task_hash=binding["task_hash"],
            source_hash=binding["source_hash"],
            lock_hash=binding["image_lock_hash"],
            derived_agent_image_id=binding["agent_image"],
            verifier_base_image_id=binding["verifier_image"],
        )
        for task_id, binding in contract["task_bindings"].items()
    }


def _attempt(task_id: str, *, resolved: bool) -> dict[str, object]:
    return {
        "task_id": task_id,
        "infrastructure_valid": True,
        "runtime_evidence_valid": True,
        "security_scan_passed": True,
        "truncation_applied": False,
        "recovery_accounting_valid": True,
        "ordinary_verifier_resolved": resolved,
        "fresh_exact_trajectory": resolved,
    }


def _provider(limit: int = OPENHANDS_V17_CANARY_MAX_ITERATIONS) -> dict[str, int]:
    return {
        "provider_call_count": limit,
        "successful_provider_response_count": limit,
        "provider_usage_record_count": limit,
        "input_tokens": 1_000,
        "output_tokens": 100,
    }


def _stats(limit: int = OPENHANDS_V17_CANARY_MAX_ITERATIONS) -> SimpleNamespace:
    return SimpleNamespace(
        finished=False,
        finish_calls=0,
        policy_failure="decision_steps_hard_limit",
        infrastructure_failure=None,
        rejected_calls=1,
        rejection_codes=("episode_limit",),
        tool_calls=limit,
        decision_steps=limit + 1,
    )


def _events(limit: int = OPENHANDS_V17_CANARY_MAX_ITERATIONS) -> dict[str, int]:
    return {
        "ActionEvent": limit + 1,
        "ConversationErrorEvent": 1,
        "MessageEvent": 1,
        "ObservationEvent": limit + 1,
        "SystemPromptEvent": 1,
    }


def _recovery_fields() -> dict[str, object]:
    return {
        "format_recovery_count": 0,
        "recovery_forced_request_count": 0,
        "recovery_validated_finish_count": 0,
        "recovery_validated_tool_count": 0,
        "sdk_stop_continuation_count": 0,
        "sdk_continuation_forced_request_count": 0,
        "sdk_continuation_validated_tool_count": 0,
        "path_policy_recovery_count": 0,
        "path_policy_recovery_forced_request_count": 0,
        "path_policy_recovery_validated_tool_count": 0,
        "recovery_response_shape": {},
        "sdk_continuation_response_shape": {},
        "path_policy_recovery_response_shape": {},
        "recovery_coalesced_output_count": 0,
    }


def _limit_evidence() -> tuple[dict[str, object], dict[str, object], ExternalAgentAccounting]:
    limit = OPENHANDS_V17_CANARY_MAX_ITERATIONS
    broker: dict[str, object] = {
        "finished": False,
        "finish_calls": 0,
        "tool_calls": limit,
        "decision_steps": limit + 1,
        "command_calls": 192,
        "file_reads": 7,
        "patches": 0,
        "infrastructure_failure": None,
        "policy_failure": "decision_steps_hard_limit",
        "rejected_calls": 1,
        "rejection_codes": ["episode_limit"],
        "raw_audit_manifest": {"secret_scan": "passed"},
    }
    summary: dict[str, object] = {
        **_recovery_fields(),
        "provider_call_budget": limit,
        "provider_call_count": limit,
        "successful_provider_response_count": limit,
        "provider_usage_record_count": limit,
        "provider_input_tokens": 1_000,
        "provider_output_tokens": 100,
        "broker_decision_steps": limit + 1,
        "event_type_counts": _events(),
        "bounded_iteration_limit_exhausted": True,
        "bounded_iteration_termination_policy_id": (OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY),
        "termination_authority": "sdk_iteration_limit",
        "tool_choice_policy": "validated_responses_recovery_state_required_tool_v18",
        "sdk_version": "1.42.1",
        "whole_episode_retries": 0,
        "default_tools_exposed": False,
        "docker_socket_exposed_to_openhands": False,
        "local_repository_exposed_to_openhands": False,
        "private_reasoning_persisted": False,
        "message_content_persisted": False,
        "ordinary_hidden_verifier_pending": False,
        "ordinary_verifier_resolved": False,
        "training_trajectory_captured": False,
        "training_trajectory_exported": False,
        "same_session_recovery": True,
        "format_recovery_policy_id": "openhands_broker_stop_hook_recovery_v1",
        "format_recovery_budget": 1,
        "sdk_stop_continuation_policy_id": "openhands_sdk_blocked_stop_continuation_v1",
        "sdk_stop_continuation_budget": 1,
        "sdk_continuation_tool_choice_policy": "responses_required_validated_v1",
        "path_policy_recovery_policy_id": "openhands_provider_path_policy_recovery_v1",
        "path_policy_recovery_budget": 1,
        "path_policy_recovery_tool_choice_policy": "responses_required_validated_v1",
        "raw_rejected_provider_arguments_persisted": False,
    }
    accounting = ExternalAgentAccounting(
        process_wall_time_s=1.0,
        cli_event_count=404,
        model_call_count=limit,
        external_tool_call_count=limit,
        external_command_count=192,
        public_test_invocation_count=0,
        external_file_read_count=7,
        external_file_write_count=0,
        external_patch_count=0,
        input_tokens=1_000,
        output_tokens=100,
        total_tokens=1_100,
    )
    return broker, summary, accounting


def test_v4_contract_is_independent_and_loads_no_heldout(tmp_path: Path) -> None:
    contract = load_v17_canary_contract(_contract_path())

    assert contract["format_id"].endswith("canary_v4")
    assert contract["contract_hash"] == (
        "18ba9369eb59b96b468f42e2338600d0c029ad3c9f0a64763125af9b4360fb83"
    )
    assert contract["teacher"]["bounded_iteration_termination_policy_id"] == (
        OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY
    )
    assert [item["task_id"] for item in contract["schedule"]] == list(OPENHANDS_V17_CANARY_TASKS)
    assert contract["heldout_task_ids_loaded"] == []
    assert contract["gate"]["bounded_iteration_limit_is_model_nonfinish"] is True

    changed = json.loads(_contract_path().read_bytes())
    changed["campaign_id"] = "v3-relabel"
    invalid = tmp_path / _contract_path().name
    invalid.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="identity changed"):
        load_v17_canary_contract(invalid)


def test_v4_agent_version_and_options_use_independent_identity() -> None:
    version = build_v17_canary_agent_version(source_commit="a" * 40, image_locks=_locks())

    assert validate_agent_version(version) == version
    assert version.agent_version_id == OPENHANDS_V17_CANARY_AGENT_VERSION_ID
    options = build_v17_canary_agent_options(seed=486, agent_version=version)
    assert options["agent_version_id"] == OPENHANDS_V17_CANARY_AGENT_VERSION_ID
    assert options["max_iterations"] == OPENHANDS_V17_CANARY_MAX_ITERATIONS
    assert OPENHANDS_V17_CANARY_CAMPAIGN_ID.endswith("v4")
    assert OPENHANDS_V17_CANARY_OPT_IN_ENV.endswith("V4")


def test_bounded_iteration_classifier_requires_the_exact_sdk_broker_shape() -> None:
    settings = SimpleNamespace(
        max_iterations=OPENHANDS_V17_CANARY_MAX_ITERATIONS,
        tool_choice_policy="validated_responses_recovery_state_required_tool_v18",
    )
    assert _bounded_iteration_limit_exhausted(
        stats=_stats(),
        settings=settings,
        provider=_provider(),
        event_types=_events(),
    )

    for field, value in (
        ("policy_failure", "mutation_actions_hard_limit"),
        ("rejected_calls", 2),
        ("rejection_codes", ("invalid_arguments",)),
        ("tool_calls", OPENHANDS_V17_CANARY_MAX_ITERATIONS - 1),
        ("decision_steps", OPENHANDS_V17_CANARY_MAX_ITERATIONS),
    ):
        changed = _stats()
        setattr(changed, field, value)
        assert not _bounded_iteration_limit_exhausted(
            stats=changed,
            settings=settings,
            provider=_provider(),
            event_types=_events(),
        )
    changed_provider = {**_provider(), "provider_usage_record_count": 199}
    assert not _bounded_iteration_limit_exhausted(
        stats=_stats(),
        settings=settings,
        provider=changed_provider,
        event_types=_events(),
    )
    changed_events = {**_events(), "ConversationErrorEvent": 2}
    assert not _bounded_iteration_limit_exhausted(
        stats=_stats(),
        settings=settings,
        provider=_provider(),
        event_types=changed_events,
    )
    wrong_policy = SimpleNamespace(
        max_iterations=OPENHANDS_V17_CANARY_MAX_ITERATIONS,
        tool_choice_policy="validated_responses_recovery_state_required_tool_v17",
    )
    assert not _bounded_iteration_limit_exhausted(
        stats=_stats(),
        settings=wrong_policy,
        provider=_provider(),
        event_types=_events(),
    )


def test_v4_runtime_evidence_accepts_only_exact_bounded_nonfinish() -> None:
    broker, summary, accounting = _limit_evidence()

    assert (
        validate_v17_runtime_evidence(
            broker,
            summary,
            accounting,
            verifier_resolved=False,
        )
        == "bounded_iteration_limit_model_nonfinish"
    )

    for target, field, value in (
        (broker, "policy_failure", "mutation_actions_hard_limit"),
        (broker, "rejected_calls", 2),
        (summary, "provider_usage_record_count", 199),
        (summary, "training_trajectory_exported", True),
        (summary, "termination_authority", "broker_typed_finish"),
    ):
        changed_broker = dict(broker)
        changed_summary = dict(summary)
        (changed_broker if target is broker else changed_summary)[field] = value
        with pytest.raises(ValueError, match="bounded iteration-limit evidence changed"):
            validate_v17_runtime_evidence(
                changed_broker,
                changed_summary,
                accounting,
                verifier_resolved=False,
            )


def test_v4_gate_allows_exact_nonfinish_when_two_training_canaries_pass() -> None:
    gate = evaluate_v17_canary_gate(
        [
            _attempt(OPENHANDS_V17_CANARY_PR2944, resolved=True),
            _attempt(OPENHANDS_V17_CANARY_PR2248, resolved=True),
            _attempt(OPENHANDS_V17_CANARY_PR3191, resolved=False),
        ]
    )

    assert gate.canary_passed is True
    assert gate.formal_collection_allowed is True
    assert gate.pr3191_passed is False
    assert gate.maximum_validation_pass_count == 2


def test_v4_runner_installs_every_independent_policy_export() -> None:
    from scripts import collect_cva6_hwe_openhands_v17_canary_v4 as runner

    runner._install_v4_policy()

    assert runner._runner.OPENHANDS_V17_CANARY_CAMPAIGN_ID == OPENHANDS_V17_CANARY_CAMPAIGN_ID
    assert runner._runner.OPENHANDS_V17_CANARY_AGENT_VERSION_ID == (
        OPENHANDS_V17_CANARY_AGENT_VERSION_ID
    )
    assert runner._runner.OPENHANDS_V17_CANARY_OPT_IN_ENV == OPENHANDS_V17_CANARY_OPT_IN_ENV
    assert runner._runner.load_v17_canary_contract is load_v17_canary_contract
    assert runner._runner.validate_v17_runtime_evidence is validate_v17_runtime_evidence
