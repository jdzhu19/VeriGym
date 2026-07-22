"""Injection-safe deterministic Yosys script generation."""

from __future__ import annotations

from typing import Literal

from verigym.core.hashing import hash_bytes
from verigym.tools.yosys.schemas import YosysSynthesisRequest

FLOW_TEMPLATE_ID: Literal["verigym-yosys-area-v1"] = "verigym-yosys-area-v1"
FLOW_TEMPLATE_CONTRACT = "\n".join(
    [
        "read_liberty -lib profile/cells.lib",
        "read_verilog <validated-options> src/<deterministic-safe-names>",
        "hierarchy -check -top <validated-top>",
        "synth -top <validated-top> [-flatten]",
        "dffunmap",
        "dfflibmap -liberty profile/cells.lib",
        "abc -liberty profile/cells.lib",
        "clean -purge",
        "check -assert",
        "write_json out/netlist.json",
        "write_verilog -noattr out/netlist.v",
        "tee -o out/stat.json stat -json -top <validated-top> -liberty profile/cells.lib",
    ]
)
FLOW_TEMPLATE_HASH = hash_bytes((FLOW_TEMPLATE_CONTRACT + "\n").encode("utf-8"))


def safe_source_names(request: YosysSynthesisRequest) -> list[str]:
    names = []
    for index, source in enumerate(request.sources):
        extension = ".sv" if source.lower().endswith(".sv") else ".v"
        names.append(f"src/{index:04d}{extension}")
    return names


def build_yosys_script(request: YosysSynthesisRequest) -> str:
    """Render only the versioned built-in flow; no untrusted command text is accepted."""

    if request.flow_template_id != FLOW_TEMPLATE_ID:
        raise ValueError(f"unsupported Yosys flow template: {request.flow_template_id}")
    if request.liberty_path is None:
        raise ValueError("the canonical Yosys flow requires a Liberty asset")
    options: list[str] = []
    if request.frontend == "systemverilog-subset":
        options.append("-sv")
    for name, value in sorted(request.defines.items()):
        options.append(f"-D{name}" if value is None else f"-D{name}={value}")
    read_parts = ["read_verilog", *options, *safe_source_names(request)]
    synth_parts = ["synth", "-top", request.top]
    if request.flatten:
        synth_parts.append("-flatten")
    lines = [
        "read_liberty -lib profile/cells.lib",
        " ".join(read_parts),
        f"hierarchy -check -top {request.top}",
        " ".join(synth_parts),
        "dffunmap",
        "dfflibmap -liberty profile/cells.lib",
        "abc -liberty profile/cells.lib",
        "clean -purge",
        "check -assert",
    ]
    if request.emit_netlist_json:
        lines.append("write_json out/netlist.json")
    if request.emit_netlist_verilog:
        lines.append("write_verilog -noattr out/netlist.v")
    if request.emit_stat_json:
        lines.append(
            f"tee -o out/stat.json stat -json -top {request.top} -liberty profile/cells.lib"
        )
    return "\n".join(lines) + "\n"


def generated_script_hash(request: YosysSynthesisRequest) -> str:
    return hash_bytes(build_yosys_script(request).encode("utf-8"))


__all__ = [
    "FLOW_TEMPLATE_CONTRACT",
    "FLOW_TEMPLATE_HASH",
    "FLOW_TEMPLATE_ID",
    "build_yosys_script",
    "generated_script_hash",
    "safe_source_names",
]
