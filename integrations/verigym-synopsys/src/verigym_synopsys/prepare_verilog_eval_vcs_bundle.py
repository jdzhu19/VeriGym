"""Prepare private per-task VCS/MCP profiles for the VerilogEval commercial variant."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.verifier_profiles import resolve_verifier_profile
from verigym.plugin_api import ConfigurationError, VerifierToolProfile
from verigym.registry.base import PluginRegistry
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile
from verigym.suites.verilog_eval.adapter import VerilogEvalSuite
from verigym.suites.verilog_eval.commercial import (
    VCS_MCP_EXCLUSIONS,
    combined_reference_testbench,
)
from verigym.suites.verilog_eval.layout import inspect_layout, validation_report
from verigym.suites.verilog_eval.schemas import VerilogEvalVariant
from verigym.suites.verilog_eval.source import resolve_layout
from verigym.tools.base import ToolPlugin

from .vcs import probe_vcs
from .vcs_mcp_client import McpVcsSimulationTool
from .vcs_mcp_profile import SERVER_VERSION, SERVICE_PROTOCOL, VcsMcpServerProfile

VARIANT = VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_V1.value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a private, hash-bound VCS/MCP profile bundle for VerilogEval."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--vcs", required=True)
    parser.add_argument("--environment", action="append", default=[])
    parser.add_argument(
        "--login-home",
        type=Path,
        help="Use a fixed login shell with this HOME to restore site VCS/license setup.",
    )
    parser.add_argument(
        "--login-user",
        help="USER supplied to the optional fixed login shell.",
    )
    parser.add_argument(
        "--python-executable",
        type=Path,
        default=Path(sys.executable),
    )
    parser.add_argument(
        "--defer-live-resolve",
        action="store_true",
        help="Derive identities now; require the qualification command to resolve every profile.",
    )
    return parser


def _write_private(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700 if executable else 0o600)


def _transport_script(
    *,
    python_executable: Path,
    server_profile: Path,
    work_root: Path,
    login_home: Path | None,
    login_user: str | None,
) -> str:
    command = [
        str(python_executable),
        "-m",
        "verigym_synopsys.vcs_mcp_server",
        "--profile",
        str(server_profile),
        "--work-root",
        str(work_root),
    ]
    inner = "exec " + " ".join(shlex.quote(item) for item in command)
    if login_home is None:
        return f"#!/bin/sh\nset -eu\n{inner}\n"
    assert login_user is not None
    outer = [
        "/usr/bin/env",
        f"HOME={login_home}",
        f"USER={login_user}",
        "/bin/bash",
        "-lc",
        inner,
    ]
    return "#!/bin/sh\nset -eu\nexec " + " ".join(shlex.quote(item) for item in outer) + "\n"


def _validated_output_root(requested: Path) -> Path:
    expanded = requested.expanduser()
    if expanded.exists() or expanded.is_symlink():
        raise ConfigurationError("VCS/MCP bundle output root already exists")
    parent = expanded.parent.resolve(strict=True)
    output = parent / expanded.name
    output.mkdir(mode=0o700)
    return output


def _derived_resolved_profile(
    server: VcsMcpServerProfile,
    client: VerifierToolProfile,
) -> ResolvedVerifierToolProfile:
    server_payload = {
        "service_protocol": SERVICE_PROTOCOL,
        "server_version": SERVER_VERSION,
        "profile_id": server.id,
        "profile_version": server.version,
        "declared_profile_hash": content_hash(server),
        "contract_hash": server.contract_hash,
        "tool_version": server.accepted_tool_version,
    }
    server_resolved_hash = content_hash(server_payload)
    payload: dict[str, Any] = {
        "profile_id": client.id,
        "profile_version": client.version,
        "declared_profile_hash": content_hash(client),
        "task_id": client.task_id,
        "source_plugin": client.source_plugin,
        "target_plugin": client.target_plugin,
        "runtime": client.runtime,
        "transport_sha256": client.transport_sha256,
        "service_protocol": client.service_protocol,
        "server_version": client.server_version,
        "server_profile_id": client.server_profile_id,
        "server_declared_profile_hash": client.server_declared_profile_hash,
        "server_resolved_profile_hash": server_resolved_hash,
        "server_contract_hash": client.server_contract_hash,
        "tool_version": client.accepted_tool_version,
    }
    return ResolvedVerifierToolProfile(
        **payload,
        resolved_profile_hash=content_hash(payload),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if (arguments.login_home is None) != (arguments.login_user is None):
        raise ConfigurationError("--login-home and --login-user must be supplied together")
    python_executable = arguments.python_executable.expanduser().resolve(strict=True)
    if not python_executable.is_file():
        raise ConfigurationError("Python executable must be a regular file")
    health = probe_vcs(arguments.vcs)
    if not health.healthy or health.version is None or health.executable is None:
        raise ConfigurationError("VCS identity probe failed while preparing VerilogEval profiles")
    vcs_executable = Path(health.executable).resolve(strict=True)

    source_config = SuiteSourceConfig(
        source_root=arguments.source_root,
        variant=VARIANT,
        strict_compatibility=True,
    )
    catalog = inspect_layout(resolve_layout(source_config))
    report = validation_report(catalog)
    if not report.valid:
        raise ConfigurationError(f"invalid VerilogEval source: {'; '.join(report.errors[:3])}")
    suite = VerilogEvalSuite(source_config)
    references = {reference.native_id: reference for reference in suite.discover()}

    output = _validated_output_root(arguments.output_root)
    _write_private(output / "INCOMPLETE", "profile bundle preparation is in progress\n")
    records: list[dict[str, object]] = []
    tools: PluginRegistry[ToolPlugin] = PluginRegistry("tool")
    tools.register(McpVcsSimulationTool())
    for problem in catalog.problems:
        if problem.native_id in VCS_MCP_EXCLUSIONS:
            continue
        reference = references.get(problem.native_id)
        if reference is None:
            raise ConfigurationError("VerilogEval discovery differs from the validated catalog")
        task = suite.load_task(reference)
        if len(task.verifier.nodes) != 1:
            raise ConfigurationError("VerilogEval VCS task must contain one verifier node")
        node = task.verifier.nodes[0]
        if node.plugin != "synopsys.vcs.simulate":
            raise ConfigurationError("VerilogEval VCS task selected an unexpected source backend")
        testbench = combined_reference_testbench(problem.reference, problem.testbench)
        testbench_path = (output / "hidden" / f"{problem.native_id}.sv").resolve()
        _write_private(testbench_path, testbench)
        if task.workspace.hidden_assets[0].content_hash != hash_bytes(testbench.encode("utf-8")):
            raise ConfigurationError("combined VerilogEval hidden-testbench identity changed")

        server_id = f"verilog-eval-{problem.native_id}-vcs-v1"
        server_path = (output / "server" / f"{problem.native_id}.yaml").resolve()
        work_root = (output / "work" / problem.native_id).resolve()
        request = node.request
        sources = request.get("sources")
        top = request.get("top")
        if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
            raise ConfigurationError("VerilogEval VCS source contract is invalid")
        if not isinstance(top, str):
            raise ConfigurationError("VerilogEval VCS top contract is invalid")
        server = VcsMcpServerProfile(
            id=server_id,
            task_id=task.id,
            executable=str(vcs_executable),
            accepted_tool_version=health.version,
            sources=sources,
            testbench=str(testbench_path),
            testbench_mount_path=str(request["testbench"]),
            testbench_sha256=hash_bytes(testbench.encode("utf-8")),
            top=top,
            pass_marker=str(request["pass_marker"]),
            fail_marker=str(request["fail_marker"]),
            timeout_s=int(request["timeout_s"]),
            environment_allowlist=arguments.environment,
        )
        _write_private(
            server_path,
            yaml.safe_dump(server.model_dump(mode="json"), sort_keys=False),
        )

        transport_path = (output / "transport" / problem.native_id).resolve()
        _write_private(
            transport_path,
            _transport_script(
                python_executable=python_executable,
                server_profile=server_path,
                work_root=work_root,
                login_home=(
                    arguments.login_home.expanduser().resolve(strict=True)
                    if arguments.login_home is not None
                    else None
                ),
                login_user=arguments.login_user,
            ),
            executable=True,
        )
        client = VerifierToolProfile(
            id=f"verilog-eval-{problem.native_id}-vcs-mcp-v1",
            version="1.0.0",
            description=(
                "Fixed VerilogEval verifier-only VCS/MCP profile; no commercial or hidden "
                "assets are embedded."
            ),
            task_id=task.id,
            source_plugin=node.plugin,
            target_plugin="synopsys.vcs.mcp",
            runtime="local",
            transport_executable=str(transport_path),
            transport_sha256=hash_bytes(transport_path.read_bytes()),
            service_protocol=SERVICE_PROTOCOL,
            server_version=SERVER_VERSION,
            server_profile_id=server.id,
            server_declared_profile_hash=content_hash(server),
            server_contract_hash=server.contract_hash,
            accepted_tool_version=health.version,
        )
        resolved = (
            _derived_resolved_profile(server, client)
            if arguments.defer_live_resolve
            else resolve_verifier_profile(task=task, profile=client, tools=tools)
        )
        client_path = output / "client" / f"{problem.native_id}.yaml"
        _write_private(
            client_path,
            yaml.safe_dump(client.model_dump(mode="json"), sort_keys=False),
        )
        records.append(
            {
                "native_id": problem.native_id,
                "task_id": task.id,
                "task_hash": content_hash(task),
                "hidden_testbench_sha256": server.testbench_sha256,
                "server_profile": server_path.relative_to(output).as_posix(),
                "server_declared_profile_hash": content_hash(server),
                "server_contract_hash": server.contract_hash,
                "transport": transport_path.relative_to(output).as_posix(),
                "transport_sha256": client.transport_sha256,
                "client_profile": client_path.relative_to(output).as_posix(),
                "client_declared_profile_hash": content_hash(client),
                "client_resolved_profile_hash": resolved.resolved_profile_hash,
                "server_resolved_profile_hash": resolved.server_resolved_profile_hash,
            }
        )

    identity = {
        "variant": VARIANT,
        "dataset_content_hash": catalog.dataset_content_hash,
        "task_count": len(records),
        "accepted_vcs_version": health.version,
        "excluded_tasks": [
            {"native_id": native_id, "reason_code": reason_code}
            for native_id, reason_code in sorted(VCS_MCP_EXCLUSIONS.items())
            if any(problem.native_id == native_id for problem in catalog.problems)
        ],
        "profile_resolution_mode": (
            "derived_pending_qualification" if arguments.defer_live_resolve else "live"
        ),
        "records": records,
    }
    catalog_payload = {
        "schema_version": "1.0",
        "kind": "verilog_eval_vcs_mcp_profile_bundle_v1",
        **identity,
        "bundle_identity_hash": content_hash(identity),
        "model_calls": 0,
    }
    _write_private(
        output / "catalog.json",
        json.dumps(catalog_payload, indent=2, sort_keys=True) + "\n",
    )
    (output / "INCOMPLETE").unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
