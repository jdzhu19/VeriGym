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
    materialize_hwe_deepseek_harness_v142_cleanup_control_scaffold as runner,
)
from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V71_MATRIX_TASK_IDS,
    load_v69_manifest,
    load_v92_official_matrix_manifest,
    load_v142_cleanup_control_scaffold_manifest,
)


def _pr465() -> Any:
    manifest = load_v69_manifest(runner.v69.MANIFEST)
    return manifest.primary_tasks[0]


def _cleanup_manifest(**changes: Any) -> SimpleNamespace:
    values = {
        "socket_cleanup_control_timeout_seconds": 300,
        "socket_cleanup_stage_metadata_required": True,
        "socket_cleanup_raw_output_allowed": False,
        "dind_socket_volume": "verigym-deepseek-harness-v142-dind-socket",
        "dind_socket_backing": str(runner.DIND_SOCKET_BACKING),
        "dind_image_id": "sha256:" + "1" * 64,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_v142_authorization_binds_manifest_runner_and_main_gate() -> None:
    authorization = (
        runner._REPOSITORY
        / "docs/audits/2026-09-05_deepseek-harness-v142-cleanup-control-scaffold-authorization.md"
    ).read_text(encoding="utf-8")
    manifest_sha = hashlib.sha256(runner.MANIFEST.read_bytes()).hexdigest()
    runner_sha = hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()

    assert manifest_sha in authorization
    assert runner_sha in authorization
    assert "33896629910" in authorization


def test_v142_manifest_freezes_fresh_cleanup_bound_five_task_scaffold() -> None:
    manifest = load_v142_cleanup_control_scaffold_manifest(runner.MANIFEST)

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v142-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v142-dind-socket"
    assert manifest.verifier_docker_control_timeout_seconds == 300
    assert manifest.official_verifier_test_timeout_seconds == 900
    assert manifest.socket_cleanup_control_timeout_seconds == 300
    assert manifest.socket_cleanup_stage_metadata_required is True
    assert manifest.socket_cleanup_raw_output_allowed is False
    assert manifest.v140_volume_inspection_allowed is False
    assert manifest.v140_volume_mutation_allowed is False
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v144-official-matrix-v1"
    assert manifest.requires_independent_v143_audit is True
    assert all(getattr(manifest, name) is False for name in runner.v94._closed_training_flags())


def test_v142_static_bindings_accept_only_immutable_evidence() -> None:
    source = inspect.getsource(runner._validate_static_bindings)
    assert "v140-dind-data" not in source
    assert "deepseek-harness-hwe-v140/data" not in source
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


def test_v142_configuration_routes_and_restores_v140() -> None:
    original = {name: getattr(runner.v140, name) for name in runner._V140_NAMES}

    with runner._v142_configuration():
        assert runner.v140.IDENTITY == runner.IDENTITY
        assert runner.v140.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v140._v140_materialize_task is runner._v142_materialize_task
        assert runner.v140._clean_socket_volume is runner._clean_socket_volume
        with runner._v140_baseline():
            assert runner.v140.IDENTITY != runner.IDENTITY
        assert runner.v140.IDENTITY == runner.IDENTITY

    assert all(getattr(runner.v140, name) is value for name, value in original.items())


@pytest.mark.parametrize("pr_number", [465, 1135, 1780, 2017, 2711])
def test_v142_scanner_uses_fresh_bounded_identity(
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
    assert policy.policy_id == "deepseek-harness-v142-bounded-command-scan-v1"
    assert policy.container_name == f"verigym-hwe-v142-command-scan-pr-{pr_number}"
    assert policy.owner_label == runner.IDENTITY
    assert policy.overall_timeout_seconds == 720
    assert result["scan_passed"] is True
    assert lock.security_scan_passed is True


def test_v142_cleanup_uses_exact_300_second_control_bound_and_content_free_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backing = tmp_path / "socket"
    backing.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", backing)
    monkeypatch.setattr(runner.dind, "_bind_backed_volume", lambda *args, **kwargs: backing)
    calls: list[tuple[list[str], int]] = []

    def run(command: list[str], *, timeout_s: int) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, timeout_s))
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(runner.dind, "_run", run)
    receipt = runner._clean_socket_volume(
        _cleanup_manifest(dind_socket_backing=str(backing)), root=tmp_path
    )

    assert [timeout for _command, timeout in calls] == [300, 300]
    assert calls[0][0][0:2] == ["docker", "run"]
    assert "none" in calls[0][0]
    assert calls[1][0] == [
        "docker",
        "volume",
        "rm",
        "verigym-deepseek-harness-v142-dind-socket",
    ]
    assert receipt["socket_volume_removed"] is True
    assert receipt["socket_cleanup_control_timeout_seconds"] == 300
    diagnostic_path = tmp_path / "socket-cleanup-diagnostics/attempt-1.json"
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["status"] == "passed"
    assert diagnostic["raw_output_persisted"] is False
    assert diagnostic["nonempty_output_hashed"] is False
    assert "stdout_bytes" in diagnostic["stages"]["cleanup_helper"]
    assert "stderr_bytes" in diagnostic["stages"]["cleanup_helper"]
    assert "stdout_sha256" not in diagnostic["stages"]["cleanup_helper"]
    assert "stderr_sha256" not in diagnostic["stages"]["cleanup_helper"]


def test_v142_cleanup_timeout_fails_closed_and_bounds_exact_helper_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backing = tmp_path / "socket"
    backing.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", backing)
    monkeypatch.setattr(runner.dind, "_bind_backed_volume", lambda *args, **kwargs: backing)
    calls: list[tuple[list[str], int]] = []

    def run(command: list[str], *, timeout_s: int) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, timeout_s))
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, timeout_s, output=b"secret")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(runner.dind, "_run", run)
    with pytest.raises(ConfigurationError, match="helper timed out"):
        runner._clean_socket_volume(
            _cleanup_manifest(dind_socket_backing=str(backing)), root=tmp_path
        )

    assert [timeout for _command, timeout in calls] == [300, 300]
    assert calls[1][0][0:3] == ["docker", "rm", "--force"]
    raw = (tmp_path / "socket-cleanup-diagnostics/attempt-1.json").read_bytes()
    assert b"secret" not in raw
    diagnostic = json.loads(raw)
    assert diagnostic["status"] == "failed"
    assert diagnostic["category"] == "cleanup_helper_timeout"
    assert diagnostic["raw_exception_persisted"] is False


def test_v142_cleanup_volume_removal_failure_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backing = tmp_path / "socket"
    backing.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", backing)
    monkeypatch.setattr(runner.dind, "_bind_backed_volume", lambda *args, **kwargs: backing)
    calls = 0

    def run(command: list[str], *, timeout_s: int) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            command,
            0 if calls == 1 else 1,
            stdout=b"",
            stderr=b"daemon detail",
        )

    monkeypatch.setattr(runner.dind, "_run", run)
    with pytest.raises(ConfigurationError, match="volume removal failed"):
        runner._clean_socket_volume(
            _cleanup_manifest(dind_socket_backing=str(backing)), root=tmp_path
        )

    raw = (tmp_path / "socket-cleanup-diagnostics/attempt-1.json").read_bytes()
    assert b"daemon detail" not in raw
    diagnostic = json.loads(raw)
    assert diagnostic["category"] == "socket_volume_remove_failed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("socket_cleanup_control_timeout_seconds", 60),
        ("socket_cleanup_stage_metadata_required", False),
        ("socket_cleanup_raw_output_allowed", True),
    ],
)
def test_v142_cleanup_rejects_changed_policy(
    field: str,
    value: object,
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="policy changed"):
        runner._clean_socket_volume(_cleanup_manifest(**{field: value}), root=tmp_path)


def test_v142_task_materialization_uses_fresh_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _pr465()
    observed: dict[str, Any] = {}
    original_loader = runner.v69._load_completed_archive
    monkeypatch.setattr(runner, "_load_composed_manifest", lambda _path: SimpleNamespace())

    def explicit_import(bound: Any, **kwargs: Any) -> None:
        observed["import_task"] = bound

    def materialize(bound: Any, **kwargs: Any) -> dict[str, Any]:
        observed["tag"] = kwargs["command_tag_version"]
        runner.v69._load_completed_archive(bound, archive_root=kwargs["archive_root"])
        return {"task_id": bound.task_id, "task_receipt_hash": "old"}

    monkeypatch.setattr(runner.v138, "_explicit_archive_import", explicit_import)
    monkeypatch.setattr(runner.v132, "_V127_BASE_MATERIALIZE_TASK", materialize)
    monkeypatch.setattr(
        runner.v140,
        "_verifier_control_diagnostic",
        lambda _root, _task: {"diagnostic_hash": "0" * 64},
    )
    receipt = runner._v142_materialize_task(
        task,
        archive_root=tmp_path,
        root=tmp_path,
        command_tag_version="v97",
    )

    assert observed["tag"] == "v142"
    assert observed["import_task"] == task
    assert runner.v69._load_completed_archive is original_loader
    assert receipt["scanner_policy_id"] == "deepseek-harness-v142-bounded-command-scan-v1"


def test_v142_progress_maps_success_to_v143(tmp_path: Path) -> None:
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
    assert written["status"] == "completed_pending_independent_v143_audit"
    assert written["v140_volume_inspected"] is False
    assert written["socket_cleanup_control_timeout_seconds"] == 300
    assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]


def test_v142_static_source_never_targets_the_v140_volume() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")

    assert "verigym-deepseek-harness-v140-dind-data" not in source
    assert "/data2/jiadongzhu/docker/deepseek-harness-hwe-v140/data" not in source
    assert "LocalRuntime" not in source
