from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import collect_ibex_hwe_deepseek_harness_v62_provider_canary as canary
from verigym.core.errors import ConfigurationError
from verigym.hwe.image_lock import HweCommandImageLock

_AUTHORIZATION = Path(
    "configs/training/qwen35_hwe_deepseek_harness_v62_ibex_pr974_provider_canary_v1.json"
)
_COMMAND_LOCK = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v61-ibex-pr974-command-image-v1/image-locks/pr-974.json"
)


class _ExactTokenizer:
    tokenizer_id = "Qwen3.5-9B/local-frozen-chat-template"
    tokenizer_hash = "1" * 64
    chat_template_hash = "2" * 64

    def count_decision_example(self, **_kwargs: Any) -> tuple[int, int, int]:
        return 3, 2, 1

    def tokenize_decision_example(self, **_kwargs: Any) -> tuple[list[int], list[int]]:
        return [11, 12, 13], [0, 0, 1]


def _source_row() -> dict[str, Any]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in ("apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell")
    ]
    return {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_deepseek_harness_decision_sft_v3",
        "sample_id": "3" * 64,
        "task_id": canary.TASK_ID,
        "task_hash": "4" * 64,
        "source_hash": "5" * 64,
        "candidate_hash": "6" * 64,
        "verifier_hash": "7" * 64,
        "transcript_hash": "8" * 64,
        "decision_index": 2,
        "target_message_index": 4,
        "call_ids": ["call-diff", "call-finish"],
        "action_names": ["inspect_diff", "finish"],
        "tool_action_count": 2,
        "trajectory_assistant_decision_count": 3,
        "trajectory_accepted_tool_action_count": 2,
        "trajectory_masked_policy_error_decision_count": 1,
        "trajectory_masked_format_error_decision_count": 1,
        "trajectory_format_repair_count": 1,
        "tools": tools,
        "input_messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "masked failed decision"},
            {"role": "tool", "content": "public error"},
        ],
        "target_message": {
            "role": "assistant",
            "content": "Public validation conclusion.",
            "tool_calls": [
                {
                    "id": "call-diff",
                    "type": "function",
                    "function": {"name": "inspect_diff", "arguments": "{}"},
                },
                {
                    "id": "call-finish",
                    "type": "function",
                    "function": {"name": "finish", "arguments": '{"summary":"done"}'},
                },
            ],
        },
        "tokenizer_id": _ExactTokenizer.tokenizer_id,
        "tokenizer_hash": _ExactTokenizer.tokenizer_hash,
        "chat_template_hash": _ExactTokenizer.chat_template_hash,
        "input_tokens": 2,
        "target_tokens": 1,
        "token_count": 3,
        "max_length": 32_768,
        "truncation": "error",
        "eligible": True,
        "supervised_target_kind": "complete_assistant_decision",
        "supervised_roles": ["assistant"],
        "input_loss_masked": True,
        "failed_tool_decisions_loss_masked": True,
        "format_error_decisions_loss_masked": True,
        "exact_model_visible_context": True,
        "context_transformed_after_collection": False,
        "nap_required": False,
        "verifier_resolved": True,
        "infrastructure_valid": True,
        "public_assistant_text_exported": True,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
        "record_hash": "9" * 64,
    }


def test_authorization_is_hash_bound_and_keeps_collection_closed() -> None:
    authorization = json.loads(_AUTHORIZATION.read_text(encoding="utf-8"))
    assert canary.validate_authorization(authorization)["authorization_hash"] == (
        canary.AUTHORIZATION_HASH
    )
    tampered = copy.deepcopy(authorization)
    tampered["provider_budget"]["max_provider_calls"] = 65
    with pytest.raises(ConfigurationError, match="authorization identity"):
        canary.validate_authorization(tampered)


def test_exact_64k_derivation_preserves_public_rationale_and_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_row()
    monkeypatch.setattr(
        canary,
        "materialize_deepseek_harness_decision_examples_v3",
        lambda *_args, **_kwargs: [copy.deepcopy(source)],
    )
    records, dry_runs = canary.materialize_exact_64k_records(
        {"transcript_hash": "8" * 64},
        binding={},
        tokenizer=_ExactTokenizer(),  # type: ignore[arg-type]
    )
    assert len(records) == len(dry_runs) == 1
    assert records[0]["input_messages"] == source["input_messages"]
    assert records[0]["target_message"] == source["target_message"]
    assert records[0]["tool_action_count"] == 2
    assert records[0]["max_length"] == 65_536
    assert records[0]["eligible"] is True
    assert dry_runs[0]["truncation_applied"] is False


@pytest.mark.skipif(not _COMMAND_LOCK.is_file(), reason="v61 command image lock is not installed")
def test_runtime_uses_locked_verilator_command_image_with_no_network() -> None:
    lock = HweCommandImageLock.model_validate_json(_COMMAND_LOCK.read_text(encoding="utf-8"))
    runtime = canary._runtime_config(lock)  # noqa: SLF001
    assert runtime.network_mode == "none"
    assert runtime.command_image is not None
    assert runtime.command_image.network_mode == "none"
    assert runtime.command_image.execution_backend == "episode_container_exec_v1"
    assert runtime.command_image.expected_image_id == lock.derived_command_image_id
    assert (
        runtime.command_image.required_image_labels["org.verigym.ibex.toolchain.profile"]
        == "verilator"
    )
    assert runtime.command_image.required_image_labels["org.verigym.provider_credentials"] == (
        "absent"
    )
