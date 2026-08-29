"""Deterministic OpenSTA script generation and report parsing."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from verigym.tools.yosys.schemas import YosysSynthesisRequest

OpenSTAFlowTemplateId = Literal[
    "verigym-yosys-opensta-atp-v1",
    "verigym-yosys-opensta-atp-v2",
]
LEGACY_FLOW_TEMPLATE_ID: Literal["verigym-yosys-opensta-atp-v1"] = "verigym-yosys-opensta-atp-v1"
FLOW_TEMPLATE_ID: Literal["verigym-yosys-opensta-atp-v2"] = "verigym-yosys-opensta-atp-v2"
FLOW_TEMPLATE_IDS = frozenset({LEGACY_FLOW_TEMPLATE_ID, FLOW_TEMPLATE_ID})
_BASE_FLOW_TEMPLATE_CONTRACT_LINES = [
    "exec yosys -Q -T -l out/yosys.log -s synthesis.ys 2>@1",
    "read_liberty profile/cells.lib",
    "read_verilog out/netlist.v",
    "link_design <validated-top>",
    "read_sdc profile/constraints.sdc",
    "set_wire_load_model -name <validated-model>",
    "set_power_activity -global -activity <frozen> -duty <frozen> -clock <frozen>",
    "find_timing_paths -path_delay max",
    "report_checks -path_delay max",
    "report_worst_slack -max",
    "report_power -format json",
    "report_power -format text",
]
LEGACY_FLOW_TEMPLATE_CONTRACT = "\n".join(
    [*_BASE_FLOW_TEMPLATE_CONTRACT_LINES, "write deterministic metrics.kv"]
)
FLOW_TEMPLATE_CONTRACT = "\n".join(
    [
        *_BASE_FLOW_TEMPLATE_CONTRACT_LINES,
        "sta::redirect_file_begin out/units.rpt; report_units; sta::redirect_file_end",
        "sta::redirect_file_begin out/activity_annotation.rpt; "
        "report_activity_annotation; sta::redirect_file_end",
        "write deterministic metrics.kv",
    ]
)
FLOW_TEMPLATE_CONTRACTS = {
    LEGACY_FLOW_TEMPLATE_ID: LEGACY_FLOW_TEMPLATE_CONTRACT,
    FLOW_TEMPLATE_ID: FLOW_TEMPLATE_CONTRACT,
}

_POWER_UNIT_SCALE_WATTS = {
    "W": 1.0,
    "mW": 1.0e-3,
    "uW": 1.0e-6,
    "nW": 1.0e-9,
    "pW": 1.0e-12,
}


def _tcl_float(value: float | None, name: str) -> str:
    if value is None or not math.isfinite(value):
        raise ValueError(f"OpenSTA {name} must be finite")
    return f"{value:.12g}"


def opensta_power_activity_identity(*, mode: str, activity: float, duty: float) -> str:
    if not mode or not math.isfinite(activity) or not math.isfinite(duty):
        raise ValueError("OpenSTA power activity contract is incomplete")
    return f"opensta_{mode}:activity={activity:.12g}:duty={duty:.12g}"


def power_activity_identity(request: YosysSynthesisRequest) -> str:
    if (
        request.power_activity_mode is None
        or request.power_activity is None
        or request.power_duty is None
    ):
        raise ValueError("OpenSTA power activity contract is incomplete")
    return opensta_power_activity_identity(
        mode=request.power_activity_mode,
        activity=request.power_activity,
        duty=request.power_duty,
    )


def build_opensta_script(request: YosysSynthesisRequest) -> str:
    """Render a trusted Tcl driver for the complete Yosys/OpenSTA flow."""

    if request.flow_template_id not in FLOW_TEMPLATE_IDS:
        raise ValueError(f"unsupported OpenSTA flow template: {request.flow_template_id}")
    required = (
        request.constraints_sha256,
        request.timing_unit,
        request.power_unit,
        request.clock_name,
        request.clock_period,
        request.wire_load_model,
        request.power_activity,
        request.power_duty,
    )
    if any(value is None for value in required):
        raise ValueError("OpenSTA script requires a complete timing/power contract")
    activity = _tcl_float(request.power_activity, "power activity")
    duty = _tcl_float(request.power_duty, "power duty")
    expected_period = _tcl_float(request.clock_period, "clock period")
    assert request.clock_name is not None
    assert request.wire_load_model is not None
    assert request.constraints_sha256 is not None
    assert request.timing_unit is not None
    assert request.power_unit is not None
    activity_identity = power_activity_identity(request)
    diagnostic_reports = ""
    if request.flow_template_id == FLOW_TEMPLATE_ID:
        diagnostic_reports = (
            "sta::redirect_file_begin out/units.rpt\n"
            "report_units\n"
            "sta::redirect_file_end\n"
            "sta::redirect_file_begin out/activity_annotation.rpt\n"
            "report_activity_annotation\n"
            "sta::redirect_file_end\n"
        )
    return (
        "set vg_yosys_status [catch {exec yosys -Q -T -l out/yosys.log -s synthesis.ys "
        "2>@1} vg_yosys_error]\n"
        'if {$vg_yosys_status != 0} { error "Yosys failed: $vg_yosys_error" }\n'
        "read_liberty profile/cells.lib\n"
        "read_verilog out/netlist.v\n"
        f"link_design {request.top}\n"
        "read_sdc profile/constraints.sdc\n"
        f"set_wire_load_model -name {request.wire_load_model}\n"
        f"set vg_clocks [get_clocks {request.clock_name}]\n"
        'if {[llength $vg_clocks] != 1} { error "profile clock was not resolved uniquely" }\n'
        "set vg_clock [lindex $vg_clocks 0]\n"
        "set vg_period [get_property $vg_clock period]\n"
        f"if {{abs($vg_period - {expected_period}) > 1.0e-9}} "
        '{ error "clock period differs from profile" }\n'
        f"set_power_activity -global -activity {activity} -duty {duty} -clock $vg_clock\n"
        "set vg_path_ends [find_timing_paths -path_delay max -group_path_count 1 "
        "-endpoint_path_count 1]\n"
        'if {[llength $vg_path_ends] < 1} { error "no maximum timing path" }\n'
        "set vg_path_end [lindex $vg_path_ends 0]\n"
        "set vg_path [$vg_path_end path]\n"
        "set vg_arrival [get_property $vg_path arrival]\n"
        "set vg_slack [get_property $vg_path_end slack]\n"
        "set vg_wns [expr {$vg_slack < 0.0 ? $vg_slack : 0.0}]\n"
        "report_checks -path_delay max -group_path_count 1 -endpoint_path_count 1 "
        "-digits 8 > out/timing.rpt\n"
        "report_worst_slack -max -digits 8 > out/slack.rpt\n"
        "report_power -format json -digits 8 > out/power.json\n"
        "report_power -format text -digits 8 > out/power.rpt\n"
        f"{diagnostic_reports}"
        "check_setup > out/check_setup.rpt\n"
        "set vg_metrics [open out/opensta_metrics.kv w]\n"
        'puts $vg_metrics "VERIGYM_OPENSTA_METRICS_V1"\n'
        'puts $vg_metrics "critical_path_delay=$vg_arrival"\n'
        'puts $vg_metrics "worst_negative_slack=$vg_wns"\n'
        'puts $vg_metrics "clock_period=$vg_period"\n'
        f'puts $vg_metrics "timing_unit={request.timing_unit}"\n'
        f'puts $vg_metrics "constraints_sha256={request.constraints_sha256}"\n'
        f'puts $vg_metrics "wire_load_model={request.wire_load_model}"\n'
        f'puts $vg_metrics "power_unit={request.power_unit}"\n'
        f'puts $vg_metrics "power_activity_mode={activity_identity}"\n'
        "close $vg_metrics\n"
        "exit\n"
    )


def parse_opensta_metrics(payload: bytes) -> dict[str, str]:
    text = payload.decode("utf-8", errors="strict")
    lines = text.splitlines()
    if not lines or lines[0] != "VERIGYM_OPENSTA_METRICS_V1":
        raise ValueError("OpenSTA metrics sentinel is missing")
    parsed: dict[str, str] = {}
    for line in lines[1:]:
        if not line or "=" not in line:
            raise ValueError("OpenSTA metrics contain a malformed line")
        key, value = line.split("=", 1)
        if key in parsed or not key or not value:
            raise ValueError("OpenSTA metrics contain duplicate or empty fields")
        parsed[key] = value
    expected = {
        "critical_path_delay",
        "worst_negative_slack",
        "clock_period",
        "timing_unit",
        "constraints_sha256",
        "wire_load_model",
        "power_unit",
        "power_activity_mode",
    }
    if set(parsed) != expected:
        raise ValueError("OpenSTA metrics fields differ from the versioned contract")
    return parsed


def parse_opensta_power_json(payload: bytes, *, target_unit: str) -> float:
    if target_unit not in _POWER_UNIT_SCALE_WATTS:
        raise ValueError("unsupported OpenSTA power unit")
    try:
        report: Any = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("OpenSTA power JSON is invalid") from exc
    if not isinstance(report, dict):
        raise ValueError("OpenSTA power JSON must be an object")
    total = report.get("Total")
    if not isinstance(total, dict):
        raise ValueError("OpenSTA power JSON has no Total object")
    watts = total.get("total")
    if not isinstance(watts, (int, float)) or isinstance(watts, bool):
        raise ValueError("OpenSTA total power is not numeric")
    value = float(watts) / _POWER_UNIT_SCALE_WATTS[target_unit]
    if not math.isfinite(value) or value <= 0:
        raise ValueError("OpenSTA total power must be finite and positive")
    return value


__all__ = [
    "FLOW_TEMPLATE_CONTRACT",
    "FLOW_TEMPLATE_CONTRACTS",
    "FLOW_TEMPLATE_ID",
    "FLOW_TEMPLATE_IDS",
    "LEGACY_FLOW_TEMPLATE_CONTRACT",
    "LEGACY_FLOW_TEMPLATE_ID",
    "OpenSTAFlowTemplateId",
    "build_opensta_script",
    "opensta_power_activity_identity",
    "parse_opensta_metrics",
    "parse_opensta_power_json",
    "power_activity_identity",
]
