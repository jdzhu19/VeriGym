"""Generic single-call API-backed repository repair agent."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.core.episode import TerminationReason
from verigym.core.model_gateway import ModelBudgetError
from verigym.models.base import ModelClientError
from verigym.prompts.policy import agent_configuration_hash, validate_prompt_text
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    EpisodeResult,
    FinalSubmissionAction,
    Observation,
    ToolCallAction,
)
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import AgentDescriptor, ErrorCategory, InteractionMode
from verigym.schemas.model import ModelErrorCategory, ModelFinishReason, ModelMessage
from verigym.schemas.prompt import AgentPromptPolicySpec
from verigym.schemas.score import EpisodeFailure

_ACTION_ADAPTER: TypeAdapter[AgentAction] = TypeAdapter(AgentAction)


class ApiRepositoryActionPlan(StrictModel):
    """One bounded provider response; the runtime still enforces every action."""

    schema_version: Literal["1.0"] = "1.0"
    actions: list[dict[str, Any]] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_protocol(self) -> ApiRepositoryActionPlan:
        types = [action.get("type") for action in self.actions]
        if types != ["apply_patch", "tool_call", "tool_call", "final"]:
            raise ValueError("actions must be apply_patch, public_test, file.diff, then final")
        first_tool, second_tool = self.actions[1], self.actions[2]
        if first_tool.get("tool") != "repository.public_test" or set(first_tool) - {
            "type",
            "tool",
            "arguments",
            "schema_version",
        }:
            raise ValueError("the second action must be one repository.public_test call")
        if second_tool.get("tool") != "file.diff" or second_tool.get("arguments", {}) != {}:
            raise ValueError("the third action must be file.diff with empty arguments")
        final = self.actions[3]
        if final.get("files") is not None:
            raise ValueError("API repository plans may not submit replacement file maps")
        return self


class ApiRepositoryAgent(AgentAdapter):
    """Read public inputs in Docker, then execute one strict remote action plan."""

    requires_model = True
    supported_modes = frozenset({InteractionMode.AGENT})
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="api_repository_action_plan_v1",
        prompt_contract_version="1.0.0",
        task_context_policy="bounded_public_repository_snapshot_v1",
        base_instruction_policy="strict_four_action_repository_repair_v1",
        content_visibility_policy="visible_assets_and_public_test_contract_only_v1",
        max_prompt_bytes=1024 * 1024,
        max_task_context_bytes=768 * 1024,
        versioned_context_allowed=True,
    )
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="api-repository-agent",
        version="0.2.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "agent_eval",
            "api_backed_repository_agent",
            "single_model_call",
            "strict_structured_action_plan",
            "docker_workspace_delegated",
            "credential_isolated",
            "frozen_agent_version_binding",
            "explicit_output_token_limit",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._read_queue: list[str] = []
        self._current_read: str | None = None
        self._visible_content: dict[str, str] = {}
        self._actions: list[AgentAction] = []
        self._request_complete = False
        self._max_output_tokens: int | None = None
        self._last_action: AgentAction | None = None

    def start(self, context: AgentContext) -> None:
        if context.model_gateway is None or context.prompt_policy is None:
            raise ValueError("ApiRepositoryAgent requires a model gateway and prompt policy")
        if context.prompt_builder is not None:
            raise ValueError("ApiRepositoryAgent owns its resolved execution prompt")
        if context.prompt_policy.id != self.prompt_policy_spec.prompt_contract_id:
            raise ValueError("API repository prompt policy identity mismatch")
        if context.agent_options:
            allowed = {
                "action_plan_protocol",
                "agent_version_hash",
                "agent_version_id",
                "agent_version_manifest_json",
                "max_output_tokens",
            }
            if set(context.agent_options) - allowed:
                raise ValueError("API repository agent received unknown options")
            protocol = context.agent_options.get("action_plan_protocol")
            if protocol not in {None, "strict_four_action_repository_repair_v1"}:
                raise ValueError("unsupported API repository action-plan protocol")
        output_limit = context.agent_options.get("max_output_tokens")
        if output_limit is not None and (
            isinstance(output_limit, bool)
            or not isinstance(output_limit, int)
            or not 1 <= output_limit <= 65_536
        ):
            raise ValueError("max_output_tokens must be an integer in [1, 65536]")
        task_limit = context.task.budget.max_output_tokens
        if output_limit is not None and task_limit is not None and output_limit > task_limit:
            raise ValueError("agent max_output_tokens may not exceed the task budget")
        self._max_output_tokens = output_limit if output_limit is not None else task_limit
        self._context = context
        self._read_queue = [
            "TASK.md",
            "PUBLIC_TESTS.md",
            "repository/README.md",
            *sorted(context.task.workspace.entrypoints),
        ]
        self._current_read = None
        self._visible_content = {}
        self._actions = []
        self._request_complete = False
        self._last_action = None

    def act(self, observation: Observation) -> AgentAction:
        if self._context is None:
            raise RuntimeError("ApiRepositoryAgent has not been started")
        self._capture_read(observation)
        self._inspect_previous_action(observation)
        if self._read_queue:
            path = self._read_queue.pop(0)
            self._current_read = path
            return ToolCallAction(tool="file.read", arguments={"path": path})
        if not self._request_complete:
            self._actions = self._request_plan()
            self._request_complete = True
        if not self._actions:
            raise AgentTerminationError(
                TerminationReason.MODEL_ERROR,
                EpisodeFailure(
                    kind="model",
                    category="agent_output_failure",
                    message="API repository action plan ended without a final action",
                ),
            )
        action = self._actions.pop(0)
        self._last_action = action
        return action

    def finish(self, result: EpisodeResult) -> None:
        del result

    def _capture_read(self, observation: Observation) -> None:
        if self._current_read is None:
            return
        result = observation.previous_tool_result
        path = self._current_read
        self._current_read = None
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
        self._visible_content[path] = result.stdout

    def _inspect_previous_action(self, observation: Observation) -> None:
        if self._last_action is None:
            return
        previous_action = self._last_action
        result = observation.previous_tool_result
        self._last_action = None
        if (
            isinstance(previous_action, ApplyPatchAction)
            and result is not None
            and result.category == ErrorCategory.PERMISSION_DENIED
            and result.message == "patch context does not match the workspace"
        ):
            raise _agent_output_error(
                "provider patch could not be materialized against the visible repository"
            )
        if result is not None and result.category in {
            ErrorCategory.PERMISSION_DENIED,
            ErrorCategory.POLICY_DENIED,
        }:
            raise AgentTerminationError(
                TerminationReason.POLICY_VIOLATION,
                EpisodeFailure(
                    kind="policy",
                    category="workspace_policy_failure",
                    message="API repository action was safely contained by workspace policy",
                ),
            )

    def _request_plan(self) -> list[AgentAction]:
        assert self._context is not None and self._context.model_gateway is not None
        context = self._context
        gateway = context.model_gateway
        prompt_policy = context.prompt_policy
        assert gateway is not None and prompt_policy is not None
        prompt = _render_prompt(context, self._visible_content)
        validate_prompt_text(prompt, prompt_policy)
        prompt_hash = prompt_policy.configuration_fingerprint
        configuration_hash = agent_configuration_hash(self.descriptor, context.agent_options)
        request = gateway.create_request(
            [
                ModelMessage(
                    role="system",
                    content=(
                        "You are a repository repair agent. Return exactly one JSON object "
                        "matching the supplied action-plan protocol and no markdown."
                    ),
                ),
                ModelMessage(role="user", content=prompt),
            ],
            max_output_tokens=self._max_output_tokens,
            metadata={
                "interaction_mode": "agent",
                "prompt_policy_hash": prompt_hash,
                "agent_configuration_hash": configuration_hash,
                "action_plan_protocol": "strict_four_action_repository_repair_v1",
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
                    message=f"model budget terminated API repository agent: {exc.reason.value}",
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
            raise _agent_output_error("provider response stopped at the output limit")
        try:
            raw = json.loads(response.text, object_pairs_hook=_unique_object)
            plan = ApiRepositoryActionPlan.model_validate(raw)
            actions = [_ACTION_ADAPTER.validate_python(item) for item in plan.actions]
            _validate_task_actions(context, actions)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            gateway.emit_action_rejected(
                request.request_id,
                category="invalid_api_repository_action_plan",
                message=str(exc),
                invalid_count=1,
            )
            raise _agent_output_error(f"invalid API repository action plan: {exc}") from exc
        gateway.emit_parsed_action(
            request.request_id,
            {"protocol": "strict_four_action_repository_repair_v1", "actions": plan.actions},
        )
        return actions


def _render_prompt(context: AgentContext, files: Mapping[str, str]) -> str:
    prompt_policy = context.prompt_policy
    assert prompt_policy is not None
    repository = context.task.metadata.get("repository_repair")
    public_ids: list[str] = []
    if isinstance(repository, dict):
        raw = repository.get("public_test_ids")
        if isinstance(raw, list) and all(isinstance(value, str) for value in raw):
            public_ids = sorted(raw)
    payload = {
        "schema_version": "1.0",
        "protocol": "strict_four_action_repository_repair_v1",
        "task": {
            "id": context.task.id,
            "title": context.task.title,
            "description": context.task.description,
            "editable_globs": sorted(context.task.workspace.editable_globs),
            "readonly_globs": sorted(context.task.workspace.readonly_globs),
            "max_changed_files": context.task.workspace.max_changed_files,
            "max_patch_lines": context.task.workspace.max_patch_lines,
            "public_test_ids": public_ids,
        },
        "visible_files": {path: files[path] for path in sorted(files)},
        "required_response": {
            "schema_version": "1.0",
            "actions": [
                {"type": "apply_patch", "patch": "unified diff rooted at repository/"},
                {
                    "type": "tool_call",
                    "tool": "repository.public_test",
                    "arguments": {"test_id": "one listed public test ID"},
                },
                {"type": "tool_call", "tool": "file.diff", "arguments": {}},
                {"type": "final", "message": "bounded completion note"},
            ],
        },
        "rules": [
            "Use only visible information in this prompt.",
            "Do not mention or infer hidden tests or reference patches.",
            "Do not use markdown fences or include extra JSON fields.",
            "Do not replace files wholesale; provide one deterministic unified patch.",
            "Never request network, shell, credential, or outside-workspace operations.",
        ],
        "seed": context.seed,
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(rendered.encode("utf-8")) > (prompt_policy.max_task_context_bytes or 0):
        raise ValueError("visible repository context exceeds its prompt-policy byte bound")
    return rendered


def _validate_task_actions(context: AgentContext, actions: list[AgentAction]) -> None:
    repository = context.task.metadata.get("repository_repair")
    public_ids = repository.get("public_test_ids") if isinstance(repository, dict) else None
    test_action = actions[1]
    if not isinstance(actions[0], ApplyPatchAction):
        raise ValueError("first action did not validate as apply_patch")
    if not isinstance(test_action, ToolCallAction):
        raise ValueError("second action did not validate as tool_call")
    if set(test_action.arguments) != {"test_id"} or test_action.arguments.get("test_id") not in (
        public_ids or []
    ):
        raise ValueError("public test action does not name one task-declared test")
    if not isinstance(actions[2], ToolCallAction) or not isinstance(
        actions[3], FinalSubmissionAction
    ):
        raise ValueError("action plan types are invalid")


def _provider_failure_category(category: ModelErrorCategory) -> str:
    return {
        ModelErrorCategory.AUTHENTICATION: "provider_authentication_error",
        ModelErrorCategory.RATE_LIMIT: "provider_rate_limit",
        ModelErrorCategory.TIMEOUT: "provider_timeout",
        ModelErrorCategory.OUTPUT_LIMIT: "provider_output_limit",
        ModelErrorCategory.PROVIDER_UNAVAILABLE: "provider_unavailable",
        ModelErrorCategory.TRANSPORT: "provider_unavailable",
        ModelErrorCategory.PROTOCOL_ERROR: "provider_protocol_error",
        ModelErrorCategory.MALFORMED_RESPONSE: "provider_malformed_response",
        ModelErrorCategory.INVALID_RESPONSE: "provider_malformed_response",
    }.get(category, f"provider_{category.value}")


def _agent_output_error(message: str) -> AgentTerminationError:
    return AgentTerminationError(
        TerminationReason.MODEL_ERROR,
        EpisodeFailure(kind="model", category="agent_output_error", message=message),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("provider action plan contains duplicate JSON keys")
        result[key] = value
    return result


__all__ = ["ApiRepositoryActionPlan", "ApiRepositoryAgent"]
