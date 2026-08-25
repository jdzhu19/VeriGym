from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from verigym.plugin_api import content_hash
from verigym.profiles.registry import ToolchainProfileRegistry

from verigym_synopsys.mcp_server import (
    LIST_PROFILES_TOOL,
    SYNTHESIZE_TOOL,
    DesignCompilerMcpService,
    _handle,
)
from verigym_synopsys.prepare import main as prepare_profile


def _site_profile(tmp_path: Path) -> tuple[Path, bytes]:
    rtl = b"module counter(input clk, output reg q); always @(posedge clk) q <= ~q; endmodule\n"
    liberty = tmp_path / "cells.lib"
    liberty.write_text("library (cells) {}\n", encoding="utf-8")
    database = tmp_path / "cells.db"
    database.write_bytes(b"private-db")
    sdc = tmp_path / "design.sdc"
    sdc.write_text("create_clock -name clk -period 10 [get_ports clk]\n", encoding="utf-8")
    sdc_hash = hashlib.sha256(sdc.read_bytes()).hexdigest()
    executable = tmp_path / "dc_shell"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "if '-version' in sys.argv:\n"
        "    print('Design Compiler U-2022.12')\n"
        "    raise SystemExit(0)\n"
        "out = pathlib.Path('out')\n"
        "out.mkdir(exist_ok=True)\n"
        "(out / 'metrics.kv').write_text(\n"
        "    'VERIGYM_DC_METRICS_V4\\n'\n"
        "    'mapped_area=42.5\\n'\n"
        "    'critical_path_delay=3.25\\n'\n"
        "    'worst_negative_slack=-0.125\\n'\n"
        "    'clock_period=10\\n'\n"
        "    'num_cells=17\\n'\n"
        "    'power_unit=uW\\n'\n"
        "    'power_activity_mode=global_clock_relative\\n'\n"
        "    'power_activity=0.1\\n'\n"
        "    'power_static_probability=0.5\\n'\n"
        "    'power_base_clock=clk\\n'\n"
        "    'timing_unit=ns\\n'\n"
        f"    'constraints_sha256={sdc_hash}\\n'\n"
        ")\n"
        "(out / 'power.rpt').write_text(\n"
        "    'Total Dynamic Power = 8.5 uW\\nCell Leakage Power = 300 nW\\n'\n"
        ")\n"
        "(out / 'area.rpt').write_text('Total cell area: 42.5\\n')\n"
        "(out / 'timing.rpt').write_text('data arrival time 3.25\\n')\n"
        "(out / 'qor.rpt').write_text('Leaf Cell Count: 17\\n')\n"
        "(out / 'netlist.v').write_text('module counter; endmodule\\n')\n"
        "(out / 'dc.log').write_text('compile_ultra complete\\n')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    profile = tmp_path / "profile.yaml"
    assert (
        prepare_profile(
            [
                "--liberty",
                str(liberty),
                "--sdc",
                str(sdc),
                "--input-db",
                str(database),
                "--output-profile",
                str(profile),
                "--source",
                "rtl/counter.v",
                "--top",
                "counter",
                "--clock-period",
                "10",
                "--power-base-clock",
                "clk",
                "--dc-shell",
                str(executable),
            ]
        )
        == 0
    )
    return profile, rtl


def _tool_call(request_id: int, name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def test_mcp_server_exposes_only_fixed_verifier_tools(tmp_path: Path) -> None:
    profile_path, _ = _site_profile(tmp_path)
    service = DesignCompilerMcpService([profile_path], tmp_path / "mcp-work")
    initialized = _handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        service,
    )
    assert initialized is not None
    assert initialized["result"]["serverInfo"]["name"] == "verigym-synopsys-verifier"
    listed = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, service)
    assert listed is not None
    tools = listed["result"]["tools"]
    names = {item["name"] for item in tools}
    assert names == {
        "verigym.synopsys.dc.list_profiles",
        "verigym.synopsys.dc.resolve_profile",
        "verigym.synopsys.dc.synthesize",
    }
    synthesis_schema = next(
        item["inputSchema"] for item in tools if item["name"] == SYNTHESIZE_TOOL
    )
    assert "tcl" not in json.dumps(synthesis_schema).lower()
    assert synthesis_schema["additionalProperties"] is False


def test_mcp_stdio_entrypoint_uses_newline_delimited_json_rpc(tmp_path: Path) -> None:
    profile_path, _ = _site_profile(tmp_path)
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "verigym_synopsys.mcp_server",
            "--profile",
            str(profile_path),
            "--work-root",
            str(tmp_path / "stdio-work"),
        ],
        input="".join(json.dumps(message) + "\n" for message in messages),
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [item["id"] for item in responses] == [1, 2]
    assert responses[1]["result"]["tools"][0]["name"] == LIST_PROFILES_TOOL


def test_mcp_synthesis_binds_profile_sources_and_exports_candidate_artifacts(
    tmp_path: Path,
) -> None:
    profile_path, rtl = _site_profile(tmp_path)
    profile = ToolchainProfileRegistry().load_file(profile_path)
    declared_hash = content_hash(profile)
    service = DesignCompilerMcpService([profile_path], tmp_path / "mcp-work")
    listed = _handle(_tool_call(1, LIST_PROFILES_TOOL, {}), service)
    assert listed is not None
    list_result = listed["result"]
    assert list_result["isError"] is False
    assert list_result["structuredContent"]["profiles"][0]["declared_profile_hash"] == declared_hash
    arguments: dict[str, object] = {
        "profile_id": profile.id,
        "declared_profile_hash": declared_hash,
        "reference_candidate_hash": "b" * 64,
        "top": "counter",
        "sources": [
            {
                "path": "rtl/counter.v",
                "sha256": hashlib.sha256(rtl).hexdigest(),
                "content_base64": base64.b64encode(rtl).decode("ascii"),
            }
        ],
        "run_label": "candidate",
    }
    response = _handle(_tool_call(2, SYNTHESIZE_TOOL, arguments), service)
    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["tool_result"]["success"] is True
    assert structured["tool_result"]["stdout"] == ""
    assert structured["tool_result"]["stderr"] == ""
    metrics = structured["tool_result"]["metadata"]["synthesis"]
    assert metrics["mapped_area_raw"] == 42.5
    assert metrics["critical_path_delay_raw"] == 3.25
    assert metrics["total_power_raw"] == 8.8
    artifacts = {item["path"]: item for item in structured["artifacts"]}
    assert base64.b64decode(artifacts["qor.rpt"]["content_base64"]) == b"Leaf Cell Count: 17\n"
    serialized = json.dumps(structured)
    assert str(tmp_path) not in serialized
    assert "private-db" not in serialized
    assert "create_clock" not in serialized

    rejected = _handle(
        _tool_call(3, SYNTHESIZE_TOOL, {**arguments, "tcl": "exec arbitrary-command"}),
        service,
    )
    assert rejected is not None
    assert rejected["result"]["isError"] is True
    assert "arbitrary-command" not in json.dumps(rejected)


def test_mcp_reference_response_never_exports_artifact_content(tmp_path: Path) -> None:
    profile_path, rtl = _site_profile(tmp_path)
    profile = ToolchainProfileRegistry().load_file(profile_path)
    service = DesignCompilerMcpService([profile_path], tmp_path / "mcp-work")
    response = _handle(
        _tool_call(
            1,
            SYNTHESIZE_TOOL,
            {
                "profile_id": profile.id,
                "declared_profile_hash": content_hash(profile),
                "reference_candidate_hash": "b" * 64,
                "top": "counter",
                "sources": [
                    {
                        "path": "rtl/counter.v",
                        "sha256": hashlib.sha256(rtl).hexdigest(),
                        "content_base64": base64.b64encode(rtl).decode("ascii"),
                    }
                ],
                "run_label": "reference",
            },
        ),
        service,
    )
    assert response is not None
    structured = response["result"]["structuredContent"]
    assert structured["tool_result"]["artifacts"] == []
    assert all(item["content_base64"] is None for item in structured["artifacts"])
