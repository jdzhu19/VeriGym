"""Provider-visible HWE tool-schema normalization for OpenHands 1.42.1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

_NO_RAW_HOST_PATH_PATTERN = (
    r"^(?![\s\S]*(?:^|[^A-Za-z0-9._-])/(?:home|data|hpc)"
    r"(?:/|$|[^A-Za-z0-9._-]))(?![\s\S]*[A-Za-z]:\\)[\s\S]*$"
)
_WORKSPACE_RELATIVE_PATH_PATTERN = (
    r"^(?!/)(?![A-Za-z]:[\\/])"
    r"(?![\s\S]*(?:^|[^A-Za-z0-9._-])/(?:home|data|hpc)"
    r"(?:/|$|[^A-Za-z0-9._-]))(?![\s\S]*[A-Za-z]:\\)[\s\S]*$"
)
_EXPECTED_TOOL_FIELDS = {
    "apply_patch": {"patch"},
    "finish": {"summary"},
    "inspect_diff": set(),
    "list_files": {"path"},
    "read_file": {"end_line", "path", "start_line"},
    "shell": {"command", "cwd"},
}
_FIELD_GUIDANCE = {
    ("apply_patch", "patch"): (
        "One unified diff whose file headers use workspace-relative repository paths. "
        "Do not include controller or host filesystem paths."
    ),
    ("finish", "summary"): (
        "Brief completion summary. Refer to repository files only by workspace-relative path."
    ),
    ("list_files", "path"): (
        "Optional workspace-relative POSIX directory, such as '.' or 'core'. Never use a "
        "leading slash or drive-letter prefix."
    ),
    ("read_file", "path"): (
        "Workspace-relative POSIX file path, such as 'core/id_stage.sv'. Never use a leading "
        "slash or drive-letter prefix."
    ),
    ("shell", "command"): (
        "One bounded shell diagnostic. Refer to repository files by workspace-relative path and "
        "never copy controller or host filesystem paths into the command."
    ),
    ("shell", "cwd"): (
        "Optional workspace-relative POSIX working directory, such as '.' or 'core'. Never use "
        "a leading slash or drive-letter prefix."
    ),
}


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


def with_workspace_relative_hwe_constraints(
    tools: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bind the canonical six-tool schema to workspace-relative repository paths.

    The provider still emits every argument. This helper adds only model-visible
    JSON-schema guidance and never rewrites a response. The adapter's independent
    pre-dispatch raw-host-path check remains authoritative and fail closed.
    """

    constrained: list[dict[str, Any]] = []
    observed: set[str] = set()
    for value in tools:
        tool = deepcopy(dict(value))
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            parameters = function.get("parameters")
        else:
            name = tool.get("name")
            parameters = tool.get("parameters")
        if not isinstance(name, str) or name not in _EXPECTED_TOOL_FIELDS:
            raise ValueError("OpenHands HWE workspace schema contains an unknown tool")
        if name in observed:
            raise ValueError("OpenHands HWE workspace schema contains a duplicate tool")
        if not isinstance(parameters, dict):
            raise ValueError("OpenHands HWE workspace schema parameters are malformed")
        properties = parameters.get("properties")
        if not isinstance(properties, dict) or set(properties) != _EXPECTED_TOOL_FIELDS[name]:
            raise ValueError("OpenHands HWE workspace schema fields changed")
        parameters["additionalProperties"] = False
        for field, schema in properties.items():
            if not isinstance(schema, dict):
                raise ValueError("OpenHands HWE workspace schema property is malformed")
            guidance = _FIELD_GUIDANCE.get((name, field))
            if guidance is not None:
                schema["description"] = guidance
            if schema.get("type") == "string":
                schema["pattern"] = _NO_RAW_HOST_PATH_PATTERN
            if field in {"path", "cwd"}:
                schema["pattern"] = _WORKSPACE_RELATIVE_PATH_PATTERN
        observed.add(name)
        constrained.append(tool)
    if observed != set(_EXPECTED_TOOL_FIELDS):
        raise ValueError("OpenHands HWE workspace schema must contain the exact six tools")
    return constrained
