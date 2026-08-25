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
    assert "DeepSeekHarnessHweBroker" in source
    assert "deepseek_harness_tool_definitions" in mcp
    assert 'f"PYTHONPATH={mcp_pythonpath}"' in source
    assert '"openhands_sdk_hwe_prompt_policy_bound"' in source
    assert '"openhands_sdk_identity_observed"' in source
    assert '"openhands_hwe_prompt_policy_bound"' not in source
    assert '"openhands_hwe_identity_observed"' not in source
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
        },
        task_wall_time_s=4200,
    )
    assert settings.max_iterations == 200
    assert settings.max_context_tokens == 65_536
    assert settings.capture_training_transcript is True
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
