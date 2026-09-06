"""Server-owned fixed profiles for verifier-only VCS MCP execution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator, model_validator
from verigym.plugin_api import SCHEMA_VERSION, ConfigurationError, StrictModel, content_hash

from .common import safe_executable, safe_relative_path

SERVICE_PROTOCOL = "verigym.synopsys.vcs.mcp.v1"
SERVER_VERSION = "0.1.0"
LIST_PROFILES_TOOL = "verigym.synopsys.vcs.list_profiles"
RESOLVE_PROFILE_TOOL = "verigym.synopsys.vcs.resolve_profile"
SIMULATE_TOOL = "verigym.synopsys.vcs.simulate"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TOOL_VERSION = re.compile(r"[A-Z]-\d{4}\.\d{2}(?:-[A-Za-z0-9._-]+)?")
_LICENSE_ENVIRONMENT = frozenset({"SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE", "VCS_HOME"})
_MAX_PROFILE_BYTES = 1024 * 1024


class VcsMcpAuxiliaryFile(StrictModel):
    """One server-owned verifier asset identified publicly by mount path and hash."""

    path: str
    mount_path: str
    sha256: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("server auxiliary files must use absolute paths")
        return str(path)

    @field_validator("mount_path")
    @classmethod
    def validate_mount_path(cls, value: str) -> str:
        normalized = safe_relative_path(value)
        if Path(normalized).parts[0] in {".verigym_internal", "csrc", "input", "out"}:
            raise ValueError("VCS auxiliary mount collides with private build paths")
        return normalized

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("auxiliary-file identity must be a lowercase SHA-256")
        return value

    def contract_payload(self) -> dict[str, str]:
        return {"mount_path": self.mount_path, "sha256": self.sha256}


class VcsMcpServerProfile(StrictModel):
    """Private site profile; testbench location never crosses the MCP boundary."""

    schema_version: str = SCHEMA_VERSION
    id: str
    version: str = "1.0.0"
    description: str = ""
    task_id: str
    executable: str
    accepted_tool_version: str
    sources: list[str] = Field(min_length=1, max_length=64)
    testbench: str
    testbench_mount_path: str = "verifier/testbench.v"
    testbench_sha256: str
    auxiliary_files: list[VcsMcpAuxiliaryFile] = Field(default_factory=list, max_length=64)
    top: str
    pass_marker: str = "VERIGYM_PASS"
    fail_marker: str = "VERIGYM_FAIL"
    timeout_s: int = Field(default=180, ge=1, le=3600)
    environment_allowlist: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if _PROFILE_ID.fullmatch(value) is None:
            raise ValueError("invalid VCS MCP profile ID")
        return value

    @field_validator("executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        return safe_executable(value)

    @field_validator("accepted_tool_version")
    @classmethod
    def validate_tool_version(cls, value: str) -> str:
        if _TOOL_VERSION.fullmatch(value) is None:
            raise ValueError("VCS MCP profile requires one exact VCS version")
        return value

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        normalized = [safe_relative_path(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("VCS MCP profile sources must be unique")
        if any(Path(item).suffix.lower() not in {".v", ".sv"} for item in normalized):
            raise ValueError("VCS MCP profile sources must use Verilog filenames")
        return normalized

    @field_validator("testbench")
    @classmethod
    def validate_testbench(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute() or path.suffix.lower() not in {".v", ".sv"}:
            raise ValueError("server testbench must be an absolute Verilog file path")
        return str(path)

    @field_validator("testbench_mount_path")
    @classmethod
    def validate_testbench_mount_path(cls, value: str) -> str:
        normalized = safe_relative_path(value)
        if Path(normalized).suffix.lower() not in {".v", ".sv"}:
            raise ValueError("VCS testbench mount must use a Verilog filename")
        return normalized

    @field_validator("testbench_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("testbench identity must be a lowercase SHA-256")
        return value

    @field_validator("top")
    @classmethod
    def validate_top(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value) is None:
            raise ValueError("invalid VCS top-module identifier")
        return value

    @field_validator("pass_marker", "fail_marker")
    @classmethod
    def validate_marker(cls, value: str) -> str:
        if not value or len(value) > 256 or "\x00" in value:
            raise ValueError("VCS marker must contain 1-256 safe characters")
        return value

    @field_validator("environment_allowlist")
    @classmethod
    def validate_environment(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or not set(value).issubset(_LICENSE_ENVIRONMENT):
            raise ValueError("unsupported VCS MCP server environment allowlist")
        return sorted(value)

    @model_validator(mode="after")
    def validate_contract(self) -> VcsMcpServerProfile:
        if self.pass_marker == self.fail_marker:
            raise ValueError("VCS pass and fail markers must differ")
        mounts = [item.mount_path for item in self.auxiliary_files]
        if len(mounts) != len(set(mounts)):
            raise ValueError("VCS auxiliary mount paths must be unique")
        if self.testbench_mount_path in mounts or any(source in mounts for source in self.sources):
            raise ValueError("VCS auxiliary mounts must be distinct from RTL inputs")
        return self

    def contract_payload(self) -> dict[str, object]:
        """Public identity excluding all site paths and license configuration."""

        return {
            "service_protocol": SERVICE_PROTOCOL,
            "server_version": SERVER_VERSION,
            "profile_id": self.id,
            "profile_version": self.version,
            "task_id": self.task_id,
            "accepted_tool_version": self.accepted_tool_version,
            "sources": self.sources,
            "testbench_mount_path": self.testbench_mount_path,
            "testbench_sha256": self.testbench_sha256,
            "auxiliary_files": [item.contract_payload() for item in self.auxiliary_files],
            "top": self.top,
            "pass_marker": self.pass_marker,
            "fail_marker": self.fail_marker,
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
            raise ConfigurationError(f"duplicate VCS MCP profile key: {key!r}")
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
            raise ConfigurationError(f"duplicate VCS MCP profile key: {key!r}")
        result[key] = value
    return result


def load_vcs_server_profile(path: Path) -> VcsMcpServerProfile:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError("VCS MCP server profile must be a regular non-symlink file")
    if expanded.stat().st_size > _MAX_PROFILE_BYTES:
        raise ConfigurationError("VCS MCP server profile exceeds the 1 MiB bound")
    try:
        text = expanded.read_text(encoding="utf-8")
        payload = (
            json.loads(text, object_pairs_hook=_construct_unique_json)
            if expanded.suffix.lower() == ".json"
            else yaml.load(text, Loader=_UniqueSafeLoader)
        )
        profile = VcsMcpServerProfile.model_validate(payload)
    except Exception as exc:
        raise ConfigurationError(f"invalid VCS MCP server profile: {exc}") from exc
    testbench = Path(profile.testbench)
    if testbench.is_symlink() or not testbench.is_file():
        raise ConfigurationError("VCS MCP testbench must be a regular non-symlink file")
    for item in profile.auxiliary_files:
        auxiliary = Path(item.path)
        if auxiliary.is_symlink() or not auxiliary.is_file():
            raise ConfigurationError("VCS MCP auxiliary input must be a regular non-symlink file")
    return profile


__all__ = [
    "SERVER_VERSION",
    "SERVICE_PROTOCOL",
    "LIST_PROFILES_TOOL",
    "RESOLVE_PROFILE_TOOL",
    "SIMULATE_TOOL",
    "VcsMcpAuxiliaryFile",
    "VcsMcpServerProfile",
    "load_vcs_server_profile",
]
