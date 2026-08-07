"""Single-call ChatEval harness with controlled RTL submission parsing."""

from __future__ import annotations

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.agents.parsing import (
    ModelOutputParseError,
    parse_single_turn_rtl,
    postprocess_single_line_completion,
)
from verigym.core.episode import TerminationReason
from verigym.core.model_gateway import ModelBudgetError
from verigym.models.base import ModelClientError
from verigym.prompts.policy import agent_configuration_hash
from verigym.schemas.agent import AgentAction, EpisodeResult, FinalSubmissionAction, Observation
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor, InteractionMode
from verigym.schemas.model import ModelMessage
from verigym.schemas.score import EpisodeFailure

_LINE_COMPLETION_PROMPT = (
    "Complete the code prefix in the user message. Return exactly the single source-code line "
    "that comes next and nothing else. Do not explain, use Markdown, or include surrounding "
    "text. Hidden verifier assets and targets are inaccessible."
)
_LINE_COMPLETION_PROMPT_PROFILE = "instructional-v1"


class SingleTurnAgent(AgentAdapter):
    """Build one ChatEval prompt, call one model once, and submit one RTL file."""

    requires_model = True
    supported_modes = frozenset({InteractionMode.CHAT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="single-turn",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=["chat_eval", "single_model_call", "controlled_rtl_submission"],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._called = False
        self._line_completion_prompt = False

    def start(self, context: AgentContext) -> None:
        if context.model_gateway is None or context.prompt_builder is None:
            raise ValueError("SingleTurnAgent requires a model gateway and prompt builder")
        if context.prompt_builder.mode != InteractionMode.CHAT:
            raise ValueError("SingleTurnAgent requires the ChatEval prompt policy")
        unknown_options = sorted(set(context.agent_options) - {"line_completion_prompt"})
        if unknown_options:
            raise ValueError("unsupported single-turn agent options: " + ", ".join(unknown_options))
        prompt_profile = context.agent_options.get("line_completion_prompt")
        if prompt_profile not in {None, _LINE_COMPLETION_PROMPT_PROFILE}:
            raise ValueError("single-turn line_completion_prompt must be 'instructional-v1'")
        if prompt_profile is not None and context.task.interaction.final_submission.kind != "line":
            raise ValueError("single-turn line completion instructions require a line submission")
        self._context = context
        self._called = False
        self._line_completion_prompt = prompt_profile is not None

    def act(self, observation: Observation) -> AgentAction:
        if self._context is None:
            raise RuntimeError("SingleTurnAgent has not been started")
        if self._called:
            raise AgentTerminationError(
                TerminationReason.MODEL_OUTPUT_INVALID,
                EpisodeFailure(
                    kind="agent",
                    category="multiple_single_turn_calls",
                    message="SingleTurnAgent was asked to call the model more than once",
                ),
            )
        self._called = True
        gateway = self._context.model_gateway
        builder = self._context.prompt_builder
        assert gateway is not None and builder is not None
        messages = builder.initial_messages(self._context.task, observation)
        if self._line_completion_prompt:
            messages = [ModelMessage(role="system", content=_LINE_COMPLETION_PROMPT), *messages]
        request = gateway.create_request(
            messages,
            max_output_tokens=self._context.task.budget.max_output_tokens,
            metadata={
                "interaction_mode": "chat",
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
                    message=f"model budget terminated ChatEval: {exc.reason.value}",
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
        try:
            source = (
                postprocess_single_line_completion(response.text)
                if self._context.task.interaction.final_submission.kind == "line"
                else parse_single_turn_rtl(response.text)
            )
        except ModelOutputParseError as exc:
            gateway.emit_action_rejected(
                request.request_id,
                category="invalid_single_turn_output",
                message=str(exc),
                invalid_count=1,
            )
            raise AgentTerminationError(
                TerminationReason.MODEL_OUTPUT_INVALID,
                EpisodeFailure(
                    kind="model",
                    category="invalid_output",
                    message=str(exc),
                ),
            ) from exc
        entrypoints = self._context.task.workspace.entrypoints
        if len(entrypoints) != 1:
            raise AgentTerminationError(
                TerminationReason.MODEL_OUTPUT_INVALID,
                EpisodeFailure(
                    kind="agent",
                    category="unsupported_submission_policy",
                    message="SingleTurnAgent requires exactly one task entrypoint",
                ),
            )
        action = FinalSubmissionAction(
            message="Single-turn candidate submitted.",
            files={entrypoints[0]: source},
        )
        gateway.emit_parsed_action(request.request_id, action.model_dump(mode="json"))
        return action

    def finish(self, result: EpisodeResult) -> None:
        return None
