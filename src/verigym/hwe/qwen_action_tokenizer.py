"""Exact Qwen chat-template tokenization for HWE action-conditioned rows."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from verigym.core.hashing import content_hash

_TOKENIZER_FILES = frozenset(
    {
        "chat_template.jinja",
        "preprocessor_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    }
)


class QwenChatTemplate(Protocol):
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


class QwenActionExampleTokenizer:
    """Render one exact-context row and supervise only its final assistant action."""

    def __init__(self, tokenizer: QwenChatTemplate, *, tokenizer_root: Path) -> None:
        root = _safe_tokenizer_root(tokenizer_root)
        template = tokenizer.chat_template
        if not isinstance(template, str) or not template:
            raise ValueError("Qwen tokenizer has no frozen chat template")
        self._tokenizer = tokenizer
        self.tokenizer_id = "Qwen3.5-9B/local-frozen-chat-template"
        self.tokenizer_hash = tokenizer_tree_hash(root)
        self.chat_template_hash = hashlib.sha256(template.encode("utf-8")).hexdigest()

    def count_action_example(
        self,
        *,
        tools: Sequence[Mapping[str, Any]],
        input_messages: Sequence[Mapping[str, Any]],
        target_message: Mapping[str, Any],
    ) -> tuple[int, int, int]:
        tokens, loss_mask = self.tokenize_action_example(
            tools=tools,
            input_messages=input_messages,
            target_message=target_message,
        )
        target_tokens = sum(loss_mask)
        return len(tokens), len(tokens) - target_tokens, target_tokens

    def tokenize_action_example(
        self,
        *,
        tools: Sequence[Mapping[str, Any]],
        input_messages: Sequence[Mapping[str, Any]],
        target_message: Mapping[str, Any],
    ) -> tuple[list[int], list[int]]:
        if target_message.get("role") != "assistant":
            raise ValueError("Qwen action-conditioned target must be an assistant message")
        messages = [copy.deepcopy(dict(item)) for item in input_messages]
        if len(messages) < 2 or [item.get("role") for item in messages[:2]] != [
            "system",
            "user",
        ]:
            raise ValueError("Qwen action context must start with system then user")
        target = copy.deepcopy(dict(target_message))
        if target.get("content") not in {None, ""}:
            raise ValueError("Qwen HWE action target cannot contain assistant prose")
        rendered_tools = [copy.deepcopy(dict(item)) for item in tools]
        adapted_input = _adapt_openai_tool_arguments(copy.deepcopy(messages))
        adapted_full = _adapt_openai_tool_arguments(copy.deepcopy([*messages, target]))
        prefix = self._render(adapted_input, rendered_tools)
        full = self._render(adapted_full, rendered_tools)
        if not full.startswith(prefix) or full == prefix:
            raise ValueError("Qwen chat template is not prefix-stable for the final action")
        input_ids = self._encode(prefix)
        full_ids = self._encode(full)
        if full_ids[: len(input_ids)] != input_ids:
            raise ValueError("Qwen tokenizer does not preserve the rendered input token prefix")
        target_ids = full_ids[len(input_ids) :]
        if not input_ids or not target_ids:
            raise ValueError("Qwen action-conditioned tokenization produced an empty segment")
        return full_ids, [0] * len(input_ids) + [1] * len(target_ids)

    def _render(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> str:
        rendered = self._tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=False,
        )
        if not isinstance(rendered, str):
            raise ValueError("Qwen chat template did not return text")
        return rendered

    def _encode(self, text: str) -> list[int]:
        tokens = self._tokenizer.encode(text, add_special_tokens=False)
        if not isinstance(tokens, list) or any(not isinstance(item, int) for item in tokens):
            raise ValueError("Qwen tokenizer returned malformed token ids")
        return tokens


class QwenDecisionExampleTokenizer(QwenActionExampleTokenizer):
    """Render one exact Harness decision, including public text and sibling tool calls."""

    def count_decision_example(
        self,
        *,
        tools: Sequence[Mapping[str, Any]],
        input_messages: Sequence[Mapping[str, Any]],
        target_message: Mapping[str, Any],
    ) -> tuple[int, int, int]:
        tokens, loss_mask = self.tokenize_decision_example(
            tools=tools,
            input_messages=input_messages,
            target_message=target_message,
        )
        target_tokens = sum(loss_mask)
        return len(tokens), len(tokens) - target_tokens, target_tokens

    def tokenize_decision_example(
        self,
        *,
        tools: Sequence[Mapping[str, Any]],
        input_messages: Sequence[Mapping[str, Any]],
        target_message: Mapping[str, Any],
    ) -> tuple[list[int], list[int]]:
        if target_message.get("role") != "assistant":
            raise ValueError("Qwen decision target must be an assistant message")
        messages = [copy.deepcopy(dict(item)) for item in input_messages]
        if len(messages) < 2 or [item.get("role") for item in messages[:2]] != [
            "system",
            "user",
        ]:
            raise ValueError("Qwen decision context must start with system then user")
        target = copy.deepcopy(dict(target_message))
        content = target.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("Qwen decision target content must be public text or null")
        calls = target.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError("Qwen decision target must contain at least one typed tool call")
        rendered_tools = [copy.deepcopy(dict(item)) for item in tools]
        adapted_input = _adapt_openai_tool_arguments(
            copy.deepcopy(messages),
            require_single_call=False,
        )
        adapted_full = _adapt_openai_tool_arguments(
            copy.deepcopy([*messages, target]),
            require_single_call=False,
        )
        prefix = self._render(adapted_input, rendered_tools)
        full = self._render(adapted_full, rendered_tools)
        if not full.startswith(prefix) or full == prefix:
            raise ValueError("Qwen chat template is not prefix-stable for the final decision")
        input_ids = self._encode(prefix)
        full_ids = self._encode(full)
        if full_ids[: len(input_ids)] != input_ids:
            raise ValueError("Qwen tokenizer does not preserve the rendered input token prefix")
        target_ids = full_ids[len(input_ids) :]
        if not input_ids or not target_ids:
            raise ValueError("Qwen decision tokenization produced an empty segment")
        return full_ids, [0] * len(input_ids) + [1] * len(target_ids)


def dry_run_action_record(
    record: Mapping[str, Any],
    *,
    tokenizer: QwenActionExampleTokenizer,
) -> dict[str, Any]:
    """Re-tokenize a sealed row and prove final-action-only loss masking."""

    identity = copy.deepcopy(dict(record))
    expected_hash = identity.pop("record_hash", None)
    if not isinstance(expected_hash, str) or content_hash(identity) != expected_hash:
        raise ValueError("Qwen action record identity changed")
    if (
        record.get("tokenizer_id") != tokenizer.tokenizer_id
        or record.get("tokenizer_hash") != tokenizer.tokenizer_hash
        or record.get("chat_template_hash") != tokenizer.chat_template_hash
    ):
        raise ValueError("Qwen action record tokenizer identity changed")
    tools = record.get("tools")
    input_messages = record.get("input_messages")
    target = record.get("target_message")
    if (
        not isinstance(tools, list)
        or not isinstance(input_messages, list)
        or not isinstance(target, Mapping)
    ):
        raise ValueError("Qwen action record messages are malformed")
    tokens, loss_mask = tokenizer.tokenize_action_example(
        tools=tools,
        input_messages=input_messages,
        target_message=target,
    )
    target_tokens = sum(loss_mask)
    input_tokens = len(tokens) - target_tokens
    if (
        record.get("token_count") != len(tokens)
        or record.get("input_tokens") != input_tokens
        or record.get("target_tokens") != target_tokens
        or record.get("truncation") != "error"
        or record.get("max_length") != 32_768
        or not target_tokens
        or loss_mask != [0] * input_tokens + [1] * target_tokens
    ):
        raise ValueError("Qwen action record loss-mask dry run differs from the sealed row")
    return {
        "record_hash": expected_hash,
        "token_count": len(tokens),
        "input_tokens": input_tokens,
        "target_tokens": target_tokens,
        "overlength": len(tokens) > 32_768,
        "truncation_applied": False,
        "loss_mask_sha256": hashlib.sha256(bytes(loss_mask)).hexdigest(),
    }


def dry_run_decision_record(
    record: Mapping[str, Any],
    *,
    tokenizer: QwenDecisionExampleTokenizer,
) -> dict[str, Any]:
    """Re-tokenize a sealed v3 row and prove complete-decision-only loss masking."""

    identity = copy.deepcopy(dict(record))
    expected_hash = identity.pop("record_hash", None)
    if not isinstance(expected_hash, str) or content_hash(identity) != expected_hash:
        raise ValueError("Qwen decision record identity changed")
    if (
        record.get("tokenizer_id") != tokenizer.tokenizer_id
        or record.get("tokenizer_hash") != tokenizer.tokenizer_hash
        or record.get("chat_template_hash") != tokenizer.chat_template_hash
    ):
        raise ValueError("Qwen decision record tokenizer identity changed")
    tools = record.get("tools")
    input_messages = record.get("input_messages")
    target = record.get("target_message")
    if (
        not isinstance(tools, list)
        or not isinstance(input_messages, list)
        or not isinstance(target, Mapping)
    ):
        raise ValueError("Qwen decision record messages are malformed")
    tokens, loss_mask = tokenizer.tokenize_decision_example(
        tools=tools,
        input_messages=input_messages,
        target_message=target,
    )
    target_tokens = sum(loss_mask)
    input_tokens = len(tokens) - target_tokens
    if (
        record.get("token_count") != len(tokens)
        or record.get("input_tokens") != input_tokens
        or record.get("target_tokens") != target_tokens
        or record.get("truncation") != "error"
        or record.get("max_length") != 32_768
        or not target_tokens
        or loss_mask != [0] * input_tokens + [1] * target_tokens
    ):
        raise ValueError("Qwen decision record loss-mask dry run differs from the sealed row")
    return {
        "record_hash": expected_hash,
        "token_count": len(tokens),
        "input_tokens": input_tokens,
        "target_tokens": target_tokens,
        "overlength": len(tokens) > 32_768,
        "truncation_applied": False,
        "loss_mask_sha256": hashlib.sha256(bytes(loss_mask)).hexdigest(),
    }


def exact_decision_token_receipt(
    *,
    tokenizer: QwenDecisionExampleTokenizer,
    tools: Sequence[Mapping[str, Any]],
    input_messages: Sequence[Mapping[str, Any]],
    target_message: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a path-free receipt for the exact tool-aware decision tokenization."""

    tokens, loss_mask = tokenizer.tokenize_decision_example(
        tools=tools,
        input_messages=input_messages,
        target_message=target_message,
    )
    target_tokens = sum(loss_mask)
    return {
        "tokenizer_id": tokenizer.tokenizer_id,
        "tokenizer_hash": tokenizer.tokenizer_hash,
        "chat_template_hash": tokenizer.chat_template_hash,
        "token_count": len(tokens),
        "input_tokens": len(tokens) - target_tokens,
        "target_tokens": target_tokens,
        "input_ids_sha256": token_ids_sha256(tokens),
        "loss_mask_sha256": loss_mask_sha256(loss_mask),
        "input_ids_hash_format": "sha256_u32be_v1",
        "loss_mask_hash_format": "sha256_bytes_v1",
    }


def dry_run_decision_record_v4(
    record: Mapping[str, Any],
    *,
    tokenizer: QwenDecisionExampleTokenizer,
) -> dict[str, Any]:
    """Re-tokenize one v4 row and reject any tool, token, mask, or template drift."""

    identity = copy.deepcopy(dict(record))
    expected_hash = identity.pop("record_hash", None)
    if not isinstance(expected_hash, str) or content_hash(identity) != expected_hash:
        raise ValueError("Qwen v4 decision record identity changed")
    tools = record.get("tools")
    input_messages = record.get("input_messages")
    target = record.get("target_message")
    if (
        not isinstance(tools, list)
        or not isinstance(input_messages, list)
        or not isinstance(target, Mapping)
    ):
        raise ValueError("Qwen v4 decision record messages are malformed")
    receipt = exact_decision_token_receipt(
        tokenizer=tokenizer,
        tools=tools,
        input_messages=input_messages,
        target_message=target,
    )
    for key, value in receipt.items():
        if record.get(key) != value:
            raise ValueError(f"Qwen v4 decision {key} differs from the exact receipt")
    if (
        record.get("tool_schema_hash") != content_hash(tools)
        or record.get("truncation") != "error"
        or record.get("max_length") != 65_536
        or record.get("eligible") is not True
        or receipt["token_count"] > 65_536
    ):
        raise ValueError("Qwen v4 decision loader contract changed")
    return {
        "record_hash": expected_hash,
        **receipt,
        "overlength": False,
        "truncation_applied": False,
    }


def token_ids_sha256(tokens: Sequence[int]) -> str:
    """Hash token IDs with an unambiguous fixed-width, big-endian representation."""

    digest = hashlib.sha256()
    for token in tokens:
        if not isinstance(token, int) or token < 0 or token > 0xFFFFFFFF:
            raise ValueError("token ids must be unsigned 32-bit integers")
        digest.update(struct.pack(">I", token))
    return digest.hexdigest()


def loss_mask_sha256(loss_mask: Sequence[int]) -> str:
    """Hash an exact binary loss mask without JSON or platform-dependent encoding."""

    if any(item not in {0, 1} for item in loss_mask):
        raise ValueError("loss mask must contain only zero and one")
    return hashlib.sha256(bytes(loss_mask)).hexdigest()


def tokenizer_tree_hash(root: Path) -> str:
    """Hash the local tokenizer assets without including their host path."""

    directory = _safe_tokenizer_root(root)
    inventory: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if path.name not in _TOKENIZER_FILES or not path.is_file():
            continue
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_size <= 0:
            raise ValueError("Qwen tokenizer identity contains an unsafe file")
        inventory.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "size_bytes": metadata.st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if not inventory or not any(
        Path(str(item["path"])).name == "tokenizer_config.json" for item in inventory
    ):
        raise ValueError("Qwen tokenizer root lacks tokenizer_config.json")
    return content_hash(inventory)


def _adapt_openai_tool_arguments(
    messages: list[dict[str, Any]],
    *,
    require_single_call: bool = True,
) -> list[dict[str, Any]]:
    for message in messages:
        tool_calls = message.get("tool_calls")
        if tool_calls is None:
            continue
        if not isinstance(tool_calls, list) or not tool_calls:
            raise ValueError("Qwen HWE assistant tool calls must be a non-empty list")
        if require_single_call and len(tool_calls) != 1:
            raise ValueError("Qwen HWE messages require exactly one tool call per assistant step")
        for call in tool_calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("arguments"), str):
                raise ValueError("Qwen HWE tool call is malformed")
            try:
                arguments = json.loads(function["arguments"])
            except json.JSONDecodeError as exc:
                raise ValueError("Qwen HWE tool arguments are invalid JSON") from exc
            if not isinstance(arguments, dict):
                raise ValueError("Qwen HWE tool arguments must decode to an object")
            function["arguments"] = arguments
    return messages


def _safe_tokenizer_root(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("Qwen tokenizer root cannot be a symlink")
    root = path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Qwen tokenizer root must be a directory")
    return root


__all__ = [
    "QwenActionExampleTokenizer",
    "QwenDecisionExampleTokenizer",
    "QwenChatTemplate",
    "dry_run_action_record",
    "dry_run_decision_record",
    "dry_run_decision_record_v4",
    "exact_decision_token_receipt",
    "loss_mask_sha256",
    "token_ids_sha256",
    "tokenizer_tree_hash",
]
