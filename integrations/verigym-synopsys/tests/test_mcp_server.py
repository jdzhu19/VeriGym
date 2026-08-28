from __future__ import annotations

import base64
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from verigym.core.synthesis import execute_synthesis_quality
from verigym.plugin_api import ConfigurationError, ToolContext, content_hash
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.runtimes.base import Runtime, RuntimeSession
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.common import (
    RuntimeDescriptor,
    RuntimeImageIdentity,
    RuntimeResourceSummary,
    RuntimeSecuritySummary,
)
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.task import Candidate

from verigym_synopsys.agent_worker import _launcher_contract, _run_lsf
from verigym_synopsys.agent_worker_protocol import (
    AgentWorkerDescribeResponse,
    AgentWorkerEnvelope,
    AgentWorkerLaunchRequest,
)
from verigym_synopsys.export_mcp_profile import (
    bind_mcp_client_profile_to_docker,
)
from verigym_synopsys.export_mcp_profile import (
    main as export_mcp_profile,
)
from verigym_synopsys.mcp_client import McpDesignCompilerSynthesisTool, _run_stdio
from verigym_synopsys.mcp_server import (
    LIST_PROFILES_TOOL,
    SYNTHESIZE_TOOL,
    DesignCompilerMcpService,
    McpSource,
    McpSynthesisRequest,
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


def _fake_agent_worker(tmp_path: Path, profile_path: Path) -> Path:
    worker = tmp_path / "agent-worker"
    worker.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib, json, sys\n"
        "from pathlib import Path\n"
        "from verigym_synopsys.agent_worker_protocol import "
        "AgentWorkerEnvelope, AgentWorkerLaunchRequest, AgentWorkerReceipt\n"
        "from verigym_synopsys.mcp_server import "
        "DesignCompilerMcpService, McpSynthesisRequest\n"
        "raw = json.load(sys.stdin)\n"
        "if raw.get('operation') == 'describe':\n"
        "    print(json.dumps({'protocol': 'verigym.synopsys.dc.agent_worker.v1', "
        "'contract': {'protocol': 'verigym.synopsys.dc.agent_worker.v1', "
        "'isolation_kind': 'lsf_job', 'launcher_version': 'test-v1', "
        "'code_identity_hash': 'f' * 64, "
        "'isolation_profile_hash': 'e' * 64, 'disposable_worker': True, "
        "'one_candidate_per_worker': True, 'cleanup_before_response': True, "
        "'credential_scope': 'worker_only', 'network_policy': 'site_license_controlled', "
        "'raw_artifacts_returned': False, 'max_wall_seconds': 30, "
        "'memory_mb': 512, 'cores': 1}}))\n"
        "    raise SystemExit(0)\n"
        "request = AgentWorkerLaunchRequest.model_validate(raw)\n"
        f"service = DesignCompilerMcpService([Path({str(profile_path)!r})], "
        f"Path({str(tmp_path / 'worker-private')!r}))\n"
        "synthesis = service._synthesize_local("
        "McpSynthesisRequest.model_validate(request.synthesis))\n"
        "dispatch = hashlib.sha256(request.request_hash.encode()).hexdigest()\n"
        "response = AgentWorkerEnvelope(success=True, synthesis=synthesis, "
        "receipt=AgentWorkerReceipt(contract_hash=request.contract_hash, "
        "code_identity_hash=request.code_identity_hash, "
        "isolation_profile_hash=request.isolation_profile_hash, "
        "request_hash=request.request_hash, source_bundle_hash=request.source_bundle_hash, "
        "dispatch_id_hash=dispatch, scheduler_dispatched=True, worker_started=True, "
        "worker_completed=True, cleanup_complete=True, lifecycle='completed_clean', "
        "duration_s=0.01))\n"
        "print(response.model_dump_json())\n",
        encoding="utf-8",
    )
    worker.chmod(0o755)
    return worker


def _fake_bsub(tmp_path: Path) -> Path:
    executable = tmp_path / "bsub"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        "environment = dict(os.environ)\n"
        "environment['LSB_JOBID'] = '12345'\n"
        "print('Job <12345> is submitted to queue <test>.', flush=True)\n"
        "completed = subprocess.run(['/bin/sh', sys.argv[-1]], env=environment, check=False)\n"
        "raise SystemExit(completed.returncode)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


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
    task = SimpleNamespace(
        budget=SimpleNamespace(max_output_bytes_per_tool=1_000_000),
        metadata={},
        workspace=SimpleNamespace(entrypoints=["rtl/counter.v"]),
    )
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


def test_agent_feedback_uses_hash_bound_disposable_worker_and_returns_no_reports(
    tmp_path: Path,
) -> None:
    server_profile_path, rtl = _site_profile(tmp_path)
    worker = _fake_agent_worker(tmp_path, server_profile_path)
    worker_hash = hashlib.sha256(worker.read_bytes()).hexdigest()
    with pytest.raises(ConfigurationError, match="reserve 300 seconds"):
        DesignCompilerMcpService(
            [server_profile_path],
            tmp_path / "short-timeout-work",
            agent_worker_executable=worker,
            agent_worker_sha256=worker_hash,
            agent_worker_timeout_s=329,
        )
    service = DesignCompilerMcpService(
        [server_profile_path],
        tmp_path / "probe-work",
        agent_worker_executable=worker,
        agent_worker_sha256=worker_hash,
        agent_worker_timeout_s=330,
    )
    worker_summary = service._agent_worker_summary()
    assert worker_summary is not None
    contract_hash = worker_summary["contract_hash"]

    transport = tmp_path / "dc-agent-mcp-transport"
    transport.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} -m verigym_synopsys.mcp_server "
        f"--profile {shlex.quote(str(server_profile_path))} "
        f"--work-root {shlex.quote(str(tmp_path / 'server-work'))} "
        f"--agent-worker-executable {shlex.quote(str(worker))} "
        f"--agent-worker-sha256 {worker_hash} --agent-worker-timeout 330\n",
        encoding="utf-8",
    )
    transport.chmod(0o755)
    client_profile_path = tmp_path / "agent-client.yaml"
    assert (
        export_mcp_profile(
            [
                "--server-profile",
                str(server_profile_path),
                "--transport-executable",
                str(transport),
                "--output-profile",
                str(client_profile_path),
                "--agent-feedback-worker-contract-hash",
                contract_hash,
                "--agent-feedback-worker-isolation-kind",
                "lsf_job",
            ]
        )
        == 0
    )
    profile = ToolchainProfileRegistry().load_file(client_profile_path)
    plugin = McpDesignCompilerSynthesisTool()
    runtime = LocalRuntime()
    reference_hash = content_hash(Candidate(files={"rtl/counter.v": rtl.decode()}))
    resolved = plugin.resolve_profile(
        profile,
        runtime,
        source_paths=["rtl/counter.v"],
        top_module="counter",
        reference_candidate_hash=reference_hash,
    )
    assert resolved.metadata["agent_feedback_worker_contract_hash"] == contract_hash
    source = tmp_path / "agent-source"
    (source / "rtl").mkdir(parents=True)
    (source / "rtl" / "counter.v").write_bytes(rtl)
    session = runtime.create_session(
        SessionSpec(source_dir=str(source), label="agent-feedback", max_output_bytes=1_000_000)
    )
    artifacts = tmp_path / "agent-artifacts"
    try:
        result = plugin.execute(
            plugin.build_agent_feedback_request(profile, resolved),
            ToolContext(session=session, artifact_dir=artifacts),
        )
    finally:
        session.close()
        runtime.close()

    assert result.success, result.message
    assert result.metadata["synthesis"]["mapped_area_raw"] == 42.5
    receipt = result.metadata["agent_feedback_execution"]
    assert receipt["contract_hash"] == contract_hash
    assert receipt["scheduler_dispatched"] is True
    assert receipt["cleanup_complete"] is True
    assert result.artifacts == []
    assert result.diagnostics == []
    assert not artifacts.exists()
    serialized = json.dumps(result.model_dump(mode="json"))
    assert str(tmp_path) not in serialized
    lowered = serialized.lower()
    for forbidden in ('"reference_candidate', '"ratio"', "netlist.v", "dc.log", "license"):
        assert forbidden not in lowered


def test_lsf_launcher_runs_one_job_and_cleans_the_disposable_workspace(tmp_path: Path) -> None:
    profile_path, rtl = _site_profile(tmp_path)
    profile = ToolchainProfileRegistry().load_file(profile_path)
    work_root = tmp_path / "lsf-launches"
    launcher_argv = [
        sys.executable,
        "-m",
        "verigym_synopsys.agent_worker",
        "lsf",
        "--profile",
        str(profile_path),
        "--work-root",
        str(work_root),
        "--queue",
        "test",
        "--python-executable",
        sys.executable,
        "--bsub-executable",
        str(_fake_bsub(tmp_path)),
        "--max-wall-seconds",
        "30",
        "--memory-mb",
        "512",
        "--cores",
        "1",
    ]
    described = subprocess.run(
        launcher_argv,
        input=json.dumps({"operation": "describe"}),
        capture_output=True,
        check=False,
        text=True,
        timeout=45,
    )
    assert described.returncode == 0, described.stderr
    contract = AgentWorkerDescribeResponse.model_validate_json(described.stdout).contract
    synthesis = McpSynthesisRequest(
        profile_id=profile.id,
        declared_profile_hash=content_hash(profile),
        reference_candidate_hash="b" * 64,
        top="counter",
        sources=[
            McpSource(
                path="rtl/counter.v",
                sha256=hashlib.sha256(rtl).hexdigest(),
                content_base64=base64.b64encode(rtl).decode("ascii"),
            )
        ],
        run_label="agent_feedback",
        artifact_content_policy="none",
    )
    source_bundle = [{"path": item.path, "sha256": item.sha256} for item in synthesis.sources]
    launch = AgentWorkerLaunchRequest(
        contract_hash="c" * 64,
        code_identity_hash=contract.code_identity_hash,
        isolation_profile_hash=contract.isolation_profile_hash,
        request_hash=content_hash(synthesis.model_dump(mode="json")),
        source_bundle_hash=content_hash({"top": synthesis.top, "sources": source_bundle}),
        synthesis=synthesis.model_dump(mode="json"),
    )
    completed = subprocess.run(
        launcher_argv,
        input=launch.model_dump_json(),
        capture_output=True,
        check=False,
        text=True,
        timeout=45,
    )

    assert completed.returncode == 0, completed.stderr
    envelope = AgentWorkerEnvelope.model_validate_json(completed.stdout)
    assert envelope.success
    assert envelope.receipt.scheduler_dispatched
    assert envelope.receipt.worker_started
    assert envelope.receipt.worker_completed
    assert envelope.receipt.cleanup_complete
    assert envelope.receipt.lifecycle == "completed_clean"
    assert envelope.synthesis is not None
    assert envelope.synthesis["artifacts"] == []
    assert list(work_root.iterdir()) == []


def test_lsf_launcher_timeout_returns_only_a_clean_failure_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path, rtl = _site_profile(tmp_path)
    profile = ToolchainProfileRegistry().load_file(profile_path)
    work_root = tmp_path / "timed-out-lsf-launches"
    args = SimpleNamespace(
        profile=[profile_path],
        work_root=work_root,
        queue="test",
        python_executable=Path(sys.executable),
        bsub_executable=_fake_bsub(tmp_path),
        max_wall_seconds=1,
        memory_mb=512,
        cores=1,
    )
    contract = _launcher_contract(args)
    synthesis = McpSynthesisRequest(
        profile_id=profile.id,
        declared_profile_hash=content_hash(profile),
        reference_candidate_hash="b" * 64,
        top="counter",
        sources=[
            McpSource(
                path="rtl/counter.v",
                sha256=hashlib.sha256(rtl).hexdigest(),
                content_base64=base64.b64encode(rtl).decode("ascii"),
            )
        ],
        run_label="agent_feedback",
        artifact_content_policy="none",
    )
    source_bundle = [{"path": item.path, "sha256": item.sha256} for item in synthesis.sources]
    launch = AgentWorkerLaunchRequest(
        contract_hash="c" * 64,
        code_identity_hash=contract.code_identity_hash,
        isolation_profile_hash=contract.isolation_profile_hash,
        request_hash=content_hash(synthesis.model_dump(mode="json")),
        source_bundle_hash=content_hash({"top": synthesis.top, "sources": source_bundle}),
        synthesis=synthesis.model_dump(mode="json"),
    )

    def time_out(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="bsub", timeout=1)

    monkeypatch.setattr("verigym_synopsys.agent_worker.subprocess.run", time_out)
    envelope = _run_lsf(launch, args)

    assert envelope.success is False
    assert envelope.failure_category == "scheduler"
    assert envelope.receipt.lifecycle == "infrastructure_failed_clean"
    assert envelope.receipt.cleanup_complete is True
    assert list(work_root.iterdir()) == []


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


def test_existing_mcp_client_profile_can_be_bound_to_docker(tmp_path: Path) -> None:
    server_profile_path, _ = _site_profile(tmp_path)
    output = tmp_path / "client.yaml"
    assert (
        export_mcp_profile(
            [
                "--server-profile",
                str(server_profile_path),
                "--transport-executable",
                sys.executable,
                "--transport-sha256",
                "e" * 64,
                "--output-profile",
                str(output),
            ]
        )
        == 0
    )
    client = ToolchainProfileRegistry().load_file(output)
    image_id = "sha256:" + "d" * 64
    bound = bind_mcp_client_profile_to_docker(
        client,
        image="example/rtl-tools:frozen",
        prepared_image_id=image_id,
        profile_id="docker-client",
        profile_version="1.0.0",
    )

    assert bound.runtime.runtime == "docker"
    assert bound.container_image == "example/rtl-tools:frozen"
    assert bound.metadata["prepared_image_id"] == image_id
    assert bound.metadata["mcp_transport_execution_boundary"] == ("host_verifier_control_plane")


def test_docker_mcp_profile_uses_host_control_plane_over_private_staging(
    tmp_path: Path,
) -> None:
    server_profile_path, rtl = _site_profile(tmp_path)
    wrapper = tmp_path / "docker-dc-mcp-transport"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} -m verigym_synopsys.mcp_server "
        f"--profile {shlex.quote(str(server_profile_path))} "
        f"--work-root {shlex.quote(str(tmp_path / 'docker-remote-work'))}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    image = "verigym/open-rtl-tools:iverilog12-yosys067-opensta310"
    image_id = "sha256:" + "d" * 64
    profile_path = tmp_path / "docker-client.yaml"
    assert (
        export_mcp_profile(
            [
                "--server-profile",
                str(server_profile_path),
                "--transport-executable",
                str(wrapper),
                "--output-profile",
                str(profile_path),
                "--runtime",
                "docker",
                "--docker-image",
                image,
                "--prepared-image-id",
                image_id,
            ]
        )
        == 0
    )
    profile = ToolchainProfileRegistry().load_file(profile_path)
    descriptor = RuntimeDescriptor(
        name="docker",
        version="0.1.0",
        provider="verigym",
        isolation_level="docker_standard",
        image=RuntimeImageIdentity(
            requested_reference=image,
            resolved_image_id=image_id,
            os="linux",
            architecture="amd64",
            effective_user="10001:10001",
        ),
        security=RuntimeSecuritySummary(
            network_mode="none",
            read_only_rootfs=True,
            configured_user="10001:10001",
            cap_drop=["ALL"],
            no_new_privileges=True,
        ),
        resources=RuntimeResourceSummary(
            memory_bytes=512 * 1024 * 1024,
            memory_swap_bytes=512 * 1024 * 1024,
            swap_enforced=True,
            cpus=1.0,
            pids_limit=128,
            tmpfs_bytes=64 * 1024 * 1024,
            max_command_time_s=900,
        ),
    )
    runtime = cast(Runtime, SimpleNamespace(descriptor=descriptor))
    plugin = McpDesignCompilerSynthesisTool()
    reference_hash = content_hash(Candidate(files={"rtl/counter.v": rtl.decode()}))
    resolved = plugin.resolve_profile(
        profile,
        runtime,
        source_paths=["rtl/counter.v"],
        top_module="counter",
        reference_candidate_hash=reference_hash,
    )
    assert resolved.runtime_identity.resolved_image_id == image_id
    request = plugin.build_synthesis_request(profile, resolved, run_label="candidate")
    assert request["transport_execution_boundary"] == "host_verifier_control_plane"

    source = tmp_path / "docker-private-staging"
    (source / "rtl").mkdir(parents=True)
    (source / "rtl" / "counter.v").write_bytes(rtl)

    def refuse_runtime_execution(_command: object) -> None:
        raise AssertionError("the commercial MCP wrapper must not execute inside the RTL image")

    session = cast(
        RuntimeSession,
        SimpleNamespace(root=source, execute=refuse_runtime_execution),
    )
    result = plugin.execute(request, ToolContext(session=session, artifact_dir=tmp_path / "out"))

    assert result.success, result.message
    assert result.metadata["synthesis"]["mapped_area_raw"] == 42.5
