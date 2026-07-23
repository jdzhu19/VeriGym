"""Bounded, duplicate-key-safe experiment configuration loading."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import yaml

from verigym.core.errors import ConfigurationError
from verigym.core.schema_compat import validate_schema_version
from verigym.experiments.schemas import ExperimentConfig

_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_DEPTH = 32
_MAX_CONTAINER_ITEMS = 100_000


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
        try:
            duplicate = key in result
        except TypeError as exc:
            raise ConfigurationError("experiment mappings require scalar keys") from exc
        if duplicate:
            raise ConfigurationError(f"duplicate experiment configuration key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate experiment configuration key: {key!r}")
        result[key] = value
    return result


def _validate_shape(value: Any, *, depth: int = 0, seen: set[int] | None = None) -> int:
    if depth > _MAX_DEPTH:
        raise ConfigurationError(f"experiment configuration exceeds depth {_MAX_DEPTH}")
    if isinstance(value, (dict, list)):
        seen = seen or set()
        identity = id(value)
        if identity in seen:
            raise ConfigurationError("recursive YAML aliases are not permitted")
        seen.add(identity)
        if isinstance(value, dict):
            count = len(value)
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ConfigurationError("experiment configuration keys must be strings")
                count += _validate_shape(item, depth=depth + 1, seen=seen)
        else:
            count = len(value)
            for item in value:
                count += _validate_shape(item, depth=depth + 1, seen=seen)
        seen.remove(identity)
        if count > _MAX_CONTAINER_ITEMS:
            raise ConfigurationError("experiment configuration contains too many values")
        return count
    return 1


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    """Load one strict JSON/YAML experiment without executing plugins or tools."""

    config_path = Path(path).expanduser()
    try:
        metadata = os.lstat(config_path)
    except OSError as exc:
        raise ConfigurationError(f"cannot access experiment config {config_path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError("experiment config must be a regular, non-symlink file")
    if metadata.st_size > _MAX_CONFIG_BYTES:
        raise ConfigurationError(
            f"experiment config exceeds the {_MAX_CONFIG_BYTES}-byte size limit"
        )
    try:
        raw = config_path.read_bytes()
        if len(raw) != metadata.st_size:
            raise ConfigurationError("experiment config changed while it was being read")
        text = raw.decode("utf-8")
        suffix = config_path.suffix.lower()
        if suffix == ".json":
            payload = json.loads(text, object_pairs_hook=_json_object)
        elif suffix in {".yaml", ".yml"}:
            payload = yaml.load(text, Loader=_UniqueSafeLoader)
        else:
            raise ConfigurationError("experiment config must use .json, .yaml, or .yml")
        _validate_shape(payload)
        validate_schema_version(payload, ExperimentConfig, artifact=config_path.name)
        return ExperimentConfig.model_validate(payload)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"cannot load experiment config {config_path}: {exc}") from exc


__all__ = ["load_experiment_config"]
