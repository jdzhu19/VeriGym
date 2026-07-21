from __future__ import annotations

import pytest

from verigym.core.errors import DuplicatePluginError, PluginError, PluginNotFoundError
from verigym.registry import suite_registry, tool_registry
from verigym.registry.base import PluginRegistry
from verigym.schemas.common import PluginDescriptor


class DummyPlugin:
    def __init__(self, name: str, *, api_version: str = "1.0", provider: str = "tests") -> None:
        self.descriptor = PluginDescriptor(
            name=name,
            version="1.0.0",
            api_version=api_version,
            provider=provider,
        )


def test_registry_lists_and_loads_by_stable_slug() -> None:
    registry: PluginRegistry[DummyPlugin] = PluginRegistry("tests.plugins")
    plugin = DummyPlugin("alpha")
    registry.register(plugin)
    assert registry.names() == ["alpha"]
    assert registry.get("alpha") is plugin


def test_duplicate_plugin_ids_fail_with_both_origins() -> None:
    registry: PluginRegistry[DummyPlugin] = PluginRegistry("tests.plugins")
    registry.register(DummyPlugin("same", provider="first"))
    with pytest.raises(DuplicatePluginError, match="first and second"):
        registry.register(DummyPlugin("same", provider="second"))


def test_incompatible_and_missing_plugins_fail_clearly() -> None:
    registry: PluginRegistry[DummyPlugin] = PluginRegistry("tests.plugins")
    with pytest.raises(PluginError, match="requires 1.0"):
        registry.register(DummyPlugin("old", api_version="0.1"))
    with pytest.raises(PluginNotFoundError, match="available: none"):
        registry.get("missing")


def test_stable_lower_level_registry_imports_are_available() -> None:
    assert "toy-rtl" in suite_registry.names()
    assert "file.read" in tool_registry.names()
