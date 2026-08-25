from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.collect_cva6_hwe_deepseek import _zero_model_call_preflight_receipt
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness import (
    DEEPSEEK_HARNESS_PILOT_TASKS,
    build_deepseek_harness_dataset_manifest,
    build_deepseek_harness_dataset_manifest_v3,
    build_deepseek_harness_transcript,
    build_deepseek_harness_transcript_v3,
    deepseek_harness_tool_definitions,
    materialize_deepseek_harness_action_examples,
    materialize_deepseek_harness_decision_examples_v3,
    set_deepseek_harness_verifier_result,
    set_deepseek_harness_verifier_result_v3,
    validate_deepseek_harness_transcript,
    validate_deepseek_harness_transcript_v3,
)
from verigym.hwe.qwen_action_tokenizer import (
    QwenActionExampleTokenizer,
    QwenDecisionExampleTokenizer,
    dry_run_action_record,
    dry_run_decision_record,
)
from verigym.hwe.trajectory import HweNormalizedEvent


class _StableTemplateTokenizer:
    chat_template = "unit-test-qwen-template-v1"

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
        prefix = json.dumps(tools, sort_keys=True, separators=(",", ":"))
        return prefix + "".join(
            json.dumps(message, sort_keys=True, separators=(",", ":")) for message in conversation
        )

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        assert add_special_tokens is False
        return list(text.encode("utf-8"))


class _OverlengthCounter:
    tokenizer_id = "Qwen3.5-9B/local-frozen-chat-template"
    tokenizer_hash = "8" * 64
    chat_template_hash = "9" * 64

    def count_action_example(self, **_kwargs: Any) -> tuple[int, int, int]:
        return 32_769, 32_768, 1

    def count_decision_example(self, **_kwargs: Any) -> tuple[int, int, int]:
        return 32_769, 32_768, 1


def _identity() -> dict[str, str]:
    return {
        "revision": "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e",
        "version": "0.1.1-rc.2",
        "sdk_transport": "python_sdk_source_controller_container",
        "controller_network": "verigym-hwe-net",
        "tool_transport": "owner_only_unix_socket",
        "source_tree_hash": "1" * 64,
        "controller_image_id": "2" * 64,
        "controller_image_digest_hash": "3" * 64,
        "cordis_config_hash": "4" * 64,
        "tool_plugin_hash": "5" * 64,
        "configuration_fingerprint": "6" * 64,
    }


def _session(*, task_prompt: str, observation: str = "No candidate diff.") -> list[dict[str, Any]]:
    function_tools = [item["function"] for item in deepseek_harness_tool_definitions()]
    return [
        {
            "type": "request/header",
            "data": {
                "header": {
                    "config": {
                        "provider": "deepseek-official",
                        "model": "deepseek-v4-flash",
                        "maxTokens": 2048,
                        "reasoningEffort": "off",
                        "temperature": 0,
                    },
                    "system": "system",
                    "tools": function_tools,
                }
            },
        },
        {
            "type": "user/message",
            "data": {"message": {"content": [{"type": "text", "text": task_prompt}]}},
        },
        {
            "type": "assistant/message",
            "data": {
                "message": {
                    "source": {"model": "deepseek-v4-flash"},
                    "content": [
                        {
                            "type": "tool-call",
                            "id": "call-finish",
                            "name": "finish",
                            "arguments": '{"summary":"done"}',
                        }
                    ],
                },
                "usage": {"inputTokens": 123, "outputTokens": 7},
            },
        },
        {
            "type": "tool/result",
            "data": {
                "message": {
                    "source": {"callId": "call-finish"},
                    "content": [
                        {
                            "type": "tool-result",
                            "toolCallId": "call-finish",
                            "isError": False,
                            "content": [{"type": "text", "text": observation}],
                        }
                    ],
                }
            },
        },
        {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
    ]


def _transcript() -> dict[str, Any]:
    observation = "No candidate diff."
    event = HweNormalizedEvent(
        sequence=0,
        action="finish",
        arguments={"summary": "done"},
        workspace_epoch_before=0,
        workspace_epoch_after=0,
        compact_observation_sha256=__import__("hashlib").sha256(observation.encode()).hexdigest(),
        compact_observation_tokens=4,
        event_mapping="deepseek_harness_native_tool",
    )
    return build_deepseek_harness_transcript(
        task_id=DEEPSEEK_HARNESS_PILOT_TASKS[0],
        system_prompt="system",
        task_prompt="task",
        session_events=_session(task_prompt="task", observation=observation),
        broker_events=[event],
        broker_call_ids=["call-finish"],
        harness_identity=_identity(),
    )


def _v3_transcript() -> dict[str, Any]:
    repair = "VERIGYM_HWE_FORMAT_RECOVERY_V1: call a typed tool now"
    inspect_observation = "Candidate diff is bounded."
    finish_observation = "Candidate diff accepted."
    function_tools = [item["function"] for item in deepseek_harness_tool_definitions()]

    def header() -> dict[str, Any]:
        return {
            "type": "request/header",
            "data": {
                "header": {
                    "config": {
                        "provider": "deepseek-official",
                        "model": "deepseek-v4-flash",
                        "maxTokens": 2048,
                        "reasoningEffort": "off",
                        "temperature": 0,
                    },
                    "system": "system-v3",
                    "tools": function_tools,
                }
            },
        }

    events = [
        header(),
        {
            "type": "user/message",
            "data": {"message": {"content": [{"type": "text", "text": "task-v3"}]}},
        },
        {
            "type": "assistant/message",
            "data": {
                "message": {
                    "source": {"model": "deepseek-v4-flash"},
                    "content": [{"type": "text", "text": "unfinished public analysis"}],
                },
                "usage": {"inputTokens": 10, "outputTokens": 2048},
            },
        },
        {"type": "turn/end", "data": {"reason": {"kind": "max-tokens"}}},
        header(),
        {
            "type": "user/message",
            "data": {"message": {"content": [{"type": "text", "text": repair}]}},
        },
        {
            "type": "assistant/message",
            "data": {
                "message": {
                    "source": {"model": "deepseek-v4-flash"},
                    "content": [
                        {"type": "text", "text": "Correcting a rejected command."},
                        {
                            "type": "tool-call",
                            "id": "call-bad",
                            "name": "shell",
                            "arguments": '{"command":"echo bad > out"}',
                        },
                    ],
                },
                "usage": {"inputTokens": 20, "outputTokens": 20},
            },
        },
        {
            "type": "tool/result",
            "data": {
                "message": {
                    "source": {"callId": "call-bad"},
                    "content": [
                        {
                            "type": "tool-result",
                            "toolCallId": "call-bad",
                            "isError": True,
                            "content": [
                                {"type": "text", "text": "invalid_arguments: redirection denied"}
                            ],
                        }
                    ],
                }
            },
        },
        {
            "type": "assistant/message",
            "data": {
                "message": {
                    "source": {"model": "deepseek-v4-flash"},
                    "content": [
                        {"type": "text", "text": "The candidate is ready."},
                        {
                            "type": "tool-call",
                            "id": "call-diff",
                            "name": "inspect_diff",
                            "arguments": "{}",
                        },
                        {
                            "type": "tool-call",
                            "id": "call-finish-v3",
                            "name": "finish",
                            "arguments": '{"summary":"done"}',
                        },
                    ],
                },
                "usage": {"inputTokens": 30, "outputTokens": 30},
            },
        },
    ]
    for call_id, text in (
        ("call-diff", inspect_observation),
        ("call-finish-v3", finish_observation),
    ):
        events.append(
            {
                "type": "tool/result",
                "data": {
                    "message": {
                        "source": {"callId": call_id},
                        "content": [
                            {
                                "type": "tool-result",
                                "toolCallId": call_id,
                                "isError": False,
                                "content": [{"type": "text", "text": text}],
                            }
                        ],
                    }
                },
            }
        )
    events.append({"type": "turn/end", "data": {"reason": {"kind": "completed"}}})
    broker_events = [
        HweNormalizedEvent(
            sequence=0,
            action="inspect_diff",
            arguments={},
            workspace_epoch_before=0,
            workspace_epoch_after=0,
            compact_observation_sha256=__import__("hashlib")
            .sha256(inspect_observation.encode())
            .hexdigest(),
            event_mapping="deepseek_harness_native_tool",
        ),
        HweNormalizedEvent(
            sequence=1,
            action="finish",
            arguments={"summary": "done"},
            workspace_epoch_before=0,
            workspace_epoch_after=0,
            compact_observation_sha256=__import__("hashlib")
            .sha256(finish_observation.encode())
            .hexdigest(),
            event_mapping="deepseek_harness_native_tool",
        ),
    ]
    return build_deepseek_harness_transcript_v3(
        task_id=DEEPSEEK_HARNESS_PILOT_TASKS[0],
        system_prompt="system-v3",
        task_prompt="task-v3",
        session_events=events,
        broker_events=broker_events,
        broker_call_ids=["call-diff", "call-finish-v3"],
        harness_identity=_identity(),
        format_repair_prompts=[repair],
    )


def test_transcript_preserves_exact_six_tool_causality_and_rejects_prose() -> None:
    transcript = validate_deepseek_harness_transcript(_transcript())
    assert [item["function"]["name"] for item in transcript["tools"]] == [
        "apply_patch",
        "finish",
        "inspect_diff",
        "list_files",
        "read_file",
        "shell",
    ]
    assert [message["role"] for message in transcript["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert transcript["model_call_count"] == 1
    assert transcript["nap_required"] is False

    session = _session(task_prompt="task")
    session[2]["data"]["message"]["content"] = [{"type": "text", "text": "reasoning"}]
    with pytest.raises(ValueError, match="tool call"):
        build_deepseek_harness_transcript(
            task_id=DEEPSEEK_HARNESS_PILOT_TASKS[0],
            system_prompt="system",
            task_prompt="task",
            session_events=session,
            broker_events=[],
            broker_call_ids=[],
            harness_identity=_identity(),
        )


def test_exact_qwen_rows_mask_only_final_action_and_fail_closed_overlength(
    tmp_path: Path,
) -> None:
    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()
    (tokenizer_root / "tokenizer_config.json").write_text("{}\n", encoding="utf-8")
    exact = QwenActionExampleTokenizer(
        _StableTemplateTokenizer(),
        tokenizer_root=tokenizer_root,
    )
    transcript = set_deepseek_harness_verifier_result(_transcript(), verifier_resolved=True)
    binding = {
        "sample_id": "a" * 64,
        "task_hash": "b" * 64,
        "source_hash": "c" * 64,
        "candidate_hash": "d" * 64,
        "verifier_hash": "e" * 64,
    }
    examples = materialize_deepseek_harness_action_examples(
        transcript,
        binding=binding,
        tokenizer=exact,
    )
    assert len(examples) == 1
    assert examples[0]["eligible"] is True
    assert examples[0]["input_messages"] == transcript["messages"][:2]
    assert examples[0]["target_message"] == transcript["messages"][2]
    assert dry_run_action_record(examples[0], tokenizer=exact)["truncation_applied"] is False

    overlength = materialize_deepseek_harness_action_examples(
        transcript,
        binding=binding,
        tokenizer=_OverlengthCounter(),
    )
    manifest = build_deepseek_harness_dataset_manifest(
        overlength,
        pilot_task_ids=DEEPSEEK_HARNESS_PILOT_TASKS,
    )
    assert overlength[0]["eligible"] is False
    assert manifest["loader_ready"] is False
    assert manifest["overlength_records"][0]["token_count"] == 32_769
    assert manifest["production_training_ready"] is False
    assert manifest["hpc_jobs_submitted"] is False


def test_v3_retains_public_text_and_errors_but_supervises_only_valid_decisions(
    tmp_path: Path,
) -> None:
    transcript = validate_deepseek_harness_transcript_v3(_v3_transcript())
    assert transcript["assistant_decision_count"] == 3
    assert transcript["accepted_tool_action_count"] == 2
    assert transcript["supervised_decision_count"] == 1
    assert transcript["masked_policy_error_decision_count"] == 1
    assert transcript["masked_format_error_decision_count"] == 1
    assert transcript["format_repair_count"] == 1
    assert [item["supervised_target"] for item in transcript["assistant_decisions"]] == [
        False,
        False,
        True,
    ]
    assert any(message.get("error") is True for message in transcript["messages"])

    tokenizer_root = tmp_path / "tokenizer-v3"
    tokenizer_root.mkdir()
    (tokenizer_root / "tokenizer_config.json").write_text("{}\n", encoding="utf-8")
    tokenizer = QwenDecisionExampleTokenizer(
        _StableTemplateTokenizer(),
        tokenizer_root=tokenizer_root,
    )
    transcript = set_deepseek_harness_verifier_result_v3(
        transcript,
        verifier_resolved=True,
    )
    binding = {
        "sample_id": "a" * 64,
        "task_hash": "b" * 64,
        "source_hash": "c" * 64,
        "candidate_hash": "d" * 64,
        "verifier_hash": "e" * 64,
    }
    examples = materialize_deepseek_harness_decision_examples_v3(
        transcript,
        binding=binding,
        tokenizer=tokenizer,
    )
    assert len(examples) == 1
    assert examples[0]["decision_index"] == 2
    assert examples[0]["action_names"] == ["inspect_diff", "finish"]
    assert examples[0]["public_assistant_text_exported"] is True
    assert [message["role"] for message in examples[0]["input_messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "tool",
    ]
    assert dry_run_decision_record(examples[0], tokenizer=tokenizer)["truncation_applied"] is False
    manifest = build_deepseek_harness_dataset_manifest_v3(
        examples,
        pilot_task_ids=DEEPSEEK_HARNESS_PILOT_TASKS,
    )
    assert manifest["supervised_decision_count"] == 1
    assert manifest["supervised_tool_action_count"] == 2
    assert manifest["masked_policy_error_decision_count"] == 1
    assert manifest["masked_format_error_decision_count"] == 1
    assert manifest["format_repair_count"] == 1
    assert manifest["production_training_ready"] is False


def test_v3_overlength_decision_fails_closed() -> None:
    transcript = set_deepseek_harness_verifier_result_v3(
        _v3_transcript(),
        verifier_resolved=True,
    )
    examples = materialize_deepseek_harness_decision_examples_v3(
        transcript,
        binding={
            "sample_id": "1" * 64,
            "task_hash": "2" * 64,
            "source_hash": "3" * 64,
            "candidate_hash": "4" * 64,
            "verifier_hash": "5" * 64,
        },
        tokenizer=_OverlengthCounter(),
    )
    manifest = build_deepseek_harness_dataset_manifest_v3(
        examples,
        pilot_task_ids=DEEPSEEK_HARNESS_PILOT_TASKS,
    )
    assert examples[0]["eligible"] is False
    assert manifest["loader_ready"] is False


def test_transcript_hash_detects_mutation_and_unresolved_is_not_sft_eligible() -> None:
    transcript = _transcript()
    mutated = copy.deepcopy(transcript)
    mutated["messages"][1]["content"] = "changed"
    with pytest.raises(ValueError, match="identity changed"):
        validate_deepseek_harness_transcript(mutated)
    with pytest.raises(ValueError, match="verifier-passed"):
        materialize_deepseek_harness_action_examples(
            transcript,
            binding={
                key: "f" * 64
                for key in (
                    "sample_id",
                    "task_hash",
                    "source_hash",
                    "candidate_hash",
                    "verifier_hash",
                )
            },
            tokenizer=_OverlengthCounter(),
        )


def test_superseded_preflight_receipt_accepts_only_sealed_zero_model_call_failure(
    tmp_path: Path,
) -> None:
    base = {
        "status": "stopped_infrastructure_invalid",
        "attempts": [
            {
                "status": "infrastructure_invalid",
                "model_call_count": None,
                "action_record_count": 0,
                "normalized": False,
            }
        ],
    }
    report = tmp_path / "campaign-report.json"
    report.write_text(
        json.dumps({**base, "report_hash": content_hash(base)}),
        encoding="utf-8",
    )
    assert _zero_model_call_preflight_receipt(report) == content_hash(base)

    called = copy.deepcopy(base)
    called["attempts"][0]["model_call_count"] = 1
    report.write_text(
        json.dumps({**called, "report_hash": content_hash(called)}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="zero-model-call"):
        _zero_model_call_preflight_receipt(report)
