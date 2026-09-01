from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.memory import validate_agent_version
from verigym.hwe.image_lock import HweCommandImageLock, build_hwe_command_image_lock
from verigym.schemas.external_agent import ExternalAgentAccounting

from verigym_openhands import hwe_agent
from verigym_openhands.hwe_v20 import build_v20_protocol_receipt
from verigym_openhands.hwe_v20_protocol import OPENHANDS_V20_TOOL_CHOICE_POLICY
from verigym_openhands.hwe_v37_canary_runtime import (
    OPENHANDS_V37_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V37_CANARY_CONTRACT_FORMAT,
    OPENHANDS_V37_CANARY_OPT_IN_ENV,
    OPENHANDS_V37_CANARY_SAMPLE_INDEX,
    OPENHANDS_V37_CANARY_SEED,
    OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
    build_v37_canary_agent_options,
    build_v37_canary_agent_version,
    validate_v37_canary_runtime_evidence,
)

_runner = importlib.import_module("scripts.collect_cva6_hwe_openhands_v37_provider_canary")
_REPOSITORY = Path(__file__).resolve().parents[3]
_AUTHORIZATION = _REPOSITORY / "configs/training/qwen35_hwe_openhands_v37_provider_canary_v1.json"


def _authorization() -> dict[str, object]:
    return json.loads(_AUTHORIZATION.read_text(encoding="utf-8"))


def _command_lock(task_id: str, index: int) -> HweCommandImageLock:
    return build_hwe_command_image_lock(
        task_id=task_id,
        task_hash=f"{index + 1:064x}",
        source_hash=f"{index + 10:064x}",
        verifier_base_image_id="sha256:" + f"{index + 20:064x}",
        derived_command_image_id="sha256:" + f"{index + 30:064x}",
        rg_sha256="a" * 64,
        rg_release_archive_sha256="b" * 64,
        toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
        allowlisted_artifacts=[
            {"path": "/usr/bin/make", "sha256": "c" * 64, "role": "build_tool"},
            {
                "path": "/tools/verilator/bin/verilator_bin",
                "sha256": "d" * 64,
                "role": "simulator",
            },
        ],
        security_scan_id=f"{index + 40:064x}",
    )


def _contract() -> tuple[dict[str, object], dict[str, HweCommandImageLock]]:
    locks = {task_id: _command_lock(task_id, index) for index, task_id in enumerate(_runner._TASKS)}
    roles = ("training", "validation")
    base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V37_CANARY_CONTRACT_FORMAT,
        "protocol_profile": OPENHANDS_V20_TOOL_CHOICE_POLICY,
        "predecessor_catalog_hash": "f" * 64,
        "schedule": [
            {
                "task_id": task_id,
                "role": roles[index],
                "seed": OPENHANDS_V37_CANARY_SEED,
                "sample_index": OPENHANDS_V37_CANARY_SAMPLE_INDEX,
            }
            for index, task_id in enumerate(_runner._TASKS)
        ],
        "task_bindings": {
            task_id: {
                "task_hash": lock.task_hash,
                "source_hash": lock.source_hash,
                "command_image_lock_hash": lock.lock_hash,
                "command_image": lock.derived_command_image_id,
                "verifier_image": lock.verifier_base_image_id,
                "security_scan_id": lock.security_scan_id,
            }
            for task_id, lock in locks.items()
        },
        "runtime": {
            "command_execution_backend": OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
            "command_role": "credential_free_command_image",
            "network": "none",
            "codex_present": False,
            "provider_credentials_in_command_container": False,
        },
        "heldout_task_ids_loaded": [],
    }
    return {**base, "contract_hash": content_hash(base)}, locks


def _six_plane_attempt(**changes: object) -> dict[str, object]:
    attempt: dict[str, object] = {
        "result": {
            "benchmark_verifier_pass": True,
            "agent_protocol_valid": True,
            "trajectory_eligible": True,
            "infrastructure_valid": True,
            "security_valid": True,
            "sft_admitted": True,
        },
        "trajectory_receipt": {"receipt_hash": "a" * 64},
        "decision_receipt": {"receipt_hash": "b" * 64},
        "token_receipt": {"receipt_hash": "c" * 64},
        "exact_64k_eligible": True,
        "decision_only_loss_mask": True,
        "public_tool_thought_supervised": True,
        "truncation_applied": False,
    }
    attempt.update(changes)
    return attempt


def test_v37_authorization_binds_fresh_schedule_v20_and_no_collection() -> None:
    authorization = _authorization()
    validated = _runner._validated_authorization(authorization)
    base = copy.deepcopy(authorization)
    observed = base.pop("authorization_hash")

    assert observed == content_hash(base) == _runner.OPENHANDS_V37_APPROVAL_HASH
    assert validated["failed_v36_evidence"]["provider_call_count"] == 1
    assert validated["failed_v36_evidence"]["failed_task_retry_authorized"] is False
    assert validated["schedule"]["task_ids"] == list(_runner._TASKS)
    assert "pr-2330" not in " ".join(validated["schedule"]["task_ids"])
    assert validated["schedule"]["pr3226_consumed_as_canary"] is True
    assert validated["schedule"]["formal_training_schedule_requires_replacement"] is True
    assert validated["protocol"]["profile"] == OPENHANDS_V20_TOOL_CHOICE_POLICY
    assert validated["protocol"]["public_visible_tool_thought_supervised"] is True
    assert validated["provider_budget"] == {
        "temperature": 0,
        "max_provider_calls_per_episode": 64,
        "max_provider_tokens_per_episode": 1_000_000,
        "max_context_tokens": 65_536,
        "max_output_tokens": 2_048,
        "provider_request_retries": 0,
        "whole_episode_retries": 0,
    }
    assert validated["formal_collection_allowed"] is False
    assert validated["authorized_actions"]["start_formal_collection"] is False
    assert validated["authorized_actions"]["start_training"] is False


def test_v37_authorization_rejects_task_protocol_or_collection_substitution() -> None:
    for section, field, value in (
        ("schedule", "task_ids", list(reversed(_runner._TASKS))),
        ("runtime", "network", "bridge"),
        ("protocol", "private_reasoning_rejected", False),
        ("authorized_actions", "retry_pr2330", True),
        ("authorized_actions", "start_formal_collection", True),
    ):
        changed = _authorization()
        changed[section][field] = value  # type: ignore[index]
        changed_base = copy.deepcopy(changed)
        changed_base.pop("authorization_hash")
        changed["authorization_hash"] = content_hash(changed_base)
        with pytest.raises(ConfigurationError, match="authorization identity changed"):
            _runner._validated_authorization(changed)


def test_v37_agent_version_is_fresh_and_binds_v20_and_images() -> None:
    contract, locks = _contract()
    version = build_v37_canary_agent_version(
        contract=contract,
        source_commit="e" * 40,
        command_image_locks=locks,
        predecessor_report_hash="d" * 64,
        v33_catalog_hash="f" * 64,
        control_plane_contract_hash="1" * 64,
    )
    training = build_v37_canary_agent_options(
        seed=OPENHANDS_V37_CANARY_SEED,
        role="training",
        agent_version=version,
    )
    validation = build_v37_canary_agent_options(
        seed=OPENHANDS_V37_CANARY_SEED,
        role="validation",
        agent_version=version,
    )

    assert validate_agent_version(version) == version
    assert version.agent_version_id == OPENHANDS_V37_CANARY_AGENT_VERSION_ID
    assert set(version.image_hashes) == {
        "pr3226-command",
        "pr3226-verifier",
        "pr3204-command",
        "pr3204-verifier",
    }
    assert training["tool_choice_policy"] == OPENHANDS_V20_TOOL_CHOICE_POLICY
    assert training["campaign_role"] == "training"
    assert validation["campaign_role"] == "validation"
    assert training["max_iterations"] == 64
    assert training["max_provider_billed_units"] == 1_000_000
    assert training["max_context_tokens"] == 65_536
    assert training["max_output_tokens"] == 2_048
    assert training["whole_episode_retries"] == 0


def test_v37_runtime_uses_only_the_locked_command_image() -> None:
    lock = _command_lock(_runner._TRAINING_TASK, 0)
    config = _runner._runtime_config(lock)
    assert config.external_agent is None
    assert config.network_mode == "none"
    assert config.command_image is not None
    assert config.command_image.expected_image_id == lock.derived_command_image_id
    assert config.command_image.execution_backend == OPENHANDS_V37_COMMAND_EXECUTION_BACKEND

    manifest = {
        "docker_role_images": {
            "external_agent": None,
            "command": {"resolved_image_id": lock.derived_command_image_id},
        },
        "external_agent_execution_backend": "runtime_external_process_unavailable",
        "external_agent_command_execution_backend": OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
    }
    _runner._validate_runtime_manifest(manifest, lock)
    manifest["external_agent_execution_backend"] = "docker_outer_runtime_delegated"
    with pytest.raises(ConfigurationError, match="runtime evidence changed"):
        _runner._validate_runtime_manifest(manifest, lock)


def test_v37_stops_after_any_failed_plane_or_exact_64k_failure() -> None:
    assert _runner._attempt_stop_kind(_six_plane_attempt()) is None
    for plane in (
        "benchmark_verifier_pass",
        "agent_protocol_valid",
        "trajectory_eligible",
        "sft_admitted",
    ):
        attempt = _six_plane_attempt()
        attempt["result"][plane] = False  # type: ignore[index]
        assert _runner._attempt_stop_kind(attempt) == "six_plane_gate_failed"

    attempt = _six_plane_attempt()
    attempt["result"]["security_valid"] = False  # type: ignore[index]
    assert _runner._attempt_stop_kind(attempt) == "infrastructure_or_security_invalid"
    assert _runner._attempt_stop_kind(_six_plane_attempt(token_receipt=None)) == (
        "six_plane_gate_failed"
    )
    assert _runner._attempt_stop_kind(_six_plane_attempt(public_tool_thought_supervised=False)) == (
        "six_plane_gate_failed"
    )


def test_v37_runtime_evidence_requires_safe_shape_and_public_thought_accounting() -> None:
    protocol = build_v20_protocol_receipt(
        provider={
            "provider_call_count": 2,
            "successful_provider_response_count": 2,
            "provider_usage_record_count": 2,
            "input_tokens": 100,
            "output_tokens": 20,
        },
        protocol={
            "required_tool_request_count": 2,
            "canonical_tool_response_count": 2,
            "mixed_content_tool_response_count": 1,
            "content_only_response_count": 0,
            "format_recovery_count": 0,
            "recovery_forced_request_count": 0,
            "recovery_validated_tool_count": 0,
            "over_budget_response_count": 0,
        },
        broker_decision_steps=2,
    )
    summary = {
        "provider_response_shape": {
            "reasoning_content_present": False,
            "responses_reasoning_present": False,
            "thinking_blocks_present": False,
            "raw_model_content_persisted": False,
            "raw_tool_arguments_persisted": False,
        },
        "tool_choice_policy": OPENHANDS_V20_TOOL_CHOICE_POLICY,
        "v20_protocol_receipt_hash": protocol["receipt_hash"],
        "provider_call_budget": 64,
        "provider_call_count": 2,
        "provider_input_tokens": 100,
        "provider_output_tokens": 20,
        "provider_total_tokens": 120,
        "required_tool_request_count": 2,
        "canonical_tool_response_count": 2,
        "content_free_tool_response_count": 1,
        "mixed_content_tool_response_count": 1,
        "content_only_response_count": 0,
        "whole_episode_retries": 0,
        "local_repository_exposed_to_openhands": False,
        "docker_socket_exposed_to_openhands": False,
        "default_tools_exposed": False,
        "plugins_loaded": False,
    }
    broker = {"finished": True, "infrastructure_failure": None, "decision_steps": 2}
    accounting = ExternalAgentAccounting(
        process_wall_time_s=1.0,
        cli_event_count=2,
        model_call_count=2,
        input_tokens=100,
        output_tokens=20,
    )
    assert (
        validate_v37_canary_runtime_evidence(
            broker=broker,
            summary=summary,
            accounting=accounting,
            protocol_receipt=protocol,
        )
        == protocol
    )
    summary["provider_response_shape"]["reasoning_content_present"] = True
    with pytest.raises(ValueError, match="runtime evidence changed"):
        validate_v37_canary_runtime_evidence(
            broker=broker,
            summary=summary,
            accounting=accounting,
            protocol_receipt=protocol,
        )


def test_v37_requires_explicit_opt_in_before_any_provider_episode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OPENHANDS_V37_CANARY_OPT_IN_ENV, raising=False)
    with pytest.raises(ConfigurationError, match=f"{OPENHANDS_V37_CANARY_OPT_IN_ENV}=1"):
        _runner._require_opt_in(_runner.OPENHANDS_V37_CANARY_CAMPAIGN_ID)

    source = Path(_runner.__file__).read_text(encoding="utf-8")
    assert "_zero_call_preflight(root, locks, sources)" in source
    assert source.index("_zero_call_preflight(root, locks, sources)") < source.index(
        "service = _service()"
    )
    assert '"formal_collection_started": False' in source
    assert '"training_started": False' in source
    assert '"pr2330_retry_authorized": False' in source


def test_v37_control_plane_is_exact_and_validated_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = tuple(tmp_path / f"mcp-{index}" for index in range(4))
    broker = tmp_path / "broker"
    broker.mkdir()
    for entry in entries:
        entry.mkdir()
    monkeypatch.setattr(_runner, "_BROKER_ROOT", str(broker))
    monkeypatch.setattr(_runner, "_MCP_PYTHONPATH_ENTRIES", tuple(map(str, entries)))
    monkeypatch.delenv(_runner._BROKER_ROOT_ENV, raising=False)
    monkeypatch.delenv(_runner._MCP_PYTHONPATH_ENV, raising=False)

    with pytest.raises(ConfigurationError, match="broker root contract changed"):
        _runner._validated_control_plane_environment()
    monkeypatch.setenv(_runner._BROKER_ROOT_ENV, str(broker))
    monkeypatch.setenv(_runner._MCP_PYTHONPATH_ENV, os.pathsep.join(map(str, entries)))
    monkeypatch.setattr(hwe_agent, "_configured_control_root", lambda: broker)
    monkeypatch.setattr(
        hwe_agent,
        "_configured_mcp_pythonpath",
        lambda: os.pathsep.join(map(str, entries)),
    )
    observed = _runner._validated_control_plane_environment()

    assert observed["format_id"] == "verigym_openhands_hwe_v37_control_plane_contract_v1"
    source = Path(_runner.__file__).read_text(encoding="utf-8")
    assert source.index("_require_opt_in(arguments.campaign_id)") < source.index(
        "root = _new_output(arguments.output)"
    )


def test_v37_preflight_receipt_is_content_free_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _runner,
        "_validated_control_plane_environment",
        lambda: (_ for _ in ()).throw(ValueError("do not persist this detail")),
    )

    with pytest.raises(ValueError, match="do not persist"):
        _runner._zero_call_preflight(tmp_path, {}, {})
    receipt = json.loads((tmp_path / "zero-call-preflight.json").read_text(encoding="utf-8"))

    assert receipt["status"] == "failed"
    assert receipt["failed_stage"] == "control_plane"
    assert receipt["exception_type"] == "ValueError"
    assert receipt["raw_exception_persisted"] is False
    assert "do not persist this detail" not in json.dumps(receipt)


@pytest.mark.skipif(
    "VERIGYM_V33_EVIDENCE_ROOT" not in os.environ,
    reason="requires the sealed local v33 materialization",
)
def test_v37_accepts_the_sealed_local_v33_evidence_read_only() -> None:
    root = Path(os.environ["VERIGYM_V33_EVIDENCE_ROOT"])
    contract, catalog, progress, locks = _runner._materialized_contract(root)

    assert contract["protocol_profile"] == OPENHANDS_V20_TOOL_CHOICE_POLICY
    assert catalog["catalog_hash"] == _runner._V33_CATALOG_HASH
    assert progress["progress_hash"] == _runner._V33_PROGRESS_HASH
    assert set(locks) == set(_runner._TASKS)


@pytest.mark.skipif(
    "VERIGYM_V36_FAILED_EVIDENCE_ROOT" not in os.environ,
    reason="requires the sealed local v36 failed canary",
)
def test_v37_accepts_the_sealed_local_v36_failure_read_only() -> None:
    root = Path(os.environ["VERIGYM_V36_FAILED_EVIDENCE_ROOT"])
    report = _runner._failed_v36_evidence(root)

    assert report["report_hash"] == _runner._V36_REPORT_HASH
    assert report["provider_call_count"] == 1
    assert len(report["attempts"]) == 1
