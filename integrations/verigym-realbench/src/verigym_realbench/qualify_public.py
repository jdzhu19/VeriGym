"""Explicit, zero-model reference/negative qualification; never retries an invocation."""

from __future__ import annotations

import argparse
import json
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from verigym_cadence.protocol import bounded_read, unique_json

from verigym.core.public_test_profiles import (
    PublicTestProfileController,
    resolve_public_test_profile,
)
from verigym.plugin_api import hash_bytes
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.registry.collections import build_registries
from verigym.runtimes.docker import DockerRuntime
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.suite import SuiteSourceConfig

from .adapter import RealBenchSuite
from .functional import FunctionalProfile
from .prepare import atomic_json
from .prepare_public import OUTPUTS
from .public_client import RealBenchPublicTool
from .source import load_source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", action="append", choices=list(OUTPUTS))
    parser.add_argument(
        "--case", action="append", choices=["reference", "function_negative", "syntax_negative"]
    )
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("qualification output exists; no implicit retry or overwrite")
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = load_source(args.source_root)
    suite = RealBenchSuite(SuiteSourceConfig(source_root=args.source_root))
    refs = {ref.native_id: ref for ref in suite.discover()}
    tools = build_registries(discover_external=False).tools
    plugin = RealBenchPublicTool()
    tools.register(plugin)
    result: dict[str, Any] = {
        "kind": "realbench_functional_qualification_v1",
        "source_lock_hash": lock.identity,
        "model_calls": 0,
        "commercial_jobs": 0,
        "benchmark_score_claimed": False,
        "status": "running",
        "records": [],
    }
    atomic_json(args.output, result)
    try:
        for module in lock.tasks:
            top = module.top
            if args.task and top not in args.task:
                continue
            task = suite.load_task(refs[module.native_id])
            server = FunctionalProfile.model_validate(
                unique_json(bounded_read(args.bundle_root / f"{top}.server.json").decode())
            )
            client = load_verifier_profile(args.bundle_root / f"{top}.client.json")
            resolved = resolve_public_test_profile(task=task, profile=client, tools=tools)
            controller = PublicTestProfileController(
                task=task, profile=client, resolved_profile=resolved, backend=plugin
            )
            for case in args.case or ["reference", "function_negative", "syntax_negative"]:
                record: dict[str, Any] = {
                    "native_id": module.native_id,
                    "case": case,
                    "resolved_profile_hash": resolved.resolved_profile_hash,
                    "status": "started",
                }
                result["records"].append(record)
                atomic_json(args.output, result)
                if case == "reference":
                    payload = bounded_read(args.source_root / f"aes/{top}/{top}.v")
                else:
                    stub = bounded_read(args.source_root / f"verigym-inputs/{top}.sv").decode()
                    body = "\n".join(f"assign {name} = '0;" for name in OUTPUTS[top])
                    if case == "syntax_negative":
                        body = f"assign {OUTPUTS[top][0]} = ;"
                    payload = stub.replace("endmodule", body + "\nendmodule").encode()
                record["candidate_sha256"] = hash_bytes(payload)
                runtime = DockerRuntime(server.docker)
                try:
                    runtime.prepare(f"realbench-qualification-{top}-{case}")
                    with tempfile.TemporaryDirectory(prefix="rb-qualify-") as empty:
                        path = Path(empty) / server.sources[0]
                        path.parent.mkdir(parents=True)
                        path.write_bytes(payload)
                        with closing(
                            runtime.create_session(SessionSpec(source_dir=empty, label="verifier"))
                        ) as session:
                            completed = controller.execute("compile", session)
                finally:
                    runtime.close()
                cleanup = runtime.descriptor.cleanup
                record["cleanup_complete"] = cleanup is not None and cleanup.complete
                response = unique_json(completed.stdout)
                record.update(
                    {
                        "category": response["category"],
                        "passed": response["passed"],
                        "failure_origin": completed.failure_origin,
                        "status": "completed",
                    }
                )
                expected = {
                    "reference": "success",
                    "function_negative": "test_failed",
                    "syntax_negative": "compile_failed",
                }[case]
                record["matches_expected"] = response["category"] == expected
                atomic_json(args.output, result)
                print(json.dumps(record), flush=True)
                if completed.failure_origin == "control_plane" or not record["cleanup_complete"]:
                    raise ValueError("infrastructure-invalid qualification; stopped without retry")
                if not record["matches_expected"]:
                    raise ValueError("qualification disagrees with expected control")
        result["status"] = "completed"
        atomic_json(args.output, result)
        return 0
    except Exception:
        result["status"] = "stopped"
        atomic_json(args.output, result)
        print("functional qualification stopped; original evidence preserved", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
