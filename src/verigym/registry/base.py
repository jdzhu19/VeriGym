"""Typed plugin registry with Python entry-point discovery."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Generic, Literal, Protocol, TypeVar

from verigym.core.errors import DuplicatePluginError, PluginError, PluginNotFoundError
from verigym.schemas.base import PLUGIN_API_VERSION
from verigym.schemas.common import PluginDescriptor


class DescribedPlugin(Protocol):
    @property
    def descriptor(self) -> PluginDescriptor: ...


PluginT = TypeVar("PluginT", bound=DescribedPlugin)


@dataclass(frozen=True)
class PluginOrigin:
    package: str | None
    version: str | None
    entry_point: str | None
    registration: Literal["builtin", "entry_point", "runtime"]


@dataclass(frozen=True)
class PluginDiagnostic:
    group: str
    entry_point: str
    value: str
    status: Literal["loaded", "rejected"]
    origin: PluginOrigin
    message: str


class PluginRegistry(Generic[PluginT]):
    """Store plugins by stable slug and discover optional external providers."""

    def __init__(self, group: str) -> None:
        self.group = group
        self._plugins: dict[str, PluginT] = {}
        self._origins: dict[str, PluginOrigin] = {}
        self._diagnostics: list[PluginDiagnostic] = []

    def register(self, plugin: PluginT, *, origin: PluginOrigin | None = None) -> None:
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
        self._origins[descriptor.name] = origin or PluginOrigin(
            package=None,
            version=None,
            entry_point=None,
            registration="runtime",
        )

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

    def origin(self, name: str) -> PluginOrigin:
        self.get(name)
        return self._origins[name]

    def diagnostics(self) -> list[PluginDiagnostic]:
        return list(self._diagnostics)

    def discover(self, *, strict: bool = False) -> None:
        """Load entry points independently and retain safe rejection diagnostics."""

        entry_points = sorted(
            metadata.entry_points().select(group=self.group),
            key=lambda item: (item.name, item.value),
        )
        for entry_point in entry_points:
            distribution = getattr(entry_point, "dist", None)
            origin = PluginOrigin(
                package=(
                    str(distribution.metadata.get("Name"))
                    if distribution is not None and distribution.metadata.get("Name")
                    else None
                ),
                version=(
                    str(distribution.version)
                    if distribution is not None and distribution.version
                    else None
                ),
                entry_point=entry_point.name,
                registration="entry_point",
            )
            try:
                loaded = entry_point.load()
                plugin = loaded() if isinstance(loaded, type) else loaded
                self.register(plugin, origin=origin)
                diagnostic = PluginDiagnostic(
                    group=self.group,
                    entry_point=entry_point.name,
                    value=entry_point.value,
                    status="loaded",
                    origin=origin,
                    message=f"registered plugin {plugin.descriptor.name!r}",
                )
                self._diagnostics.append(diagnostic)
            except PluginError as exc:
                diagnostic = PluginDiagnostic(
                    group=self.group,
                    entry_point=entry_point.name,
                    value=entry_point.value,
                    status="rejected",
                    origin=origin,
                    message=str(exc)[:1024],
                )
                self._diagnostics.append(diagnostic)
                if strict:
                    raise
            except Exception as exc:
                error = PluginError(
                    f"failed loading entry point {entry_point.name!r} "
                    f"from {entry_point.value}: {type(exc).__name__}"
                )
                diagnostic = PluginDiagnostic(
                    group=self.group,
                    entry_point=entry_point.name,
                    value=entry_point.value,
                    status="rejected",
                    origin=origin,
                    message=str(error),
                )
                self._diagnostics.append(diagnostic)
                if strict:
                    raise error from exc


__all__ = ["PluginDiagnostic", "PluginOrigin", "PluginRegistry"]
