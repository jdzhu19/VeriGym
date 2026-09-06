"""Create external task-bound functional profiles without starting Docker or models."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

from verigym_cadence.protocol import Asset, bounded_read

from verigym.plugin_api import VerifierToolProfile, content_hash, hash_bytes
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

from .adapter import RealBenchSuite
from .functional import PROTOCOL, VERSION, FunctionalProfile
from .prepare import atomic_json
from .public_client import RealBenchPublicTool
from .source import load_source

OUTPUTS = {
    "aes_sbox": ["b"],
    "aes_rcon": ["out"],
    "aes_key_expand_128": ["wo_0", "wo_1", "wo_2", "wo_3"],
}


def prepare_public(root: Path, bundle: Path, docker: DockerRuntimeConfig) -> dict[str, Any]:
    if bundle.exists() or bundle.is_symlink():
        raise ValueError("functional bundle already exists; frozen profiles cannot be overwritten")
    lock = load_source(root)
    suite = RealBenchSuite(SuiteSourceConfig(source_root=root))
    refs = {ref.native_id: ref for ref in suite.discover()}
    bundle.mkdir(mode=0o700, parents=True)
    records = []
    for module in lock.tasks:
        task = suite.load_task(refs[module.native_id])
        assets = [
            Asset(role=Path(a.path).name, path=str((root / a.path).absolute()), sha256=a.sha256)
            for a in module.assets
            if "/verification/" in a.path and Path(a.path).suffix in {".v", ".sv"}
        ]
        server = FunctionalProfile(
            id=f"realbench-{module.top}-functional-v1",
            task_id=task.id,
            top=module.top,
            sources=task.metadata["public_test_profile_sources"],
            docker=docker,
            assets=assets,
            outputs=OUTPUTS[module.top],
        )
        summary = server.summary()
        server_path = bundle / f"{module.top}.server.json"
        atomic_json(server_path, server.model_dump(mode="json"))
        transport = bundle / f"{module.top}.transport"
        executable = Path(sys.executable).absolute()
        transport.write_text(
            "#!/bin/sh\nTMPDIR="
            + shlex.quote(tempfile.gettempdir())
            + " exec "
            + shlex.quote(str(executable))
            + " -m verigym_realbench.public_server --profile "
            + shlex.quote(str(server_path.absolute()))
            + "\n",
            encoding="utf-8",
        )
        transport.chmod(0o700)
        client = VerifierToolProfile(
            id=server.id,
            version="1",
            task_id=task.id,
            source_plugin="repository.public_test",
            target_plugin=RealBenchPublicTool.descriptor.name,
            transport_executable=str(transport.absolute()),
            transport_sha256=hash_bytes(bounded_read(transport)),
            service_protocol=PROTOCOL,
            server_version=VERSION,
            server_profile_id=server.id,
            server_declared_profile_hash=summary.declared_profile_hash,
            server_contract_hash=summary.contract_hash,
            accepted_tool_version=server.tool_version,
        )
        client_path = bundle / f"{module.top}.client.json"
        atomic_json(client_path, client.model_dump(mode="json"))
        records.append(
            {
                "native_id": module.native_id,
                "task_id": task.id,
                "task_hash": content_hash(task),
                "server_profile": server_path.name,
                "client_profile": client_path.name,
                "contract_hash": summary.contract_hash,
            }
        )
    result = {
        "kind": "realbench_functional_bundle_v1",
        "source_lock_hash": lock.identity,
        "records": records,
        "image_id": docker.expected_image_id,
    }
    result["bundle_hash"] = content_hash(result)
    atomic_json(bundle / "catalog.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--image-id", required=True)
    args = parser.parse_args()
    result = prepare_public(
        args.source_root,
        args.bundle_root,
        DockerRuntimeConfig(
            image=args.image,
            expected_image_id=args.image_id,
            memory_bytes=4 * 1024**3,
            run_as_user=f"{os.getuid()}:{os.getgid()}",
            cpus=2,
            pids_limit=256,
            max_command_time_s=300,
        ),
    )
    print(json.dumps({"bundle_hash": result["bundle_hash"], "tasks": len(result["records"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
