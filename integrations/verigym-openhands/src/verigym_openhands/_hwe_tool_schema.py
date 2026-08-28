"""Provider-visible HWE tool-schema normalization for OpenHands 1.42.1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


def without_openhands_tool_metadata(
    tools: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Remove only SDK-added metadata while preserving semantic HWE fields.

    OpenHands 1.42.1 adds ``security_risk`` and ``summary`` to every provider
    tool schema.  The HWE MCP adapter cannot forward those fields to the
    canonical broker.  A distinct collection policy therefore removes them
    before the provider request.  ``finish.summary`` belongs to the HWE
    contract and is intentionally retained.
    """

    normalized: list[dict[str, Any]] = []
    for value in tools:
        tool = deepcopy(dict(value))
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            parameters = function.get("parameters")
        else:
            name = tool.get("name")
            parameters = tool.get("parameters")
        if not isinstance(name, str) or not isinstance(parameters, dict):
            raise ValueError("OpenHands HWE provider tool schema is malformed")
        properties = parameters.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("OpenHands HWE provider tool properties are malformed")
        properties.pop("security_risk", None)
        if name != "finish":
            properties.pop("summary", None)
        required = parameters.get("required")
        if required is not None:
            if not isinstance(required, list) or any(
                not isinstance(item, str) for item in required
            ):
                raise ValueError("OpenHands HWE provider tool required fields are malformed")
            retained = [
                item
                for item in required
                if item != "security_risk" and not (item == "summary" and name != "finish")
            ]
            if retained:
                parameters["required"] = retained
            else:
                parameters.pop("required", None)
        normalized.append(tool)
    return normalized
