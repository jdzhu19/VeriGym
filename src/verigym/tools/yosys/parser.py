"""Bounded parser for Yosys ``stat -json`` output."""

from __future__ import annotations

import json
import math
import re
from typing import Any, NoReturn

from verigym.tools.yosys.schemas import ParsedYosysStat


class YosysStatParseError(ValueError):
    pass


def _reject_constant(value: str) -> NoReturn:
    raise YosysStatParseError(f"non-finite JSON constant is forbidden: {value}")


def _validate_complexity(value: Any, *, max_depth: int, max_nodes: int) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > max_nodes:
            raise YosysStatParseError("Yosys stat JSON exceeds the structural node limit")
        if depth > max_depth:
            raise YosysStatParseError("Yosys stat JSON exceeds the nesting-depth limit")
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise YosysStatParseError(f"Yosys stat field {field!r} must be an object")
    return value


def _count(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise YosysStatParseError(f"Yosys stat field {field!r} must be a nonnegative integer")
    return value


def parse_yosys_stat_json(
    raw: bytes,
    *,
    top: str,
    max_bytes: int = 1_048_576,
    max_depth: int = 32,
    max_nodes: int = 100_000,
    expected_yosys_version: str | None = None,
) -> ParsedYosysStat:
    if len(raw) > max_bytes:
        raise YosysStatParseError("Yosys stat JSON exceeds the configured byte limit")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise YosysStatParseError("Yosys stat JSON is not UTF-8") from exc
    try:
        value = json.loads(decoded, parse_constant=_reject_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise YosysStatParseError("Yosys stat output is malformed or truncated JSON") from exc
    _validate_complexity(value, max_depth=max_depth, max_nodes=max_nodes)
    root = _mapping(value, "root")
    creator = root.get("creator")
    if not isinstance(creator, str) or not creator.startswith("Yosys "):
        raise YosysStatParseError("Yosys stat JSON has no supported creator identity")
    if expected_yosys_version is not None:
        prefix = f"Yosys {expected_yosys_version}"
        if re.match(rf"^{re.escape(prefix)}(?:\+|\s|\()", creator) is None:
            raise YosysStatParseError(
                f"Yosys stat creator is incompatible: expected {prefix!r}, got {creator!r}"
            )
    modules = _mapping(root.get("modules"), "modules")
    module_key = f"\\{top}"
    if module_key not in modules and top not in modules:
        raise YosysStatParseError(f"Yosys stat JSON does not contain top module {top!r}")
    _mapping(modules.get(module_key, modules.get(top)), f"modules.{top}")
    design = _mapping(root.get("design"), "design")
    histogram_payload = _mapping(design.get("num_cells_by_type"), "num_cells_by_type")
    histogram: dict[str, int] = {}
    for cell_type, count in histogram_payload.items():
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise YosysStatParseError(
                f"Yosys cell count for {cell_type!r} must be a nonnegative integer"
            )
        histogram[cell_type] = count
    num_cells = _count(design, "num_cells")
    if sum(histogram.values()) != num_cells:
        raise YosysStatParseError("Yosys cell histogram does not equal the total cell count")
    raw_area = design.get("area")
    area: float | None
    if raw_area is None:
        area = None
    elif isinstance(raw_area, bool) or not isinstance(raw_area, (int, float)):
        raise YosysStatParseError("Yosys mapped area must be numeric when present")
    else:
        area = float(raw_area)
        if not math.isfinite(area) or area <= 0:
            raise YosysStatParseError("Yosys mapped area must be finite and positive")
    return ParsedYosysStat(
        creator=creator,
        top=top,
        num_wires=_count(design, "num_wires"),
        num_wire_bits=_count(design, "num_wire_bits"),
        num_memories=_count(design, "num_memories"),
        num_memory_bits=_count(design, "num_memory_bits"),
        num_processes=_count(design, "num_processes"),
        num_cells=num_cells,
        cells_by_type=dict(sorted(histogram.items())),
        area=area,
    )


__all__ = ["YosysStatParseError", "parse_yosys_stat_json"]
