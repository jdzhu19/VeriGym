from __future__ import annotations

import hashlib
import json
import shlex
import sys
from pathlib import Path

import pytest
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
from verigym.profiles.verifier_registry import load_verifier_profile
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

from verigym_synopsys.export_vcs_mcp_profile import main as export_vcs_profile
from verigym_synopsys.merge_verilog_eval_vcs_qualifications import (
    main as merge_verilog_eval_vcs_qualifications,
)
from verigym_synopsys.prepare_verilog_eval_vcs_bundle import (
    main as prepare_verilog_eval_vcs_bundle,
)
from verigym_synopsys.qualify_verilog_eval_vcs_bundle import (
    main as qualify_verilog_eval_vcs_bundle,
)
from verigym_synopsys.reissue_vcs_mcp_profile import main as reissue_vcs_profile
from verigym_synopsys.vcs_mcp_client import (
    DEFAULT_VCS_MCP_PROFILE_ENVIRONMENT,
    LEGACY_VCS_MCP_PROFILE_ENVIRONMENT,
    McpVcsSimulationTool,
)
from verigym_synopsys.vcs_mcp_profile import (
    SERVER_VERSION,
    SERVICE_PROTOCOL,
    VcsMcpAuxiliaryFile,
    VcsMcpServerProfile,
    load_vcs_server_profile,
)
from verigym_synopsys.vcs_mcp_server import (
    RESOLVE_PROFILE_TOOL,
    SIMULATE_TOOL,
    VcsMcpRequestError,
    VcsMcpService,
    _handle,
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


def test_prepare_verilog_eval_vcs_bundle_freezes_every_fixture_task(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    fixture = repository / "tests/fixtures/verilog_eval_v2_synthetic"
    executable = tmp_path / "vcs"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if '-ID' in sys.argv:\n"
        " print('Compiler version = VCS V-2023.12-SP2-2_Full64')\n"
        " raise SystemExit(0)\n"
        "print('Mismatches: 0 in 1 samples')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    output = tmp_path / "bundle"

    assert (
        prepare_verilog_eval_vcs_bundle(
            [
                "--source-root",
                str(fixture),
                "--output-root",
                str(output),
                "--vcs",
                str(executable),
                "--python-executable",
                sys.executable,
            ]
        )
        == 0
    )

    catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["kind"] == "verilog_eval_vcs_mcp_profile_bundle_v1"
    assert catalog["variant"] == "v2-spec-to-rtl-agent-eval-vcs-mcp-v1"
    assert catalog["task_count"] == 2
    assert catalog["model_calls"] == 0
    assert len(catalog["bundle_identity_hash"]) == 64
    assert not (output / "INCOMPLETE").exists()
    for record in catalog["records"]:
        client = load_verifier_profile(output / record["client_profile"])
        server = load_vcs_server_profile(output / record["server_profile"])
        assert client.task_id == record["task_id"]
        assert client.source_plugin == "synopsys.vcs.simulate"
        assert client.target_plugin == "synopsys.vcs.mcp"
        assert server.sources == ["repository/rtl/TopModule.sv"]
        assert server.testbench_mount_path == "verifier/testbench.sv"
        assert server.pass_marker == "Mismatches: 0 in"
        assert server.fail_marker == "VERIGYM_VCS_EXPLICIT_FAIL"
        assert server.timeout_s == 180
        assert Path(server.testbench).stat().st_mode & 0o777 == 0o600
        assert Path(client.transport_executable).stat().st_mode & 0o777 == 0o700

    receipt_path = tmp_path / "qualification.json"
    assert (
        qualify_verilog_eval_vcs_bundle(
            [
                "--source-root",
                str(fixture),
                "--bundle-root",
                str(output),
                "--work-root",
                str(tmp_path / "qualification-work"),
                "--output",
                str(receipt_path),
                "--reference-only",
            ]
        )
        == 0
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["passed"] is True
    assert receipt["task_count"] == 2
    assert receipt["commercial_jobs"] == 2
    assert receipt["model_calls"] == 0
    assert receipt["automatic_retries"] == 0

    aggregate_path = tmp_path / "qualification-aggregate.json"
    assert (
        merge_verilog_eval_vcs_qualifications(
            ["--input", str(receipt_path), "--output", str(aggregate_path)]
        )
        == 0
    )
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    assert aggregate["passed"] is True
    assert aggregate["task_count"] == 2
    assert aggregate["commercial_jobs"] == 2
    assert aggregate["reference_passes"] == 2
    assert aggregate["known_bad_rejections"] == 0


def test_vcs_exporter_can_replace_an_iverilog_hidden_node(tmp_path: Path) -> None:
    server, _server_path, wrapper = _fixture(tmp_path)
    output = tmp_path / "client-profile.yaml"

    assert (
        export_vcs_profile(
            [
                "--id",
                "rtllm-harder-vcs-client-v1",
                "--version",
                "2.0.0",
                "--server-profile-id",
                server.id,
                "--server-declared-profile-hash",
                content_hash(server),
                "--server-contract-hash",
                server.contract_hash,
                "--task-id",
                server.task_id,
                "--source-plugin",
                "iverilog.simulate",
                "--transport-executable",
                str(wrapper),
                "--output-profile",
                str(output),
            ]
        )
        == 0
    )
    exported = load_verifier_profile(output)
    assert exported.source_plugin == "iverilog.simulate"
    assert exported.version == "2.0.0"


def test_vcs_profile_mismatch_has_a_stable_safe_reason_code(tmp_path: Path) -> None:
    profile, profile_path, _ = _fixture(tmp_path)
    service = VcsMcpService([profile_path], tmp_path / "reason-work")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": RESOLVE_PROFILE_TOOL,
            "arguments": {
                "profile_id": profile.id,
                "declared_profile_hash": "0" * 64,
                "contract_hash": profile.contract_hash,
            },
        },
    }

    response = _handle(request, service)

    assert response is not None
    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"] == {
        "error": "declared profile hash differs from the server profile",
        "reason_code": "profile_identity_mismatch",
    }
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert profile.executable not in serialized


def test_doctor_prefers_the_v2_profile_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, _, wrapper = _fixture(tmp_path)
    client = _client_profile(server, wrapper).model_copy(update={"version": "2.0.0"})
    profile_path = tmp_path / "client-v2.yaml"
    profile_path.write_text(
        yaml.safe_dump(client.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setenv(DEFAULT_VCS_MCP_PROFILE_ENVIRONMENT, str(profile_path))
    monkeypatch.setenv(LEGACY_VCS_MCP_PROFILE_ENVIRONMENT, str(tmp_path / "missing-v1.yaml"))

    health = McpVcsSimulationTool().health_check()

    assert health.healthy is True
    assert health.version == server.accepted_tool_version


def test_reissue_creates_a_new_stable_v2_identity_without_changing_v1(
    tmp_path: Path,
) -> None:
    server, server_path, wrapper = _fixture(tmp_path)
    client_path = tmp_path / "client-v1.yaml"
    client_path.write_text(
        yaml.safe_dump(_client_profile(server, wrapper).model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    original_server = server_path.read_bytes()
    original_client = client_path.read_bytes()
    output = tmp_path / "issued-v2"
    receipt = tmp_path / "receipt-v2.json"

    assert (
        reissue_vcs_profile(
            [
                "--base-server",
                str(server_path),
                "--base-client",
                str(client_path),
                "--server-id",
                "rtllm-counter-vcs-v2",
                "--client-id",
                "rtllm-counter-vcs-mcp-local-v2",
                "--output-dir",
                str(output),
                "--receipt",
                str(receipt),
            ]
        )
        == 0
    )

    issued_server = load_vcs_server_profile(output / "server-v2.yaml")
    issued_client = load_verifier_profile(output / "client-v2.yaml")
    result = json.loads(receipt.read_text(encoding="utf-8"))
    assert server_path.read_bytes() == original_server
    assert client_path.read_bytes() == original_client
    assert issued_server.version == issued_client.version == "2.0.0"
    assert issued_client.server_declared_profile_hash == content_hash(issued_server)
    assert issued_client.server_contract_hash == issued_server.contract_hash
    assert result["cause"] == "server_client_canonical_profile_hash_drift"
    assert result["license_failure"] is False
    assert result["tool_failure"] is False
    assert result["repeated_resolution_stable"] is True
    assert str(tmp_path) not in json.dumps(result)


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


def test_vcs_mcp_stages_server_owned_auxiliary_files_without_exposing_paths(
    tmp_path: Path,
) -> None:
    base, _, _ = _fixture(tmp_path)
    auxiliary = tmp_path / "private-wfull.txt"
    auxiliary.write_text("0\n1\n", encoding="utf-8")
    profile = base.model_copy(
        update={
            "auxiliary_files": [
                VcsMcpAuxiliaryFile(
                    path=str(auxiliary),
                    mount_path="wfull.txt",
                    sha256=hash_bytes(auxiliary.read_bytes()),
                )
            ]
        },
        deep=True,
    )
    profile_path = tmp_path / "server-profile-with-aux.yaml"
    profile_path.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    rtl = b"module counter_12; endmodule\n"
    source_hash = hash_bytes(rtl)
    response = VcsMcpService([profile_path], tmp_path / "aux-work").call(
        SIMULATE_TOOL,
        {
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
            "auxiliary_files": ["wfull.txt"],
            "top": "tb",
            "pass_marker": "VERIGYM_PASS",
            "fail_marker": "VERIGYM_FAIL",
        },
    )

    assert response["profile"]["auxiliary_files"] == [
        {"mount_path": "wfull.txt", "sha256": hash_bytes(auxiliary.read_bytes())}
    ]
    serialized = json.dumps(response)
    assert str(auxiliary) not in serialized
    assert str(tmp_path) not in serialized
