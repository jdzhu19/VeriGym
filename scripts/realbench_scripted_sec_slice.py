"""Opt-in, no-model S-box orchestrator qualification with one separately approved SEC.

The fixed public-spec candidate must be audited and hash-approved at the site first.
This does not authorize arbitrary RTL in the trusted-fixture native worker.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from realbench_scripted_functional_slice import patch, public_spec_sbox
from verigym_cadence.client import JasperGoldMcpTool
from verigym_cadence.protocol import bounded_read
from verigym_realbench.adapter import RealBenchSuite
from verigym_realbench.functional import FunctionalProfile
from verigym_realbench.prepare import atomic_json
from verigym_realbench.public_client import RealBenchPublicTool
from verigym_realbench.source import load_source

from verigym.agents.base import AgentAdapter, AgentContext
from verigym.core.orchestrator import VeriGym
from verigym.core.public_test_profiles import resolve_public_test_profile
from verigym.core.replay import replay_run
from verigym.core.verifier_profiles import task_with_verifier_profile
from verigym.plugin_api import content_hash, hash_bytes
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.registry.collections import build_registries
from verigym.schemas.agent import (
    AbortAction,
    AgentAction,
    EpisodeResult,
    FinalSubmissionAction,
    Observation,
    ToolCallAction,
)
from verigym.schemas.common import AgentDescriptor
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile


class ScriptedSboxAgent(AgentAdapter):
    descriptor = AgentDescriptor(
        name="realbench-scripted-sbox-sec-v1",
        version="1.0.0",
        provider="verigym-realbench-qualification",
        capabilities=["deterministic", "audited_fixture", "no_model"],
    )

    def __init__(self, stub: str) -> None:
        self.stub = stub
        self.index = 0
        self.actions: list[tuple[AgentAction, bool]] = []

    def start(self, context: AgentContext) -> None:
        if not context.task.id.endswith("/aes/aes_sbox") or context.model_gateway is not None:
            raise ValueError("only the no-model S-box fixture is supported")
        path = "repository/rtl/aes_sbox.sv"
        wrong = self.stub.replace("endmodule", "assign b = 8'h00;\nendmodule")
        self.actions = [
            (
                ToolCallAction(tool="file.read", arguments={"path": "repository/spec/aes_sbox.md"}),
                True,
            ),
            (patch(self.stub, wrong, path), True),
            (
                ToolCallAction(tool="repository.public_test", arguments={"test_id": "compile"}),
                False,
            ),
            (patch(wrong, public_spec_sbox(), path), True),
            (ToolCallAction(tool="repository.public_test", arguments={"test_id": "compile"}), True),
            (ToolCallAction(tool="file.diff", arguments={}), True),
            (FinalSubmissionAction(message="Audited public-spec S-box submitted."), True),
        ]
        self.index = 0

    def act(self, observation: Observation) -> AgentAction:
        if self.index:
            result = observation.previous_tool_result
            expected = self.actions[self.index - 1][1]
            if (
                result is None
                or result.success != expected
                or (not expected and result.category.value != "test_failed")
            ):
                return AbortAction(reason="Unexpected public result; no final SEC submission.")
        if self.index >= len(self.actions):
            return AbortAction(reason="Script exhausted; no repeated submission.")
        action, _ = self.actions[self.index]
        self.index += 1
        return action

    def finish(self, result: EpisodeResult) -> None:
        del result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--public-bundle", type=Path, required=True)
    parser.add_argument("--sec-profile", type=Path, required=True)
    parser.add_argument("--resolved-sec-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-commercial-sec", action="store_true", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be new; never resume a commercial invocation")
    args.output.mkdir(parents=True, mode=0o700)
    status: dict[str, Any] = {
        "kind": "realbench_scripted_orchestrator_sec_v1",
        "status": "started",
        "maximum_commercial_jobs": 1,
        "automatic_retries": 0,
        "model_calls": 0,
        "seed": 0,
        "sample_count": 1,
        "suite_qualified": False,
        "benchmark_score_claimed": False,
    }
    progress = args.output / "progress.json"
    atomic_json(progress, status)
    try:
        source = SuiteSourceConfig(source_root=args.source_root)
        lock = load_source(args.source_root)
        suite = RealBenchSuite(source)
        task = suite.load_task(next(r for r in suite.discover() if r.native_id == "aes/aes_sbox"))
        assets = suite.resolve_assets(task)
        stub = bounded_read(Path(assets.visible_root) / "repository/rtl/aes_sbox.sv").decode()
        agent = ScriptedSboxAgent(stub)
        registries = build_registries(discover_external=False)
        registries.suites.register(RealBenchSuite())
        registries.agents.register(agent)
        registries.tools.register(JasperGoldMcpTool())
        registries.tools.register(RealBenchPublicTool())
        public = load_verifier_profile(args.public_bundle / "aes_sbox.client.json")
        functional = FunctionalProfile.model_validate_json(
            bounded_read(args.public_bundle / "aes_sbox.server.json")
        )
        resolved_public = resolve_public_test_profile(
            task=task, profile=public, tools=registries.tools
        )
        sec = load_verifier_profile(args.sec_profile)
        resolved_sec = ResolvedVerifierToolProfile.model_validate_json(
            bounded_read(args.resolved_sec_profile)
        )
        config = RunConfig(
            task_id=task.id,
            agent=agent.descriptor.name,
            suite_source=source,
            runtime="docker",
            docker_config=functional.docker,
            verifier_profile_id=sec.id,
            verifier_profile=sec,
            expected_resolved_verifier_profile=resolved_sec,
            public_test_profile_id=public.id,
            public_test_profile=public,
            expected_resolved_public_test_profile=resolved_public,
            expected_source_hash=lock.identity,
            expected_task_hash=content_hash(task_with_verifier_profile(task, sec)),
            output=args.output / "run",
            run_id="realbench-scripted-sbox-sec-v1",
            seed=0,
        )
        status.update(
            {
                "source_lock_hash": lock.identity,
                "task_hash": config.expected_task_hash,
                "base_task_hash": content_hash(task),
                "config_hash": content_hash(config),
                "agent_source_sha256": hash_bytes(Path(__file__).read_bytes()),
                "candidate_sha256": hash_bytes(public_spec_sbox().encode()),
                "resolved_sec_profile_hash": resolved_sec.resolved_profile_hash,
                "resolved_public_profile_hash": resolved_public.resolved_profile_hash,
            }
        )
        atomic_json(progress, status)
        result = VeriGym(registries).run(config)
        replay = replay_run(result.run_dir, verify=False)
        formal = result.scorecard.verifier_results
        candidate = bounded_read(result.run_dir / "candidate/repository/rtl/aes_sbox.sv")
        private = [
            bounded_read(args.source_root / a.path)
            for module in lock.tasks
            if module.native_id == "aes/aes_sbox"
            for a in module.assets
            if a.destination is None
        ]
        leak_free = not any(
            data in path.read_bytes()
            for path in result.run_dir.rglob("*")
            if path.is_file()
            for data in private
            if len(data) > 64
        )
        cleanup = result.manifest.runtime.cleanup
        status.update(
            {
                "typed_finish": result.scorecard.termination_reason == "final_submission",
                "formal_status": formal[0].metadata.get("formal_status")
                if len(formal) == 1
                else None,
                "resolved": result.scorecard.correctness.resolved,
                "infrastructure_error": result.scorecard.correctness.infrastructure_error,
                "offline_replay": replay.integrity.status == "verified",
                "candidate_exact": candidate == public_spec_sbox().encode(),
                "hidden_asset_leakage_scan_passed": leak_free,
                "cleanup_complete": cleanup is not None and cleanup.complete,
                "public_test_outcomes": [r.passed for r in result.manifest.repository_public_tests],
            }
        )
        passed = all(
            status[name]
            for name in (
                "typed_finish",
                "resolved",
                "offline_replay",
                "candidate_exact",
                "hidden_asset_leakage_scan_passed",
                "cleanup_complete",
            )
        )
        status["status"] = (
            "completed"
            if passed and status["formal_status"] == "proven" and not status["infrastructure_error"]
            else "stopped"
        )
    except Exception as exc:
        status.update({"status": "stopped", "exception_type": type(exc).__name__})
    atomic_json(progress, status)
    print(json.dumps(status), flush=True)
    return 0 if status["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
