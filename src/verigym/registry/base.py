"""Typed plugin registry with Python entry-point discovery."""

from __future__ import annotations

from importlib import metadata
from typing import Generic, Protocol, TypeVar

from verigym.core.errors import DuplicatePluginError, PluginError, PluginNotFoundError
from verigym.schemas.base import PLUGIN_API_VERSION
from verigym.schemas.common import PluginDescriptor


class DescribedPlugin(Protocol):
    @property
    def descriptor(self) -> PluginDescriptor: ...


PluginT = TypeVar("PluginT", bound=DescribedPlugin)


class PluginRegistry(Generic[PluginT]):
    """Store plugins by stable slug and discover optional external providers."""

    def __init__(self, group: str) -> None:
        self.group = group
        self._plugins: dict[str, PluginT] = {}

    def register(self, plugin: PluginT) -> None:
        descriptor = plugin.descriptor
        if descriptor.api_version != PLUGIN_API_VERSION:
            raise PluginError(
                f"plugin {descriptor.name!r} uses API {descriptor.api_version}; "
                f"VeriGym requires {PLUGIN_API_VERSION}"
            )
        if descriptor.name in self._plugins:
            incumbent = self._plugins[descriptor.name].descriptor
            raise DuplicatePluginError(
                f"duplicate plugin ID {descriptor.name!r}: "
                f"{incumbent.provider} and {descriptor.provider}"
            )
        self._plugins[descriptor.name] = plugin

    def get(self, name: str) -> PluginT:
        try:
            return self._plugins[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._plugins)) or "none"
            raise PluginNotFoundError(
                f"plugin {name!r} is not registered in {self.group}; available: {available}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._plugins)

    def items(self) -> list[tuple[str, PluginT]]:
        return [(name, self._plugins[name]) for name in sorted(self._plugins)]

    def discover(self) -> None:
        """Load plugins published under this registry's entry-point group."""

        for entry_point in metadata.entry_points().select(group=self.group):
            try:
                loaded = entry_point.load()
                plugin = loaded() if isinstance(loaded, type) else loaded
                self.register(plugin)
            except PluginError:
                raise
            except Exception as exc:
                raise PluginError(
                    f"failed loading entry point {entry_point.name!r} "
                    f"from {entry_point.value}: {exc}"
                ) from exc
