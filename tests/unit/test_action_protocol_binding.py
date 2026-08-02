from __future__ import annotations

from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import (
    BatchRunner,
    _child_config,
    _maximum_model_api_calls,
    _validate_execution_plan,
)
from verigym.experiments.schemas import ExperimentConfig


def _config(output: Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "name": "repository action protocol binding",
            "suite": {
                "id": "repo-api-protocol",
                "tasks": {
                    "include": ["repo-api-protocol/protocol-valid-hold"],
                    "exclude": [],
                },
            },
            "runs": {"mode": "agent", "seeds": [3], "samples_per_task": 1},
            "systems": [
                {
                    "id": "provider-neutral-api-v2",
                    "agent": {
                        "id": "provider-neutral-api-repository-agent",
                        "options": {
                            "action_protocol": "repository_action.v2",
                            "action_transport": "json_content",
                            "max_completion_calls": 6,
                            "max_response_bytes": 262144,
                        },
                    },
                    "model": {"id": "openai-compatible"},
                }
            ],
            "runtime": {"id": "local"},
            "execution": {"max_workers": 1, "max_model_processes": 1},
            "output": {"root": output},
        }
    )


def test_planner_and_batch_prelaunch_independently_bind_protocol(tmp_path: Path) -> None:
    planner = ExperimentPlanner()
    plan = planner.build(_config(tmp_path / "experiment"))
    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.action_protocol is not None
    assert item.action_protocol.protocol_id == "repository_action.v2"
    assert item.action_protocol.action_transport == "json_content"
    assert item.action_protocol.max_completion_calls == 6
    config = _child_config(
        tmp_path / "experiment",
        item,
        "binding-child",
        plan.experiment_id,
    )
    resolved = BatchRunner(planner=planner)._resolve_child_execution_contract(item, config)
    assert resolved.expected_action_protocol == item.action_protocol
    assert resolved.resolved_action_protocol == item.action_protocol


def test_batch_prelaunch_rejects_transport_or_registry_identity_drift(tmp_path: Path) -> None:
    planner = ExperimentPlanner()
    plan = planner.build(_config(tmp_path / "experiment"))
    item = plan.items[0]
    config = _child_config(
        tmp_path / "experiment",
        item,
        "binding-child",
        plan.experiment_id,
    )
    drifted = config.model_copy(
        update={
            "agent_options": {
                **config.agent_options,
                "action_transport": "native_tool_call",
            }
        }
    )
    with pytest.raises(ConfigurationError, match="agent execution configuration"):
        BatchRunner(planner=planner)._resolve_child_execution_contract(item, drifted)

    assert item.action_protocol is not None
    tampered_item = item.model_copy(
        update={
            "action_protocol": item.action_protocol.model_copy(
                update={"action_registry_hash": "f" * 64}
            )
        }
    )
    with pytest.raises(ConfigurationError, match="action_registry_hash"):
        BatchRunner(planner=planner)._resolve_child_execution_contract(tampered_item, config)


def test_strict_multi_turn_campaign_requires_exact_reserved_api_call_budget(
    tmp_path: Path,
) -> None:
    base = _config(tmp_path / "experiment")
    strict_execution = base.execution.model_copy(
        update={
            "max_model_processes": 1,
            "resume_model_process_policy": "never_rerun_after_authorization",
            "seal_plan_before_execution": True,
            "frozen_campaign_identity": {"protocol": "repository_action.v2"},
        }
    )
    planner = ExperimentPlanner()
    missing_budget = planner.build(base.model_copy(update={"execution": strict_execution}))
    assert _maximum_model_api_calls(missing_budget.items[0]) == 6
    with pytest.raises(ConfigurationError, match="exact model API-call budget"):
        _validate_execution_plan(missing_budget)

    frozen = planner.build(
        base.model_copy(
            update={"execution": strict_execution.model_copy(update={"max_model_api_calls": 6})}
        )
    )
    _validate_execution_plan(frozen)
