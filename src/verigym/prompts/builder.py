"""Deterministic ChatEval and ReAct prompts with an explicit visibility boundary."""

from __future__ import annotations

import json
from typing import Any

from verigym.core.hashing import content_hash
from verigym.schemas.agent import Observation
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import MemoryPack
from verigym.schemas.model import ModelMessage
from verigym.schemas.prompt import PromptPolicyDescriptor
from verigym.schemas.task import VeriTask

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "file.list": {"path": "string", "recursive": "boolean"},
    "file.read": {"path": "string"},
    "file.search": {"query": "string", "path": "string", "glob": "string"},
    "file.apply_patch": {"patch": "unified diff string"},
    "file.diff": {},
    "iverilog.simulate_visible": {
        "sources": ["relative source path"],
        "top": "top module name",
        "pass_marker": "string",
        "fail_marker": "string",
    },
}


class PromptBuilder:
    """Build stable model messages without hidden assets or runtime paths."""

    VERSION = "1.0.0"

    def __init__(
        self,
        mode: InteractionMode,
        *,
        descriptor: PromptPolicyDescriptor | None = None,
        memory_pack: MemoryPack | None = None,
    ) -> None:
        if mode not in {InteractionMode.CHAT, InteractionMode.AGENT}:
            raise ValueError(f"no Milestone 5 prompt policy for mode {mode.value}")
        self.mode = mode
        policy_config = {
            "mode": mode.value,
            "version": self.VERSION,
            "action_protocol": "strict-json-v1" if mode == InteractionMode.AGENT else None,
            "tool_schemas": _TOOL_SCHEMAS if mode == InteractionMode.AGENT else {},
        }
        default_descriptor = PromptPolicyDescriptor(
            id="verigym-chat-v1" if mode == InteractionMode.CHAT else "verigym-react-v1",
            version=self.VERSION,
            interaction_mode=mode,
            configuration_fingerprint=content_hash(policy_config),
        )
        self.descriptor = descriptor or default_descriptor
        if self.descriptor.interaction_mode != mode:
            raise ValueError("prompt descriptor interaction mode differs from its builder")
        self._memory_pack = self._validated_memory(memory_pack)

    def initial_messages(self, task: VeriTask, observation: Observation) -> list[ModelMessage]:
        if self.mode == InteractionMode.CHAT:
            return self._chat_messages(task, observation)
        return self._react_messages(task, observation)

    def observation_message(
        self,
        observation: Observation,
        *,
        parser_feedback: str | None = None,
    ) -> ModelMessage:
        payload = self._observation_payload(observation)
        if parser_feedback is not None:
            payload["parser_feedback"] = parser_feedback
        return ModelMessage(
            role="user",
            content="Visible environment update:\n"
            + json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        )

    def _chat_messages(self, task: VeriTask, observation: Observation) -> list[ModelMessage]:
        system = ModelMessage(
            role="system",
            content=(
                "You are completing a bounded RTL generation task. Return exactly one candidate "
                "for the declared entrypoint, either as raw Verilog/SystemVerilog source or as one "
                "fenced verilog/systemverilog block. Do not include multiple candidate blocks. "
                "Inaccessible hidden verifier assets must not be requested, inferred, or "
                "reproduced."
            ),
        )
        payload = {
            "task_id": task.id,
            "title": task.title,
            "description": task.description,
            "entrypoints": sorted(task.workspace.entrypoints),
            "submission": {
                "kind": task.interaction.final_submission.kind,
                "accepted_formats": ["raw RTL source", "one fenced verilog block"],
            },
            "visible_files": sorted(observation.visible_files),
            "selected_files": {
                key: observation.selected_files[key] for key in sorted(observation.selected_files)
            },
            "policy_reminders": list(observation.policy_reminders),
        }
        return [
            system,
            ModelMessage(
                role="user",
                content=json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            ),
        ]

    def _react_messages(self, task: VeriTask, observation: Observation) -> list[ModelMessage]:
        allowed_tools = sorted(
            tool
            for tool in task.interaction.allowed_tools
            if tool not in task.interaction.denied_tools
        )
        tool_schemas = {tool: _TOOL_SCHEMAS.get(tool, {}) for tool in allowed_tools}
        system_content = (
            "You are the VeriGym reference ReAct agent. Respond with exactly one JSON object "
            "and no markdown. Valid tagged actions are: "
            '{"type":"tool_call","tool":"...","arguments":{...}}, '
            '{"type":"apply_patch","patch":"..."}, '
            '{"type":"final","message":"..."}, or '
            '{"type":"abort","reason":"..."}. '
            "Unknown fields and action types are invalid. Never emit shell commands or private "
            "reasoning. Hidden verifier assets are inaccessible and must not be requested, "
            "inferred, or reproduced."
        )
        if self._memory_pack is not None:
            memory_artifact = {
                "schema_version": "1.0",
                "label": "frozen_task_independent_read_only_agent_memory",
                "content_hash": self._memory_pack.content_hash,
                "read_only": True,
                "must_not_write_to_candidate_workspace": True,
                "sections": [
                    {"section": section.section, "items": section.items}
                    for section in self._memory_pack.sections
                ],
            }
            system_content += (
                "\nUse this frozen task-independent memory as general process guidance only. "
                "It is read-only and must not be copied into the candidate workspace:\n"
                + json.dumps(memory_artifact, sort_keys=True, ensure_ascii=False)
            )
        system = ModelMessage(role="system", content=system_content)
        payload = {
            "task_id": task.id,
            "title": task.title,
            "description": task.description,
            "entrypoints": sorted(task.workspace.entrypoints),
            "allowed_tools": allowed_tools,
            "tool_schemas": tool_schemas,
            "initial_observation": self._observation_payload(observation),
        }
        return [
            system,
            ModelMessage(
                role="user",
                content=json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            ),
        ]

    def _validated_memory(self, memory_pack: MemoryPack | None) -> MemoryPack | None:
        expected_hash = self.descriptor.memory_pack_hash
        if memory_pack is None:
            if expected_hash is not None:
                raise ValueError("memory-bearing prompt descriptor requires its frozen memory pack")
            return None
        if self.mode != InteractionMode.AGENT:
            raise ValueError("versioned agent memory is supported only in AgentEval")
        from verigym.evolution.memory import validate_memory_pack

        memory = validate_memory_pack(memory_pack)
        if expected_hash != memory.content_hash:
            raise ValueError("prompt descriptor and frozen memory pack identities differ")
        return memory

    @staticmethod
    def _observation_payload(observation: Observation) -> dict[str, Any]:
        return {
            "task_id": observation.task_id,
            "task_description": observation.task_description,
            "visible_files": sorted(observation.visible_files),
            "selected_files": {
                key: observation.selected_files[key] for key in sorted(observation.selected_files)
            },
            "previous_tool_result": (
                observation.previous_tool_result.model_dump(mode="json")
                if observation.previous_tool_result
                else None
            ),
            "remaining_budget": observation.remaining_budget.model_dump(mode="json"),
            "diff_summary": observation.diff_summary,
            "policy_reminders": list(observation.policy_reminders),
            "episode_status": observation.episode_status,
            "message": observation.message,
        }
