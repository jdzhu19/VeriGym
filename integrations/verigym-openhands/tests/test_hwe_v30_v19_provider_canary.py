from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.core.errors import ConfigurationError
from verigym.evolution.memory import validate_agent_version
from verigym.schemas.external_agent import ExternalAgentAccounting

from verigym_openhands.hwe_v19 import build_v19_protocol_receipt
from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_CANARY_VALIDATION_BINDING,
    OPENHANDS_V19_CANARY_VALIDATION_TASK,
    OPENHANDS_V19_QUALIFICATION_CANDIDATES,
    build_v19_canary_contract,
    seal_v19_qualification_receipt,
)
from verigym_openhands.hwe_v19_canary_runtime import (
    OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V19_CANARY_SEED,
    OPENHANDS_V19_TOOL_CHOICE_POLICY,
    build_v19_canary_agent_options,
    build_v19_canary_agent_version,
    validate_v19_canary_runtime_evidence,
)

_runner = importlib.import_module("scripts.collect_cva6_hwe_openhands_v30_v19_provider_canary")
_REPOSITORY = Path(__file__).resolve().parents[3]


def _authorization_path() -> Path:
    return _REPOSITORY / "configs/training/qwen35_hwe_openhands_v30_v19_provider_canary_v1.json"


def _contract() -> dict[str, object]:
    task_ids = OPENHANDS_V19_QUALIFICATION_CANDIDATES[:5]
    outcomes = [
        {
            "task_id": task_id,
            "infrastructure_valid": True,
            "verifier_network": "none",
            "verifier_image": "sha256:" + "e" * 64,
            "model_process_count": 0,
            "base_failed": True,
            "reference_passed": True,
        }
        for task_id in task_ids
    ]
    bindings = {
        task_id: {
            "task_hash": "a" * 64,
            "source_hash": "b" * 64,
            "image_lock_hash": "c" * 64,
            "agent_image": "sha256:" + "d" * 64,
            "verifier_image": "sha256:" + "e" * 64,
        }
        for task_id in task_ids
    }
    qualification = seal_v19_qualification_receipt(outcomes, bindings=bindings)
    return build_v19_canary_contract(
        qualification,
        validation_binding=OPENHANDS_V19_CANARY_VALIDATION_BINDING,
    )


def _locks(contract: dict[str, object]) -> dict[str, SimpleNamespace]:
    bindings = contract["task_bindings"]
    assert isinstance(bindings, dict)
    result: dict[str, SimpleNamespace] = {}
    for task_id, raw in bindings.items():
        assert isinstance(raw, dict)
        result[task_id] = SimpleNamespace(
            task_id=task_id,
            task_hash=raw["task_hash"],
            source_hash=raw["source_hash"],
            lock_hash=raw["image_lock_hash"],
            derived_agent_image_id=raw["agent_image"],
            verifier_base_image_id=raw["verifier_image"],
            runtime_network="none",
            security_scan_passed=True,
            hidden_assets_present=False,
            reference_patch_present=False,
            provider_credentials_present=False,
            verifier_payload_present=False,
        )
    return result


def _protocol() -> dict[str, object]:
    return build_v19_protocol_receipt(
        provider={
            "provider_call_count": 1,
            "successful_provider_response_count": 1,
            "provider_usage_record_count": 1,
            "input_tokens": 100,
            "output_tokens": 10,
        },
        protocol={
            "required_tool_request_count": 1,
            "canonical_tool_response_count": 1,
            "content_only_response_count": 0,
            "format_recovery_count": 0,
            "recovery_forced_request_count": 0,
            "recovery_validated_tool_count": 0,
            "over_budget_response_count": 0,
        },
        broker_decision_steps=1,
    )


def test_v30_authorization_binds_two_provider_episodes_and_no_collection() -> None:
    value = json.loads(_authorization_path().read_text(encoding="utf-8"))
    approved = _runner._validated_authorization(value)

    assert approved["authorization_hash"] == _runner.OPENHANDS_V30_APPROVAL_HASH
    assert approved["schedule"]["maximum_provider_episodes"] == 2
    assert approved["required_controls"]["stop_after_first_failed_gate"] is True
    assert approved["authorized_actions"]["invoke_provider"] is True
    assert approved["authorized_actions"]["start_collection"] is False
    assert approved["authorized_actions"]["start_training"] is False
    assert approved["authorized_actions"]["load_heldout_tasks"] is False


def test_v30_authorization_rejects_schedule_or_input_substitution() -> None:
    value = json.loads(_authorization_path().read_text(encoding="utf-8"))
    changed = copy.deepcopy(value)
    changed["schedule"]["task_ids"].reverse()
    with pytest.raises(ConfigurationError, match="authorization identity changed"):
        _runner._validated_authorization(changed)

    changed = copy.deepcopy(value)
    changed["input_locks"]["tokenizer_hash"] = "0" * 64
    with pytest.raises(ConfigurationError, match="authorization identity changed"):
        _runner._validated_authorization(changed)


def test_v19_canary_agent_version_and_options_bind_required_tool_budget() -> None:
    contract = _contract()
    version = build_v19_canary_agent_version(
        contract=contract,
        source_commit="a" * 40,
        image_locks=_locks(contract),
    )
    options = build_v19_canary_agent_options(
        seed=OPENHANDS_V19_CANARY_SEED,
        agent_version=version,
    )

    assert validate_agent_version(version) == version
    assert version.agent_version_id == OPENHANDS_V19_CANARY_AGENT_VERSION_ID
    assert options["tool_choice_policy"] == OPENHANDS_V19_TOOL_CHOICE_POLICY
    assert options["max_iterations"] == 64
    assert options["max_provider_tokens"] == 1_000_000
    assert options["max_context_tokens"] == 65_536
    assert options["max_output_tokens"] == 2_048
    assert options["whole_episode_retries"] == 0


def test_v19_canary_runtime_evidence_matches_protocol_and_accounting() -> None:
    protocol = _protocol()
    accounting = ExternalAgentAccounting(
        process_wall_time_s=1.0,
        cli_event_count=1,
        model_call_count=1,
        external_tool_call_count=1,
        input_tokens=100,
        output_tokens=10,
    )
    summary = {
        "tool_choice_policy": OPENHANDS_V19_TOOL_CHOICE_POLICY,
        "v19_protocol_receipt_hash": protocol["receipt_hash"],
        "provider_call_budget": 64,
        "provider_call_count": 1,
        "provider_input_tokens": 100,
        "provider_output_tokens": 10,
        "provider_total_tokens": 110,
        "required_tool_request_count": 1,
        "canonical_tool_response_count": 1,
        "content_only_response_count": 0,
        "whole_episode_retries": 0,
        "local_repository_exposed_to_openhands": False,
        "docker_socket_exposed_to_openhands": False,
        "default_tools_exposed": False,
        "plugins_loaded": False,
    }
    broker = {"finished": True, "infrastructure_failure": None, "decision_steps": 1}

    assert (
        validate_v19_canary_runtime_evidence(
            broker=broker,
            summary=summary,
            accounting=accounting,
            protocol_receipt=protocol,
        )["receipt_hash"]
        == protocol["receipt_hash"]
    )
    changed = dict(summary)
    changed["provider_call_count"] = 2
    with pytest.raises(ValueError, match="runtime evidence changed"):
        validate_v19_canary_runtime_evidence(
            broker=broker,
            summary=changed,
            accounting=accounting,
            protocol_receipt=protocol,
        )


def test_v30_stops_before_validation_after_first_ordinary_failure() -> None:
    ordinary_failure = {
        "result": {
            "infrastructure_valid": True,
            "security_valid": True,
            "sft_admitted": False,
        }
    }
    security_failure = {
        "result": {
            "infrastructure_valid": True,
            "security_valid": False,
            "sft_admitted": False,
        }
    }
    admitted = {
        "result": {
            "infrastructure_valid": True,
            "security_valid": True,
            "sft_admitted": True,
        }
    }

    assert _runner._attempt_stop_kind(ordinary_failure) == "six_plane_gate_failed"
    assert _runner._attempt_stop_kind(security_failure) == "infrastructure_or_security_invalid"
    assert _runner._attempt_stop_kind(admitted) is None


def test_v30_observes_accounting_even_without_a_protocol_receipt(tmp_path: Path) -> None:
    path = tmp_path / "runs/failed/artifacts/openhands_sdk"
    path.mkdir(parents=True)
    accounting = ExternalAgentAccounting(
        process_wall_time_s=1.0,
        cli_event_count=1,
        model_call_count=3,
        input_tokens=100,
        output_tokens=10,
    )
    (path / "accounting.json").write_text(
        json.dumps(accounting.model_dump(mode="json")),
        encoding="utf-8",
    )

    assert _runner._observed_provider_accounting(tmp_path, []) == {
        "provider_episode_count": 1,
        "provider_call_count": 3,
    }


def test_v30_schedule_keeps_historical_validation_task_frozen() -> None:
    value = json.loads(_authorization_path().read_text(encoding="utf-8"))
    assert value["schedule"]["task_ids"][1] == OPENHANDS_V19_CANARY_VALIDATION_TASK
