"""Strict loader for site-owned verifier transport profiles."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import yaml

from verigym.core.errors import ConfigurationError
from verigym.schemas.verifier_profile import VerifierToolProfile

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
            raise ConfigurationError(f"duplicate verifier-profile key: {key!r}")
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
            raise ConfigurationError(f"duplicate verifier-profile key: {key!r}")
        result[key] = value
    return result


def load_verifier_profile(path: str | Path) -> VerifierToolProfile:
    profile_path = Path(path).expanduser()
    try:
        metadata = os.lstat(profile_path)
    except OSError as exc:
        raise ConfigurationError(f"verifier profile is unavailable: {profile_path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError("verifier profile must be a regular, non-symlink file")
    if metadata.st_size > _MAX_PROFILE_BYTES:
        raise ConfigurationError("verifier profile exceeds the 1 MiB limit")
    raw = profile_path.read_bytes()
    if len(raw) != metadata.st_size:
        raise ConfigurationError("verifier profile changed while it was being read")
    try:
        text = raw.decode("utf-8")
        if profile_path.suffix.lower() == ".json":
            payload = json.loads(text, object_pairs_hook=_construct_unique_json)
        elif profile_path.suffix.lower() in {".yaml", ".yml"}:
            payload = yaml.load(text, Loader=_UniqueSafeLoader)
        else:
            raise ConfigurationError("verifier profile must use .json, .yaml, or .yml")
        return VerifierToolProfile.model_validate(payload)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"invalid verifier profile {profile_path}: {exc}") from exc


__all__ = ["load_verifier_profile"]
