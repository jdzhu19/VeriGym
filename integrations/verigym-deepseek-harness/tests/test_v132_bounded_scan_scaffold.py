from __future__ import annotations

import argparse
import contextlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V71_MATRIX_TASK_IDS,
    load_v92_official_matrix_manifest,
    load_v132_bounded_scan_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v132_bounded_scan_scaffold as runner,
)


def test_v132_manifest_freezes_five_tasks_bounded_scanner_and_closed_policy() -> None:
    manifest = load_v132_bounded_scan_scaffold_manifest(runner.MANIFEST)

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v132-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v132-dind-socket"
    assert manifest.scanner_policy_source == "exact-audited-v130-policy"
    assert manifest.scanner_create_timeout_seconds == 300
    assert manifest.scanner_inspect_timeout_seconds == 60
    assert manifest.scanner_start_timeout_seconds == 180
    assert manifest.scanner_remove_timeout_seconds == 120
    assert manifest.scanner_overall_timeout_seconds == 720
    assert manifest.scanner_all_five_tasks_required is True
    assert manifest.scanner_deterministic_owner_cleanup_required is True
    assert manifest.scanner_nonempty_output_hashing_allowed is False
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.requires_independent_v133_audit is True
    assert all(getattr(manifest, name) is False for name in runner.v94._closed_training_flags())


def test_v132_static_bindings_use_immutable_files_not_predecessor_volumes() -> None:
    source = inspect.getsource(runner._validate_static_bindings)
    assert "v127-dind-data" not in source
    assert "deepseek-harness-hwe-v127/data" not in source
    manifest = runner._load_composed_manifest(runner.MANIFEST)
    v97 = runner.v127.v118.v115.v112.v109.v106.v103.v100.v97
    v92_manifest = load_v92_official_matrix_manifest(v97.V92_MANIFEST)
    v92_report = runner.v94._load_json(v97.V92_REPORT)

    runner._validate_static_bindings(
        manifest,
        v92_manifest,
        v92_report,
        v92_manifest_path=v97.V92_MANIFEST,
        v92_report_path=v97.V92_REPORT,
    )

    evidence = runner._load_v130_evidence(manifest)
    assert evidence["report"]["command_image_scan_passed"] is True
    assert evidence["report"]["cleanup_confirmed"] is False
    assert evidence["late_cleanup"]["status"] == "passed"


def test_v132_configuration_routes_identity_paths_and_scanner() -> None:
    original = {name: getattr(runner.v127, name) for name in runner._V127_CONFIGURATION_NAMES}
    original_scan = runner.v69.scan_and_lock

    with runner._v132_configuration():
        assert runner.v127.IDENTITY == runner.IDENTITY
        assert runner.v127.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v127._v127_materialize_task is runner._v132_materialize_task
        assert runner.v69.scan_and_lock is runner._bounded_scan_and_lock
        with runner._v127_predecessor_configuration():
            assert runner.v127.IDENTITY != runner.IDENTITY
        assert runner.v127.IDENTITY == runner.IDENTITY

    assert all(getattr(runner.v127, name) is value for name, value in original.items())
    assert runner.v69.scan_and_lock is original_scan


def test_v132_identity_reaches_the_frozen_base_scaffold() -> None:
    v115 = runner.v127.v118.v115
    v112 = v115.v112
    v109 = v112.v109
    v106 = v109.v106
    v103 = v106.v103
    v100 = v103.v100
    v97 = v100.v97

    with contextlib.ExitStack() as stack:
        stack.enter_context(runner._v132_configuration())
        stack.enter_context(runner.v127._v127_configuration())
        stack.enter_context(runner.v127.v118._v118_configuration())
        stack.enter_context(v115._v115_configuration())
        stack.enter_context(v112._v112_configuration())
        stack.enter_context(v109._v109_configuration())
        stack.enter_context(v106._v106_configuration())
        stack.enter_context(v103._v103_configuration())
        stack.enter_context(v100._v100_base_configuration())
        stack.enter_context(v97._v97_base_configuration())
        assert runner.v94.IDENTITY == runner.IDENTITY
        assert runner.v94.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v94._materialize_tasks is runner._materialize_tasks
        assert runner.v69.scan_and_lock is runner._bounded_scan_and_lock
        assert runner.dind._DIND_OWNER == runner.IDENTITY


@pytest.mark.parametrize("pr_number", [465, 1135, 1780, 2017, 2711])
def test_v132_scanner_injects_the_exact_policy_for_each_task(
    pr_number: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def scan(**kwargs: Any) -> tuple[dict[str, Any], SimpleNamespace]:
        observed.update(kwargs)
        policy = kwargs["runtime_policy"]
        return (
            {
                "scan_passed": True,
                "diagnostic": {
                    "status": "passed",
                    "runtime_policy": policy.as_dict(),
                    "temporary_container_removed": True,
                    "temporary_workspace_removed": True,
                    "nonempty_output_hashed": False,
                },
            },
            SimpleNamespace(security_scan_passed=True),
        )

    monkeypatch.setattr(runner, "_V69_SCAN_AND_LOCK", scan)
    result, lock = runner._bounded_scan_and_lock(
        identity_lock_path=tmp_path / f"pr-{pr_number}.json"
    )

    policy = observed["runtime_policy"]
    assert policy.policy_id == "deepseek-harness-v132-bounded-command-scan-v1"
    assert policy.container_name == f"verigym-hwe-v132-command-scan-pr-{pr_number}"
    assert policy.owner_label == runner.IDENTITY
    assert policy.create_timeout_seconds == 300
    assert policy.inspect_timeout_seconds == 60
    assert policy.start_timeout_seconds == 180
    assert policy.remove_timeout_seconds == 120
    assert policy.overall_timeout_seconds == 720
    assert result["scan_passed"] is True
    assert lock.security_scan_passed is True


def test_v132_scanner_refuses_external_policy_and_unknown_task(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="externally supplied"):
        runner._bounded_scan_and_lock(
            identity_lock_path=tmp_path / "pr-465.json",
            runtime_policy=object(),
        )
    with pytest.raises(ConfigurationError, match="identity"):
        runner._bounded_scan_and_lock(identity_lock_path=tmp_path / "pr-48.json")


def test_v132_command_image_tag_and_receipt_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def materialize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return {"task_id": "task", "task_receipt_hash": "old"}

    monkeypatch.setattr(runner, "_V127_BASE_MATERIALIZE_TASK", materialize)
    receipt = runner._v132_materialize_task("task", command_tag_version="v97")

    assert observed["kwargs"]["command_tag_version"] == "v132"
    assert receipt["scanner_create_timeout_seconds"] == 300
    assert receipt["scanner_overall_timeout_seconds"] == 720
    assert receipt["v130_scan_qualified"] is True
    assert runner.v94._canonical_hash(receipt, "task_receipt_hash") == receipt["task_receipt_hash"]
    with pytest.raises(ConfigurationError, match="tag version"):
        runner._v132_materialize_task("task", command_tag_version="v127")


def test_v132_progress_maps_every_historical_success_to_v133(tmp_path: Path) -> None:
    for index, status in enumerate(sorted(runner.v127._SUCCESS_STATUS_NAMES)):
        root = tmp_path / str(index)
        root.mkdir()
        progress = {
            "schema_version": "1.0",
            "format_id": "predecessor",
            "identity": runner.IDENTITY,
            "status": status,
            "provider_calls": 0,
        }
        runner._write_progress(root, progress)
        written = runner.v94._load_json(root / "execution-scaffold-progress.json")
        assert written["status"] == "completed_pending_independent_v133_audit"
        assert written["scanner_create_timeout_seconds"] == 300
        assert written["predecessor_volumes_inspected"] is False
        assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]


def test_v132_contract_binds_scanner_and_independent_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = SimpleNamespace(
        v127_manifest_hash="v127",
        v128_audit_merge="v128",
        v130_manifest_hash="v130",
        v130_security_scan_id="scan",
        v130_late_cleanup_hash="cleanup",
        v131_audit_merge="v131",
        v131_post_merge_main_run_id=33846866494,
        scanner_policy_id="deepseek-harness-v132-bounded-command-scan-v1",
        scanner_create_timeout_seconds=300,
        scanner_inspect_timeout_seconds=60,
        scanner_start_timeout_seconds=180,
        scanner_remove_timeout_seconds=120,
        scanner_overall_timeout_seconds=720,
    )
    monkeypatch.setattr(
        runner,
        "_V127_SCAFFOLD_CONTRACT",
        lambda _manifest, **_kwargs: {
            "contract_hash": "old",
            "requires_independent_v128_audit": True,
        },
    )

    contract = runner._scaffold_contract(manifest)

    assert contract["identity"] == runner.IDENTITY
    assert contract["scanner_all_five_tasks_passed"] is True
    assert contract["requires_independent_v133_audit"] is True
    assert contract["predecessor_volumes_inspected"] is False
    assert runner.v94._canonical_hash(contract, "contract_hash") == contract["contract_hash"]


def test_v132_refuses_provider_environment_before_creating_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    arguments = argparse.Namespace(post_merge_main_run_id=33846866494)

    with runner._v132_configuration(), pytest.raises(ConfigurationError, match="provider"):
        runner.v127.materialize(arguments)
