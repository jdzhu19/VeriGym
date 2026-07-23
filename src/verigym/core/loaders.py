"""Strict JSON and YAML model loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from verigym.core.errors import ConfigurationError
from verigym.core.schema_compat import validate_schema_version

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    """Load a JSON/YAML document and validate it as ``model_type``."""

    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        elif path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        else:
            raise ConfigurationError(f"unsupported manifest extension: {path.suffix}")
        validate_schema_version(data, model_type, artifact=path.name)
        return model_type.model_validate(data)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"cannot load {path}: {exc}") from exc


def dump_json(path: Path, value: BaseModel | dict[str, object]) -> None:
    """Write stable, human-readable JSON with a trailing newline."""

    # A trusted rewrite makes an existing derived integrity index stale. Leave
    # the scope explicitly legacy-unverified until its owner regenerates it.
    integrity_manifest = path.parent / "artifact_manifest.json"
    if path.name != "artifact_manifest.json" and integrity_manifest.is_file():
        integrity_manifest.unlink()
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
