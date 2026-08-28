from __future__ import annotations

import hashlib
import json
import shlex
import sys
from pathlib import Path

import yaml
from verigym.core.verifier_profiles import resolve_verifier_profile, task_with_verifier_profile
from verigym.plugin_api import (
    AssetRef,
    InteractionMode,
    TaskType,
    ToolContext,
    ToolVisibility,
    VerifierToolProfile,
    content_hash,
    hash_bytes,
)
from verigym.registry.base import PluginRegistry
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.task import (
    BudgetSpec,
    InteractionSpec,
    ScoringSpec,
    SourceSpec,
    SubmissionPolicy,
    VeriTask,
    WorkspaceSpec,
)
from verigym.schemas.verifier import VerifierGraph, VerifierNode
from verigym.tools.base import ToolPlugin

from verigym_synopsys.vcs_mcp_client import McpVcsSimulationTool
from verigym_synopsys.vcs_mcp_profile import (
    SERVER_VERSION,
    SERVICE_PROTOCOL,
    VcsMcpServerProfile,
)
from verigym_synopsys.vcs_mcp_server import (
    SIMULATE_TOOL,
    VcsMcpRequestError,
    VcsMcpService,
    tool_definitions,
)


def _fixture(tmp_path: Path) -> tuple[VcsMcpServerProfile, Path, Path]:
    testbench = tmp_path / "hidden-testbench.v"
    testbench.write_text('module tb; initial $display("VERIGYM_PASS"); endmodule\n')
    executable = tmp_path / "vcs"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "if '-ID' in sys.argv:\n"
        " print('Compiler version = VCS V-2023.12-SP2-2_Full64')\n"
        " raise SystemExit(0)\n"
        "out = pathlib.Path('out')\n"
        "out.mkdir(exist_ok=True)\n"
        "(out / 'vcs.log').write_text('site/private/path\\nVERIGYM_PASS\\n')\n"
        "print('VERIGYM_PASS')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    profile = VcsMcpServerProfile(
        id="rtllm-counter-vcs-v1",
        task_id="rtllm/counter_12",
        executable=str(executable),
        accepted_tool_version="V-2023.12-SP2-2_Full64",
        sources=["rtl/counter_12.v"],
        testbench=str(testbench),
        testbench_sha256=hash_bytes(testbench.read_bytes()),
        top="tb",
        pass_marker="VERIGYM_PASS",
        fail_marker="VERIGYM_FAIL",
    )
    profile_path = tmp_path / "server-profile.yaml"
    profile_path.write_text(yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False))
    wrapper = tmp_path / "vcs-mcp-transport"
    repository = Path(__file__).resolve().parents[3]
    python_path = f"{repository / 'src'}:{repository / 'integrations/verigym-synopsys/src'}"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export PYTHONPATH={shlex.quote(python_path)}\n"
        f"exec {shlex.quote(sys.executable)} -m verigym_synopsys.vcs_mcp_server "
        f"--profile {shlex.quote(str(profile_path))} "
        f"--work-root {shlex.quote(str(tmp_path / 'service-work'))}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return profile, profile_path, wrapper


def _client_profile(server: VcsMcpServerProfile, wrapper: Path) -> VerifierToolProfile:
    return VerifierToolProfile(
        id="rtllm-counter-vcs-mcp-local-v1",
        version="1.0.0",
        task_id=server.task_id,
        source_plugin="synopsys.vcs.simulate",
        target_plugin="synopsys.vcs.mcp",
        transport_executable=str(wrapper),
        transport_sha256=hash_bytes(wrapper.read_bytes()),
        service_protocol=SERVICE_PROTOCOL,
        server_version=SERVER_VERSION,
        server_profile_id=server.id,
        server_declared_profile_hash=content_hash(server),
        server_contract_hash=server.contract_hash,
        accepted_tool_version=server.accepted_tool_version,
    )


def test_vcs_mcp_surface_is_fixed_and_response_is_sanitized(tmp_path: Path) -> None:
    profile, profile_path, _ = _fixture(tmp_path)
    definitions = tool_definitions()
    assert {item["name"] for item in definitions} == {
        "verigym.synopsys.vcs.list_profiles",
        "verigym.synopsys.vcs.resolve_profile",
        "verigym.synopsys.vcs.simulate",
    }
    simulation_schema = next(
        item["inputSchema"] for item in definitions if item["name"] == SIMULATE_TOOL
    )
    assert simulation_schema["additionalProperties"] is False
    serialized = json.dumps(simulation_schema).lower()
    assert "flags" not in serialized
    assert "command" not in serialized
    assert "environment" not in serialized

    service = VcsMcpService([profile_path], tmp_path / "direct-work")
    rtl = b"module counter_12; endmodule\n"
    source_hash = hashlib.sha256(rtl).hexdigest()
    arguments = {
        "profile_id": profile.id,
        "declared_profile_hash": content_hash(profile),
        "contract_hash": profile.contract_hash,
        "task_id": profile.task_id,
        "candidate_hash": content_hash({"sources": {"rtl/counter_12.v": source_hash}}),
        "sources": [
            {
                "path": "rtl/counter_12.v",
                "sha256": source_hash,
                "content_base64": __import__("base64").b64encode(rtl).decode(),
            }
        ],
        "testbench_mount_path": "verifier/testbench.v",
        "top": "tb",
        "pass_marker": "VERIGYM_PASS",
        "fail_marker": "VERIGYM_FAIL",
    }
    response = service.call(SIMULATE_TOOL, arguments)
    result = response["tool_result"]
    assert result["success"] is True
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert result["artifacts"] == []
    assert str(tmp_path) not in json.dumps(response)
    assert "site/private/path" not in json.dumps(response)
    bad_arguments = {**arguments, "candidate_hash": "a" * 64}
    with __import__("pytest").raises(VcsMcpRequestError, match="candidate hash differs"):
        service.call(SIMULATE_TOOL, bad_arguments)


def test_vcs_mcp_client_resolves_executes_and_binds_task_graph(tmp_path: Path) -> None:
    server, _, wrapper = _fixture(tmp_path)
    client = _client_profile(server, wrapper)
    plugin = McpVcsSimulationTool()
    registry: PluginRegistry[ToolPlugin] = PluginRegistry("tools")
    registry.register(plugin)
    task = VeriTask(
        id=server.task_id,
        suite="rtllm",
        suite_version="1",
        task_type=TaskType.GENERATION,
        title="fixed VCS MCP test",
        description="fixed VCS MCP test",
        source=SourceSpec(kind="synthetic"),
        workspace=WorkspaceSpec(
            base=AssetRef(kind="inline", content=""),
            editable_globs=["rtl/*.v"],
            entrypoints=["rtl/counter_12.v"],
        ),
        interaction=InteractionSpec(
            supported_modes=[InteractionMode.CHAT],
            default_mode=InteractionMode.CHAT,
            allowed_tools=[],
            final_submission=SubmissionPolicy(kind="file", path="rtl/counter_12.v"),
        ),
        budget=BudgetSpec(),
        verifier=VerifierGraph(
            nodes=[
                VerifierNode(
                    id="vcs_regression",
                    plugin="synopsys.vcs.simulate",
                    visibility=ToolVisibility.VERIFIER_ONLY,
                    request={
                        "sources": ["rtl/counter_12.v"],
                        "testbench": "verifier/testbench.v",
                        "top": "tb",
                        "pass_marker": "VERIGYM_PASS",
                        "fail_marker": "VERIGYM_FAIL",
                        "timeout_s": server.timeout_s,
                    },
                )
            ]
        ),
        scoring=ScoringSpec(correctness_required_nodes=["vcs_regression"]),
    )
    resolved = resolve_verifier_profile(task=task, profile=client, tools=registry)
    assert resolved.tool_version == "V-2023.12-SP2-2_Full64"
    assert plugin.resolve_verifier_profile(client, expected=resolved) == resolved
    transformed = task_with_verifier_profile(task, client)
    assert transformed.verifier.nodes[0].plugin == "synopsys.vcs.mcp"

    source = tmp_path / "source"
    (source / "rtl").mkdir(parents=True)
    (source / "verifier").mkdir()
    (source / "rtl" / "counter_12.v").write_text("module counter_12; endmodule\n")
    (source / "verifier" / "testbench.v").write_bytes(Path(server.testbench).read_bytes())
    runtime = LocalRuntime()
    session = runtime.create_session(
        SessionSpec(source_dir=str(source), label="vcs-mcp-client", max_output_bytes=1_000_000)
    )
    try:
        result = plugin.execute(
            transformed.verifier.nodes[0].request,
            ToolContext(
                session=session,
                verifier_profile=client,
                resolved_verifier_profile=resolved,
            ),
        )
    finally:
        session.close()
        runtime.close()
    assert result.success, result.message
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.artifacts == []
    assert result.diagnostics == []

    changed = wrapper.read_bytes() + b"# changed\n"
    wrapper.write_bytes(changed)
    with __import__("pytest").raises(Exception, match="hash differs"):
        plugin.resolve_verifier_profile(client)
