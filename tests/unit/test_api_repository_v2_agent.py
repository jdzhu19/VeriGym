from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.agents.api_repository_v2 import ProviderNeutralApiRepositoryAgent
from verigym.agents.base import AgentContext, AgentTerminationError
from verigym.core.episode import BudgetTracker
from verigym.core.model_gateway import ModelGateway
from verigym.core.trace import TraceWriter
from verigym.models.static import StaticModelClient
from verigym.prompts.policy import resolve_prompt_policy
from verigym.protocols.repository_action import resolve_repository_action_protocol
from verigym.schemas.agent import BudgetRemaining, Observation, ToolCallAction
from verigym.schemas.common import ErrorCategory, InteractionMode
from verigym.schemas.task import TaskRef
from verigym.schemas.tool import ToolResult
from verigym.suites.repo_api_protocol.adapter import RepositoryApiProtocolSuite


def _response(action: str, arguments: dict[str, object]) -> str:
    return json.dumps(
        {
            "protocol": "repository_action.v2",
            "action": action,
            "arguments": arguments,
        },
        separators=(",", ":"),
    )


def _observation(previous: ToolResult | None = None) -> Observation:
    return Observation(
        task_id="repo-api-protocol/protocol-valid-hold",
        remaining_budget=BudgetRemaining(
            turns=20,
            tool_calls=40,
            wall_time_s=300,
            model_calls=6,
        ),
        previous_tool_result=previous,
        episode_status="running",
    )


def _started(
    tmp_path: Path,
    responses: list[str],
    *,
    max_completion_calls: int = 6,
) -> tuple[ProviderNeutralApiRepositoryAgent, ModelGateway, RepositoryApiProtocolSuite, Path]:
    suite = RepositoryApiProtocolSuite()
    task = suite.load_task(
        TaskRef(
            id="repo-api-protocol/protocol-valid-hold",
            suite="repo-api-protocol",
            native_id="protocol-valid-hold",
        )
    )
    assets = suite.resolve_assets(task)
    agent = ProviderNeutralApiRepositoryAgent()
    options = {
        "action_protocol": "repository_action.v2",
        "action_transport": "json_content",
        "max_completion_calls": max_completion_calls,
        "max_response_bytes": 262_144,
    }
    gateway = ModelGateway(
        run_id="repository-action-v2-fixture",
        client=StaticModelClient(name="repository-action-v2-static", responses=responses),
        trace=TraceWriter(tmp_path / "trace.jsonl", "repository-action-v2-fixture"),
        tracker=BudgetTracker(task.budget),
        max_visible_bytes=task.budget.max_output_bytes_per_tool,
    )
    prompt = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options=options,
        task=task,
    )
    protocol = resolve_repository_action_protocol(
        agent_descriptor=agent.descriptor,
        protocol_spec=agent.action_protocol_spec,
        agent_options=options,
        task=task,
    )
    agent.start(
        AgentContext(
            run_id="repository-action-v2-fixture",
            task=task,
            seed=4,
            model_gateway=gateway,
            agent_options=options,
            prompt_policy=prompt,
            action_protocol=protocol,
        )
    )
    return agent, gateway, suite, Path(assets.visible_root)


def _advance_bootstrap(agent: ProviderNeutralApiRepositoryAgent, visible: Path):  # type: ignore[no-untyped-def]
    action = agent.act(_observation())
    for _ in range(4):
        assert isinstance(action, ToolCallAction) and action.tool == "file.read"
        path = str(action.arguments["path"])
        action = agent.act(
            _observation(
                ToolResult(
                    tool="file.read",
                    success=True,
                    category=ErrorCategory.SUCCESS,
                    stdout=(visible / path).read_text(encoding="utf-8"),
                )
            )
        )
    return action


@pytest.mark.parametrize(
    ("response", "subcategory"),
    [
        ("", "agent_empty_output"),
        ("not json", "agent_malformed_json"),
        ("prefix {}", "agent_extra_prose"),
        ("[]", "agent_non_object_json"),
        (json.dumps([{}, {}]), "agent_multiple_actions"),
        (
            json.dumps({"protocol": "repository_action.v2", "action": "exec", "arguments": {}}),
            "agent_unknown_action",
        ),
        (
            json.dumps(
                {
                    "protocol": "repository_action.v2",
                    "action": "read_file",
                    "arguments": {"path": 9},
                }
            ),
            "agent_invalid_arguments",
        ),
        (
            _response("run_public_test", {"test_id": "protocol-valid-hold-public"}),
            "agent_invalid_state_transition",
        ),
        (_response("finish", {"message": "premature"}), "agent_finish_invalid"),
    ],
)
def test_fake_provider_invalid_matrix_is_terminal_without_reprompt(
    tmp_path: Path, response: str, subcategory: str
) -> None:
    agent, gateway, _suite, visible = _started(tmp_path, [response])
    with pytest.raises(AgentTerminationError) as raised:
        _advance_bootstrap(agent, visible)
    assert raised.value.failure.category == "agent_output_error"
    assert raised.value.failure.protocol_error_subcategory == subcategory
    assert not raised.value.failure.infrastructure
    assert gateway.tracker.model_calls == 1
    assert agent.action_protocol_records()[-1].error_subcategory == subcategory


def test_fake_provider_multi_turn_valid_path_binds_each_tool_observation(tmp_path: Path) -> None:
    patch = (
        "--- a/repository/rtl/valid_register.sv\n"
        "+++ b/repository/rtl/valid_register.sv\n"
        "@@ -1,1 +1,1 @@\n-old\n+new\n"
    )
    responses = [
        _response("read_file", {"path": "repository/rtl/valid_register.sv"}),
        _response("apply_patch", {"patch": patch}),
        _response("run_public_test", {"test_id": "protocol-valid-hold-public"}),
        _response("inspect_diff", {}),
        _response("finish", {"message": "candidate frozen"}),
    ]
    agent, gateway, _suite, visible = _started(tmp_path, responses)
    read = _advance_bootstrap(agent, visible)
    assert isinstance(read, ToolCallAction) and read.tool == "file.read"
    apply = agent.act(
        _observation(
            ToolResult(
                tool="file.read",
                success=True,
                category=ErrorCategory.SUCCESS,
                stdout=(visible / "repository/rtl/valid_register.sv").read_text(encoding="utf-8"),
            )
        )
    )
    assert apply.type == "apply_patch"
    public = agent.act(
        _observation(
            ToolResult(
                tool="file.apply_patch",
                success=True,
                category=ErrorCategory.SUCCESS,
                message="patch applied",
            )
        )
    )
    assert public.type == "tool_call" and public.tool == "repository.public_test"
    diff = agent.act(
        _observation(
            ToolResult(
                tool="repository.public_test",
                success=False,
                category=ErrorCategory.TEST_FAILED,
                message="public test failed with bounded feedback",
            )
        )
    )
    assert diff.type == "tool_call" and diff.tool == "file.diff"
    finish = agent.act(
        _observation(
            ToolResult(
                tool="file.diff",
                success=True,
                category=ErrorCategory.SUCCESS,
                stdout=patch,
            )
        )
    )
    assert finish.type == "final"
    records = agent.action_protocol_records()
    assert len(records) == 5
    assert [record.action_name for record in records] == [
        "read_file",
        "apply_patch",
        "run_public_test",
        "inspect_diff",
        "finish",
    ]
    assert all(record.accepted for record in records)
    assert all(record.tool_result_hash for record in records[:-1])
    assert gateway.tracker.model_calls == 5


def test_patch_context_mismatch_is_precise_agent_argument_failure(tmp_path: Path) -> None:
    patch = (
        "--- a/repository/rtl/valid_register.sv\n"
        "+++ b/repository/rtl/valid_register.sv\n"
        "@@ -1,1 +1,1 @@\n-old\n+new\n"
    )
    agent, gateway, _suite, visible = _started(
        tmp_path,
        [
            _response("read_file", {"path": "repository/rtl/valid_register.sv"}),
            _response("apply_patch", {"patch": patch}),
        ],
    )
    _advance_bootstrap(agent, visible)
    agent.act(
        _observation(
            ToolResult(
                tool="file.read",
                success=True,
                category=ErrorCategory.SUCCESS,
                stdout="visible source",
            )
        )
    )
    with pytest.raises(AgentTerminationError) as raised:
        agent.act(
            _observation(
                ToolResult(
                    tool="file.apply_patch",
                    success=False,
                    category=ErrorCategory.PERMISSION_DENIED,
                    message="patch context does not match the workspace",
                )
            )
        )
    assert raised.value.failure.protocol_error_subcategory == "agent_invalid_arguments"
    assert gateway.tracker.model_calls == 2


def test_turn_budget_exhaustion_is_terminal_without_an_extra_provider_call(
    tmp_path: Path,
) -> None:
    agent, gateway, _suite, visible = _started(
        tmp_path,
        [_response("read_file", {"path": "repository/rtl/valid_register.sv"})],
        max_completion_calls=1,
    )
    read = _advance_bootstrap(agent, visible)
    assert isinstance(read, ToolCallAction) and read.tool == "file.read"
    with pytest.raises(AgentTerminationError) as raised:
        agent.act(
            _observation(
                ToolResult(
                    tool="file.read",
                    success=True,
                    category=ErrorCategory.SUCCESS,
                    stdout="visible source",
                )
            )
        )
    assert raised.value.failure.protocol_error_subcategory == "agent_turn_budget_exhausted"
    assert gateway.tracker.model_calls == 1


def test_action_after_finish_is_rejected_by_explicit_state_machine(tmp_path: Path) -> None:
    patch = (
        "--- a/repository/rtl/valid_register.sv\n"
        "+++ b/repository/rtl/valid_register.sv\n"
        "@@ -1,1 +1,1 @@\n-old\n+new\n"
    )
    responses = [
        _response("apply_patch", {"patch": patch}),
        _response("run_public_test", {"test_id": "protocol-valid-hold-public"}),
        _response("inspect_diff", {}),
        _response("finish", {"message": "candidate frozen"}),
        _response("read_file", {"path": "repository/README.md"}),
    ]
    agent, gateway, _suite, visible = _started(tmp_path, responses)
    apply = _advance_bootstrap(agent, visible)
    assert apply.type == "apply_patch"
    public = agent.act(
        _observation(
            ToolResult(
                tool="file.apply_patch",
                success=True,
                category=ErrorCategory.SUCCESS,
                message="patch applied",
            )
        )
    )
    assert public.type == "tool_call"
    diff = agent.act(
        _observation(
            ToolResult(
                tool="repository.public_test",
                success=True,
                category=ErrorCategory.SUCCESS,
            )
        )
    )
    assert diff.type == "tool_call"
    finish = agent.act(
        _observation(
            ToolResult(
                tool="file.diff",
                success=True,
                category=ErrorCategory.SUCCESS,
                stdout=patch,
            )
        )
    )
    assert finish.type == "final"
    with pytest.raises(AgentTerminationError) as raised:
        agent.act(_observation())
    assert raised.value.failure.protocol_error_subcategory == ("agent_invalid_state_transition")
    assert gateway.tracker.model_calls == 5
