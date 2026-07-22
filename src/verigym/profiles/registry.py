"""Strict registry for declared toolchain profiles."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.resources import files

import yaml

from verigym.core.errors import ConfigurationError, DuplicatePluginError, PluginNotFoundError
from verigym.schemas.common import ToolchainProfile


class ToolchainProfileRegistry:
    def __init__(self, profiles: Iterable[ToolchainProfile] = ()) -> None:
        self._profiles: dict[str, ToolchainProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ToolchainProfile) -> None:
        if profile.id in self._profiles:
            raise DuplicatePluginError(f"duplicate toolchain profile ID {profile.id!r}")
        self._profiles[profile.id] = profile.model_copy(deep=True)

    def get(self, profile_id: str) -> ToolchainProfile:
        try:
            return self._profiles[profile_id].model_copy(deep=True)
        except KeyError as exc:
            available = ", ".join(sorted(self._profiles)) or "none"
            raise PluginNotFoundError(
                f"toolchain profile {profile_id!r} is not registered; available: {available}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._profiles)

    def items(self) -> list[tuple[str, ToolchainProfile]]:
        return [(name, self.get(name)) for name in self.names()]


def builtin_profiles() -> ToolchainProfileRegistry:
    resource = files("verigym.profiles.builtins").joinpath("open_yosys_toy_area.yaml")
    try:
        payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
        profile = ToolchainProfile.model_validate(payload)
    except Exception as exc:
        raise ConfigurationError(f"built-in toolchain profile is invalid: {exc}") from exc
    return ToolchainProfileRegistry([profile])


__all__ = ["ToolchainProfileRegistry", "builtin_profiles"]
