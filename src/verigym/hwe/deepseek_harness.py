"""Provider-neutral DeepSeek Harness transcript and exact-context SFT contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, Protocol

from verigym.core.hashing import content_hash
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_OBSERVATION_POLICY_V2_ID,
    HWE_TOOL_CONTRACT_V2_ID,
    canonical_hwe_action_json,
    hwe_tool_contract_hash,
    hwe_tool_definitions,
)
from verigym.hwe.trajectory import HweNormalizedEvent
from verigym.schemas.hwe import (
    HweDeepSeekHarnessActionSftDatasetManifest,
    HweDeepSeekHarnessActionSftExample,
    HweDeepSeekHarnessDecisionSftDatasetManifestV3,
    HweDeepSeekHarnessDecisionSftExampleV3,
)

DEEPSEEK_HARNESS_TRANSCRIPT_FORMAT = "verigym_hwe_deepseek_harness_teacher_transcript_v1"
DEEPSEEK_HARNESS_ACTION_SFT_FORMAT = "verigym_hwe_deepseek_harness_action_sft_v1"
DEEPSEEK_HARNESS_DATASET_FORMAT = "verigym_hwe_deepseek_harness_action_sft_dataset_v1"
DEEPSEEK_HARNESS_CAMPAIGN_FORMAT = "verigym_hwe_deepseek_harness_campaign_report_v1"
DEEPSEEK_HARNESS_TRANSCRIPT_FORMAT_V3 = "verigym_hwe_deepseek_harness_teacher_transcript_v3"
DEEPSEEK_HARNESS_DECISION_SFT_FORMAT_V3 = "verigym_hwe_deepseek_harness_decision_sft_v3"
DEEPSEEK_HARNESS_DATASET_FORMAT_V3 = "verigym_hwe_deepseek_harness_decision_sft_dataset_v3"
DEEPSEEK_HARNESS_CAMPAIGN_FORMAT_V3 = "verigym_hwe_deepseek_harness_campaign_report_v3"
DEEPSEEK_HARNESS_MODEL = "deepseek-v4-flash"
DEEPSEEK_HARNESS_REVISION = "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"
DEEPSEEK_HARNESS_PILOT_TASKS = (
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
)
DEEPSEEK_HARNESS_TOOL_NAMES = (
    "apply_patch",
    "finish",
    "inspect_diff",
    "list_files",
    "read_file",
    "shell",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ExactChatTokenizer(Protocol):
    tokenizer_id: str
    tokenizer_hash: str
    chat_template_hash: str

    def count_action_example(
        self,
        *,
        tools: Sequence[Mapping[str, Any]],
        input_messages: Sequence[Mapping[str, Any]],
        target_message: Mapping[str, Any],
    ) -> tuple[int, int, int]: ...


class ExactDecisionTokenizer(Protocol):
    tokenizer_id: str
    tokenizer_hash: str
    chat_template_hash: str

    def count_decision_example(
        self,
        *,
        tools: Sequence[Mapping[str, Any]],
        input_messages: Sequence[Mapping[str, Any]],
        target_message: Mapping[str, Any],
    ) -> tuple[int, int, int]: ...


def build_deepseek_harness_transcript(
    *,
    task_id: str,
    system_prompt: str,
    task_prompt: str,
    session_events: Sequence[Mapping[str, Any]],
    broker_events: Sequence[HweNormalizedEvent],
    broker_call_ids: Sequence[str],
    harness_identity: Mapping[str, Any],
    verifier_resolved: bool = False,
    infrastructure_valid: bool = True,
) -> dict[str, Any]:
    """Normalize one append-only DSH session without changing model-visible context."""

    if len(broker_events) != len(broker_call_ids):
        raise ValueError("DeepSeek Harness broker events and call ids differ")
    if not system_prompt.strip() or not task_prompt.strip():
        raise ValueError("DeepSeek Harness prompts must be non-empty")
    _validate_harness_identity(harness_identity)
    tools = deepseek_harness_tool_definitions()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_prompt},
    ]
    normalized_events: list[dict[str, Any]] = []
    headers: list[dict[str, Any]] = []
    assistant_by_call: dict[str, dict[str, Any]] = {}
    usage_input = 0
    usage_output = 0
    model_calls = 0
    user_messages = 0
    saw_turn_end = False
    observed_model: str | None = None

    for raw in session_events:
        event_type = raw.get("type")
        data = raw.get("data")
        if not isinstance(event_type, str) or not isinstance(data, Mapping):
            continue
        if event_type == "request/header":
            header = data.get("header")
            if not isinstance(header, Mapping):
                raise ValueError("DeepSeek Harness request header is malformed")
            headers.append(dict(copy.deepcopy(header)))
        elif event_type == "user/message":
            embedded_message = data.get("message")
            user_message: Mapping[Any, Any] = (
                embedded_message if isinstance(embedded_message, Mapping) else data
            )
            text = _text_content(user_message.get("content"))
            user_messages += 1
            if user_messages != 1 or text != task_prompt:
                raise ValueError("DeepSeek Harness injected an unexpected user message")
        elif event_type == "assistant/message":
            assistant_message = data.get("message")
            if not isinstance(assistant_message, Mapping):
                raise ValueError("DeepSeek Harness assistant message is malformed")
            source = assistant_message.get("source")
            if isinstance(source, Mapping) and isinstance(source.get("model"), str):
                observed_model = str(source["model"])
            blocks = assistant_message.get("content")
            if not isinstance(blocks, list) or len(blocks) != 1:
                raise ValueError("DeepSeek Harness requires exactly one action block per step")
            block = blocks[0]
            if not isinstance(block, Mapping) or block.get("type") != "tool-call":
                raise ValueError(
                    "DeepSeek Harness emitted prose or reasoning instead of one tool call"
                )
            call_id = block.get("id")
            name = block.get("name")
            arguments_json = block.get("arguments")
            if (
                not isinstance(call_id, str)
                or not isinstance(name, str)
                or not isinstance(arguments_json, str)
            ):
                raise ValueError("DeepSeek Harness tool-call block is malformed")
            if call_id in assistant_by_call:
                raise ValueError("DeepSeek Harness reused a tool-call id")
            arguments = json.loads(arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError("DeepSeek Harness tool arguments are not an object")
            canonical_hwe_action_json(
                name,
                arguments,
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
            assistant: dict[str, Any] = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(
                                arguments,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
            messages.append(assistant)
            assistant_by_call[call_id] = assistant
            usage = data.get("usage")
            if not isinstance(usage, Mapping):
                usage = assistant_message.get("usage")
            if isinstance(usage, Mapping):
                input_tokens = usage.get("inputTokens")
                output_tokens = usage.get("outputTokens")
                usage_input += input_tokens if isinstance(input_tokens, int) else 0
                usage_output += output_tokens if isinstance(output_tokens, int) else 0
            model_calls += 1
        elif event_type == "tool/result":
            tool_message = data.get("message")
            if not isinstance(tool_message, Mapping):
                raise ValueError("DeepSeek Harness tool result is malformed")
            source = tool_message.get("source")
            call_id = source.get("callId") if isinstance(source, Mapping) else None
            if not isinstance(call_id, str) or call_id not in assistant_by_call:
                raise ValueError("DeepSeek Harness tool result lacks its assistant call")
            content = tool_message.get("content")
            if not isinstance(content, list) or len(content) != 1:
                raise ValueError("DeepSeek Harness tool result has an unexpected shape")
            result_block = content[0]
            if not isinstance(result_block, Mapping) or result_block.get("type") != "tool-result":
                raise ValueError("DeepSeek Harness tool result block is malformed")
            if result_block.get("toolCallId") != call_id or result_block.get("isError") is True:
                raise ValueError("DeepSeek Harness tool call did not complete successfully")
            result_text = _text_content(result_block.get("content"))
            assistant = assistant_by_call.pop(call_id)
            completed_call: dict[str, Any] = assistant["tool_calls"][0]
            name = completed_call["function"]["name"]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": result_text,
                }
            )
        elif event_type == "turn/end":
            reason = data.get("reason")
            if not isinstance(reason, Mapping) or reason.get("kind") != "completed":
                raise ValueError("DeepSeek Harness turn did not end with completed")
            saw_turn_end = True

    if assistant_by_call or not saw_turn_end:
        raise ValueError("DeepSeek Harness session ended with an incomplete action")
    _validate_headers(headers, expected_system=system_prompt)
    if observed_model not in {None, DEEPSEEK_HARNESS_MODEL}:
        raise ValueError("DeepSeek Harness observed model differs from the frozen model")
    if len(broker_events) != model_calls or not broker_events:
        raise ValueError("DeepSeek Harness model and broker action counts differ")
    if broker_events[-1].action != "finish":
        raise ValueError("DeepSeek Harness transcript lacks an explicit finish action")

    for index, (event, call_id) in enumerate(zip(broker_events, broker_call_ids, strict=True)):
        assistant = messages[2 + index * 2]
        observation = messages[3 + index * 2]
        replayed_call: dict[str, Any] = assistant["tool_calls"][0]
        if (
            replayed_call["id"] != call_id
            or replayed_call["function"]["name"] != event.action
            or observation["tool_call_id"] != call_id
            or observation["name"] != event.action
            or event.sequence != index
        ):
            raise ValueError("DeepSeek Harness session and broker causality differ")
        if event.compact_observation_sha256 != content_hash_bytes(observation["content"]):
            raise ValueError("DeepSeek Harness tool result differs from broker compact output")
        normalized_events.append(
            {
                **asdict(event),
                "changed_paths": list(event.changed_paths),
                "call_id": call_id,
                "turn": 1,
                "step": index + 1,
            }
        )

    base = {
        "schema_version": "1.0",
        "format_id": DEEPSEEK_HARNESS_TRANSCRIPT_FORMAT,
        "task_id": task_id,
        "provider": "deepseek-official",
        "requested_model_id": DEEPSEEK_HARNESS_MODEL,
        "observed_model_id": observed_model or DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "observation_policy_id": HWE_OBSERVATION_POLICY_V2_ID,
        "tool_contract_id": HWE_TOOL_CONTRACT_V2_ID,
        "tool_contract_hash": hwe_tool_contract_hash(profile_id=HWE_COLLECTION_PROFILE_V2_ID),
        "harness_identity": dict(copy.deepcopy(harness_identity)),
        "tools": tools,
        "messages": messages,
        "normalized_events": normalized_events,
        "model_call_count": model_calls,
        "input_tokens": usage_input,
        "output_tokens": usage_output,
        "total_tokens": usage_input + usage_output,
        "verifier_resolved": verifier_resolved,
        "infrastructure_valid": infrastructure_valid,
        "causal_validation": "passed",
        "exact_model_visible_context": True,
        "context_transformed_after_collection": False,
        "nap_required": False,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    return {**base, "transcript_hash": content_hash(base)}


def validate_deepseek_harness_transcript(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(copy.deepcopy(value))
    expected = candidate.pop("transcript_hash", None)
    if not isinstance(expected, str) or content_hash(candidate) != expected:
        raise ValueError("DeepSeek Harness transcript identity changed")
    required = {
        "format_id": DEEPSEEK_HARNESS_TRANSCRIPT_FORMAT,
        "requested_model_id": DEEPSEEK_HARNESS_MODEL,
        "observed_model_id": DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "observation_policy_id": HWE_OBSERVATION_POLICY_V2_ID,
        "tool_contract_id": HWE_TOOL_CONTRACT_V2_ID,
        "tool_contract_hash": hwe_tool_contract_hash(profile_id=HWE_COLLECTION_PROFILE_V2_ID),
        "infrastructure_valid": True,
        "causal_validation": "passed",
        "exact_model_visible_context": True,
        "context_transformed_after_collection": False,
        "nap_required": False,
    }
    if any(value.get(key) != item for key, item in required.items()):
        raise ValueError("DeepSeek Harness transcript differs from its frozen contract")
    _validate_harness_identity(value.get("harness_identity"))
    tools = value.get("tools")
    if tools != deepseek_harness_tool_definitions():
        raise ValueError("DeepSeek Harness transcript tool schemas changed")
    messages = value.get("messages")
    events = value.get("normalized_events")
    if not isinstance(messages, list) or not isinstance(events, list) or not events:
        raise ValueError("DeepSeek Harness transcript lacks messages or events")
    if len(messages) != 2 + 2 * len(events):
        raise ValueError("DeepSeek Harness transcript message causality changed")
    for key in (
        "raw_provider_events_exported",
        "raw_observations_exported",
        "private_reasoning_exported",
        "hidden_assets_exported",
        "reference_solutions_exported",
        "credential_values_exported",
        "raw_host_paths_exported",
    ):
        if value.get(key) is not False:
            raise ValueError(f"DeepSeek Harness transcript violates {key}")
    return dict(copy.deepcopy(value))


def set_deepseek_harness_verifier_result(
    transcript: Mapping[str, Any],
    *,
    verifier_resolved: bool,
) -> dict[str, Any]:
    validated = validate_deepseek_harness_transcript(transcript)
    validated.pop("transcript_hash")
    validated["verifier_resolved"] = verifier_resolved
    return {**validated, "transcript_hash": content_hash(validated)}


def materialize_deepseek_harness_action_examples(
    transcript: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    tokenizer: ExactChatTokenizer,
    max_length: int = 32_768,
) -> list[dict[str, Any]]:
    validated = validate_deepseek_harness_transcript(transcript)
    if validated.get("verifier_resolved") is not True:
        raise ValueError("only verifier-passed DeepSeek Harness transcripts may enter SFT")
    _validate_binding(binding)
    messages = validated["messages"]
    tools = validated["tools"]
    examples: list[dict[str, Any]] = []
    for action_index in range(len(validated["normalized_events"])):
        target_index = 2 + action_index * 2
        target = copy.deepcopy(messages[target_index])
        input_messages = copy.deepcopy(messages[:target_index])
        total_tokens, input_tokens, target_tokens = tokenizer.count_action_example(
            tools=tools,
            input_messages=input_messages,
            target_message=target,
        )
        base = {
            "schema_version": "1.0",
            "format_id": DEEPSEEK_HARNESS_ACTION_SFT_FORMAT,
            "sample_id": binding["sample_id"],
            "task_id": validated["task_id"],
            "task_hash": binding["task_hash"],
            "source_hash": binding["source_hash"],
            "candidate_hash": binding["candidate_hash"],
            "verifier_hash": binding["verifier_hash"],
            "transcript_hash": validated["transcript_hash"],
            "action_index": action_index,
            "call_id": validated["normalized_events"][action_index]["call_id"],
            "tools": tools,
            "input_messages": input_messages,
            "target_message": target,
            "tokenizer_id": tokenizer.tokenizer_id,
            "tokenizer_hash": tokenizer.tokenizer_hash,
            "chat_template_hash": tokenizer.chat_template_hash,
            "input_tokens": input_tokens,
            "target_tokens": target_tokens,
            "token_count": total_tokens,
            "max_length": max_length,
            "truncation": "error",
            "eligible": total_tokens <= max_length,
            "supervised_roles": ["assistant"],
            "masked_roles": ["system", "user", "tool"],
            "exact_model_visible_context": True,
            "context_transformed_after_collection": False,
            "nap_required": False,
            "verifier_resolved": True,
            "infrastructure_valid": True,
            "raw_provider_events_exported": False,
            "raw_observations_exported": False,
            "private_reasoning_exported": False,
            "hidden_assets_exported": False,
            "reference_solutions_exported": False,
            "credential_values_exported": False,
            "raw_host_paths_exported": False,
        }
        example = HweDeepSeekHarnessActionSftExample.model_validate(
            {**base, "record_hash": content_hash(base)}
        )
        examples.append(example.model_dump(mode="json"))
    return examples


def build_deepseek_harness_dataset_manifest(
    examples: Sequence[Mapping[str, Any]],
    *,
    pilot_task_ids: Sequence[str],
) -> dict[str, Any]:
    hashes: list[str] = []
    overlength: list[dict[str, Any]] = []
    represented_tasks: set[str] = set()
    for example in examples:
        validated_example = HweDeepSeekHarnessActionSftExample.model_validate(example)
        hashes.append(validated_example.record_hash)
        represented_tasks.add(validated_example.task_id)
        if not validated_example.eligible:
            overlength.append(
                {
                    "task_id": validated_example.task_id,
                    "action_index": validated_example.action_index,
                    "token_count": validated_example.token_count,
                }
            )
    tasks = sorted(set(str(item) for item in pilot_task_ids))
    if tasks != list(DEEPSEEK_HARNESS_PILOT_TASKS):
        raise ValueError("DeepSeek Harness pilot tasks differ from the frozen three-task set")
    represented = sorted(represented_tasks)
    base = {
        "schema_version": "1.0",
        "format_id": DEEPSEEK_HARNESS_DATASET_FORMAT,
        "record_count": len(examples),
        "record_hashes": hashes,
        "pilot_task_ids": tasks,
        "represented_task_ids": represented,
        "trajectory_count": len(represented),
        "max_length": 32_768,
        "truncation": "error",
        "overlength_records": overlength,
        "loader_ready": bool(examples) and not overlength,
        "production_training_ready": False,
        "training_started": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    manifest = HweDeepSeekHarnessActionSftDatasetManifest.model_validate(
        {**base, "dataset_hash": content_hash(base)}
    )
    return manifest.model_dump(mode="json")


def build_deepseek_harness_transcript_v3(
    *,
    task_id: str,
    system_prompt: str,
    task_prompt: str,
    session_events: Sequence[Mapping[str, Any]],
    broker_events: Sequence[HweNormalizedEvent],
    broker_call_ids: Sequence[str],
    harness_identity: Mapping[str, Any],
    format_repair_prompts: Sequence[str] = (),
    verifier_resolved: bool = False,
    infrastructure_valid: bool = True,
) -> dict[str, Any]:
    """Normalize the native Harness decision stream while retaining recoverable errors."""

    if len(broker_events) != len(broker_call_ids):
        raise ValueError("DeepSeek Harness v3 broker events and call ids differ")
    if not system_prompt.strip() or not task_prompt.strip():
        raise ValueError("DeepSeek Harness v3 prompts must be non-empty")
    if len(format_repair_prompts) > 1 or any(not item.strip() for item in format_repair_prompts):
        raise ValueError("DeepSeek Harness v3 format repair receipt is invalid")
    _validate_harness_identity(harness_identity)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_prompt},
    ]
    tools = deepseek_harness_tool_definitions()
    headers: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    call_result_error: dict[str, bool] = {}
    successful_call_ids: list[str] = []
    turn_end_reasons: list[str] = []
    usage_input = 0
    usage_output = 0
    observed_model: str | None = None
    user_messages: list[str] = []
    current_turn = 0

    for raw in session_events:
        event_type = raw.get("type")
        data = raw.get("data")
        if not isinstance(event_type, str) or not isinstance(data, Mapping):
            continue
        if event_type == "request/header":
            header = data.get("header")
            if not isinstance(header, Mapping):
                raise ValueError("DeepSeek Harness v3 request header is malformed")
            headers.append(dict(copy.deepcopy(header)))
        elif event_type == "user/message":
            embedded = data.get("message")
            message = embedded if isinstance(embedded, Mapping) else data
            text = _text_content(message.get("content"))
            user_messages.append(text)
            current_turn = len(user_messages)
            if current_turn == 1:
                if text != task_prompt:
                    raise ValueError("DeepSeek Harness v3 initial task prompt changed")
            else:
                repair_index = current_turn - 2
                if (
                    repair_index >= len(format_repair_prompts)
                    or text != format_repair_prompts[repair_index]
                ):
                    raise ValueError("DeepSeek Harness v3 injected an unknown user message")
                messages.append({"role": "user", "content": text})
        elif event_type == "assistant/message":
            assistant_message = data.get("message")
            if not isinstance(assistant_message, Mapping):
                raise ValueError("DeepSeek Harness v3 assistant message is malformed")
            source = assistant_message.get("source")
            if isinstance(source, Mapping) and isinstance(source.get("model"), str):
                observed_model = str(source["model"])
            blocks = assistant_message.get("content")
            if not isinstance(blocks, list) or not blocks:
                raise ValueError("DeepSeek Harness v3 assistant content is empty")
            text_parts: list[str] = []
            rendered_calls: list[dict[str, Any]] = []
            saw_tool_call = False
            for block in blocks:
                if not isinstance(block, Mapping):
                    raise ValueError("DeepSeek Harness v3 assistant block is malformed")
                block_type = block.get("type")
                if block_type == "text":
                    if saw_tool_call or not isinstance(block.get("text"), str):
                        raise ValueError("DeepSeek Harness v3 public text ordering changed")
                    text_parts.append(str(block["text"]))
                    continue
                if block_type != "tool-call":
                    raise ValueError("DeepSeek Harness v3 contains a private or foreign block")
                saw_tool_call = True
                call_id = block.get("id")
                name = block.get("name")
                arguments_json = block.get("arguments")
                if (
                    not isinstance(call_id, str)
                    or not call_id
                    or call_id in calls
                    or not isinstance(name, str)
                    or name not in DEEPSEEK_HARNESS_TOOL_NAMES
                    or not isinstance(arguments_json, str)
                ):
                    raise ValueError("DeepSeek Harness v3 tool-call identity is malformed")
                try:
                    arguments = json.loads(arguments_json)
                except json.JSONDecodeError as exc:
                    raise ValueError("DeepSeek Harness v3 tool arguments are invalid JSON") from exc
                if not isinstance(arguments, dict):
                    raise ValueError("DeepSeek Harness v3 tool arguments are not an object")
                rendered = {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(
                            arguments,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                    },
                }
                rendered_calls.append(rendered)
                calls[call_id] = {
                    "decision_index": len(decisions),
                    "name": name,
                    "arguments": arguments,
                }
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(text_parts) or None,
            }
            if rendered_calls:
                assistant["tool_calls"] = rendered_calls
            message_index = len(messages)
            messages.append(assistant)
            decisions.append(
                {
                    "decision_index": len(decisions),
                    "message_index": message_index,
                    "turn": current_turn,
                    "call_ids": [item["id"] for item in rendered_calls],
                    "action_names": [item["function"]["name"] for item in rendered_calls],
                    "public_text_present": bool(assistant["content"]),
                }
            )
            usage = data.get("usage")
            if not isinstance(usage, Mapping):
                usage = assistant_message.get("usage")
            if isinstance(usage, Mapping):
                input_tokens = usage.get("inputTokens")
                output_tokens = usage.get("outputTokens")
                usage_input += input_tokens if isinstance(input_tokens, int) else 0
                usage_output += output_tokens if isinstance(output_tokens, int) else 0
        elif event_type == "tool/result":
            tool_message = data.get("message")
            if not isinstance(tool_message, Mapping):
                raise ValueError("DeepSeek Harness v3 tool result is malformed")
            source = tool_message.get("source")
            call_id = source.get("callId") if isinstance(source, Mapping) else None
            if not isinstance(call_id, str) or call_id not in calls or call_id in call_result_error:
                raise ValueError("DeepSeek Harness v3 tool result lacks a unique assistant call")
            content = tool_message.get("content")
            if not isinstance(content, list) or len(content) != 1:
                raise ValueError("DeepSeek Harness v3 tool result shape changed")
            result_block = content[0]
            if (
                not isinstance(result_block, Mapping)
                or result_block.get("type") != "tool-result"
                or result_block.get("toolCallId") != call_id
                or not isinstance(result_block.get("isError"), bool)
            ):
                raise ValueError("DeepSeek Harness v3 tool result block is malformed")
            result_text = _text_content(result_block.get("content"))
            is_error = bool(result_block["isError"])
            call_result_error[call_id] = is_error
            if not is_error:
                successful_call_ids.append(call_id)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": calls[call_id]["name"],
                    "content": result_text,
                    "error": is_error,
                }
            )
        elif event_type == "turn/end":
            reason = data.get("reason")
            kind = reason.get("kind") if isinstance(reason, Mapping) else None
            if kind not in {"completed", "max-tokens"}:
                raise ValueError("DeepSeek Harness v3 turn ended unexpectedly")
            turn_end_reasons.append(str(kind))

    expected_users = [task_prompt, *format_repair_prompts]
    if user_messages != expected_users:
        raise ValueError("DeepSeek Harness v3 user-message receipt changed")
    if not turn_end_reasons or turn_end_reasons[-1] != "completed":
        raise ValueError("DeepSeek Harness v3 final interval did not complete")
    if len(turn_end_reasons) != len(expected_users):
        raise ValueError("DeepSeek Harness v3 run interval count changed")
    if format_repair_prompts and turn_end_reasons[:-1][0] not in {"max-tokens", "completed"}:
        raise ValueError("DeepSeek Harness v3 format repair trigger changed")
    if len(call_result_error) != len(calls):
        raise ValueError("DeepSeek Harness v3 ended with an incomplete tool call")
    _validate_headers(headers, expected_system=system_prompt)
    if observed_model not in {None, DEEPSEEK_HARNESS_MODEL}:
        raise ValueError("DeepSeek Harness v3 observed model changed")
    if successful_call_ids != list(broker_call_ids):
        raise ValueError("DeepSeek Harness v3 successful calls differ from broker calls")
    if not broker_events or broker_events[-1].action != "finish":
        raise ValueError("DeepSeek Harness v3 transcript lacks an accepted finish action")

    normalized_events: list[dict[str, Any]] = []
    event_by_call: dict[str, HweNormalizedEvent] = {}
    for index, (event, call_id) in enumerate(zip(broker_events, broker_call_ids, strict=True)):
        call = calls.get(call_id)
        if call is None or call_result_error.get(call_id) is not False or event.sequence != index:
            raise ValueError("DeepSeek Harness v3 broker sequence changed")
        canonical = json.loads(
            canonical_hwe_action_json(
                str(call["name"]),
                call["arguments"],
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
        )
        if event.action != call["name"] or event.arguments != canonical["arguments"]:
            raise ValueError("DeepSeek Harness v3 action differs from the broker action")
        tool_messages = [
            message
            for message in messages
            if message.get("role") == "tool" and message.get("tool_call_id") == call_id
        ]
        if len(tool_messages) != 1 or event.compact_observation_sha256 != content_hash_bytes(
            str(tool_messages[0]["content"])
        ):
            raise ValueError("DeepSeek Harness v3 compact observation changed")
        event_by_call[call_id] = event
        normalized_events.append(
            {
                **asdict(event),
                "changed_paths": list(event.changed_paths),
                "call_id": call_id,
                "turn": decisions[int(call["decision_index"])]["turn"],
                "decision_index": call["decision_index"],
            }
        )

    masked_policy = 0
    masked_format = 0
    for decision in decisions:
        decision_call_ids = decision["call_ids"]
        result_errors = [call_result_error[call_id] for call_id in decision_call_ids]
        supervised = (
            bool(decision_call_ids)
            and not any(result_errors)
            and all(call_id in event_by_call for call_id in decision_call_ids)
        )
        decision["tool_result_errors"] = result_errors
        decision["supervised_target"] = supervised
        decision["mask_reason"] = (
            None
            if supervised
            else "format_error_no_tool_call"
            if not decision_call_ids
            else "policy_rejected_tool_decision"
        )
        masked_format += int(not decision_call_ids)
        masked_policy += int(bool(decision_call_ids) and not supervised)

    base = {
        "schema_version": "1.0",
        "format_id": DEEPSEEK_HARNESS_TRANSCRIPT_FORMAT_V3,
        "task_id": task_id,
        "provider": "deepseek-official",
        "requested_model_id": DEEPSEEK_HARNESS_MODEL,
        "observed_model_id": observed_model or DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "observation_policy_id": HWE_OBSERVATION_POLICY_V2_ID,
        "tool_contract_id": HWE_TOOL_CONTRACT_V2_ID,
        "tool_contract_hash": hwe_tool_contract_hash(profile_id=HWE_COLLECTION_PROFILE_V2_ID),
        "harness_identity": dict(copy.deepcopy(harness_identity)),
        "tools": tools,
        "messages": messages,
        "assistant_decisions": decisions,
        "normalized_events": normalized_events,
        "assistant_decision_count": len(decisions),
        "accepted_tool_action_count": len(normalized_events),
        "supervised_decision_count": sum(item["supervised_target"] for item in decisions),
        "masked_policy_error_decision_count": masked_policy,
        "masked_format_error_decision_count": masked_format,
        "format_repair_prompts": list(format_repair_prompts),
        "format_repair_count": len(format_repair_prompts),
        "run_interval_count": len(expected_users),
        "turn_end_reasons": turn_end_reasons,
        "model_call_count": len(decisions),
        "input_tokens": usage_input,
        "output_tokens": usage_output,
        "total_tokens": usage_input + usage_output,
        "verifier_resolved": verifier_resolved,
        "infrastructure_valid": infrastructure_valid,
        "causal_validation": "passed",
        "assistant_output_contract": "public_text_plus_one_or_more_typed_tool_calls",
        "failed_decisions_retained_as_context": True,
        "failed_decisions_supervised": False,
        "exact_model_visible_context": True,
        "context_transformed_after_collection": False,
        "nap_required": False,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    return {**base, "transcript_hash": content_hash(base)}


def validate_deepseek_harness_transcript_v3(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(copy.deepcopy(value))
    expected = candidate.pop("transcript_hash", None)
    if not isinstance(expected, str) or content_hash(candidate) != expected:
        raise ValueError("DeepSeek Harness v3 transcript identity changed")
    required = {
        "format_id": DEEPSEEK_HARNESS_TRANSCRIPT_FORMAT_V3,
        "requested_model_id": DEEPSEEK_HARNESS_MODEL,
        "observed_model_id": DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "observation_policy_id": HWE_OBSERVATION_POLICY_V2_ID,
        "tool_contract_id": HWE_TOOL_CONTRACT_V2_ID,
        "tool_contract_hash": hwe_tool_contract_hash(profile_id=HWE_COLLECTION_PROFILE_V2_ID),
        "infrastructure_valid": True,
        "causal_validation": "passed",
        "assistant_output_contract": "public_text_plus_one_or_more_typed_tool_calls",
        "failed_decisions_retained_as_context": True,
        "failed_decisions_supervised": False,
        "exact_model_visible_context": True,
        "context_transformed_after_collection": False,
        "nap_required": False,
    }
    if any(value.get(key) != item for key, item in required.items()):
        raise ValueError("DeepSeek Harness v3 transcript differs from its frozen contract")
    _validate_harness_identity(value.get("harness_identity"))
    if value.get("tools") != deepseek_harness_tool_definitions():
        raise ValueError("DeepSeek Harness v3 tool schemas changed")
    messages = value.get("messages")
    decisions = value.get("assistant_decisions")
    events = value.get("normalized_events")
    repairs = value.get("format_repair_prompts")
    if (
        not isinstance(messages, list)
        or not isinstance(decisions, list)
        or not decisions
        or not isinstance(events, list)
        or not events
        or not isinstance(repairs, list)
        or len(repairs) > 1
        or value.get("assistant_decision_count") != len(decisions)
        or value.get("accepted_tool_action_count") != len(events)
        or value.get("supervised_decision_count")
        != sum(item.get("supervised_target") is True for item in decisions)
        or value.get("masked_policy_error_decision_count")
        != sum(item.get("mask_reason") == "policy_rejected_tool_decision" for item in decisions)
        or value.get("masked_format_error_decision_count")
        != sum(item.get("mask_reason") == "format_error_no_tool_call" for item in decisions)
        or value.get("format_repair_count") != len(repairs)
        or value.get("run_interval_count") != 1 + len(repairs)
    ):
        raise ValueError("DeepSeek Harness v3 transcript counts changed")
    for index, decision in enumerate(decisions):
        message_index = decision.get("message_index")
        if (
            decision.get("decision_index") != index
            or not isinstance(message_index, int)
            or message_index >= len(messages)
            or messages[message_index].get("role") != "assistant"
            or [item.get("id") for item in messages[message_index].get("tool_calls", [])]
            != decision.get("call_ids")
        ):
            raise ValueError("DeepSeek Harness v3 decision-message binding changed")
    for key in (
        "raw_provider_events_exported",
        "raw_observations_exported",
        "private_reasoning_exported",
        "hidden_assets_exported",
        "reference_solutions_exported",
        "credential_values_exported",
        "raw_host_paths_exported",
    ):
        if value.get(key) is not False:
            raise ValueError(f"DeepSeek Harness v3 transcript violates {key}")
    return dict(copy.deepcopy(value))


def set_deepseek_harness_verifier_result_v3(
    transcript: Mapping[str, Any],
    *,
    verifier_resolved: bool,
) -> dict[str, Any]:
    validated = validate_deepseek_harness_transcript_v3(transcript)
    validated.pop("transcript_hash")
    validated["verifier_resolved"] = verifier_resolved
    return {**validated, "transcript_hash": content_hash(validated)}


def materialize_deepseek_harness_decision_examples_v3(
    transcript: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    tokenizer: ExactDecisionTokenizer,
    max_length: int = 32_768,
) -> list[dict[str, Any]]:
    validated = validate_deepseek_harness_transcript_v3(transcript)
    if validated.get("verifier_resolved") is not True:
        raise ValueError("only verifier-passed DeepSeek Harness v3 transcripts may enter SFT")
    _validate_binding(binding)
    messages = validated["messages"]
    tools = validated["tools"]
    examples: list[dict[str, Any]] = []
    for decision in validated["assistant_decisions"]:
        if decision["supervised_target"] is not True:
            continue
        target_index = decision["message_index"]
        target = copy.deepcopy(messages[target_index])
        input_messages = copy.deepcopy(messages[:target_index])
        total_tokens, input_tokens, target_tokens = tokenizer.count_decision_example(
            tools=tools,
            input_messages=input_messages,
            target_message=target,
        )
        base = {
            "schema_version": "1.0",
            "format_id": DEEPSEEK_HARNESS_DECISION_SFT_FORMAT_V3,
            "sample_id": binding["sample_id"],
            "task_id": validated["task_id"],
            "task_hash": binding["task_hash"],
            "source_hash": binding["source_hash"],
            "candidate_hash": binding["candidate_hash"],
            "verifier_hash": binding["verifier_hash"],
            "transcript_hash": validated["transcript_hash"],
            "decision_index": decision["decision_index"],
            "target_message_index": target_index,
            "call_ids": decision["call_ids"],
            "action_names": decision["action_names"],
            "tool_action_count": len(decision["call_ids"]),
            "trajectory_assistant_decision_count": validated["assistant_decision_count"],
            "trajectory_accepted_tool_action_count": validated["accepted_tool_action_count"],
            "trajectory_masked_policy_error_decision_count": validated[
                "masked_policy_error_decision_count"
            ],
            "trajectory_masked_format_error_decision_count": validated[
                "masked_format_error_decision_count"
            ],
            "trajectory_format_repair_count": validated["format_repair_count"],
            "tools": tools,
            "input_messages": input_messages,
            "target_message": target,
            "tokenizer_id": tokenizer.tokenizer_id,
            "tokenizer_hash": tokenizer.tokenizer_hash,
            "chat_template_hash": tokenizer.chat_template_hash,
            "input_tokens": input_tokens,
            "target_tokens": target_tokens,
            "token_count": total_tokens,
            "max_length": max_length,
            "truncation": "error",
            "eligible": total_tokens <= max_length,
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
            "public_assistant_text_exported": bool(target.get("content")),
            "raw_provider_events_exported": False,
            "raw_observations_exported": False,
            "private_reasoning_exported": False,
            "hidden_assets_exported": False,
            "reference_solutions_exported": False,
            "credential_values_exported": False,
            "raw_host_paths_exported": False,
        }
        model = HweDeepSeekHarnessDecisionSftExampleV3.model_validate(
            {**base, "record_hash": content_hash(base)}
        )
        examples.append(model.model_dump(mode="json"))
    return examples


def build_deepseek_harness_dataset_manifest_v3(
    examples: Sequence[Mapping[str, Any]],
    *,
    pilot_task_ids: Sequence[str],
) -> dict[str, Any]:
    validated = [HweDeepSeekHarnessDecisionSftExampleV3.model_validate(item) for item in examples]
    tasks = sorted(set(str(item) for item in pilot_task_ids))
    if tasks != list(DEEPSEEK_HARNESS_PILOT_TASKS):
        raise ValueError("DeepSeek Harness v3 pilot tasks differ from the frozen set")
    represented = sorted({item.task_id for item in validated})
    trajectory_receipts: dict[str, tuple[int, int, int]] = {}
    for item in validated:
        receipt = (
            item.trajectory_masked_policy_error_decision_count,
            item.trajectory_masked_format_error_decision_count,
            item.trajectory_format_repair_count,
        )
        previous = trajectory_receipts.setdefault(item.sample_id, receipt)
        if previous != receipt:
            raise ValueError("DeepSeek Harness v3 trajectory receipt changed between rows")
    overlength = [
        {
            "task_id": item.task_id,
            "decision_index": item.decision_index,
            "token_count": item.token_count,
        }
        for item in validated
        if not item.eligible
    ]
    base = {
        "schema_version": "1.0",
        "format_id": DEEPSEEK_HARNESS_DATASET_FORMAT_V3,
        "record_count": len(validated),
        "record_hashes": [item.record_hash for item in validated],
        "pilot_task_ids": tasks,
        "represented_task_ids": represented,
        "trajectory_count": len(represented),
        "supervised_decision_count": len(validated),
        "supervised_tool_action_count": sum(item.tool_action_count for item in validated),
        "masked_policy_error_decision_count": sum(item[0] for item in trajectory_receipts.values()),
        "masked_format_error_decision_count": sum(item[1] for item in trajectory_receipts.values()),
        "format_repair_count": sum(item[2] for item in trajectory_receipts.values()),
        "max_length": 32_768,
        "truncation": "error",
        "overlength_records": overlength,
        "loader_ready": bool(validated) and not overlength,
        "production_training_ready": False,
        "training_started": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    manifest = HweDeepSeekHarnessDecisionSftDatasetManifestV3.model_validate(
        {**base, "dataset_hash": content_hash(base)}
    )
    return manifest.model_dump(mode="json")


def content_hash_bytes(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def deepseek_harness_tool_definitions() -> list[dict[str, Any]]:
    """Project HWE v2 into the pinned Harness JSON-schema subset and stable order."""

    canonical = hwe_tool_definitions(profile_id=HWE_COLLECTION_PROFILE_V2_ID)
    projected: list[dict[str, Any]] = []
    for item in canonical:
        clone = copy.deepcopy(item)
        function = clone["function"]
        for value in function["parameters"]["properties"].values():
            value.pop("minimum", None)
        projected.append(clone)
    projected.sort(key=lambda item: item["function"]["name"])
    if tuple(item["function"]["name"] for item in projected) != DEEPSEEK_HARNESS_TOOL_NAMES:
        raise AssertionError("DeepSeek Harness tool projection changed")
    return projected


def _validate_headers(
    headers: Sequence[Mapping[str, Any]],
    *,
    expected_system: str,
) -> None:
    if not headers:
        raise ValueError("DeepSeek Harness session lacks a request header")
    for header in headers:
        config = header.get("config")
        if not isinstance(config, Mapping):
            raise ValueError("DeepSeek Harness request config is missing")
        required = {
            "provider": "deepseek-official",
            "model": DEEPSEEK_HARNESS_MODEL,
            "maxTokens": 2048,
            "reasoningEffort": "off",
            "temperature": 0,
        }
        if any(config.get(key) != item for key, item in required.items()):
            raise ValueError("DeepSeek Harness effective request configuration changed")
        if header.get("system") != expected_system:
            raise ValueError("DeepSeek Harness effective system prompt changed")
        raw_tools = header.get("tools")
        expected_tools = [item["function"] for item in deepseek_harness_tool_definitions()]
        if raw_tools != expected_tools:
            raise ValueError("DeepSeek Harness request exposed tools outside the six-tool contract")


def _text_content(value: object) -> str:
    if not isinstance(value, list):
        raise ValueError("DeepSeek Harness content blocks are malformed")
    parts: list[str] = []
    for block in value:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            raise ValueError("DeepSeek Harness content includes reasoning or a foreign block")
        text = block.get("text")
        if not isinstance(text, str):
            raise ValueError("DeepSeek Harness text block is malformed")
        parts.append(text)
    return "".join(parts)


def _validate_harness_identity(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("DeepSeek Harness identity is missing")
    required = {
        "revision": DEEPSEEK_HARNESS_REVISION,
        "version": "0.1.1-rc.2",
        "sdk_transport": "python_sdk_source_controller_container",
        "controller_network": "verigym-hwe-net",
        "tool_transport": "owner_only_unix_socket",
    }
    if any(value.get(key) != item for key, item in required.items()):
        raise ValueError("DeepSeek Harness dependency identity changed")
    for key in (
        "source_tree_hash",
        "controller_image_id",
        "controller_image_digest_hash",
        "cordis_config_hash",
        "tool_plugin_hash",
        "configuration_fingerprint",
    ):
        item = value.get(key)
        if not isinstance(item, str) or not _SHA256.fullmatch(item):
            raise ValueError(f"DeepSeek Harness identity {key} must be SHA-256")


def _validate_binding(binding: Mapping[str, Any]) -> None:
    for key in ("sample_id", "task_hash", "source_hash", "candidate_hash", "verifier_hash"):
        value = binding.get(key)
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError(f"DeepSeek Harness binding {key} must be SHA-256")


__all__ = [
    "DEEPSEEK_HARNESS_ACTION_SFT_FORMAT",
    "DEEPSEEK_HARNESS_CAMPAIGN_FORMAT_V3",
    "DEEPSEEK_HARNESS_CAMPAIGN_FORMAT",
    "DEEPSEEK_HARNESS_DATASET_FORMAT",
    "DEEPSEEK_HARNESS_DATASET_FORMAT_V3",
    "DEEPSEEK_HARNESS_DECISION_SFT_FORMAT_V3",
    "DEEPSEEK_HARNESS_MODEL",
    "DEEPSEEK_HARNESS_PILOT_TASKS",
    "DEEPSEEK_HARNESS_REVISION",
    "DEEPSEEK_HARNESS_TOOL_NAMES",
    "DEEPSEEK_HARNESS_TRANSCRIPT_FORMAT",
    "DEEPSEEK_HARNESS_TRANSCRIPT_FORMAT_V3",
    "ExactDecisionTokenizer",
    "ExactChatTokenizer",
    "build_deepseek_harness_dataset_manifest",
    "build_deepseek_harness_dataset_manifest_v3",
    "build_deepseek_harness_transcript",
    "build_deepseek_harness_transcript_v3",
    "deepseek_harness_tool_definitions",
    "materialize_deepseek_harness_action_examples",
    "materialize_deepseek_harness_decision_examples_v3",
    "set_deepseek_harness_verifier_result",
    "set_deepseek_harness_verifier_result_v3",
    "validate_deepseek_harness_transcript",
    "validate_deepseek_harness_transcript_v3",
]
