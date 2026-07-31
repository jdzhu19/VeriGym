from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.run_m10b_security_reseal_campaign import load_historical_contamination_report
from verigym.core.hashing import content_hash
from verigym.core.loaders import load_model
from verigym.evolution.memory import validate_memory_pack
from verigym.evolution.memory_builder import memory_builder_allowed_synthesis_sources
from verigym.evolution.splits import (
    build_allowed_synthesis_corpus,
    build_contamination_scan_policy,
    build_task_split,
    scan_contamination_report,
    validate_allowed_synthesis_corpus,
    validate_asset_signature_manifest,
    validate_contamination_scan_policy,
    validate_contamination_scan_report,
)
from verigym.schemas.evolution import (
    ContaminationMatch,
    MemoryPack,
    MemoryPackSection,
    RewardVector,
    TaskSplitEntry,
)
from verigym.schemas.repository import RepositoryTaskManifest

_TRAINING_TASKS = (
    "arbiter_reset_recovery",
    "counter_wrap",
    "pipeline_stall_backpressure",
)
_HELDOUT_TASKS = (
    "arbiter_rotating_priority",
    "counter_load_wrap",
    "pipeline_flush",
)


def _entry(root: Path) -> TaskSplitEntry:
    manifest = load_model(root / "task.yaml", RepositoryTaskManifest)
    return TaskSplitEntry(
        task_id=manifest.task.id,
        source_hash=manifest.source.repository_hash,
        task_hash=content_hash(manifest.task),
        license=manifest.source.license,
        attribution=manifest.source.attribution,
    )


def _first_party_roots() -> tuple[dict[str, Path], dict[str, Path]]:
    base = Path("src/verigym/suites/repo_rtl")
    training = {
        _entry(base / "assets" / name).task_id: base / "assets" / name for name in _TRAINING_TASKS
    }
    heldout = {
        _entry(base / "heldout_assets" / name).task_id: base / "heldout_assets" / name
        for name in _HELDOUT_TASKS
    }
    return training, heldout


def _policy_and_corpus(
    training: dict[str, Path],
    *,
    prompt_suffix: str = "",
) -> tuple[object, object]:
    policy = build_contamination_scan_policy()
    prompt_sources = memory_builder_allowed_synthesis_sources()
    if prompt_suffix:
        prompt_sources = {**prompt_sources, "fixture": prompt_suffix}
    corpus = build_allowed_synthesis_corpus(
        policy=policy,
        training_roots=training,
        prompt_schema_texts=prompt_sources,
        sanitized_training_summary=None,
        reward_channel_names=tuple(RewardVector.model_fields),
        generic_policy_instructions={
            "generic-memory-policy": (
                "Generalize task-independent public-test strategy, workspace policy, "
                "debugging checklists, and patch discipline."
            )
        },
    )
    return policy, corpus


def _historical_memory() -> MemoryPack:
    memory = load_model(
        Path("tests/fixtures/m10b_historical_memory_pack_3da8dd6.json"),
        MemoryPack,
    )
    assert memory.content_hash == (
        "88ff2d9fb62a297430e74431df3ae4fec0a8f746a6e12a978b17e02a90489274"
    )
    return validate_memory_pack(memory)


def _scan(memory: MemoryPack) -> tuple[object, object]:
    training, heldout = _first_party_roots()
    policy, corpus = _policy_and_corpus(training)
    split = build_task_split(
        split_id="m10b-contamination-regression",
        training=[_entry(root) for root in training.values()],
        heldout=[_entry(root) for root in heldout.values()],
        heldout_assets_loaded_after_version_hash="a" * 64,
    )
    return scan_contamination_report(
        split_manifest=split,
        training_roots=training,
        heldout_roots=heldout,
        allowed_corpus=corpus,
        policy=policy,
        memory_pack=memory,
    )


def test_final_reseal_loads_composite_contamination_report(tmp_path: Path) -> None:
    report, _ = _scan(_historical_memory())
    path = tmp_path / "contamination-report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    assert load_historical_contamination_report(path) == report


def _memory_with_items(items: list[str]) -> MemoryPack:
    base = _historical_memory()
    sections = list(base.sections)
    sections[0] = MemoryPackSection(section="principles", items=items)
    return base.model_copy(
        update={
            "sections": sections,
            "content_hash": content_hash({"fixture_items": items}),
            "total_utf8_bytes": len("\n".join(items).encode("utf-8")),
        }
    )


def test_historical_memory_generic_words_are_diagnostic_not_blocking() -> None:
    report, signatures = _scan(_historical_memory())
    assert validate_contamination_scan_report(report) == report
    assert validate_asset_signature_manifest(signatures) == signatures
    assert report.passed
    assert report.hard_contamination_count == 0
    assert report.frozen_memory_scan is not None
    diagnostics = {
        match.public_excerpt: match
        for match in report.frozen_memory_scan.matches
        if match.severity == "diagnostic_overlap"
    }
    assert diagnostics["preserve"].match_class == "allowed_synthesis_vocabulary"
    assert diagnostics["validation"].match_class == "generic_vocabulary"
    assert report.frozen_memory_scan.hidden_assets_exported is False
    assert report.frozen_memory_scan.reference_assets_exported is False


@pytest.mark.parametrize(
    ("items", "expected_class"),
    [
        (["repo-rtl/counter-load-wrap-heldout"], "exact_task_id"),
        (["Inspect repository/rtl/loadable_counter.sv carefully."], "repository_path"),
        (["Inspect loadable_counter before editing."], "distinctive_identifier"),
        (
            ["Reset has highest priority and sets the count."],
            "heldout_issue_phrase",
        ),
        (
            ["module loadable_counter input logic clk input logic rst_n"],
            "source_code_sequence",
        ),
    ],
)
def test_provenance_bearing_public_memory_leakage_blocks(
    items: list[str],
    expected_class: str,
) -> None:
    report, _ = _scan(_memory_with_items(items))
    assert not report.passed
    assert report.frozen_memory_scan is not None
    assert expected_class in {
        match.match_class
        for match in report.frozen_memory_scan.matches
        if match.severity == "hard_contamination"
    }


@pytest.mark.parametrize(
    ("relative", "expected_class"),
    [
        ("hidden/tb_counter_load_hidden.sv", "hidden_test_fragment"),
        ("reference/reference.patch", "reference_patch_fragment"),
    ],
)
def test_private_fragment_matches_are_hash_only(
    relative: str,
    expected_class: str,
) -> None:
    root = Path("src/verigym/suites/repo_rtl/heldout_assets/counter_load_wrap")
    private_lines = [
        line.strip()
        for line in (root / relative).read_text(encoding="utf-8").splitlines()
        if len(" ".join(line.strip().split())) >= 16
        and not line.lstrip().startswith(("//", "#", "/*", "*"))
    ][:5]
    assert len(private_lines) == 5
    report, _ = _scan(_memory_with_items(private_lines))
    assert not report.passed
    assert report.frozen_memory_scan is not None
    private = [
        match for match in report.frozen_memory_scan.matches if match.match_class == expected_class
    ]
    assert private
    assert all(match.public_excerpt is None for match in private)
    rendered = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    assert "\n".join(private_lines) not in rendered


def test_common_engineering_vocabulary_never_blocks_as_single_words() -> None:
    memory = _memory_with_items(
        [
            "preserve validation",
            "reset state",
            "public test",
            "workspace policy",
            "compile and verify",
            "patch correctness",
        ]
    )
    report, _ = _scan(memory)
    assert report.passed
    assert report.hard_contamination_count == 0


def test_allowed_input_overlap_remains_diagnostic() -> None:
    training, heldout = _first_party_roots()
    policy, corpus = _policy_and_corpus(training, prompt_suffix="unique_shared_guidance")
    split = build_task_split(
        split_id="allowed-input-overlap",
        training=[_entry(root) for root in training.values()],
        heldout=[_entry(root) for root in heldout.values()],
        heldout_assets_loaded_after_version_hash="a" * 64,
    )
    memory = _memory_with_items(["unique_shared_guidance validation"])
    report, _ = scan_contamination_report(
        split_manifest=split,
        training_roots=training,
        heldout_roots=heldout,
        allowed_corpus=corpus,
        policy=policy,
        memory_pack=memory,
    )
    assert report.passed


def test_split_asset_exact_copy_is_hard_contamination(tmp_path: Path) -> None:
    training_root = tmp_path / "training"
    heldout_root = tmp_path / "heldout"
    for root in (training_root, heldout_root):
        (root / "repository/rtl").mkdir(parents=True)
        (root / "repository/rtl/copied.sv").write_text(
            "module copied(input logic a, output logic y);\nassign y = a;\nendmodule\n",
            encoding="utf-8",
        )
        (root / "issue.md").write_text(
            "Repair the deliberately duplicated fixture source.",
            encoding="utf-8",
        )
    training_entry = TaskSplitEntry(
        task_id="repo-rtl/training-fixture",
        source_hash="1" * 64,
        task_hash="2" * 64,
        license="Apache-2.0",
        attribution="first-party fixture",
    )
    heldout_entry = TaskSplitEntry(
        task_id="repo-rtl/heldout-fixture",
        source_hash="3" * 64,
        task_hash="4" * 64,
        license="Apache-2.0",
        attribution="first-party fixture",
    )
    split = build_task_split(
        split_id="exact-copy-fixture",
        training=[training_entry],
        heldout=[heldout_entry],
    )
    training = {training_entry.task_id: training_root}
    heldout = {heldout_entry.task_id: heldout_root}
    policy, corpus = _policy_and_corpus(training)
    report, _ = scan_contamination_report(
        split_manifest=split,
        training_roots=training,
        heldout_roots=heldout,
        allowed_corpus=corpus,
        policy=policy,
    )
    assert not report.passed
    assert "exact_file_content" in {match.match_class for match in report.split_asset_scan.matches}


def test_scanner_identities_are_deterministic_and_policy_bound() -> None:
    training, heldout = _first_party_roots()
    policy, corpus = _policy_and_corpus(training)
    assert validate_contamination_scan_policy(policy) == policy
    assert validate_allowed_synthesis_corpus(corpus) == corpus
    split = build_task_split(
        split_id="deterministic-scan",
        training=[_entry(root) for root in training.values()],
        heldout=[_entry(root) for root in heldout.values()],
        heldout_assets_loaded_after_version_hash="a" * 64,
    )
    first = scan_contamination_report(
        split_manifest=split,
        training_roots=training,
        heldout_roots=heldout,
        allowed_corpus=corpus,
        policy=policy,
        memory_pack=_historical_memory(),
    )
    second = scan_contamination_report(
        split_manifest=split,
        training_roots=training,
        heldout_roots=heldout,
        allowed_corpus=corpus,
        policy=policy,
        memory_pack=_historical_memory(),
    )
    assert first == second
    changed_policy = build_contamination_scan_policy(natural_language_min_tokens=6)
    assert changed_policy.policy_hash != policy.policy_hash


def test_changed_heldout_asset_changes_signature_identity(tmp_path: Path) -> None:
    training, heldout = _first_party_roots()
    policy, corpus = _policy_and_corpus(training)
    split = build_task_split(
        split_id="changed-heldout-signature",
        training=[_entry(root) for root in training.values()],
        heldout=[_entry(root) for root in heldout.values()],
        heldout_assets_loaded_after_version_hash="a" * 64,
    )
    _, original = scan_contamination_report(
        split_manifest=split,
        training_roots=training,
        heldout_roots=heldout,
        allowed_corpus=corpus,
        policy=policy,
        memory_pack=_historical_memory(),
    )
    changed = dict(heldout)
    task_id = "repo-rtl/counter-load-wrap-heldout"
    changed_root = tmp_path / "counter-load-wrap"
    shutil.copytree(changed[task_id], changed_root)
    (changed_root / "issue.md").write_text(
        (changed_root / "issue.md").read_text(encoding="utf-8")
        + "\nDistinctive heldout_probe_signature_91 must remain private.\n",
        encoding="utf-8",
    )
    changed[task_id] = changed_root
    _, modified = scan_contamination_report(
        split_manifest=split,
        training_roots=training,
        heldout_roots=changed,
        allowed_corpus=corpus,
        policy=policy,
        memory_pack=_historical_memory(),
    )
    assert modified.manifest_hash != original.manifest_hash


def test_unknown_match_class_is_rejected_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ContaminationMatch.model_validate(
            {
                "stage": "frozen_memory_to_heldout",
                "match_class": "unclassified_similarity",
                "severity": "diagnostic_overlap",
                "evidence_hash": "a" * 64,
                "heldout_identity": "fixture",
                "normalized_token_count": 1,
                "match_location_class": "unknown",
            }
        )
