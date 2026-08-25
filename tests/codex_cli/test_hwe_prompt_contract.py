from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym_codex_cli.agent import CodexCliHweAgentAdapter, _agent_prompt

from verigym.agents.base import AgentContext
from verigym.core.orchestrator import VeriGym
from verigym.registry.collections import build_registries

pytestmark = [pytest.mark.codex_cli, pytest.mark.codex_cli_agent]


def _prompt_payload(tmp_path: Path, *, hwe_collection: bool) -> dict[str, object]:
    task = VeriGym(build_registries(discover_external=False)).load_task("toy-rtl/and-gate-basic")[1]
    task = task.model_copy(
        update={"metadata": {"repository_repair": {"public_test_ids": ["public-zexth"]}}}
    )
    workspace = tmp_path / "visible"
    (workspace / "repository" / "core").mkdir(parents=True)
    (workspace / "TASK.md").write_text("Repair the decoder.\n", encoding="utf-8")
    (workspace / "repository" / "core" / "decoder.sv").write_text(
        "module decoder; endmodule\n", encoding="utf-8"
    )
    bridge = SimpleNamespace(
        workspace_root=workspace,
        editable_globs=("repository/core/**",),
        readonly_globs=("TASK.md",),
    )
    prompt = _agent_prompt(
        AgentContext(run_id="prompt-test", task=task, seed=0),
        bridge,
        hwe_collection=hwe_collection,
    )
    serialized = prompt[prompt.index("{") : prompt.rindex("}") + 1]
    payload = json.loads(serialized)
    assert isinstance(payload, dict)
    return payload


def test_hwe_prompt_exposes_local_diagnostics_without_unavailable_launcher(
    tmp_path: Path,
) -> None:
    payload = _prompt_payload(tmp_path, hwe_collection=True)
    repository = payload["repository_repair"]
    assert isinstance(repository, dict)
    assert repository["public_test_launcher"] == {
        "available": False,
        "execution_owner": "verigym_after_submission",
        "model_access": "unavailable",
    }
    assert repository["local_diagnostics"] == {
        "available_commands": ["rg", "make", "verilator"],
        "repository_scripts": "allowed within workspace policy",
    }
    instructions = payload["instructions"]
    assert isinstance(instructions, list)
    assert any("launcher and verifier assets are unavailable" in line for line in instructions)
    assert all("verigym-public-test run <test-id>" not in line for line in instructions)


def test_non_hwe_repository_prompt_preserves_public_launcher_contract(tmp_path: Path) -> None:
    payload = _prompt_payload(tmp_path, hwe_collection=False)
    repository = payload["repository_repair"]
    assert isinstance(repository, dict)
    assert repository["public_test_launcher"] == {
        "assets": "trusted read-only mount; direct asset access is forbidden",
        "list": ["verigym-public-test", "list"],
        "run": ["verigym-public-test", "run", "<test-id>"],
        "test_ids": ["public-zexth"],
    }


def test_hwe_prompt_change_has_a_distinct_frozen_identity() -> None:
    spec = CodexCliHweAgentAdapter.prompt_policy_spec
    assert spec.prompt_contract_id == "codex_cli_hwe_native_shell_context_v9"
    assert spec.prompt_contract_version == "9.0.0"
    assert spec.base_instruction_policy == "hwe_native_shell_base_instructions_v9"


def test_hwe_prompt_declares_container_native_reads_and_workspace_only_candidate(
    tmp_path: Path,
) -> None:
    payload = _prompt_payload(tmp_path, hwe_collection=True)
    assert payload["collection_profile_id"] == "hwe_standard_v2"
    assert payload["observation_policy_id"] == "hwe_repository_observation_v2"
    contract = payload["native_shell_contract"]
    assert isinstance(contract, dict)
    assert contract["parent_paths"] == "allowed"
    assert contract["absolute_container_paths"] == "allowed"
    assert contract["candidate_write_scope"] == "/workspace/repository"
    assert contract["ephemeral_write_scope"] == "/tmp"
    workspace_policy = payload["workspace_policy"]
    assert isinstance(workspace_policy, dict)
    assert workspace_policy["outside_workspace_access"] == ("isolated_container_read_only_allowed")
    instructions = payload["instructions"]
    assert isinstance(instructions, list)
    assert any("find .." in instruction for instruction in instructions)
    assert any("source paths begin with repository/" in instruction for instruction in instructions)
    assert any("direct filesystem-write" in instruction for instruction in instructions)
    assert any("Do not embed full file contents" in instruction for instruction in instructions)
    assert any("Do not probe environment variables" in instruction for instruction in instructions)
    assert any("Never issue an empty" in instruction for instruction in instructions)
    assert any(
        "Do not assign shell or environment variables" in instruction
        for instruction in instructions
    )
    assert any("never use a heredoc to reproduce" in instruction for instruction in instructions)
    assert any(
        "single interrupt of a stalled known process" in instruction for instruction in instructions
    )
    assert any("never run shell commands or edits in parallel" in line for line in instructions)
