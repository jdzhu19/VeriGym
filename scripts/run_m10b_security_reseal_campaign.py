#!/usr/bin/env python3
"""Offline-only M10B security-scanner repair verification and final reseal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.evolution.comparison import build_evolving_evaluation
from verigym.evolution.exporter import replay_trajectory_dataset, validate_trajectory_dataset
from verigym.evolution.memory import validate_agent_version, validate_memory_pack
from verigym.evolution.reporting import EvolutionReportService
from verigym.evolution.splits import validate_contamination_scan_report, validate_task_split
from verigym.evolution.versions import (
    build_agent_lineage,
    replay_context_update,
    validate_agent_lineage,
)
from verigym.experiments.state import atomic_dump_json, atomic_write_text, load_json_model
from verigym.reporting.loader import load_report_inputs
from verigym.schemas.evolution import (
    AgentUpdateManifest,
    AgentVersionManifest,
    ContaminationScanReport,
    EvolvingEvaluationReport,
    MemoryPack,
    SanitizedTrainingSummary,
    TaskSplitManifest,
    TrajectoryDatasetManifest,
)

START_COMMIT = "93097b7027e5a1ee8d4f021ee312b6377118ad5a"
START_TREE = "a74eb817a4965e55574bbbd26095f15d0c553787"
HISTORICAL_ROOT = Path(
    "/data/jzhu484/Agent/VeriGym_m10b_contamination_93097b7/evidence-bundle-final"
)
TRAINING_ROOT = Path("/data/jzhu484/Agent/VeriGym_m10b_memory_builder_3da8dd6")
REFERENCE_CHECKPOINT = Path(
    "/data/jzhu484/Agent/VeriGym_reference_qualified_52318e1/"
    "checkpoint-bundle-114/BUNDLE-MANIFEST.json"
)
PROTECTED_BUNDLES: tuple[tuple[str, Path, str], ...] = (
    (
        "m10b_93097b7",
        HISTORICAL_ROOT,
        "067dfa3fa4ddf5f34d14b4ee52a63ef443312398477bf0f76a9d13f917e4666d",
    ),
    (
        "m10b_3da8dd6",
        Path("/data/jzhu484/Agent/VeriGym_m10b_memory_builder_3da8dd6/evidence-bundle-final"),
        "ec9fd849195121057e781c228861b683a14cef948a535754d4323382723b1f41",
    ),
    (
        "m10b_9811aa4",
        Path("/data/jzhu484/Agent/VeriGym_m10b_prompt_binding_9811aa4/evidence-bundle-final"),
        "2abd8f8f90f8333e68cfd9e19a793e98c5688cdaa58603794634984958810fb7",
    ),
    (
        "m10b_de9dc9d",
        Path("/data/jzhu484/Agent/VeriGym_milestone10b_de9dc9d/evidence-bundle-final"),
        "fd549b7e064aabdad1c2e07630de62f8e424a9a4c368d7df71813c048def8188",
    ),
    (
        "m10a_53b0755",
        Path("/data/jzhu484/Agent/VeriGym_milestone10a_53b0755/evidence-bundle-final"),
        "afa59b11bbe9f57caed8b5eb8b27739ff09cfd57e9a0fbd11df64851f4ffe420",
    ),
)
REFERENCE_CHECKPOINT_SHA256 = "2d5cdb67bf60c1a26f3b20bfab4c50bbe3efc331db3bf7508ece2f1cbf3d1ce9"
HISTORICAL_AUDIT_SHA256 = "18252bfe7ccef2dc97857cc6c2aaa6cb779a2ffbb79dbf958db68d7cdc31f31e"
MEMORY_PACK_HASH = "88ff2d9fb62a297430e74431df3ae4fec0a8f746a6e12a978b17e02a90489274"
V0_ID = "codex-cli-agent-v0-final"
V1_ID = "codex-cli-agent-v1-final"
EXPECTED_OUTCOMES_SHA256 = "fad996aa865e7fab2c7756f9abb3ae3c301174a231c9c4b8362d69c6eaf1e995"
PROXY_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
)


def load_historical_contamination_report(path: Path) -> ContaminationScanReport:
    """Load and validate the frozen two-stage contamination report."""

    report = load_json_model(path, ContaminationScanReport)
    validate_contamination_scan_report(report)
    if not report.passed or report.hard_contamination_count:
        raise RuntimeError("frozen contamination report no longer passes")
    return report


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


def _assert_source_identity(expected_commit: str, expected_tree: str) -> None:
    if _git("rev-parse", "HEAD") != expected_commit:
        raise RuntimeError("source commit differs from the final reseal identity")
    if _git("rev-parse", "HEAD^{tree}") != expected_tree:
        raise RuntimeError("source tree differs from the final reseal identity")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("source worktree must be clean before final reseal")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", START_COMMIT, expected_commit],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _assert_checksum_manifest(root: Path) -> int:
    manifest = root / "SHA256SUMS"
    if not manifest.is_file() or manifest.is_symlink():
        raise RuntimeError("protected bundle lacks a safe checksum manifest")
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
    bundles: list[dict[str, Any]] = []
    for bundle_id, root, expected in PROTECTED_BUNDLES:
        verified = _assert_checksum_manifest(root)
        actual = _sha256(root / "SHA256SUMS")
        if actual != expected:
            raise RuntimeError(f"protected bundle identity changed: {bundle_id}")
        bundles.append(
            {
                "bundle_id": bundle_id,
                "sha256sums_sha256": actual,
                "verified_file_count": verified,
                "modified": False,
            }
        )
    if _sha256(HISTORICAL_ROOT / "audit_manifest.json") != HISTORICAL_AUDIT_SHA256:
        raise RuntimeError("historical failed audit identity changed")
    if _sha256(REFERENCE_CHECKPOINT) != REFERENCE_CHECKPOINT_SHA256:
        raise RuntimeError("live reference-qualified checkpoint identity changed")
    return {
        "schema_version": "1.0",
        "bundles": bundles,
        "historical_failed_audit_sha256": HISTORICAL_AUDIT_SHA256,
        "reference_checkpoint_manifest_sha256": REFERENCE_CHECKPOINT_SHA256,
        "protected_assets_modified": False,
    }


def _metric(metric: Any) -> tuple[int, int, float | None, float | None, float | None]:
    return (
        metric.evaluable,
        metric.resolved,
        metric.macro_pass_at_1,
        metric.macro_pass_at_2,
        metric.macro_pass_at_3,
    )


def verify_required_metrics(report: EvolvingEvaluationReport) -> dict[str, Any]:
    """Require the exact frozen descriptive result without rounding it internally."""

    by_id = {item.agent_version_id: item for item in report.version_metrics}
    if set(by_id) != {V0_ID, V1_ID}:
        raise RuntimeError("evaluation report version identities changed")
    expected = {
        V0_ID: (9, 7, 0.7777777777777777, 1.0, 1.0),
        V1_ID: (9, 6, 0.6666666666666666, 0.8888888888888888, 1.0),
    }
    for version_id, values in expected.items():
        actual = _metric(by_id[version_id])
        if actual != values:
            raise RuntimeError(f"frozen metric changed: {version_id}")
    delta = report.paired_difference.macro_pass_at_1_delta
    if delta != -0.11111111111111105:
        raise RuntimeError("paired pass@1 difference changed")
    if report.establishes_general_improvement or not report.no_weight_update:
        raise RuntimeError("required bounded-pilot interpretation changed")
    return {
        "schema_version": "1.0",
        "v0": {
            "evaluable": 9,
            "resolved": 7,
            "pass_at_1": 0.7777777777777777,
            "pass_at_2": 1.0,
            "pass_at_3": 1.0,
        },
        "v1": {
            "evaluable": 9,
            "resolved": 6,
            "pass_at_1": 0.6666666666666666,
            "pass_at_2": 0.8888888888888888,
            "pass_at_3": 1.0,
        },
        "paired_v1_minus_v0_pass_at_1": delta,
        "matches_required_offline_metrics": True,
    }


def _validate_prompt_and_candidate_binding(experiment: Path) -> dict[str, Any]:
    inputs = load_report_inputs(experiment)
    if inputs.planned_count != 18 or len(inputs.valid_runs) != 18 or inputs.invalid_inputs:
        raise RuntimeError("frozen held-out experiment is not 18/18 valid")
    plans = {item.plan_index: item for item in inputs.plan_items}
    resolved = 0
    policy = 0
    run_rows: list[dict[str, Any]] = []
    for run in sorted(inputs.valid_runs, key=lambda item: item.plan_index):
        item = plans[run.plan_index]
        if run.manifest.task_id != item.task_id or run.manifest.task_hash != item.task_hash:
            raise RuntimeError("plan/child task binding changed")
        if run.manifest.prompt_policy != item.prompt_policy:
            raise RuntimeError("plan/child prompt policy binding changed")
        version_id = item.system.agent_options.get("agent_version_id")
        version_hash = item.system.agent_options.get("agent_version_hash")
        if version_id not in {V0_ID, V1_ID} or not isinstance(version_hash, str):
            raise RuntimeError("plan/child agent-version binding changed")
        repository = run.manifest.repository_candidate
        if run.scorecard.resolved:
            resolved += 1
            if repository is None or not repository.patch.reapply_exact:
                raise RuntimeError("resolved candidate lost exact patch reproduction evidence")
        if (
            run.scorecard.failure is not None
            and run.scorecard.failure.kind == "policy"
            and run.scorecard.failure.category == "workspace_policy"
        ):
            policy += 1
        run_rows.append(
            {
                "plan_index": run.plan_index,
                "run_id": run.manifest.run_id,
                "task_id": run.manifest.task_id,
                "agent_version_id": version_id,
                "agent_version_hash": version_hash,
                "prompt_policy_hash": run.manifest.prompt_policy_hash,
                "candidate_hash": run.manifest.candidate_hash,
                "resolved": run.scorecard.resolved,
                "evaluable": True,
                "outcome_kind": (
                    "resolved_candidate"
                    if run.scorecard.resolved
                    else (
                        "contained_workspace_policy_failure"
                        if run.scorecard.failure is not None
                        and run.scorecard.failure.kind == "policy"
                        and run.scorecard.failure.category == "workspace_policy"
                        else "candidate_failure"
                    )
                ),
                "patch_reapply_exact": (
                    repository.patch.reapply_exact if repository is not None else None
                ),
            }
        )
    if resolved != 13 or policy != 5:
        raise RuntimeError("frozen held-out outcome counts changed")
    return {
        "schema_version": "1.0",
        "plan_hash": inputs.plan_hash,
        "planned": 18,
        "terminal": 18,
        "evaluable": 18,
        "resolved": resolved,
        "contained_policy_failures": policy,
        "infrastructure_failures": 0,
        "prompt_bindings_valid": 18,
        "candidate_artifact_manifests_valid": 18,
        "resolved_patch_reproductions_valid": resolved,
        "runs": run_rows,
    }


def _validate_replay_summary() -> dict[str, Any]:
    source = _load(HISTORICAL_ROOT / "replay/replay-summary.json")
    probe = source.get("probe")
    heldout = source.get("heldout")
    if not isinstance(probe, list) or not isinstance(heldout, list):
        raise RuntimeError("historical replay summary has invalid coverage")
    rows = [*probe, *heldout]
    if len(probe) != 1 or len(heldout) != 18 or len(rows) != 19:
        raise RuntimeError("historical zero-call replay is not 19/19")
    call_fields = (
        "codex_calls",
        "broker_calls",
        "credential_accesses",
        "proxy_uses",
        "public_launcher_calls",
    )
    for row in rows:
        if any(row.get(field) != 0 for field in call_fields):
            raise RuntimeError("historical replay contains an external call")
    if any(source.get(field) != 0 for field in call_fields):
        raise RuntimeError("historical replay aggregate contains an external call")
    return {
        "schema_version": "1.0",
        "probe_replays": 1,
        "heldout_replays": 18,
        "total_replays": 19,
        "terminal_replays_valid": 19,
        "codex_calls": 0,
        "broker_calls": 0,
        "credential_accesses": 0,
        "proxy_uses": 0,
        "public_launcher_calls": 0,
        "network_calls": 0,
        "stored_replay_summary_sha256": _sha256(HISTORICAL_ROOT / "replay/replay-summary.json"),
    }


def _validate_process_accounting() -> dict[str, Any]:
    process = _load(HISTORICAL_ROOT / "security-and-integrity/process-ledger-manifest.json")
    records = process.get("records")
    if not isinstance(records, list):
        raise RuntimeError("process ledger records are unavailable")
    terminal = [item for item in records if item.get("record_phase") == "terminal"]
    authorized = [item for item in records if item.get("record_phase") == "authorized"]
    if len(terminal) != 19 or len(authorized) != 19:
        raise RuntimeError("historical process ledger coverage changed")
    if any(not item.get("model_process_started") for item in terminal):
        raise RuntimeError("historical terminal process lacks start evidence")
    if any(item.get("retry") or item.get("resume") for item in records):
        raise RuntimeError("historical process ledger contains retry or resume")
    kinds = {item.get("process_kind") for item in terminal}
    if kinds != {"implementation_probe", "heldout"}:
        raise RuntimeError("historical process kinds changed")
    return {
        "schema_version": "1.0",
        "historical_authorized_processes": 19,
        "historical_terminal_processes": 19,
        "probe_processes": 1,
        "heldout_processes": 18,
        "new_model_processes": 0,
        "retry_or_resume": False,
        "model_processes_authorized_by_reseal": 0,
        "ledger_manifest_hash": process.get("manifest_hash"),
    }


def _validate_lineage() -> tuple[AgentVersionManifest, AgentVersionManifest, MemoryPack, Any]:
    v0 = load_json_model(HISTORICAL_ROOT / "memory-reuse/v0-final.json", AgentVersionManifest)
    v1 = load_json_model(HISTORICAL_ROOT / "memory-reuse/v1-final.json", AgentVersionManifest)
    memory = load_json_model(HISTORICAL_ROOT / "memory-reuse/frozen-memory-pack.json", MemoryPack)
    update = load_json_model(
        HISTORICAL_ROOT / "memory-reuse/final-update-lineage.json", AgentUpdateManifest
    )
    validate_agent_version(v0)
    validate_agent_version(v1)
    validate_memory_pack(memory)
    if v0.memory_pack_hash is not None or v1.memory_pack_hash != MEMORY_PACK_HASH:
        raise RuntimeError("frozen v0/v1 memory binding changed")
    if memory.content_hash != MEMORY_PACK_HASH:
        raise RuntimeError("frozen memory-pack content identity changed")
    stable = (
        "base_agent_id",
        "agent_descriptor_hash",
        "model_id",
        "reasoning_effort",
        "auth_semantic_id",
        "runtime_identity_hash",
        "tool_policy_hash",
        "prompt_contract_hash",
        "source_commit",
        "package_hashes",
        "image_hashes",
    )
    if any(getattr(v0, field) != getattr(v1, field) for field in stable):
        raise RuntimeError("frozen v0/v1 stable execution identity changed")
    training_dataset = load_json_model(
        TRAINING_ROOT / "training-import/export-a/dataset-manifest.json",
        TrajectoryDatasetManifest,
    )
    summary = load_json_model(
        TRAINING_ROOT / "final-sanitized-training-summary.json",
        SanitizedTrainingSummary,
    )
    replay_context_update(
        parent=v0,
        result=v1,
        update=update,
        dataset=training_dataset,
        training_summary=summary,
        memory_pack=memory,
    )
    lineage = build_agent_lineage(
        parent=v0,
        result=v1,
        update=update,
        lineage_id="m10b-final-security-reseal-lineage",
    )
    validate_agent_lineage(lineage)
    return v0, v1, memory, lineage


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
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        os.chmod(path, mode & ~0o222)
    mode = stat.S_IMODE(os.lstat(root).st_mode)
    os.chmod(root, mode & ~0o222)


def _final_report(source_commit: str) -> str:
    return "\n".join(
        [
            "# M10B Final Security-Scanner Repair and Reseal",
            "",
            f"- Final scanner source commit: `{source_commit}`.",
            "- The historical 93097b7 failure remains valid, immutable diagnostic evidence.",
            "- Only scanner classification logic changed.",
            "- The frozen memory pack, agent versions, prompts, policies, tasks, candidates, "
            "and outcomes remained unchanged.",
            "- The context-aware scan distinguishes structured field roles and requires "
            "concrete, redacted credential evidence for a blocking secret finding.",
            "- True-positive bearer, API-token, session, cookie, private-key, credential-URI, "
            "secret-assignment, proxy-value, and unknown-sensitive-entropy canaries remained "
            "blocking.",
            "- Raw canary values were not exported, logged, or included in exceptions; proxy "
            "values were neither persisted nor hashed.",
            "- Historical result integrity, prompt binding, candidate artifacts, process "
            "accounting, lineage, and contamination evidence were revalidated offline.",
            "- Zero-call replay coverage was 19/19 with Codex, broker, credentials, proxies, "
            "public launcher, and network unavailable.",
            "- v0 resolved 7/9; pass@1 0.778, pass@2 1.000, pass@3 1.000.",
            "- v1 resolved 6/9; pass@1 0.667, pass@2 0.889, pass@3 1.000.",
            "- The paired v1-v0 pass@1 difference was -0.111.",
            "- This three-task pilot does not establish general performance improvement.",
            "- v1 was directionally worse than v0 on pass@1.",
            "- No model-bearing process was authorized or launched during this campaign.",
            "- MILESTONE 10B FINAL SECURITY-SCANNER REPAIR AND RESEAL: PASS",
            "- MILESTONE 10B EVOLVING-AGENT EVALUATION BRIDGE: PASS",
            "",
        ]
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--core-wheel", type=Path, required=True)
    parser.add_argument("--plugin-wheel", type=Path, required=True)
    parser.add_argument("--quality-evidence", type=Path, required=True)
    parser.add_argument("--forensic-evidence", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_arguments()
    repository_root = Path.cwd().resolve(strict=True)
    output = args.output_root.resolve()
    if output.exists():
        raise RuntimeError("final reseal output already exists")
    _assert_source_identity(args.source_commit, args.source_tree)
    if args.source_tree == START_TREE:
        raise RuntimeError("final scanner repair tree unexpectedly equals the failed baseline tree")
    for path in (args.core_wheel, args.plugin_wheel, args.quality_evidence, args.forensic_evidence):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("required final input is unavailable or unsafe")

    preservation_before = _preservation_identity()
    historical_experiment = HISTORICAL_ROOT / "heldout-evaluation/experiment"
    historical_dataset = HISTORICAL_ROOT / "heldout-evaluation/trajectory-dataset"
    experiment_integrity = verify_artifact_manifest(
        historical_experiment, expected_scope="experiment"
    )
    for run_root in sorted((historical_experiment / "runs").iterdir()):
        if run_root.is_dir():
            verify_artifact_manifest(run_root, expected_scope="run")
    binding = _validate_prompt_and_candidate_binding(historical_experiment)
    replay = _validate_replay_summary()
    process_accounting = _validate_process_accounting()
    dataset_manifest = validate_trajectory_dataset(historical_dataset)
    replayed_manifest = replay_trajectory_dataset(historical_dataset, historical_experiment)
    if replayed_manifest != dataset_manifest:
        raise RuntimeError("held-out trajectory replay identity changed")
    split = load_json_model(historical_dataset / "task-split-manifest.json", TaskSplitManifest)
    validate_task_split(split)
    contamination = load_historical_contamination_report(
        HISTORICAL_ROOT / "implementation/contamination-report.json"
    )
    v0, v1, memory, lineage = _validate_lineage()
    evaluation = build_evolving_evaluation(
        historical_experiment,
        split_manifest=split,
        baseline_version_id=V0_ID,
        evolved_version_id=V1_ID,
    )
    historical_evaluation = load_json_model(
        HISTORICAL_ROOT / "reports/evolving-evaluation.json", EvolvingEvaluationReport
    )
    if evaluation != historical_evaluation:
        raise RuntimeError("offline evaluation does not reproduce the frozen report exactly")
    metrics = verify_required_metrics(evaluation)
    if _sha256(HISTORICAL_ROOT / "heldout-evaluation/per-run-outcomes.json") != (
        EXPECTED_OUTCOMES_SHA256
    ):
        raise RuntimeError("historical per-run outcomes identity changed")

    proxy_values = tuple(os.environ[name] for name in PROXY_NAMES if os.environ.get(name))
    historical_security = require_security_scan_pass(
        scan_artifact_roots(
            [HISTORICAL_ROOT],
            report_id="m10b-historical-bundle-context-aware-security-scan",
            proxy_values=proxy_values,
            forbidden_host_roots=(str(repository_root),),
        )
    )

    bundle = output / "evidence-bundle-final"
    for relative in (
        "root-cause",
        "implementation",
        "frozen-inputs",
        "reports",
        "replay",
        "security-and-integrity",
        "source-and-package-identities",
    ):
        (bundle / relative).mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.forensic_evidence, bundle / "root-cause/secret-scanner-forensic.json")
    atomic_dump_json(
        bundle / "root-cause/false-positive-regression.json",
        {
            "schema_version": "1.0",
            "historical_artifact": "implementation/allowed-synthesis-corpus.json",
            "field_path": "$.normalized_tokens[446]",
            "field_role": "enum_or_identifier",
            "historical_value_sha256": (
                "a26212cbb92e3c5f94dbdc91029ad6d7b325a1e5b8850b22605a3f854ec45c76"
            ),
            "old_unanchored_suffix_match": True,
            "new_blocking_secret_finding": False,
            "new_diagnostic_vocabulary_finding": True,
            "exact_string_whitelist_used": False,
        },
    )
    shutil.copy2(
        repository_root / "docs/schemas/security-scan-policy.schema.json",
        bundle / "implementation/security-scan-policy.schema.json",
    )
    shutil.copy2(
        repository_root / "docs/schemas/security-finding.schema.json",
        bundle / "implementation/security-finding.schema.json",
    )
    shutil.copy2(args.quality_evidence, bundle / "implementation/quality-and-ci.json")
    atomic_dump_json(
        bundle / "implementation/scanner-test-matrix.json",
        {
            "schema_version": "1.0",
            "structured_parsers": ["json", "jsonl", "yaml", "toml", "csv", "text", "binary"],
            "field_roles": [
                "field_name",
                "enum_or_identifier",
                "boolean_or_null_policy",
                "known_hash_identity",
                "documentation_text",
                "runtime_value",
                "credential_value_candidate",
                "unknown_value",
            ],
            "true_positive_canaries": [
                "authorization_bearer",
                "provider_api_token",
                "session_or_cookie",
                "private_key",
                "credential_bearing_uri",
                "persisted_secret_assignment",
                "persisted_proxy_value",
                "unknown_sensitive_high_entropy",
            ],
            "raw_canary_values_exported": False,
            "proxy_values_hashed_or_persisted": False,
            "unknown_sensitive_values_fail_closed": True,
        },
    )
    atomic_dump_json(
        bundle / "frozen-inputs/historical-linkage.json",
        {
            "schema_version": "1.0",
            "historical_bundle_id": "m10b_93097b7",
            "historical_sha256sums_sha256": preservation_before["bundles"][0]["sha256sums_sha256"],
            "historical_audit_sha256": HISTORICAL_AUDIT_SHA256,
            "historical_outcomes_sha256": EXPECTED_OUTCOMES_SHA256,
            "historical_bundle_modified": False,
            "historical_failure_reinterpreted": False,
        },
    )
    atomic_dump_json(bundle / "frozen-inputs/prompt-candidate-binding.json", binding)
    atomic_dump_json(
        bundle / "frozen-inputs/memory-version-lineage.json",
        {
            "schema_version": "1.0",
            "memory_pack_hash": memory.content_hash,
            "v0_version_hash": v0.version_hash,
            "v0_memory_pack_hash": v0.memory_pack_hash,
            "v1_version_hash": v1.version_hash,
            "v1_memory_pack_hash": v1.memory_pack_hash,
            "lineage_hash": lineage.lineage_hash,
            "frozen_inputs_modified": False,
        },
    )
    atomic_dump_json(bundle / "reports/evolving-evaluation.json", evaluation)
    atomic_dump_json(bundle / "reports/exact-metrics.json", metrics)
    atomic_dump_json(bundle / "reports/agent-lineage.json", lineage)
    atomic_dump_json(bundle / "reports/security-scan.json", historical_security)
    report_service = EvolutionReportService()
    report_service.generate_dataset(historical_dataset, bundle / "reports/trajectory-reward")
    report_service.generate_evaluation(evaluation, bundle / "reports/evaluation")
    report_service.generate_lineage(
        lineage=lineage, memory=memory, output=bundle / "reports/lineage"
    )
    atomic_write_text(bundle / "reports/final-report.md", _final_report(args.source_commit))
    atomic_dump_json(
        bundle / "reports/final-gate.json",
        {
            "schema_version": "1.0",
            "gate": "PASS",
            "label": "MILESTONE 10B FINAL SECURITY-SCANNER REPAIR AND RESEAL: PASS",
            "bridge_label": "MILESTONE 10B EVOLVING-AGENT EVALUATION BRIDGE: PASS",
            "scanner_classification_only_change": True,
            "frozen_run_inputs_and_outcomes_unchanged": True,
            "general_performance_improvement_established": False,
            "v1_directionally_worse_on_pass_at_1": True,
        },
    )
    atomic_dump_json(bundle / "replay/zero-call-replay-validation.json", replay)
    atomic_dump_json(
        bundle / "replay/trajectory-reward-replay.json",
        {
            "schema_version": "1.0",
            "dataset_hash": replayed_manifest.dataset_hash,
            "record_count": replayed_manifest.record_count,
            "reward_vectors_recomputed": replayed_manifest.record_count,
            "source_bindings_revalidated": replayed_manifest.record_count,
            "model_calls": 0,
            "runtime_calls": 0,
            "network_calls": 0,
        },
    )
    atomic_dump_json(
        bundle / "security-and-integrity/historical-preservation-before.json",
        preservation_before,
    )
    atomic_dump_json(bundle / "security-and-integrity/process-accounting.json", process_accounting)
    atomic_dump_json(
        bundle / "security-and-integrity/integrity-validation.json",
        {
            "schema_version": "1.0",
            "experiment_artifact_manifest_status": experiment_integrity.status,
            "experiment_artifact_manifest_hash": experiment_integrity.manifest_hash,
            "run_artifact_manifests_verified": 18,
            "trajectory_dataset_hash": dataset_manifest.dataset_hash,
            "contamination_scan_hash": contamination.scan_hash,
            "contamination_gate": "pass" if contamination.passed else "fail",
            "hidden_or_reference_leaks": 0,
            "private_reasoning_exported": False,
            "candidate_outcomes_modified": False,
        },
    )
    atomic_dump_json(
        bundle / "source-and-package-identities/source.json",
        {
            "schema_version": "1.0",
            "starting_commit": START_COMMIT,
            "starting_tree": START_TREE,
            "final_commit": args.source_commit,
            "final_tree": args.source_tree,
            "worktree_clean": True,
            "change_scope": "context_aware_security_scanner_classification_only",
        },
    )
    atomic_dump_json(
        bundle / "source-and-package-identities/packages.json",
        {
            "schema_version": "1.0",
            "core_wheel_sha256": _sha256(args.core_wheel),
            "plugin_wheel_sha256": _sha256(args.plugin_wheel),
            "package_rebuilt_after_final_commit": True,
            "model_processes": 0,
        },
    )

    preseal_scan = require_security_scan_pass(
        scan_artifact_roots(
            [bundle],
            report_id="m10b-final-bundle-preseal-security-scan",
            proxy_values=proxy_values,
            forbidden_host_roots=(str(repository_root),),
        )
    )
    atomic_dump_json(
        bundle / "security-and-integrity/final-bundle-security-scan.json", preseal_scan
    )
    preservation_after = _preservation_identity()
    if preservation_after != preservation_before:
        raise RuntimeError("protected historical identity changed during final reseal")
    atomic_dump_json(
        bundle / "security-and-integrity/historical-preservation-after.json",
        preservation_after,
    )
    final_scan = require_security_scan_pass(
        scan_artifact_roots(
            [bundle],
            report_id="m10b-final-bundle-complete-security-scan",
            proxy_values=proxy_values,
            forbidden_host_roots=(str(repository_root),),
        )
    )
    if final_scan.hard_secret_leak_count or final_scan.scanner_error_count:
        raise RuntimeError("complete final evidence bundle did not pass security scanning")

    preseal = {
        path.relative_to(bundle).as_posix(): _sha256(path)
        for path in sorted(bundle.rglob("*"))
        if path.is_file()
    }
    atomic_dump_json(
        bundle / "audit_manifest.json",
        {
            "schema_version": "1.0",
            "milestone": "10B",
            "campaign": "context_aware_secret_scanner_repair_and_final_reseal",
            "gate": "PASS",
            "source_commit": args.source_commit,
            "source_tree": args.source_tree,
            "historical_bundle_modified": False,
            "scanner_classification_only_change": True,
            "frozen_inputs_and_outcomes_modified": False,
            "historical_processes_revalidated": 19,
            "new_model_processes": 0,
            "replay_model_calls": 0,
            "preseal_file_set_hash": content_hash(preseal),
        },
    )
    checksum_count = _write_checksums(bundle)
    _assert_checksum_manifest(bundle)
    atomic_dump_json(
        output / "bundle-seal.json",
        {
            "schema_version": "1.0",
            "bundle_name": "evidence-bundle-final",
            "sha256sums_sha256": _sha256(bundle / "SHA256SUMS"),
            "audit_manifest_sha256": _sha256(bundle / "audit_manifest.json"),
            "checksum_entry_count": checksum_count,
            "gate": "PASS",
        },
    )
    _make_read_only(bundle)
    _assert_checksum_manifest(bundle)
    print(str(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
