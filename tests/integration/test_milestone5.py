from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from verigym.cli.app import app
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.core.trace import read_trace
from verigym.models.base import ModelClient
from verigym.models.openai_compatible import OpenAICompatibleModelClient
from verigym.models.static import COUNTER_GOOD_SOURCE, StaticModelClient, StaticResponseSpec
from verigym.registry.collections import Registries, build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.model import (
    ModelRequest,
    ModelResponse,
    ModelRunConfig,
    NormalizedModelUsage,
)
from verigym.schemas.run import RunConfig

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("iverilog") is None or shutil.which("vvp") is None,
        reason="Icarus Verilog is not installed",
    ),
]


def service(*models: ModelClient) -> VeriGym:
    registries = build_registries(discover_external=False)
    for model in models:
        registries.models.register(model)
    return VeriGym(registries)


def run_config(
    output: Path,
    *,
    mode: InteractionMode,
    agent: str,
    model: str,
    max_invalid_actions: int = 3,
) -> RunConfig:
    return RunConfig(
        task_id="toy-rtl/counter-basic",
        mode=mode,
        agent=agent,
        model=model,
        max_invalid_actions=max_invalid_actions,
        runtime="local",
        output=output,
    )


@pytest.mark.parametrize(
    "model_name",
    ["static-counter-good", "static-counter-good-fenced"],
)
def test_single_turn_raw_and_fenced_candidates_pass_in_exactly_one_call(
    tmp_path, model_name: str
) -> None:
    result = service().run(
        run_config(
            tmp_path / model_name,
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=model_name,
        )
    )
    assert result.scorecard.resolved
    assert result.scorecard.status == "completed"
    assert result.scorecard.efficiency.model_calls == 1
    assert result.scorecard.efficiency.tool_calls == 0
    assert result.manifest.model is not None
    assert result.manifest.model.name == model_name
    assert result.manifest.agent.name == "single-turn"
    assert result.manifest.agent_harness is not None
    assert result.manifest.agent_harness.name == "single-turn"
    assert result.manifest.interaction_mode == "chat"
    assert result.manifest.tool_policy is not None
    assert result.manifest.tool_policy.allowed_tools == []
    assert result.manifest.prompt_policy is not None
    assert result.manifest.model.name != result.manifest.agent_harness.name

    events = read_trace(result.run_dir / "trace.jsonl", expected_run_id=result.manifest.run_id)
    event_types = [event.event_type for event in events]
    assert event_types.count("model_request") == 1
    assert event_types.count("model_response") == 1
    assert event_types.count("agent_action_parsed") == 1
    assert "tool_request" not in event_types
    assert "final_submission" in event_types


def test_single_turn_incorrect_candidate_is_not_infrastructure_failure(tmp_path) -> None:
    result = service().run(
        run_config(
            tmp_path / "bad",
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model="static-counter-bad",
        )
    )
    assert not result.scorecard.resolved
    assert result.scorecard.status == "completed"
    assert not result.scorecard.correctness.infrastructure_error
    assert result.scorecard.failure is None
    assert result.scorecard.verifier_results[-1].error_category.value == "test_failed"
    assert result.scorecard.quality.ppa is None


@pytest.mark.parametrize(
    "output",
    [
        "",
        "```verilog\nmodule counter; endmodule\n```\n```verilog\nmodule second; endmodule\n```",
        "not RTL",
    ],
)
def test_single_turn_malformed_output_is_structured(tmp_path, output: str) -> None:
    model = StaticModelClient(name=f"test-malformed-{len(output)}", responses=[output])
    result = service(model).run(
        run_config(
            tmp_path / str(len(output)),
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=model.descriptor.name,
        )
    )
    assert not result.scorecard.resolved
    assert result.scorecard.status == "failed"
    assert result.scorecard.termination_reason == "model_output_invalid"
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.kind == "model"
    assert result.scorecard.failure.category == "invalid_output"
    assert result.scorecard.efficiency.model_calls == 1


def test_reference_react_runs_real_traced_and_accounted_loop(tmp_path) -> None:
    result = service().run(
        run_config(
            tmp_path / "react",
            mode=InteractionMode.AGENT,
            agent="react",
            model="static-react-counter-good",
        )
    )
    assert result.scorecard.resolved
    assert result.scorecard.efficiency.model_calls == 4
    assert result.scorecard.efficiency.tool_calls == 3
    assert result.scorecard.efficiency.turns == 4
    assert result.scorecard.efficiency.model_input_tokens == 80
    assert result.scorecard.efficiency.model_output_tokens == 120
    assert result.scorecard.efficiency.total_tokens == 200
    assert result.manifest.model is not None
    assert result.manifest.model.name == "static-react-counter-good"
    assert result.manifest.agent_harness is not None
    assert result.manifest.agent_harness.name == "react"
    assert result.manifest.tool_policy is not None
    assert "file.read" in result.manifest.tool_policy.allowed_tools
    candidate = (result.run_dir / "candidate" / "rtl" / "counter.v").read_text(encoding="utf-8")
    assert "q <= q + 8'h01" in candidate

    events = read_trace(result.run_dir / "trace.jsonl", expected_run_id=result.manifest.run_id)
    event_types = [event.event_type for event in events]
    assert event_types.count("model_request") == 4
    assert event_types.count("model_response") == 4
    assert event_types.count("agent_action_parsed") == 4
    assert event_types.count("tool_request") == 3
    assert event_types.count("tool_result") == 3
    assert "patch_applied" in event_types
    assert "file_changed" in event_types
    assert "final_submission" in event_types

    visible_artifacts = "\n".join(
        [
            (result.run_dir / "trace.jsonl").read_text(encoding="utf-8"),
            (result.run_dir / "logs" / "agent.log").read_text(encoding="utf-8"),
            (result.run_dir / "workspace_diff.patch").read_text(encoding="utf-8"),
        ]
    )
    for hidden_name in ("tb_counter.sv", "check_result.py", "module tb_counter"):
        assert hidden_name not in visible_artifacts
    assert not (result.run_dir / "candidate" / "hidden").exists()


def test_react_disallowed_tool_is_policy_denied_and_never_changes_workspace(tmp_path) -> None:
    model = StaticModelClient(
        name="test-react-disallowed",
        responses=[
            json.dumps(
                {
                    "type": "tool_call",
                    "tool": "file.write",
                    "arguments": {"path": "rtl/counter.v", "content": "malicious"},
                }
            ),
            json.dumps({"type": "final", "message": "done"}),
        ],
    )
    result = service(model).run(
        run_config(
            tmp_path / "disallowed",
            mode=InteractionMode.AGENT,
            agent="react",
            model=model.descriptor.name,
        )
    )
    assert not result.scorecard.resolved
    assert result.scorecard.efficiency.failed_tool_calls == 1
    assert result.scorecard.patch.changed_files == []
    events = read_trace(result.run_dir / "trace.jsonl")
    policy_results = [
        event
        for event in events
        if event.event_type == "tool_result" and event.payload.get("category") == "policy_denied"
    ]
    assert len(policy_results) == 1
    assert any(
        event.event_type == "agent_action_rejected"
        and event.payload.get("category") == "tool_policy"
        for event in events
    )


def test_react_repeated_malformed_actions_reach_invalid_limit(tmp_path) -> None:
    result = service().run(
        run_config(
            tmp_path / "malformed-react",
            mode=InteractionMode.AGENT,
            agent="react",
            model="static-react-malformed",
            max_invalid_actions=3,
        )
    )
    assert not result.scorecard.resolved
    assert result.scorecard.status == "failed"
    assert result.scorecard.termination_reason == "invalid_action_limit"
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "invalid_action_limit"
    assert result.scorecard.efficiency.model_calls == 3
    events = read_trace(result.run_dir / "trace.jsonl")
    rejected = [event for event in events if event.event_type == "agent_action_rejected"]
    assert [event.payload["invalid_count"] for event in rejected] == [1, 2, 3]
    requests = [event for event in events if event.event_type == "model_request"]
    assert "parser_feedback" in json.dumps(requests[-1].payload)


def test_model_client_failure_is_infrastructure_error_not_malformed_action(tmp_path) -> None:
    result = service().run(
        run_config(
            tmp_path / "model-error",
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model="static-exhausted",
        )
    )
    assert not result.scorecard.resolved
    assert result.scorecard.status == "error"
    assert result.scorecard.correctness.infrastructure_error
    assert result.scorecard.termination_reason == "model_error"
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "exhausted"
    events = read_trace(result.run_dir / "trace.jsonl")
    response = next(event for event in events if event.event_type == "model_response")
    assert response.payload["error"]["category"] == "exhausted"
    assert not any(event.event_type == "agent_action_parsed" for event in events)


class LimitedBudgetVeriGym(VeriGym):
    def __init__(self, registries: Registries, **limits: int) -> None:
        super().__init__(registries)
        self.limits = limits

    def load_task(self, task_id: str) -> tuple[Any, Any, Any]:
        suite, task, assets = super().load_task(task_id)
        for field, value in self.limits.items():
            setattr(task.budget, field, value)
        return suite, task, assets


@pytest.mark.parametrize(
    ("limits", "responses", "expected_reason", "expected_calls"),
    [
        (
            {"max_model_calls": 1},
            [
                '{"type":"tool_call","tool":"file.read","arguments":{"path":"rtl/counter.v"}}',
                '{"type":"final","message":"done"}',
            ],
            "model_budget_exhausted",
            1,
        ),
        (
            {"max_turns": 1},
            [
                '{"type":"tool_call","tool":"file.read","arguments":{"path":"rtl/counter.v"}}',
                '{"type":"final","message":"done"}',
            ],
            "turn_budget_exhausted",
            1,
        ),
        (
            {"max_tool_calls": 0},
            ['{"type":"tool_call","tool":"file.read","arguments":{"path":"rtl/counter.v"}}'],
            "tool_budget_exhausted",
            1,
        ),
        (
            {"max_total_tokens": 10},
            ['{"type":"final","message":"done"}'],
            "token_budget_exhausted",
            1,
        ),
    ],
)
def test_react_honors_model_turn_tool_and_token_budgets(
    tmp_path,
    limits: dict[str, int],
    responses: list[str],
    expected_reason: str,
    expected_calls: int,
) -> None:
    configured_responses: list[str | StaticResponseSpec] = list(responses)
    if expected_reason == "token_budget_exhausted":
        configured_responses = [
            StaticResponseSpec(
                text=responses[0],
                usage=NormalizedModelUsage(
                    input_tokens=8,
                    output_tokens=8,
                    total_tokens=16,
                ),
            )
        ]
    model = StaticModelClient(name=f"test-budget-{expected_reason}", responses=configured_responses)
    registries = build_registries(discover_external=False)
    registries.models.register(model)
    vg = LimitedBudgetVeriGym(registries, **limits)
    result = vg.run(
        run_config(
            tmp_path / expected_reason,
            mode=InteractionMode.AGENT,
            agent="react",
            model=model.descriptor.name,
        )
    )
    assert not result.scorecard.resolved
    assert result.scorecard.termination_reason == expected_reason
    assert result.scorecard.efficiency.model_calls == expected_calls


class CountingStaticModel(StaticModelClient):
    def __init__(self, calls: list[str]) -> None:
        super().__init__(name="test-replay-counting", responses=["module counter; endmodule"])
        self.calls = calls

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request.request_id)
        return super().generate(request)

    def clone_for_run(self, configuration: ModelRunConfig | None = None) -> CountingStaticModel:
        return CountingStaticModel(self.calls)


def test_replay_reverification_never_calls_model(tmp_path) -> None:
    calls: list[str] = []
    model = CountingStaticModel(calls)
    vg = service(model)
    result = vg.run(
        run_config(
            tmp_path / "replay",
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=model.descriptor.name,
        )
    )
    assert calls == [f"{result.manifest.run_id}-model-0001"]
    trace_before = (result.run_dir / "trace.jsonl").read_bytes()
    replay = replay_run(result.run_dir, verify=True, service=vg)
    assert replay.reverified_resolved is False
    assert calls == [f"{result.manifest.run_id}-model-0001"]
    assert (result.run_dir / "trace.jsonl").read_bytes() == trace_before


class ReplayIdentityProvider:
    def create_chat_completion(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        connect_timeout_s: float,
        read_timeout_s: float,
        request_timeout_s: float,
        max_response_bytes: int,
    ) -> Mapping[str, Any]:
        del (
            url,
            headers,
            payload,
            connect_timeout_s,
            read_timeout_s,
            request_timeout_s,
            max_response_bytes,
        )
        return {
            "id": "safe-provider-request",
            "model": "provider-replay-model",
            "choices": [{"message": {"content": COUNTER_GOOD_SOURCE}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }


def test_provider_backed_chat_run_replays_request_bindings(tmp_path) -> None:
    model = OpenAICompatibleModelClient(
        base_url="https://provider.example.test/v1",
        client_id="provider-replay",
        provider_id="provider-replay",
        model_id="provider-replay-model",
        api_key="test-only-key",
        thinking_mode="disabled",
        transport=ReplayIdentityProvider(),
    )
    result = service(model).run(
        run_config(
            tmp_path / "provider-replay",
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=model.descriptor.name,
        )
    )
    request = result.manifest.model_observations[0].provider_request
    assert request is not None
    assert request.prompt_policy_hash == result.manifest.prompt_policy_hash
    assert request.agent_configuration_hash == result.manifest.agent_configuration_hash
    assert result.manifest.model is not None
    assert result.manifest.model.configuration["thinking_mode"] == "disabled"
    assert replay_run(result.run_dir).scorecard.resolved


def test_chat_and_react_literal_cli_commands_and_plugin_discovery(tmp_path) -> None:
    runner = CliRunner()
    models = runner.invoke(app, ["models", "list"])
    agents = runner.invoke(app, ["agents", "list"])
    assert models.exit_code == 0
    assert "static-counter-good" in models.output
    assert agents.exit_code == 0
    assert "single-turn" in agents.output
    assert "react" in agents.output

    commands = [
        (
            "chat",
            "single-turn",
            "static-counter-good",
            tmp_path / "cli-chat",
        ),
        (
            "agent",
            "react",
            "static-react-counter-good",
            tmp_path / "cli-react",
        ),
    ]
    for mode, agent, model, output in commands:
        result = runner.invoke(
            app,
            [
                "run",
                "--suite",
                "toy-rtl",
                "--task",
                "counter-basic",
                "--mode",
                mode,
                "--agent",
                agent,
                "--model",
                model,
                "--runtime",
                "local",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "PASS toy-rtl/counter-basic" in result.output
