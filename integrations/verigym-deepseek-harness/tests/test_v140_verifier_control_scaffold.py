from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v140_verifier_control_scaffold as runner,
)
from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V71_MATRIX_TASK_IDS,
    load_v69_manifest,
    load_v92_official_matrix_manifest,
    load_v140_verifier_control_scaffold_manifest,
)


def _pr465() -> Any:
    manifest = load_v69_manifest(runner.v69.MANIFEST)
    return manifest.primary_tasks[0]


def _write_verifier_result(path: Path, *, status: str, category: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": "1.0",
        "status": status,
        "error_category": category,
        "exit_code": 0,
        "tests_passed": 1 if status == "passed" else 0,
        "tests_total": 1,
        "stdout_sha256": "0" * 64,
        "stderr_sha256": "0" * 64,
        "raw_output_persisted": False,
        "metadata": {
            "docker_control_stage": "complete",
            "docker_control_timeout_s": 300,
            "verifier_timeout_s": 900,
            "network_mode": "none",
            "container_removed": True,
            "output_persisted": False,
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")


def test_v140_authorization_binds_manifest_runner_and_main_gate() -> None:
    authorization = (
        runner._REPOSITORY
        / "docs/audits/2026-09-04_deepseek-harness-v140-verifier-control-scaffold-authorization.md"
    ).read_text(encoding="utf-8")
    manifest_sha = hashlib.sha256(runner.MANIFEST.read_bytes()).hexdigest()
    runner_sha = hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()

    assert manifest_sha in authorization
    assert runner_sha in authorization
    assert "33866159895" in authorization


def test_v140_manifest_freezes_fresh_control_bound_five_task_scaffold() -> None:
    manifest = load_v140_verifier_control_scaffold_manifest(runner.MANIFEST)

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v140-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v140-dind-socket"
    assert manifest.verifier_docker_control_timeout_seconds == 300
    assert manifest.official_verifier_test_timeout_seconds == 900
    assert manifest.verifier_control_stage_metadata_required is True
    assert manifest.verifier_control_raw_output_allowed is False
    assert manifest.v138_volume_inspection_allowed is False
    assert manifest.v138_volume_mutation_allowed is False
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v142-official-matrix-v1"
    assert manifest.requires_independent_v141_audit is True
    assert all(getattr(manifest, name) is False for name in runner.v94._closed_training_flags())


def test_v140_static_bindings_accept_only_immutable_evidence() -> None:
    source = inspect.getsource(runner._validate_static_bindings)
    assert "v138-dind-data" not in source
    assert "deepseek-harness-hwe-v138/data" not in source
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


def test_v140_configuration_routes_and_restores_v138() -> None:
    original = {name: getattr(runner.v138, name) for name in runner._V138_NAMES}

    with runner._v140_configuration():
        assert runner.v138.IDENTITY == runner.IDENTITY
        assert runner.v138.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v138._v138_materialize_task is runner._v140_materialize_task
        assert runner.v138._bounded_scan_and_lock is runner._bounded_scan_and_lock
        with runner._v138_baseline():
            assert runner.v138.IDENTITY != runner.IDENTITY
        assert runner.v138.IDENTITY == runner.IDENTITY

    assert all(getattr(runner.v138, name) is value for name, value in original.items())


@pytest.mark.parametrize("pr_number", [465, 1135, 1780, 2017, 2711])
def test_v140_scanner_uses_fresh_bounded_identity(
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

    monkeypatch.setattr(runner.v132, "_V69_SCAN_AND_LOCK", scan)
    result, lock = runner._bounded_scan_and_lock(
        identity_lock_path=tmp_path / f"pr-{pr_number}.json"
    )

    policy = observed["runtime_policy"]
    assert policy.policy_id == "deepseek-harness-v140-bounded-command-scan-v1"
    assert policy.container_name == f"verigym-hwe-v140-command-scan-pr-{pr_number}"
    assert policy.owner_label == runner.IDENTITY
    assert policy.overall_timeout_seconds == 720
    assert result["scan_passed"] is True
    assert lock.security_scan_passed is True


def test_v140_verifier_control_diagnostic_is_separate_and_content_free(tmp_path: Path) -> None:
    task = _pr465()
    qualification = tmp_path / "qualification/pr-465"
    _write_verifier_result(
        qualification / "base-verifier/run_hidden_regression/result.json",
        status="failed",
        category="test_failed",
    )
    _write_verifier_result(
        qualification / "reference-verifier/run_hidden_regression/result.json",
        status="passed",
        category="success",
    )

    diagnostic = runner._verifier_control_diagnostic(tmp_path, task)
    raw = (tmp_path / "verifier-control-diagnostics/pr-465.json").read_bytes()

    assert diagnostic["status"] == "passed"
    assert diagnostic["control_bound_widened_only"] is True
    assert diagnostic["official_verifier_semantics_unchanged"] is True
    assert diagnostic["nonempty_output_hashed"] is False
    assert [row["docker_control_timeout_seconds"] for row in diagnostic["verifier_runs"]] == [
        300,
        300,
    ]
    assert [
        row["official_verifier_test_timeout_seconds"] for row in diagnostic["verifier_runs"]
    ] == [900, 900]
    assert b"stdout_sha256" not in raw
    assert b"stderr_sha256" not in raw
    assert (
        runner.v94._canonical_hash(diagnostic, "diagnostic_hash") == diagnostic["diagnostic_hash"]
    )


def test_v140_verifier_control_diagnostic_rejects_cleanup_failure(tmp_path: Path) -> None:
    result = tmp_path / "qualification/pr-465/base-verifier/run_hidden_regression/result.json"
    _write_verifier_result(result, status="failed", category="test_failed")
    value = json.loads(result.read_text(encoding="utf-8"))
    value["metadata"]["container_removed"] = False
    result.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="control result"):
        runner._verifier_control_row(result, role="base", expected_status="failed")


def test_v140_task_materialization_injects_fresh_import_and_control_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _pr465()
    observed: dict[str, Any] = {}
    original_loader = runner.v69._load_completed_archive
    monkeypatch.setattr(runner, "_load_composed_manifest", lambda _path: SimpleNamespace())

    def explicit_import(bound: Any, **kwargs: Any) -> None:
        observed["import_task"] = bound
        observed["import_kwargs"] = kwargs

    def materialize(bound: Any, **kwargs: Any) -> dict[str, Any]:
        observed["tag"] = kwargs["command_tag_version"]
        runner.v69._load_completed_archive(bound, archive_root=kwargs["archive_root"])
        qualification = tmp_path / "qualification/pr-465"
        _write_verifier_result(
            qualification / "base-verifier/run_hidden_regression/result.json",
            status="failed",
            category="test_failed",
        )
        _write_verifier_result(
            qualification / "reference-verifier/run_hidden_regression/result.json",
            status="passed",
            category="success",
        )
        return {"task_id": bound.task_id, "task_receipt_hash": "old"}

    monkeypatch.setattr(runner.v138, "_explicit_archive_import", explicit_import)
    monkeypatch.setattr(runner.v132, "_V127_BASE_MATERIALIZE_TASK", materialize)
    receipt = runner._v140_materialize_task(
        task,
        archive_root=tmp_path,
        root=tmp_path,
        command_tag_version="v97",
    )

    assert observed["tag"] == "v140"
    assert observed["import_task"] == task
    assert observed["import_kwargs"]["root"] == tmp_path
    assert runner.v69._load_completed_archive is original_loader
    assert receipt["archive_import_explicit_endpoint"] is True
    assert receipt["scanner_policy_id"] == "deepseek-harness-v140-bounded-command-scan-v1"
    assert receipt["verifier_docker_control_timeout_seconds"] == 300
    assert receipt["official_verifier_test_timeout_seconds"] == 900
    assert runner.v94._canonical_hash(receipt, "task_receipt_hash") == receipt["task_receipt_hash"]


def test_v140_progress_maps_success_to_v141(tmp_path: Path) -> None:
    status = next(iter(runner.v127._SUCCESS_STATUS_NAMES))
    progress = {
        "schema_version": "1.0",
        "format_id": "predecessor",
        "identity": runner.IDENTITY,
        "status": status,
        "provider_calls": 0,
    }

    runner._write_progress(tmp_path, progress)

    written = runner.v94._load_json(tmp_path / "execution-scaffold-progress.json")
    assert written["status"] == "completed_pending_independent_v141_audit"
    assert written["v138_volume_inspected"] is False
    assert written["verifier_docker_control_timeout_seconds"] == 300
    assert written["official_verifier_test_timeout_seconds"] == 900
    assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]


def test_v140_materializer_passes_control_timeout_to_smoke() -> None:
    source = inspect.getsource(runner.v69._materialize_task)

    assert "docker_control_timeout_s=docker_control_timeout_s" in source
    assert "run_zero_model_smoke" in source
