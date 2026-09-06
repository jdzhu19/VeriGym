#!/usr/bin/env python3
"""Deploy a PPA47-aware disposable DC worker and reissue its MCP client profiles."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

import yaml
from verigym_rtllm.ppa import PPA47_BINDINGS_SHA256, PPA47_TASK_NAMES
from verigym_synopsys.agent_worker_protocol import (
    AgentWorkerDescribeResponse,
    agent_worker_contract_identity_payload,
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

_MAX_TRANSPORT_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-profile-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--identity-suffix", default="v3")
    parser.add_argument("--profile-version", default="3.0.0")
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser().resolve(strict=False)
    if os.path.lexists(expanded) or not expanded.parent.is_dir():
        raise ConfigurationError("reissued PPA47 profile root must be a new directory")
    expanded.mkdir(mode=0o700)
    (expanded / "open").mkdir(mode=0o700)
    (expanded / "dc-client").mkdir(mode=0o700)
    (expanded / "transport").mkdir(mode=0o700)
    return expanded


def _new_file(path: Path) -> Path:
    expanded = path.expanduser().resolve(strict=False)
    if os.path.lexists(expanded) or not expanded.parent.is_dir():
        raise ConfigurationError("worker deployment receipt must be a new file")
    return expanded


def _bounded_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_TRANSPORT_BYTES:
        raise ConfigurationError("PPA47 transport must be a bounded regular file")
    return path.read_text(encoding="utf-8")


def _ssh_command(transport: str) -> list[str]:
    try:
        line = next(
            item for item in transport.splitlines() if item.startswith("exec ") and " '" in item
        )
        command = shlex.split(line.split(" '", 1)[0])[1:]
    except (StopIteration, ValueError) as exc:
        raise ConfigurationError("PPA47 transport has no fixed SSH command") from exc
    if len(command) < 2 or Path(command[0]).name != "ssh":
        raise ConfigurationError("PPA47 transport does not use the approved SSH boundary")
    return command


def _option(transport: str, name: str) -> str:
    matches: list[str] = []
    for line in transport.splitlines():
        if name not in line:
            continue
        try:
            words = shlex.split(line.rstrip(" \\"))
        except ValueError as exc:
            raise ConfigurationError("PPA47 transport contains invalid quoting") from exc
        for index, word in enumerate(words[:-1]):
            if word == name:
                matches.append(words[index + 1])
    if len(matches) != 1:
        raise ConfigurationError(f"PPA47 transport must bind {name} exactly once")
    return matches[0]


def _remote_servers(root: Path) -> tuple[PurePosixPath, ...]:
    paths: set[PurePosixPath] = set()
    for name in PPA47_TASK_NAMES:
        transport = _bounded_text(root / "transport" / name)
        for line in transport.splitlines():
            if "--profile" not in line:
                continue
            words = shlex.split(line.rstrip(" \\"))
            path = PurePosixPath(words[words.index("--profile") + 1])
            if path.name == f"{name}.yaml" and "rtllm-ppa47-" in path.as_posix():
                paths.add(path)
    if len(paths) != len(PPA47_TASK_NAMES):
        raise ConfigurationError("PPA47 transports do not cover 47 remote server profiles")
    return tuple(sorted(paths, key=lambda item: item.as_posix()))


def _worker_source(old: bytes, profiles: tuple[PurePosixPath, ...]) -> bytes:
    text = old.decode("utf-8")
    lines = text.splitlines()
    indices = [index for index, line in enumerate(lines) if "--profile" in line]
    if not indices:
        raise ConfigurationError("base agent worker contains no fixed profiles")
    first = indices[0]
    prefix = lines[first].split("--profile", 1)[0]
    replacement = [f"{prefix}--profile {shlex.quote(str(path))} \\" for path in profiles]
    lines[first : indices[-1] + 1] = replacement
    return ("\n".join(lines) + "\n").encode("utf-8")


def _deploy_worker(
    ssh: list[str], remote_path: PurePosixPath, content: bytes
) -> AgentWorkerDescribeResponse:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        info = tarfile.TarInfo(remote_path.name)
        info.mode = 0o700
        info.size = len(content)
        stream.addfile(info, io.BytesIO(content))
    parent = shlex.quote(str(remote_path.parent))
    name = shlex.quote(remote_path.name)
    command = f"umask 077; test ! -e {parent}/{name} && /usr/bin/tar -C {parent} -xf -"
    deployed = subprocess.run(
        [*ssh, command], input=archive.getvalue(), capture_output=True, timeout=30, check=False
    )
    if deployed.returncode != 0:
        raise ConfigurationError("remote PPA47 worker deployment failed")
    described = subprocess.run(
        [*ssh, str(remote_path)],
        input=b'{"operation":"describe"}\n',
        capture_output=True,
        timeout=30,
        check=False,
    )
    if described.returncode != 0:
        raise ConfigurationError("remote PPA47 worker description failed")
    try:
        return AgentWorkerDescribeResponse.model_validate_json(described.stdout)
    except Exception as exc:
        raise ConfigurationError("remote PPA47 worker returned an invalid description") from exc


def _export_client(
    *,
    server: Path,
    transport: Path,
    base_client: ToolchainProfile,
    output: Path,
    name: str,
    suffix: str,
    version: str,
    worker_hash: str,
    worker: AgentWorkerDescribeResponse,
) -> None:
    profile = base_client
    image = profile.container_image
    metadata = profile.metadata
    prepared_image = metadata.get("prepared_image_id")
    if not isinstance(image, str) or not isinstance(prepared_image, str):
        raise ConfigurationError("base PPA47 client lacks its Docker identity")
    if worker.release is None:
        raise ConfigurationError("PPA47 worker lacks a frozen release identity")
    arguments = [
        "--server-profile",
        str(server),
        "--transport-executable",
        str(transport),
        "--output-profile",
        str(output),
        "--profile-id",
        f"rtllm-ppa47-{name}-dc-mcp-{suffix}",
        "--profile-version",
        version,
        "--runtime",
        "docker",
        "--docker-image",
        image,
        "--prepared-image-id",
        prepared_image,
        "--agent-feedback-worker-contract-hash",
        worker_hash,
        "--agent-feedback-worker-isolation-kind",
        worker.contract.isolation_kind,
        "--agent-feedback-worker-release-hash",
        worker.release.release_hash,
        "--agent-feedback-worker-release-protocol",
        worker.release.protocol,
    ]
    for environment_name in profile.environment_allowlist:
        arguments.extend(("--transport-environment", environment_name))
    with contextlib.redirect_stdout(io.StringIO()):
        if export_mcp_profile(arguments) != 0:
            raise ConfigurationError(f"PPA47 worker client export failed for {name}")
    output.chmod(0o600)


def _reissue_open_profile(
    *, source: Path, output: Path, name: str, suffix: str, version: str
) -> ToolchainProfile:
    loader = ToolchainProfileRegistry()
    payload = loader.load_file(source).model_dump(mode="json", exclude_none=True)
    payload.update(
        {
            "id": f"rtllm-ppa47-{name}-opensta-{suffix}",
            "version": version,
        }
    )
    flow = payload.get("flow")
    scripts = payload.get("scripts")
    if not isinstance(flow, dict) or not isinstance(scripts, list):
        raise ConfigurationError("base OpenSTA profile lacks a flow or scripts")
    generated = [
        script
        for script in scripts
        if isinstance(script, dict) and script.get("source_kind") == "generated"
    ]
    if len(generated) != 1:
        raise ConfigurationError("base OpenSTA profile must bind one generated script")
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
    profile = ToolchainProfile.model_validate(payload)
    output.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    output.chmod(0o600)
    return profile


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    base = arguments.base_profile_root.expanduser().resolve(strict=True)
    if base.is_symlink() or not base.is_dir():
        raise ConfigurationError("base PPA47 profile root must be a real directory")
    output = _new_directory(arguments.output_dir)
    receipt_path = _new_file(arguments.receipt)
    sample_transport = _bounded_text(base / "transport" / PPA47_TASK_NAMES[0])
    ssh = _ssh_command(sample_transport)
    old_worker_path = PurePosixPath(_option(sample_transport, "--agent-worker-executable"))
    old_worker_hash = _option(sample_transport, "--agent-worker-sha256")
    fetched = subprocess.run(
        [*ssh, f"/bin/cat {shlex.quote(str(old_worker_path))}"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if fetched.returncode != 0 or hash_bytes(fetched.stdout) != old_worker_hash:
        raise ConfigurationError("base remote PPA worker identity differs from its transport")
    remote_servers = _remote_servers(base)
    worker_bytes = _worker_source(fetched.stdout, remote_servers)
    worker_sha256 = hash_bytes(worker_bytes)
    remote_worker = old_worker_path.parent / f"rtllm-ppa47-agent-worker-{arguments.identity_suffix}"
    worker = _deploy_worker(ssh, remote_worker, worker_bytes)
    contract = agent_worker_contract_identity_payload(worker.contract)
    worker_contract_hash = content_hash(
        {"launcher_sha256": worker_sha256, "isolation_contract": contract}
    )

    loader = ToolchainProfileRegistry()
    records: list[dict[str, str]] = []
    for name in PPA47_TASK_NAMES:
        open_source = base / "open" / f"{name}.yaml"
        open_output = output / "open" / f"{name}.yaml"
        open_profile = _reissue_open_profile(
            source=open_source,
            output=open_output,
            name=name,
            suffix=arguments.identity_suffix,
            version=arguments.profile_version,
        )
        old_transport_path = base / "transport" / name
        old_transport = _bounded_text(old_transport_path)
        if (
            old_transport.count(str(old_worker_path)) != 1
            or old_transport.count(old_worker_hash) != 1
        ):
            raise ConfigurationError("base transport worker binding is not unique")
        transport_text = old_transport.replace(str(old_worker_path), str(remote_worker), 1)
        transport_text = transport_text.replace(old_worker_hash, worker_sha256, 1)
        transport = output / "transport" / name
        transport.write_text(transport_text, encoding="utf-8")
        transport.chmod(0o700)
        base_client = loader.load_file(base / "dc-client" / f"{name}.yaml")
        client = output / "dc-client" / f"{name}.yaml"
        _export_client(
            server=base / "dc-server" / f"{name}.yaml",
            transport=transport,
            base_client=base_client,
            output=client,
            name=name,
            suffix=arguments.identity_suffix,
            version=arguments.profile_version,
            worker_hash=worker_contract_hash,
            worker=worker,
        )
        client_profile = loader.load_file(client)
        records.append(
            {
                "task": name,
                "open_profile_hash": content_hash(open_profile),
                "dc_client_profile_hash": content_hash(client_profile),
                "transport_sha256": hash_bytes(transport.read_bytes()),
            }
        )
    catalog = {
        "format_id": "rtllm_ppa47_worker_profile_reissue_v1",
        "bindings_sha256": PPA47_BINDINGS_SHA256,
        "worker_launcher_sha256": worker_sha256,
        "worker_contract_hash": worker_contract_hash,
        "worker_release_hash": worker.release.release_hash if worker.release else None,
        "profiles": records,
    }
    (output / "catalog.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    receipt = {
        "format_id": "rtllm_ppa47_remote_worker_deployment_v1",
        "bindings_sha256": PPA47_BINDINGS_SHA256,
        "task_count": len(records),
        "worker_launcher_sha256": worker_sha256,
        "worker_contract_hash": worker_contract_hash,
        "worker_release_protocol": worker.release.protocol if worker.release else None,
        "worker_release_hash": worker.release.release_hash if worker.release else None,
        "remote_paths_disclosed": False,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt_path.chmod(0o600)
    print(f"RTLLM_PPA47_WORKER_PROFILES_READY tasks={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
