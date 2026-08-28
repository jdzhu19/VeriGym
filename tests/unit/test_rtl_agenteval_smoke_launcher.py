from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from verigym_codex_cli.agenteval_agent import CodexCliAgentEvalAdapter

from tests.milestone9_helpers import offline_service
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig


def _launcher_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtl_agenteval_codex_smoke.py"
    spec = importlib.util.spec_from_file_location("rtl_agenteval_smoke_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts_path = str(path.parent)
    sys.path.insert(0, scripts_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


def test_launcher_preserves_all_prelaunch_agent_resolutions() -> None:
    launcher = _launcher_module()
    service = offline_service()
    service.registries.agents.register(CodexCliAgentEvalAdapter())
    runtime = service.registries.runtimes.get("local").descriptor
    config = RunConfig(
        task_id="repo-rtl/counter-wrap",
        mode=InteractionMode.AGENT,
        agent="codex-cli-agenteval-agent",
        agent_options={"max_completion_calls": 1},
        runtime="local",
    )

    frozen = launcher._freeze_run_config(
        service,
        config,
        runtime_descriptor=runtime,
        expected_profile=None,
    )

    assert frozen.expected_prompt_policy == frozen.resolved_prompt_policy
    assert frozen.expected_prompt_policy_hash == frozen.resolved_prompt_policy_hash
    assert frozen.expected_agent_configuration_hash == frozen.resolved_agent_configuration_hash
    assert frozen.expected_action_protocol == frozen.resolved_action_protocol
    assert frozen.expected_agent_feedback_contract == frozen.resolved_agent_feedback_contract


def test_commercial_diagnostic_scan_allows_only_local_mcp_configuration() -> None:
    launcher = _launcher_module()

    assert launcher._COMMERCIAL_DIAGNOSTIC.search(b"mcp_servers.verigym.command") is None
    assert launcher._COMMERCIAL_DIAGNOSTIC.search(b"mcp_server_profile_id") is not None
    assert launcher._COMMERCIAL_DIAGNOSTIC.search(b"license server unavailable") is not None
