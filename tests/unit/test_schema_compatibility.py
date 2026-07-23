"""Compatibility dispatch tests for persistent top-level artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.errors import SchemaCompatibilityError
from verigym.core.loaders import load_model
from verigym.schemas.task import VeriTask


def _toy_task() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "id": "compat",
        "suite": "toy",
        "suite_version": "1",
        "release_id": None,
        "description": "compatibility fixture",
        "design": {
            "top_module": "dut",
            "language": "systemverilog",
            "editable_files": ["dut.sv"],
            "support_files": [],
            "include_dirs": [],
            "defines": {},
            "clocks": [],
            "resets": [],
        },
        "verifier": {
            "nodes": [
                {
                    "id": "compile",
                    "plugin": "iverilog_compile",
                    "depends_on": [],
                    "required": True,
                    "options": {},
                }
            ]
        },
        "budget": {},
        "metadata": {},
    }


@pytest.mark.parametrize(
    ("version", "category"),
    [
        ("2.0", "schema_major_unsupported"),
        ("1.1", "schema_minor_unsupported"),
        ("v1", "schema_version_malformed"),
        (1, "schema_version_malformed"),
    ],
)
def test_loader_rejects_unsupported_schema_versions(
    tmp_path: Path,
    version: object,
    category: str,
) -> None:
    payload = _toy_task()
    payload["schema_version"] = version
    path = tmp_path / "task.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaCompatibilityError) as error:
        load_model(path, VeriTask)

    assert error.value.category == category


def test_loader_requires_explicit_schema_version(tmp_path: Path) -> None:
    payload = _toy_task()
    del payload["schema_version"]
    path = tmp_path / "task.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaCompatibilityError) as error:
        load_model(path, VeriTask)

    assert error.value.category == "schema_version_missing"
