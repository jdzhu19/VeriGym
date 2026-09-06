#!/usr/bin/env python3
"""Issue external OpenSTA and DC/MCP profiles for the frozen RTLLM PPA47 catalog."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from verigym_rtllm.ppa import (
    PPA47_BINDINGS_SHA256,
    PPA47_TASK_NAMES,
    PPA_TASK_BINDINGS,
)
from verigym_synopsys.export_mcp_profile import main as export_mcp_profile

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.schemas.common import ToolchainProfile
from verigym.tools.yosys.opensta import (
    LATCH_MAPPING_FLOW_TEMPLATE_CONTRACT,
    LATCH_MAPPING_FLOW_TEMPLATE_ID,
)

_MAX_PROFILE_BYTES = 1024 * 1024
_MAX_TRANSPORT_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-base", type=Path, required=True)
    parser.add_argument("--dc-single-server-base", type=Path, required=True)
    parser.add_argument("--dc-single-client-base", type=Path, required=True)
    parser.add_argument("--dc-multi-server-base", type=Path, required=True)
    parser.add_argument("--dc-multi-client-base", type=Path, required=True)
    parser.add_argument("--dc-transport-base", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--identity-suffix", default="v1")
    parser.add_argument("--profile-version", default="1.0.0")
    return parser


def _regular_file(path: Path, label: str, maximum: int = _MAX_PROFILE_BYTES) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file() or expanded.stat().st_size > maximum:
        raise ConfigurationError(f"{label} must be a bounded regular non-symlink file")
    return expanded.resolve(strict=True)


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser().resolve(strict=False)
    if os.path.lexists(expanded) or not expanded.parent.is_dir():
        raise ConfigurationError("PPA47 output must be a new directory under an existing parent")
    expanded.mkdir(mode=0o700)
    (expanded / "sdc").mkdir(mode=0o700)
    (expanded / "open").mkdir(mode=0o700)
    (expanded / "dc-server").mkdir(mode=0o700)
    (expanded / "dc-client").mkdir(mode=0o700)
    (expanded / "transport").mkdir(mode=0o700)
    return expanded


def _write_yaml(path: Path, profile: ToolchainProfile) -> None:
    path.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _profile_payload(base: ToolchainProfile) -> dict[str, Any]:
    return base.model_dump(mode="json", exclude_none=True)


def _transport_profile_token(transport: str, base: Path) -> str:
    matches: list[str] = []
    for line in transport.splitlines():
        if "--profile" not in line:
            continue
        try:
            words = shlex.split(line.rstrip(" \\"))
        except ValueError as exc:
            raise ConfigurationError("DC transport contains invalid shell quoting") from exc
        for index, word in enumerate(words[:-1]):
            if word == "--profile" and Path(words[index + 1]).name == base.name:
                matches.append(words[index + 1])
    if len(matches) != 1 or transport.count(matches[0]) != 1:
        raise ConfigurationError("DC transport does not bind its selected base exactly once")
    return matches[0]


def _replace_constraint(payload: dict[str, Any], sdc: Path, sdc_uri: str) -> None:
    constraints = payload.get("constraints")
    if not isinstance(constraints, list) or len(constraints) != 1:
        raise ConfigurationError("PPA47 template must contain exactly one timing constraint")
    constraint = constraints[0]
    if not isinstance(constraint, dict) or constraint.get("media_type") != "application/x-sdc":
        raise ConfigurationError("PPA47 template constraint is not an SDC artifact")
    constraint.update(
        {
            "uri": sdc_uri,
            "content_hash": hash_bytes(sdc.read_bytes()),
            "attribution": "Frozen RTLLM PPA47 timing constraints",
            "semantics": "Task-bound RTLLM PPA47 synthesis timing constraints",
        }
    )


def _bind_payload(
    base: ToolchainProfile,
    *,
    name: str,
    profile_id: str,
    profile_version: str,
    sdc: Path,
    sdc_uri: str,
) -> dict[str, Any]:
    binding = PPA_TASK_BINDINGS[name]
    payload = _profile_payload(base)
    payload.update(
        {
            "id": profile_id,
            "version": profile_version,
            "description": (
                "Task-bound RTLLM PPA47 synthesis profile; vectorless and non-signoff."
            ),
        }
    )
    flow = payload.get("flow")
    metadata = payload.get("metadata")
    if not isinstance(flow, dict) or not isinstance(metadata, dict):
        raise ConfigurationError("PPA47 template lacks a flow or metadata")
    flow.update(
        {
            "default_sources": [binding.source_path],
            "top_module": binding.top,
        }
    )
    metadata.update(
        {
            "clock_name": binding.power_base_clock,
            "clock_period": binding.clocks[0][1],
            "power_base_clock": binding.power_base_clock,
            "rtllm_ppa47_task": name,
            "rtllm_ppa47_clock_mode": binding.clock_mode,
            "rtllm_ppa47_bindings_sha256": PPA47_BINDINGS_SHA256,
        }
    )
    _replace_constraint(payload, sdc, sdc_uri)
    return payload


def _bind_opensta_compatibility_flow(payload: dict[str, Any]) -> None:
    flow = payload.get("flow")
    scripts = payload.get("scripts")
    if not isinstance(flow, dict) or not isinstance(scripts, list):
        raise ConfigurationError("OpenSTA PPA47 template lacks a flow or scripts")
    generated = [
        script
        for script in scripts
        if isinstance(script, dict) and script.get("source_kind") == "generated"
    ]
    if len(generated) != 1:
        raise ConfigurationError("OpenSTA PPA47 template must bind one generated script")
    flow["template_id"] = LATCH_MAPPING_FLOW_TEMPLATE_ID
    generated[0].update(
        {
            "name": LATCH_MAPPING_FLOW_TEMPLATE_ID,
            "version": "4.0.0",
            "content_hash": hash_bytes(
                (LATCH_MAPPING_FLOW_TEMPLATE_CONTRACT + "\n").encode("utf-8")
            ),
            "semantics": (
                "trusted deterministic OpenSTA flow with parser-compatible structural "
                "netlist export"
            ),
        }
    )


def _export_dc_client(
    *,
    server_path: Path,
    transport_path: Path,
    base: ToolchainProfile,
    output: Path,
    name: str,
    image: str,
    prepared_image: str,
    identity_suffix: str,
    profile_version: str,
) -> ToolchainProfile:
    metadata = base.metadata
    arguments = [
        "--server-profile",
        str(server_path),
        "--transport-executable",
        str(transport_path),
        "--output-profile",
        str(output),
        "--profile-id",
        f"rtllm-ppa47-{name}-dc-mcp-{identity_suffix}",
        "--profile-version",
        profile_version,
        "--runtime",
        "docker",
        "--docker-image",
        image,
        "--prepared-image-id",
        prepared_image,
    ]
    for environment_name in base.environment_allowlist:
        arguments.extend(("--transport-environment", environment_name))
    optional = (
        ("agent_feedback_worker_contract_hash", "--agent-feedback-worker-contract-hash"),
        ("agent_feedback_worker_isolation_kind", "--agent-feedback-worker-isolation-kind"),
        ("agent_feedback_worker_release_hash", "--agent-feedback-worker-release-hash"),
        ("agent_feedback_worker_release_protocol", "--agent-feedback-worker-release-protocol"),
    )
    for key, option in optional:
        value = metadata.get(key)
        if value is not None:
            arguments.extend((option, str(value)))
    with contextlib.redirect_stdout(io.StringIO()):
        if export_mcp_profile(arguments) != 0:
            raise ConfigurationError(f"DC/MCP client export failed for {name}")
    output.chmod(0o600)
    return ToolchainProfileRegistry().load_file(output)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    loader = ToolchainProfileRegistry()
    open_base = loader.load_file(_regular_file(arguments.open_base, "OpenSTA base profile"))
    single_server_path = _regular_file(arguments.dc_single_server_base, "DC single base")
    multi_server_path = _regular_file(arguments.dc_multi_server_base, "DC multi base")
    single_server = loader.load_file(single_server_path)
    multi_server = loader.load_file(multi_server_path)
    single_client = loader.load_file(
        _regular_file(arguments.dc_single_client_base, "DC single client base")
    )
    multi_client = loader.load_file(
        _regular_file(arguments.dc_multi_client_base, "DC multi client base")
    )
    transport_source = _regular_file(
        arguments.dc_transport_base, "DC transport base", _MAX_TRANSPORT_BYTES
    )
    transport_text = transport_source.read_text(encoding="utf-8")
    single_remote_base = PurePosixPath(_transport_profile_token(transport_text, single_server_path))
    multi_remote_base = PurePosixPath(_transport_profile_token(transport_text, multi_server_path))
    if single_remote_base.parent != multi_remote_base.parent:
        raise ConfigurationError("DC transport base profiles do not share a remote directory")
    remote_root = single_remote_base.parent / f"rtllm-ppa47-{arguments.identity_suffix}"
    image = open_base.container_image
    prepared_image = open_base.metadata.get("prepared_image_id")
    if not isinstance(image, str) or not isinstance(prepared_image, str):
        raise ConfigurationError("OpenSTA template lacks its frozen Docker binding")
    output = _new_directory(arguments.output_dir)
    records: list[dict[str, object]] = []
    for name in PPA47_TASK_NAMES:
        binding = PPA_TASK_BINDINGS[name]
        assert binding.sdc is not None
        sdc = output / "sdc" / f"{name}.sdc"
        sdc.write_text(binding.sdc, encoding="utf-8")
        sdc.chmod(0o600)
        remote_sdc = remote_root / "sdc" / f"{name}.sdc"

        open_payload = _bind_payload(
            open_base,
            name=name,
            profile_id=f"rtllm-ppa47-{name}-opensta-{arguments.identity_suffix}",
            profile_version=arguments.profile_version,
            sdc=sdc,
            sdc_uri=str(sdc),
        )
        _bind_opensta_compatibility_flow(open_payload)
        open_profile = ToolchainProfile.model_validate(open_payload)
        open_path = output / "open" / f"{name}.yaml"
        _write_yaml(open_path, open_profile)

        is_multi = binding.clock_mode == "asynchronous_dual_clock"
        dc_base = multi_server if is_multi else single_server
        client_base = multi_client if is_multi else single_client
        old_server_path = multi_server_path if is_multi else single_server_path
        dc_payload = _bind_payload(
            dc_base,
            name=name,
            profile_id=f"rtllm-ppa47-{name}-dc-server-{arguments.identity_suffix}",
            profile_version=arguments.profile_version,
            sdc=sdc,
            sdc_uri=str(remote_sdc),
        )
        dc_server = ToolchainProfile.model_validate(dc_payload)
        server_path = output / "dc-server" / f"{name}.yaml"
        _write_yaml(server_path, dc_server)

        old = _transport_profile_token(transport_text, old_server_path)
        transport_path = output / "transport" / name
        remote_server = remote_root / "dc-server" / f"{name}.yaml"
        transport_path.write_text(
            transport_text.replace(old, str(remote_server), 1), encoding="utf-8"
        )
        transport_path.chmod(0o700)
        client_path = output / "dc-client" / f"{name}.yaml"
        dc_client = _export_dc_client(
            server_path=server_path,
            transport_path=transport_path,
            base=client_base,
            output=client_path,
            name=name,
            image=image,
            prepared_image=prepared_image,
            identity_suffix=arguments.identity_suffix,
            profile_version=arguments.profile_version,
        )
        if (
            open_profile.flow is None
            or dc_client.flow is None
            or open_profile.flow.default_sources != [binding.source_path]
            or dc_client.flow.default_sources != [binding.source_path]
            or open_profile.flow.top_module != binding.top
            or dc_client.flow.top_module != binding.top
        ):
            raise ConfigurationError(f"PPA47 generated profile binding failed for {name}")
        records.append(
            {
                "task": name,
                "clock_mode": binding.clock_mode,
                "open_profile_id": open_profile.id,
                "open_profile_hash": content_hash(open_profile),
                "dc_server_profile_id": dc_server.id,
                "dc_server_profile_hash": content_hash(dc_server),
                "dc_client_profile_id": dc_client.id,
                "dc_client_profile_hash": content_hash(dc_client),
                "sdc_sha256": hash_bytes(sdc.read_bytes()),
                "transport_sha256": hash_bytes(transport_path.read_bytes()),
            }
        )
    catalog = {
        "format_id": "rtllm_ppa47_external_profile_catalog_v1",
        "bindings_sha256": PPA47_BINDINGS_SHA256,
        "profile_partitions_comparable": False,
        "tasks": records,
    }
    catalog_path = output / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    catalog_path.chmod(0o600)
    print(f"RTLLM_PPA47_PROFILES_READY tasks={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
