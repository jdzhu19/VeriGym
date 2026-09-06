"""Multi-turn provider-neutral API repository agent using ``repository_action.v2``."""

from __future__ import annotations

import json
from typing import Any

from verigym.agents.api_repository import _provider_failure_category
from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.core.agent_feedback import public_feedback_test_ids
from verigym.core.episode import TerminationReason
from verigym.core.hashing import content_hash
from verigym.core.model_gateway import ModelBudgetError
from verigym.models.base import ModelClientError
from verigym.prompts.policy import agent_configuration_hash, validate_prompt_text
from verigym.protocols.repository_action import (
    RepositoryActionProtocolViolation,
    bounded_tool_result_identity,
    canonical_repository_action_to_agent_action,
    extract_transport_action,
    prompt_contract,
    repository_action_state_failure,
    task_requires_public_test,
    validate_canonical_action,
)
from verigym.schemas.action_protocol import (
    RepositoryActionProtocolSpec,
    RepositoryActionState,
    RepositoryActionTurnRecord,
    RepositoryProtocolError,
)
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    EpisodeResult,
    Observation,
    ToolCallAction,
)
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor, ErrorCategory, InteractionMode
from verigym.schemas.model import ModelFinishReason, ModelMessage
from verigym.schemas.prompt import AgentPromptPolicySpec
from verigym.schemas.score import EpisodeFailure


class ProviderNeutralApiRepositoryAgent(AgentAdapter):
    """Execute exactly one strict canonical repository action per provider turn."""

    requires_model = True
    supported_modes = frozenset({InteractionMode.AGENT})
    action_protocol_spec = RepositoryActionProtocolSpec()
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="repository_action_v2_prompt_v2",
        prompt_contract_version="1.0.0",
        task_context_policy="bounded_public_repository_tools_v2",
        base_instruction_policy="generated_repository_action_registry_v2",
        content_visibility_policy="visible_assets_and_bounded_tool_observations_v2",
        max_prompt_bytes=1024 * 1024,
        max_task_context_bytes=768 * 1024,
        versioned_context_allowed=False,
    )
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="provider-neutral-api-repository-agent",
        version="0.2.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "agent_eval",
            "api_backed_repository_agent",
            "provider_neutral",
            "multi_turn",
            "repository_action.v2",
            "one_action_per_turn",
            "docker_workspace_delegated",
            "credential_isolated",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bootstrap_queue: list[str] = []
        self._bootstrap_current: str | None = None
        self._bootstrap_content: dict[str, str] = {}
        self._observations: list[dict[str, Any]] = []
        self._records: list[RepositoryActionTurnRecord] = []
        self._last_action: AgentAction | None = None
        self._last_record_index: int | None = None
        self._state: RepositoryActionState = "awaiting_action"
        self._patch_applied = False
        self._public_test_observed = False
        self._compile_passed = False
        self._diff_observed = False
        self._max_output_tokens: int | None = None

    def start(self, context: AgentContext) -> None:
        if context.model_gateway is None or context.prompt_policy is None:
            raise ValueError("provider-neutral API repository agent requires a model and prompt")
        if context.action_protocol is None:
            raise ValueError("provider-neutral API repository agent requires a resolved protocol")
        if context.prompt_builder is not None:
            raise ValueError("provider-neutral API repository agent owns its execution prompt")
        if context.prompt_policy.id != context.action_protocol.prompt_contract_id:
            raise ValueError("repository action prompt identity mismatch")
        if context.action_protocol.protocol_id != "repository_action.v2":
            raise ValueError("repository action protocol identity mismatch")
        allowed_options = {
            "action_protocol",
            "action_transport",
            "max_completion_calls",
            "max_response_bytes",
        }
        if set(context.agent_options) - allowed_options:
            raise ValueError("provider-neutral API repository agent received unknown options")
        self._context = context
        self._bootstrap_queue = [
            "TASK.md",
            "PUBLIC_TESTS.md",
            "repository/README.md",
            *sorted(context.task.workspace.entrypoints),
        ]
        self._bootstrap_current = None
        self._bootstrap_content = {}
        self._observations = []
        self._records = []
        self._last_action = None
        self._last_record_index = None
        self._state = "awaiting_action"
        self._patch_applied = False
        self._public_test_observed = False
        self._compile_passed = False
        self._diff_observed = False
        self._max_output_tokens = context.task.budget.max_output_tokens

    def act(self, observation: Observation) -> AgentAction:
        context = self._require_context()
        self._capture_bootstrap(observation)
        self._capture_action_result(observation)
        if self._bootstrap_queue:
            path = self._bootstrap_queue.pop(0)
            self._bootstrap_current = path
            return ToolCallAction(tool="file.read", arguments={"path": path})
        protocol = context.action_protocol
        assert protocol is not None and context.model_gateway is not None
        if context.model_gateway.tracker.model_calls >= protocol.max_completion_calls:
            raise _protocol_error(
                "agent_turn_budget_exhausted",
                "repository action completion-turn budget was exhausted before finish",
            )
        return self._request_action()

    def finish(self, result: EpisodeResult) -> None:
        del result

    def action_protocol_records(self) -> list[RepositoryActionTurnRecord]:
        return [record.model_copy(deep=True) for record in self._records]

    def _require_context(self) -> AgentContext:
        if self._context is None:
            raise RuntimeError("provider-neutral API repository agent has not been started")
        return self._context

    def _capture_bootstrap(self, observation: Observation) -> None:
        if self._bootstrap_current is None:
            return
        path = self._bootstrap_current
        self._bootstrap_current = None
        result = observation.previous_tool_result
        if result is None or result.tool != "file.read" or not result.success:
            raise AgentTerminationError(
                TerminationReason.RUNTIME_ERROR,
                EpisodeFailure(
                    kind="runtime",
                    category="visible_repository_read_failure",
                    message=f"trusted visible-file read failed for {path}",
                    infrastructure=True,
                ),
            )
        self._bootstrap_content[path] = result.stdout

    def _capture_action_result(self, observation: Observation) -> None:
        context = self._require_context()
        if self._last_action is None:
            return
        action = self._last_action
        self._last_action = None
        result = observation.previous_tool_result
        if result is None:
            raise AgentTerminationError(
                TerminationReason.RUNTIME_ERROR,
                EpisodeFailure(
                    kind="runtime",
                    category="missing_action_observation",
                    message="repository action did not produce a tool observation",
                    infrastructure=True,
                ),
            )
        if self._last_record_index is not None:
            record = self._records[self._last_record_index]
            self._records[self._last_record_index] = record.model_copy(
                update={"tool_result_hash": content_hash(bounded_tool_result_identity(result))}
            )
        self._last_record_index = None
        if result.category in {ErrorCategory.PERMISSION_DENIED, ErrorCategory.POLICY_DENIED}:
            if (
                isinstance(action, ApplyPatchAction)
                and result.message == "patch context does not match the workspace"
            ):
                self._set_last_termination("model_output_invalid")
                raise _protocol_error(
                    "agent_invalid_arguments",
                    "repository patch could not be materialized against the visible repository",
                )
            self._set_last_termination("policy_violation")
            raise AgentTerminationError(
                TerminationReason.POLICY_VIOLATION,
                EpisodeFailure(
                    kind="policy",
                    category="workspace_policy_failure",
                    message="repository action was safely contained by workspace policy",
                ),
            )
        if result.category in {ErrorCategory.INTERNAL_ERROR, ErrorCategory.SANDBOX_ERROR}:
            self._set_last_termination("runtime_error")
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
            if context.action_protocol is not None and context.action_protocol.state_machine_id == (
                "repository_action_state_machine_v3"
            ):
                self._public_test_observed = False
                self._compile_passed = False
                self._diff_observed = False
            self._state = "candidate_modified"
        elif isinstance(action, ToolCallAction) and action.tool == "repository.public_test":
            self._public_test_observed = True
            test_id = action.arguments.get("test_id")
            if context.agent_feedback_contract is not None and test_id == (
                context.agent_feedback_contract.compile_test_id
            ):
                self._compile_passed = result.success
                self._state = "compile_observed"
            elif context.agent_feedback_contract is not None and test_id == (
                context.agent_feedback_contract.ppa_test_id
            ):
                self._state = "ppa_observed"
            else:
                self._state = "public_test_observed"
        elif isinstance(action, ToolCallAction) and action.tool == "file.diff":
            self._diff_observed = True
            self._state = "diff_observed"
        if self._records:
            self._records[-1] = self._records[-1].model_copy(update={"state_after": self._state})
        self._observations.append(bounded_tool_result_identity(result))

    def _request_action(self) -> AgentAction:
        context = self._require_context()
        gateway = context.model_gateway
        protocol = context.action_protocol
        prompt_policy = context.prompt_policy
        assert gateway is not None and protocol is not None and prompt_policy is not None
        prompt = _render_prompt(
            context=context,
            bootstrap=self._bootstrap_content,
            observations=self._observations,
            state=self._state,
        )
        validate_prompt_text(prompt, prompt_policy)
        request = gateway.create_request(
            [
                ModelMessage(
                    role="system",
                    content=(
                        "You are a bounded repository repair agent. Return exactly one JSON "
                        "object matching repository_action.v2 and no prose."
                    ),
                ),
                ModelMessage(role="user", content=prompt),
            ],
            max_output_tokens=self._max_output_tokens,
            metadata={
                "interaction_mode": "agent",
                "prompt_policy_hash": prompt_policy.configuration_fingerprint,
                "agent_configuration_hash": agent_configuration_hash(
                    self.descriptor, context.agent_options
                ),
                "action_protocol_hash": protocol.configuration_fingerprint,
                "action_transport": protocol.action_transport,
                "completion_turn": gateway.tracker.model_calls,
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
                    message=f"model budget terminated repository action agent: {exc.reason.value}",
                    infrastructure=True,
                ),
            ) from exc
        except ModelClientError as exc:
            raise AgentTerminationError(
                TerminationReason.MODEL_ERROR,
                EpisodeFailure(
                    kind="model",
                    category=_provider_failure_category(exc.info.category),
                    message=exc.info.message,
                    infrastructure=True,
                ),
            ) from exc
        if response.finish_reason == ModelFinishReason.LENGTH:
            self._reject(request.request_id, "agent_response_oversized")
        if response.finish_reason in {ModelFinishReason.CONTENT_FILTER, ModelFinishReason.ERROR}:
            self._reject(request.request_id, "agent_unsupported_transport")
        try:
            raw, normalization = extract_transport_action(
                transport=protocol.action_transport,
                text=response.text,
                native_tool_calls=response.native_tool_calls,
                max_response_bytes=protocol.max_response_bytes,
            )
            envelope, arguments = validate_canonical_action(raw, task=context.task)
            action = canonical_repository_action_to_agent_action(envelope.action, arguments)
            self._validate_state_transition(envelope.action, envelope.arguments)
        except RepositoryActionProtocolViolation as exc:
            gateway.emit_action_rejected(
                request.request_id,
                category=exc.subcategory,
                message=str(exc),
                invalid_count=1,
            )
            self._records.append(
                RepositoryActionTurnRecord(
                    turn_index=gateway.tracker.model_calls - 1,
                    request_id=request.request_id,
                    transport=protocol.action_transport,
                    state_before=self._state,
                    normalization=(locals().get("normalization")),
                    accepted=False,
                    permitted_normalization_used=bool(
                        locals().get("normalization")
                        and len(locals()["normalization"].decisions) > 1
                    ),
                    validation_result="rejected",
                    action_envelope_hash=(
                        content_hash(locals()["raw"]) if "raw" in locals() else None
                    ),
                    error_subcategory=exc.subcategory,
                    termination_reason="model_output_invalid",
                )
            )
            raise _protocol_error(exc.subcategory, str(exc)) from exc
        record = RepositoryActionTurnRecord(
            turn_index=gateway.tracker.model_calls - 1,
            request_id=request.request_id,
            transport=protocol.action_transport,
            state_before=self._state,
            state_after="finished" if envelope.action == "finish" else self._state,
            normalization=normalization,
            accepted=True,
            permitted_normalization_used=bool(normalization and len(normalization.decisions) > 1),
            validation_result="accepted",
            action_name=envelope.action,
            action_envelope_hash=content_hash(envelope),
            arguments_hash=content_hash(envelope.arguments),
            termination_reason=("final_submission" if envelope.action == "finish" else None),
        )
        self._records.append(record)
        gateway.emit_parsed_action(
            request.request_id,
            {
                "protocol": "repository_action.v2",
                "transport": protocol.action_transport,
                "turn_index": record.turn_index,
                "action": envelope.model_dump(mode="json"),
                "normalization": (
                    normalization.model_dump(mode="json") if normalization is not None else None
                ),
            },
        )
        if envelope.action == "finish":
            self._state = "finished"
        else:
            self._last_action = action
            self._last_record_index = len(self._records) - 1
        return action

    def _reject(self, request_id: str, subcategory: RepositoryProtocolError) -> None:
        context = self._require_context()
        assert context.model_gateway is not None and context.action_protocol is not None
        context.model_gateway.emit_action_rejected(
            request_id,
            category=subcategory,
            message="provider response finish state is incompatible with the action protocol",
            invalid_count=1,
        )
        self._records.append(
            RepositoryActionTurnRecord(
                turn_index=context.model_gateway.tracker.model_calls - 1,
                request_id=request_id,
                transport=context.action_protocol.action_transport,
                state_before=self._state,
                accepted=False,
                validation_result="rejected",
                error_subcategory=subcategory,
                termination_reason="model_output_invalid",
            )
        )
        raise _protocol_error(
            subcategory, "provider response finish state is incompatible with the action protocol"
        )

    def _validate_state_transition(self, action: str, arguments: dict[str, Any]) -> None:
        context = self._require_context()
        protocol = context.action_protocol
        assert protocol is not None
        failure = repository_action_state_failure(
            action,
            state_machine_id=protocol.state_machine_id,
            public_test_required=task_requires_public_test(context.task),
            patch_applied=self._patch_applied,
            public_observed=self._public_test_observed,
            diff_observed=self._diff_observed,
            finished=self._state == "finished",
            public_test_id=(arguments.get("test_id") if action == "run_public_test" else None),
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

    def _set_last_termination(self, reason: str) -> None:
        if self._records:
            self._records[-1] = self._records[-1].model_copy(update={"termination_reason": reason})


def _render_prompt(
    *,
    context: AgentContext,
    bootstrap: dict[str, str],
    observations: list[dict[str, Any]],
    state: RepositoryActionState,
) -> str:
    policy = context.prompt_policy
    protocol = context.action_protocol
    assert policy is not None and protocol is not None
    public_ids = public_feedback_test_ids(context.task)
    payload = {
        "schema_version": "1.0",
        "prompt_contract": prompt_contract(protocol.state_machine_id),
        "action_protocol_identity": protocol.model_dump(mode="json"),
        "task": {
            "id": context.task.id,
            "title": context.task.title,
            "description": context.task.description,
            "entrypoints": sorted(context.task.workspace.entrypoints),
            "editable_globs": sorted(context.task.workspace.editable_globs),
            "readonly_globs": sorted(context.task.workspace.readonly_globs),
            "public_test_ids": sorted(public_ids),
            "max_changed_files": context.task.workspace.max_changed_files,
            "max_patch_lines": context.task.workspace.max_patch_lines,
        },
        "bootstrap_visible_files": {path: bootstrap[path] for path in sorted(bootstrap)},
        "state": state,
        "completed_turns": len(observations),
        "bounded_observations": observations,
        "seed": context.seed,
    }
    if context.agent_feedback_contract is not None:
        payload["agent_feedback_contract"] = context.agent_feedback_contract.model_dump(mode="json")
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(rendered.encode("utf-8")) > (policy.max_task_context_bytes or 0):
        raise ValueError("repository action task context exceeds its frozen byte bound")
    return rendered


def _protocol_error(
    subcategory: RepositoryProtocolError,
    message: str,
) -> AgentTerminationError:
    return AgentTerminationError(
        TerminationReason.MODEL_OUTPUT_INVALID,
        EpisodeFailure(
            kind="model",
            category="agent_output_error",
            protocol_error_subcategory=subcategory,
            message=message,
            infrastructure=False,
        ),
    )


__all__ = ["ProviderNeutralApiRepositoryAgent"]
