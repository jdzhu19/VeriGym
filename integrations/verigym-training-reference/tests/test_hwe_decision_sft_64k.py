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
    V4_RECORD_FORMAT,
    V4_TOOL_NAMES,
    ToolAwareParquetInputs,
    read_tool_aware_parquet,
    tool_aware_exact_final_decision_tokens,
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
            json.dumps(message, sort_keys=True, separators=(",", ":")) + "\n"
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
        "messages": messages,
        "tools": tools,
        "tool_schema_hash": content_hash(tools),
        "exact_token_receipt": _receipt(tokenizer, messages, tools),
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
