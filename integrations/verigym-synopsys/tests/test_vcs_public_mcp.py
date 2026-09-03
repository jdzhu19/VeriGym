from __future__ import annotations

import json
import os
import shlex
import sys
from difflib import unified_diff
from pathlib import Path
from typing import Any

import pytest
import yaml
from verigym.agents.base import AgentAdapter, AgentContext
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.orchestrator import VeriGym
from verigym.core.public_test_profiles import (
    PublicTestProfileController,
    resolve_public_test_profile,
)
from verigym.core.replay import replay_run
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentDescriptor,
    ApplyPatchAction,
    EpisodeResult,
    ErrorCategory,
    FinalSubmissionAction,
    Observation,
    ToolCallAction,
    ToolResult,
    VerifierToolProfile,
)
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.registry.base import PluginRegistry
from verigym.registry.collections import build_registries
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.task import VeriTask
from verigym.suites.verilog_eval.adapter import VerilogEvalSuite
from verigym.tools.base import ToolPlugin

from verigym_synopsys.prepare_verilog_eval_vcs_public_bundle import (
    main as prepare_public_bundle,
)
from verigym_synopsys.qualify_verilog_eval_vcs_public_bundle import (
    main as qualify_public_bundle,
)
from verigym_synopsys.vcs_mcp_client import McpVcsSimulationTool
from verigym_synopsys.vcs_mcp_profile import (
    SERVER_VERSION as HIDDEN_SERVER_VERSION,
)
from verigym_synopsys.vcs_mcp_profile import (
    SERVICE_PROTOCOL as HIDDEN_SERVICE_PROTOCOL,
)
from verigym_synopsys.vcs_mcp_profile import (
    VcsMcpServerProfile,
)
from verigym_synopsys.vcs_public_compile import _project_diagnostics
from verigym_synopsys.vcs_public_mcp_client import McpVcsPublicCompileTool
from verigym_synopsys.vcs_public_mcp_profile import (
    SERVER_VERSION,
    SERVICE_PROTOCOL,
    VcsPublicMcpServerProfile,
)
from verigym_synopsys.vcs_public_mcp_server import (
    COMPILE_TOOL,
    _sanitized_result,
    tool_definitions,
)

_REAL_SOURCE = os.environ.get("VERIGYM_VERILOG_EVAL_SOURCE")
_REAL_PUBLIC_PROFILE = os.environ.get("VERIGYM_VCS_PUBLIC_MCP_PROFILE")
_REAL_HIDDEN_PROFILE = os.environ.get("VERIGYM_VCS_MCP_PROFILE")
_REAL_RUNTIME = os.environ.get("VERIGYM_VCS_PUBLIC_TEST_RUNTIME", "local")
_REAL_DOCKER_IMAGE = os.environ.get("VERIGYM_VCS_PUBLIC_DOCKER_IMAGE")
_REAL_DOCKER_IMAGE_ID = os.environ.get("VERIGYM_VCS_PUBLIC_DOCKER_IMAGE_ID")


class _ReferencePublicCompileAgent(AgentAdapter):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="test-verilog-eval-public-vcs-reference",
        version="1.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="tests",
        capabilities=["deterministic", "public_vcs_mcp"],
    )

    def __init__(self, source: str) -> None:
        before = "module TopModule;\nendmodule\n"
        broken = "module TopModule( ;\nendmodule\n"
        self._broken_patch = "".join(
            unified_diff(
                before.splitlines(keepends=True),
                broken.splitlines(keepends=True),
                fromfile="a/repository/rtl/TopModule.sv",
                tofile="b/repository/rtl/TopModule.sv",
            )
        )
        self._reference_patch = "".join(
            unified_diff(
                broken.splitlines(keepends=True),
                source.splitlines(keepends=True),
                fromfile="a/repository/rtl/TopModule.sv",
                tofile="b/repository/rtl/TopModule.sv",
            )
        )
        self._actions: list[Any] = []

    def start(self, context: AgentContext) -> None:
        del context
        self._actions = [
            ApplyPatchAction(patch=self._broken_patch),
            ToolCallAction(tool="repository.public_test", arguments={"test_id": "compile"}),
            ApplyPatchAction(patch=self._reference_patch),
            ToolCallAction(tool="repository.public_test", arguments={"test_id": "compile"}),
            ToolCallAction(tool="file.diff", arguments={}),
            FinalSubmissionAction(message="reference candidate complete"),
        ]

    def act(self, observation: Observation) -> Any:
        del observation
        return self._actions.pop(0)

    def finish(self, result: EpisodeResult) -> None:
        del result


def _fake_vcs(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "if '-ID' in sys.argv:\n"
        " print('Compiler version = VCS V-2023.12-SP2-2_Full64')\n"
        " raise SystemExit(0)\n"
        "source = next(pathlib.Path(item) for item in sys.argv if item.startswith('input/'))\n"
        "text = source.read_text()\n"
        "out = pathlib.Path('out')\n"
        "out.mkdir(exist_ok=True)\n"
        "if 'BROKEN' in text or 'TopModule( ;' in text:\n"
        " (out / 'vcs.log').write_text(\n"
        "  'private/site/path\\nError-[SE] Syntax error\\n'\n"
        "  '\"input/000.sv\", 2: token is bad\\n'\n"
        " )\n"
        " raise SystemExit(1)\n"
        "(out / 'vcs.log').write_text('compile passed\\n')\n"
        "(out / 'simv').write_text('compiled\\n')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _fake_hidden_vcs(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "if '-ID' in sys.argv:\n"
        " print('Compiler version = VCS V-2023.12-SP2-2_Full64')\n"
        " raise SystemExit(0)\n"
        "out = pathlib.Path('out')\n"
        "out.mkdir(exist_ok=True)\n"
        "(out / 'vcs.log').write_text('Mismatches: 0 in 1 samples\\n')\n"
        "print('Mismatches: 0 in 1 samples')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _transport(
    path: Path,
    *,
    module: str,
    server_profile: Path,
    work_root: Path,
) -> None:
    repository = Path(__file__).resolve().parents[3]
    python_path = f"{repository / 'src'}:{repository / 'integrations/verigym-synopsys/src'}"
    path.write_text(
        "#!/bin/sh\n"
        f"export PYTHONPATH={shlex.quote(python_path)}\n"
        f"exec {shlex.quote(sys.executable)} -m {module} "
        f"--profile {shlex.quote(str(server_profile))} "
        f"--work-root {shlex.quote(str(work_root))}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _fixture(
    tmp_path: Path,
) -> tuple[VerilogEvalSuite, VeriTask, VcsPublicMcpServerProfile, VerifierToolProfile]:
    repository = Path(__file__).resolve().parents[3]
    source = repository / "tests/fixtures/verilog_eval_v2_synthetic"
    suite = VerilogEvalSuite(
        SuiteSourceConfig(
            source_root=source,
            variant="v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1",
            strict_compatibility=True,
        )
    )
    reference = list(suite.discover())[0]
    task = suite.load_task(reference)
    executable = tmp_path / "vcs"
    _fake_vcs(executable)
    server = VcsPublicMcpServerProfile(
        id="verilog-eval-public-test-v1",
        task_id=task.id,
        executable=str(executable),
        accepted_tool_version="V-2023.12-SP2-2_Full64",
        sources=["repository/rtl/TopModule.sv"],
        top="TopModule",
    )
    server_path = tmp_path / "server.yaml"
    server_path.write_text(
        yaml.safe_dump(server.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    wrapper = tmp_path / "transport"
    _transport(
        wrapper,
        module="verigym_synopsys.vcs_public_mcp_server",
        server_profile=server_path,
        work_root=tmp_path / "service-work",
    )
    client = VerifierToolProfile(
        id="verilog-eval-public-test-client-v1",
        version="1.0.0",
        task_id=task.id,
        source_plugin="repository.public_test",
        target_plugin="synopsys.vcs.public-compile.mcp",
        transport_executable=str(wrapper),
        transport_sha256=hash_bytes(wrapper.read_bytes()),
        service_protocol=SERVICE_PROTOCOL,
        server_version=SERVER_VERSION,
        server_profile_id=server.id,
        server_declared_profile_hash=content_hash(server),
        server_contract_hash=server.contract_hash,
        accepted_tool_version=server.accepted_tool_version,
    )
    return suite, task, server, client


def _hidden_profile(
    tmp_path: Path,
    suite: VerilogEvalSuite,
    task: VeriTask,
) -> VerifierToolProfile:
    hidden = suite.resolve_assets(task).hidden_assets[0]
    assert hidden.content is not None
    testbench = tmp_path / "hidden-testbench.sv"
    testbench.write_text(hidden.content, encoding="utf-8")
    executable = tmp_path / "hidden-vcs"
    _fake_hidden_vcs(executable)
    server = VcsMcpServerProfile(
        id="verilog-eval-hidden-test-v1",
        task_id=task.id,
        executable=str(executable),
        accepted_tool_version="V-2023.12-SP2-2_Full64",
        sources=["repository/rtl/TopModule.sv"],
        testbench=str(testbench),
        testbench_mount_path="verifier/testbench.sv",
        testbench_sha256=hash_bytes(testbench.read_bytes()),
        top="tb",
        pass_marker="Mismatches: 0 in",
        fail_marker="VERIGYM_VCS_EXPLICIT_FAIL",
        timeout_s=180,
    )
    server_path = tmp_path / "hidden-server.yaml"
    server_path.write_text(
        yaml.safe_dump(server.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    wrapper = tmp_path / "hidden-transport"
    _transport(
        wrapper,
        module="verigym_synopsys.vcs_mcp_server",
        server_profile=server_path,
        work_root=tmp_path / "hidden-service-work",
    )
    return VerifierToolProfile(
        id="verilog-eval-hidden-test-client-v1",
        version="1.0.0",
        task_id=task.id,
        source_plugin="synopsys.vcs.simulate",
        target_plugin="synopsys.vcs.mcp",
        transport_executable=str(wrapper),
        transport_sha256=hash_bytes(wrapper.read_bytes()),
        service_protocol=HIDDEN_SERVICE_PROTOCOL,
        server_version=HIDDEN_SERVER_VERSION,
        server_profile_id=server.id,
        server_declared_profile_hash=content_hash(server),
        server_contract_hash=server.contract_hash,
        accepted_tool_version=server.accepted_tool_version,
    )


def test_public_vcs_mcp_surface_has_no_hidden_or_simulation_fields() -> None:
    definitions = tool_definitions()
    assert {item["name"] for item in definitions} == {
        "verigym.synopsys.vcs.public_compile.list_profiles",
        "verigym.synopsys.vcs.public_compile.resolve_profile",
        "verigym.synopsys.vcs.public_compile.compile",
    }
    compile_schema = next(
        item["inputSchema"] for item in definitions if item["name"] == COMPILE_TOOL
    )
    serialized = json.dumps(compile_schema).lower()
    for forbidden in ("testbench", "reference", "pass_marker", "fail_marker", "command", "flags"):
        assert forbidden not in serialized


def test_public_vcs_mcp_resolves_and_returns_only_sanitized_compile_feedback(
    tmp_path: Path,
) -> None:
    suite, task, _server, client = _fixture(tmp_path)
    plugin = McpVcsPublicCompileTool()
    tools: PluginRegistry[ToolPlugin] = PluginRegistry("tools")
    tools.register(plugin)
    resolved = resolve_public_test_profile(task=task, profile=client, tools=tools)
    controller = PublicTestProfileController(
        task=task,
        profile=client,
        resolved_profile=resolved,
        backend=plugin,
    )
    reference = suite.reference_solution(task)
    assert reference is not None
    staging = tmp_path / "candidate"
    source_path = staging / "repository/rtl/TopModule.sv"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(reference.files["repository/rtl/TopModule.sv"], encoding="utf-8")
    runtime = LocalRuntime()
    runtime.prepare("public-vcs-mcp-test")
    session = runtime.create_session(SessionSpec(source_dir=str(staging), label="candidate"))
    try:
        passed = controller.execute("compile", session)
        assert passed.exit_code == 0
        payload = json.loads(passed.stdout)
        assert payload["passed"] is True
        assert payload["backend"] == "synopsys.vcs.public-compile.mcp"
        session.write_file(
            "repository/rtl/TopModule.sv",
            b"module TopModule;\nBROKEN\nendmodule\n",
        )
        failed = controller.execute("compile", session)
    finally:
        session.close()
        runtime.close()
    assert failed.exit_code == 1
    assert failed.failure_origin == "candidate_process"
    payload = json.loads(failed.stdout)
    assert payload["category"] == "compile_failed"
    assert payload["diagnostics"] == ["repository/rtl/TopModule.sv:2: VCS Error-[SE]"]
    serialized = json.dumps(payload)
    assert str(tmp_path) not in serialized
    assert "private/site/path" not in serialized
    assert "token is bad" not in serialized


def test_public_diagnostic_projection_emits_only_controlled_locations() -> None:
    projected = _project_diagnostics(
        'secret/path\nError-[SE] Syntax error\n"input/000.sv", 17: secret source echo',
        ["repository/rtl/TopModule.sv"],
    )
    assert projected == ["repository/rtl/TopModule.sv:17: VCS Error-[SE]"]


def test_public_server_fails_closed_on_an_invalid_diagnostic_projection() -> None:
    payload = _sanitized_result(
        ToolResult(
            tool="synopsys.vcs.public-compile",
            success=False,
            category=ErrorCategory.COMPILE_FAILED,
            diagnostics=["/private/compiler/path:1: error"],
            metadata={"candidate_failure": True},
        )
    )

    assert payload["success"] is False
    assert payload["category"] == "invalid_request"
    assert payload["diagnostics"] == []
    assert payload["metadata"] == {"candidate_failure": False}


def test_prepare_and_qualify_public_bundle_on_synthetic_fixture(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    source = repository / "tests/fixtures/verilog_eval_v2_synthetic"
    executable = tmp_path / "vcs"
    _fake_vcs(executable)
    bundle = tmp_path / "bundle"
    assert (
        prepare_public_bundle(
            [
                "--source-root",
                str(source),
                "--output-root",
                str(bundle),
                "--vcs",
                str(executable),
                "--python-executable",
                sys.executable,
            ]
        )
        == 0
    )
    catalog = json.loads((bundle / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["kind"] == "verilog_eval_vcs_public_mcp_profile_bundle_v1"
    assert catalog["variant"] == "v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1"
    assert catalog["task_count"] == 2
    assert catalog["model_calls"] == 0
    output = tmp_path / "qualification.json"
    assert (
        qualify_public_bundle(
            [
                "--source-root",
                str(source),
                "--bundle-root",
                str(bundle),
                "--work-root",
                str(tmp_path / "qualification-work"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["passed"] is True
    assert receipt["task_count"] == 2
    assert receipt["commercial_jobs"] == 4
    assert receipt["model_calls"] == 0
    assert receipt["automatic_retries"] == 0


def test_full_run_uses_public_vcs_repeated_feedback_and_separate_hidden_profile(
    tmp_path: Path,
) -> None:
    suite, task, _server, public_profile = _fixture(tmp_path)
    hidden_profile = _hidden_profile(tmp_path, suite, task)
    reference = suite.reference_solution(task)
    assert reference is not None
    agent = _ReferencePublicCompileAgent(reference.files["repository/rtl/TopModule.sv"])
    registries = build_registries(discover_external=False)
    registries.tools.register(McpVcsPublicCompileTool())
    registries.tools.register(McpVcsSimulationTool())
    registries.agents.register(agent)
    service = VeriGym(registries)
    source = SuiteSourceConfig(
        source_root=Path(__file__).resolve().parents[3]
        / "tests/fixtures/verilog_eval_v2_synthetic",
        variant="v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1",
        strict_compatibility=True,
    )
    result = service.run(
        RunConfig(
            task_id=task.id,
            suite_source=source,
            agent=agent.descriptor.name,
            verifier_profile_id=hidden_profile.id,
            verifier_profile=hidden_profile,
            public_test_profile_id=public_profile.id,
            public_test_profile=public_profile,
            output=tmp_path / "runs",
        )
    )
    assert result.scorecard.resolved is True
    assert result.manifest.resolved_verifier_profile_hash is not None
    assert result.manifest.resolved_public_test_profile_hash is not None
    assert (
        result.manifest.resolved_verifier_profile_hash
        != result.manifest.resolved_public_test_profile_hash
    )
    assert len(result.manifest.agent_feedback_evaluations) == 2
    rejected, accepted = result.manifest.agent_feedback_evaluations
    assert rejected.test_id == accepted.test_id == "compile"
    assert rejected.passed is False
    assert rejected.category == "compile_failed"
    assert accepted.passed is True
    assert rejected.profile_hash == result.manifest.resolved_public_test_profile_hash
    assert accepted.profile_hash == result.manifest.resolved_public_test_profile_hash
    assert result.manifest.repository_public_tool_invocation_count == 2
    assert (result.run_dir / "artifacts/public_test_profile.json").is_file()
    assert (result.run_dir / "artifacts/resolved_public_test_profile.json").is_file()
    replay = replay_run(result.run_dir, service=service)
    assert replay.scorecard.resolved is True


def test_batch_plan_freezes_and_propagates_both_vcs_mcp_profiles(tmp_path: Path) -> None:
    suite, task, _server, public_profile = _fixture(tmp_path)
    hidden_profile = _hidden_profile(tmp_path, suite, task)
    reference = suite.reference_solution(task)
    assert reference is not None
    agent = _ReferencePublicCompileAgent(reference.files["repository/rtl/TopModule.sv"])
    registries = build_registries(discover_external=False)
    registries.tools.register(McpVcsPublicCompileTool())
    registries.tools.register(McpVcsSimulationTool())
    registries.agents.register(agent)
    service = VeriGym(registries)
    public_path = tmp_path / "public-client.yaml"
    hidden_path = tmp_path / "hidden-client.yaml"
    public_path.write_text(
        yaml.safe_dump(public_profile.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    hidden_path.write_text(
        yaml.safe_dump(hidden_profile.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    config = ExperimentConfig.model_validate(
        {
            "name": "public VCS MCP batch fixture",
            "suite": {
                "id": "verilog-eval",
                "source": Path(__file__).resolve().parents[3]
                / "tests/fixtures/verilog_eval_v2_synthetic",
                "variant": "v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1",
                "strict_compatibility": True,
                "tasks": {"include": ["Prob900_fixture_and"], "exclude": []},
            },
            "runs": {"mode": "agent", "seeds": [0], "samples_per_task": 1},
            "systems": [{"id": "reference", "agent": {"id": agent.descriptor.name}}],
            "runtime": {"id": "local"},
            "verifier_profile": hidden_profile.id,
            "verifier_profile_file": hidden_path,
            "public_test_profile": public_profile.id,
            "public_test_profile_file": public_path,
            "execution": {"max_workers": 1},
            "output": {"root": tmp_path / "experiment"},
        }
    )
    planner = ExperimentPlanner(service)
    plan = planner.build(config)
    assert len(plan.items) == 1
    assert plan.items[0].verifier_profile == hidden_profile
    assert plan.items[0].public_test_profile == public_profile
    assert plan.items[0].resolved_verifier_profile is not None
    assert plan.items[0].resolved_public_test_profile is not None
    planner.verify_frozen_inputs(plan)
    batch = BatchRunner(planner=planner, service_factory=lambda: service).run(plan)
    assert batch.exit_code == 0


@pytest.mark.skipif(
    not (_REAL_SOURCE and _REAL_PUBLIC_PROFILE and _REAL_HIDDEN_PROFILE),
    reason="set the VerilogEval source and both task-bound VCS/MCP profiles",
)
def test_real_public_iteration_and_final_hidden_vcs_mcp(tmp_path: Path) -> None:
    assert _REAL_SOURCE is not None
    assert _REAL_PUBLIC_PROFILE is not None
    assert _REAL_HIDDEN_PROFILE is not None
    source = SuiteSourceConfig(
        source_root=Path(_REAL_SOURCE),
        variant="v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1",
        strict_compatibility=True,
    )
    suite = VerilogEvalSuite(source)
    reference = next(item for item in suite.discover() if item.native_id == "Prob001_zero")
    task = suite.load_task(reference)
    candidate = suite.reference_solution(task)
    assert candidate is not None
    public_profile = load_verifier_profile(Path(_REAL_PUBLIC_PROFILE))
    hidden_profile = load_verifier_profile(Path(_REAL_HIDDEN_PROFILE))
    assert public_profile.task_id == hidden_profile.task_id == task.id
    agent = _ReferencePublicCompileAgent(candidate.files["repository/rtl/TopModule.sv"])
    registries = build_registries(discover_external=False)
    registries.tools.register(McpVcsPublicCompileTool())
    registries.tools.register(McpVcsSimulationTool())
    registries.agents.register(agent)
    service = VeriGym(registries)
    assert _REAL_RUNTIME in {"local", "docker"}
    if _REAL_RUNTIME == "docker":
        assert _REAL_DOCKER_IMAGE is not None
        assert _REAL_DOCKER_IMAGE_ID is not None
        docker_config = DockerRuntimeConfig(
            image=_REAL_DOCKER_IMAGE,
            expected_image_id=_REAL_DOCKER_IMAGE_ID,
            pull_policy="never",
            run_as_user="10001:10001",
            max_command_time_s=300,
        )
    else:
        docker_config = None
    result = service.run(
        RunConfig(
            task_id=task.id,
            suite_source=source,
            agent=agent.descriptor.name,
            verifier_profile_id=hidden_profile.id,
            verifier_profile=hidden_profile,
            public_test_profile_id=public_profile.id,
            public_test_profile=public_profile,
            runtime=_REAL_RUNTIME,
            docker_config=docker_config,
            output=tmp_path / "runs",
        )
    )
    assert result.scorecard.resolved is True
    assert result.manifest.runtime.name == _REAL_RUNTIME
    assert [item.passed for item in result.manifest.agent_feedback_evaluations] == [False, True]
    assert result.manifest.repository_public_tool_invocation_count == 2
    assert result.manifest.resolved_verifier_profile_hash is not None
    assert result.manifest.resolved_public_test_profile_hash is not None
    assert (
        result.manifest.resolved_verifier_profile_hash
        != result.manifest.resolved_public_test_profile_hash
    )
    assert replay_run(result.run_dir, service=service).scorecard.resolved is True
