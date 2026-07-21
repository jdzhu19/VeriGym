"""Offline trace validation and optional verifier-only re-execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from verigym.core.errors import ReplayError
from verigym.core.hashing import content_hash, hash_directory
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.trace import read_trace
from verigym.schemas.common import ToolchainProfile
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.task import VeriTask
from verigym.schemas.trace import EpisodeEvent
from verigym.schemas.verifier import VerifierResult, VerifierStatus


@dataclass(frozen=True)
class ReplaySummary:
    manifest: RunManifest
    scorecard: ScoreCard
    events: list[EpisodeEvent]
    reverified_results: list[VerifierResult] | None = None

    @property
    def reverified_resolved(self) -> bool | None:
        if self.reverified_results is None:
            return None
        return all(result.status == VerifierStatus.PASSED for result in self.reverified_results)


def replay_run(
    run_dir: Path,
    *,
    verify: bool = False,
    service: VeriGym | None = None,
) -> ReplaySummary:
    """Validate stored hashes and events; never invoke an agent or model."""

    run_dir = run_dir.expanduser().resolve()
    required = [
        "run_manifest.json",
        "task_snapshot.json",
        "trace.jsonl",
        "scorecard.json",
        "workspace_diff.patch",
        "candidate",
        "logs",
        "artifacts",
    ]
    missing = [name for name in required if not (run_dir / name).exists()]
    if missing:
        raise ReplayError(f"run directory is incomplete; missing: {', '.join(missing)}")
    manifest = load_model(run_dir / "run_manifest.json", RunManifest)
    task = load_model(run_dir / "task_snapshot.json", VeriTask)
    try:
        task_payload = json.loads((run_dir / "task_snapshot.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError("task snapshot is not valid JSON") from exc
    scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
    if scorecard.run_id != manifest.run_id or scorecard.task_id != manifest.task_id:
        raise ReplayError("scorecard identity does not match the run manifest")
    if content_hash(task_payload) != manifest.task_hash:
        raise ReplayError("task_snapshot.json does not match the manifest task hash")
    candidate_hash = hash_directory(run_dir / "candidate")
    if manifest.candidate_hash is None or candidate_hash != manifest.candidate_hash:
        raise ReplayError("candidate snapshot does not match the manifest candidate hash")
    if scorecard.reproducibility.candidate_hash != candidate_hash:
        raise ReplayError("scorecard candidate hash does not match the frozen candidate")
    if scorecard.reproducibility.task_hash != manifest.task_hash:
        raise ReplayError("scorecard task hash does not match the run manifest")
    if scorecard.reproducibility.run_config_hash != manifest.run_config_hash:
        raise ReplayError("scorecard run-config hash does not match the run manifest")
    if content_hash(task_payload.get("verifier")) != manifest.verifier_hash:
        raise ReplayError("verifier graph does not match the manifest verifier hash")
    if scorecard.reproducibility.verifier_hash != manifest.verifier_hash:
        raise ReplayError("scorecard verifier hash does not match the run manifest")
    profile_path = run_dir / "artifacts" / "toolchain_profile.json"
    if profile_path.is_file() and manifest.toolchain_profiles:
        profile = load_model(profile_path, ToolchainProfile)
        try:
            profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayError("stored toolchain profile is not valid JSON") from exc
        profile_ref = manifest.toolchain_profiles[0]
        if (
            profile.id != profile_ref.id
            or profile.version != profile_ref.version
            or content_hash(profile_payload) != profile_ref.content_hash
        ):
            raise ReplayError("stored toolchain profile does not match its manifest reference")
    events = read_trace(run_dir / "trace.jsonl", expected_run_id=manifest.run_id)
    if not events or events[0].event_type != "episode_started":
        raise ReplayError("trace does not begin with episode_started")
    if events[-1].event_type != "episode_terminated":
        raise ReplayError("trace does not end with episode_terminated")

    reverified: list[VerifierResult] | None = None
    if verify:
        service = service or VeriGym()
        suite_id = manifest.task_id.split("/", 1)[0]
        suite = service.registries.suites.get(suite_id)
        if manifest.suite_source is not None:
            frozen_source = manifest.suite_source
            suite = suite.with_source(
                SuiteSourceConfig(
                    source_root=Path(frozen_source.source_root),
                    variant=frozen_source.variant,
                    strict_compatibility=frozen_source.strict_compatibility,
                )
            )
            current_source = suite.source_snapshot()
            if (
                current_source is None
                or current_source.dataset_content_hash != frozen_source.dataset_content_hash
                or current_source.configuration_fingerprint
                != frozen_source.configuration_fingerprint
            ):
                raise ReplayError("external suite source differs from the frozen manifest")
        assets = suite.resolve_assets(task)
        runtime = service.registries.runtimes.get(manifest.runtime.name)
        reverified = service._verify_candidate(
            task=task,
            assets=assets,
            runtime=runtime,
            candidate_dir=run_dir / "candidate",
            artifact_root=run_dir / "artifacts" / "replay-verification",
        )
    return ReplaySummary(
        manifest=manifest,
        scorecard=scorecard,
        events=events,
        reverified_results=reverified,
    )
