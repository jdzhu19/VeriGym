"""Crash-safe parent experiment artifact primitives."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import canonical_json
from verigym.core.schema_compat import validate_schema_version

ModelT = TypeVar("ModelT", bound=BaseModel)
_MAX_PARENT_FILE_BYTES = 64 * 1024 * 1024
_MAX_PARENT_JSON_DEPTH = 64


def _json_value(value: BaseModel | dict[str, Any]) -> Any:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def atomic_write_text(path: Path, text: str) -> None:
    """Replace a parent artifact atomically from a same-directory temporary file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_dump_json(path: Path, value: BaseModel | dict[str, Any]) -> None:
    payload = json.dumps(_json_value(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    atomic_write_text(path, payload)


def atomic_dump_jsonl(path: Path, values: Iterable[BaseModel | dict[str, Any]]) -> None:
    lines = [canonical_json(_json_value(value)) for value in values]
    atomic_write_text(path, "".join(f"{line}\n" for line in lines))


def _read_regular_file(path: Path) -> bytes:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"parent artifact is not a regular file: {path.name}")
    if metadata.st_size > _MAX_PARENT_FILE_BYTES:
        raise ConfigurationError(f"parent artifact is oversized: {path.name}")
    raw = path.read_bytes()
    if len(raw) != metadata.st_size:
        raise ConfigurationError(f"parent artifact changed while reading: {path.name}")
    return raw


def _check_json_depth(value: Any, depth: int = 0) -> None:
    if depth > _MAX_PARENT_JSON_DEPTH:
        raise ConfigurationError("parent artifact exceeds the JSON nesting-depth limit")
    if isinstance(value, dict):
        for item in value.values():
            _check_json_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_json_depth(item, depth + 1)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigurationError(f"duplicate JSON key in parent artifact: {key!r}")
        value[key] = item
    return value


def load_json_model(path: Path, model: type[ModelT]) -> ModelT:
    try:
        payload = json.loads(
            _read_regular_file(path).decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
        _check_json_depth(payload)
        validate_schema_version(payload, model, artifact=path.name)
        return model.model_validate(payload)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"invalid parent artifact {path.name}: {exc}") from exc


def load_jsonl_models(path: Path, model: type[ModelT]) -> list[ModelT]:
    try:
        values: list[ModelT] = []
        text = _read_regular_file(path).decode("utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                raise ConfigurationError(f"blank JSONL record at {path.name}:{line_number}")
            payload = json.loads(line, object_pairs_hook=_unique_json_object)
            _check_json_depth(payload)
            validate_schema_version(
                payload,
                model,
                artifact=f"{path.name}:{line_number}",
            )
            values.append(model.model_validate(payload))
        return values
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"invalid parent artifact {path.name}: {exc}") from exc


__all__ = [
    "atomic_dump_json",
    "atomic_dump_jsonl",
    "atomic_write_text",
    "load_json_model",
    "load_jsonl_models",
]
