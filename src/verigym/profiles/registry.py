"""Strict registry for declared toolchain profiles."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from verigym.core.errors import ConfigurationError, DuplicatePluginError, PluginNotFoundError
from verigym.schemas.common import ToolchainProfile

_MAX_PROFILE_BYTES = 1024 * 1024


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueSafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ConfigurationError(f"duplicate toolchain-profile key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _construct_unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate toolchain-profile key: {key!r}")
        result[key] = value
    return result


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

    def load_file(self, path: str | Path) -> ToolchainProfile:
        profile_path = Path(path).expanduser()
        try:
            metadata = os.lstat(profile_path)
        except OSError as exc:
            raise ConfigurationError(f"toolchain profile is unavailable: {profile_path}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ConfigurationError("toolchain profile must be a regular, non-symlink file")
        if metadata.st_size > _MAX_PROFILE_BYTES:
            raise ConfigurationError("toolchain profile exceeds the 1 MiB limit")
        raw = profile_path.read_bytes()
        if len(raw) != metadata.st_size:
            raise ConfigurationError("toolchain profile changed while it was being read")
        try:
            text = raw.decode("utf-8")
            if profile_path.suffix.lower() == ".json":
                payload = json.loads(text, object_pairs_hook=_construct_unique_json)
            elif profile_path.suffix.lower() in {".yaml", ".yml"}:
                payload = yaml.load(text, Loader=_UniqueSafeLoader)
            else:
                raise ConfigurationError("toolchain profile must use .json, .yaml, or .yml")
            profile = ToolchainProfile.model_validate(payload)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError(f"invalid toolchain profile {profile_path}: {exc}") from exc
        self.register(profile)
        return profile.model_copy(deep=True)


def builtin_profiles() -> ToolchainProfileRegistry:
    resource = files("verigym.profiles.builtins").joinpath("open_yosys_toy_area.yaml")
    try:
        payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
        profile = ToolchainProfile.model_validate(payload)
    except Exception as exc:
        raise ConfigurationError(f"built-in toolchain profile is invalid: {exc}") from exc
    return ToolchainProfileRegistry([profile])


__all__ = ["ToolchainProfileRegistry", "builtin_profiles"]
