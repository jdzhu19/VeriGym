from __future__ import annotations

from verigym.core.environment import VeriGymEnv
from verigym.core.episode import EpisodeState, TerminationReason
from verigym.core.trace import TraceWriter, read_trace
from verigym.registry.collections import build_registries
from verigym.schemas.agent import FinalSubmissionAction, MessageAction, ToolCallAction
from verigym.schemas.common import ErrorCategory, InteractionMode
from verigym.suites.toy_rtl.adapter import ToyRtlSuite


def make_environment(
    tmp_path,
    *,
    max_turns: int = 20,
    mode: InteractionMode = InteractionMode.AGENT,
) -> tuple[VeriGymEnv, TraceWriter]:
    registries = build_registries(discover_external=False)
    suite = ToyRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    task.budget.max_turns = max_turns
    assets = suite.resolve_assets(task)
    env = VeriGymEnv(
        task=task,
        assets=assets,
        runtime=registries.runtimes.get("local"),
        tools=registries.tools,
        mode=mode,
    )
    return env, TraceWriter(tmp_path / "trace.jsonl", "run-test")


def test_environment_never_materializes_hidden_assets(tmp_path) -> None:
    env, trace = make_environment(tmp_path)
    try:
        observation, _ = env.reset(run_id="run-test", trace=trace)
        assert all(not path.startswith("hidden") for path in observation.visible_files)
        assert env.session is not None
        assert not (env.session.root / "hidden").exists()
        observation, _, terminated, truncated, _ = env.step(
            ToolCallAction(tool="file.read", arguments={"path": "hidden/tb_counter.sv"})
        )
        assert not terminated and not truncated
        assert observation.previous_tool_result is not None
        assert observation.previous_tool_result.category == ErrorCategory.PERMISSION_DENIED
        assert "module tb_counter" not in observation.model_dump_json()
    finally:
        env.close()


def test_disallowed_tool_is_a_structured_policy_failure(tmp_path) -> None:
    env, trace = make_environment(tmp_path)
    try:
        env.reset(run_id="run-test", trace=trace)
        observation, _, _, _, _ = env.step(
            ToolCallAction(
                tool="file.write",
                arguments={"path": "rtl/counter.v", "content": "not allowed"},
            )
        )
        assert observation.previous_tool_result is not None
        assert observation.previous_tool_result.category == ErrorCategory.POLICY_DENIED
        assert env.tracker is not None and env.tracker.failed_tool_calls == 1
    finally:
        env.close()


def test_chat_eval_denies_every_tool_before_execution(tmp_path) -> None:
    env, trace = make_environment(tmp_path, mode=InteractionMode.CHAT)
    try:
        env.reset(run_id="run-test", trace=trace)
        observation, _, terminated, truncated, _ = env.step(
            ToolCallAction(tool="file.read", arguments={"path": "README.md"})
        )
        assert not terminated and not truncated
        assert observation.previous_tool_result is not None
        assert observation.previous_tool_result.category == ErrorCategory.POLICY_DENIED
        assert env.tracker is not None
        assert env.tracker.tool_calls == 0
        assert env.tracker.failed_tool_calls == 1
        events = read_trace(tmp_path / "trace.jsonl", expected_run_id="run-test")
        assert "tool_request" not in [event.event_type for event in events]
        assert any(
            event.event_type == "agent_action_rejected"
            and event.payload["category"] == "chat_tool_policy"
            for event in events
        )
    finally:
        env.close()


def test_turn_budget_truncates_with_structured_reason(tmp_path) -> None:
    env, trace = make_environment(tmp_path, max_turns=1)
    try:
        observation, _ = env.reset(run_id="run-test", trace=trace)
        observation, _, terminated, truncated, _ = env.step(MessageAction(message="one"))
        assert not terminated and not truncated
        _, _, terminated, truncated, info = env.step(MessageAction(message="two"))
        assert not terminated and truncated
        assert info["termination_reason"] == TerminationReason.TURN_BUDGET_EXHAUSTED.value
        assert env.state == EpisodeState.VERIFYING
    finally:
        env.close()


def test_final_action_ends_visible_episode_without_running_verifier(tmp_path) -> None:
    env, trace = make_environment(tmp_path)
    try:
        env.reset(run_id="run-test", trace=trace)
        _, _, terminated, truncated, info = env.step(FinalSubmissionAction())
        assert terminated and not truncated
        assert info["termination_reason"] == "final_submission"
        events = read_trace(tmp_path / "trace.jsonl", expected_run_id="run-test")
        assert "verifier_started" not in [event.event_type for event in events]
    finally:
        env.close()
