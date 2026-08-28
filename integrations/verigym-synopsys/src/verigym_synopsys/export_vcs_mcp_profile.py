"""Export a sanitized verifier client profile from a reachable VCS MCP service."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import yaml
from verigym.plugin_api import ConfigurationError, VerifierToolProfile, hash_bytes

from .mcp_client import (
    _mcp_messages,
    _run_stdio,
    _transport_identity,
)
from .vcs_mcp_client import VcsResolveResponse, _tool_response
from .vcs_mcp_profile import RESOLVE_PROFILE_TOOL, SERVER_VERSION, SERVICE_PROTOCOL


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a sanitized VCS MCP verifier profile.")
    parser.add_argument("--id", required=True)
    parser.add_argument("--server-profile-id", required=True)
    parser.add_argument("--server-declared-profile-hash", required=True)
    parser.add_argument("--server-contract-hash", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--transport-executable", type=Path, required=True)
    parser.add_argument("--transport-environment", action="append", default=[])
    parser.add_argument("--output-profile", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    executable, transport_hash = _transport_identity(
        str(arguments.transport_executable),
        hash_bytes(arguments.transport_executable.read_bytes()),
    )
    completed = _run_stdio(
        executable,
        _mcp_messages(
            RESOLVE_PROFILE_TOOL,
            {
                "profile_id": arguments.server_profile_id,
                "declared_profile_hash": arguments.server_declared_profile_hash,
                "contract_hash": arguments.server_contract_hash,
            },
        ),
        environment_names=arguments.transport_environment,
        timeout_s=30,
    )
    response = VcsResolveResponse.model_validate(_tool_response(completed, SERVER_VERSION))
    if (
        response.profile.task_id != arguments.task_id
        or response.profile.declared_profile_hash != arguments.server_declared_profile_hash
        or response.profile.contract_hash != arguments.server_contract_hash
    ):
        raise ConfigurationError("remote VCS profile differs from the export arguments")
    profile = VerifierToolProfile(
        id=arguments.id,
        version="1.0.0",
        description="Fixed verifier-only VCS MCP profile; no commercial assets are embedded.",
        task_id=arguments.task_id,
        source_plugin="synopsys.vcs.simulate",
        target_plugin="synopsys.vcs.mcp",
        runtime="local",
        transport_executable=executable,
        transport_sha256=transport_hash,
        transport_environment=arguments.transport_environment,
        service_protocol=SERVICE_PROTOCOL,
        server_version=SERVER_VERSION,
        server_profile_id=arguments.server_profile_id,
        server_declared_profile_hash=arguments.server_declared_profile_hash,
        server_contract_hash=arguments.server_contract_hash,
        accepted_tool_version=response.resolved_profile.tool_version,
    )
    output = arguments.output_profile.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    output.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
