"""Reissue a drifted VCS MCP identity without modifying its historical profile."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

import yaml
from verigym.plugin_api import ConfigurationError, content_hash, hash_bytes
from verigym.profiles.verifier_registry import load_verifier_profile

from .export_vcs_mcp_profile import main as export_client_profile
from .vcs import probe_vcs
from .vcs_mcp_client import McpVcsSimulationTool
from .vcs_mcp_profile import load_vcs_server_profile

_MAX_TRANSPORT_BYTES = 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-server", type=Path, required=True)
    parser.add_argument("--base-client", type=Path, required=True)
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--checker", type=Path)
    parser.add_argument("--drop-auxiliary", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser().resolve(strict=False)
    if os.path.lexists(expanded) or not expanded.parent.is_dir():
        raise ConfigurationError("VCS v2 output directory must be new under an existing directory")
    expanded.mkdir(mode=0o700)
    return expanded


def _new_file(path: Path) -> Path:
    expanded = path.expanduser().resolve(strict=False)
    if os.path.lexists(expanded) or not expanded.parent.is_dir():
        raise ConfigurationError("VCS v2 receipt must be a new file under an existing directory")
    return expanded


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    output = _new_directory(arguments.output_dir)
    receipt_path = _new_file(arguments.receipt)
    base_server_path = arguments.base_server.expanduser().resolve(strict=True)
    base_client_path = arguments.base_client.expanduser().resolve(strict=True)
    server = load_vcs_server_profile(base_server_path)
    client = load_verifier_profile(base_client_path)
    health = probe_vcs(server.executable)
    if (
        not health.healthy
        or health.version != server.accepted_tool_version
        or client.server_profile_id != server.id
    ):
        raise ConfigurationError("historical VCS identity is not healthy enough to reissue")

    updates: dict[str, object] = {
        "id": arguments.server_id,
        "version": "2.0.0",
        "task_id": arguments.task_id or server.task_id,
    }
    if arguments.checker is not None:
        checker = arguments.checker.expanduser()
        if checker.is_symlink() or not checker.is_file():
            raise ConfigurationError("replacement VCS checker must be a regular non-symlink file")
        checker = checker.resolve(strict=True)
        updates.update(
            {
                "testbench": str(checker),
                "testbench_sha256": hash_bytes(checker.read_bytes()),
            }
        )
    if arguments.drop_auxiliary:
        updates["auxiliary_files"] = []
    issued_server = type(server).model_validate({**server.model_dump(mode="python"), **updates})
    server_path = output / "server-v2.yaml"
    server_path.write_text(
        yaml.safe_dump(issued_server.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    server_path.chmod(0o600)

    transport_source = Path(client.transport_executable)
    if (
        transport_source.is_symlink()
        or not transport_source.is_file()
        or transport_source.stat().st_size > _MAX_TRANSPORT_BYTES
    ):
        raise ConfigurationError("historical VCS transport is not a bounded regular file")
    transport = transport_source.read_text(encoding="utf-8")
    old = str(base_server_path)
    if transport.count(old) != 1:
        raise ConfigurationError("historical VCS transport does not bind its server exactly once")
    transport_path = output / "transport-v2"
    transport_path.write_text(transport.replace(old, str(server_path), 1), encoding="utf-8")
    transport_path.chmod(0o700)

    client_path = output / "client-v2.yaml"
    export_arguments = [
        "--id",
        arguments.client_id,
        "--version",
        "2.0.0",
        "--server-profile-id",
        issued_server.id,
        "--server-declared-profile-hash",
        content_hash(issued_server),
        "--server-contract-hash",
        issued_server.contract_hash,
        "--task-id",
        issued_server.task_id,
        "--source-plugin",
        client.source_plugin,
        "--transport-executable",
        str(transport_path),
        "--output-profile",
        str(client_path),
    ]
    for name in client.transport_environment:
        export_arguments.extend(("--transport-environment", name))
    export_client_profile(export_arguments)
    issued_client = load_verifier_profile(client_path)
    plugin = McpVcsSimulationTool()
    resolved = plugin.resolve_verifier_profile(issued_client)
    if plugin.resolve_verifier_profile(issued_client, expected=resolved) != resolved:
        raise ConfigurationError("reissued VCS identity was not stable on repeated resolution")

    receipt = {
        "format_id": "verigym_vcs_mcp_profile_reissue_v2",
        "cause": "server_client_canonical_profile_hash_drift",
        "license_failure": False,
        "tool_failure": False,
        "server_profile_id": issued_server.id,
        "server_profile_version": issued_server.version,
        "server_declared_profile_hash": content_hash(issued_server),
        "server_contract_hash": issued_server.contract_hash,
        "client_profile_id": issued_client.id,
        "client_profile_version": issued_client.version,
        "client_declared_profile_hash": content_hash(issued_client),
        "transport_hash": issued_client.transport_sha256,
        "server_resolved_profile_hash": resolved.server_resolved_profile_hash,
        "client_resolved_profile_hash": resolved.resolved_profile_hash,
        "tool_version": resolved.tool_version,
        "repeated_resolution_stable": True,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt_path.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
