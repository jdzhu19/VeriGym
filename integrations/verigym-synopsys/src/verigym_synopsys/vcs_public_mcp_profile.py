"""Server-owned identities for public compile-only VCS/MCP execution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from verigym.plugin_api import SCHEMA_VERSION, ConfigurationError, StrictModel, content_hash

from .common import safe_executable, safe_relative_path

SERVICE_PROTOCOL = "verigym.synopsys.vcs.public_compile.mcp.v1"
SERVER_VERSION = "0.1.0"
LIST_PROFILES_TOOL = "verigym.synopsys.vcs.public_compile.list_profiles"
RESOLVE_PROFILE_TOOL = "verigym.synopsys.vcs.public_compile.resolve_profile"
COMPILE_TOOL = "verigym.synopsys.vcs.public_compile.compile"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TOOL_VERSION = re.compile(r"[A-Z]-\d{4}\.\d{2}(?:-[A-Za-z0-9._-]+)?")
_LICENSE_ENVIRONMENT = frozenset({"SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE", "VCS_HOME"})
_MAX_PROFILE_BYTES = 1024 * 1024


class VcsPublicMcpServerProfile(StrictModel):
    """Private site profile containing no hidden testbench or reference design."""

    schema_version: str = SCHEMA_VERSION
    id: str
    version: str = "1.0.0"
    description: str = ""
    task_id: str
    executable: str
    accepted_tool_version: str
    test_id: str = "compile"
    sources: list[str] = Field(min_length=1, max_length=64)
    top: str
    timeout_s: int = Field(default=30, ge=1, le=300)
    environment_allowlist: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if _PROFILE_ID.fullmatch(value) is None:
            raise ValueError("invalid VCS public MCP profile ID")
        return value

    @field_validator("executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        return safe_executable(value)

    @field_validator("accepted_tool_version")
    @classmethod
    def validate_tool_version(cls, value: str) -> str:
        if _TOOL_VERSION.fullmatch(value) is None:
            raise ValueError("VCS public MCP profile requires one exact VCS version")
        return value

    @field_validator("test_id")
    @classmethod
    def validate_test_id(cls, value: str) -> str:
        if value != "compile":
            raise ValueError("VCS public MCP supports only the compile public-test ID")
        return value

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        normalized = [safe_relative_path(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("VCS public MCP profile sources must be unique")
        if any(Path(item).suffix.lower() not in {".v", ".sv"} for item in normalized):
            raise ValueError("VCS public MCP profile sources must use Verilog filenames")
        return normalized

    @field_validator("top")
    @classmethod
    def validate_top(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value) is None:
            raise ValueError("invalid VCS public MCP top module")
        return value

    @field_validator("environment_allowlist")
    @classmethod
    def validate_environment(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or not set(value).issubset(_LICENSE_ENVIRONMENT):
            raise ValueError("unsupported VCS public MCP environment allowlist")
        return sorted(value)

    def contract_payload(self) -> dict[str, object]:
        return {
            "service_protocol": SERVICE_PROTOCOL,
            "server_version": SERVER_VERSION,
            "profile_id": self.id,
            "profile_version": self.version,
            "task_id": self.task_id,
            "accepted_tool_version": self.accepted_tool_version,
            "test_id": self.test_id,
            "sources": self.sources,
            "top": self.top,
            "timeout_s": self.timeout_s,
        }

    @property
    def contract_hash(self) -> str:
        return content_hash(self.contract_payload())


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
            raise ConfigurationError(f"duplicate VCS public MCP profile key: {key!r}")
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
            raise ConfigurationError(f"duplicate VCS public MCP profile key: {key!r}")
        result[key] = value
    return result


def load_vcs_public_server_profile(path: Path) -> VcsPublicMcpServerProfile:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError("VCS public MCP server profile must be a regular non-symlink file")
    if expanded.stat().st_size > _MAX_PROFILE_BYTES:
        raise ConfigurationError("VCS public MCP server profile exceeds the 1 MiB bound")
    try:
        text = expanded.read_text(encoding="utf-8")
        payload = (
            json.loads(text, object_pairs_hook=_construct_unique_json)
            if expanded.suffix.lower() == ".json"
            else yaml.load(text, Loader=_UniqueSafeLoader)
        )
        return VcsPublicMcpServerProfile.model_validate(payload)
    except Exception as exc:
        raise ConfigurationError(f"invalid VCS public MCP server profile: {exc}") from exc


__all__ = [
    "COMPILE_TOOL",
    "LIST_PROFILES_TOOL",
    "RESOLVE_PROFILE_TOOL",
    "SERVER_VERSION",
    "SERVICE_PROTOCOL",
    "VcsPublicMcpServerProfile",
    "load_vcs_public_server_profile",
]
