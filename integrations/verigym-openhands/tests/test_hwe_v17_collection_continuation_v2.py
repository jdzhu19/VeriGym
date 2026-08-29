from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.hwe_v17_collection_continuation_contract import (
    OPENHANDS_V17_CONTINUATION_CAMPAIGN_ID,
    OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
    OPENHANDS_V17_FROZEN_AGENT_VERSION_HASH,
    OPENHANDS_V17_RECOVERY_TASK,
    build_v17_continuation_agent_version,
    evaluate_v17_continuation_gate,
    load_v17_continuation_contract,
    validate_v17_recovery_root,
)

from verigym_openhands.hwe_v17_collection import (
    OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
    OPENHANDS_V17_FORMAL_TRAINING_ORDER,
    OPENHANDS_V17_FORMAL_VALIDATION_ORDER,
    OPENHANDS_V17_IMPORTED_TRAINING_TASKS,
)


def _root() -> Path:
    return Path(__file__).parents[3]


def _contract_path() -> Path:
    return (
        _root()
        / "configs"
        / "training"
        / "qwen35_hwe_openhands_v17_collection_continuation_v2.json"
    )


def _attempt(task_id: str, *, imported: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": task_id,
        "role": "training",
        "infrastructure_valid": True,
        "security_scan_passed": True,
        "truncation_applied": False,
        "ordinary_verifier_resolved": True,
        "fresh_exact_trajectory": True,
        "exact_64k_eligible": True,
    }
    if imported is not None:
        value[imported] = True
    return value


def test_continuation_contract_imports_pr2282_without_reexecution() -> None:
    contract = load_v17_continuation_contract(_contract_path())

    assert contract["contract_hash"] == (
        "df47b0ca1e3900ad1a82d359bfd1711d35cd4b30ae4fc1b88d966b855513b8f4"
    )
    assert contract["recovery_import"]["task_id"] == OPENHANDS_V17_RECOVERY_TASK
    assert contract["recovery_import"]["provider_episode_retry_allowed"] is False
    assert contract["collection"]["recovery_task_reexecution_allowed"] is False
    assert contract["collection"]["provider_training_attempt_order"] == list(
        OPENHANDS_V17_FORMAL_TRAINING_ORDER[1:]
    )
    assert contract["collection"]["provider_validation_attempt_order"] == list(
        OPENHANDS_V17_FORMAL_VALIDATION_ORDER
    )
    assert contract["frozen_agent"] == {
        "agent_version_id": OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
        "agent_version_hash": OPENHANDS_V17_FROZEN_AGENT_VERSION_HASH,
        "source_commit": OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
        "agent_behavior_changed": False,
    }
    assert contract["heldout_task_ids_loaded"] == []


def test_continuation_gate_resumes_at_pr2468() -> None:
    attempts = [
        *(
            _attempt(task_id, imported="imported_canary")
            for task_id in OPENHANDS_V17_IMPORTED_TRAINING_TASKS
        ),
        _attempt(OPENHANDS_V17_RECOVERY_TASK, imported="imported_recovery"),
    ]

    gate = evaluate_v17_continuation_gate(attempts)

    assert gate.possible is True
    assert gate.next_role == "training"
    assert gate.training_pass_count == 3
    attempts.append(_attempt(OPENHANDS_V17_FORMAL_TRAINING_ORDER[1]))
    assert evaluate_v17_continuation_gate(attempts).training_pass_count == 4


def test_continuation_rejects_agent_identity_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import hwe_v17_collection_continuation_contract as continuation

    monkeypatch.setattr(
        continuation._v1,
        "build_v17_collection_agent_version",
        lambda **kwargs: SimpleNamespace(version_hash="changed"),
    )

    with pytest.raises(ValueError, match="frozen agent identity changed"):
        build_v17_continuation_agent_version(image_locks={})


def test_recovery_root_fails_closed_before_reading_unbound_evidence(tmp_path: Path) -> None:
    contract = load_v17_continuation_contract(_contract_path())

    with pytest.raises(ValueError, match="evidence changed"):
        validate_v17_recovery_root(tmp_path, contract)


def test_recovery_root_rejects_a_symlink(tmp_path: Path) -> None:
    contract = load_v17_continuation_contract(_contract_path())
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "recovery"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="recovery root is unsafe"):
        validate_v17_recovery_root(link, contract)


def test_fresh_materialization_exports_transcript_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import collect_cva6_hwe_openhands_v17 as runner

    trajectory = {"transcript_hash": "a" * 64}
    record = {"record_hash": "b" * 64, "token_count": 17}
    monkeypatch.setattr(
        runner,
        "_json",
        lambda path: (
            {"reproducibility": {"candidate_hash": "c", "verifier_hash": "d"}}
            if path.name == "scorecard.json"
            else {}
        ),
    )
    monkeypatch.setattr(runner, "validate_openhands_training_trajectory", lambda value: trajectory)
    monkeypatch.setattr(runner, "materialize_openhands_decisions", lambda *args, **kwargs: [record])
    monkeypatch.setattr(
        runner,
        "dry_run_decision_record_v4",
        lambda *args, **kwargs: {"overlength": False, "token_count": 17},
    )

    attempt, records, _dry_runs = runner._materialize_fresh_attempt(
        attempt={"ordinary_verifier_resolved": True, "run_hash": "e" * 64},
        episode={"episode_id": "training-pr2282-s487", "task_id": OPENHANDS_V17_RECOVERY_TASK},
        runs=Path("/unused"),
        entry=SimpleNamespace(task_hash="f" * 64, source_hash="0" * 64),
        contract={"contract_hash": "1" * 64},
        tokenizer=object(),
    )

    assert attempt["transcript_hash"] == trajectory["transcript_hash"]
    assert records == [record]


def test_trajectory_record_pair_is_cleaned_if_manifest_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import collect_cva6_hwe_openhands_v17 as runner

    path = tmp_path / "records.jsonl"
    monkeypatch.setattr(
        runner,
        "atomic_dump_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("manifest failed")),
    )
    with pytest.raises(RuntimeError, match="manifest failed"):
        runner._write_trajectory_records(
            path,
            [{"record_hash": "a" * 64, "token_count": 17}],
            attempt={
                "episode_id": "training-pr2282-s487",
                "role": "training",
                "task_id": OPENHANDS_V17_RECOVERY_TASK,
                "transcript_hash": "b" * 64,
                "run_hash": "c" * 64,
            },
        )

    assert not path.exists()
    assert not path.with_suffix(".manifest.json").exists()


def test_campaign_persistence_is_inside_the_fail_closed_boundary() -> None:
    from scripts import collect_cva6_hwe_openhands_v17 as runner

    source = inspect.getsource(runner.collect)
    boundary = source.index('failure_stage = "episode_execution"')
    handler = source.index("except Exception as exc:", boundary)

    assert boundary < source.index("_write_trajectory_records(", boundary) < handler
    assert boundary < source.index("_write_progress(", boundary) < handler
    assert boundary < source.index("_write_gate(", boundary) < handler
    assert OPENHANDS_V17_CONTINUATION_CAMPAIGN_ID.endswith("-v2")


def test_continuation_persists_the_import_gate_before_docker_or_provider_calls() -> None:
    from scripts import collect_cva6_hwe_openhands_v17_continuation_v2 as runner

    source = inspect.getsource(runner.collect)
    initialization = source.index('failure_stage = "initial_directory_persistence"')
    preflight = source.index("_zero_call_preflight(locks)")
    provider = source.index("service = _v1._service()")

    assert initialization < source.index("_write_gate(root, attempts)", initialization) < preflight
    assert preflight < provider


def test_formal_runner_exposes_the_provider_scan_to_the_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import collect_cva6_hwe_openhands_v17 as formal
    from scripts import collect_cva6_hwe_openhands_v17_continuation_v2 as continuation

    expected = {"passed": True, "provider_value_hit_count": 0}
    monkeypatch.setattr(formal._canary_runner, "_scan_provider_values", lambda root: expected)

    assert formal._scan_provider_values(tmp_path) == expected
    assert inspect.getsource(continuation.collect).count("_v1._scan_provider_values(") == 2


def test_fail_closed_stop_overwrites_a_stale_continue_gate(tmp_path: Path) -> None:
    from scripts import collect_cva6_hwe_openhands_v17 as formal
    from scripts import collect_cva6_hwe_openhands_v17_continuation_v2 as continuation

    for name, runner in (("formal", formal), ("continuation", continuation)):
        root = tmp_path / name
        root.mkdir()
        runner._write_gate(root, [])
        previous = json.loads((root / "data-gate.json").read_bytes())
        runner._stop(root, {}, [], "episode_execution:ConfigurationError")
        gate = json.loads((root / "data-gate.json").read_bytes())

        assert gate["satisfied"] is False
        assert gate["possible"] is False
        assert gate["next_role"] is None
        assert gate["reason"] == "campaign_stopped_fail_closed"
        assert gate["capacity_reason"] == previous["reason"]
        assert gate["stop_reason"] == "episode_execution:ConfigurationError"
