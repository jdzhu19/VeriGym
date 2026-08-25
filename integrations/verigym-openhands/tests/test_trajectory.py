from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from verigym.core.hashing import content_hash
from verigym.core.repository_tool_broker import RepositoryToolBrokerTurn
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions
from verigym.hwe.qwen_action_tokenizer import QwenDecisionExampleTokenizer
from verigym.hwe.trajectory import HweNormalizedEvent
from verigym.protocols.repository_action import repository_tool_definitions

from verigym_openhands.trajectory import (
    OpenHandsTrajectoryError,
    OpenHandsTrajectoryInfrastructureError,
    build_openhands_training_trajectory,
    hwe_broker_receipts,
    materialize_openhands_decisions,
    repository_broker_receipts,
    set_openhands_verifier_result,
    validate_openhands_training_trajectory,
    write_openhands_decision_dataset,
)


class _Tokenizer:
    chat_template = "test-prefix-stable-tool-template-v1"

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
        prefix = json.dumps(tools, sort_keys=True, separators=(",", ":")) + "\n"
        return prefix + "".join(
            json.dumps(message, sort_keys=True, separators=(",", ":")) + "\n"
            for message in conversation
        )

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        assert add_special_tokens is False
        return list(text.encode())


def _tokenizer(tmp_path: Path) -> QwenDecisionExampleTokenizer:
    root = tmp_path / "tokenizer"
    root.mkdir()
    (root / "tokenizer.json").write_text("{}\n", encoding="utf-8")
    (root / "tokenizer_config.json").write_text("{}\n", encoding="utf-8")
    return QwenDecisionExampleTokenizer(_Tokenizer(), tokenizer_root=root)


def _tools() -> list[dict[str, Any]]:
    tools = copy.deepcopy(repository_tool_definitions(dialect="openai"))
    for tool in tools:
        parameters = tool["function"]["parameters"]
        parameters.setdefault("properties", {})["summary"] = {
            "default": None,
            "type": ["string", "null"],
        }
    return tools


def _message(role: str, content: str) -> dict[str, Any]:
    return {
        "role": role,
        "content": [{"type": "text", "text": content}],
        "tool_calls": None,
        "tool_call_id": None,
        "name": None,
        "reasoning_content": None,
        "thinking_blocks": [],
        "responses_reasoning_item": None,
    }


def _action(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    arguments_json = json.dumps(arguments, separators=(",", ":"), ensure_ascii=False)
    return {
        "event_type": "ActionEvent",
        "event_id": f"event-{call_id}",
        "parent_id": None,
        "source": "agent",
        "message": {
            "role": "assistant",
            "content": [],
            "tool_calls": [
                {
                    "id": call_id,
                    "name": name,
                    "arguments": arguments_json,
                    "origin": "completion",
                }
            ],
            "tool_call_id": None,
            "name": None,
            "reasoning_content": None,
            "thinking_blocks": [],
            "responses_reasoning_item": None,
        },
        "tool_name": name,
        "tool_call_id": call_id,
        "llm_response_id": f"response-{call_id}",
        "reasoning_content_present": False,
        "thinking_blocks_present": False,
        "responses_reasoning_present": False,
        "critic_present": False,
    }


def _observation(call_id: str, name: str, content: str) -> dict[str, Any]:
    message = _message("tool", content)
    message["content"] = [
        {"type": "text", "text": f"[Tool '{name}' executed.]"},
        {"type": "text", "text": content},
    ]
    message["tool_call_id"] = call_id
    message["name"] = name
    return {
        "event_type": "ObservationEvent",
        "event_id": f"observation-{call_id}",
        "parent_id": f"event-{call_id}",
        "source": "environment",
        "message": message,
        "tool_name": name,
        "tool_call_id": call_id,
        "action_id": f"event-{call_id}",
        "extended_content_present": False,
    }


def _episode(
    *, system_text: str = "Bounded repository repair system."
) -> tuple[list[dict[str, Any]], tuple[RepositoryToolBrokerTurn, ...]]:
    list_observation = '{"entries":["TASK.md"]}'
    finish_observation = '{"accepted":true,"terminal":true}'
    snapshots = [
        {
            "event_type": "SystemPromptEvent",
            "event_id": "system",
            "parent_id": None,
            "source": "agent",
            "message": _message("system", system_text),
            "dynamic_context_present": False,
        },
        {
            "event_type": "MessageEvent",
            "event_id": "user",
            "parent_id": "system",
            "source": "user",
            "message": _message("user", "Repair the visible task."),
            "activated_skills": [],
            "extended_content_present": False,
            "critic_present": False,
        },
        _action("call-list", "list_files", {"path": ".", "summary": "inspect files"}),
        _observation("call-list", "list_files", list_observation),
        _action(
            "call-finish",
            "finish",
            {"message": "done", "summary": "submit candidate"},
        ),
        _observation("call-finish", "finish", finish_observation),
    ]
    turns = (
        RepositoryToolBrokerTurn(
            tool_name="list_files",
            arguments_json='{"path":".","recursive":true}',
            observation_json=list_observation,
        ),
        RepositoryToolBrokerTurn(
            tool_name="finish",
            arguments_json='{"message":"done"}',
            observation_json=finish_observation,
        ),
    )
    return snapshots, turns


def _trajectory(*, system_text: str = "Bounded repository repair system.") -> dict[str, Any]:
    snapshots, turns = _episode(system_text=system_text)
    return build_openhands_training_trajectory(
        task_id="suite/repository/task-1",
        provider="openai-compatible",
        model_id="local/Qwen3.5-9B",
        configuration_fingerprint=content_hash({"configuration": "frozen"}),
        event_snapshots=snapshots,
        tools=_tools(),
        broker_turns=repository_broker_receipts(turns),
        tool_contract="repository_action.v2",
    )


def _binding() -> dict[str, str]:
    return {
        key: content_hash({"binding": key})
        for key in ("sample_id", "task_hash", "source_hash", "candidate_hash", "verifier_hash")
    }


def test_exact_openhands_trajectory_to_decision_dataset_round_trip(tmp_path: Path) -> None:
    pending = _trajectory()
    assert pending["verifier_resolved"] is False
    assert pending["sft_eligible"] is False
    assert pending["assistant_decision_count"] == 2
    assert pending["tools"][0]["function"]["parameters"]["properties"]["summary"]

    resolved = set_openhands_verifier_result(pending, verifier_resolved=True)
    tokenizer = _tokenizer(tmp_path)
    records = materialize_openhands_decisions(
        resolved,
        binding=_binding(),
        tokenizer=tokenizer,
    )

    assert len(records) == 2
    assert records[0]["target_message"]["tool_calls"][0]["function"]["arguments"] == (
        '{"path":".","summary":"inspect files"}'
    )
    assert records[0]["loss_mask_sha256"]
    assert records[1]["input_messages"][-1]["role"] == "tool"

    output = tmp_path / "dataset"
    manifest = write_openhands_decision_dataset(records, tokenizer=tokenizer, output=output)
    assert manifest["record_count"] == 2
    assert manifest["only_verifier_resolved"] is True
    assert manifest["production_training_ready"] is False
    assert (output / "train.jsonl").read_text(encoding="utf-8").count("\n") == 2


def test_unresolved_openhands_trajectory_cannot_enter_sft(tmp_path: Path) -> None:
    with pytest.raises(OpenHandsTrajectoryError, match="only verifier-passed"):
        materialize_openhands_decisions(
            _trajectory(),
            binding=_binding(),
            tokenizer=_tokenizer(tmp_path),
        )


def test_openhands_broker_argument_drift_fails_as_infrastructure() -> None:
    snapshots, turns = _episode()
    changed = list(turns)
    changed[0] = RepositoryToolBrokerTurn(
        tool_name="list_files",
        arguments_json='{"path":"src"}',
        observation_json=turns[0].observation_json,
    )
    with pytest.raises(OpenHandsTrajectoryInfrastructureError, match="broker semantics"):
        build_openhands_training_trajectory(
            task_id="suite/repository/task-1",
            provider="openai-compatible",
            model_id="local/Qwen3.5-9B",
            configuration_fingerprint=content_hash({"configuration": "frozen"}),
            event_snapshots=snapshots,
            tools=_tools(),
            broker_turns=repository_broker_receipts(changed),
            tool_contract="repository_action.v2",
        )


def test_openhands_private_reasoning_and_dynamic_context_fail_closed() -> None:
    snapshots, turns = _episode()
    snapshots[2]["reasoning_content_present"] = True
    with pytest.raises(OpenHandsTrajectoryError, match="private reasoning"):
        build_openhands_training_trajectory(
            task_id="suite/repository/task-1",
            provider="openai-compatible",
            model_id="local/Qwen3.5-9B",
            configuration_fingerprint=content_hash({"configuration": "frozen"}),
            event_snapshots=snapshots,
            tools=_tools(),
            broker_turns=repository_broker_receipts(turns),
            tool_contract="repository_action.v2",
        )

    snapshots, turns = _episode()
    snapshots[0]["dynamic_context_present"] = True
    with pytest.raises(OpenHandsTrajectoryError, match="system prompt"):
        build_openhands_training_trajectory(
            task_id="suite/repository/task-1",
            provider="openai-compatible",
            model_id="local/Qwen3.5-9B",
            configuration_fingerprint=content_hash({"configuration": "frozen"}),
            event_snapshots=snapshots,
            tools=_tools(),
            broker_turns=repository_broker_receipts(turns),
            tool_contract="repository_action.v2",
        )


def test_openhands_missing_tool_or_finish_fails_closed() -> None:
    snapshots, turns = _episode()
    with pytest.raises(OpenHandsTrajectoryError, match="six tool schemas"):
        build_openhands_training_trajectory(
            task_id="suite/repository/task-1",
            provider="openai-compatible",
            model_id="local/Qwen3.5-9B",
            configuration_fingerprint=content_hash({"configuration": "frozen"}),
            event_snapshots=snapshots,
            tools=_tools()[:-1],
            broker_turns=repository_broker_receipts(turns),
            tool_contract="repository_action.v2",
        )

    with pytest.raises(OpenHandsTrajectoryError, match="typed finish"):
        build_openhands_training_trajectory(
            task_id="suite/repository/task-1",
            provider="openai-compatible",
            model_id="local/Qwen3.5-9B",
            configuration_fingerprint=content_hash({"configuration": "frozen"}),
            event_snapshots=snapshots[:-2],
            tools=_tools(),
            broker_turns=repository_broker_receipts(turns[:-1]),
            tool_contract="repository_action.v2",
        )


def test_openhands_hash_and_overlength_drift_fail_closed(tmp_path: Path) -> None:
    trajectory = _trajectory()
    changed = copy.deepcopy(trajectory)
    changed["messages"][0]["content"] = "changed"
    with pytest.raises(OpenHandsTrajectoryError, match="identity changed"):
        validate_openhands_training_trajectory(changed)

    long = set_openhands_verifier_result(
        _trajectory(system_text="x" * 70_000), verifier_resolved=True
    )
    with pytest.raises(OpenHandsTrajectoryError, match="exceeds 65536"):
        materialize_openhands_decisions(
            long,
            binding=_binding(),
            tokenizer=_tokenizer(tmp_path),
        )


def test_hwe_native_shell_openhands_metadata_binds_to_broker() -> None:
    shell_observation = "exit_code=0\nrtl/core/csr_regfile.sv"
    finish_observation = "Candidate diff inspected."
    snapshots = [
        {
            "event_type": "SystemPromptEvent",
            "event_id": "system",
            "parent_id": None,
            "source": "agent",
            "message": _message("system", "Bounded HWE repair system."),
            "dynamic_context_present": False,
        },
        {
            "event_type": "MessageEvent",
            "event_id": "user",
            "parent_id": "system",
            "source": "user",
            "message": _message("user", "Repair TASK.md."),
            "activated_skills": [],
            "extended_content_present": False,
            "critic_present": False,
        },
        _action(
            "call-shell",
            "shell",
            {"command": "rg -n csr_regfile rtl", "cwd": ".", "summary": "locate CSR"},
        ),
        _observation("call-shell", "shell", shell_observation),
        _action("call-finish", "finish", {"summary": "validated candidate"}),
        _observation("call-finish", "finish", finish_observation),
    ]
    events = (
        HweNormalizedEvent(
            sequence=0,
            action="shell",
            arguments={"command": "rg -n csr_regfile rtl", "cwd": "."},
            workspace_epoch_before=0,
            workspace_epoch_after=0,
            compact_observation_sha256=hashlib.sha256(shell_observation.encode()).hexdigest(),
        ),
        HweNormalizedEvent(
            sequence=1,
            action="finish",
            arguments={"summary": "validated candidate"},
            workspace_epoch_before=0,
            workspace_epoch_after=0,
            compact_observation_sha256=hashlib.sha256(finish_observation.encode()).hexdigest(),
        ),
    )
    tools = copy.deepcopy(deepseek_harness_tool_definitions())
    for tool in tools:
        if tool["function"]["name"] != "finish":
            tool["function"]["parameters"]["properties"]["summary"] = {
                "default": None,
                "type": ["string", "null"],
            }

    trajectory = build_openhands_training_trajectory(
        task_id="hwe-bench/repo-repair-v1/task-1",
        provider="openai-compatible",
        model_id="local/Qwen3.5-9B",
        configuration_fingerprint=content_hash({"configuration": "hwe-frozen"}),
        event_snapshots=snapshots,
        tools=tools,
        broker_turns=hwe_broker_receipts(events, ("call-shell", "call-finish")),
        tool_contract="hwe_native_shell_v2",
    )

    assert trajectory["tool_contract"] == "hwe_native_shell_v2"
    assert trajectory["assistant_decisions"][0]["tool_name"] == "shell"
    arguments = trajectory["messages"][2]["tool_calls"][0]["function"]["arguments"]
    assert arguments.endswith('"summary":"locate CSR"}')
