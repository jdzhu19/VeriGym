"""rLLM-native multi-turn repository workflow backed by an isolated broker."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from rllm.agents.agent import Action, BaseAgent, Step, Trajectory  # type: ignore[import-not-found]
from rllm.engine import ModelOutput, RolloutEngine  # type: ignore[import-not-found]
from rllm.environments.base.base_env import BaseEnv  # type: ignore[import-not-found]
from rllm.workflows.multi_turn_workflow import (  # type: ignore[import-not-found]
    MultiTurnWorkflow,
)
from rllm.workflows.workflow import (  # type: ignore[import-not-found]
    TerminationEvent,
    TerminationReason,
)
from verigym.protocols.repository_action import (
    canonical_action_json,
    canonical_tool_observation,
    repository_tool_definitions,
)

from .repository_broker_protocol import RepositoryBrokerClient, await_model_or_terminal
from .repository_context import repository_native_tool_messages


class VeriGymRepositoryAgent(BaseAgent):  # type: ignore[misc]
    """Own OpenAI-style messages and trainable rLLM Steps, but no scheduling loop."""

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []
        self._trajectory = Trajectory(name="verigym_repository_online_v2")
        self._model_output: ModelOutput | None = None
        self._pending_step: Step | None = None
        self._turn = 0
        self._task: dict[str, Any] | None = None

    @property
    def chat_completions(self) -> list[dict[str, Any]]:
        return [dict(message) for message in self._messages]

    @property
    def trajectory(self) -> Trajectory:
        return self._trajectory

    @property
    def turn(self) -> int:
        return self._turn

    def bind_model_output(self, output: ModelOutput) -> None:
        if self._model_output is not None:
            raise RuntimeError("repository agent already has an unconsumed ModelOutput")
        _validate_trainable_model_output(output)
        self._model_output = output

    def update_from_env(
        self,
        observation: Any,
        reward: float,
        done: bool,
        info: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        del kwargs
        if info.get("initial") is True:
            task = info.get("task")
            contract = info.get("prompt_contract")
            if not isinstance(task, dict) or not isinstance(contract, dict):
                raise RuntimeError("repository environment omitted its initial public contract")
            self._task = task
            task_id = task.get("task_id")
            if not isinstance(task_id, str):
                raise RuntimeError("repository rollout task lacks a task ID")
            self._messages = repository_native_tool_messages(
                task_id=task_id,
                task_description=task.get("task_description"),
                contract=contract,
                public_test_ids=info.get("public_test_ids", []),
                observation=observation,
                broker_observation_truncated=info.get("observation_truncated") is True,
            )
            self._trajectory.task = task_id
            self._trajectory.input = {"public_input_hash": task.get("record_hash")}
            self._trajectory.metadata = {
                "repository_action_protocol": "repository_action.v2",
                "state_machine_id": contract.get("state_machine_id"),
                "hidden_assets_loaded_by_model": False,
                "reference_solution_loaded_by_model": False,
                "source_root_loaded_by_training_process": False,
                "docker_socket_loaded_by_training_process": False,
            }
            return
        if self._pending_step is None:
            raise RuntimeError("repository environment returned a result without a model action")
        call = self._pending_call()
        observation_text = observation if isinstance(observation, str) else json.dumps(observation)
        tool_message = {
            "role": "tool",
            "tool_call_id": call["id"],
            "name": call["function"]["name"],
            "content": observation_text,
        }
        self._messages.append(tool_message)
        self._pending_step.observation = observation_text
        self._pending_step.reward = reward
        self._pending_step.done = done
        self._pending_step.output = info
        self._pending_step.metadata = {
            **(self._pending_step.metadata or {}),
            "broker_response_hash": info.get("response_hash"),
            "action_name": info.get("action_name"),
            "protocol_error": info.get("protocol_error"),
            "terminal": done,
        }
        self._pending_step = None
        if done:
            self._trajectory.output = {
                "resolved": info.get("resolved"),
                "termination_reason": info.get("termination_reason"),
                "candidate_hash": info.get("candidate_hash"),
            }
            self._trajectory.reward = reward

    def update_from_model(self, response: str, **kwargs: Any) -> Action:
        del response, kwargs
        output = self._model_output
        self._model_output = None
        if output is None:
            raise RuntimeError("repository agent did not receive the complete ModelOutput")
        calls = output.tool_calls or []
        if len(calls) != 1:
            raise RuntimeError("Qwen repository rollout must emit exactly one native tool call")
        call = calls[0]
        if not isinstance(call.name, str) or not isinstance(call.arguments, dict):
            raise RuntimeError("Qwen repository tool call is malformed")
        raw_action = canonical_action_json(call.name, call.arguments)
        envelope = json.loads(raw_action)
        arguments = envelope["arguments"]
        call_id = _tool_call_id(self._turn, call.name, arguments)
        assistant_message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
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
        step = Step(
            chat_completions=[*self._messages, assistant_message],
            action=Action(
                action={
                    "id": call_id,
                    "name": call.name,
                    "arguments": arguments,
                    "raw_action": raw_action,
                }
            ),
            model_response=output.text or output.content or "",
            model_output=output,
            metadata={
                "turn": self._turn,
                "trainable": True,
                "repository_action_protocol": "repository_action.v2",
                "tool_call_id": call_id,
            },
        )
        self._messages.append(assistant_message)
        self._trajectory.steps.append(step)
        self._pending_step = step
        self._turn += 1
        return step.action

    def reset(self) -> None:
        self._messages = []
        self._trajectory = Trajectory(name="verigym_repository_online_v2")
        self._model_output = None
        self._pending_step = None
        self._turn = 0
        self._task = None

    def _pending_call(self) -> dict[str, Any]:
        if not self._messages:
            raise RuntimeError("repository agent has no pending assistant tool call")
        calls = self._messages[-1].get("tool_calls")
        if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
            raise RuntimeError("repository agent pending tool call changed")
        return calls[0]


class VeriGymBrokerEnvironment(BaseEnv):  # type: ignore[misc]
    """Expose the existing immutable broker protocol as an rLLM BaseEnv."""

    def __init__(
        self,
        *,
        repository_broker_root: str,
        broker_timeout_s: int = 3900,
        terminal_poll_interval_s: float = 0.05,
    ) -> None:
        if broker_timeout_s <= 0 or terminal_poll_interval_s <= 0:
            raise ValueError("repository broker timeouts must be positive")
        self.repository_broker_root = Path(repository_broker_root).resolve(strict=True)
        self.broker_timeout_s = broker_timeout_s
        self.terminal_poll_interval_s = terminal_poll_interval_s
        self._uid: str | None = None
        self._client: RepositoryBrokerClient | None = None
        self._turn = 0
        self._terminal: dict[str, Any] | None = None
        self.max_completion_calls: int | None = None

    def bind_uid(self, uid: str) -> None:
        if not uid:
            raise ValueError("repository rollout UID must be non-empty")
        self._uid = uid

    def reset(self, task: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
        if not isinstance(task, dict):
            raise RuntimeError("repository environment requires a public task record")
        if task.get("hidden_assets_included") is not False:
            raise RuntimeError("repository rollout task did not explicitly exclude hidden assets")
        if task.get("submission_kind") != "patch":
            raise RuntimeError("repository workflow requires a patch-submission public record")
        task_id = task.get("task_id")
        public_input_hash = task.get("record_hash")
        if not isinstance(task_id, str) or not isinstance(public_input_hash, str):
            raise RuntimeError("repository rollout task lacks its frozen public identity")
        if self._uid is None:
            raise RuntimeError("repository environment has no bound rollout UID")
        self._client = RepositoryBrokerClient(
            self.repository_broker_root,
            task_id=task_id,
            public_input_hash=public_input_hash,
            uid=self._uid,
            seed=int(task.get("seed", 20260809)),
            sample_index=int(task.get("sample_index", 0)),
            timeout_s=self.broker_timeout_s,
        )
        self._turn = 0
        self._terminal = None
        initial = self._client.open()
        if initial.get("terminal") is True:
            self._accept_terminal(initial)
            raise RuntimeError("repository broker terminated before the first model action")
        maximum = initial.get("max_completion_calls")
        contract = initial.get("prompt_contract")
        if not isinstance(maximum, int) or maximum < 1 or not isinstance(contract, dict):
            raise RuntimeError("repository broker omitted its frozen action contract")
        self.max_completion_calls = maximum
        return initial.get("observation"), {
            "initial": True,
            "task": task,
            "prompt_contract": contract,
            "public_test_ids": initial.get("public_test_ids", []),
            "observation_truncated": initial.get("observation_truncated") is True,
            "response_hash": initial.get("response_hash"),
        }

    def step(self, action: Any) -> tuple[str, float, bool, dict[str, Any]]:
        client = self._require_client()
        payload = action.action if isinstance(action, Action) else action
        if not isinstance(payload, dict):
            raise RuntimeError("repository environment received a malformed rLLM Action")
        name = payload.get("name")
        raw_action = payload.get("raw_action")
        if not isinstance(name, str) or not isinstance(raw_action, str):
            raise RuntimeError("repository environment action lacks canonical serialization")
        response = client.act(self._turn, raw_action)
        self._turn += 1
        done = response.get("terminal") is True
        if done:
            self._accept_terminal(response)
        reward = float(response.get("resolved") is True) if done else 0.0
        observation = canonical_tool_observation(
            name,
            {
                "accepted": response.get("accepted"),
                "state": response.get("state"),
                "protocol_error": response.get("protocol_error"),
                "observation": response.get("observation"),
                "terminal": done,
            },
            is_error=response.get("accepted") is False,
        )
        return observation, reward, done, dict(response)

    async def wait_for_terminal(self) -> dict[str, Any]:
        client = self._require_client()
        deadline = asyncio.get_running_loop().time() + self.broker_timeout_s
        while True:
            terminal = client.poll_terminal()
            if terminal is not None:
                self._accept_terminal(terminal)
                return terminal
            if (client.root / "STOP").is_file():
                raise RuntimeError("repository broker stopped without publishing a terminal")
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("repository broker terminal grace period expired")
            await asyncio.sleep(self.terminal_poll_interval_s)

    def close(self) -> None:
        self._client = None

    @staticmethod
    def from_dict(info: dict[str, Any]) -> VeriGymBrokerEnvironment:
        return VeriGymBrokerEnvironment(**info)

    @staticmethod
    def is_multithread_safe() -> bool:
        return True

    def _require_client(self) -> RepositoryBrokerClient:
        if self._client is None:
            raise RuntimeError("repository broker environment has not been reset")
        return self._client

    def _accept_terminal(self, response: dict[str, Any]) -> None:
        if response.get("infrastructure_valid") is not True:
            raise RuntimeError("VeriGym repository broker reported infrastructure-invalid outcome")
        if response.get("resolved") not in {True, False}:
            raise RuntimeError("VeriGym repository broker omitted its binary task outcome")
        self._terminal = dict(response)


class VeriGymRepositoryWorkflow(MultiTurnWorkflow):  # type: ignore[misc]
    """Keep the historical entry point while delegating the loop to upstream rLLM."""

    def __init__(
        self,
        rollout_engine: RolloutEngine,
        *,
        repository_broker_root: str,
        broker_timeout_s: int = 3900,
        terminal_poll_interval_s: float = 0.05,
        action_tokens: int | None = None,
        max_steps: int = 128,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("timeout", 4200)
        if float(kwargs["timeout"]) <= broker_timeout_s:
            raise ValueError("repository workflow timeout must exceed the broker terminal grace")
        self.action_tokens = action_tokens
        self._configured_max_steps = max_steps
        super().__init__(
            rollout_engine=rollout_engine,
            agent_cls=VeriGymRepositoryAgent,
            env_cls=VeriGymBrokerEnvironment,
            env_args={
                "repository_broker_root": repository_broker_root,
                "broker_timeout_s": broker_timeout_s,
                "terminal_poll_interval_s": terminal_poll_interval_s,
            },
            max_steps=max_steps,
            **kwargs,
        )

    def reset(
        self, task: dict[str, Any] | None = None, uid: str | None = None
    ) -> tuple[Any, dict[Any, Any]]:
        if uid is None:
            raise RuntimeError("repository workflow requires a rollout UID")
        self.agent.reset()
        self.env.bind_uid(uid)
        observation, info = super().reset(task, uid)
        if not isinstance(info, dict):
            raise RuntimeError("repository environment reset info must be an object")
        if self.env.max_completion_calls is None:
            raise RuntimeError("repository environment omitted its completion-call limit")
        self.max_steps = min(self._configured_max_steps, self.env.max_completion_calls)
        return observation, info

    async def timed_llm_call(self, *args: Any, **kwargs: Any) -> ModelOutput:
        requested_tools = kwargs.pop("tools", None)
        tools = repository_tool_definitions(dialect="openai")
        if requested_tools is not None and requested_tools != tools:
            raise RuntimeError("repository workflow refuses a second tool contract")
        kwargs["tools"] = tools
        kwargs["application_id"] = f"{kwargs['application_id']}:repository:{self.agent.turn}"
        if self.action_tokens is not None:
            kwargs["max_tokens"] = self.action_tokens
        terminal_task = asyncio.create_task(self.env.wait_for_terminal())
        try:
            output, terminal = await await_model_or_terminal(
                super().timed_llm_call(*args, **kwargs), terminal_task
            )
        finally:
            if not terminal_task.done():
                terminal_task.cancel()
            await asyncio.gather(terminal_task, return_exceptions=True)
        if terminal is not None:
            raise TerminationEvent(TerminationReason.ENV_DONE)
        if output is None:
            raise RuntimeError("repository rollout returned no ModelOutput")
        self.agent.bind_model_output(output)
        return output


def _tool_call_id(turn: int, name: str, arguments: dict[str, Any]) -> str:
    value = json.dumps(
        {"turn": turn, "name": name, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "call_" + hashlib.sha256(value.encode()).hexdigest()[:24]


def _validate_trainable_model_output(output: ModelOutput) -> None:
    if not output.prompt_ids or not output.completion_ids or output.logprobs is None:
        raise RuntimeError("repository rollout lacks on-policy token IDs or logprobs")
    if len(output.completion_ids) != len(output.logprobs):
        raise RuntimeError("repository rollout completion IDs and logprobs are misaligned")


__all__ = [
    "VeriGymBrokerEnvironment",
    "VeriGymRepositoryAgent",
    "VeriGymRepositoryWorkflow",
]
