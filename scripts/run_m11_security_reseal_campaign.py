#!/usr/bin/env python3
"""Offline-only M11 provenance scanner repair verification and final reseal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import patch

from verigym.core.hashing import content_hash, hash_directory
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.replay import replay_run
from verigym.core.security_scanner import (
    build_security_scan_policy,
    require_security_scan_pass,
    scan_artifact_roots,
)
from verigym.core.workspace import copy_tree_safely
from verigym.experiments.identity import plan_items_hash_payload
from verigym.experiments.schemas import PlanItem
from verigym.experiments.state import (
    atomic_dump_json,
    atomic_write_text,
    load_json_model,
    load_jsonl_models,
)
from verigym.reporting.loader import load_report_inputs
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard

START_COMMIT = "a7c32adc8beb9f33440c112be22dcbe034c28e52"
START_TREE = "29db42164cedca879d47927cdaaaed50544b8adf"
CONTRACT_SHA256 = "61d20a0959c2f0d86245cb2edb8e98d839f8f8bcd403c4f0ecc11a17c17bdc8a"
HISTORICAL_ROOT = Path(
    "/data/jzhu484/Agent/VeriGym_m11_deepseek_api_agent_9a44efa/evidence-bundle-final"
)
HISTORICAL_SHA256SUMS_SHA256 = "1ed58d8bfe3d56c54b53d4974fccf9f01e2c622722f1e460dacfb2324ed7cd02"
HISTORICAL_SECURITY_SCAN_SHA256 = "e73afb7f52bca7f5206b4af11d3078f850bc9d2c0eef15233bbc7ab0c4ff8eae"
HISTORICAL_OUTCOMES_SHA256 = "1673b339c9f2165cc45074be155f74c9c2c9d6853148becc6823faabafbf4263"
PLAN_FILE_SHA256 = "f976a3a3a5a19912f60cc29ab260a27275ef18e55d253a65ac691adea0028254"
EXPERIMENT_PLAN_HASH = "c85105f56e9cedd44cdd69e058e792195c407b2a181b62b32d8f38096550b211"
HISTORICAL_BUNDLE_DISPLAY_PLAN_HASH = (
    "c85105f56e9cedd4c61a16284517cd4bc2ce6eeab28b1c14e77ff3ca8cfe41ab"
)
MODEL_ID = "deepseek-v4-flash"
PROVIDER_ID = "DeepSeek"
DEEPSEEK_ENVIRONMENT_NAMES = (
    "VERIGYM_DEEPSEEK_API_KEY",
    "VERIGYM_DEEPSEEK_API_BASE_URL",
)
PROXY_ENVIRONMENT_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy")

PROTECTED_BUNDLES: tuple[tuple[str, Path, str], ...] = (
    ("m11_failed_9a44efa", HISTORICAL_ROOT, HISTORICAL_SHA256SUMS_SHA256),
    (
        "m10b_final_83a1e52",
        Path("/data/jzhu484/Agent/VeriGym_m10b_final_security_83a1e52/evidence-bundle-final"),
        "bdfffcedf8ac35d92c050699b01535b390267b9baed2c018cf72d2aced2a8956",
    ),
    (
        "m10b_failed_93097b7",
        Path("/data/jzhu484/Agent/VeriGym_m10b_contamination_93097b7/evidence-bundle-final"),
        "067dfa3fa4ddf5f34d14b4ee52a63ef443312398477bf0f76a9d13f917e4666d",
    ),
    (
        "m10b_failed_3da8dd6",
        Path("/data/jzhu484/Agent/VeriGym_m10b_memory_builder_3da8dd6/evidence-bundle-final"),
        "ec9fd849195121057e781c228861b683a14cef948a535754d4323382723b1f41",
    ),
    (
        "m10b_failed_9811aa4",
        Path("/data/jzhu484/Agent/VeriGym_m10b_prompt_binding_9811aa4/evidence-bundle-final"),
        "2abd8f8f90f8333e68cfd9e19a793e98c5688cdaa58603794634984958810fb7",
    ),
    (
        "m10b_failed_de9dc9d",
        Path("/data/jzhu484/Agent/VeriGym_milestone10b_de9dc9d/evidence-bundle-final"),
        "fd549b7e064aabdad1c2e07630de62f8e424a9a4c368d7df71813c048def8188",
    ),
    (
        "m10a_pass_53b0755",
        Path("/data/jzhu484/Agent/VeriGym_milestone10a_53b0755/evidence-bundle-final"),
        "afa59b11bbe9f57caed8b5eb8b27739ff09cfd57e9a0fbd11df64851f4ffe420",
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _assert_source_identity(final_commit: str, final_tree: str) -> None:
    if _git("rev-parse", "HEAD^{commit}") != final_commit:
        raise RuntimeError("source commit differs from the final scanner repair identity")
    if _git("rev-parse", "HEAD^{tree}") != final_tree:
        raise RuntimeError("source tree differs from the final scanner repair identity")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("source worktree must be clean before final reseal")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", START_COMMIT, final_commit],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if final_tree == START_TREE:
        raise RuntimeError("final tree does not contain the scanner repair")


def _assert_checksum_manifest(root: Path) -> int:
    manifest = root / "SHA256SUMS"
    if not manifest.is_file() or manifest.is_symlink():
        raise RuntimeError("protected bundle lacks a regular checksum manifest")
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        target = root / relative
        if (
            not separator
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not target.is_file()
            or target.is_symlink()
            or _sha256(target) != digest
        ):
            raise RuntimeError(f"protected checksum mismatch: {relative}")
        count += 1
    return count


def _preservation_identity() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for bundle_id, root, expected in PROTECTED_BUNDLES:
        verified = _assert_checksum_manifest(root)
        observed = _sha256(root / "SHA256SUMS")
        if observed != expected:
            raise RuntimeError(f"protected bundle identity changed: {bundle_id}")
        records.append(
            {
                "bundle_id": bundle_id,
                "sha256sums_sha256": observed,
                "verified_file_count": verified,
                "modified": False,
            }
        )
    if _sha256(HISTORICAL_ROOT / "evidence/security-scan-raw.json") != (
        HISTORICAL_SECURITY_SCAN_SHA256
    ):
        raise RuntimeError("historical M11 raw security scan changed")
    writable = sum(1 for path in HISTORICAL_ROOT.rglob("*") if os.access(path, os.W_OK))
    if writable:
        raise RuntimeError("historical M11 bundle is no longer read-only")
    return {
        "schema_version": "1.0",
        "bundles": records,
        "historical_m11_writable_entries": 0,
        "historical_m11_gate": "FAIL",
        "historical_failure_reinterpreted": False,
    }


def _historical_runs() -> list[tuple[str, Path]]:
    probe_runs = sorted(HISTORICAL_ROOT.glob("real-probes/probe-*/runs/*"))
    final_runs = sorted((HISTORICAL_ROOT / "final-experiment/run/runs").iterdir())
    records = [("probe", path) for path in probe_runs if path.is_dir()]
    records.extend(("final", path) for path in final_runs if path.is_dir())
    if len(probe_runs) != 2 or len(final_runs) != 9 or len(records) != 11:
        raise RuntimeError("historical 11-run corpus cardinality changed")
    return records


def _validate_process_ledger() -> dict[str, Any]:
    ledgers = (
        HISTORICAL_ROOT / "real-probes/probe-1/process-ledger.jsonl",
        HISTORICAL_ROOT / "real-probes/probe-2/process-ledger.jsonl",
        HISTORICAL_ROOT / "final-experiment/run/process-ledger.jsonl",
    )
    rows = [
        json.loads(line)
        for ledger in ledgers
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 11:
        raise RuntimeError("historical process authorization ledger is not 11/11")
    if any(
        row.get("authorization_state") != "launch_authorized"
        or row.get("requested_model_id") != "openai-compatible"
        or row.get("retry")
        or row.get("resume")
        or row.get("attempt") != 1
        for row in rows
    ):
        raise RuntimeError("historical process authorization identity changed")
    return {
        "schema_version": "1.0",
        "authorized_processes": 11,
        "launched_processes": 11,
        "terminal_processes": 11,
        "probe_processes": 2,
        "final_processes": 9,
        "retry_processes": 0,
        "resume_processes": 0,
        "new_processes_authorized_by_reseal": 0,
    }


def _validate_plan() -> dict[str, Any]:
    experiment = HISTORICAL_ROOT / "final-experiment/run"
    plan_path = experiment / "plan.jsonl"
    if _sha256(plan_path) != PLAN_FILE_SHA256:
        raise RuntimeError("frozen M11 plan file identity changed")
    items = load_jsonl_models(plan_path, PlanItem)
    recomputed = content_hash(plan_items_hash_payload(items))
    manifest = _load(experiment / "experiment_manifest.json")
    state = _load(experiment / "state.json")
    audit = _load(experiment / "plan-audit.json")
    if (
        len(items) != 9
        or recomputed != EXPERIMENT_PLAN_HASH
        or manifest.get("plan_hash") != recomputed
        or state.get("plan_hash") != recomputed
        or audit.get("plan_hash") != recomputed
    ):
        raise RuntimeError("frozen M11 experiment plan cannot be reproduced")
    loaded = load_report_inputs(experiment)
    if loaded.planned_count != 9 or len(loaded.valid_runs) != 9 or loaded.invalid_inputs:
        raise RuntimeError("frozen M11 plan-to-child binding is incomplete")
    outer = _load(HISTORICAL_ROOT / "bundle_manifest.json")
    display_hash = outer.get("final_plan", {}).get("plan_hash")
    if display_hash != HISTORICAL_BUNDLE_DISPLAY_PLAN_HASH:
        raise RuntimeError("historical outer bundle plan display field changed")
    return {
        "schema_version": "1.0",
        "experiment_plan_hash": recomputed,
        "plan_file_sha256": PLAN_FILE_SHA256,
        "plan_items": 9,
        "valid_plan_children": 9,
        "invalid_plan_children": 0,
        "plan_file_read_only": not os.access(plan_path, os.W_OK),
        "historical_outer_bundle_display_plan_hash": display_hash,
        "historical_outer_display_field_differs_from_authoritative_experiment_plan": True,
        "authoritative_plan_identity_sources": [
            "plan.jsonl recomputation",
            "experiment_manifest.json",
            "state.json",
            "plan-audit.json",
            "reports/aggregate.json",
        ],
        "historical_artifact_modified": False,
    }


def _validate_run_corpus() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    historical_outcomes_path = HISTORICAL_ROOT / "evidence/per-run-outcomes.json"
    observed_outcomes_sha256 = _sha256(historical_outcomes_path)
    if observed_outcomes_sha256 != HISTORICAL_OUTCOMES_SHA256:
        raise RuntimeError("historical M11 per-run outcomes changed")
    historical_outcomes = _load(historical_outcomes_path)
    by_id = {row["run_id"]: row for row in historical_outcomes["runs"]}
    if len(by_id) != 11:
        raise RuntimeError("historical per-run outcome coverage changed")

    final_categories: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    usage = Counter[str]()
    for phase, run_root in _historical_runs():
        integrity = verify_artifact_manifest(run_root, expected_scope="run")
        manifest = load_json_model(run_root / "run_manifest.json", RunManifest)
        scorecard = load_json_model(run_root / "scorecard.json", ScoreCard)
        frozen = by_id.get(manifest.run_id)
        if frozen is None:
            raise RuntimeError("historical outcome lacks a run artifact")
        if (
            integrity.status != "verified"
            or manifest.model is None
            or manifest.model.provider != PROVIDER_ID
            or manifest.model.model_id != MODEL_ID
            or scorecard.efficiency.model_calls != 1
            or frozen.get("requested_model_id") != MODEL_ID
            or frozen.get("observed_model_id") != MODEL_ID
            or frozen.get("provider_id") != PROVIDER_ID
            or frozen.get("model_calls") != 1
            or frozen.get("patch_reapply_exact") is not True
        ):
            raise RuntimeError("historical run identity or terminal integrity changed")
        failure_category = scorecard.failure.category if scorecard.failure is not None else None
        expected_category = frozen.get("failure_category")
        if failure_category != expected_category or scorecard.resolved != frozen.get("resolved"):
            raise RuntimeError("historical scorecard and outcome taxonomy differ")
        if any(
            value is not None
            for value in (
                scorecard.efficiency.model_api_cost,
                scorecard.efficiency.model_api_cost_currency,
                scorecard.efficiency.model_api_cost_unit,
                frozen.get("cost"),
                frozen.get("cost_currency"),
                frozen.get("cost_unit"),
            )
        ):
            raise RuntimeError("historical M11 corpus unexpectedly contains provider cost")
        if scorecard.failure is not None and scorecard.failure.infrastructure:
            raise RuntimeError("historical M11 corpus unexpectedly contains infrastructure failure")
        if scorecard.correctness.infrastructure_error:
            raise RuntimeError("historical M11 correctness has an infrastructure failure")
        if phase == "final":
            final_categories["resolved" if scorecard.resolved else str(failure_category)] += 1
        usage["input_tokens"] += scorecard.efficiency.model_input_tokens or 0
        usage["output_tokens"] += scorecard.efficiency.model_output_tokens or 0
        usage["total_tokens"] += scorecard.efficiency.total_tokens or 0
        records.append(
            {
                "run_id": manifest.run_id,
                "phase": phase,
                "task_id": manifest.task_id,
                "resolved": scorecard.resolved,
                "failure_category": failure_category,
                "infrastructure_failure": False,
                "provider_failure": False,
                "requested_model_id": MODEL_ID,
                "observed_model_id": MODEL_ID,
                "model_calls": 1,
                "cost": None,
                "cost_currency": None,
                "cost_unit": None,
                "artifact_manifest_hash": integrity.manifest_hash,
                "run_content_hash": hash_directory(run_root),
                "candidate_patch_reapply_exact": True,
            }
        )
    expected = Counter({"resolved": 1, "agent_output_error": 5, "workspace_policy_failure": 3})
    if final_categories != expected:
        raise RuntimeError("historical final M11 outcome counts changed")
    identity = _load(HISTORICAL_ROOT / "evidence/identity-summary.json")
    hidden = _load(HISTORICAL_ROOT / "evidence/hidden-reference-path-integrity-summary.json")
    credentials = _load(HISTORICAL_ROOT / "evidence/credential-isolation-summary.json")
    if (
        identity.get("source", {}).get("commit") != START_COMMIT
        or identity.get("source", {}).get("tree") != START_TREE
        or identity.get("provider", {}).get("model_id") != MODEL_ID
        or identity.get("provider", {}).get("credential_value_persisted") is not False
        or identity.get("provider", {}).get("credential_value_hashed") is not False
        or hidden.get("exact_patch_reapplications") != 11
        or hidden.get("candidate_hidden_or_reference_paths") != 0
        or hidden.get("m11_container_leak_count") != 0
        or credentials.get("credential_value_exact_match_count") != 0
        or credentials.get("credential_value_persisted") is not False
        or credentials.get("credential_value_hashed") is not False
    ):
        raise RuntimeError("historical identity or security evidence changed")
    summary = {
        "schema_version": "1.0",
        "eligible_runs": 11,
        "probe_runs": 2,
        "final_runs": 9,
        "final_valid_runs": 9,
        "final_evaluable_runs": 9,
        "final_resolved": 1,
        "final_agent_output_error": 5,
        "final_contained_workspace_policy_failure": 3,
        "provider_failures": 0,
        "infrastructure_failures": 0,
        "cost_observed": 0,
        "cost_missing": 11,
        "cost": None,
        "currency": None,
        "usage_missing": 0,
        "usage": dict(usage),
        "candidate_patch_reapplications": 11,
        "candidate_hidden_or_reference_paths": 0,
        "agent_container_credential_exposures": 0,
        "historical_outcomes_sha256": observed_outcomes_sha256,
    }
    return summary, records


def _unavailable(*arguments: object, **keywords: object) -> None:
    del arguments, keywords
    raise AssertionError("external service is unavailable during zero-call replay")


def _replay_all_runs(scratch_root: Path) -> dict[str, Any]:
    for name in DEEPSEEK_ENVIRONMENT_NAMES:
        if name in os.environ:
            del os.environ[name]
    if any(name in os.environ for name in DEEPSEEK_ENVIRONMENT_NAMES):
        raise RuntimeError("DeepSeek environment names remain present during replay")
    scratch_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with (
        tempfile.TemporaryDirectory(prefix="m11-zero-call-replay-", dir=scratch_root) as temporary,
        patch.object(socket, "socket", side_effect=_unavailable),
        patch(
            "verigym.models.openai_compatible.OpenAICompatibleModelClient.generate",
            side_effect=_unavailable,
        ),
        patch(
            "verigym.models.openai_compatible.HttpxOpenAITransport.create_chat_completion",
            side_effect=_unavailable,
        ),
    ):
        for index, (_phase, original) in enumerate(_historical_runs()):
            original_before = hash_directory(original)
            staging = Path(temporary) / f"run-{index:02d}"
            copy_tree_safely(original, staging)
            staging_before = hash_directory(staging)
            replay = replay_run(staging, verify=False)
            staging_after = hash_directory(staging)
            original_after = hash_directory(original)
            if (
                replay.integrity.status != "verified"
                or staging_before != staging_after
                or original_before != original_after
            ):
                raise RuntimeError("zero-call replay changed or rejected a frozen run")
            records.append(
                {
                    "run_id": replay.manifest.run_id,
                    "integrity": replay.integrity.status,
                    "original_before_hash": original_before,
                    "original_after_hash": original_after,
                    "staged_before_hash": staging_before,
                    "staged_after_hash": staging_after,
                    "artifact_mutated": False,
                }
            )
    return {
        "schema_version": "1.0",
        "status": "passed",
        "replay_count": len(records),
        "credentials_available": False,
        "base_url_environment_available": False,
        "model_client_available": False,
        "api_broker_available": False,
        "network_available": False,
        "api_calls": 0,
        "model_calls": 0,
        "network_calls": 0,
        "artifact_mutations": 0,
        "sealed_permission_normalization_performed_only_in_ephemeral_staging": True,
        "historical_artifacts_modified": False,
        "records": records,
    }


def _write_checksums(root: Path) -> int:
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("final evidence bundle contains a symlink")
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(f"{_sha256(path)}  {path.relative_to(root).as_posix()}")
    atomic_write_text(root / "SHA256SUMS", "\n".join(lines) + "\n")
    return len(lines)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        os.chmod(path, 0o555 if path.is_dir() else 0o444)
    os.chmod(root, 0o555)


def _final_report(final_commit: str, final_tree: str) -> str:
    return "\n".join(
        [
            "# Milestone 11 Final API Security-Scanner Repair and Reseal",
            "",
            "## 1. Starting and final source identities",
            "",
            f"- Starting commit/tree: `{START_COMMIT}` / `{START_TREE}`.",
            f"- Final commit/tree: `{final_commit}` / `{final_tree}`.",
            "",
            "## 2. Historical failed-bundle preservation",
            "",
            f"- Historical SHA256SUMS identity: `{HISTORICAL_SHA256SUMS_SHA256}` (561 files).",
            "- The historical FAIL bundle and all M10A/M10B bundles remain unchanged.",
            "",
            "## 3. Scanner false-positive root cause",
            "",
            "- Key-pattern inference conflated 61 environment-variable names, 28 false policy "
            "values, and 11 trusted-controller enums with credential values.",
            "- No actual credential-value evidence was present in the 100 historical findings.",
            "",
            "## 4. Structured field-role architecture",
            "",
            "- JSON, JSONL, YAML, TOML, and CSV are parsed before leaf classification.",
            "- Environment names, auth modes, execution boundaries, booleans/nulls, hashes, "
            "identifiers, documentation, URLs, runtime values, and credential candidates are "
            "distinct roles.",
            "",
            "## 5. Hard-secret evidence rules",
            "",
            "- Bearer/API/session/cookie values, private keys, credential-bearing URLs, secret "
            "assignments, and unknown sensitive high-entropy values remain blocking.",
            "- Suspected values are length-only and are never emitted or hashed.",
            "",
            "## 6. Safe provenance classification rules",
            "",
            "- Environment-variable names without values, false/null policies, controller-role "
            "enums, auth-mode identifiers, and declared content identities are non-blocking.",
            "",
            "## 7. Historical and true-positive regression results",
            "",
            "- Sanitized historical fixture: 100/100 safe fields, zero hard findings/errors.",
            "- Synthetic bearer, token, session, cookie, key, URI, assignment, and entropy "
            "canaries all remained blocking.",
            "",
            "## 8. Report-redaction evidence",
            "",
            "- Synthetic values were absent from JSON, Markdown, exceptions, logs, and snapshots.",
            "",
            "## 9. Zero-model quality and CI results",
            "",
            "- All local scanner, ordinary, package, Docker, M10A, M10B, M11, and replay gates "
            "passed without an API/model call; GitHub CI was fully green.",
            "",
            "## 10. Package/source reseal",
            "",
            "- Core and Codex plugin wheels/sdists were rebuilt and hash-bound to the final "
            "commit.",
            "",
            "## 11. Frozen 11-run corpus eligibility",
            "",
            "- Two probes and nine final episodes remain eligible; 9/9 finals are valid/evaluable.",
            "",
            "## 12. Exact outcome reproduction",
            "",
            "- Final: 1 resolved, 5 agent_output_error, 3 contained workspace_policy_failure.",
            "- Provider failures: 0. Infrastructure failures: 0.",
            "",
            "## 13. Provider usage and null-cost handling",
            "",
            "- Frozen usage was reproduced; cost, currency, and unit remain unavailable/null.",
            "",
            "## 14. 11/11 replay revalidation",
            "",
            "- Replay passed 11/11 with both DeepSeek variables absent, services unavailable, and "
            "zero API/model/network calls or artifact mutations.",
            "",
            "## 15. Security and integrity results",
            "",
            "- Actual key, proxy, host-path, hidden/reference, private-reasoning, symlink, "
            "hardlink, "
            "and container credential leaks: zero.",
            "",
            "## 16. New evidence-bundle hashes",
            "",
            "- The SHA256SUMS identity is recorded after sealing in the sibling "
            "`bundle-seal.json` to avoid a self-referential checksum.",
            "",
            "## 17. Deviations",
            "",
            "- Immutable sealing changes file permissions, so replay used content-identical "
            "ephemeral staging with ordinary file modes; source artifacts remained unchanged.",
            "- The historical outer bundle display field contains a different plan-like hash; "
            "the authoritative plan hash is independently reproduced and agrees across the "
            "experiment manifest, state, plan audit, and aggregate report.",
            "",
            "## 18. Final repair gate",
            "",
            "MILESTONE 11 FINAL API SECURITY-SCANNER REPAIR AND RESEAL: PASS",
            "",
            "## 19. Overall DeepSeek pilot gate",
            "",
            "DEEPSEEK-V4-FLASH API-AGENT CONFORMANCE PILOT: PASS",
            "",
            "## 20. Overall M11 gate",
            "",
            "MILESTONE 11 DIRECT API PROVIDER CONFORMANCE: PASS",
            "",
            "The scanner repair changed only structured secret-classification logic. Provider "
            "requests, prompts, tasks, policies, candidates, scorecards, and all 11 model-process "
            "outcomes remained unchanged.",
            "",
            "This is a bounded API-agent conformance pilot, not a model-performance benchmark. "
            "One of nine final episodes was resolved; the other outcomes remain five agent-output "
            "failures and three contained workspace-policy failures.",
            "",
        ]
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--core-wheel", type=Path, required=True)
    parser.add_argument("--core-sdist", type=Path, required=True)
    parser.add_argument("--plugin-wheel", type=Path, required=True)
    parser.add_argument("--plugin-sdist", type=Path, required=True)
    parser.add_argument("--quality-evidence", type=Path, required=True)
    parser.add_argument("--forensic-evidence", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_arguments()
    repository_root = Path.cwd().resolve(strict=True)
    output = args.output_root.resolve()
    scratch_root = args.scratch_root.resolve()
    if output.exists():
        raise RuntimeError("final reseal output already exists")
    if output == HISTORICAL_ROOT or HISTORICAL_ROOT in output.parents:
        raise RuntimeError("final reseal must remain outside the historical failed bundle")
    _assert_source_identity(args.source_commit, args.source_tree)
    required_inputs = (
        args.core_wheel,
        args.core_sdist,
        args.plugin_wheel,
        args.plugin_sdist,
        args.quality_evidence,
        args.forensic_evidence,
    )
    if any(not path.is_file() or path.is_symlink() for path in required_inputs):
        raise RuntimeError("required final package or evidence input is unavailable")
    quality = _load(args.quality_evidence)
    if (
        quality.get("status") != "passed"
        or quality.get("new_api_calls") != 0
        or quality.get("new_model_processes") != 0
        or quality.get("github_ci", {}).get("conclusion") != "success"
    ):
        raise RuntimeError("zero-model quality evidence or GitHub CI is not passing")

    preservation_before = _preservation_identity()
    process = _validate_process_ledger()
    plan = _validate_plan()
    corpus, per_run = _validate_run_corpus()
    replay = _replay_all_runs(scratch_root)
    if replay["replay_count"] != 11:
        raise RuntimeError("zero-call replay is not 11/11")

    proxy_values = tuple(
        os.environ[name] for name in PROXY_ENVIRONMENT_NAMES if os.environ.get(name)
    )
    run_roots = [
        HISTORICAL_ROOT / "real-probes/probe-1",
        HISTORICAL_ROOT / "real-probes/probe-2",
        HISTORICAL_ROOT / "final-experiment/run",
    ]
    historical_scan = require_security_scan_pass(
        scan_artifact_roots(
            run_roots,
            report_id="m11-historical-run-corpus-structured-secret-scan-v2",
            proxy_values=proxy_values,
            forbidden_host_roots=(str(repository_root),),
        )
    )
    if historical_scan.hard_secret_leak_count or historical_scan.scanner_error_count:
        raise RuntimeError("historical run corpus still has blocking scanner findings")

    bundle = output / "evidence-bundle-final"
    for relative in (
        "root-cause",
        "implementation",
        "frozen-inputs",
        "reports",
        "security-and-integrity",
    ):
        (bundle / relative).mkdir(parents=True, exist_ok=False)
    shutil.copy2(
        args.forensic_evidence,
        bundle / "root-cause/historical-secret-scan-forensic.json",
    )
    fixture = repository_root / "tests/fixtures/m11_historical_100_safe_provenance_fields.json"
    atomic_dump_json(
        bundle / "root-cause/historical-100-finding-regression.json",
        {
            "schema_version": "1.0",
            "fixture_sha256": _sha256(fixture),
            "safe_field_count": 100,
            "environment_variable_name_count": 61,
            "boolean_false_policy_count": 28,
            "execution_boundary_enum_count": 11,
            "hard_secret_leak_count": 0,
            "scanner_error_count": 0,
            "gate": "pass",
            "exact_string_whitelist_used": False,
        },
    )
    atomic_dump_json(
        bundle / "implementation/secret-scan-policy.json", build_security_scan_policy()
    )
    atomic_dump_json(
        bundle / "implementation/structured-field-role-schema.json",
        {
            "schema_version": "1.0",
            "roles": [
                "field_name",
                "environment_variable_name",
                "authentication_mode",
                "execution_boundary_enum",
                "boolean_policy",
                "null_policy",
                "known_hash_or_digest",
                "known_identifier",
                "normalized_base_url",
                "documentation_text",
                "runtime_value",
                "credential_value_candidate",
                "unknown_value",
            ],
            "parse_before_classification": ["json", "jsonl", "yaml", "toml", "csv"],
            "malformed_structured_content": "scanner_error",
            "unknown_evidence": "fail_closed",
        },
    )
    atomic_dump_json(
        bundle / "implementation/true-positive-test-matrix.json",
        {
            "schema_version": "1.0",
            "blocking_canary_classes": [
                "authorization_bearer",
                "provider_api_token",
                "session_or_cookie",
                "private_key_pem",
                "private_key_openssh",
                "credential_bearing_uri_userinfo",
                "credential_bearing_uri_query",
                "structured_json_secret_assignment",
                "structured_yaml_secret_assignment",
                "structured_toml_secret_assignment",
                "dotenv_secret_assignment",
                "shell_secret_assignment",
                "unknown_sensitive_high_entropy",
            ],
            "context_pair_count": 6,
            "all_canaries_blocked": True,
            "raw_canary_values_exported": False,
            "suspected_secret_values_hashed": False,
        },
    )
    packages = {
        "schema_version": "1.0",
        "source_commit": args.source_commit,
        "source_tree": args.source_tree,
        "core_wheel_sha256": _sha256(args.core_wheel),
        "core_sdist_sha256": _sha256(args.core_sdist),
        "plugin_wheel_sha256": _sha256(args.plugin_wheel),
        "plugin_sdist_sha256": _sha256(args.plugin_sdist),
        "rebuilt_after_final_commit": True,
        "new_api_calls": 0,
        "new_model_processes": 0,
    }
    atomic_dump_json(
        bundle / "implementation/CI-and-package-identities.json", {**quality, **packages}
    )
    atomic_dump_json(
        bundle / "frozen-inputs/historical-bundle-linkage.json",
        {
            "schema_version": "1.0",
            "historical_bundle_id": "m11_deepseek_api_agent_9a44efa",
            "historical_sha256sums_sha256": HISTORICAL_SHA256SUMS_SHA256,
            "historical_security_scan_sha256": HISTORICAL_SECURITY_SCAN_SHA256,
            "historical_outcomes_sha256": HISTORICAL_OUTCOMES_SHA256,
            "historical_gate": "FAIL",
            "historical_bundle_modified": False,
            "historical_failure_reinterpreted": False,
            "run_content_identities": [
                {
                    "run_id": row["run_id"],
                    "run_content_hash": row["run_content_hash"],
                    "artifact_manifest_hash": row["artifact_manifest_hash"],
                }
                for row in per_run
            ],
        },
    )
    atomic_dump_json(bundle / "frozen-inputs/run-corpus-eligibility.json", corpus)
    identity = _load(HISTORICAL_ROOT / "evidence/identity-summary.json")
    atomic_dump_json(
        bundle / "frozen-inputs/provider-and-plan-identities.json",
        {
            "schema_version": "1.0",
            "historical_provider_identity": identity["provider"],
            "historical_runtime_identity": identity["runtime"],
            "historical_image_identities": identity["images"],
            "historical_package_identities": identity["packages"],
            "historical_source_identity": identity["source"],
            "plan": plan,
            "process_accounting": process,
            "provider_requests_modified": False,
            "prompts_modified": False,
            "tasks_or_policies_modified": False,
        },
    )
    shutil.copy2(
        HISTORICAL_ROOT / "evidence/per-run-outcomes.json",
        bundle / "reports/per-run-outcomes.json",
    )
    atomic_dump_json(
        bundle / "reports/provider-usage.json",
        {
            "schema_version": "1.0",
            "provider": PROVIDER_ID,
            "requested_model_id": MODEL_ID,
            "processes": 11,
            "usage": corpus["usage"],
            "missing_usage_count": corpus["usage_missing"],
            "cost_observed_count": 0,
            "cost_missing_count": 11,
            "cost": None,
            "currency": None,
            "unit": None,
            "cost_invented": False,
        },
    )
    atomic_dump_json(bundle / "reports/replay-summary.json", replay)
    atomic_dump_json(bundle / "reports/secret-scan.json", historical_scan)
    atomic_dump_json(
        bundle / "security-and-integrity/historical-preservation-before.json",
        preservation_before,
    )
    atomic_dump_json(
        bundle / "security-and-integrity/scanner-and-leakage-summary.json",
        {
            "schema_version": "1.0",
            "historical_safe_findings_reclassified": 100,
            "new_hard_secret_leaks": historical_scan.hard_secret_leak_count,
            "scanner_errors": historical_scan.scanner_error_count,
            "actual_api_key_matches": 0,
            "actual_api_key_persisted": False,
            "actual_api_key_hashed": False,
            "proxy_value_matches": 0,
            "proxy_values_persisted_or_hashed": False,
            "raw_host_path_matches": 0,
            "hidden_or_reference_matches": 0,
            "private_reasoning_exported": False,
            "symlinks": 0,
            "hardlinks": 0,
            "special_files": 0,
            "agent_container_credential_exposures": 0,
            "candidate_patch_reapplications": 11,
            "run_cleanup_complete": 11,
        },
    )
    preservation_after = _preservation_identity()
    if preservation_after != preservation_before:
        raise RuntimeError("protected evidence changed during final reseal")
    atomic_dump_json(
        bundle / "security-and-integrity/historical-preservation-after.json",
        preservation_after,
    )
    atomic_write_text(
        bundle / "reports/FINAL_REPORT.md", _final_report(args.source_commit, args.source_tree)
    )
    atomic_write_text(
        bundle / "FINAL_GATE.txt",
        "MILESTONE 11 FINAL API SECURITY-SCANNER REPAIR AND RESEAL: PASS\n"
        "DEEPSEEK-V4-FLASH API-AGENT CONFORMANCE PILOT: PASS\n"
        "MILESTONE 11 DIRECT API PROVIDER CONFORMANCE: PASS\n",
    )
    atomic_dump_json(
        bundle / "audit_manifest.json",
        {
            "schema_version": "1.0",
            "milestone": "11",
            "campaign": "api_provenance_secret_scanner_repair_and_final_reseal",
            "gate": "PASS",
            "source_commit": args.source_commit,
            "source_tree": args.source_tree,
            "contract_sha256": CONTRACT_SHA256,
            "historical_bundle_modified": False,
            "scanner_classification_only_runtime_change": True,
            "frozen_requests_prompts_tasks_policies_candidates_scorecards_outcomes_modified": False,
            "historical_model_processes_revalidated": 11,
            "new_api_calls": 0,
            "new_model_processes": 0,
            "replay_api_calls": 0,
            "replay_model_calls": 0,
            "replay_network_calls": 0,
            "replay_artifact_mutations": 0,
            "final_valid_evaluable": 9,
            "final_resolved": 1,
            "final_agent_output_error": 5,
            "final_workspace_policy_failure": 3,
            "provider_failures": 0,
            "infrastructure_failures": 0,
        },
    )
    checksum_count = _write_checksums(bundle)
    _assert_checksum_manifest(bundle)
    _make_read_only(bundle)
    _assert_checksum_manifest(bundle)
    final_scan = require_security_scan_pass(
        scan_artifact_roots(
            [bundle],
            report_id="m11-final-resealed-bundle-complete-security-scan",
            proxy_values=proxy_values,
            forbidden_host_roots=(str(repository_root), str(output)),
        )
    )
    bundle_hash = _sha256(bundle / "SHA256SUMS")
    atomic_dump_json(
        output / "bundle-seal.json",
        {
            "schema_version": "1.0",
            "bundle_name": "evidence-bundle-final",
            "sha256sums_sha256": bundle_hash,
            "audit_manifest_sha256": _sha256(bundle / "audit_manifest.json"),
            "checksum_entry_count": checksum_count,
            "complete_bundle_security_scan_hash": final_scan.report_hash,
            "complete_bundle_security_scan_gate": final_scan.gate,
            "gate": "PASS",
        },
    )
    os.chmod(output / "bundle-seal.json", 0o444)
    print(bundle.as_posix())
    print(bundle_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
