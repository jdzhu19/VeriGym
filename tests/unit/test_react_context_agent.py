from __future__ import annotations

import pytest

from verigym.agents.react import VersionedContextReActAgent
from verigym.core.episode import BudgetTracker
from verigym.core.hashing import canonical_json, content_hash
from verigym.evolution.memory import build_agent_version, build_memory_pack
from verigym.prompts.builder import PromptBuilder
from verigym.prompts.policy import prompt_contract_identity_hash, resolve_prompt_policy
from verigym.schemas.agent import Observation
from verigym.schemas.common import InteractionMode
from verigym.suites.toy_rtl.adapter import ToyRtlSuite


def _memory():
    return build_memory_pack(
        {
            "principles": ["Confirm observable behavior before making a focused change."],
            "public_test_strategy": ["Use bounded public feedback before finalizing."],
            "workspace_policy_reminders": ["Keep edits inside the declared editable workspace."],
            "debugging_checklist": ["Check reset, control priority, boundaries, and recovery."],
            "patch_discipline": ["Review a minimal coherent diff before finishing."],
        }
    )


def _versions():
    agent = VersionedContextReActAgent()
    suite = ToyRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    neutral = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options={},
        task=task,
    )
    assert neutral is not None
    common = {
        "status": "frozen",
        "executable_in_m10b": True,
        "base_agent_id": agent.descriptor.name,
        "agent_descriptor_hash": content_hash(agent.descriptor),
        "model_id": "test-model",
        "reasoning_effort": "not-applicable",
        "auth_semantic_id": "test.auth.env.v1",
        "runtime_identity_hash": "1" * 64,
        "tool_policy_hash": "2" * 64,
        "prompt_contract_hash": prompt_contract_identity_hash(neutral),
        "source_commit": "3" * 40,
        "package_hashes": {"verigym": "4" * 64},
        "image_hashes": {},
        "model_weights_modified": False,
    }
    v0 = build_agent_version(
        **common,
        agent_version_id="react-context-v0",
        parent_version_hash=None,
        update_type="none",
    )
    memory = _memory()
    v1 = build_agent_version(
        **common,
        agent_version_id="react-context-v1",
        parent_version_hash=v0.version_hash,
        update_type="context_memory",
        training_dataset_hash="5" * 64,
        reward_schema_hash="6" * 64,
        reward_profile_hash="7" * 64,
        memory_builder_identity_hash="8" * 64,
        memory_pack_hash=memory.content_hash,
    )
    return agent, task, v0, v1, memory


def _options(version, memory=None):
    values = {
        "agent_version_id": version.agent_version_id,
        "agent_version_hash": version.version_hash,
        "agent_version_manifest_json": canonical_json(version),
    }
    if memory is not None:
        values["memory_pack"] = memory.model_dump(mode="json")
    return values


def test_versioned_react_prompt_injects_only_hash_bound_v1_memory() -> None:
    agent, task, v0, v1, memory = _versions()
    v0_policy = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options=_options(v0),
        task=task,
    )
    v1_policy = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options=_options(v1, memory),
        task=task,
    )
    assert v0_policy is not None and v1_policy is not None
    assert v0_policy.memory_pack_hash is None
    assert v1_policy.memory_pack_hash == memory.content_hash
    assert v0_policy.configuration_fingerprint != v1_policy.configuration_fingerprint
    assert prompt_contract_identity_hash(v0_policy) == prompt_contract_identity_hash(v1_policy)

    observation = Observation(
        task_id=task.id,
        task_description=task.description,
        visible_files=["README.md"],
        selected_files={"README.md": "Visible instructions only."},
        remaining_budget=BudgetTracker(task.budget).remaining(),
        policy_reminders=["Hidden verifier assets are inaccessible."],
        episode_status="running",
    )
    baseline = PromptBuilder(
        InteractionMode.AGENT,
        descriptor=v0_policy,
    ).initial_messages(task, observation)
    evolved = PromptBuilder(
        InteractionMode.AGENT,
        descriptor=v1_policy,
        memory_pack=memory,
    ).initial_messages(task, observation)
    assert memory.content_hash not in baseline[0].content
    assert memory.content_hash in evolved[0].content
    assert memory.sections[0].items[0] in evolved[0].content
    assert "must_not_write_to_candidate_workspace" in evolved[0].content

    with pytest.raises(ValueError, match="requires its frozen memory pack"):
        PromptBuilder(InteractionMode.AGENT, descriptor=v1_policy)
