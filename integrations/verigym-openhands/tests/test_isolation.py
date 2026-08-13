from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _config_module() -> ModuleType:
    path = Path(__file__).parents[1] / "src" / "verigym_openhands" / "config.py"
    spec = importlib.util.spec_from_file_location("verigym_openhands_test_config", path)
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
