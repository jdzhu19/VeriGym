from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.milestone9_helpers import experiment_config, offline_service
from verigym.agents.base import AgentContext
from verigym.agents.scripted import ScriptedAgent
from verigym.core.errors import ConfigurationError
from verigym.core.orchestrator import VeriGym
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import PlanItem
from verigym.prompts.policy import resolve_prompt_policy, validate_prompt_policy_binding
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor
from verigym.schemas.prompt import AgentPromptPolicySpec, PromptPolicyDescriptor
from verigym.schemas.run import RunConfig, RunResult


class PromptedScriptedAgent(ScriptedAgent):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="prompted-scripted",
        version="1.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-tests",
        capabilities=["deterministic", "prompt_binding_fixture"],
    )
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="test_agent_execution_prompt_v1",
        prompt_contract_version="1.0.0",
        task_context_policy="public_toy_task_context_v1",
        base_instruction_policy="test_scripted_instructions_v1",
        content_visibility_policy="public_task_only_v1",
        max_prompt_bytes=65_536,
        max_task_context_bytes=32_768,
    )

    def __init__(self) -> None:
        super().__init__()
        self.observed_context: AgentContext | None = None

    def start(self, context: AgentContext) -> None:
        self.observed_context = context
        super().start(context)


def _service(agent: PromptedScriptedAgent) -> VeriGym:
    service = offline_service()
    service.registries.agents.register(agent)
    return service


def test_historical_probe2_null_child_prompt_remains_incompatible() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures" / "prompt_policy" / "historical_probe2_null.json"
        ).read_text(encoding="utf-8")
    )
    expected = PromptPolicyDescriptor.model_validate(fixture["plan_prompt_policy"])
    assert (
        fixture["historical_bundle_sha256sums_sha256"]
        == "fd549b7e064aabdad1c2e07630de62f8e424a9a4c368d7df71813c048def8188"
    )
    assert all(
        len(fixture[field]) == 64
        for field in (
            "historical_plan_jsonl_sha256",
            "historical_child_manifest_sha256",
            "historical_plan_item_id",
        )
    )
    assert fixture["model_calls_during_binding_check"] == 0
    with pytest.raises(ValueError, match="prompt policy mismatch: descriptor, hash"):
        validate_prompt_policy_binding(
            expected=expected,
            expected_hash=fixture["plan_prompt_policy_hash"],
            resolved=fixture["child_prompt_policy"],
            resolved_hash=fixture["child_prompt_policy_hash"],
        )


def test_ordinary_run_supplies_resolved_policy_to_harness_and_manifest(
    tmp_path: Path,
) -> None:
    agent = PromptedScriptedAgent()
    service = _service(agent)
    config = experiment_config(
        tmp_path / "experiment",
        tasks=["and-gate-basic"],
        systems=[{"id": "prompted", "agent": {"id": agent.descriptor.name}}],
        seeds=[0],
    )
    planner = ExperimentPlanner(service)
    captured: list[RunConfig] = []

    def child(_item: PlanItem, run_config: RunConfig) -> RunResult:
        captured.append(run_config)
        return service.run(run_config)

    batch = BatchRunner(planner=planner, child_executor=child).run(planner.build(config))
    assert batch.exit_code == 0
    assert len(captured) == 1
    assert captured[0].expected_prompt_policy == captured[0].resolved_prompt_policy
    assert captured[0].expected_prompt_policy_hash == captured[0].resolved_prompt_policy_hash
    run = next((batch.experiment_dir / "runs").iterdir())
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    prompt = PromptPolicyDescriptor.model_validate(manifest["prompt_policy"])
    assert prompt.resolver_id == "agent_execution_prompt_policy_v1"
    assert manifest["prompt_policy_hash"] == prompt.configuration_fingerprint
    assert manifest["agent_configuration_hash"] is not None
    assert agent.observed_context is not None
    assert agent.observed_context.prompt_policy == prompt


def test_descriptor_hashes_public_context_without_persisting_sensitive_text() -> None:
    agent = PromptedScriptedAgent()
    service = _service(agent)
    _suite, task, _assets = service.load_task("toy-rtl/and-gate-basic")
    marker = "CREDENTIAL-MARKER reference/hidden/path"
    policy = resolve_prompt_policy(
        interaction_mode=task.interaction.supported_modes[0],
        agent=agent,
        agent_options={},
        task=task.model_copy(update={"description": marker}),
    )
    assert policy is not None
    assert marker not in json.dumps(policy.model_dump(mode="json"))


def test_batch_resolves_policy_before_model_process_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = PromptedScriptedAgent()
    service = _service(agent)
    config = experiment_config(
        tmp_path / "experiment",
        tasks=["and-gate-basic"],
        systems=[{"id": "prompted", "agent": {"id": agent.descriptor.name}}],
        seeds=[0],
    )
    config = config.model_copy(
        update={
            "execution": config.execution.model_copy(
                update={"max_model_processes": 1, "seal_plan_before_execution": True}
            )
        }
    )
    planner = ExperimentPlanner(service)
    plan = planner.build(config)
    assert plan.items[0].prompt_policy is not None
    monkeypatch.setattr(
        PromptedScriptedAgent,
        "prompt_policy_spec",
        agent.prompt_policy_spec.model_copy(
            update={"base_instruction_policy": "mutated_after_plan"}
        ),
    )
    runner = BatchRunner(planner=planner, service_factory=lambda: service)
    with pytest.raises(ConfigurationError, match="prompt policy mismatch"):
        runner.run(plan)
    assert not (config.output.root / "process-ledger.jsonl").read_text(encoding="utf-8")
