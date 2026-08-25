"""Strict Yosys request and parser schemas."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.core.workspace import normalize_relative_path
from verigym.schemas.base import StrictModel

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_DEFINE_VALUE = re.compile(r"^[A-Za-z0-9_]+$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class YosysSynthesisRequest(StrictModel):
    sources: list[str] = Field(min_length=1, max_length=256)
    top: str
    frontend: Literal["verilog-2005", "systemverilog-subset"] = "verilog-2005"
    include_dirs: list[str] = Field(default_factory=list, max_length=0)
    defines: dict[str, str | None] = Field(default_factory=dict)
    flatten: bool = True
    liberty_asset_id: str | None = None
    liberty_path: str | None = None
    liberty_sha256: str | None = None
    area_unit: str | None = None
    flow_template_id: Literal[
        "verigym-yosys-area-v1",
        "verigym-yosys-opensta-atp-v1",
        "verigym-yosys-opensta-atp-v2",
    ] = "verigym-yosys-area-v1"
    emit_netlist_verilog: bool = True
    emit_netlist_json: bool = True
    emit_stat_json: bool = True
    require_mapped_area: bool = False
    constraints_path: str | None = None
    constraints_sha256: str | None = None
    timing_unit: str | None = None
    power_unit: Literal["W", "mW", "uW", "nW", "pW"] | None = None
    clock_name: str | None = None
    clock_period: float | None = Field(default=None, gt=0)
    wire_load_model: str | None = None
    power_activity_mode: Literal["global_clock_relative"] | None = None
    power_activity: float | None = Field(default=None, gt=0)
    power_duty: float | None = Field(default=None, ge=0, le=1)
    opensta_executable: str | None = None
    opensta_executable_sha256: str | None = None
    expected_opensta_version: str | None = None
    timeout_s: int = Field(default=60, ge=1, le=3600)
    max_stat_json_bytes: int = Field(default=1_048_576, ge=1, le=4_194_304)
    expected_flow_script_hash: str | None = None
    expected_yosys_version: str | None = None
    resolved_profile_hash: str | None = None
    tool_identity: dict[str, str | None] = Field(default_factory=dict)
    run_label: Literal["candidate", "reference"] = "candidate"

    @field_validator("top")
    @classmethod
    def validate_top(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("top module must be an ordinary Verilog identifier")
        return value

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        for source in value:
            normalized = normalize_relative_path(source)
            if not normalized.lower().endswith((".v", ".sv")):
                raise ValueError("Yosys sources must use .v or .sv extensions")
        return value

    @field_validator("defines")
    @classmethod
    def validate_defines(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        for name, definition in value.items():
            if not _IDENTIFIER.fullmatch(name):
                raise ValueError("define names must be ordinary Verilog identifiers")
            if definition is not None and not _DEFINE_VALUE.fullmatch(definition):
                raise ValueError("define values may contain only letters, digits, and underscore")
        return dict(sorted(value.items()))

    @field_validator(
        "liberty_sha256",
        "constraints_sha256",
        "opensta_executable_sha256",
        "expected_flow_script_hash",
        "resolved_profile_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        if value is not None and not _HASH.fullmatch(value):
            raise ValueError("content identities must be lowercase SHA-256 values")
        return value

    @model_validator(mode="after")
    def validate_area_contract(self) -> YosysSynthesisRequest:
        liberty_fields = (
            self.liberty_asset_id,
            self.liberty_path,
            self.liberty_sha256,
            self.area_unit,
        )
        if self.require_mapped_area and any(value is None for value in liberty_fields):
            raise ValueError("mapped area requires an identified, hashed Liberty asset and unit")
        if any(value is not None for value in liberty_fields) and not all(
            value is not None for value in liberty_fields
        ):
            raise ValueError(
                "Liberty asset id, path, hash, and area unit are all required together"
            )
        if self.require_mapped_area and not self.emit_stat_json:
            raise ValueError("mapped area requires machine-readable statistics")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("source paths must be unique")
        timing_power_fields = (
            self.constraints_path,
            self.constraints_sha256,
            self.timing_unit,
            self.power_unit,
            self.clock_name,
            self.clock_period,
            self.wire_load_model,
            self.power_activity_mode,
            self.power_activity,
            self.power_duty,
            self.opensta_executable,
            self.opensta_executable_sha256,
            self.expected_opensta_version,
        )
        if self.flow_template_id in {
            "verigym-yosys-opensta-atp-v1",
            "verigym-yosys-opensta-atp-v2",
        }:
            if any(value is None for value in timing_power_fields):
                raise ValueError("the Yosys/OpenSTA flow requires a complete timing/power contract")
            if not self.emit_netlist_verilog or not self.emit_stat_json:
                raise ValueError("the Yosys/OpenSTA flow requires Verilog and stat JSON outputs")
            if self.clock_name is None or not _IDENTIFIER.fullmatch(self.clock_name):
                raise ValueError("OpenSTA clock name must be an ordinary identifier")
            if self.wire_load_model is None or not re.fullmatch(
                r"[A-Za-z0-9_][A-Za-z0-9_.-]*", self.wire_load_model
            ):
                raise ValueError("OpenSTA wire-load model has unsupported characters")
            if self.opensta_executable is None or any(
                character in self.opensta_executable for character in ("\x00", "\n", "\r")
            ):
                raise ValueError("OpenSTA executable is invalid")
            if not self.timing_unit:
                raise ValueError("OpenSTA timing unit must be explicit")
        elif any(value is not None for value in timing_power_fields):
            raise ValueError("the area-only Yosys flow cannot declare timing/power settings")
        return self


class ParsedYosysStat(StrictModel):
    creator: str
    top: str
    num_wires: int = Field(ge=0)
    num_wire_bits: int = Field(ge=0)
    num_memories: int = Field(ge=0)
    num_memory_bits: int = Field(ge=0)
    num_processes: int = Field(ge=0)
    num_cells: int = Field(ge=0)
    cells_by_type: dict[str, int]
    area: float | None = None


__all__ = ["ParsedYosysStat", "YosysSynthesisRequest"]
