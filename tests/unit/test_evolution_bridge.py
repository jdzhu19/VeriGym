from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_directory
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.evolution import exporter as trajectory_exporter
from verigym.evolution.comparison import build_evolving_evaluation
from verigym.evolution.exporter import (
    TrajectoryExporter,
    _trajectory_eligibility,
    replay_trajectory_dataset,
    validate_trajectory_dataset,
)
from verigym.evolution.ledger import (
    authorize_process,
    finish_process,
    seal_process_ledger,
    validate_process_ledger_manifest,
)
from verigym.evolution.memory import (
    build_agent_version,
    build_memory_pack,
    prepare_training_summary,
    validate_agent_version,
    validate_memory_pack,
)
from verigym.evolution.memory_builder import (
    MEMORY_BUILDER_PROMPT_HASH,
    build_memory_builder_input,
    parse_memory_builder_output,
    render_memory_builder_prompt,
    validate_memory_builder_input,
)
from verigym.evolution.reporting import EvolutionReportService
from verigym.evolution.rewards import classify_outcome
from verigym.evolution.splits import (
    build_task_split,
    scan_contamination,
    validate_contamination_scan,
    validate_task_split,
)
from verigym.evolution.trainer import (
    build_agent_import_manifest,
    build_trainer_export_manifest,
    validate_agent_import_manifest,
)
from verigym.evolution.versions import (
    build_agent_lineage,
    build_agent_version_set,
    build_run_version_assignments,
    freeze_context_update,
    replay_context_update,
    validate_agent_lineage,
    validate_agent_version_set,
    validate_run_version_assignments,
)
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig
from verigym.experiments.state import atomic_dump_json, load_jsonl_models
from verigym.reporting.loader import load_report_inputs
from verigym.schemas.evolution import (
    AgentUpdateManifest,
    EpisodeTrajectory,
    RewardVector,
    RunAgentVersionAssignment,
    SanitizedTrainingEpisode,
    SanitizedTrainingSummary,
    TaskSplitEntry,
)
from verigym.schemas.repository import RepositoryTaskManifest
from verigym.schemas.run import RunConfig
from verigym.schemas.score import EpisodeFailure, ScoreCard
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite

_HASH = "a" * 64


def _reward() -> RewardVector:
    return RewardVector(
        outcome_kind="resolved_candidate",
        infrastructure_valid=1,
        policy_compliance=1,
        public_test_reached=1,
        public_test_passed=1,
        patch_reproducible=1,
        candidate_compile_passed=1,
        hidden_regression_passed=1,
        task_resolved=1,
        changed_file_count=1,
        added_lines=2,
        deleted_lines=2,
        public_tool_calls=1,
        wall_time_s=4.0,
        input_tokens=100,
        output_tokens=20,
    )


def _summary() -> SanitizedTrainingSummary:
    episode = SanitizedTrainingEpisode(
        public_task_category="repository_rtl_repair",
        observable_action_summary=["tool_invocation", "public_test", "candidate_freeze"],
        public_test_outcomes=[False, True],
        patch_metrics={
            "changed_file_count": 1,
            "added_lines": 2,
            "deleted_lines": 2,
            "public_tool_calls": 1,
        },
        outcome_kind="resolved_candidate",
        reward=_reward(),
        compile_passed=True,
        hidden_regression_passed=True,
        generalized_failure_labels=[],
    )
    base = {
        "schema_version": "1.0",
        "summary_id": "m10b-v0-training-summary",
        "split_manifest_hash": "b" * 64,
        "trajectory_dataset_hash": "c" * 64,
        "episodes": [episode.model_dump(mode="json")],
        "hidden_assets_included": False,
        "references_included": False,
        "private_reasoning_included": False,
        "heldout_assets_included": False,
    }
    return SanitizedTrainingSummary.model_validate({**base, "summary_hash": content_hash(base)})


def _memory():
    return build_memory_pack(
        {
            "principles": ["Confirm observable behavior before making a focused change."],
            "public_test_strategy": [
                "Run the smallest public check first and use its bounded feedback."
            ],
            "workspace_policy_reminders": [
                "Keep every edit within the declared editable workspace."
            ],
            "debugging_checklist": [
                "Check control priority, boundary conditions, reset behavior, and recovery."
            ],
            "patch_discipline": ["Prefer a minimal coherent change and review the resulting diff."],
        }
    )


def _version(*, evolved: bool = False, parent_hash: str | None = None):
    return build_agent_version(
        agent_version_id="codex-cli-agent-v1" if evolved else "codex-cli-agent-v0",
        status="frozen",
        parent_version_hash=(parent_hash or "1" * 64) if evolved else None,
        update_type="context_memory" if evolved else "none",
        executable_in_m10b=True,
        base_agent_id="codex-cli-agent",
        agent_descriptor_hash="2" * 64,
        model_id="gpt-5.4",
        reasoning_effort="xhigh",
        auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        runtime_identity_hash="3" * 64,
        tool_policy_hash="4" * 64,
        prompt_contract_hash="5" * 64,
        source_commit="53b0755715a876432ddcdface143632278ccddd3",
        package_hashes={"verigym": "6" * 64, "verigym-codex-cli": "7" * 64},
        image_hashes={"agent": "8" * 64, "verifier": "9" * 64},
        training_dataset_hash="a" * 64 if evolved else None,
        reward_schema_hash="b" * 64 if evolved else None,
        reward_profile_hash="c" * 64 if evolved else None,
        memory_builder_identity_hash="d" * 64 if evolved else None,
        memory_pack_hash=_memory().content_hash if evolved else None,
        model_weights_modified=False,
    )


def test_memory_pack_is_deterministic_bounded_and_code_free() -> None:
    memory = _memory()
    assert validate_memory_pack(memory) == memory
    assert memory.content_hash == _memory().content_hash
    assert [section.section for section in memory.sections] == [
        "principles",
        "public_test_strategy",
        "workspace_policy_reminders",
        "debugging_checklist",
        "patch_discipline",
    ]
    with pytest.raises(ValueError, match="rtl_code"):
        build_memory_pack(
            {
                **{section.section: section.items for section in memory.sections},
                "principles": ["Use module example; endmodule when done."],
            }
        )
    with pytest.raises(ValueError, match="repository_path"):
        build_memory_pack(
            {
                **{section.section: section.items for section in memory.sections},
                "principles": ["Edit repository/rtl/unit.sv."],
            }
        )
    with pytest.raises(ValueError, match="held-out-only"):
        validate_memory_pack(memory, heldout_only_tokens=("observable behavior",))


def test_memory_builder_prompt_excludes_identity_hashes_and_parser_fails_closed() -> None:
    summary = _summary()
    request = build_memory_builder_input(
        training_summary=summary,
        model_identity_hash="1" * 64,
        codex_identity_hash="2" * 64,
        auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        runtime_identity_hash="3" * 64,
        image_identity_hash="4" * 64,
        requested_model_id="gpt-5.4",
        reasoning_effort="xhigh",
        output_schema_hash="5" * 64,
    )
    assert validate_memory_builder_input(request) == request
    assert request.prompt_contract_hash == MEMORY_BUILDER_PROMPT_HASH
    prompt = render_memory_builder_prompt(request)
    assert summary.summary_hash not in prompt
    assert summary.trajectory_dataset_hash not in prompt
    assert "hidden_regression_passed" in prompt

    values = {section.section: section.items for section in _memory().sections}
    parsed = parse_memory_builder_output(json.dumps(values, sort_keys=True))
    assert parsed == _memory()
    with pytest.raises(ValueError, match="complete JSON"):
        parse_memory_builder_output(f"```json\n{json.dumps(values)}\n```")
    with pytest.raises(ValueError, match="unexpected shape"):
        parse_memory_builder_output(json.dumps({**values, "extra": ["unsafe"]}))
    with pytest.raises(ValueError, match="duplicate"):
        parse_memory_builder_output(
            '{"principles":["one"],"principles":["two"],'
            '"public_test_strategy":["x"],"workspace_policy_reminders":["x"],'
            '"debugging_checklist":["x"],"patch_discipline":["x"]}'
        )


def test_trajectory_content_policy_rejects_private_fields_secrets_and_host_paths() -> None:
    trajectory_exporter._safe_json(  # noqa: SLF001 - direct fail-closed policy fixture
        {"logical_workspace": "/workspace", "message": "Inspect repository/rtl safely."}
    )
    for payload in (
        {"chain_of_thought": "must not be exported"},
        {"message": "read /data/private/source"},
        {"message": "authorization: Bearer secret-shaped-value"},
        {"message": "read /etc/passwd"},
        {"message": "bad\u0000control"},
    ):
        with pytest.raises(ConfigurationError):
            trajectory_exporter._safe_json(payload)  # noqa: SLF001


def test_reward_outcomes_keep_candidate_policy_and_infrastructure_distinct() -> None:
    scorecard = load_model(
        Path("tests/fixtures/golden/v1/unresolved_normal/scorecard.json"),
        ScoreCard,
    )
    assert classify_outcome(scorecard) == "incorrect_policy_compliant_candidate"
    assert _trajectory_eligibility(classify_outcome(scorecard)).eligible

    policy = scorecard.model_copy(
        update={
            "failure": EpisodeFailure(
                kind="policy",
                category="workspace_policy",
                message="contained rejection",
                infrastructure=False,
            )
        }
    )
    assert classify_outcome(policy) == "contained_workspace_policy_failure"
    assert _trajectory_eligibility(classify_outcome(policy)).eligible

    infrastructure = scorecard.model_copy(
        update={
            "correctness": scorecard.correctness.model_copy(update={"infrastructure_error": True})
        }
    )
    assert classify_outcome(infrastructure) == "infrastructure_invalid"
    eligibility = _trajectory_eligibility(classify_outcome(infrastructure))
    assert not eligibility.eligible
    assert eligibility.reason == "infrastructure_invalid"


def test_agent_versions_and_run_assignments_are_immutable(tmp_path: Path) -> None:
    v0 = _version()
    v1 = _version(evolved=True, parent_hash=v0.version_hash)
    assert validate_agent_version(v0) == v0
    assert validate_agent_version(v1) == v1
    stable_fields = (
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
    assert all(getattr(v0, field) == getattr(v1, field) for field in stable_fields)
    assignments = build_run_version_assignments(
        [
            RunAgentVersionAssignment(
                run_id="run-b",
                agent_version_id=v1.agent_version_id,
                agent_version_hash=v1.version_hash,
            ),
            RunAgentVersionAssignment(
                run_id="run-a",
                agent_version_id=v0.agent_version_id,
                agent_version_hash=v0.version_hash,
            ),
        ]
    )
    assert [item.run_id for item in assignments.assignments] == ["run-a", "run-b"]
    assert validate_run_version_assignments(assignments) == assignments
    with pytest.raises(ValidationError, match="repeat"):
        assignments.model_copy(
            update={"assignments": [assignments.assignments[0]] * 2}
        ).model_validate(
            assignments.model_copy(
                update={"assignments": [assignments.assignments[0]] * 2}
            ).model_dump()
        )

    update_base = {
        "schema_version": "1.0",
        "update_id": "evolve-context-v0-to-v1",
        "update_type": "context_memory",
        "parent_version_hash": v0.version_hash,
        "result_version_hash": v1.version_hash,
        "training_summary_hash": "a" * 64,
        "memory_builder_input_hash": "b" * 64,
        "memory_builder_output_hash": "c" * 64,
        "memory_pack_hash": v1.memory_pack_hash,
        "process_ledger_hash": "d" * 64,
        "heldout_assets_loaded": False,
        "model_weights_modified": False,
    }
    update = AgentUpdateManifest.model_validate(
        {**update_base, "update_hash": content_hash(update_base)}
    )
    lineage = build_agent_lineage(parent=v0, result=v1, update=update)
    assert validate_agent_lineage(lineage) == lineage
    version_set = build_agent_version_set([v1, v0])
    assert [item.agent_version_id for item in version_set.versions] == [
        "codex-cli-agent-v0",
        "codex-cli-agent-v1",
    ]
    assert validate_agent_version_set(version_set) == version_set
    reports = EvolutionReportService().generate_lineage(
        lineage=lineage,
        memory=_memory(),
        output=tmp_path / "lineage-reports",
    )
    assert {path.name for path in reports.paths} == {
        "agent-lineage.json",
        "agent-lineage.md",
        "memory-pack-audit.json",
    }


def test_model_process_ledger_is_append_only_hash_chained_and_capped(tmp_path: Path) -> None:
    ledger = tmp_path / "model-process-ledger.jsonl"
    authorization = authorize_process(
        ledger,
        process_kind="implementation_probe",
        authorization_id="m10b-owner-contract-v1",
        run_or_build_id="probe-1",
        requested_model_id="gpt-5.4",
        reasoning_effort="xhigh",
        task_identity_hash="a" * 64,
        agent_version_hash="b" * 64,
    )
    assert authorization.record_phase == "authorized"
    assert not authorization.model_process_started
    with pytest.raises(ValueError, match="prior authorized"):
        authorize_process(
            ledger,
            process_kind="implementation_probe",
            authorization_id="m10b-owner-contract-v1",
            run_or_build_id="probe-2",
            requested_model_id="gpt-5.4",
            reasoning_effort="xhigh",
        )
    terminal = finish_process(
        ledger,
        authorization_record=authorization,
        terminal_outcome="evaluable_candidate_failure",
    )
    assert terminal.record_phase == "terminal"
    assert terminal.source_ledger_record_hash == authorization.record_hash
    manifest = seal_process_ledger(
        ledger,
        authorization_id="m10b-owner-contract-v1",
        complete=True,
    )
    assert validate_process_ledger_manifest(manifest) == manifest
    assert manifest.authorized_processes == manifest.started_processes == 1

    text = ledger.read_text(encoding="utf-8")
    ledger.write_text(text.replace('"ordinal":1', '"ordinal":2', 1), encoding="utf-8")
    with pytest.raises(ValueError, match="identity changed"):
        seal_process_ledger(
            ledger,
            authorization_id="m10b-owner-contract-v1",
            complete=True,
        )


def test_future_trainer_manifests_are_identity_bound_secret_free_and_non_executable() -> None:
    export = build_trainer_export_manifest(
        trajectory_dataset_hash="a" * 64,
        split_manifest_hash="b" * 64,
        reward_schema_hash="c" * 64,
        reward_profile_hash="d" * 64,
    )
    assert export.executable_artifacts_included is False
    assert export.secrets_included is False
    imported = build_agent_import_manifest(
        import_id="future-checkpoint-v2",
        update_type="external_checkpoint",
        parent_version_hash="a" * 64,
        trainer_identity_hash="b" * 64,
        training_dataset_hash="c" * 64,
        artifact_hash="d" * 64,
        compatible_runtime_hash="e" * 64,
        license="Apache-2.0",
        provenance="offline-example",
        loading_configuration={"format": "safetensors", "revision": "frozen"},
    )
    assert not imported.executable_in_m10b
    assert validate_agent_import_manifest(imported) == imported
    with pytest.raises(ValueError, match="secret-free"):
        validate_agent_import_manifest(
            build_agent_import_manifest(
                import_id="unsafe-import",
                update_type="external_adapter",
                parent_version_hash="a" * 64,
                trainer_identity_hash="b" * 64,
                training_dataset_hash="c" * 64,
                artifact_hash="d" * 64,
                compatible_runtime_hash="e" * 64,
                license="Apache-2.0",
                provenance="offline-example",
                loading_configuration={"api_key": "not-exportable"},
            )
        )


def _split_entry(root: Path) -> TaskSplitEntry:
    manifest = load_model(root / "task.yaml", RepositoryTaskManifest)
    return TaskSplitEntry(
        task_id=manifest.task.id,
        source_hash=manifest.source.repository_hash,
        task_hash=content_hash(manifest.task),
        license=manifest.source.license,
        attribution=manifest.source.attribution,
    )


def test_first_party_split_has_six_independent_tasks_and_no_contamination() -> None:
    base = Path("src/verigym/suites/repo_rtl")
    training = {
        _split_entry(root).task_id: root
        for root in sorted((base / "assets").iterdir())
        if (root / "task.yaml").is_file()
    }
    heldout = {
        _split_entry(root).task_id: root
        for root in sorted((base / "heldout_assets").iterdir())
        if (root / "task.yaml").is_file()
    }
    assert len(training) == len(heldout) == 3
    split = build_task_split(
        split_id="m10b-first-party-v1",
        training=[_split_entry(root) for root in training.values()],
        heldout=[_split_entry(root) for root in heldout.values()],
        heldout_assets_loaded_after_version_hash=_version(evolved=True).version_hash,
    )
    assert validate_task_split(split) == split
    scan = scan_contamination(
        split_manifest=split,
        training_roots=training,
        heldout_roots=heldout,
        memory_pack=_memory(),
    )
    assert validate_contamination_scan(scan) == scan
    assert scan.passed
    assert not scan.findings
    assert scan.hidden_assets_exported is False
    assert scan.reference_assets_exported is False


def test_contamination_scanner_rejects_copied_training_content(tmp_path: Path) -> None:
    source = Path("src/verigym/suites/repo_rtl/assets/counter_wrap")
    training_root = tmp_path / "training"
    heldout_root = tmp_path / "heldout"
    shutil.copytree(source, training_root)
    shutil.copytree(source, heldout_root)
    training = TaskSplitEntry(
        task_id="repo-rtl/training-copy",
        source_hash="1" * 64,
        task_hash="2" * 64,
        license="Apache-2.0",
        attribution="first-party fixture",
    )
    heldout = TaskSplitEntry(
        task_id="repo-rtl/heldout-copy",
        source_hash="3" * 64,
        task_hash="4" * 64,
        license="Apache-2.0",
        attribution="first-party fixture",
    )
    split = build_task_split(
        split_id="copied-content-rejection",
        training=[training],
        heldout=[heldout],
    )
    scan = scan_contamination(
        split_manifest=split,
        training_roots={training.task_id: training_root},
        heldout_roots={heldout.task_id: heldout_root},
    )
    assert not scan.passed
    assert {item.category for item in scan.findings} >= {
        "identical_file",
        "reference_fragment",
        "hidden_test_fragment",
        "issue_text_overlap",
    }


def test_heldout_suite_discovery_requires_a_frozen_context_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST", raising=False)
    assert len(list(RepositoryRtlSuite().discover())) == 3

    invalid = tmp_path / "v0.json"
    atomic_dump_json(invalid, _version())
    monkeypatch.setenv("VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST", str(invalid))
    with pytest.raises(Exception, match="context-memory"):
        RepositoryRtlSuite()

    valid = tmp_path / "v1.json"
    atomic_dump_json(valid, _version(evolved=True))
    monkeypatch.setenv("VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST", str(valid))
    suite = RepositoryRtlSuite()
    references = list(suite.discover())
    assert len(references) == 6
    assert sum("heldout" in reference.id for reference in references) == 3
    assert suite.validate_source().valid


@pytest.mark.requires_iverilog
def test_heldout_scripted_good_bad_and_policy_paths_are_evaluable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    grant = tmp_path / "v1.json"
    atomic_dump_json(grant, _version(evolved=True))
    monkeypatch.setenv("VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST", str(grant))
    service = VeriGym()
    heldout = [
        reference.id for reference in RepositoryRtlSuite().discover() if "heldout" in reference.id
    ]
    assert len(heldout) == 3
    for task_id in heldout:
        good = service.run(
            RunConfig(
                task_id=task_id,
                agent="repo-scripted-good",
                output=tmp_path / "good",
            )
        )
        assert good.scorecard.resolved
        assert good.manifest.repository_candidate is not None
        assert good.manifest.repository_candidate.patch.reapply_exact
        assert replay_run(good.run_dir, verify=True).reverified_resolved

        bad = service.run(
            RunConfig(
                task_id=task_id,
                agent="repo-scripted-bad",
                output=tmp_path / "bad",
            )
        )
        assert not bad.scorecard.resolved
        assert not bad.scorecard.correctness.infrastructure_error

    policy = service.run(
        RunConfig(
            task_id=heldout[0],
            agent="repo-scripted-policy-bad",
            output=tmp_path / "policy",
        )
    )
    assert not policy.scorecard.resolved
    assert policy.scorecard.failure is not None
    assert policy.scorecard.failure.kind == "policy"
    assert not policy.scorecard.failure.infrastructure


@pytest.mark.requires_iverilog
def test_trajectory_export_is_deterministic_recomputable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    v0 = _version()
    config = ExperimentConfig.model_validate(
        {
            "schema_version": "1.0",
            "name": "m10b trajectory acceptance",
            "suite": {
                "id": "repo-rtl",
                "tasks": {"include": ["counter-wrap"], "exclude": []},
            },
            "runs": {
                "mode": "agent",
                "seeds": [0],
                "samples_per_task": 1,
                "pass_k": [1],
            },
            "systems": [
                {
                    "id": "v0",
                    "agent": {
                        "id": "repo-scripted-good",
                        "options": {
                            "agent_version_id": v0.agent_version_id,
                            "agent_version_hash": v0.version_hash,
                        },
                    },
                }
            ],
            "runtime": {"id": "local"},
            "execution": {
                "max_workers": 1,
                "continue_on_infrastructure_error": True,
            },
            "output": {"root": tmp_path / "experiment"},
        }
    )
    planner = ExperimentPlanner()
    result = BatchRunner(planner=planner).run(planner.build(config))
    assert result.exit_code == 0
    inputs = load_report_inputs(result.experiment_dir)
    assert len(inputs.valid_runs) == 1
    run_id = inputs.valid_runs[0].manifest.run_id
    task_root = Path("src/verigym/suites/repo_rtl/assets/counter_wrap")
    split = build_task_split(
        split_id="m10b-training-export-v1",
        training=[_split_entry(task_root)],
        heldout=[],
    )
    arguments = {
        "split_manifest": split,
        "agent_versions": {v0.agent_version_id: v0},
        "run_agent_versions": {run_id: v0.agent_version_id},
        "source_commit": "53b0755715a876432ddcdface143632278ccddd3",
        "package_identities": {"verigym": "e" * 64},
    }
    first = tmp_path / "dataset-first"
    second = tmp_path / "dataset-second"
    first_manifest = TrajectoryExporter().export(
        result.experiment_dir,
        first,
        **arguments,
    )
    second_manifest = TrajectoryExporter().export(
        result.experiment_dir,
        second,
        **arguments,
    )
    assert first_manifest == second_manifest
    assert hash_directory(first) == hash_directory(second)
    assert validate_trajectory_dataset(first) == first_manifest
    assert replay_trajectory_dataset(first, result.experiment_dir) == first_manifest
    generated = EvolutionReportService().generate_dataset(
        first,
        tmp_path / "trajectory-reports",
    )
    assert all(path.is_file() for path in generated.paths)
    trajectory_text = (first / "trajectories.jsonl").read_text(encoding="utf-8")
    reward_text = (first / "rewards.jsonl").read_text(encoding="utf-8")
    assert "/data/" not in trajectory_text
    assert "/home/" not in trajectory_text
    assert "reference.patch" not in trajectory_text
    assert '"private_reasoning_exported":false' in trajectory_text
    assert '"hidden_assets_exported":false' in trajectory_text
    assert '"offline_recomputed":true' in reward_text
    assert '"scalar_profile_id":"repo_rtl_sparse_v1"' in reward_text

    trajectories = load_jsonl_models(first / "trajectories.jsonl", EpisodeTrajectory)
    summary = prepare_training_summary(
        trajectories,
        split_manifest_hash=split.manifest_hash,
        trajectory_dataset_hash=first_manifest.dataset_hash,
    )
    memory = _memory()
    v1, update = freeze_context_update(
        parent=v0,
        dataset=first_manifest,
        training_summary=summary,
        memory_pack=memory,
        memory_builder_identity_hash="1" * 64,
        memory_builder_input_hash="2" * 64,
        memory_builder_output_hash=content_hash(memory),
        process_ledger_hash="3" * 64,
    )
    replay_context_update(
        parent=v0,
        result=v1,
        update=update,
        dataset=first_manifest,
        training_summary=summary,
        memory_pack=memory,
    )
    assert v1.memory_pack_hash == memory.content_hash

    trajectories = first / "trajectories.jsonl"
    trajectories.write_text(trajectory_text.replace('"eligible":true', '"eligible":false', 1))
    with pytest.raises(Exception, match="checksum"):
        validate_trajectory_dataset(first)


@pytest.mark.requires_iverilog
def test_generic_batch_and_paired_evolving_report_cover_all_heldout_groups(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    v0 = _version()
    v1 = _version(evolved=True)
    grant = tmp_path / "v1.json"
    atomic_dump_json(grant, v1)
    monkeypatch.setenv("VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST", str(grant))
    memory = _memory()
    heldout_ids = [
        reference.id for reference in RepositoryRtlSuite().discover() if "heldout" in reference.id
    ]
    config = ExperimentConfig.model_validate(
        {
            "schema_version": "1.0",
            "name": "m10b fake heldout comparison",
            "suite": {
                "id": "repo-rtl",
                "tasks": {"include": heldout_ids, "exclude": []},
            },
            "runs": {
                "mode": "agent",
                "seeds": [0],
                "samples_per_task": 3,
                "pass_k": [1, 2, 3],
            },
            "systems": [
                {
                    "id": "v0",
                    "agent": {
                        "id": "repo-scripted-bad",
                        "options": {
                            "agent_version_id": v0.agent_version_id,
                            "agent_version_hash": v0.version_hash,
                        },
                    },
                },
                {
                    "id": "v1",
                    "agent": {
                        "id": "repo-scripted-good",
                        "options": {
                            "agent_version_id": v1.agent_version_id,
                            "agent_version_hash": v1.version_hash,
                            "memory_pack": memory.model_dump(mode="json"),
                        },
                    },
                },
            ],
            "runtime": {"id": "local"},
            "execution": {
                "max_workers": 1,
                "continue_on_infrastructure_error": True,
                "max_plan_items": 18,
                "plan_order_policy": "counterbalanced_systems_v1",
            },
            "output": {"root": tmp_path / "experiment"},
        }
    )
    planner = ExperimentPlanner()
    plan = planner.build(config)
    assert len(plan.items) == 18
    for offset in range(0, 6, 2):
        expected = ["v0", "v1"] if offset != 2 else ["v1", "v0"]
        assert [item.system.system_id for item in plan.items[offset : offset + 2]] == expected
    result = BatchRunner(planner=planner).run(plan)
    assert result.exit_code == 0

    heldout_roots = Path("src/verigym/suites/repo_rtl/heldout_assets")
    split = build_task_split(
        split_id="m10b-heldout-report-v1",
        training=[],
        heldout=[
            _split_entry(root)
            for root in sorted(heldout_roots.iterdir())
            if (root / "task.yaml").is_file()
        ],
        heldout_assets_loaded_after_version_hash=v1.version_hash,
    )
    report = build_evolving_evaluation(
        result.experiment_dir,
        split_manifest=split,
        baseline_version_id=v0.agent_version_id,
        evolved_version_id=v1.agent_version_id,
    )
    baseline, evolved = report.version_metrics
    assert (baseline.planned, baseline.evaluable, baseline.resolved) == (9, 9, 0)
    assert (evolved.planned, evolved.evaluable, evolved.resolved) == (9, 9, 9)
    assert baseline.macro_pass_at_1 == 0.0
    assert evolved.macro_pass_at_1 == 1.0
    assert report.paired_difference.macro_pass_at_3_delta == 1.0
    assert len(report.task_version_metrics) == 6
    assert report.establishes_general_improvement is False
    assert "does not establish general performance improvement" in report.required_interpretation
    generated = EvolutionReportService().generate_evaluation(
        report,
        tmp_path / "evaluation-reports",
    )
    assert all(path.is_file() for path in generated.paths)
