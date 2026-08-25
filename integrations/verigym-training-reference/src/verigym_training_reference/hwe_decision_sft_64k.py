"""Exact tool-aware parquet boundary for the frozen DeepSeek Harness 64K dataset."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from verigym.core.hashing import content_hash
from verigym.hwe.qwen_action_tokenizer import loss_mask_sha256, token_ids_sha256
from verigym.schemas.hwe import (
    HweDeepSeekHarnessDecisionSftDatasetManifestV4,
    HweDeepSeekHarnessDecisionSftExampleV4,
)

V4_RECORD_FORMAT = "verigym_hwe_deepseek_harness_decision_sft_64k_v4"
V4_DATASET_FORMAT = "verigym_hwe_deepseek_harness_decision_sft_dataset_64k_v4"
V4_MAX_LENGTH = 65_536
V4_EXPECTED_RECORDS = 83
V4_EXPECTED_TOOL_ACTIONS = 85
V4_EXPECTED_MAX_TOKENS = 50_117
V4_TOOL_NAMES = (
    "apply_patch",
    "finish",
    "inspect_diff",
    "list_files",
    "read_file",
    "shell",
)
_MAX_DATASET_BYTES = 16 * 1024 * 1024


class ToolAwareTokenizer(Protocol):
    chat_template: str

    def apply_chat_template(
        self,
        conversation: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> Any: ...

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


@dataclass(frozen=True)
class ExactToolAwareTokens:
    """Token IDs and the decision-only loss mask produced at the veRL boundary."""

    input_ids: list[int]
    loss_mask: list[int]
    receipt: dict[str, Any]


@dataclass(frozen=True)
class ToolAwareParquetInputs:
    """Validated v4 rows in the exact shape handed from rLLM to veRL."""

    root: Path
    manifest: HweDeepSeekHarnessDecisionSftDatasetManifestV4
    rows: tuple[dict[str, Any], ...]
    train_jsonl_sha256: str


def load_tool_aware_v4_dataset(root: Path) -> ToolAwareParquetInputs:
    """Load the sealed v4 JSONL and materialize its lossless parquet rows."""

    directory = _safe_directory(root)
    manifest_payload = _read_regular(directory / "dataset-manifest.json")
    train_payload = _read_regular(directory / "train.jsonl")
    manifest = HweDeepSeekHarnessDecisionSftDatasetManifestV4.model_validate_json(manifest_payload)
    raw_lines = train_payload.decode("utf-8").splitlines()
    if len(raw_lines) != V4_EXPECTED_RECORDS or any(not line for line in raw_lines):
        raise ValueError("64K v4 train.jsonl must contain exactly 83 non-empty rows")
    examples = [
        HweDeepSeekHarnessDecisionSftExampleV4.model_validate_json(line) for line in raw_lines
    ]
    if [example.record_hash for example in examples] != manifest.record_hashes:
        raise ValueError("64K v4 parquet row order or record identity changed")

    rows = tuple(_parquet_row(example) for example in examples)
    if (
        sum(len(row["messages"][-1]["tool_calls"]) for row in rows) != V4_EXPECTED_TOOL_ACTIONS
        or max(row["exact_token_receipt"]["token_count"] for row in rows) != V4_EXPECTED_MAX_TOKENS
    ):
        raise ValueError("64K v4 parquet action or token counts changed")
    return ToolAwareParquetInputs(
        root=directory,
        manifest=manifest,
        rows=rows,
        train_jsonl_sha256=hashlib.sha256(train_payload).hexdigest(),
    )


def write_tool_aware_parquet(inputs: ToolAwareParquetInputs, output: Path) -> str:
    """Write one lossless parquet file without Arrow struct-union coercion."""

    if output.exists() or output.is_symlink():
        raise ValueError("tool-aware parquet output must not already exist")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    import pyarrow as pa  # type: ignore[import-untyped]
    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    encoded_rows = [_encode_parquet_payloads(row) for row in inputs.rows]
    partial = output.with_name(f".{output.name}.partial")
    if partial.exists() or partial.is_symlink():
        raise ValueError("tool-aware parquet partial output already exists")
    table = pa.Table.from_pylist(encoded_rows)
    try:
        pq.write_table(table, partial, compression="zstd")
        loaded = read_tool_aware_parquet(partial)
        if loaded != list(inputs.rows):
            raise ValueError("messages, tools, or exact receipts changed in parquet round-trip")
        os.replace(partial, output)
    finally:
        if partial.exists():
            partial.unlink()
    return hashlib.sha256(output.read_bytes()).hexdigest()


def read_tool_aware_parquet(path: Path) -> list[dict[str, Any]]:
    """Read and validate the semantic parquet boundary used by veRL."""

    payload_path = _safe_regular_path(path)
    import pyarrow.parquet as pq

    raw_rows = pq.read_table(payload_path).to_pylist()
    rows = [_decode_parquet_payloads(row) for row in raw_rows]
    for index, row in enumerate(rows):
        _validate_parquet_row(row, index=index)
    return rows


def decode_tool_aware_parquet_value(value: Any, *, field: str) -> Any:
    """Decode one canonical JSON payload as seen by pandas/veRL."""

    plain = _plain_value(value)
    if not isinstance(plain, str):
        raise ValueError(f"tool-aware parquet {field} must be canonical JSON text")
    try:
        decoded = json.loads(plain)
    except json.JSONDecodeError as exc:
        raise ValueError(f"tool-aware parquet {field} contains invalid JSON") from exc
    if _canonical_json(decoded) != plain:
        raise ValueError(f"tool-aware parquet {field} is not canonical JSON")
    return decoded


def tool_aware_exact_final_decision_tokens(
    tokenizer: ToolAwareTokenizer,
    *,
    messages: Any,
    tools: Any,
    expected_receipt: Any,
    tokenizer_id: str,
    tokenizer_hash: str,
) -> ExactToolAwareTokens:
    """Independently reproduce the v4 token receipt at dataset access time."""

    normalized_messages = _plain_value(messages)
    normalized_tools = _plain_value(tools)
    normalized_receipt = _plain_value(expected_receipt)
    if not isinstance(normalized_messages, list) or len(normalized_messages) < 3:
        raise ValueError("tool-aware row requires a complete message list")
    if not isinstance(normalized_tools, list):
        raise ValueError("tool-aware row is missing tools")
    if not isinstance(normalized_receipt, dict):
        raise ValueError("tool-aware row is missing its exact token receipt")
    _validate_tools(normalized_tools)
    if [item.get("role") for item in normalized_messages[:2]] != ["system", "user"]:
        raise ValueError("tool-aware messages must start with system then user")
    target = normalized_messages[-1]
    if target.get("role") != "assistant" or not target.get("tool_calls"):
        raise ValueError("tool-aware row must end with one complete assistant decision")

    adapted = _adapt_openai_tool_arguments(copy.deepcopy(normalized_messages))
    prefix = _render(tokenizer, adapted[:-1], normalized_tools)
    full = _render(tokenizer, adapted, normalized_tools)
    if not full.startswith(prefix) or full == prefix:
        raise ValueError("tool-aware chat template is not final-decision prefix stable")
    prefix_ids = _encode(tokenizer, prefix)
    full_ids = _encode(tokenizer, full)
    if not prefix_ids or full_ids[: len(prefix_ids)] != prefix_ids:
        raise ValueError("tool-aware input token prefix changed")
    target_count = len(full_ids) - len(prefix_ids)
    if target_count <= 0:
        raise ValueError("tool-aware target token segment is empty")
    loss_mask = [0] * len(prefix_ids) + [1] * target_count
    actual = {
        "tokenizer_id": tokenizer_id,
        "tokenizer_hash": tokenizer_hash,
        "chat_template_hash": hashlib.sha256(tokenizer.chat_template.encode("utf-8")).hexdigest(),
        "token_count": len(full_ids),
        "input_tokens": len(prefix_ids),
        "target_tokens": target_count,
        "input_ids_sha256": token_ids_sha256(full_ids),
        "loss_mask_sha256": loss_mask_sha256(loss_mask),
        "input_ids_hash_format": "sha256_u32be_v1",
        "loss_mask_hash_format": "sha256_bytes_v1",
    }
    if actual != normalized_receipt:
        changed = sorted(key for key in actual if actual[key] != normalized_receipt.get(key))
        raise ValueError(f"tool-aware exact token receipt drifted: {', '.join(changed)}")
    if len(full_ids) > V4_MAX_LENGTH:
        raise ValueError("tool-aware row exceeds the frozen 64K bound; truncation is forbidden")
    return ExactToolAwareTokens(full_ids, loss_mask, actual)


def _parquet_row(example: HweDeepSeekHarnessDecisionSftExampleV4) -> dict[str, Any]:
    value = example.model_dump(mode="json")
    receipt_keys = (
        "tokenizer_id",
        "tokenizer_hash",
        "chat_template_hash",
        "token_count",
        "input_tokens",
        "target_tokens",
        "input_ids_sha256",
        "loss_mask_sha256",
        "input_ids_hash_format",
        "loss_mask_hash_format",
    )
    row = {
        "format_id": value["format_id"],
        "source_v3_dataset_hash": value["source_v3_dataset_hash"],
        "source_v3_record_index": value["source_v3_record_index"],
        "source_v3_record_hash": value["source_v3_record_hash"],
        "record_hash": value["record_hash"],
        "messages": [*value["input_messages"], value["target_message"]],
        "tools": value["tools"],
        "tool_schema_hash": value["tool_schema_hash"],
        "exact_token_receipt": {key: value[key] for key in receipt_keys},
        "max_length": value["max_length"],
        "truncation": value["truncation"],
    }
    _validate_parquet_row(row, index=value["source_v3_record_index"])
    return row


def _validate_parquet_row(row: Any, *, index: int) -> None:
    if not isinstance(row, dict):
        raise ValueError(f"tool-aware parquet row {index} is not an object")
    required = {
        "format_id",
        "source_v3_dataset_hash",
        "source_v3_record_index",
        "source_v3_record_hash",
        "record_hash",
        "messages",
        "tools",
        "tool_schema_hash",
        "exact_token_receipt",
        "max_length",
        "truncation",
    }
    if set(row) != required or row.get("format_id") != V4_RECORD_FORMAT:
        raise ValueError(f"tool-aware parquet row {index} fields changed")
    if row.get("source_v3_record_index") != index:
        raise ValueError(f"tool-aware parquet row {index} order changed")
    tools = _plain_value(row.get("tools"))
    _validate_tools(tools)
    if row.get("tool_schema_hash") != content_hash(tools):
        raise ValueError(f"tool-aware parquet row {index} tool schema changed")
    messages = _plain_value(row.get("messages"))
    receipt = _plain_value(row.get("exact_token_receipt"))
    if not isinstance(messages, list) or not isinstance(receipt, dict):
        raise ValueError(f"tool-aware parquet row {index} payload is malformed")
    if row.get("max_length") != V4_MAX_LENGTH or row.get("truncation") != "error":
        raise ValueError(f"tool-aware parquet row {index} permits truncation")
    if receipt.get("token_count", V4_MAX_LENGTH + 1) > V4_MAX_LENGTH:
        raise ValueError(f"tool-aware parquet row {index} is overlength")


def _encode_parquet_payloads(row: dict[str, Any]) -> dict[str, Any]:
    encoded = copy.deepcopy(row)
    for field in ("messages", "tools", "exact_token_receipt"):
        encoded[field] = _canonical_json(encoded[field])
    return encoded


def _decode_parquet_payloads(row: dict[str, Any]) -> dict[str, Any]:
    decoded = copy.deepcopy(row)
    for field in ("messages", "tools", "exact_token_receipt"):
        decoded[field] = decode_tool_aware_parquet_value(decoded.get(field), field=field)
    return decoded


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_tools(tools: Any) -> None:
    if not isinstance(tools, list) or len(tools) != len(V4_TOOL_NAMES):
        raise ValueError("tool-aware row must preserve exactly six tool schemas")
    names = tuple(
        item.get("function", {}).get("name") if isinstance(item, dict) else None for item in tools
    )
    if names != V4_TOOL_NAMES:
        raise ValueError("tool-aware row tool schemas or order changed")


def _render(
    tokenizer: ToolAwareTokenizer,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> str:
    rendered = tokenizer.apply_chat_template(
        messages,
        tools=tools,
        tokenize=False,
        add_generation_prompt=False,
    )
    if not isinstance(rendered, str):
        raise ValueError("tool-aware chat template did not return text")
    return rendered


def _encode(tokenizer: ToolAwareTokenizer, text: str) -> list[int]:
    ids = tokenizer.encode(text, add_special_tokens=False)
    if not isinstance(ids, list) or any(not isinstance(item, int) for item in ids):
        raise ValueError("tool-aware tokenizer returned malformed input IDs")
    return ids


def _adapt_openai_tool_arguments(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for message in messages:
        calls = message.get("tool_calls")
        if calls is None:
            continue
        if not isinstance(calls, list) or not calls:
            raise ValueError("tool-aware assistant tool_calls must be a non-empty list")
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("arguments"), str):
                raise ValueError("tool-aware assistant call is malformed")
            try:
                arguments = json.loads(function["arguments"])
            except json.JSONDecodeError as exc:
                raise ValueError("tool-aware assistant arguments are invalid JSON") from exc
            if not isinstance(arguments, dict):
                raise ValueError("tool-aware assistant arguments must decode to an object")
            function["arguments"] = arguments
    return messages


def _plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    if hasattr(value, "as_py"):
        return _plain_value(value.as_py())
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        return _plain_value(value.tolist())
    return value


def _safe_directory(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("64K v4 dataset root cannot be a symlink")
    root = path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("64K v4 dataset root must be a directory")
    return root


def _safe_regular_path(path: Path) -> Path:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("tool-aware parquet input must be a regular file")
    return path.resolve(strict=True)


def _read_regular(path: Path) -> bytes:
    safe = _safe_regular_path(path)
    size = safe.stat().st_size
    if size <= 0 or size > _MAX_DATASET_BYTES:
        raise ValueError(f"64K v4 dataset file size is invalid: {safe.name}")
    return safe.read_bytes()


__all__ = [
    "ExactToolAwareTokens",
    "ToolAwareParquetInputs",
    "V4_DATASET_FORMAT",
    "V4_EXPECTED_MAX_TOKENS",
    "V4_EXPECTED_RECORDS",
    "V4_EXPECTED_TOOL_ACTIONS",
    "V4_MAX_LENGTH",
    "V4_RECORD_FORMAT",
    "V4_TOOL_NAMES",
    "decode_tool_aware_parquet_value",
    "load_tool_aware_v4_dataset",
    "read_tool_aware_parquet",
    "tool_aware_exact_final_decision_tokens",
    "write_tool_aware_parquet",
]
