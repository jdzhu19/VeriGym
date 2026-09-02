from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
from typing import cast

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.memory import validate_agent_version
from verigym.hwe.image_lock import HweCommandImageLock, build_hwe_command_image_lock
from verigym.schemas.external_agent import ExternalAgentAccounting

from verigym_openhands.hwe_v23 import build_v23_protocol_receipt
from verigym_openhands.hwe_v23_protocol import OPENHANDS_V23_TOOL_CHOICE_POLICY
from verigym_openhands.hwe_v58_ibex_canary_runtime import (
    OPENHANDS_V58_AGENT_VERSION_ID,
    OPENHANDS_V58_OPT_IN_ENV,
    OPENHANDS_V58_SAMPLE_INDEX,
    OPENHANDS_V58_SEED,
    OPENHANDS_V58_TASK_ID,
    build_v58_agent_options,
    build_v58_agent_version,
    validate_v58_authorization,
    validate_v58_runtime_evidence,
)

_runner = importlib.import_module("scripts.collect_ibex_hwe_openhands_v58_provider_canary")
_REPOSITORY = Path(__file__).resolve().parents[3]
_AUTHORIZATION = (
    _REPOSITORY / "configs/training/qwen35_hwe_openhands_v58_ibex_pr54_provider_canary_v1.json"
)


def _authorization() -> dict[str, object]:
    value = json.loads(_AUTHORIZATION.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _command_lock() -> HweCommandImageLock:
    return build_hwe_command_image_lock(
        task_id=OPENHANDS_V58_TASK_ID,
        task_hash="b03b430845b6bb97a0b0443c52d337817b4ff33e3cc1b3ea15800bb8bfb4a14a",
        source_hash="5393fbc4261f1a8e19ba7af7b1501367a6c1f3c28bed72f556291f734d095914",
        verifier_base_image_id=(
            "sha256:a35075b506d4d8b4e9434e31f38ee0699afdb18f7119e324d49bee60565f5bfa"
        ),
        derived_command_image_id=(
            "sha256:6f88fdae127f75326407b4ebff529fea5f87aeb64997970d4408678fab942c3b"
        ),
        rg_sha256="e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849",
        rg_release_archive_sha256=(
            "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c"
        ),
        toolchain_profile_id="ibex-iverilog-container-native-v1",
        allowlisted_artifacts=[
            {
                "path": "/usr/bin/make",
                "sha256": "92f646030615cd98490a68a94c0aefd87b552be3158b941c02e43b0bfdb576db",
                "role": "build_tool",
            },
            {
                "path": "/usr/bin/iverilog",
                "sha256": "1ba67856249142771239573b5d51c7f6e4d67a1e7931a0d0fab56e0d473d2167",
                "role": "simulator",
            },
            {
                "path": "/usr/bin/vvp",
                "sha256": "075b114070eed3bc72e0e4559decf40520f3b693b1da9c94bba1defe8896966d",
                "role": "simulator",
            },
            {
                "path": "/usr/local/lib/verigym-command-tools/rg",
                "sha256": "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849",
                "role": "public_asset",
            },
        ],
        source_whiteout_path="/home/ibex",
        security_scan_id="1bd004e75bdf245596bd1bcd3021d184123203711c30fda24969d040656ed281",
    )


def _protocol() -> dict[str, object]:
    observation = [
        {
            "sequence": index,
            "raw_sha256": hashlib.sha256(f"raw-{index}".encode()).hexdigest(),
            "raw_bytes": 10 + index,
            "compact_sha256": hashlib.sha256(f"compact-{index}".encode()).hexdigest(),
            "compact_tokens": 20 + index,
            "rule_id": "hwe_repository_observation_v2/read_v23",
            "omitted": False,
        }
        for index in range(3)
    ]
    progress = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_v23_progress_observation_receipt_v1",
        "first_effective_modification_action": 2,
        "progress_checkpoint_action": None,
        "progress_checkpoint_injected": False,
        "progress_checkpoint_sha256": hashlib.sha256(b"checkpoint").hexdigest(),
        "no_progress_action": None,
        "no_progress_terminated": False,
        "progress_gate_state": "released_after_modification",
        "observation_compaction": observation,
    }
    return cast(
        dict[str, object],
        build_v23_protocol_receipt(
            provider={
                "provider_call_count": 3,
                "successful_provider_response_count": 3,
                "provider_usage_record_count": 3,
                "input_tokens": 100,
                "output_tokens": 20,
            },
            protocol={
                "ordinary_auto_request_count": 2,
                "required_tool_request_count": 1,
                "canonical_tool_decision_count": 2,
                "canonical_tool_call_count": 3,
                "public_text_decision_count": 1,
                "content_only_response_count": 1,
                "format_recovery_count": 1,
                "recovery_validated_tool_count": 1,
                "over_budget_response_count": 0,
                "decision_tool_call_counts": [2, 1],
                "sibling_tool_decision_count": 1,
                "sibling_tool_call_count": 2,
            },
            broker={"tool_calls": 3, "decision_steps": 2, "finished": True},
            progress=progress,
            stuck_status="not_stuck",
        ),
    )


def test_v58_authorization_is_single_use_v23_and_does_not_start_collection() -> None:
    authorization = _authorization()
    validated = validate_v58_authorization(authorization)
    base = copy.deepcopy(authorization)
    observed = base.pop("authorization_hash")

    assert observed == content_hash(base) == _runner._AUTHORIZATION_HASH
    assert validated["schedule"] == [
        {
            "task_id": OPENHANDS_V58_TASK_ID,
            "role": "training",
            "seed": OPENHANDS_V58_SEED,
            "sample_index": OPENHANDS_V58_SAMPLE_INDEX,
        }
    ]
    assert validated["protocol"]["profile"] == OPENHANDS_V23_TOOL_CHOICE_POLICY
    assert validated["protocol"]["ordinary_tool_choice"] == "auto"
    assert validated["protocol"]["content_only_recovery_tool_choice"] == "required"
    assert validated["protocol"]["provider_hidden_thinking"] == "disabled"
    assert validated["authorized_actions"]["retry_pr54"] is False
    assert validated["formal_collection_allowed"] is False
    assert validated["training_started"] is False


def test_v58_authorization_rejects_task_protocol_budget_or_retry_substitution() -> None:
    for section, field, value in (
        ("task_binding", "task_id", "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-55"),
        ("protocol", "ordinary_tool_choice", "required"),
        ("protocol", "provider_hidden_thinking", "enabled"),
        ("provider_budget", "whole_episode_retries", 1),
        ("authorized_actions", "retry_pr54", True),
    ):
        changed = _authorization()
        changed[section][field] = value  # type: ignore[index]
        changed_base = copy.deepcopy(changed)
        changed_base.pop("authorization_hash")
        changed["authorization_hash"] = content_hash(changed_base)
        with pytest.raises(ValueError, match="authorization policy changed"):
            validate_v58_authorization(changed)


def test_v58_agent_version_binds_ibex_images_v23_and_exact_budgets() -> None:
    authorization = _authorization()
    version = build_v58_agent_version(
        authorization=authorization,
        source_commit="e" * 40,
        command_image_lock=_command_lock(),
    )
    options = build_v58_agent_options(agent_version=version)

    assert validate_agent_version(version) == version
    assert version.agent_version_id == OPENHANDS_V58_AGENT_VERSION_ID
    assert set(version.image_hashes) == {"ibex-pr54-command", "ibex-pr54-verifier"}
    assert options["tool_choice_policy"] == OPENHANDS_V23_TOOL_CHOICE_POLICY
    assert options["max_iterations"] == 64
    assert options["max_provider_billed_units"] == 1_000_000
    assert options["max_context_tokens"] == 65_536
    assert options["max_output_tokens"] == 2_048
    assert options["whole_episode_retries"] == 0
    assert options["campaign_role"] == "training"


def test_v58_runtime_evidence_reconciles_auto_recovery_siblings_and_hidden_reasoning() -> None:
    protocol = _protocol()
    summary = {
        "provider_response_shape": {
            "reasoning_content_present": False,
            "responses_reasoning_present": False,
            "thinking_blocks_present": False,
            "raw_model_content_persisted": False,
            "raw_tool_arguments_persisted": False,
        },
        "private_reasoning_persisted": False,
        "tool_choice_policy": OPENHANDS_V23_TOOL_CHOICE_POLICY,
        "v23_protocol_receipt_hash": protocol["receipt_hash"],
        "provider_call_budget": 64,
        "provider_call_count": 3,
        "provider_input_tokens": 100,
        "provider_output_tokens": 20,
        "provider_total_tokens": 120,
        "ordinary_auto_request_count": 2,
        "recovery_required_request_count": 1,
        "canonical_tool_decision_count": 2,
        "canonical_tool_call_count": 3,
        "public_text_decision_count": 1,
        "sibling_tool_decision_count": 1,
        "sibling_tool_call_count": 2,
        "first_effective_modification_action": 2,
        "progress_checkpoint_injected": False,
        "no_progress_terminated": False,
        "stuck_status": "not_stuck",
        "whole_episode_retries": 0,
        "local_repository_exposed_to_openhands": False,
        "docker_socket_exposed_to_openhands": False,
        "default_tools_exposed": False,
        "plugins_loaded": False,
    }
    accounting = ExternalAgentAccounting(
        process_wall_time_s=1.0,
        cli_event_count=2,
        model_call_count=3,
        input_tokens=100,
        output_tokens=20,
    )
    assert (
        validate_v58_runtime_evidence(
            broker={"finished": True, "infrastructure_failure": None},
            summary=summary,
            accounting=accounting,
            protocol_receipt=protocol,
        )
        == protocol
    )
    summary["provider_response_shape"]["reasoning_content_present"] = True
    with pytest.raises(ValueError, match="runtime evidence changed"):
        validate_v58_runtime_evidence(
            broker={"finished": True, "infrastructure_failure": None},
            summary=summary,
            accounting=accounting,
            protocol_receipt=protocol,
        )


def test_v58_attempt_gate_requires_six_planes_exact_64k_and_unsplit_siblings() -> None:
    attempt: dict[str, object] = {
        "result": {
            "benchmark_verifier_pass": True,
            "agent_protocol_valid": True,
            "trajectory_eligible": True,
            "infrastructure_valid": True,
            "security_valid": True,
            "sft_admitted": True,
        },
        "trajectory_receipt": {},
        "decision_receipt": {},
        "token_receipt": {},
        "exact_64k_eligible": True,
        "decision_only_loss_mask": True,
        "public_rationale_supervised": True,
        "content_only_recovery_supervised": False,
        "failed_tool_decisions_supervised": False,
        "sibling_targets_split": False,
        "truncation_applied": False,
    }
    assert _runner._attempt_stop_kind(attempt) is None
    changed = copy.deepcopy(attempt)
    changed["sibling_targets_split"] = True
    assert _runner._attempt_stop_kind(changed) == "six_plane_gate_failed"
    changed = copy.deepcopy(attempt)
    changed["result"]["security_valid"] = False  # type: ignore[index]
    assert _runner._attempt_stop_kind(changed) == "infrastructure_or_security_invalid"


def test_v58_requires_opt_in_and_preflight_before_provider_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OPENHANDS_V58_OPT_IN_ENV, raising=False)
    with pytest.raises(ConfigurationError, match=f"{OPENHANDS_V58_OPT_IN_ENV}=1"):
        _runner._require_opt_in(_runner.OPENHANDS_V58_CAMPAIGN_ID)

    source = Path(_runner.__file__).read_text(encoding="utf-8")
    assert source.index("_zero_call_preflight(root, lock, source_root)") < source.index(
        "attempt = _run_episode("
    )
    assert '"retry_authorized": False' in source
    assert '"formal_collection_allowed": False' in source
    assert '"training_started": False' in source


def test_v58_required_merged_paths_include_authorization_runner_protocol_and_audit() -> None:
    required = set(_runner._REQUIRED_MERGED_PATHS)
    assert {
        "configs/training/qwen35_hwe_openhands_v58_ibex_pr54_provider_canary_v1.json",
        "docs/audits/2026-09-02_openhands-ibex-pr54-zero-provider-materialization.md",
        "docs/audits/2026-09-02_openhands-v58-ibex-pr54-provider-canary-authorization.md",
        "integrations/verigym-openhands/src/verigym_openhands/hwe_v23.py",
        "integrations/verigym-openhands/src/verigym_openhands/hwe_v23_protocol.py",
        "integrations/verigym-openhands/src/verigym_openhands/hwe_v58_ibex_canary_runtime.py",
        "scripts/collect_ibex_hwe_openhands_v58_provider_canary.py",
    } <= required
    assert not any("pr-167" in path or "pr-222" in path or "pr-1735" in path for path in required)
