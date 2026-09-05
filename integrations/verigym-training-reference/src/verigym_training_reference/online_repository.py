"""Host-owned repository sessions for online rLLM rollouts."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, ClassVar

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.core.agent_feedback import public_feedback_test_ids
from verigym.core.episode import TerminationReason
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.core.repository_observation import REPOSITORY_OBSERVATION_POLICY_ID
from verigym.protocols.repository_action import (
    RepositoryActionProtocolViolation,
    canonical_repository_action_to_agent_action,
    extract_json_content,
    prompt_contract,
    repository_action_state_failure,
    task_requires_public_test,
    validate_canonical_action,
)
from verigym.registry.collections import build_registries
from verigym.schemas.action_protocol import RepositoryActionStateMachine
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    EpisodeResult,
    Observation,
    ToolCallAction,
)
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor, ErrorCategory, InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.score import EpisodeFailure
from verigym.schemas.suite import SuiteSourceConfig

from .online_verifier import online_docker_runtime_config
from .repository_broker_protocol import (
    atomic_json,
    atomic_json_new,
    hashed_message,
    read_hashed_message,
)
from .repository_context import (
    REPOSITORY_OBSERVATION_MAX_BYTES,
    project_repository_observation,
)

_STATE_MACHINE_ID: RepositoryActionStateMachine = "repository_action_state_machine_v2"
_MAX_ACTION_BYTES = 2 * 1024 * 1024
_MAX_OBSERVATION_BYTES = REPOSITORY_OBSERVATION_MAX_BYTES


class OnlineRepositoryBrokerAgent(AgentAdapter):
    """Block on hash-bound rLLM actions while VeriGym owns the live workspace."""

    supported_modes: ClassVar[frozenset[InteractionMode]] = frozenset({InteractionMode.AGENT})

    def __init__(
        self,
        *,
        broker_root: Path,
        session_id: str,
        public_input_hash: str,
    ) -> None:
        self.descriptor = AgentDescriptor(
            schema_version=SCHEMA_VERSION,
            name=f"rllm-repository-bridge-{session_id[:20]}",
            version="1.0.0",
            api_version=PLUGIN_API_VERSION,
            provider="verigym-training-reference",
            capabilities=[
                "deterministic_bridge",
                "online_training_repository_agent",
                "repository_action.v2",
            ],
        )
        self._broker_root = broker_root
        self._session_id = session_id
        self._public_input_hash = public_input_hash
        self._request_root = broker_root / "requests" / session_id
        self._response_root = broker_root / "responses" / session_id
        self._context: AgentContext | None = None
        self._next_turn = 0
        self._last_turn: int | None = None
        self._last_action: AgentAction | None = None
        self._last_action_name: str | None = None
        self._patch_applied = False
        self._public_observed = False
        self._compile_passed = False
        self._last_public_test_id: str | None = None
        self._diff_observed = False
        self._pending_protocol_error: str | None = None
        self._session_deadline: float | None = None

    @property
    def pending_turn(self) -> int | None:
        return self._last_turn

    @property
    def pending_protocol_error(self) -> str | None:
        return self._pending_protocol_error

    def start(self, context: AgentContext) -> None:
        if context.model_gateway is not None or context.external_bridge is not None:
            raise ValueError(
                "online repository bridge cannot receive model or external-agent access"
            )
        self._context = context
        self._session_deadline = time.monotonic() + context.task.budget.max_wall_time_s
        self._response_root.mkdir(mode=0o700, parents=True, exist_ok=False)

    def act(self, observation: Observation) -> AgentAction:
        context = self._require_context()
        if self._last_turn is None:
            self._publish_initial(observation)
        else:
            self._capture_result(observation)
        turn = self._next_turn
        maximum = self._maximum_completion_calls(context)
        if turn >= maximum:
            self._pending_protocol_error = "agent_turn_budget_exhausted"
            raise self._termination(
                "agent_turn_budget_exhausted",
                "repository action completion-turn budget was exhausted before finish",
            )
        if self._last_turn is not None:
            self._publish_observation(self._last_turn, observation)
        request = self._wait_for_action(turn)
        raw_action = request.get("raw_action")
        if not isinstance(raw_action, str):
            raise RuntimeError("repository action request omits its raw model response")
        try:
            value, _normalization = extract_json_content(
                raw_action,
                max_response_bytes=_MAX_ACTION_BYTES,
            )
            envelope, arguments = validate_canonical_action(value, task=context.task)
            failure = repository_action_state_failure(
                envelope.action,
                state_machine_id=self._state_machine_id(context),
                public_test_required=task_requires_public_test(context.task),
                patch_applied=self._patch_applied,
                public_observed=self._public_observed,
                diff_observed=self._diff_observed,
                finished=False,
                public_test_id=(
                    envelope.arguments.get("test_id")
                    if envelope.action == "run_public_test"
                    else None
                ),
                compile_test_id=(
                    context.agent_feedback_contract.compile_test_id
                    if context.agent_feedback_contract is not None
                    else None
                ),
                compile_passed=self._compile_passed,
                compile_required_for_finish=(
                    context.agent_feedback_contract.compile_required_for_finish
                    if context.agent_feedback_contract is not None
                    else False
                ),
            )
            if failure is not None:
                raise RepositoryActionProtocolViolation(
                    failure,
                    "repository action is invalid for the current frozen state-machine state",
                )
            action = canonical_repository_action_to_agent_action(envelope.action, arguments)
        except RepositoryActionProtocolViolation as exc:
            self._last_turn = turn
            self._pending_protocol_error = exc.subcategory
            raise self._termination(exc.subcategory, str(exc)) from exc
        self._last_turn = turn
        self._last_action = action
        self._last_action_name = envelope.action
        self._next_turn += 1
        return action

    def finish(self, result: EpisodeResult) -> None:
        del result

    def _require_context(self) -> AgentContext:
        if self._context is None:
            raise RuntimeError("online repository bridge has not been started")
        return self._context

    def _maximum_completion_calls(self, context: AgentContext) -> int:
        model_calls = context.task.budget.max_model_calls
        return min(model_calls or context.task.budget.max_turns, context.task.budget.max_turns, 128)

    def _publish_initial(self, observation: Observation) -> None:
        context = self._require_context()
        public_ids = public_feedback_test_ids(context.task)
        extra: dict[str, Any] = {
            "prompt_contract": prompt_contract(self._state_machine_id(context)),
            "public_test_ids": public_ids,
            "public_test_required": task_requires_public_test(context.task),
            "max_completion_calls": self._maximum_completion_calls(context),
        }
        if context.agent_feedback_contract is not None:
            extra["agent_feedback_contract"] = context.agent_feedback_contract.model_dump(
                mode="json"
            )
        payload = self._response_base(
            turn=None,
            terminal=False,
            observation=observation,
            extra=extra,
        )
        atomic_json(
            self._response_root / "initial.json",
            hashed_message(payload, hash_field="response_hash"),
        )

    def _publish_observation(self, turn: int, observation: Observation) -> None:
        payload = self._response_base(
            turn=turn,
            terminal=False,
            observation=observation,
            extra={
                "accepted": True,
                "action_name": self._last_action_name,
                "state": self._state(),
            },
        )
        atomic_json(
            self._response_root / f"turn-{turn:04d}.json",
            hashed_message(payload, hash_field="response_hash"),
        )

    def publish_terminal(self, turn: int | None, result: dict[str, Any]) -> str:
        payload = self._response_base(
            turn=turn,
            terminal=True,
            observation=None,
            extra={
                **result,
                "protocol_error": self._pending_protocol_error,
                "state": (
                    "finished"
                    if result.get("termination_reason") == "final_submission"
                    else self._state()
                ),
            },
        )
        message = hashed_message(payload, hash_field="response_hash")
        try:
            atomic_json_new(self._response_root / "terminal.json", message)
        except FileExistsError as exc:
            raise RuntimeError("repository broker terminal response already exists") from exc
        return str(message["response_hash"])

    def _response_base(
        self,
        *,
        turn: int | None,
        terminal: bool,
        observation: Observation | None,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._require_context()
        bounded_observation: object | None = None
        observation_truncated = False
        if observation is not None:
            bounded_observation, observation_truncated = project_repository_observation(
                observation.model_dump(mode="json"), max_bytes=_MAX_OBSERVATION_BYTES
            )
        return {
            "schema_version": "1.0",
            "format_id": "verigym_online_repository_response_v1",
            "session_id": self._session_id,
            "task_id": context.task.id,
            "public_input_hash": self._public_input_hash,
            "turn": turn,
            "terminal": terminal,
            "observation": bounded_observation,
            "observation_truncated": observation_truncated,
            **extra,
        }

    def _capture_result(self, observation: Observation) -> None:
        context = self._require_context()
        result = observation.previous_tool_result
        action = self._last_action
        if result is None or action is None:
            raise RuntimeError("repository bridge action did not receive a tool observation")
        if result.category in {ErrorCategory.PERMISSION_DENIED, ErrorCategory.POLICY_DENIED}:
            raise AgentTerminationError(
                TerminationReason.POLICY_VIOLATION,
                EpisodeFailure(
                    kind="policy",
                    category="workspace_policy_failure",
                    message="repository action was safely contained by workspace policy",
                ),
            )
        if result.category in {ErrorCategory.INTERNAL_ERROR, ErrorCategory.SANDBOX_ERROR}:
            raise AgentTerminationError(
                TerminationReason.RUNTIME_ERROR,
                EpisodeFailure(
                    kind="runtime",
                    category="repository_action_runtime_failure",
                    message="trusted repository action runtime failed",
                    infrastructure=True,
                ),
            )
        if isinstance(action, ApplyPatchAction) and result.success:
            self._patch_applied = True
            if context.agent_feedback_contract is not None:
                self._public_observed = False
                self._compile_passed = False
                self._last_public_test_id = None
                self._diff_observed = False
        elif isinstance(action, ToolCallAction) and action.tool == "repository.public_test":
            self._public_observed = True
            test_id = action.arguments.get("test_id")
            self._last_public_test_id = test_id if isinstance(test_id, str) else None
            if (
                context.agent_feedback_contract is not None
                and test_id == context.agent_feedback_contract.compile_test_id
            ):
                self._compile_passed = result.success
        elif isinstance(action, ToolCallAction) and action.tool == "file.diff":
            self._diff_observed = True

    def _state(self) -> str:
        if self._diff_observed:
            return "diff_observed"
        context = self._require_context()
        feedback = getattr(context, "agent_feedback_contract", None)
        if feedback is not None and self._last_public_test_id == feedback.ppa_test_id:
            return "ppa_observed"
        if feedback is not None and self._last_public_test_id == feedback.compile_test_id:
            return "compile_observed"
        if self._public_observed:
            return "public_test_observed"
        if self._patch_applied:
            return "candidate_modified"
        return "awaiting_action"

    @staticmethod
    def _state_machine_id(context: AgentContext) -> RepositoryActionStateMachine:
        if context.agent_feedback_contract is not None:
            return context.agent_feedback_contract.state_machine_id
        return _STATE_MACHINE_ID

    def _wait_for_action(self, turn: int) -> dict[str, Any]:
        context = self._require_context()
        path = self._request_root / f"turn-{turn:04d}.json"
        deadline = self._session_deadline
        if deadline is None:
            raise RuntimeError("repository bridge session deadline was not initialized")
        while not path.is_file():
            if (self._broker_root / "STOP").is_file():
                raise AgentTerminationError(
                    TerminationReason.CANCELLED,
                    EpisodeFailure(
                        kind="runtime",
                        category="repository_broker_stopped",
                        message="online repository broker stopped before the next action",
                        infrastructure=True,
                    ),
                )
            if time.monotonic() >= deadline:
                raise AgentTerminationError(
                    TerminationReason.WALL_TIME_EXHAUSTED,
                    EpisodeFailure(
                        kind="model",
                        category="repository_agent_action_timeout",
                        message=(
                            "repository model action did not arrive before the episode deadline"
                        ),
                        infrastructure=False,
                    ),
                )
            time.sleep(0.05)
        request = read_hashed_message(path, hash_field="request_hash")
        raw_action = request.get("raw_action")
        if (
            request.get("format_id") != "verigym_online_repository_action_v1"
            or request.get("session_id") != self._session_id
            or request.get("task_id") != context.task.id
            or request.get("public_input_hash") != self._public_input_hash
            or request.get("turn") != turn
            or not isinstance(raw_action, str)
            or request.get("raw_action_sha256") != hashlib.sha256(raw_action.encode()).hexdigest()
        ):
            raise RuntimeError("online repository action request identity changed")
        return request

    @staticmethod
    def _termination(subcategory: str, message: str) -> AgentTerminationError:
        return AgentTerminationError(
            TerminationReason.MODEL_OUTPUT_INVALID,
            EpisodeFailure(
                kind="model",
                category="agent_output_error",
                message=message,
                protocol_error_subcategory=subcategory,
            ),
        )


def run_online_repository_session(
    *,
    binding: dict[str, Any],
    open_request: dict[str, Any],
    source_root: Path,
    broker_root: Path,
    output: Path,
) -> dict[str, Any]:
    """Run one host-owned repository episode and publish its terminal outcome."""

    public = binding.get("public_record")
    session_id = open_request.get("session_id")
    task_id = open_request.get("task_id")
    if (
        not isinstance(public, dict)
        or not isinstance(session_id, str)
        or task_id != binding.get("task_id")
        or task_id != public.get("task_id")
        or open_request.get("public_input_hash") != public.get("record_hash")
    ):
        raise RuntimeError("online repository open request differs from its task binding")
    registries = build_registries()
    service = VeriGym(registries)
    source = SuiteSourceConfig(
        source_root=source_root.resolve(strict=True), variant=binding["variant"]
    )
    _suite, task, _assets = service.load_task(str(task_id), source)
    if content_hash(task) != public.get("task_hash") or task.source.content_hash != public.get(
        "source_hash"
    ):
        raise RuntimeError("online repository task identity differs from its public record")
    agent = OnlineRepositoryBrokerAgent(
        broker_root=broker_root,
        session_id=session_id,
        public_input_hash=public["record_hash"],
    )
    registries.agents.register(agent)
    result = service.run(
        RunConfig(
            task_id=task.id,
            suite_source=source,
            expected_task_hash=content_hash(task),
            expected_source_hash=task.source.content_hash,
            mode=InteractionMode.AGENT,
            agent=agent.descriptor.name,
            runtime="docker",
            docker_config=online_docker_runtime_config(
                str(binding["verifier_image"]), str(binding["verifier_image_id"])
            ),
            seed=int(open_request.get("seed", 20260809)),
            sample_index=int(open_request.get("sample_index", 0)),
            output=output,
            run_id=f"online-repository-{session_id[:20]}",
            experiment_id="qwen35-rllm-verl-online-repository-v1",
            plan_item_id=f"online-repository-{session_id[:20]}",
            system_id="qwen35-rllm-verl-repository-policy",
            base_seed=int(open_request.get("seed", 20260809)),
            agent_options={"observation_policy_id": REPOSITORY_OBSERVATION_POLICY_ID},
        )
    )
    invalid = _is_infrastructure_invalid(result.scorecard)
    terminal = {
        "infrastructure_valid": not invalid,
        "resolved": None if invalid else result.scorecard.resolved,
        "compile_status": result.scorecard.correctness.compile_status,
        "task_hash": result.scorecard.reproducibility.task_hash,
        "verifier_hash": result.scorecard.reproducibility.verifier_hash,
        "candidate_hash": result.scorecard.reproducibility.candidate_hash,
        "termination_reason": result.scorecard.termination_reason,
        "run_id": result.run_dir.name,
    }
    terminal_hash = agent.publish_terminal(agent.pending_turn, terminal)
    return {
        "session_id": session_id,
        "task_id": task_id,
        "run_id": result.run_dir.name,
        "infrastructure_valid": not invalid,
        "resolved": terminal["resolved"],
        "terminal_hash": terminal_hash,
    }


def _is_infrastructure_invalid(scorecard: Any) -> bool:
    failure = scorecard.failure
    return bool(
        scorecard.correctness.infrastructure_error
        or (failure is not None and failure.infrastructure)
        or (scorecard.status == "error" and (failure is None or failure.kind == "runtime"))
    )


__all__ = ["OnlineRepositoryBrokerAgent", "run_online_repository_session"]
