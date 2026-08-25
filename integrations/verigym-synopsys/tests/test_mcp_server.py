from __future__ import annotations

import base64
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.core.synthesis import execute_synthesis_quality
from verigym.plugin_api import ConfigurationError, ToolContext, content_hash
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.task import Candidate

from verigym_synopsys.export_mcp_profile import main as export_mcp_profile
from verigym_synopsys.mcp_client import McpDesignCompilerSynthesisTool, _run_stdio
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


def test_mcp_client_backend_runs_candidate_reference_and_exact_replay(tmp_path: Path) -> None:
    server_profile_path, rtl = _site_profile(tmp_path)
    wrapper = tmp_path / "dc-mcp-transport"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} -m verigym_synopsys.mcp_server "
        f"--profile {shlex.quote(str(server_profile_path))} "
        f"--work-root {shlex.quote(str(tmp_path / 'remote-work'))}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    client_profile_path = tmp_path / "client-profile.yaml"
    assert (
        export_mcp_profile(
            [
                "--server-profile",
                str(server_profile_path),
                "--transport-executable",
                str(wrapper),
                "--output-profile",
                str(client_profile_path),
            ]
        )
        == 0
    )
    client_profile_text = client_profile_path.read_text(encoding="utf-8")
    assert str(server_profile_path) not in client_profile_text
    assert "source_kind: remote_service" in client_profile_text
    server_profile = ToolchainProfileRegistry().load_file(server_profile_path)
    private_uris = [
        item.uri
        for item in [
            *server_profile.libraries,
            *(item for item in server_profile.constraints if hasattr(item, "uri")),
        ]
        if item.uri is not None
    ]
    assert all(uri not in client_profile_text for uri in private_uris)
    client_profile = ToolchainProfileRegistry().load_file(client_profile_path)
    assert client_profile.flow is not None
    assert client_profile.flow.backend_plugin == "synopsys.dc.mcp"
    assert client_profile.libraries[0].uri is None
    assert client_profile.libraries[0].copy_permitted is False

    plugin = McpDesignCompilerSynthesisTool()
    validation = plugin.validate_profile_contract(client_profile)
    assert validation.valid, validation.errors
    runtime = LocalRuntime()
    reference_candidate = Candidate(files={"rtl/counter.v": rtl.decode("utf-8")})
    reference_hash = content_hash(reference_candidate)
    resolved = plugin.resolve_profile(
        client_profile,
        runtime,
        source_paths=["rtl/counter.v"],
        top_module="counter",
        reference_candidate_hash=reference_hash,
    )
    assert resolved.metadata["mcp_server_resolved_profile_hash"]
    assert resolved.resolved_profile_hash != resolved.metadata["mcp_server_resolved_profile_hash"]
    replayed = plugin.resolve_profile(
        client_profile,
        runtime,
        source_paths=["rtl/counter.v"],
        top_module="counter",
        reference_candidate_hash=reference_hash,
        expected=resolved,
    )
    assert replayed == resolved
    tampered = client_profile.model_copy(deep=True)
    tampered.metadata["power_activity"] = 0.2
    with pytest.raises(ConfigurationError, match="flow settings differ"):
        plugin.resolve_profile(
            tampered,
            runtime,
            source_paths=["rtl/counter.v"],
            top_module="counter",
            reference_candidate_hash=reference_hash,
        )
    tampered_version = client_profile.model_copy(deep=True)
    tampered_version.metadata["remote_design_compiler_version"] = "==unexpected-version"
    with pytest.raises(ConfigurationError, match="Design Compiler requirement differs"):
        plugin.resolve_profile(
            tampered_version,
            runtime,
            source_paths=["rtl/counter.v"],
            top_module="counter",
            reference_candidate_hash=reference_hash,
        )

    source = tmp_path / "client-source"
    (source / "rtl").mkdir(parents=True)
    (source / "rtl" / "counter.v").write_bytes(rtl)
    plugin.stage_profile_assets(client_profile, resolved, source)
    session = runtime.create_session(
        SessionSpec(source_dir=str(source), label="mcp-client", max_output_bytes=1_000_000)
    )
    try:
        candidate_artifacts = tmp_path / "candidate-artifacts"
        candidate = plugin.execute(
            plugin.build_synthesis_request(client_profile, resolved, run_label="candidate"),
            ToolContext(session=session, artifact_dir=candidate_artifacts),
        )
        assert candidate.success, candidate.message
        metrics = candidate.metadata["synthesis"]
        assert metrics["resolved_profile_hash"] == resolved.resolved_profile_hash
        assert (
            metrics["tool_identity"]["mcp_server_resolved_profile_hash"]
            == resolved.metadata["mcp_server_resolved_profile_hash"]
        )
        assert metrics["mapped_area_raw"] == 42.5
        assert metrics["critical_path_delay_raw"] == 3.25
        assert metrics["total_power_raw"] == 8.8
        assert (candidate_artifacts / "flow.tcl").is_file()
        assert (candidate_artifacts / "power.rpt").is_file()
        assert not (candidate_artifacts / "netlist.v").exists()
        assert not (candidate_artifacts / "dc.log").exists()

        reference = plugin.execute(
            plugin.build_synthesis_request(client_profile, resolved, run_label="reference"),
            ToolContext(session=session, artifact_dir=tmp_path / "reference-artifacts"),
        )
        assert reference.success, reference.message
        assert reference.artifacts == []
        assert not (tmp_path / "reference-artifacts").exists()
    finally:
        session.close()
    suite = SimpleNamespace(reference_solution=lambda _task: reference_candidate)
    task = SimpleNamespace(budget=SimpleNamespace(max_output_bytes_per_tool=1_000_000))
    evaluation = execute_synthesis_quality(
        suite=suite,
        task=task,
        candidate_dir=source,
        runtime=runtime,
        profile=client_profile,
        resolved=resolved,
        artifact_root=tmp_path / "quality-artifacts",
        plugin=plugin,
        correctness_passed=True,
    )
    assert evaluation.candidate.synthesis_ok
    assert evaluation.reference.synthesis_ok
    assert evaluation.candidate.resolved_profile_hash == resolved.resolved_profile_hash
    assert evaluation.reference.artifacts == []
    assert (tmp_path / "quality-artifacts" / "synopsys_dc_mcp" / "candidate" / "flow.tcl").is_file()
    assert (tmp_path / "quality-artifacts" / "synopsys_dc_mcp" / "reference_summary.json").is_file()
    runtime.close()
    wrapper.write_text(wrapper.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    assert not plugin.validate_profile_contract(client_profile).valid


def test_mcp_control_plane_transport_output_is_bounded(tmp_path: Path) -> None:
    wrapper = tmp_path / "oversized-mcp-transport"
    wrapper.write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.stdout.write('x' * (2 * 1024 * 1024 + 1))\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    completed = _run_stdio(str(wrapper), "", environment_names=[], timeout_s=5)
    assert completed.exit_code == 0
    assert completed.output_truncated
    assert len(completed.stdout.encode("utf-8")) == 2 * 1024 * 1024


def test_mcp_client_profile_can_bind_an_off_host_wrapper_hash(tmp_path: Path) -> None:
    server_profile_path, _ = _site_profile(tmp_path)
    output = tmp_path / "off-host-client.yaml"
    assert (
        export_mcp_profile(
            [
                "--server-profile",
                str(server_profile_path),
                "--transport-executable",
                "/opt/verigym/bin/verigym-dc-mcp-transport",
                "--transport-sha256",
                "c" * 64,
                "--output-profile",
                str(output),
                "--transport-environment",
                "SSH_AUTH_SOCK",
            ]
        )
        == 0
    )
    profile = ToolchainProfileRegistry().load_file(output)
    assert profile.metadata["mcp_transport_sha256"] == "c" * 64
    assert profile.environment_allowlist == ["SSH_AUTH_SOCK"]
