from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v138_fresh_explicit_scaffold as runner,
)
from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V71_MATRIX_TASK_IDS,
    load_v69_manifest,
    load_v92_official_matrix_manifest,
    load_v138_fresh_explicit_scaffold_manifest,
)


def _pr465() -> Any:
    manifest = load_v69_manifest(runner.v69.MANIFEST)
    return manifest.primary_tasks[0]


def test_v138_authorization_binds_manifest_runner_and_main_gate() -> None:
    authorization = (
        runner._REPOSITORY
        / "docs/audits/2026-09-04_deepseek-harness-v138-fresh-explicit-scaffold-authorization.md"
    ).read_text(encoding="utf-8")
    manifest_sha = hashlib.sha256(runner.MANIFEST.read_bytes()).hexdigest()
    runner_sha = hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()

    assert manifest_sha in authorization
    assert runner_sha in authorization
    assert "33861403120" in authorization


def test_v138_manifest_freezes_fresh_explicit_five_task_scaffold() -> None:
    manifest = load_v138_fresh_explicit_scaffold_manifest(runner.MANIFEST)

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v138-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v138-dind-socket"
    assert manifest.archive_import_timeout_seconds == 1800
    assert manifest.archive_import_explicit_endpoint_required is True
    assert manifest.archive_import_stage_diagnostic_required is True
    assert manifest.archive_import_raw_output_allowed is False
    assert manifest.archive_import_nonempty_output_hashing_allowed is False
    assert manifest.docker_cli_explicit_binding_required is True
    assert manifest.v132_volume_inspection_allowed is False
    assert manifest.v132_volume_mutation_allowed is False
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v140-official-matrix-v1"
    assert manifest.requires_independent_v133_audit is False
    assert manifest.requires_independent_v139_audit is True
    assert all(getattr(manifest, name) is False for name in runner.v94._closed_training_flags())


def test_v138_static_bindings_accept_only_immutable_evidence() -> None:
    source = inspect.getsource(runner._validate_static_bindings)
    assert "v132-dind-data" not in source
    assert "deepseek-harness-hwe-v132/data" not in source
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


def test_v138_configuration_routes_and_restores_v132() -> None:
    original = {name: getattr(runner.v132, name) for name in runner._V132_NAMES}

    with runner._v138_configuration():
        assert runner.v132.IDENTITY == runner.IDENTITY
        assert runner.v132.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v132._v132_materialize_task is runner._v138_materialize_task
        assert runner.v132._bounded_scan_and_lock is runner._bounded_scan_and_lock
        with runner._v132_baseline():
            assert runner.v132.IDENTITY != runner.IDENTITY
        assert runner.v132.IDENTITY == runner.IDENTITY

    assert all(getattr(runner.v132, name) is value for name, value in original.items())


@pytest.mark.parametrize("pr_number", [465, 1135, 1780, 2017, 2711])
def test_v138_scanner_uses_fresh_bounded_identity(
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
    assert policy.policy_id == "deepseek-harness-v138-bounded-command-scan-v1"
    assert policy.container_name == f"verigym-hwe-v138-command-scan-pr-{pr_number}"
    assert policy.owner_label == runner.IDENTITY
    assert policy.overall_timeout_seconds == 720
    assert result["scan_passed"] is True
    assert lock.security_scan_passed is True


def test_v138_explicit_archive_import_records_only_bounded_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _pr465()
    archive_root = tmp_path / "archives"
    archive = archive_root / task.archive_relpath
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"completed-local-archive")
    root = tmp_path / "evidence"
    root.mkdir()
    manifest = SimpleNamespace(
        nested_docker_host="unix:///explicit/docker.sock",
        archive_import_timeout_seconds=1800,
    )
    monkeypatch.setattr(runner, "_explicit_docker_environment", lambda _manifest: {})
    results = iter(
        (
            subprocess.CompletedProcess([], 0, b"loaded", b""),
            subprocess.CompletedProcess([], 0, f"{task.official_verifier_image}\n".encode(), b""),
            subprocess.CompletedProcess([], 1, b"", b"not-found"),
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, f"{task.official_verifier_image}\n".encode(), b""),
        )
    )
    monkeypatch.setattr(runner, "_docker_command", lambda *_args, **_kwargs: next(results))

    runner._explicit_archive_import(task, archive_root=archive_root, root=root, manifest=manifest)

    path = root / "archive-import-diagnostics/pr-465.json"
    raw = path.read_bytes()
    diagnostic = json.loads(raw)
    assert diagnostic["status"] == "passed"
    assert diagnostic["category"] == "archive_import_complete"
    assert diagnostic["explicit_endpoint_binding"] is True
    assert diagnostic["raw_output_persisted"] is False
    assert diagnostic["nonempty_output_hashed"] is False
    assert b"loaded" not in raw
    assert b"not-found" not in raw
    assert (
        runner.v94._canonical_hash(diagnostic, "diagnostic_hash") == diagnostic["diagnostic_hash"]
    )


def test_v138_archive_import_failure_is_stage_specific_and_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _pr465()
    archive_root = tmp_path / "archives"
    archive = archive_root / task.archive_relpath
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"completed-local-archive")
    root = tmp_path / "evidence"
    root.mkdir()
    manifest = SimpleNamespace(
        nested_docker_host="unix:///explicit/docker.sock",
        archive_import_timeout_seconds=1800,
    )
    monkeypatch.setattr(runner, "_explicit_docker_environment", lambda _manifest: {})
    monkeypatch.setattr(
        runner,
        "_docker_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 1, b"sensitive-stdout", b"sensitive-stderr"
        ),
    )

    with pytest.raises(ConfigurationError, match="archive import failed"):
        runner._explicit_archive_import(
            task, archive_root=archive_root, root=root, manifest=manifest
        )

    raw = (root / "archive-import-diagnostics/pr-465.json").read_bytes()
    diagnostic = json.loads(raw)
    assert diagnostic["category"] == "archive_load_exit_nonzero"
    assert diagnostic["stages"]["load"]["exit_code"] == 1
    assert b"sensitive-stdout" not in raw
    assert b"sensitive-stderr" not in raw


def test_v138_task_materialization_injects_import_and_fresh_tag(
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
        return {"task_id": bound.task_id, "task_receipt_hash": "old"}

    monkeypatch.setattr(runner, "_explicit_archive_import", explicit_import)
    monkeypatch.setattr(runner.v132, "_V127_BASE_MATERIALIZE_TASK", materialize)
    receipt = runner._v138_materialize_task(
        task,
        archive_root=tmp_path,
        root=tmp_path,
        command_tag_version="v97",
    )

    assert observed["tag"] == "v138"
    assert observed["import_task"] == task
    assert observed["import_kwargs"]["root"] == tmp_path
    assert runner.v69._load_completed_archive is original_loader
    assert receipt["archive_import_explicit_endpoint"] is True
    assert receipt["scanner_policy_id"] == "deepseek-harness-v138-bounded-command-scan-v1"
    assert runner.v94._canonical_hash(receipt, "task_receipt_hash") == receipt["task_receipt_hash"]


def test_v138_progress_maps_success_to_v139(tmp_path: Path) -> None:
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
    assert written["status"] == "completed_pending_independent_v139_audit"
    assert written["v132_volume_inspected"] is False
    assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]
