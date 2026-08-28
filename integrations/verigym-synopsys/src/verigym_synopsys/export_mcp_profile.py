"""Export a path-sanitized client profile for the remote DC MCP backend."""

from __future__ import annotations

import argparse
import os
import re
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from verigym.plugin_api import ArtifactDescriptor, ToolchainProfile, content_hash, hash_bytes
from verigym.profiles.registry import ToolchainProfileRegistry

from .common import resolve_executable, safe_executable
from .dc import (
    AREA_TIMING_FLOW_TEMPLATE_ID,
    FLOW_TEMPLATE_ID,
    LEGACY_FLOW_TEMPLATE_ID,
    VECTORLESS_POWER_FLOW_TEMPLATE_ID,
)
from .mcp_server import SERVER_VERSION, SERVICE_PROTOCOL

_AGENT_WORKER_PROTOCOL = "verigym.synopsys.dc.agent_worker.v1"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_TRANSPORT_ENVIRONMENT = {"SSH_AUTH_SOCK", "KRB5CCNAME"}
_TEMPLATE_IDS = {
    LEGACY_FLOW_TEMPLATE_ID,
    AREA_TIMING_FLOW_TEMPLATE_ID,
    VECTORLESS_POWER_FLOW_TEMPLATE_ID,
    FLOW_TEMPLATE_ID,
}


def _transport_hash(executable: str, supplied: str | None) -> str:
    safe_executable(executable)
    if supplied is not None:
        if _SHA256.fullmatch(supplied) is None:
            raise ValueError("--transport-sha256 must be a lowercase SHA-256 value")
        return supplied
    resolved = Path(resolve_executable(executable))
    try:
        metadata = os.lstat(resolved)
    except OSError as exc:
        raise ValueError(
            "--transport-sha256 is required when the client wrapper is unavailable locally"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("MCP transport executable must be a regular, non-symlink file")
    if not os.access(resolved, os.X_OK) or metadata.st_size > 16 * 1024 * 1024:
        raise ValueError("MCP transport executable is not executable or exceeds 16 MiB")
    return hash_bytes(resolved.read_bytes())


def _remote_asset(descriptor: ArtifactDescriptor) -> dict[str, Any]:
    if descriptor.content_hash is None:
        raise ValueError(f"server asset {descriptor.name!r} has no SHA-256 identity")
    return {
        "name": descriptor.name,
        "uri": None,
        "content_hash": descriptor.content_hash,
        "version": descriptor.version,
        "license": descriptor.license,
        "media_type": descriptor.media_type,
        "source_kind": "remote_service",
        "attribution": "Server-owned asset; content and path are not exported",
        "redistributable": False,
        "unit": descriptor.unit,
        "semantics": descriptor.semantics,
        "copy_permitted": False,
    }


def _validate_server_profile(profile: ToolchainProfile) -> None:
    if profile.flow is None or profile.metrics is None or profile.reference is None:
        raise ValueError("server profile has no complete synthesis contract")
    if profile.flow.backend_plugin != "synopsys.dc.synth":
        raise ValueError("server profile does not select the local Design Compiler backend")
    if profile.flow.template_id not in _TEMPLATE_IDS:
        raise ValueError("server profile uses an unsupported Design Compiler flow")
    libraries = [
        item for item in profile.libraries if item.media_type == "application/x-synopsys-db"
    ]
    constraints = [
        item
        for item in profile.constraints
        if isinstance(item, ArtifactDescriptor) and item.media_type == "application/x-sdc"
    ]
    if len(libraries) != 1 or len(constraints) != 1:
        raise ValueError("server profile requires one DB and one SDC artifact")
    if any(item.content_hash is None for item in [*libraries, *constraints]):
        raise ValueError("server DB and SDC artifacts require SHA-256 identities")
    tools = [item for item in profile.tools if item.name == "design-compiler"]
    if len(tools) != 1 or tools[0].accepted_version is None:
        raise ValueError("server profile requires one accepted Design Compiler version")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a sanitized client profile for synopsys.dc.mcp."
    )
    parser.add_argument("--server-profile", type=Path, required=True)
    parser.add_argument("--transport-executable", required=True)
    parser.add_argument(
        "--transport-sha256",
        help="Exact client wrapper hash; computed locally when omitted.",
    )
    parser.add_argument("--output-profile", type=Path, required=True)
    parser.add_argument("--profile-id")
    parser.add_argument("--profile-version")
    parser.add_argument(
        "--transport-environment",
        action="append",
        default=[],
        choices=sorted(_TRANSPORT_ENVIRONMENT),
    )
    parser.add_argument(
        "--agent-feedback-worker-contract-hash",
        help="Expected combined launcher/isolation contract hash from the MCP server.",
    )
    parser.add_argument(
        "--agent-feedback-worker-isolation-kind",
        choices=["lsf_job", "container", "vm"],
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    server_profile = ToolchainProfileRegistry().load_file(args.server_profile)
    _validate_server_profile(server_profile)
    assert server_profile.flow is not None
    assert server_profile.metrics is not None
    assert server_profile.reference is not None
    transport_executable = safe_executable(args.transport_executable)
    transport_sha256 = _transport_hash(transport_executable, args.transport_sha256)
    environment = sorted(set(args.transport_environment))
    if (args.agent_feedback_worker_contract_hash is None) != (
        args.agent_feedback_worker_isolation_kind is None
    ):
        raise ValueError("agent feedback worker hash and isolation kind are required together")
    if (
        args.agent_feedback_worker_contract_hash is not None
        and _SHA256.fullmatch(args.agent_feedback_worker_contract_hash) is None
    ):
        raise ValueError("agent feedback worker contract must be a lowercase SHA-256")
    library = next(
        item for item in server_profile.libraries if item.media_type == "application/x-synopsys-db"
    )
    constraint = next(
        item
        for item in server_profile.constraints
        if isinstance(item, ArtifactDescriptor) and item.media_type == "application/x-sdc"
    )
    scripts = [
        item.model_dump(mode="json")
        for item in server_profile.scripts
        if isinstance(item, ArtifactDescriptor) and item.source_kind == "generated"
    ]
    if len(scripts) != 1:
        raise ValueError("server profile requires one generated DC flow descriptor")
    flow = server_profile.flow.model_dump(mode="json")
    flow["backend_plugin"] = "synopsys.dc.mcp"
    metadata_keys = {
        "clock_period",
        "power_activity_mode",
        "power_activity",
        "power_static_probability",
        "power_base_clock",
        "source_liberty_sha256",
    }
    metadata = {
        key: value for key, value in server_profile.metadata.items() if key in metadata_keys
    }
    server_tool = next(item for item in server_profile.tools if item.name == "design-compiler")
    metadata.update(
        {
            "mcp_service_protocol": SERVICE_PROTOCOL,
            "mcp_server_version": SERVER_VERSION,
            "mcp_server_profile_id": server_profile.id,
            "mcp_server_declared_profile_hash": content_hash(server_profile),
            "mcp_transport_sha256": transport_sha256,
            "remote_design_compiler_version": server_tool.accepted_version,
        }
    )
    if args.agent_feedback_worker_contract_hash is not None:
        metadata.update(
            {
                "agent_feedback_worker_contract_hash": (args.agent_feedback_worker_contract_hash),
                "agent_feedback_worker_protocol": _AGENT_WORKER_PROTOCOL,
                "agent_feedback_worker_isolation_kind": (args.agent_feedback_worker_isolation_kind),
            }
        )
    profile = ToolchainProfile.model_validate(
        {
            "id": args.profile_id or f"{server_profile.id}-mcp",
            "version": args.profile_version or server_profile.version,
            "description": (
                "Sanitized verifier-side profile for a server-owned Synopsys DC MCP service"
                + (
                    " with disposable agent-feedback workers."
                    if args.agent_feedback_worker_contract_hash is not None
                    else "."
                )
            ),
            "tools": [
                {
                    "name": "synopsys-dc-mcp",
                    "executable": transport_executable,
                    "accepted_version": f"=={SERVER_VERSION}",
                    "capabilities": [
                        "remote_mcp",
                        "synthesis",
                        "mapped_area",
                        "static_timing",
                        *(("power_estimation",) if server_profile.metrics.power.enabled else ()),
                    ],
                }
            ],
            "runtime": {"runtime": "local", "allowed_runtimes": ["local"]},
            "pdk": (_remote_asset(server_profile.pdk) if server_profile.pdk is not None else None),
            "libraries": [_remote_asset(library)],
            "constraints": [_remote_asset(constraint)],
            "scripts": scripts,
            "environment_allowlist": environment,
            "deterministic": server_profile.deterministic,
            "reproducibility_scope": server_profile.reproducibility_scope,
            "compatibility_status": server_profile.compatibility_status,
            "flow": flow,
            "metrics": server_profile.metrics.model_dump(mode="json"),
            "reference": server_profile.reference.model_dump(mode="json"),
            "metadata": metadata,
        }
    )
    output = args.output_profile.expanduser()
    if output.is_symlink():
        raise ValueError("output profile cannot be a symlink")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"wrote sanitized MCP client profile: {output.resolve()}")
    print(f"client profile SHA-256: {content_hash(profile)}")
    print(f"server profile SHA-256: {content_hash(server_profile)}")
    print(f"transport SHA-256: {transport_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
