from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from verigym.core.hashing import content_hash
from verigym.hwe.qwen_action_tokenizer import loss_mask_sha256, token_ids_sha256

from verigym_training_reference.hwe_decision_sft_64k import (
    DECISION_BALANCED_OBJECTIVE,
    OPENHANDS_DATASET_FORMAT,
    OPENHANDS_RECORD_FORMAT,
    V4_RECORD_FORMAT,
    V4_TOOL_NAMES,
    ToolAwareParquetInputs,
    load_openhands_tool_aware_dataset,
    read_tool_aware_parquet,
    tool_aware_exact_all_assistant_tokens,
    tool_aware_exact_final_decision_tokens,
    trajectory_balanced_decision_indices,
    write_tool_aware_parquet,
)


class _FakeTokenizer:
    chat_template = "frozen-tool-aware-template"

    def __init__(self) -> None:
        self.tool_calls: list[list[dict[str, Any]]] = []

    def apply_chat_template(
        self,
        conversation: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> str:
        assert tokenize is False
        assert add_generation_prompt is False
        self.tool_calls.append(copy.deepcopy(tools))
        header = json.dumps(tools, sort_keys=True, separators=(",", ":")) + "\n"
        return header + "".join(
            "<|im_start|>"
            + str(message["role"])
            + "\n"
            + json.dumps(message, sort_keys=True, separators=(",", ":"))
            + "\n<|im_end|>\n"
            for message in conversation
        )

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        assert add_special_tokens is False
        return list(text.encode("utf-8"))


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} tool",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
            },
        }
        for name in V4_TOOL_NAMES
    ]


def _messages() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": "public decision",
            "tool_calls": [
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {"name": "inspect_diff", "arguments": '{"value":"a"}'},
                },
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "finish", "arguments": '{"value":"b"}'},
                },
            ],
        },
    ]


def _receipt(
    tokenizer: _FakeTokenizer,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    adapted = copy.deepcopy(messages)
    for message in adapted:
        for call in message.get("tool_calls", []):
            call["function"]["arguments"] = json.loads(call["function"]["arguments"])
    prefix = tokenizer.apply_chat_template(
        adapted[:-1], tools=tools, tokenize=False, add_generation_prompt=False
    )
    full = tokenizer.apply_chat_template(
        adapted, tools=tools, tokenize=False, add_generation_prompt=False
    )
    prefix_ids = tokenizer.encode(prefix, add_special_tokens=False)
    full_ids = tokenizer.encode(full, add_special_tokens=False)
    mask = [0] * len(prefix_ids) + [1] * (len(full_ids) - len(prefix_ids))
    return {
        "tokenizer_id": "Qwen3.5-9B/local-frozen-chat-template",
        "tokenizer_hash": "a" * 64,
        "chat_template_hash": hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
        "token_count": len(full_ids),
        "input_tokens": len(prefix_ids),
        "target_tokens": len(full_ids) - len(prefix_ids),
        "input_ids_sha256": token_ids_sha256(full_ids),
        "loss_mask_sha256": loss_mask_sha256(mask),
        "input_ids_hash_format": "sha256_u32be_v1",
        "loss_mask_hash_format": "sha256_bytes_v1",
    }


def _row() -> dict[str, Any]:
    tokenizer = _FakeTokenizer()
    messages = _messages()
    tools = _tools()
    return {
        "format_id": V4_RECORD_FORMAT,
        "source_v3_dataset_hash": "b" * 64,
        "source_v3_record_index": 0,
        "source_v3_record_hash": "c" * 64,
        "record_hash": "d" * 64,
        "transcript_hash": "f" * 64,
        "decision_index": 0,
        "trajectory_assistant_decision_count": 1,
        "messages": messages,
        "tools": tools,
        "tool_schema_hash": content_hash(tools),
        "exact_token_receipt": _receipt(tokenizer, messages, tools),
        "sft_objective": DECISION_BALANCED_OBJECTIVE,
        "max_length": 65_536,
        "truncation": "error",
    }


def test_tool_aware_loader_preserves_six_tools_and_sibling_calls() -> None:
    row = _row()
    tokenizer = _FakeTokenizer()
    exact = tool_aware_exact_final_decision_tokens(
        tokenizer,
        messages=row["messages"],
        tools=row["tools"],
        expected_receipt=row["exact_token_receipt"],
        tokenizer_id="Qwen3.5-9B/local-frozen-chat-template",
        tokenizer_hash="a" * 64,
    )

    assert len(tokenizer.tool_calls) == 2
    assert tokenizer.tool_calls[0] == tokenizer.tool_calls[1] == row["tools"]
    assert sum(exact.loss_mask) == row["exact_token_receipt"]["target_tokens"]
    assert (
        exact.loss_mask
        == [0] * row["exact_token_receipt"]["input_tokens"]
        + [1] * row["exact_token_receipt"]["target_tokens"]
    )


def test_tool_aware_parquet_round_trip_preserves_absent_schema_keys(tmp_path: Path) -> None:
    row = _row()
    inputs = ToolAwareParquetInputs(
        root=tmp_path,
        manifest=None,  # type: ignore[arg-type]
        rows=(row,),
        train_jsonl_sha256="e" * 64,
    )
    output = tmp_path / "train.parquet"

    assert len(write_tool_aware_parquet(inputs, output)) == 64
    assert read_tool_aware_parquet(output) == [row]


@pytest.mark.parametrize("field", ["tools", "exact_token_receipt"])
def test_tool_aware_loader_rejects_missing_fields(field: str) -> None:
    row = _row()
    row.pop(field)
    tokenizer = _FakeTokenizer()
    with pytest.raises(ValueError, match="missing|requires|must"):
        tool_aware_exact_final_decision_tokens(
            tokenizer,
            messages=row.get("messages"),
            tools=row.get("tools"),
            expected_receipt=row.get("exact_token_receipt"),
            tokenizer_id="Qwen3.5-9B/local-frozen-chat-template",
            tokenizer_hash="a" * 64,
        )


def test_tool_aware_loader_rejects_template_token_and_tool_drift() -> None:
    row = _row()
    changed_template = _FakeTokenizer()
    changed_template.chat_template = "changed"
    with pytest.raises(ValueError, match="chat_template_hash"):
        tool_aware_exact_final_decision_tokens(
            changed_template,
            messages=row["messages"],
            tools=row["tools"],
            expected_receipt=row["exact_token_receipt"],
            tokenizer_id="Qwen3.5-9B/local-frozen-chat-template",
            tokenizer_hash="a" * 64,
        )

    row["tools"][0]["function"]["description"] = "changed"
    with pytest.raises(ValueError, match="receipt drifted"):
        tool_aware_exact_final_decision_tokens(
            _FakeTokenizer(),
            messages=row["messages"],
            tools=row["tools"],
            expected_receipt=row["exact_token_receipt"],
            tokenizer_id="Qwen3.5-9B/local-frozen-chat-template",
            tokenizer_hash="a" * 64,
        )


def test_tool_aware_loader_rejects_overlength_without_truncating() -> None:
    row = _row()
    row["messages"][1]["content"] = "x" * 66_000
    row["exact_token_receipt"] = _receipt(_FakeTokenizer(), row["messages"], row["tools"])
    with pytest.raises(ValueError, match="exceeds the frozen 64K bound"):
        tool_aware_exact_final_decision_tokens(
            _FakeTokenizer(),
            messages=row["messages"],
            tools=row["tools"],
            expected_receipt=row["exact_token_receipt"],
            tokenizer_id="Qwen3.5-9B/local-frozen-chat-template",
            tokenizer_hash="a" * 64,
        )


def test_openhands_dataset_registers_lossless_exact_rows(tmp_path: Path) -> None:
    tokenizer = _FakeTokenizer()
    messages = _messages()
    tools = _tools()
    receipt = _receipt(tokenizer, messages, tools)
    record_base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_RECORD_FORMAT,
        "sample_id": "1" * 64,
        "task_id": "task-1",
        "task_hash": "2" * 64,
        "source_hash": "3" * 64,
        "candidate_hash": "4" * 64,
        "verifier_hash": "5" * 64,
        "transcript_hash": "6" * 64,
        "decision_index": 0,
        "target_message_index": 2,
        "call_ids": ["call-a", "call-b"],
        "action_names": ["inspect_diff", "finish"],
        "tool_action_count": 2,
        "trajectory_assistant_decision_count": 1,
        "tools": tools,
        "tool_schema_hash": content_hash(tools),
        "input_messages": messages[:-1],
        "target_message": messages[-1],
        **receipt,
        "max_length": 65_536,
        "truncation": "error",
        "eligible": True,
        "verifier_resolved": True,
        "infrastructure_valid": True,
        "input_loss_masked": True,
        "exact_model_visible_context": True,
        "context_transformed_after_collection": False,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    record = {**record_base, "record_hash": content_hash(record_base)}
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    manifest_base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_DATASET_FORMAT,
        "record_count": 1,
        "record_hashes": [record["record_hash"]],
        "records_sha256": hashlib.sha256(line.encode()).hexdigest(),
        "trajectory_count": 1,
        "trajectory_hashes": ["6" * 64],
        "supervised_decision_count": 1,
        "max_observed_token_count": receipt["token_count"],
        "max_length": 65_536,
        "truncation": "error",
        "overlength_records": [],
        "exact_token_receipts": True,
        "only_verifier_resolved": True,
        "infrastructure_invalid_excluded": True,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    manifest = {**manifest_base, "dataset_hash": content_hash(manifest_base)}
    dataset = tmp_path / "openhands"
    dataset.mkdir()
    (dataset / "train.jsonl").write_text(line, encoding="utf-8")
    (dataset / "dataset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    inputs = load_openhands_tool_aware_dataset(dataset)

    assert len(inputs.rows) == 1
    assert inputs.rows[0]["source_record"] == record
    assert inputs.rows[0]["messages"] == messages
    assert inputs.rows[0]["tools"] == tools
    assert inputs.rows[0]["sft_objective"] == DECISION_BALANCED_OBJECTIVE
    output = tmp_path / "openhands.parquet"
    write_tool_aware_parquet(inputs, output)
    assert read_tool_aware_parquet(output) == list(inputs.rows)


def test_full_trajectory_objective_supervises_every_assistant_decision() -> None:
    tokenizer = _FakeTokenizer()
    tools = _tools()
    messages = _messages()
    messages.extend(
        [
            {
                "role": "tool",
                "name": "inspect_diff",
                "tool_call_id": "call-a",
                "content": "diff",
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-c",
                        "type": "function",
                        "function": {"name": "finish", "arguments": '{"value":"done"}'},
                    }
                ],
            },
        ]
    )

    exact = tool_aware_exact_all_assistant_tokens(
        tokenizer,
        messages=messages,
        tools=tools,
        tokenizer_id="Qwen3.5-9B/local-frozen-chat-template",
        tokenizer_hash="a" * 64,
    )

    assert exact.receipt["target_tokens"] == sum(exact.loss_mask)
    assert exact.receipt["input_tokens"] + exact.receipt["target_tokens"] == len(exact.input_ids)
    assert (
        exact.receipt["target_tokens"]
        > _receipt(_FakeTokenizer(), _messages(), tools)["target_tokens"]
    )


def test_decision_schedule_weights_trajectories_equally() -> None:
    schedule = trajectory_balanced_decision_indices(
        transcript_hashes=["a" * 64] * 3 + ["b" * 64] * 2,
        decision_indices=[0, 1, 2, 0, 1],
        trajectory_decision_counts=[3, 3, 3, 2, 2],
    )

    assert schedule == (0, 3, 1, 3, 2, 4)
    assert sum(index < 3 for index in schedule) == 3
    assert sum(index >= 3 for index in schedule) == 3


def test_decision_schedule_rejects_index_outside_source_trajectory() -> None:
    with pytest.raises(ValueError, match="exceeds its source trajectory"):
        trajectory_balanced_decision_indices(
            transcript_hashes=["a" * 64],
            decision_indices=[2],
            trajectory_decision_counts=[2],
        )
