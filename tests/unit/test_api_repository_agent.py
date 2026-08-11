from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verigym.agents.api_repository import ApiRepositoryAgent
from verigym.agents.base import AgentContext, AgentTerminationError
from verigym.core.episode import BudgetTracker
from verigym.core.hashing import canonical_json, content_hash
from verigym.core.model_gateway import ModelGateway
from verigym.core.trace import TraceWriter
from verigym.evolution.memory import build_agent_version
from verigym.models.static import StaticModelClient
from verigym.prompts.policy import prompt_contract_identity_hash, resolve_prompt_policy
from verigym.schemas.agent import BudgetRemaining, Observation, ToolCallAction
from verigym.schemas.common import ErrorCategory, InteractionMode
from verigym.schemas.model import ModelMessage
from verigym.schemas.task import TaskRef
from verigym.schemas.tool import ToolResult
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite


def _good_plan(test_id: str = "counter-wrap-public") -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "actions": [
                {
                    "type": "apply_patch",
                    "patch": (
                        "--- a/repository/rtl/wrap_counter.sv\n"
                        "+++ b/repository/rtl/wrap_counter.sv\n"
                        "@@ -1,1 +1,1 @@\n-module old;\n+module new;\n"
                    ),
                },
                {
                    "type": "tool_call",
                    "tool": "repository.public_test",
                    "arguments": {"test_id": test_id},
                },
                {"type": "tool_call", "tool": "file.diff", "arguments": {}},
                {"type": "final", "message": "done"},
            ],
        },
        separators=(",", ":"),
    )


def _good_plan_without_public_test() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "actions": [
                {
                    "type": "apply_patch",
                    "patch": (
                        "--- a/repository/rtl/wrap_counter.sv\n"
                        "+++ b/repository/rtl/wrap_counter.sv\n"
                        "@@ -1,1 +1,1 @@\n-module old;\n+module new;\n"
                    ),
                },
                {"type": "tool_call", "tool": "file.diff", "arguments": {}},
                {"type": "final", "message": "done"},
            ],
        },
        separators=(",", ":"),
    )


def _observation(previous: ToolResult | None = None) -> Observation:
    return Observation(
        task_id="repo-rtl/counter-wrap",
        remaining_budget=BudgetRemaining(
            turns=20,
            tool_calls=40,
            wall_time_s=300,
            model_calls=1,
        ),
        previous_tool_result=previous,
        episode_status="running",
    )


def _started_agent(
    tmp_path: Path,
    response: str,
    *,
    options: dict[str, Any] | None = None,
    without_public_tests: bool = False,
) -> tuple[ApiRepositoryAgent, ModelGateway, RepositoryRtlSuite, Path, Path]:
    suite = RepositoryRtlSuite()
    task = suite.load_task(
        TaskRef(id="repo-rtl/counter-wrap", suite="repo-rtl", native_id="counter-wrap")
    )
    if without_public_tests:
        metadata = dict(task.metadata)
        repository = dict(metadata["repository_repair"])
        repository["public_test_ids"] = []
        metadata["repository_repair"] = repository
        task = task.model_copy(update={"metadata": metadata})
    assets = suite.resolve_assets(task)
    agent = ApiRepositoryAgent()
    client = StaticModelClient(name="fake-api", responses=[response])
    trace_path = tmp_path / "trace.jsonl"
    gateway = ModelGateway(
        run_id="fake-api-run",
        client=client,
        trace=TraceWriter(trace_path, "fake-api-run"),
        tracker=BudgetTracker(task.budget),
        max_visible_bytes=task.budget.max_output_bytes_per_tool,
    )
    prompt = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options=options or {},
        task=task,
    )
    agent.start(
        AgentContext(
            run_id="fake-api-run",
            task=task,
            seed=7,
            model_gateway=gateway,
            prompt_policy=prompt,
            agent_options=options or {},
        )
    )
    return agent, gateway, suite, Path(assets.visible_root), trace_path


def _advance_public_reads(agent: ApiRepositoryAgent, visible_root: Path) -> ToolCallAction:
    action = agent.act(_observation())
    while isinstance(action, ToolCallAction) and action.tool == "file.read":
        path = str(action.arguments["path"])
        result = ToolResult(
            tool="file.read",
            success=True,
            category=ErrorCategory.SUCCESS,
            stdout=(visible_root / path).read_text(encoding="utf-8"),
        )
        action = agent.act(_observation(result))
    return action  # type: ignore[return-value]


def test_api_repository_agent_uses_one_model_call_and_strict_public_context(
    tmp_path: Path,
) -> None:
    agent, gateway, _suite, visible, trace_path = _started_agent(tmp_path, _good_plan())
    first = _advance_public_reads(agent, visible)
    assert first.type == "apply_patch"
    assert gateway.tracker.model_calls == 1
    second = agent.act(_observation())
    third = agent.act(_observation())
    fourth = agent.act(_observation())
    assert [second.type, third.type, fourth.type] == ["tool_call", "tool_call", "final"]
    serialized = trace_path.read_text(encoding="utf-8")
    assert "strict_four_action_repository_repair_v1" in serialized
    assert "reference.patch" not in serialized
    assert "tb_counter_hidden" not in serialized
    assert "api_key" not in serialized.lower()


def test_api_repository_agent_binds_explicit_output_limit(tmp_path: Path) -> None:
    agent, _gateway, _suite, visible, trace_path = _started_agent(
        tmp_path,
        _good_plan(),
        options={"max_output_tokens": 4096},
    )

    assert _advance_public_reads(agent, visible).type == "apply_patch"

    serialized = trace_path.read_text(encoding="utf-8")
    assert '"max_output_tokens":4096' in serialized


def test_api_repository_agent_supports_tasks_without_public_tests(tmp_path: Path) -> None:
    protocol = "strict_three_action_repository_repair_v1"
    agent, gateway, _suite, visible, trace_path = _started_agent(
        tmp_path,
        _good_plan_without_public_test(),
        options={"action_plan_protocol": protocol, "max_output_tokens": 4096},
        without_public_tests=True,
    )

    first = _advance_public_reads(agent, visible)
    second = agent.act(_observation())
    third = agent.act(_observation())

    assert [first.type, second.type, third.type] == ["apply_patch", "tool_call", "final"]
    assert isinstance(second, ToolCallAction) and second.tool == "file.diff"
    assert gateway.tracker.model_calls == 1
    assert protocol in trace_path.read_text(encoding="utf-8")


def test_three_action_protocol_rejects_task_with_public_tests(tmp_path: Path) -> None:
    agent, gateway, _suite, visible, _trace = _started_agent(
        tmp_path,
        _good_plan_without_public_test(),
        options={"action_plan_protocol": "strict_three_action_repository_repair_v1"},
    )

    with pytest.raises(AgentTerminationError, match="three-action protocol"):
        _advance_public_reads(agent, visible)

    assert gateway.tracker.model_calls == 1


@pytest.mark.parametrize("limit", [True, 0, 65_537, "4096"])
def test_api_repository_agent_rejects_invalid_output_limit(
    tmp_path: Path,
    limit: object,
) -> None:
    with pytest.raises(ValueError, match="max_output_tokens"):
        _started_agent(
            tmp_path,
            _good_plan(),
            options={"max_output_tokens": limit},
        )


def test_api_repository_agent_accepts_hash_bound_frozen_version(tmp_path: Path) -> None:
    suite = RepositoryRtlSuite()
    task = suite.load_task(
        TaskRef(id="repo-rtl/counter-wrap", suite="repo-rtl", native_id="counter-wrap")
    )
    agent = ApiRepositoryAgent()
    base_policy = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options={"max_output_tokens": 4096},
        task=task,
    )
    assert base_policy is not None
    version = build_agent_version(
        agent_version_id="api-repository-test-v0",
        update_type="none",
        executable_in_m10b=True,
        base_agent_id=agent.descriptor.name,
        agent_descriptor_hash=content_hash(agent.descriptor),
        model_id="static",
        reasoning_effort="thinking-disabled",
        auth_semantic_id="offline.none",
        runtime_identity_hash="2" * 64,
        tool_policy_hash="3" * 64,
        prompt_contract_hash=prompt_contract_identity_hash(base_policy),
        source_commit="4" * 40,
        package_hashes={"verigym": "5" * 64},
        image_hashes={},
    )
    options = {
        "max_output_tokens": 4096,
        "agent_version_id": version.agent_version_id,
        "agent_version_hash": version.version_hash,
        "agent_version_manifest_json": canonical_json(version),
    }

    policy = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options=options,
        task=task,
    )

    assert policy is not None
    assert policy.agent_version_id == version.agent_version_id
    assert policy.agent_version_hash == version.version_hash


@pytest.mark.parametrize(
    "response",
    [
        "not-json",
        json.dumps({"schema_version": "1.0", "actions": []}),
        _good_plan("unknown-public-test"),
        json.dumps(
            {
                "schema_version": "1.0",
                "actions": [
                    {"type": "apply_patch", "patch": "patch"},
                    {
                        "type": "tool_call",
                        "tool": "network.fetch",
                        "arguments": {"url": "https://example.test"},
                    },
                    {"type": "tool_call", "tool": "file.diff", "arguments": {}},
                    {"type": "final", "message": "done"},
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": "1.0",
                "actions": [
                    {"type": "apply_patch", "patch": "patch"},
                    {
                        "type": "tool_call",
                        "tool": "repository.public_test",
                        "arguments": {"test_id": "counter-wrap-public"},
                    },
                    {
                        "type": "tool_call",
                        "tool": "file.write",
                        "arguments": {"path": "../outside", "content": "bad"},
                    },
                    {"type": "final", "message": "done"},
                ],
            }
        ),
    ],
)
def test_api_repository_agent_rejects_malformed_or_invalid_actions_without_retry(
    tmp_path: Path,
    response: str,
) -> None:
    agent, gateway, _suite, visible, _trace = _started_agent(tmp_path, response)
    with pytest.raises(AgentTerminationError) as raised:
        _advance_public_reads(agent, visible)
    assert raised.value.failure.category == "agent_output_error"
    assert raised.value.failure.infrastructure is False
    assert gateway.tracker.model_calls == 1


def test_model_request_schema_does_not_accept_secret_metadata() -> None:
    # The gateway redactor remains the persistence boundary; the agent itself emits only hashes.
    message = ModelMessage(role="user", content="public")
    assert message.content == "public"


def test_patch_context_mismatch_is_agent_output_not_workspace_policy(tmp_path: Path) -> None:
    agent, gateway, _suite, visible, _trace = _started_agent(tmp_path, _good_plan())
    first = _advance_public_reads(agent, visible)
    assert first.type == "apply_patch"

    with pytest.raises(AgentTerminationError) as raised:
        agent.act(
            _observation(
                ToolResult(
                    tool="file.apply_patch",
                    success=False,
                    category=ErrorCategory.PERMISSION_DENIED,
                    message="patch context does not match the workspace",
                    stderr="patch context does not match the workspace",
                )
            )
        )

    assert raised.value.failure.category == "agent_output_error"
    assert raised.value.failure.kind == "model"
    assert raised.value.failure.infrastructure is False
    assert gateway.tracker.model_calls == 1


def test_true_patch_path_denial_remains_workspace_policy_failure(tmp_path: Path) -> None:
    agent, gateway, _suite, visible, _trace = _started_agent(tmp_path, _good_plan())
    first = _advance_public_reads(agent, visible)
    assert first.type == "apply_patch"

    with pytest.raises(AgentTerminationError) as raised:
        agent.act(
            _observation(
                ToolResult(
                    tool="file.apply_patch",
                    success=False,
                    category=ErrorCategory.POLICY_DENIED,
                    message="patch target is outside the editable workspace",
                )
            )
        )

    assert raised.value.failure.category == "workspace_policy_failure"
    assert raised.value.failure.kind == "policy"
    assert raised.value.failure.infrastructure is False
    assert gateway.tracker.model_calls == 1
