"""Trainable rLLM repository workflow backed by isolated VeriGym sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rllm.agents.agent import (  # type: ignore[import-not-found]
    Action,
    Episode,
    Step,
    Trajectory,
)
from rllm.engine import ModelOutput, RolloutEngine  # type: ignore[import-not-found]
from rllm.workflows.workflow import (  # type: ignore[import-not-found]
    TerminationEvent,
    TerminationReason,
    Workflow,
)

from .repository_broker_protocol import RepositoryBrokerClient
from .rllm_grpo_compat import activate_rllm_verl_grpo_group_compatibility


class VeriGymRepositoryWorkflow(Workflow):  # type: ignore[misc]
    """Run one-action-per-turn repository repair with on-policy token evidence."""

    def __init__(
        self,
        rollout_engine: RolloutEngine,
        *,
        repository_broker_root: str,
        broker_timeout_s: int = 3600,
        action_tokens: int | None = None,
        **kwargs: Any,
    ) -> None:
        if not activate_rllm_verl_grpo_group_compatibility():
            raise RuntimeError("rLLM-to-verl GRPO group bridge is unavailable in the Ray worker")
        super().__init__(rollout_engine, **kwargs)
        self.repository_broker_root = Path(repository_broker_root).resolve(strict=True)
        self.broker_timeout_s = broker_timeout_s
        self.action_tokens = action_tokens

    async def run(self, task: dict[str, Any], uid: str, **kwargs: Any) -> Episode:
        del kwargs
        self.reset(task, uid)
        if task.get("hidden_assets_included") is not False:
            raise RuntimeError("repository rollout task did not explicitly exclude hidden assets")
        if task.get("submission_kind") != "patch":
            raise RuntimeError("repository workflow requires a patch-submission public record")
        public_input_hash = task.get("record_hash")
        task_id = task.get("task_id")
        if not isinstance(public_input_hash, str) or not isinstance(task_id, str):
            raise RuntimeError("repository rollout task lacks its frozen public identity")
        client = RepositoryBrokerClient(
            self.repository_broker_root,
            task_id=task_id,
            public_input_hash=public_input_hash,
            uid=uid,
            seed=int(task.get("seed", 20260809)),
            sample_index=int(task.get("sample_index", 0)),
            timeout_s=self.broker_timeout_s,
        )
        initial = await self.run_in_executor(client.open)
        if initial.get("terminal") is True:
            self._require_valid_infrastructure(initial)
            raise RuntimeError("repository broker terminated before the first model action")
        maximum = initial.get("max_completion_calls")
        contract = initial.get("prompt_contract")
        observation = initial.get("observation")
        if not isinstance(maximum, int) or maximum < 1 or not isinstance(contract, dict):
            raise RuntimeError("repository broker omitted its frozen action contract")
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a bounded repository repair agent. Return exactly one JSON object "
                    "matching the supplied repository_action.v2 contract and no prose."
                ),
            },
            {
                "role": "user",
                "content": _json_message(
                    {
                        "task": {
                            "id": task_id,
                            "description": task.get("task_description"),
                            "submission_kind": "patch",
                        },
                        "prompt_contract": contract,
                        "public_test_ids": initial.get("public_test_ids", []),
                        "observation": observation,
                    }
                ),
            },
        ]
        steps: list[Step] = []
        terminal: dict[str, Any] | None = None
        for turn in range(maximum):
            generation_options: dict[str, Any] = {
                "application_id": f"{uid}:repository:{turn}",
            }
            if self.action_tokens is not None:
                generation_options["max_tokens"] = self.action_tokens
            model_output: ModelOutput = await self.rollout_engine.get_model_response(
                messages,
                **generation_options,
            )
            _validate_trainable_model_output(model_output)
            raw_action = model_output.content or model_output.text
            if not isinstance(raw_action, str) or not raw_action:
                raise RuntimeError("repository rollout model returned no trainable action text")
            response = await self.run_in_executor(client.act, turn, raw_action)
            is_terminal = response.get("terminal") is True
            reward = float(response.get("resolved") is True) if is_terminal else 0.0
            assistant_message = {"role": "assistant", "content": raw_action}
            steps.append(
                Step(
                    chat_completions=[*messages, assistant_message],
                    observation=response.get("observation"),
                    action=Action(action=raw_action),
                    model_response=raw_action,
                    reward=reward,
                    done=is_terminal,
                    model_output=model_output,
                    metadata={
                        "turn": turn,
                        "trainable": True,
                        "repository_action_protocol": "repository_action.v2",
                        "broker_response_hash": response["response_hash"],
                        "action_name": response.get("action_name"),
                        "protocol_error": response.get("protocol_error"),
                        "terminal": is_terminal,
                    },
                )
            )
            if is_terminal:
                self._require_valid_infrastructure(response)
                terminal = response
                break
            observation_message = {
                "role": "user",
                "content": _json_message(
                    {
                        "tool_observation": response.get("observation"),
                        "state": response.get("state"),
                        "turn": turn,
                    }
                ),
            }
            messages.extend([assistant_message, observation_message])
        if terminal is None:
            raise RuntimeError(
                "repository workflow exhausted its frozen turn budget without finish"
            )
        reward = float(terminal.get("resolved") is True)
        trajectory = Trajectory(
            name="verigym_repository_online_v1",
            task=task_id,
            input={"public_input_hash": public_input_hash},
            output={
                "resolved": terminal.get("resolved"),
                "termination_reason": terminal.get("termination_reason"),
                "candidate_hash": terminal.get("candidate_hash"),
            },
            reward=reward,
            steps=steps,
            metadata={
                "public_input_hash": public_input_hash,
                "repository_action_protocol": "repository_action.v2",
                "state_machine_id": contract.get("state_machine_id"),
                "hidden_assets_loaded_by_model": False,
                "reference_solution_loaded_by_model": False,
                "source_root_loaded_by_training_container": False,
                "docker_socket_loaded_by_training_container": False,
            },
        )
        self.commit(trajectory=trajectory)
        raise TerminationEvent(TerminationReason.ENV_DONE)

    @staticmethod
    def _require_valid_infrastructure(response: dict[str, Any]) -> None:
        if response.get("infrastructure_valid") is not True:
            raise RuntimeError("VeriGym repository broker reported infrastructure-invalid outcome")
        if response.get("resolved") not in {True, False}:
            raise RuntimeError("VeriGym repository broker omitted its binary task outcome")


def _json_message(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_trainable_model_output(output: ModelOutput) -> None:
    prompt_ids = output.prompt_ids
    completion_ids = output.completion_ids
    logprobs = output.logprobs
    if not prompt_ids or not completion_ids or logprobs is None:
        raise RuntimeError("repository rollout lacks on-policy token IDs or logprobs")
    if len(completion_ids) != len(logprobs):
        raise RuntimeError("repository rollout completion IDs and logprobs are misaligned")


__all__ = ["VeriGymRepositoryWorkflow"]
