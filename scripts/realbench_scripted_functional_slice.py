"""Opt-in public environment -> typed finish -> offline candidate proof, without final SEC.

The scripted S-box is computed from the public GF(256) specification, never from golden RTL.
This is component qualification, not an orchestrator run or a benchmark score.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
from typing import Any

from verigym_cadence.protocol import bounded_read
from verigym_realbench.adapter import RealBenchSuite
from verigym_realbench.functional import FunctionalProfile
from verigym_realbench.prepare import atomic_json
from verigym_realbench.public_client import RealBenchPublicTool
from verigym_realbench.source import load_source

from verigym.core.artifacts import RunLayout, snapshot_candidate_file_modes
from verigym.core.environment import VeriGymEnv
from verigym.core.episode import TerminationReason
from verigym.core.public_test_profiles import (
    PublicTestProfileController,
    resolve_public_test_profile,
)
from verigym.core.trace import TraceWriter
from verigym.plugin_api import content_hash
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.registry.collections import build_registries
from verigym.runtimes.docker import DockerRuntime
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    FinalSubmissionAction,
    ToolCallAction,
)
from verigym.schemas.suite import SuiteSourceConfig


def multiply(a: int, b: int) -> int:
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        a = ((a << 1) ^ (0x11B if a & 0x80 else 0)) & 255
        b >>= 1
    return result


def public_spec_sbox() -> str:
    def substitute(a: int) -> int:
        inverse = 0 if a == 0 else next(b for b in range(1, 256) if multiply(a, b) == 1)
        result = inverse ^ 0x63
        for shift in range(1, 5):
            result ^= ((inverse << shift) | (inverse >> (8 - shift))) & 255
        return result

    assert substitute(0) == 0x63 and substitute(255) == 0x16
    lines = [
        "module aes_sbox(input wire [7:0] a, output reg [7:0] b);",
        "always @* begin",
        "case (a)",
    ]
    lines.extend(f"8'h{a:02x}: b = 8'h{substitute(a):02x};" for a in range(256))
    lines.extend(["default: b = 8'h00;", "endcase", "end", "endmodule", ""])
    return "\n".join(lines)


def patch(before: str, after: str, path: str) -> ApplyPatchAction:
    return ApplyPatchAction(
        patch="".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    layout = RunLayout.create(args.output)
    status: dict[str, Any] = {
        "kind": "realbench_scripted_public_component_v1",
        "status": "started",
        "model_calls": 0,
        "commercial_jobs": 0,
        "formal_status": "not_executed",
        "suite_qualified": False,
        "benchmark_score_claimed": False,
        "steps": [],
    }
    progress = layout.root / "progress.json"
    atomic_json(progress, status)
    runtime: DockerRuntime | None = None
    env: VeriGymEnv | None = None
    try:
        lock = load_source(args.source_root)
        suite = RealBenchSuite(SuiteSourceConfig(source_root=args.source_root))
        ref = next(r for r in suite.discover() if r.native_id == "aes/aes_sbox")
        task = suite.load_task(ref)
        status.update(
            {"task_id": task.id, "task_hash": content_hash(task), "source_lock_hash": lock.identity}
        )
        client = load_verifier_profile(args.bundle_root / "aes_sbox.client.json")
        server = FunctionalProfile.model_validate_json(
            bounded_read(args.bundle_root / "aes_sbox.server.json")
        )
        registries = build_registries(discover_external=False)
        backend = RealBenchPublicTool()
        registries.tools.register(backend)
        resolved = resolve_public_test_profile(task=task, profile=client, tools=registries.tools)
        status["resolved_public_profile_hash"] = resolved.resolved_profile_hash
        controller = PublicTestProfileController(
            task=task, profile=client, resolved_profile=resolved, backend=backend
        )
        assets = suite.resolve_assets(task)
        modes = snapshot_candidate_file_modes(Path(assets.visible_root))
        runtime = DockerRuntime(server.docker)
        runtime.prepare("realbench-scripted-public-component-v1")
        env = VeriGymEnv(
            task=task,
            assets=assets,
            runtime=runtime,
            tools=registries.tools,
            public_test_executor=controller.execute,
        )
        env.reset(
            run_id="realbench-scripted-public-component-v1",
            trace=TraceWriter(layout.trace, "realbench-scripted-public-component-v1"),
        )
        path = "repository/rtl/aes_sbox.sv"
        stub = bounded_read(Path(assets.visible_root) / path).decode()
        wrong = stub.replace("endmodule", "assign b = 8'h00;\nendmodule")
        actions: list[tuple[str, AgentAction, bool]] = [
            (
                "read_spec",
                ToolCallAction(tool="file.read", arguments={"path": "repository/spec/aes_sbox.md"}),
                True,
            ),
            ("wrong_patch", patch(stub, wrong, path), True),
            (
                "functional_rejection",
                ToolCallAction(tool="repository.public_test", arguments={"test_id": "compile"}),
                False,
            ),
            ("repair", patch(wrong, public_spec_sbox(), path), True),
            (
                "functional_pass",
                ToolCallAction(tool="repository.public_test", arguments={"test_id": "compile"}),
                True,
            ),
            ("inspect_diff", ToolCallAction(tool="file.diff", arguments={}), True),
            (
                "typed_finish",
                FinalSubmissionAction(message="Scripted public-spec implementation submitted."),
                True,
            ),
        ]
        for label, action, expected in actions:
            status["steps"].append({"step": label, "status": "started"})
            atomic_json(progress, status)
            observation, _, terminated, truncated, _ = env.step(action)
            if label == "typed_finish":
                passed = (
                    terminated
                    and not truncated
                    and env.termination_reason == TerminationReason.FINAL_SUBMISSION
                )
            else:
                result = observation.previous_tool_result
                if result is None or result.category.value == "sandbox_error":
                    raise ValueError("scripted component encountered infrastructure failure")
                passed = result.success
            status["steps"][-1].update(
                {"status": "completed", "matches_expected": passed == expected}
            )
            atomic_json(progress, status)
            if passed != expected:
                raise ValueError("unexpected scripted action result")
        assert env.session is not None
        env.session.freeze()
        layout.export_candidate(env.session.root, reference_file_modes=modes)
        record = suite.freeze_repository_candidate(
            task=task,
            candidate_dir=layout.candidate,
            run_root=layout.root,
            artifact_root=layout.artifacts,
        )
        atomic_json(layout.task_snapshot, task.model_dump(mode="json"))
        atomic_json(layout.root / "repository_candidate.json", record.model_dump(mode="json"))
        # Source-free and tool-free candidate proof, deliberately not a fake SEC verdict.
        RealBenchSuite().replay_repository_candidate(
            task=task, candidate_dir=layout.candidate, run_root=layout.root, record=record
        )
        module = next(m for m in lock.tasks if m.native_id == ref.native_id)
        private = [
            bounded_read(args.source_root / a.path) for a in module.assets if a.destination is None
        ]
        for output in layout.root.rglob("*"):
            if output.is_file() and any(
                data in output.read_bytes() for data in private if len(data) > 64
            ):
                raise ValueError("private asset content found in component artifacts")
        status.update(
            {
                "status": "completed",
                "typed_finish": True,
                "offline_candidate_replay": True,
                "hidden_asset_leakage_scan_passed": True,
                "patch_reapply_exact": record.patch.reapply_exact,
            }
        )
    except Exception:
        status["status"] = "stopped"
    finally:
        if env is not None:
            env.close()
        if runtime is not None:
            runtime.close()
            cleanup = runtime.descriptor.cleanup
            status["cleanup_complete"] = cleanup is not None and cleanup.complete
            if not status["cleanup_complete"]:
                status["status"] = "stopped"
        atomic_json(progress, status)
    print(json.dumps(status), flush=True)
    return 0 if status["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
