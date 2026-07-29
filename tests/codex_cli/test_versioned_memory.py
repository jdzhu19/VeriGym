from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym_codex_cli import CodexCliAgentAdapter
from verigym_codex_cli.capabilities import runtime_capabilities
from verigym_codex_cli.config import agent_settings, readonly_agent_settings

from verigym.core.hashing import canonical_json
from verigym.core.orchestrator import VeriGym
from verigym.evolution.memory import build_agent_version, build_memory_pack
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.schemas import PlannedSystemIdentity
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.model import ModelRunConfig
from verigym.schemas.run import RunConfig

pytestmark = [pytest.mark.codex_cli, pytest.mark.codex_cli_agent]


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


def _version(memory):
    return build_agent_version(
        agent_version_id="codex-cli-agent-v1",
        status="frozen",
        parent_version_hash="1" * 64,
        update_type="context_memory",
        executable_in_m10b=True,
        base_agent_id="codex-cli-agent",
        agent_descriptor_hash="2" * 64,
        model_id="fake-model",
        reasoning_effort="xhigh",
        auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        runtime_identity_hash="3" * 64,
        tool_policy_hash="4" * 64,
        prompt_contract_hash="5" * 64,
        source_commit="53b0755715a876432ddcdface143632278ccddd3",
        package_hashes={"verigym": "6" * 64, "plugin": "7" * 64},
        image_hashes={"agent": "8" * 64, "verifier": "9" * 64},
        training_dataset_hash="a" * 64,
        reward_schema_hash="b" * 64,
        reward_profile_hash="c" * 64,
        memory_builder_identity_hash="d" * 64,
        memory_pack_hash=memory.content_hash,
        model_weights_modified=False,
    )


def test_track_b_versioned_context_is_hash_bound_and_track_a_rejects_it(
    fake_codex: tuple[Path, Path, object],
) -> None:
    _executable, _log, _scenario = fake_codex
    _identity, capabilities = runtime_capabilities()
    memory = _memory()
    version = _version(memory)
    settings = agent_settings(
        {
            "model_id": "fake-model",
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": canonical_json(version),
            "memory_pack": memory.model_dump(mode="json"),
        },
        capabilities,
        task_wall_time_s=300,
    )
    assert settings.agent_version_id == "codex-cli-agent-v1"
    assert settings.agent_version_hash == version.version_hash
    assert settings.memory_pack_hash == memory.content_hash
    assert settings.safe_configuration(capabilities)["memory_pack_hash"] == memory.content_hash

    with pytest.raises(ValueError, match="invalid versioned memory"):
        agent_settings(
            {
                "model_id": "fake-model",
                "agent_version_id": version.agent_version_id,
                "agent_version_hash": version.version_hash,
                "agent_version_manifest_json": canonical_json(version),
                "memory_pack": {
                    **memory.model_dump(mode="json"),
                    "content_hash": "b" * 64,
                },
            },
            capabilities,
            task_wall_time_s=300,
        )
    with pytest.raises(ValueError, match="unsupported Codex CLI read-only agent options"):
        readonly_agent_settings(
            {
                "model_id": "fake-model",
                "agent_version_id": "codex-cli-agent-v1",
                "agent_version_hash": version.version_hash,
                "agent_version_manifest_json": canonical_json(version),
                "memory_pack": memory.model_dump(mode="json"),
            },
            capabilities,
            task_wall_time_s=300,
        )


def test_external_agent_prompt_contract_identity_excludes_versioned_memory() -> None:
    descriptor = CodexCliAgentAdapter().descriptor

    def planned(options):
        return PlannedSystemIdentity(
            system_id="codex-cli-agent",
            agent_id="codex-cli-agent",
            agent_descriptor=descriptor,
            agent_configuration_hash="a" * 64,
            agent_options=options,
            agent_requires_model=False,
            model_options=ModelRunConfig(),
        )

    base = {
        "prompt_contract_id": "codex_cli_workspace_verilog_task_context_v1",
    }
    first = ExperimentPlanner._prompt_policy(  # noqa: SLF001 - deterministic contract fixture
        planned(base),
        InteractionMode.AGENT,
    )
    second = ExperimentPlanner._prompt_policy(  # noqa: SLF001
        planned(
            {
                **base,
                "agent_version_hash": "b" * 64,
                "memory_pack": _memory().model_dump(mode="json"),
            }
        ),
        InteractionMode.AGENT,
    )
    assert first is not None
    assert first == second
    assert first.id == "codex_cli_workspace_verilog_task_context_v1"


@pytest.mark.requires_iverilog
def test_frozen_memory_is_a_separate_read_only_prompt_artifact(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("agent_good")
    memory = _memory()
    version = _version(memory)
    registries = build_registries(discover_external=False)
    registries.agents.register(CodexCliAgentAdapter())
    result = VeriGym(registries).run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            agent="codex-cli-agent",
            agent_options={
                "model_id": "fake-model",
                "agent_version_id": version.agent_version_id,
                "agent_version_hash": version.version_hash,
                "agent_version_manifest_json": canonical_json(version),
                "memory_pack": memory.model_dump(mode="json"),
            },
            output=tmp_path / "runs",
        )
    )
    assert result.scorecard.resolved
    records = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "model"
    ]
    assert len(records) == 1
    prompt = records[0]["prompt"]
    assert "<verigym_agent_memory" in prompt
    assert memory.content_hash in prompt
    assert "must_not_write_to_candidate_repository" in prompt
    assert not any(
        "memory" in path.name.casefold() for path in (result.run_dir / "candidate").rglob("*")
    )
