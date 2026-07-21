"""Plugin registries."""

from typing import Any

from verigym.registry.base import PluginRegistry
from verigym.registry.collections import Registries, build_registries

_defaults: Registries | None = None


def default_registries() -> Registries:
    """Return the process-wide built-in/external registry collection."""

    global _defaults
    if _defaults is None:
        _defaults = build_registries()
    return _defaults


class _RegistryProxy:
    def __init__(self, attribute: str) -> None:
        self._attribute = attribute

    def __getattr__(self, name: str) -> Any:
        registry = getattr(default_registries(), self._attribute)
        return getattr(registry, name)


suite_registry = _RegistryProxy("suites")
tool_registry = _RegistryProxy("tools")
agent_registry = _RegistryProxy("agents")
model_registry = _RegistryProxy("models")
runtime_registry = _RegistryProxy("runtimes")


__all__ = [
    "PluginRegistry",
    "Registries",
    "agent_registry",
    "build_registries",
    "default_registries",
    "model_registry",
    "runtime_registry",
    "suite_registry",
    "tool_registry",
]
