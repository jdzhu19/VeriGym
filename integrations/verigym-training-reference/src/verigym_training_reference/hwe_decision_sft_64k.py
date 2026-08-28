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
OPENHANDS_RECORD_FORMAT = "verigym_openhands_decision_sft_64k_v1"
OPENHANDS_RECOVERY_RECORD_FORMAT = "verigym_openhands_decision_sft_64k_v2"
OPENHANDS_MASKED_RECOVERY_RECORD_FORMAT = "verigym_openhands_decision_sft_64k_v3"
OPENHANDS_CONTINUATION_RECORD_FORMAT = "verigym_openhands_decision_sft_64k_v4"
OPENHANDS_MASKED_CONTINUATION_RECORD_FORMAT = "verigym_openhands_decision_sft_64k_v5"
OPENHANDS_PATH_RECOVERY_RECORD_FORMAT = "verigym_openhands_decision_sft_64k_v6"
OPENHANDS_DATASET_FORMAT = "verigym_openhands_decision_sft_dataset_64k_v1"
OPENHANDS_RECOVERY_DATASET_FORMAT = "verigym_openhands_decision_sft_dataset_64k_v2"
OPENHANDS_MASKED_RECOVERY_DATASET_FORMAT = "verigym_openhands_decision_sft_dataset_64k_v3"
OPENHANDS_CONTINUATION_DATASET_FORMAT = "verigym_openhands_decision_sft_dataset_64k_v4"
OPENHANDS_MASKED_CONTINUATION_DATASET_FORMAT = "verigym_openhands_decision_sft_dataset_64k_v5"
OPENHANDS_PATH_RECOVERY_DATASET_FORMAT = "verigym_openhands_decision_sft_dataset_64k_v6"
OPENHANDS_RECOVERY_POLICY = "openhands_broker_stop_hook_recovery_v1"
OPENHANDS_CONTINUATION_POLICY = "openhands_sdk_blocked_stop_continuation_v1"
OPENHANDS_PATH_RECOVERY_POLICY = "openhands_provider_path_policy_recovery_v1"
OPENHANDS_RECOVERY_MESSAGE = (
    "[Stop hook feedback] Your previous response did not call a tool. Continue in this same "
    "session with exactly one typed tool call and no prose. If the task is complete, call finish."
)
OPENHANDS_CONTINUATION_MESSAGE = (
    "[Adapter continuation] Continue from the Stop hook feedback already present above with "
    "exactly one typed tool call and no prose."
)
OPENHANDS_PATH_RECOVERY_MESSAGE = (
    "[Adapter path-policy feedback] The previous provider response was rejected before tool "
    "dispatch because one argument contained a host absolute path. Continue in this same "
    "session with exactly one typed tool call and no prose. Use only '.' or workspace-relative "
    "POSIX repository paths in every path, cwd, shell command, patch header, and summary. Do not "
    "mention, reconstruct, or reuse the rejected path."
)
DECISION_BALANCED_OBJECTIVE = "decision_balanced_target_token_mean_batch1_v1"
TRAJECTORY_BALANCED_OBJECTIVE = "trajectory_balanced_all_assistant_token_mean_batch1_v1"
TRAJECTORY_BALANCED_DECISION_OBJECTIVE = "trajectory_balanced_decision_target_token_mean_batch1_v1"
V4_TOOL_NAMES = (
    "apply_patch",
    "finish",
    "inspect_diff",
    "list_files",
    "read_file",
    "shell",
)
_MAX_DATASET_BYTES = 16 * 1024 * 1024
_MAX_OPENHANDS_DATASET_BYTES = 512 * 1024 * 1024

_OPENHANDS_RECORD_FORMATS = {
    OPENHANDS_RECORD_FORMAT,
    OPENHANDS_RECOVERY_RECORD_FORMAT,
    OPENHANDS_MASKED_RECOVERY_RECORD_FORMAT,
    OPENHANDS_CONTINUATION_RECORD_FORMAT,
    OPENHANDS_MASKED_CONTINUATION_RECORD_FORMAT,
    OPENHANDS_PATH_RECOVERY_RECORD_FORMAT,
}
_OPENHANDS_DATASET_FORMATS = {
    OPENHANDS_DATASET_FORMAT,
    OPENHANDS_RECOVERY_DATASET_FORMAT,
    OPENHANDS_MASKED_RECOVERY_DATASET_FORMAT,
    OPENHANDS_CONTINUATION_DATASET_FORMAT,
    OPENHANDS_MASKED_CONTINUATION_DATASET_FORMAT,
    OPENHANDS_PATH_RECOVERY_DATASET_FORMAT,
}
_OPENHANDS_RECOVERY_RECORD_FORMATS = _OPENHANDS_RECORD_FORMATS - {OPENHANDS_RECORD_FORMAT}


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


@dataclass(frozen=True)
class OpenHandsToolAwareParquetInputs:
    """Validated OpenHands rows in the exact shape handed from rLLM to veRL."""

    root: Path
    manifest: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    train_jsonl_sha256: str


def trajectory_balanced_decision_indices(
    *,
    transcript_hashes: list[str],
    decision_indices: list[int],
    trajectory_decision_counts: list[int],
) -> tuple[int, ...]:
    """Build a deterministic equal-trajectory epoch over decision source rows."""

    if not transcript_hashes or not (
        len(transcript_hashes) == len(decision_indices) == len(trajectory_decision_counts)
    ):
        raise ValueError("trajectory-balanced decision metadata is empty or misaligned")
    groups: dict[str, dict[int, int]] = {}
    declared_counts: dict[str, int] = {}
    for source_index, (transcript_hash, decision_index, declared_count) in enumerate(
        zip(transcript_hashes, decision_indices, trajectory_decision_counts, strict=True)
    ):
        if (
            len(transcript_hash) != 64
            or any(character not in "0123456789abcdef" for character in transcript_hash)
            or not isinstance(decision_index, int)
            or not isinstance(declared_count, int)
            or declared_count <= 0
        ):
            raise ValueError("trajectory-balanced decision metadata is malformed")
        if (
            transcript_hash in declared_counts
            and declared_counts[transcript_hash] != declared_count
        ):
            raise ValueError("trajectory-balanced decision count changed within one trajectory")
        declared_counts[transcript_hash] = declared_count
        group = groups.setdefault(transcript_hash, {})
        if decision_index in group:
            raise ValueError("trajectory-balanced decision index is duplicated")
        group[decision_index] = source_index
    ordered_groups: dict[str, list[int]] = {}
    for transcript_hash, group in groups.items():
        declared_count = declared_counts[transcript_hash]
        decisions = sorted(group)
        if decisions[0] < 0 or decisions[-1] >= declared_count or len(decisions) > declared_count:
            raise ValueError("trajectory-balanced decision sequence exceeds its source trajectory")
        # DeepSeek v4 deliberately omits format-error decisions. Gaps in the
        # original decision indices are therefore valid; the sealed eligible
        # rows, not the raw assistant-turn count, define the sampling support.
        ordered_groups[transcript_hash] = decisions
    maximum = max(len(group) for group in ordered_groups.values())
    schedule: list[int] = []
    for slot in range(maximum):
        for transcript_hash in sorted(groups):
            decisions = ordered_groups[transcript_hash]
            count = len(decisions)
            decision_rank = min(slot * count // maximum, count - 1)
            schedule.append(groups[transcript_hash][decisions[decision_rank]])
    return tuple(schedule)


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


def load_openhands_tool_aware_dataset(root: Path) -> OpenHandsToolAwareParquetInputs:
    """Load one sealed OpenHands decision dataset without dropping SDK tool schemas."""

    directory = _safe_directory(root)
    manifest_payload = _read_regular(
        directory / "dataset-manifest.json", max_bytes=_MAX_OPENHANDS_DATASET_BYTES
    )
    train_payload = _read_regular(directory / "train.jsonl", max_bytes=_MAX_OPENHANDS_DATASET_BYTES)
    try:
        manifest = json.loads(manifest_payload)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenHands 64K manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("format_id") not in (
        _OPENHANDS_DATASET_FORMATS
    ):
        raise ValueError("OpenHands 64K dataset format changed")
    expected_dataset_hash = manifest.get("dataset_hash")
    manifest_base = {key: value for key, value in manifest.items() if key != "dataset_hash"}
    if expected_dataset_hash != content_hash(manifest_base):
        raise ValueError("OpenHands 64K dataset manifest identity changed")
    if manifest.get("records_sha256") != hashlib.sha256(train_payload).hexdigest():
        raise ValueError("OpenHands 64K train.jsonl identity changed")
    manifest_contract = {
        "max_length": V4_MAX_LENGTH,
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
    if any(manifest.get(key) != expected for key, expected in manifest_contract.items()):
        raise ValueError("OpenHands 64K dataset eligibility or safety contract changed")
    if manifest["format_id"] != OPENHANDS_DATASET_FORMAT:
        recovery_contract = {
            "format_recovery_policy_id": OPENHANDS_RECOVERY_POLICY,
            "same_session_recovery_hash_bound": True,
            "whole_episode_retries": 0,
            "termination_authority": "broker_typed_finish",
        }
        if any(manifest.get(key) != expected for key, expected in recovery_contract.items()):
            raise ValueError("OpenHands 64K recovery dataset contract changed")
        record_formats = manifest.get("record_formats")
        if (
            not isinstance(record_formats, list)
            or not record_formats
            or record_formats != sorted(set(record_formats))
            or not set(record_formats) <= _OPENHANDS_RECORD_FORMATS
            or manifest["format_id"].replace("dataset_", "") not in record_formats
        ):
            raise ValueError("OpenHands 64K recovery record formats changed")
        recovery_count = manifest.get("format_recovery_count")
        recovery_trajectory_count = manifest.get("format_recovery_trajectory_count")
        trajectory_count = manifest.get("trajectory_count")
        if (
            not isinstance(recovery_count, int)
            or isinstance(recovery_count, bool)
            or recovery_count < 0
            or not isinstance(recovery_trajectory_count, int)
            or isinstance(recovery_trajectory_count, bool)
            or recovery_trajectory_count < 0
            or not isinstance(trajectory_count, int)
            or recovery_trajectory_count > trajectory_count
            or recovery_count != recovery_trajectory_count
        ):
            raise ValueError("OpenHands 64K recovery accounting changed")
        _validate_openhands_dataset_extension(manifest)

    raw_lines = train_payload.decode("utf-8").splitlines()
    record_count = manifest.get("record_count")
    if not isinstance(record_count, int) or record_count <= 0:
        raise ValueError("OpenHands 64K dataset record count is invalid")
    if len(raw_lines) != record_count or any(not line for line in raw_lines):
        raise ValueError("OpenHands 64K train.jsonl row count changed")
    try:
        records = [json.loads(line) for line in raw_lines]
    except json.JSONDecodeError as exc:
        raise ValueError("OpenHands 64K train.jsonl contains invalid JSON") from exc
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("OpenHands 64K train.jsonl row is not an object")
    observed_record_formats = sorted({str(record.get("format_id")) for record in records})
    expected_record_formats = (
        manifest.get("record_formats")
        if manifest["format_id"] != OPENHANDS_DATASET_FORMAT
        else [OPENHANDS_RECORD_FORMAT]
    )
    if observed_record_formats != expected_record_formats:
        raise ValueError("OpenHands 64K source record formats changed")
    hashes = [record.get("record_hash") for record in records]
    if hashes != manifest.get("record_hashes"):
        raise ValueError("OpenHands 64K parquet row order or record identity changed")
    rows = tuple(
        _openhands_parquet_row(
            record,
            index=index,
            dataset_hash=str(expected_dataset_hash),
        )
        for index, record in enumerate(records)
    )
    transcript_hashes = {str(row["transcript_hash"]) for row in rows}
    if (
        manifest.get("trajectory_count") != len(transcript_hashes)
        or sorted(transcript_hashes) != manifest.get("trajectory_hashes")
        or manifest.get("supervised_decision_count") != len(rows)
        or manifest.get("max_observed_token_count")
        != max(row["exact_token_receipt"]["token_count"] for row in rows)
    ):
        raise ValueError("OpenHands 64K dataset trajectory or token accounting changed")
    return OpenHandsToolAwareParquetInputs(
        root=directory,
        manifest=copy.deepcopy(manifest),
        rows=rows,
        train_jsonl_sha256=hashlib.sha256(train_payload).hexdigest(),
    )


def _validate_openhands_dataset_extension(manifest: dict[str, Any]) -> None:
    """Validate v2-v6 recovery, masking, continuation, and path receipts."""

    format_id = str(manifest["format_id"])
    schema_versions = {
        OPENHANDS_RECOVERY_DATASET_FORMAT: "2.0",
        OPENHANDS_MASKED_RECOVERY_DATASET_FORMAT: "3.0",
        OPENHANDS_CONTINUATION_DATASET_FORMAT: "4.0",
        OPENHANDS_MASKED_CONTINUATION_DATASET_FORMAT: "5.0",
        OPENHANDS_PATH_RECOVERY_DATASET_FORMAT: "6.0",
    }
    if manifest.get("schema_version") != schema_versions[format_id]:
        raise ValueError("OpenHands 64K recovery dataset schema changed")
    if format_id in {
        OPENHANDS_MASKED_RECOVERY_DATASET_FORMAT,
        OPENHANDS_MASKED_CONTINUATION_DATASET_FORMAT,
    }:
        masked_count = manifest.get("masked_policy_error_decision_count")
        masked_trajectories = manifest.get("masked_policy_error_trajectory_count")
        if (
            manifest.get("failed_decisions_retained_as_context") is not True
            or manifest.get("failed_decisions_supervised") is not False
            or not isinstance(masked_count, int)
            or isinstance(masked_count, bool)
            or masked_count <= 0
            or not isinstance(masked_trajectories, int)
            or isinstance(masked_trajectories, bool)
            or masked_trajectories <= 0
        ):
            raise ValueError("OpenHands 64K masked-recovery accounting changed")
    continuation_present = "sdk_stop_continuation_policy_id" in manifest
    if (
        format_id
        in {
            OPENHANDS_CONTINUATION_DATASET_FORMAT,
            OPENHANDS_MASKED_CONTINUATION_DATASET_FORMAT,
        }
        and not continuation_present
    ):
        raise ValueError("OpenHands 64K continuation receipt is missing")
    if continuation_present:
        continuation_count = manifest.get("sdk_stop_continuation_count")
        continuation_trajectories = manifest.get("sdk_stop_continuation_trajectory_count")
        if (
            manifest.get("sdk_stop_continuation_policy_id") != OPENHANDS_CONTINUATION_POLICY
            or manifest.get("sdk_upstream_source_modified") is not False
            or not isinstance(continuation_count, int)
            or isinstance(continuation_count, bool)
            or continuation_count <= 0
            or continuation_count != continuation_trajectories
        ):
            raise ValueError("OpenHands 64K continuation accounting changed")
    if format_id == OPENHANDS_PATH_RECOVERY_DATASET_FORMAT:
        path_count = manifest.get("path_policy_recovery_count")
        path_trajectories = manifest.get("path_policy_recovery_trajectory_count")
        if (
            manifest.get("path_policy_recovery_policy_id") != OPENHANDS_PATH_RECOVERY_POLICY
            or manifest.get("raw_rejected_provider_arguments_persisted") is not False
            or manifest.get("path_policy_recovery_hash_bound") is not True
            or not isinstance(path_count, int)
            or isinstance(path_count, bool)
            or path_count <= 0
            or path_count != path_trajectories
        ):
            raise ValueError("OpenHands 64K path-recovery accounting changed")


def write_tool_aware_parquet(
    inputs: ToolAwareParquetInputs | OpenHandsToolAwareParquetInputs,
    output: Path,
) -> str:
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


def tool_aware_exact_all_assistant_tokens(
    tokenizer: ToolAwareTokenizer,
    *,
    messages: Any,
    tools: Any,
    tokenizer_id: str,
    tokenizer_hash: str,
    expected_receipt: Any | None = None,
) -> ExactToolAwareTokens:
    """Render one full trajectory and supervise every complete assistant decision."""

    normalized_messages = _plain_value(messages)
    normalized_tools = _plain_value(tools)
    if not isinstance(normalized_messages, list) or len(normalized_messages) < 3:
        raise ValueError("tool-aware trajectory requires a complete message list")
    if not isinstance(normalized_tools, list):
        raise ValueError("tool-aware trajectory is missing tools")
    _validate_tools(normalized_tools)
    if [item.get("role") for item in normalized_messages[:2]] != ["system", "user"]:
        raise ValueError("tool-aware trajectory must start with system then user")
    assistant_indices = [
        index
        for index, message in enumerate(normalized_messages)
        if isinstance(message, dict)
        and message.get("role") == "assistant"
        and message.get("tool_calls")
    ]
    if not assistant_indices:
        raise ValueError("tool-aware trajectory contains no complete assistant tool decision")

    adapted = _adapt_openai_tool_arguments(copy.deepcopy(normalized_messages))
    full = _render(tokenizer, adapted, normalized_tools)
    full_ids = _encode(tokenizer, full)
    if not full_ids:
        raise ValueError("tool-aware trajectory token sequence is empty")
    loss_mask = [0] * len(full_ids)
    for index in assistant_indices:
        start = _rendered_message_start(
            tokenizer,
            full=full,
            messages=adapted,
            tools=normalized_tools,
            message_index=index,
            mutation="assistant_tool_name",
        )
        if index + 1 < len(adapted):
            end = _rendered_message_start(
                tokenizer,
                full=full,
                messages=adapted,
                tools=normalized_tools,
                message_index=index + 1,
                mutation="message_content",
            )
        else:
            end = len(full_ids)
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError("tool-aware trajectory assistant boundary is invalid")
        loss_mask[start:end] = [1] * (end - start)
    target_count = sum(loss_mask)
    actual = {
        "tokenizer_id": tokenizer_id,
        "tokenizer_hash": tokenizer_hash,
        "chat_template_hash": hashlib.sha256(tokenizer.chat_template.encode("utf-8")).hexdigest(),
        "token_count": len(full_ids),
        "input_tokens": len(full_ids) - target_count,
        "target_tokens": target_count,
        "input_ids_sha256": token_ids_sha256(full_ids),
        "loss_mask_sha256": loss_mask_sha256(loss_mask),
        "input_ids_hash_format": "sha256_u32be_v1",
        "loss_mask_hash_format": "sha256_bytes_v1",
    }
    normalized_receipt = _plain_value(expected_receipt)
    if expected_receipt is not None:
        if not isinstance(normalized_receipt, dict):
            raise ValueError("tool-aware trajectory receipt is malformed")
        if actual != normalized_receipt:
            changed = sorted(key for key in actual if actual[key] != normalized_receipt.get(key))
            raise ValueError(f"tool-aware trajectory exact receipt drifted: {', '.join(changed)}")
    if len(full_ids) > V4_MAX_LENGTH:
        raise ValueError("tool-aware trajectory exceeds the frozen 64K bound; truncation forbidden")
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
        "transcript_hash": value["transcript_hash"],
        "decision_index": value["decision_index"],
        "trajectory_assistant_decision_count": value["trajectory_assistant_decision_count"],
        "messages": [*value["input_messages"], value["target_message"]],
        "tools": value["tools"],
        "tool_schema_hash": value["tool_schema_hash"],
        "exact_token_receipt": {key: value[key] for key in receipt_keys},
        "sft_objective": DECISION_BALANCED_OBJECTIVE,
        "max_length": value["max_length"],
        "truncation": value["truncation"],
    }
    _validate_parquet_row(row, index=value["source_v3_record_index"])
    return row


def _validate_parquet_row(row: Any, *, index: int) -> None:
    if not isinstance(row, dict):
        raise ValueError(f"tool-aware parquet row {index} is not an object")
    if row.get("format_id") in _OPENHANDS_RECORD_FORMATS:
        _validate_openhands_parquet_row(row, index=index)
        return
    required = {
        "format_id",
        "source_v3_dataset_hash",
        "source_v3_record_index",
        "source_v3_record_hash",
        "record_hash",
        "transcript_hash",
        "decision_index",
        "trajectory_assistant_decision_count",
        "messages",
        "tools",
        "tool_schema_hash",
        "exact_token_receipt",
        "sft_objective",
        "max_length",
        "truncation",
    }
    if set(row) != required or row.get("format_id") != V4_RECORD_FORMAT:
        raise ValueError(f"tool-aware parquet row {index} fields changed")
    if row.get("source_v3_record_index") != index:
        raise ValueError(f"tool-aware parquet row {index} order changed")
    if (
        not isinstance(row.get("decision_index"), int)
        or not isinstance(row.get("trajectory_assistant_decision_count"), int)
        or row["decision_index"] >= row["trajectory_assistant_decision_count"]
    ):
        raise ValueError(f"tool-aware parquet row {index} trajectory binding changed")
    if row.get("sft_objective") != DECISION_BALANCED_OBJECTIVE:
        raise ValueError(f"tool-aware parquet row {index} objective changed")
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


def _openhands_parquet_row(
    record: dict[str, Any],
    *,
    index: int,
    dataset_hash: str,
) -> dict[str, Any]:
    expected_record_hash = record.get("record_hash")
    record_base = {key: value for key, value in record.items() if key != "record_hash"}
    if expected_record_hash != content_hash(record_base):
        raise ValueError(f"OpenHands 64K source row {index} identity changed")
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
    if any(key not in record for key in receipt_keys):
        raise ValueError(f"OpenHands 64K source row {index} omits its token receipt")
    input_messages = record.get("input_messages")
    target_message = record.get("target_message")
    if not isinstance(input_messages, list) or not isinstance(target_message, dict):
        raise ValueError(f"OpenHands 64K source row {index} messages are malformed")
    row = {
        "format_id": record.get("format_id"),
        "source_dataset_hash": dataset_hash,
        "source_record_index": index,
        "record_hash": expected_record_hash,
        "transcript_hash": record.get("transcript_hash"),
        "decision_index": record.get("decision_index"),
        "trajectory_assistant_decision_count": record.get("trajectory_assistant_decision_count"),
        "task_id": record.get("task_id"),
        "messages": [*copy.deepcopy(input_messages), copy.deepcopy(target_message)],
        "tools": copy.deepcopy(record.get("tools")),
        "tool_schema_hash": record.get("tool_schema_hash"),
        "exact_token_receipt": {key: record[key] for key in receipt_keys},
        "sft_objective": DECISION_BALANCED_OBJECTIVE,
        "max_length": record.get("max_length"),
        "truncation": record.get("truncation"),
        "source_record": copy.deepcopy(record),
    }
    _validate_openhands_parquet_row(row, index=index)
    return row


def _validate_openhands_parquet_row(row: dict[str, Any], *, index: int) -> None:
    required = {
        "format_id",
        "source_dataset_hash",
        "source_record_index",
        "record_hash",
        "transcript_hash",
        "decision_index",
        "trajectory_assistant_decision_count",
        "task_id",
        "messages",
        "tools",
        "tool_schema_hash",
        "exact_token_receipt",
        "sft_objective",
        "max_length",
        "truncation",
        "source_record",
    }
    if set(row) != required or row.get("source_record_index") != index:
        raise ValueError(f"OpenHands tool-aware parquet row {index} fields changed")
    source = _plain_value(row.get("source_record"))
    if not isinstance(source, dict):
        raise ValueError(f"OpenHands tool-aware parquet row {index} lost its source record")
    source_base = {key: value for key, value in source.items() if key != "record_hash"}
    if row.get("record_hash") != source.get("record_hash") or source.get(
        "record_hash"
    ) != content_hash(source_base):
        raise ValueError(f"OpenHands tool-aware parquet row {index} identity changed")
    tools = _plain_value(row.get("tools"))
    _validate_tools(tools)
    messages = _plain_value(row.get("messages"))
    receipt = _plain_value(row.get("exact_token_receipt"))
    expected_messages = [*source.get("input_messages", []), source.get("target_message")]
    if messages != expected_messages or tools != source.get("tools"):
        raise ValueError(f"OpenHands tool-aware parquet row {index} source binding changed")
    if row.get("tool_schema_hash") != content_hash(tools):
        raise ValueError(f"OpenHands tool-aware parquet row {index} tool schema changed")
    if (
        row.get("transcript_hash") != source.get("transcript_hash")
        or row.get("decision_index") != source.get("decision_index")
        or row.get("task_id") != source.get("task_id")
        or row.get("trajectory_assistant_decision_count")
        != source.get("trajectory_assistant_decision_count")
    ):
        raise ValueError(f"OpenHands tool-aware parquet row {index} trajectory binding changed")
    decision_index = row.get("decision_index")
    trajectory_count = row.get("trajectory_assistant_decision_count")
    if (
        not isinstance(decision_index, int)
        or not isinstance(trajectory_count, int)
        or trajectory_count <= 0
        or not 0 <= decision_index < trajectory_count
    ):
        raise ValueError(f"OpenHands tool-aware parquet row {index} decision index changed")
    if not isinstance(receipt, dict) or any(receipt.get(key) != source.get(key) for key in receipt):
        raise ValueError(f"OpenHands tool-aware parquet row {index} receipt binding changed")
    if (
        row.get("sft_objective") != DECISION_BALANCED_OBJECTIVE
        or row.get("max_length") != V4_MAX_LENGTH
        or row.get("truncation") != "error"
        or source.get("eligible") is not True
        or source.get("verifier_resolved") is not True
        or source.get("infrastructure_valid") is not True
    ):
        raise ValueError(f"OpenHands tool-aware parquet row {index} eligibility changed")
    source_contract = {
        "format_id": row.get("format_id"),
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
    if any(source.get(key) != expected for key, expected in source_contract.items()):
        raise ValueError(f"OpenHands tool-aware parquet row {index} safety contract changed")
    if row.get("format_id") in _OPENHANDS_RECOVERY_RECORD_FORMATS:
        recoveries = source.get("format_recoveries")
        recovery_count = source.get("format_recovery_count")
        trajectory_recovery_count = source.get("trajectory_format_recovery_count")
        schema_version = str(row["format_id"]).rsplit("_v", 1)[-1] + ".0"
        source_trajectory_format = str(row["format_id"]).replace(
            "decision_sft_64k", "exact_tool_trajectory"
        )
        recovery_contract = {
            "schema_version": schema_version,
            "source_trajectory_format": source_trajectory_format,
            "format_recovery_policy_id": OPENHANDS_RECOVERY_POLICY,
            "same_session_recovery": True,
            "whole_episode_retries": 0,
            "termination_authority": "broker_typed_finish",
        }
        if (
            any(source.get(key) != expected for key, expected in recovery_contract.items())
            or not isinstance(recoveries, list)
            or recovery_count != len(recoveries)
            or not isinstance(trajectory_recovery_count, int)
            or isinstance(trajectory_recovery_count, bool)
            or trajectory_recovery_count not in {0, 1}
            or len(recoveries) > trajectory_recovery_count
        ):
            raise ValueError(f"OpenHands tool-aware parquet row {index} recovery changed")
        _validate_openhands_recovery_source(source, index=index)
        _validate_openhands_record_extension(source, index=index)
    token_count = receipt.get("token_count", V4_MAX_LENGTH + 1)
    if not isinstance(token_count, int) or token_count > V4_MAX_LENGTH:
        raise ValueError(f"OpenHands tool-aware parquet row {index} is overlength")


def _validate_openhands_recovery_source(source: dict[str, Any], *, index: int) -> None:
    messages = source.get("input_messages")
    receipts = source.get("format_recoveries")
    if not isinstance(messages, list) or not isinstance(receipts, list):
        raise ValueError(f"OpenHands tool-aware parquet row {index} recovery is malformed")
    expected_fields = {
        "recovery_index",
        "reason",
        "assistant_message_index",
        "assistant_message_sha256",
        "hook_event_index",
        "feedback_message_index",
        "feedback_message_sha256",
        "feedback_text_sha256",
        "same_session",
        "whole_episode_retries",
        "broker_typed_finish_before",
    }
    continuation_fields = {
        "sdk_blocked_stop_hook_index",
        "adapter_continuation_message_index",
        "adapter_continuation_message_sha256",
        "adapter_continuation_text_sha256",
    }
    feedback_text_hash = hashlib.sha256(OPENHANDS_RECOVERY_MESSAGE.encode()).hexdigest()
    continuation_text_hash = hashlib.sha256(OPENHANDS_CONTINUATION_MESSAGE.encode()).hexdigest()
    for recovery_index, receipt in enumerate(receipts):
        if not isinstance(receipt, dict) or set(receipt) not in {
            frozenset(expected_fields),
            frozenset(expected_fields | continuation_fields),
        }:
            raise ValueError(f"OpenHands tool-aware parquet row {index} recovery fields changed")
        assistant_index = receipt.get("assistant_message_index")
        feedback_index = receipt.get("feedback_message_index")
        hook_index = receipt.get("hook_event_index")
        if (
            receipt.get("recovery_index") != recovery_index
            or receipt.get("reason") != "assistant_content_without_typed_tool"
            or not isinstance(assistant_index, int)
            or isinstance(assistant_index, bool)
            or not isinstance(feedback_index, int)
            or isinstance(feedback_index, bool)
            or not isinstance(hook_index, int)
            or isinstance(hook_index, bool)
            or not 2 <= assistant_index < feedback_index < len(messages)
            or hook_index < 0
            or receipt.get("same_session") is not True
            or receipt.get("whole_episode_retries") != 0
            or receipt.get("broker_typed_finish_before") is not False
            or receipt.get("feedback_text_sha256") != feedback_text_hash
        ):
            raise ValueError(f"OpenHands tool-aware parquet row {index} recovery receipt changed")
        assistant = messages[assistant_index]
        feedback = messages[feedback_index]
        if (
            not isinstance(assistant, dict)
            or assistant.get("role") != "assistant"
            or not assistant.get("content")
            or assistant.get("tool_calls")
            or not isinstance(feedback, dict)
            or feedback != {"role": "user", "content": OPENHANDS_RECOVERY_MESSAGE}
            or receipt.get("assistant_message_sha256") != content_hash(assistant)
            or receipt.get("feedback_message_sha256") != content_hash(feedback)
        ):
            raise ValueError(f"OpenHands tool-aware parquet row {index} recovery binding changed")
        if continuation_fields <= set(receipt):
            continuation_index = receipt.get("adapter_continuation_message_index")
            blocked_hook_index = receipt.get("sdk_blocked_stop_hook_index")
            if (
                not isinstance(continuation_index, int)
                or isinstance(continuation_index, bool)
                or not feedback_index < continuation_index < len(messages)
                or not isinstance(blocked_hook_index, int)
                or isinstance(blocked_hook_index, bool)
                or blocked_hook_index <= hook_index
                or receipt.get("adapter_continuation_text_sha256") != continuation_text_hash
            ):
                raise ValueError(
                    f"OpenHands tool-aware parquet row {index} continuation receipt changed"
                )
            continuation = messages[continuation_index]
            if (
                not isinstance(continuation, dict)
                or continuation != {"role": "user", "content": OPENHANDS_CONTINUATION_MESSAGE}
                or receipt.get("adapter_continuation_message_sha256") != content_hash(continuation)
            ):
                raise ValueError(
                    f"OpenHands tool-aware parquet row {index} continuation binding changed"
                )


def _validate_openhands_record_extension(source: dict[str, Any], *, index: int) -> None:
    """Validate v3-v6 row-level controls retained inside the lossless source record."""

    format_id = source.get("format_id")
    if format_id in {
        OPENHANDS_MASKED_RECOVERY_RECORD_FORMAT,
        OPENHANDS_MASKED_CONTINUATION_RECORD_FORMAT,
    }:
        masked_count = source.get("trajectory_masked_policy_error_decision_count")
        if (
            not isinstance(masked_count, int)
            or isinstance(masked_count, bool)
            or masked_count <= 0
            or source.get("failed_decisions_retained_as_context") is not True
            or source.get("failed_decisions_supervised") is not False
        ):
            raise ValueError(f"OpenHands tool-aware parquet row {index} masking changed")
    continuation_present = "trajectory_sdk_stop_continuation_count" in source
    if (
        format_id
        in {
            OPENHANDS_CONTINUATION_RECORD_FORMAT,
            OPENHANDS_MASKED_CONTINUATION_RECORD_FORMAT,
        }
        and not continuation_present
    ):
        raise ValueError(f"OpenHands tool-aware parquet row {index} continuation is missing")
    if continuation_present:
        visible_count = source.get("sdk_stop_continuation_count")
        if (
            source.get("sdk_stop_continuation_policy_id") != OPENHANDS_CONTINUATION_POLICY
            or source.get("trajectory_sdk_stop_continuation_count") != 1
            or visible_count not in {0, 1}
            or source.get("sdk_upstream_source_modified") is not False
        ):
            raise ValueError(f"OpenHands tool-aware parquet row {index} continuation changed")
    if format_id == OPENHANDS_PATH_RECOVERY_RECORD_FORMAT:
        recoveries = source.get("path_policy_recoveries")
        visible_count = source.get("path_policy_recovery_count")
        if (
            source.get("path_policy_recovery_policy_id") != OPENHANDS_PATH_RECOVERY_POLICY
            or source.get("trajectory_path_policy_recovery_count") != 1
            or not isinstance(recoveries, list)
            or visible_count != len(recoveries)
            or visible_count not in {0, 1}
            or source.get("raw_rejected_provider_arguments_persisted") is not False
            or source.get("path_policy_recovery_tool_choice_policy")
            != "responses_required_validated_v1"
        ):
            raise ValueError(f"OpenHands tool-aware parquet row {index} path recovery changed")
        _validate_openhands_path_recovery_source(source, index=index)


def _validate_openhands_path_recovery_source(source: dict[str, Any], *, index: int) -> None:
    messages = source.get("input_messages")
    receipts = source.get("path_policy_recoveries")
    if not isinstance(messages, list) or not isinstance(receipts, list):
        raise ValueError(f"OpenHands tool-aware parquet row {index} path recovery is malformed")
    expected_fields = {
        "policy_id",
        "recovery_budget",
        "recovery_index",
        "trigger_stage",
        "root_message_sha256",
        "tool_name",
        "argument_field",
        "violation_kind",
        "raw_provider_arguments_persisted",
        "same_session",
        "whole_episode_retries",
        "conversation_error_event_index",
        "feedback_message_index",
        "feedback_message_sha256",
        "feedback_text_sha256",
    }
    feedback_text_hash = hashlib.sha256(OPENHANDS_PATH_RECOVERY_MESSAGE.encode()).hexdigest()
    for recovery_index, receipt in enumerate(receipts):
        if not isinstance(receipt, dict) or set(receipt) != expected_fields:
            raise ValueError(
                f"OpenHands tool-aware parquet row {index} path recovery fields changed"
            )
        feedback_index = receipt.get("feedback_message_index")
        event_index = receipt.get("conversation_error_event_index")
        root_hash = receipt.get("root_message_sha256")
        if (
            receipt.get("policy_id") != OPENHANDS_PATH_RECOVERY_POLICY
            or receipt.get("recovery_budget") != 1
            or receipt.get("recovery_index") != recovery_index
            or receipt.get("trigger_stage") not in {"agent_loop", "sdk_stop_continuation"}
            or not isinstance(root_hash, str)
            or len(root_hash) != 64
            or any(character not in "0123456789abcdef" for character in root_hash)
            or receipt.get("tool_name") not in V4_TOOL_NAMES
            or receipt.get("argument_field")
            not in {"command", "cwd", "patch", "path", "summary", "unparsed"}
            or receipt.get("violation_kind") != "raw_host_path"
            or receipt.get("raw_provider_arguments_persisted") is not False
            or receipt.get("same_session") is not True
            or receipt.get("whole_episode_retries") != 0
            or not isinstance(event_index, int)
            or isinstance(event_index, bool)
            or event_index < 0
            or not isinstance(feedback_index, int)
            or isinstance(feedback_index, bool)
            or not 2 <= feedback_index < len(messages)
            or receipt.get("feedback_text_sha256") != feedback_text_hash
        ):
            raise ValueError(
                f"OpenHands tool-aware parquet row {index} path recovery receipt changed"
            )
        feedback = messages[feedback_index]
        if (
            not isinstance(feedback, dict)
            or feedback != {"role": "user", "content": OPENHANDS_PATH_RECOVERY_MESSAGE}
            or receipt.get("feedback_message_sha256") != content_hash(feedback)
        ):
            raise ValueError(
                f"OpenHands tool-aware parquet row {index} path recovery binding changed"
            )


def _encode_parquet_payloads(row: dict[str, Any]) -> dict[str, Any]:
    encoded = copy.deepcopy(row)
    fields = ["messages", "tools", "exact_token_receipt"]
    if "source_record" in encoded:
        fields.append("source_record")
    for field in fields:
        encoded[field] = _canonical_json(encoded[field])
    return encoded


def _decode_parquet_payloads(row: dict[str, Any]) -> dict[str, Any]:
    decoded = copy.deepcopy(row)
    fields = ["messages", "tools", "exact_token_receipt"]
    if "source_record" in decoded:
        fields.append("source_record")
    for field in fields:
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


def _rendered_message_start(
    tokenizer: ToolAwareTokenizer,
    *,
    full: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    message_index: int,
    mutation: str,
) -> int:
    variants: list[str] = []
    for suffix in ("A", "B"):
        changed = copy.deepcopy(messages)
        message = changed[message_index]
        sentinel = f"VERIGYM_BOUNDARY_{suffix}_8f3c2d1a"
        if mutation == "assistant_tool_name":
            calls = message.get("tool_calls")
            if not isinstance(calls, list) or not calls:
                raise ValueError("assistant boundary requires a complete tool decision")
            calls[0]["function"]["name"] = sentinel
        elif mutation == "message_content":
            message["content"] = sentinel
        else:
            raise ValueError("unknown tool-aware boundary mutation")
        variants.append(_render(tokenizer, changed, tools))
    common = _common_prefix_length(variants[0], variants[1])
    marker = variants[0].rfind("<|im_start|>", 0, common + 1)
    if marker < 0 or full[:marker] != variants[0][:marker]:
        raise ValueError("tool-aware trajectory template message boundary drifted")
    prefix_ids = _encode(tokenizer, full[:marker])
    full_ids = _encode(tokenizer, full)
    if full_ids[: len(prefix_ids)] != prefix_ids:
        raise ValueError("tool-aware trajectory message boundary split a token")
    return len(prefix_ids)


def _common_prefix_length(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return index
    return limit


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


def _read_regular(path: Path, *, max_bytes: int = _MAX_DATASET_BYTES) -> bytes:
    safe = _safe_regular_path(path)
    size = safe.stat().st_size
    if size <= 0 or size > max_bytes:
        raise ValueError(f"64K v4 dataset file size is invalid: {safe.name}")
    return safe.read_bytes()


__all__ = [
    "DECISION_BALANCED_OBJECTIVE",
    "ExactToolAwareTokens",
    "OPENHANDS_DATASET_FORMAT",
    "OPENHANDS_CONTINUATION_DATASET_FORMAT",
    "OPENHANDS_CONTINUATION_RECORD_FORMAT",
    "OPENHANDS_MASKED_CONTINUATION_DATASET_FORMAT",
    "OPENHANDS_MASKED_CONTINUATION_RECORD_FORMAT",
    "OPENHANDS_MASKED_RECOVERY_DATASET_FORMAT",
    "OPENHANDS_MASKED_RECOVERY_RECORD_FORMAT",
    "OPENHANDS_PATH_RECOVERY_DATASET_FORMAT",
    "OPENHANDS_PATH_RECOVERY_RECORD_FORMAT",
    "OPENHANDS_RECORD_FORMAT",
    "OPENHANDS_RECOVERY_DATASET_FORMAT",
    "OPENHANDS_RECOVERY_RECORD_FORMAT",
    "OpenHandsToolAwareParquetInputs",
    "ToolAwareParquetInputs",
    "TRAJECTORY_BALANCED_OBJECTIVE",
    "TRAJECTORY_BALANCED_DECISION_OBJECTIVE",
    "V4_DATASET_FORMAT",
    "V4_EXPECTED_MAX_TOKENS",
    "V4_EXPECTED_RECORDS",
    "V4_EXPECTED_TOOL_ACTIONS",
    "V4_MAX_LENGTH",
    "V4_RECORD_FORMAT",
    "V4_TOOL_NAMES",
    "decode_tool_aware_parquet_value",
    "load_tool_aware_v4_dataset",
    "load_openhands_tool_aware_dataset",
    "read_tool_aware_parquet",
    "tool_aware_exact_final_decision_tokens",
    "tool_aware_exact_all_assistant_tokens",
    "trajectory_balanced_decision_indices",
    "write_tool_aware_parquet",
]
