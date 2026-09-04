from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v144_command_probe_control_scaffold as runner,
)
from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V71_MATRIX_TASK_IDS,
    load_v69_manifest,
    load_v92_official_matrix_manifest,
    load_v144_command_probe_control_scaffold_manifest,
)
from verigym.runtimes.docker.errors import DockerImageError


def _pr465() -> Any:
    return load_v69_manifest(runner.v69.MANIFEST).primary_tasks[0]


def _probe_manifest(**changes: Any) -> SimpleNamespace:
    values = {
        "command_image_probe_control_timeout_seconds": 300,
        "command_image_probe_stage_metadata_required": True,
        "command_image_probe_raw_output_allowed": False,
        "command_image_probe_nonempty_output_hashing_allowed": False,
        "runtime_prepare_task_count": 1,
        "schedule": [SimpleNamespace(task_id="task-1", pr_number=465)],
    }
    values.update(changes)
    return SimpleNamespace(**values)


class _CommandConfig:
    identity_probe_timeout_s = 60

    def model_copy(self, *, update: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(**update)


class _RuntimeConfig:
    command_image = _CommandConfig()

    def model_copy(self, *, update: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(**update)


def test_v144_authorization_binds_manifest_runner_and_main_gate() -> None:
    authorization = (
        runner._REPOSITORY
        / (
            "docs/audits/2026-09-05_deepseek-harness-v144-command-probe-control-"
            "scaffold-authorization.md"
        )
    ).read_text(encoding="utf-8")
    manifest_sha = hashlib.sha256(runner.MANIFEST.read_bytes()).hexdigest()
    runner_sha = hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()

    assert manifest_sha in authorization
    assert runner_sha in authorization
    assert "33907426320" in authorization


def test_v144_manifest_freezes_fresh_probe_bound_five_task_scaffold() -> None:
    manifest = load_v144_command_probe_control_scaffold_manifest(runner.MANIFEST)

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v144-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v144-dind-socket"
    assert manifest.command_image_probe_control_timeout_seconds == 300
    assert manifest.command_image_probe_stage_metadata_required is True
    assert manifest.command_image_probe_raw_output_allowed is False
    assert manifest.command_image_probe_nonempty_output_hashing_allowed is False
    assert manifest.v142_volume_inspection_allowed is False
    assert manifest.v142_volume_mutation_allowed is False
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v146-official-matrix-v1"
    assert manifest.requires_independent_v145_audit is True
    assert all(getattr(manifest, name) is False for name in runner.v94._closed_training_flags())


def test_v144_static_bindings_accept_only_immutable_evidence() -> None:
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


def test_v144_configuration_routes_and_restores_v142() -> None:
    original = {name: getattr(runner.v142, name) for name in runner._V142_NAMES}

    with runner._v144_configuration():
        assert runner.v142.IDENTITY == runner.IDENTITY
        assert runner.v142.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v142._v142_materialize_task is runner._v144_materialize_task
        assert runner.v142._runtime_prepare_preflight is runner._runtime_prepare_preflight
        with runner._v142_baseline():
            assert runner.v142.IDENTITY != runner.IDENTITY
        assert runner.v142.IDENTITY == runner.IDENTITY

    assert all(getattr(runner.v142, name) is value for name, value in original.items())


@pytest.mark.parametrize("pr_number", [465, 1135, 1780, 2017, 2711])
def test_v144_scanner_uses_fresh_bounded_identity(
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
    assert policy.policy_id == "deepseek-harness-v144-bounded-command-scan-v1"
    assert policy.container_name == f"verigym-hwe-v144-command-scan-pr-{pr_number}"
    assert policy.owner_label == runner.IDENTITY
    assert policy.overall_timeout_seconds == 720
    assert result["scan_passed"] is True
    assert lock.security_scan_passed is True


def test_v144_runtime_preflight_applies_300_second_probe_bound_and_writes_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "OUTPUT_ROOT", tmp_path)
    original = runner.v94.v92._runtime_config
    observed: list[int] = []
    monkeypatch.setattr(runner.v94.v92, "_runtime_config", lambda _lock: _RuntimeConfig())

    def preflight(manifest: Any, *, locks: Any, dind_name: str) -> dict[str, Any]:
        del dind_name
        for binding in manifest.schedule:
            config = runner.v94.v92._runtime_config(locks[binding.task_id])
            observed.append(config.command_image.identity_probe_timeout_s)
        return {"status": "passed", "completed_task_ids": ["task-1"], "receipt_hash": "old"}

    monkeypatch.setitem(runner._V142_BASELINE, "_runtime_prepare_preflight", preflight)
    receipt = runner._runtime_prepare_preflight(
        _probe_manifest(),
        locks={"task-1": SimpleNamespace(task_id="task-1")},
        dind_name="unused",
    )

    assert observed == [300]
    assert runner.v94.v92._runtime_config is not original
    diagnostic = json.loads(
        (tmp_path / "command-image-probe-diagnostics/attempt-1.json").read_text()
    )
    assert diagnostic["status"] == "passed"
    assert diagnostic["completed_task_ids"] == ["task-1"]
    assert diagnostic["raw_output_persisted"] is False
    assert diagnostic["nonempty_output_hashed"] is False
    assert receipt["command_image_probe_control_timeout_seconds"] == 300


def test_v144_runtime_preflight_failure_keeps_only_allowlisted_probe_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(runner.v94.v92, "_runtime_config", lambda _lock: _RuntimeConfig())

    def preflight(manifest: Any, *, locks: Any, dind_name: str) -> dict[str, Any]:
        del dind_name
        binding = manifest.schedule[0]
        runner.v94.v92._runtime_config(locks[binding.task_id])
        raise DockerImageError(
            "secret raw exception",
            subreason="command_image_health_failed",
            details={
                "probe_protocol": "combined_image_identity_v1",
                "failure_reason": "timeout",
                "failure_origin": "candidate_process",
                "timed_out": True,
                "oom_killed": False,
                "output_truncated": False,
                "exit_code": None,
                "untrusted_detail": "secret raw detail",
            },
        )

    monkeypatch.setitem(runner._V142_BASELINE, "_runtime_prepare_preflight", preflight)
    with pytest.raises(DockerImageError):
        runner._runtime_prepare_preflight(
            _probe_manifest(),
            locks={"task-1": SimpleNamespace(task_id="task-1")},
            dind_name="unused",
        )

    raw = (tmp_path / "command-image-probe-diagnostics/attempt-1.json").read_bytes()
    assert b"secret" not in raw
    diagnostic = json.loads(raw)
    assert diagnostic["status"] == "failed"
    assert diagnostic["category"] == "command_image_health_failed"
    assert diagnostic["probe_details"] == {
        "probe_protocol": "combined_image_identity_v1",
        "failure_reason": "timeout",
        "failure_origin": "candidate_process",
        "timed_out": True,
        "oom_killed": False,
        "output_truncated": False,
        "exit_code": None,
    }
    assert diagnostic["raw_exception_persisted"] is False
    assert diagnostic["raw_exception_hashed"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command_image_probe_control_timeout_seconds", 60),
        ("command_image_probe_stage_metadata_required", False),
        ("command_image_probe_raw_output_allowed", True),
        ("command_image_probe_nonempty_output_hashing_allowed", True),
    ],
)
def test_v144_runtime_preflight_rejects_changed_policy(field: str, value: object) -> None:
    with pytest.raises(ConfigurationError, match="policy changed"):
        runner._runtime_prepare_preflight(
            _probe_manifest(**{field: value}),
            locks={},
            dind_name="unused",
        )


def test_v144_task_materialization_uses_fresh_tag(
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
    receipt = runner._v144_materialize_task(
        task,
        archive_root=tmp_path,
        root=tmp_path,
        command_tag_version="v97",
    )

    assert observed["tag"] == "v144"
    assert observed["import_task"] == task
    assert runner.v69._load_completed_archive is original_loader
    assert receipt["scanner_policy_id"] == "deepseek-harness-v144-bounded-command-scan-v1"


def test_v144_progress_maps_success_to_v145(tmp_path: Path) -> None:
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
    assert written["status"] == "completed_pending_independent_v145_audit"
    assert written["v142_volume_inspected"] is False
    assert written["command_image_probe_control_timeout_seconds"] == 300
    assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]


def test_v144_static_source_never_targets_the_v142_data_volume() -> None:
    source = inspect.getsource(runner)

    assert "verigym-deepseek-harness-v142-dind-data" not in source
    assert "/data2/jiadongzhu/docker/deepseek-harness-hwe-v142/data" not in source
    assert "LocalRuntime" not in source
