from __future__ import annotations

import pytest

rllm = pytest.importorskip("rllm")

from rllm.engine import ModelOutput  # noqa: E402
from rllm.tools.tool_base import ToolCall  # noqa: E402

from verigym_training_reference.repository_workflow import (  # noqa: E402
    VeriGymRepositoryAgent,
)


def test_repository_agent_binds_complete_model_output_to_step() -> None:
    agent = VeriGymRepositoryAgent()
    agent.update_from_env(
        {"visible_files": ["repository/a.sv"]},
        0.0,
        False,
        {
            "initial": True,
            "task": {
                "task_id": "suite/task",
                "task_description": "repair it",
                "record_hash": "a" * 64,
            },
            "prompt_contract": {"protocol": "repository_action.v2"},
            "public_test_ids": [],
            "observation_truncated": False,
        },
    )
    output = ModelOutput(
        text="native call",
        content="",
        tool_calls=[ToolCall(name="finish", arguments={"message": "done"})],
        prompt_ids=[1, 2, 3],
        completion_ids=[4, 5],
        logprobs=[-0.1, -0.2],
        prompt_logprobs=[None, -0.3, -0.4],
        weight_version=7,
    )

    agent.bind_model_output(output)
    action = agent.update_from_model("")
    step = agent.trajectory.steps[0]

    assert action.action["name"] == "finish"
    assert step.model_output is output
    assert step.prompt_ids == [1, 2, 3]
    assert step.response_ids == [4, 5]
    assert step.logprobs == [-0.1, -0.2]
    assert step.weight_version == 7
    assert step.chat_completions[-1]["tool_calls"][0]["id"].startswith("call_")
