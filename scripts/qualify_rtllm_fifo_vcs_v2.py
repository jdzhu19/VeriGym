#!/usr/bin/env python3
"""Qualify the RTLLM FIFO behavior contract through one fixed VCS/MCP profile."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_smoke as smoke
from verigym_rtllm.adapter import PPA47_VARIANT

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import hash_bytes
from verigym.core.orchestrator import VeriGym
from verigym.core.verifier_profiles import (
    resolve_verifier_profile,
    task_with_verifier_profile,
)
from verigym.core.workspace import copy_tree_safely
from verigym.experiments.private_staging import PrivateQualificationStaging
from verigym.experiments.state import atomic_dump_json
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--historical-candidate", type=Path, action="append", default=[])
    return parser


def _new_path(path: Path, *, directory: bool) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if os.path.lexists(resolved) or not resolved.parent.is_dir():
        raise ConfigurationError("FIFO VCS output paths must be new under existing parents")
    if directory:
        resolved.mkdir(mode=0o700)
    return resolved


def _candidate_tree(root: Path, visible: Path, files: dict[str, str]) -> Path:
    copy_tree_safely(visible, root)
    for relative, content in sorted(files.items()):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return root


def _passed(results: list[Any]) -> bool:
    return bool(results) and all(item.status == VerifierStatus.PASSED for item in results)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    output = _new_path(arguments.output, directory=False)
    site_parent = _new_path(arguments.site_work, directory=True)
    historical = [path.expanduser().resolve(strict=True) for path in arguments.historical_candidate]
    if len(historical) != 9 or any(
        path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024
        for path in historical
    ):
        raise ConfigurationError("FIFO VCS qualification requires exactly nine bounded candidates")
    registries = smoke._registries()
    service = VeriGym(registries)
    config = SuiteSourceConfig(
        source_root=arguments.rtllm_source.expanduser().resolve(strict=True),
        variant=PPA47_VARIANT,
    )
    task_id = f"rtllm/{PPA47_VARIANT}/asyn_fifo"
    suite, task, assets = service.load_task(task_id, config)
    profile = load_verifier_profile(arguments.profile.expanduser().resolve(strict=True))
    if (
        profile.task_id != task.id
        or profile.source_plugin != "iverilog.simulate"
        or profile.target_plugin != "synopsys.vcs.mcp"
    ):
        raise ConfigurationError("FIFO VCS profile is not bound to the PPA47 task")
    resolved = resolve_verifier_profile(task=task, profile=profile, tools=registries.tools)
    if (
        resolve_verifier_profile(
            task=task, profile=profile, tools=registries.tools, expected=resolved
        )
        != resolved
    ):
        raise ConfigurationError("FIFO VCS profile resolution is not stable")
    effective = task_with_verifier_profile(task, profile)
    cases = [case for case in suite.conformance_cases() if case.name.startswith("asyn_fifo-")]
    if len(cases) != 13 or [case.expected_resolved for case in cases] != [True] + [False] * 12:
        raise ConfigurationError("FIFO feedback-v2 conformance matrix drifted")

    staging = PrivateQualificationStaging(site_parent / "private")
    runtime = registries.runtimes.get("local").configure(None)
    records: list[dict[str, object]] = []
    cleanup: dict[str, object] | None = None
    try:
        runtime.prepare("rtllm-fifo-vcs-v2")
        with staging:
            for case in cases:
                candidate = _candidate_tree(
                    staging.root / "controls" / case.name,
                    Path(assets.visible_root),
                    case.candidate.files,
                )
                results = service._verify_candidate(
                    suite=suite,
                    task=effective,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate,
                    artifact_root=staging.root / "artifacts" / case.name,
                    verifier_profile=profile,
                    resolved_verifier_profile=resolved,
                )
                observed = _passed(results)
                if observed is not case.expected_resolved:
                    raise ConfigurationError(f"FIFO VCS control classification failed: {case.name}")
                records.append(
                    {"case": case.name, "expected": case.expected_resolved, "observed": observed}
                )
            for index, source in enumerate(historical, 1):
                content = source.read_text(encoding="utf-8")
                candidate = _candidate_tree(
                    staging.root / "historical" / f"candidate-{index:02d}",
                    Path(assets.visible_root),
                    {"repository/rtl/asyn_fifo.v": content},
                )
                results = service._verify_candidate(
                    suite=suite,
                    task=effective,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate,
                    artifact_root=staging.root / "artifacts" / f"historical-{index:02d}",
                    verifier_profile=profile,
                    resolved_verifier_profile=resolved,
                )
                if not _passed(results):
                    raise ConfigurationError(
                        "historical FIFO candidate failed the VCS behavior check"
                    )
                records.append(
                    {
                        "case": f"historical-{index:02d}",
                        "candidate_sha256": hash_bytes(content.encode("utf-8")),
                        "expected": True,
                        "observed": True,
                    }
                )
            cleanup = staging.cleanup()
    finally:
        runtime.close()
        if staging.root.exists() and cleanup is None:
            staging.cleanup()
    if len({item.get("candidate_sha256") for item in records if "candidate_sha256" in item}) != 9:
        raise ConfigurationError("historical FIFO candidates are not nine distinct implementations")
    payload = {
        "format_id": "rtllm_fifo_vcs_behavior_qualification_v2",
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "model_calls": 0,
        "automatic_retries": 0,
        "task_id": task.id,
        "profile_id": profile.id,
        "profile_hash": resolved.declared_profile_hash,
        "resolved_profile_hash": resolved.resolved_profile_hash,
        "records": records,
        "summary": {
            "vcs_jobs": len(records),
            "reference_accepted": 1,
            "mutants_rejected": 12,
            "historical_candidates_accepted": 9,
        },
        "private_staging_cleanup": cleanup,
    }
    atomic_dump_json(output, payload)
    print(f"RTLLM_FIFO_VCS_V2_PASS jobs={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
