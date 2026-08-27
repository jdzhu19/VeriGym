from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _config_module() -> ModuleType:
    path = Path(__file__).parents[1] / "src" / "verigym_openhands" / "config.py"
    spec = importlib.util.spec_from_file_location("verigym_openhands_test_config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _hwe_config_module() -> ModuleType:
    path = Path(__file__).parents[1] / "src" / "verigym_openhands" / "hwe_config.py"
    spec = importlib.util.spec_from_file_location("verigym_openhands_test_hwe_config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_openhands_pin_and_tool_isolation_are_static() -> None:
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    source = (root / "src" / "verigym_openhands" / "agent.py").read_text(encoding="utf-8")

    assert "openhands-sdk==1.42.1" in pyproject
    assert "tools=[]" in source
    assert "include_default_tools=[]" in source
    assert "plugins=[]" in source
    assert "client_tools=[]" in source
    assert "repository_tool_definitions" in source
    assert "conversation.arun()" in source
    assert "conversation.agent.tools_map" in source
    assert "sorted(agent.tools_map)" not in source
    assert "timeout=settings.process_timeout_s" in source
    assert "TerminalTool" not in source
    assert "FileEditor" not in source
    assert "docker.sock" not in source
    assert "bridge.workspace_root" not in source


def test_openhands_safe_configuration_contains_no_endpoint_or_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VERIGYM_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("VERIGYM_MODEL_API_KEY", "test-only-key")

    settings = _config_module().openhands_settings(
        {"model_id": "local/Qwen3.5-9B"}, task_wall_time_s=100
    )
    safe = settings.safe_dict()

    assert "127.0.0.1" not in str(safe)
    assert "test-only-key" not in str(safe)
    assert safe["include_default_tools"] == []
    assert safe["workspace_policy"] == "private_empty_non_repository"
    assert safe["capture_training_transcript"] is False


def test_openhands_transcript_capture_is_training_only(monkeypatch) -> None:
    monkeypatch.setenv("VERIGYM_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("VERIGYM_MODEL_API_KEY", "test-only-key")
    module = _config_module()

    with pytest.raises(ValueError, match="training-only"):
        module.openhands_settings(
            {
                "model_id": "local/Qwen3.5-9B",
                "campaign_role": "development",
                "capture_training_transcript": True,
            },
            task_wall_time_s=100,
        )

    settings = module.openhands_settings(
        {
            "model_id": "local/Qwen3.5-9B",
            "campaign_role": "training",
            "capture_training_transcript": True,
        },
        task_wall_time_s=100,
    )
    assert settings.capture_training_transcript is True


def test_openhands_hwe_backend_is_static_and_training_gated(monkeypatch) -> None:
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    source = (root / "src" / "verigym_openhands" / "hwe_agent.py").read_text(encoding="utf-8")
    mcp = (root / "src" / "verigym_openhands" / "hwe_mcp_stdio.py").read_text(encoding="utf-8")

    assert "openhands-hwe-agent" in pyproject
    assert "include_default_tools=[]" in source
    assert "plugins=[]" in source
    assert "client_tools=[]" in source
    assert "tool_concurrency_limit=1" in source
    assert "native_tool_calling=True" in source
    assert "num_retries=0" in source
    assert 'litellm_extra_body={"thinking": {"type": "disabled"}}' in source
    assert 'settings.tool_choice_policy == "required"' in source
    assert "RequiredToolChoiceLLM" in source
    assert 'settings.tool_choice_policy == "recovery_forced_finish"' in source
    assert "RecoveryForcedFinishLLM" in source
    assert 'settings.tool_choice_policy == "recovery_state_forced_finish_v6"' in source
    assert "RecoveryStateForcedFinishLLM" in source
    assert 'settings.tool_choice_policy == "validated_recovery_state_forced_finish_v7"' in source
    assert "ValidatedRecoveryStateForcedFinishLLM" in source
    assert '"validated_recovery_state_forced_finish_v8"' in source
    assert '"validated_responses_recovery_state_forced_finish_v9"' in source
    assert "ValidatedResponsesRecoveryStateForcedFinishLLM" in source
    assert '"openhands_hwe_recovery_tool_choice_violation"' in source
    assert '"recovery_forced_request_count"' in source
    assert '"recovery_validated_finish_count"' in source
    assert source.index("if recovery_protocol_failure:") < source.index("if not stats.finished:")
    assert "DeepSeekHarnessHweBroker" in source
    assert "HookConfig" in source
    assert 'with_name("hwe_stop_hook.py")' in source
    assert "hook_config=hook_config" in source
    assert "deepseek_harness_tool_definitions" in mcp
    assert 'f"PYTHONPATH={mcp_pythonpath}"' in source
    assert '"openhands_sdk_hwe_prompt_policy_bound"' in source
    assert '"openhands_sdk_hwe_episode_failed"' in source
    assert '"openhands_sdk_hwe_post_episode_failed"' in source
    assert '"openhands_sdk_identity_observed"' in source
    assert source.index("def persist_evidence(") < source.index("if not stats.finished:")
    assert "ordinary_hidden_verifier_pending=False" in source
    assert '"openhands_hwe_prompt_policy_bound"' not in source
    assert '"openhands_hwe_identity_observed"' not in source
    assert "conversation.agent.tools_map" in source
    assert "sorted(agent.tools_map)" not in source
    assert "TerminalTool" not in source
    assert "FileEditor" not in source
    assert "docker.sock" not in source

    monkeypatch.setenv("VERIGYM_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("VERIGYM_MODEL_API_KEY", "test-only-key")
    module = _hwe_config_module()
    settings = module.resolve_hwe_settings(
        {
            "model_id": "local/Qwen3.5-9B",
            "campaign_role": "training",
            "capture_training_transcript": True,
            "max_iterations": 200,
            "max_context_tokens": 65_536,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "tool_choice_policy": "required",
        },
        task_wall_time_s=4200,
    )
    assert settings.max_iterations == 200
    assert settings.max_context_tokens == 65_536
    assert settings.capture_training_transcript is True
    assert settings.tool_choice_policy == "required"
    assert settings.safe_dict()["tool_choice_policy"] == "required"
    assert settings.safe_dict()["format_recovery_budget"] == 1
    assert settings.safe_dict()["whole_episode_retries"] == 0
    assert settings.safe_dict()["termination_authority"] == "broker_typed_finish"
    assert "127.0.0.1" not in str(settings.safe_dict())
    assert "test-only-key" not in str(settings.safe_dict())

    with pytest.raises(ValueError, match="training-only"):
        module.resolve_hwe_settings(
            {
                "model_id": "local/Qwen3.5-9B",
                "campaign_role": "development",
                "capture_training_transcript": True,
            },
            task_wall_time_s=100,
        )


def test_openhands_hwe_tool_choice_defaults_to_historical_auto(monkeypatch) -> None:
    monkeypatch.setenv("VERIGYM_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("VERIGYM_MODEL_API_KEY", "test-only-key")
    module = _hwe_config_module()

    settings = module.resolve_hwe_settings(
        {"model_id": "local/Qwen3.5-9B"},
        task_wall_time_s=100,
    )
    assert settings.tool_choice_policy == "auto"

    recovery = module.resolve_hwe_settings(
        {
            "model_id": "local/Qwen3.5-9B",
            "tool_choice_policy": "recovery_state_forced_finish_v6",
        },
        task_wall_time_s=100,
    )
    assert recovery.tool_choice_policy == "recovery_state_forced_finish_v6"

    validated = module.resolve_hwe_settings(
        {
            "model_id": "local/Qwen3.5-9B",
            "tool_choice_policy": "validated_recovery_state_forced_finish_v7",
        },
        task_wall_time_s=100,
    )
    assert validated.tool_choice_policy == "validated_recovery_state_forced_finish_v7"

    wrapped = module.resolve_hwe_settings(
        {
            "model_id": "local/Qwen3.5-9B",
            "tool_choice_policy": "validated_recovery_state_forced_finish_v8",
        },
        task_wall_time_s=100,
    )
    assert wrapped.tool_choice_policy == "validated_recovery_state_forced_finish_v8"

    responses = module.resolve_hwe_settings(
        {
            "model_id": "local/Qwen3.5-9B",
            "tool_choice_policy": "validated_responses_recovery_state_forced_finish_v9",
        },
        task_wall_time_s=100,
    )
    assert responses.tool_choice_policy == "validated_responses_recovery_state_forced_finish_v9"

    with pytest.raises(ValueError, match="unsupported"):
        module.resolve_hwe_settings(
            {
                "model_id": "local/Qwen3.5-9B",
                "tool_choice_policy": "best-effort",
            },
            task_wall_time_s=100,
        )


def test_openhands_hwe_mcp_pythonpath_is_explicit_and_bounded(monkeypatch, tmp_path: Path) -> None:
    from verigym_openhands.hwe_agent import _configured_mcp_pythonpath

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv("VERIGYM_OPENHANDS_MCP_PYTHONPATH", f"{first}{os.pathsep}{second}")
    assert _configured_mcp_pythonpath() == f"{first}{os.pathsep}{second}"

    monkeypatch.setenv("VERIGYM_OPENHANDS_MCP_PYTHONPATH", "relative")
    with pytest.raises(ValueError, match="absolute"):
        _configured_mcp_pythonpath()


def test_openhands_hwe_identity_classifies_mcp_events_once() -> None:
    from verigym_openhands.hwe_agent import _identity
    from verigym_openhands.hwe_config import OpenHandsHweSettings

    settings = OpenHandsHweSettings(
        model_id="openai/deepseek-v4-flash",
        base_url_env="VERIGYM_MODEL_BASE_URL",
        api_key_env="VERIGYM_MODEL_API_KEY",
        max_iterations=200,
        process_timeout_s=4200.0,
        max_output_tokens=2048,
        max_context_tokens=65_536,
        seed=484,
        campaign_role="training",
        capture_training_transcript=True,
        tool_choice_policy="required",
        agent_version_id=None,
        agent_version_hash=None,
        configuration_fingerprint="a" * 64,
    )

    identity = _identity(settings, tool_calls=17, patches=1)

    assert identity.tool_event_count == 17
    assert identity.mcp_tool_event_count == 17
    assert identity.side_effecting_tool_event_count == 0
    assert identity.read_only_tool_event_count == 0
    assert identity.external_network_tool_event_count == 0
    assert identity.workspace_write_count == 1
    assert identity.harness_id == "openhands-sdk-1.42.1-hwe-native-shell-v3"
    assert identity.tool_use_policy == "repository_action_state_machine_required_tool_v3"

    adaptive = settings.__class__(
        **{
            **settings.__dict__,
            "tool_choice_policy": "recovery_forced_finish",
        }
    )
    adaptive_identity = _identity(adaptive, tool_calls=18, patches=1)
    assert adaptive_identity.harness_id == "openhands-sdk-1.42.1-hwe-native-shell-v4"
    assert (
        adaptive_identity.tool_use_policy
        == "repository_action_state_machine_recovery_forced_finish_v4"
    )

    merged_adaptive = settings.__class__(
        **{
            **settings.__dict__,
            "tool_choice_policy": "recovery_forced_finish_v5",
        }
    )
    merged_identity = _identity(merged_adaptive, tool_calls=18, patches=1)
    assert merged_identity.harness_id == "openhands-sdk-1.42.1-hwe-native-shell-v5"
    assert (
        merged_identity.tool_use_policy
        == "repository_action_state_machine_recovery_forced_finish_merged_v5"
    )

    state_adaptive = settings.__class__(
        **{
            **settings.__dict__,
            "tool_choice_policy": "recovery_state_forced_finish_v6",
        }
    )
    state_identity = _identity(state_adaptive, tool_calls=18, patches=1)
    assert state_identity.harness_id == "openhands-sdk-1.42.1-hwe-native-shell-v6"
    assert (
        state_identity.tool_use_policy
        == "repository_action_state_machine_recovery_state_forced_finish_v6"
    )

    validated_state = settings.__class__(
        **{
            **settings.__dict__,
            "tool_choice_policy": "validated_recovery_state_forced_finish_v7",
        }
    )
    validated_identity = _identity(validated_state, tool_calls=18, patches=1)
    assert validated_identity.harness_id == "openhands-sdk-1.42.1-hwe-native-shell-v7"
    assert (
        validated_identity.tool_use_policy
        == "repository_action_state_machine_validated_recovery_finish_v7"
    )

    wrapped_state = settings.__class__(
        **{
            **settings.__dict__,
            "tool_choice_policy": "validated_recovery_state_forced_finish_v8",
        }
    )
    wrapped_identity = _identity(wrapped_state, tool_calls=18, patches=1)
    assert wrapped_identity.harness_id == "openhands-sdk-1.42.1-hwe-native-shell-v8"
    assert (
        wrapped_identity.tool_use_policy
        == "repository_action_state_machine_validated_recovery_finish_v8"
    )

    responses_state = settings.__class__(
        **{
            **settings.__dict__,
            "tool_choice_policy": "validated_responses_recovery_state_forced_finish_v9",
        }
    )
    responses_identity = _identity(responses_state, tool_calls=18, patches=1)
    assert responses_identity.harness_id == "openhands-sdk-1.42.1-hwe-native-shell-v10"
    assert (
        responses_identity.tool_use_policy
        == "repository_action_state_machine_validated_responses_recovery_"
        "masked_invalid_arguments_v10"
    )


def test_openhands_hwe_finds_wrapped_recovery_violation() -> None:
    from verigym_openhands.hwe_agent import _exception_chain_contains
    from verigym_openhands.hwe_tool_choice import RecoveryToolChoiceViolation

    inner = RecoveryToolChoiceViolation("test-only")
    outer = RuntimeError("wrapper")
    outer.__cause__ = inner

    assert _exception_chain_contains(outer, RecoveryToolChoiceViolation) is True
    assert _exception_chain_contains(outer, ValueError) is False
