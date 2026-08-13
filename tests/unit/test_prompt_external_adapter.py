from __future__ import annotations

from tests.milestone9_helpers import offline_service
from verigym.agents.repository_scripted import ScriptedRepositoryGoodAgent
from verigym.core.hashing import content_hash
from verigym.prompts.policy import prompt_contract_identity_hash, resolve_prompt_policy
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor
from verigym.schemas.evolution import AgentVersionManifest
from verigym.schemas.prompt import AgentPromptPolicySpec


class _AdapterBackedAgent(ScriptedRepositoryGoodAgent):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="adapter-backed-agent",
        version="1.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="tests",
        capabilities=["repository_repair"],
    )
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="adapter_backed_prompt_v1",
        prompt_contract_version="1.0.0",
        task_context_policy="public_repository_context_v1",
        base_instruction_policy="repository_tools_v1",
        content_visibility_policy="public_only_v1",
        max_prompt_bytes=100_000,
        max_task_context_bytes=50_000,
        versioned_context_allowed=True,
    )


def test_external_adapter_version_can_bind_a_memory_free_prompt() -> None:
    agent = _AdapterBackedAgent()
    service = offline_service()
    _suite, task, _assets = service.load_task("repo-rtl/counter-wrap")
    mode = task.interaction.supported_modes[0]
    neutral = resolve_prompt_policy(
        interaction_mode=mode,
        agent=agent,
        agent_options={},
        task=task,
    )
    assert neutral is not None
    base = {
        "agent_version_id": "adapter-policy-v1",
        "status": "frozen",
        "parent_version_hash": "1" * 64,
        "update_type": "external_adapter",
        "executable_in_m10b": False,
        "base_agent_id": agent.descriptor.name,
        "agent_descriptor_hash": content_hash(agent.descriptor),
        "model_id": "Qwen/Qwen3.5-9B-adapter-v1",
        "reasoning_effort": "xhigh",
        "auth_semantic_id": "local-openai-compatible",
        "runtime_identity_hash": "2" * 64,
        "tool_policy_hash": "3" * 64,
        "prompt_contract_hash": prompt_contract_identity_hash(neutral),
        "source_commit": "4" * 40,
        "package_hashes": {},
        "image_hashes": {},
        "training_dataset_hash": "5" * 64,
        "model_weights_modified": False,
    }
    draft = AgentVersionManifest.model_construct(**base, version_hash="0" * 64)
    identity = draft.model_dump(mode="json", exclude={"version_hash"})
    version = AgentVersionManifest.model_validate({**base, "version_hash": content_hash(identity)})

    policy = resolve_prompt_policy(
        interaction_mode=mode,
        agent=agent,
        agent_options={
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": version.model_dump_json(),
        },
        task=task,
    )

    assert policy is not None
    assert policy.agent_version_hash == version.version_hash
    assert policy.memory_pack_hash is None
