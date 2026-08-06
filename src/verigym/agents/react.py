"""Minimal strict-JSON ReAct baseline harness."""

from __future__ import annotations

from dataclasses import replace

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.agents.parsing import ModelOutputParseError, parse_react_action
from verigym.core.episode import TerminationReason
from verigym.core.hashing import canonical_json
from verigym.core.model_gateway import ModelBudgetError
from verigym.models.base import ModelClientError
from verigym.prompts.builder import PromptBuilder
from verigym.prompts.policy import agent_configuration_hash, validate_prompt_text
from verigym.schemas.agent import AgentAction, EpisodeResult, MessageAction, Observation
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor, InteractionMode
from verigym.schemas.evolution import MemoryPack
from verigym.schemas.model import ModelMessage
from verigym.schemas.prompt import AgentPromptPolicySpec
from verigym.schemas.score import EpisodeFailure


class ReferenceReActAgent(AgentAdapter):
    """Small baseline loop; intentionally not a production coding-agent framework."""

    requires_model = True
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="react",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=["agent_eval", "strict_json_actions", "bounded_invalid_actions"],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._messages: list[ModelMessage] = []
        self._started_prompt = False
        self._invalid_actions = 0
        self._parser_feedback: str | None = None

    def start(self, context: AgentContext) -> None:
        if context.model_gateway is None or context.prompt_builder is None:
            raise ValueError("ReferenceReActAgent requires a model gateway and prompt builder")
        if context.prompt_builder.mode != InteractionMode.AGENT:
            raise ValueError("ReferenceReActAgent requires the AgentEval prompt policy")
        self._context = context
        self._messages = []
        self._started_prompt = False
        self._invalid_actions = 0
        self._parser_feedback = None

    def act(self, observation: Observation) -> AgentAction:
        if self._context is None:
            raise RuntimeError("ReferenceReActAgent has not been started")
        gateway = self._context.model_gateway
        builder = self._context.prompt_builder
        assert gateway is not None and builder is not None
        if not self._started_prompt:
            initial = builder.initial_messages(self._context.task, observation)
            task_context_limit = builder.descriptor.max_task_context_bytes
            if (
                task_context_limit is not None
                and len(initial[-1].content.encode("utf-8")) > task_context_limit
            ):
                raise ValueError("ReAct task context exceeds its resolved byte bound")
            self._messages.extend(initial)
            self._started_prompt = True
        else:
            self._messages.append(
                builder.observation_message(
                    observation,
                    parser_feedback=self._parser_feedback,
                )
            )
            self._parser_feedback = None
        if builder.descriptor.max_prompt_bytes is not None:
            validate_prompt_text(
                canonical_json([message.model_dump(mode="json") for message in self._messages]),
                builder.descriptor,
            )
        request = gateway.create_request(
            self._messages,
            max_output_tokens=self._context.task.budget.max_output_tokens,
            metadata={
                "interaction_mode": "agent",
                "prompt_policy_hash": builder.descriptor.configuration_fingerprint,
                "agent_configuration_hash": agent_configuration_hash(
                    self.descriptor, self._context.agent_options
                ),
            },
        )
        try:
            response = gateway.generate(request)
        except ModelBudgetError as exc:
            raise AgentTerminationError(
                exc.reason,
                EpisodeFailure(
                    kind="model",
                    category=exc.reason.value,
                    message=f"model budget terminated ReAct: {exc.reason.value}",
                ),
            ) from exc
        except ModelClientError as exc:
            raise AgentTerminationError(
                TerminationReason.MODEL_ERROR,
                EpisodeFailure(
                    kind="model",
                    category=exc.info.category.value,
                    message=exc.info.message,
                    infrastructure=True,
                ),
            ) from exc
        self._messages.append(ModelMessage(role="assistant", content=response.text))
        try:
            action = parse_react_action(response.text)
        except ModelOutputParseError as exc:
            self._invalid_actions += 1
            feedback = f"Invalid action: {exc}. Return one strict JSON action object."
            gateway.emit_action_rejected(
                request.request_id,
                category="invalid_react_action",
                message=str(exc),
                invalid_count=self._invalid_actions,
            )
            if self._invalid_actions >= self._context.max_invalid_actions:
                raise AgentTerminationError(
                    TerminationReason.INVALID_ACTION_LIMIT,
                    EpisodeFailure(
                        kind="model",
                        category="invalid_action_limit",
                        message=(
                            f"model produced {self._invalid_actions} consecutive invalid actions"
                        ),
                    ),
                ) from exc
            self._parser_feedback = feedback
            return MessageAction(message=feedback)
        self._invalid_actions = 0
        gateway.emit_parsed_action(request.request_id, action.model_dump(mode="json"))
        return action

    def finish(self, result: EpisodeResult) -> None:
        return None


class VersionedContextReActAgent(ReferenceReActAgent):
    """Strict ReAct baseline with an immutable, hash-bound context-memory input."""

    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="verigym-react-context-v1",
        prompt_contract_version="1.0.0",
        task_context_policy="public_rtl_task_observation_v1",
        base_instruction_policy="strict_json_react_with_read_only_context_v1",
        content_visibility_policy="public_task_no_hidden_reference_v1",
        max_prompt_bytes=256 * 1024,
        max_task_context_bytes=128 * 1024,
        versioned_context_allowed=True,
    )
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="react-context",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "agent_eval",
            "strict_json_actions",
            "bounded_invalid_actions",
            "versioned_context_memory",
        ],
    )

    def start(self, context: AgentContext) -> None:
        policy = context.prompt_policy
        if policy is None or policy.resolver_id != "agent_execution_prompt_policy_v1":
            raise ValueError("react-context requires a resolved versioned prompt policy")
        raw_memory = context.agent_options.get("memory_pack")
        memory = MemoryPack.model_validate(raw_memory) if raw_memory is not None else None
        builder = PromptBuilder(
            InteractionMode.AGENT,
            descriptor=policy,
            memory_pack=memory,
        )
        super().start(replace(context, prompt_builder=builder))
