from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import (  # noqa: E402
    launch_hwe_deepseek_harness_v148_cleanup_identity_scaffold as launcher,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v148_cleanup_identity_scaffold as runner,
)
from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V71_MATRIX_TASK_IDS,
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    load_v69_manifest,
    load_v92_official_matrix_manifest,
    load_v148_cleanup_identity_scaffold_manifest,
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


def test_v148_authorization_binds_manifest_runner_and_main_gate() -> None:
    authorization = (
        runner._REPOSITORY
        / (
            "docs/audits/2026-09-05_deepseek-harness-v148-cleanup-identity-"
            "scaffold-authorization.md"
        )
    ).read_text(encoding="utf-8")
    manifest_sha = hashlib.sha256(runner.MANIFEST.read_bytes()).hexdigest()
    runner_sha = hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()
    launcher_sha = hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest()

    assert manifest_sha in authorization
    assert runner_sha in authorization
    assert launcher_sha in authorization
    assert "33919008896" in authorization


def test_v148_manifest_freezes_fresh_probe_bound_five_task_scaffold() -> None:
    manifest = load_v148_cleanup_identity_scaffold_manifest(runner.MANIFEST)

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v148-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v148-dind-socket"
    assert manifest.command_image_probe_control_timeout_seconds == 300
    assert manifest.command_image_probe_stage_metadata_required is True
    assert manifest.command_image_probe_raw_output_allowed is False
    assert manifest.command_image_probe_nonempty_output_hashing_allowed is False
    assert manifest.v142_volume_inspection_allowed is False
    assert manifest.v142_volume_mutation_allowed is False
    assert tuple(manifest.provider_environment_names) == ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
    assert manifest.provider_environment_name_count == 12
    assert manifest.provider_environment_values_read_allowed is False
    assert manifest.child_boundary_verified_before_resource_creation is True
    assert manifest.cleanup_identity_binding_source == "exact-current-manifest-v1"
    assert manifest.cleanup_predecessor_literal_allowed is False
    assert manifest.cleanup_exact_volume_required is True
    assert manifest.cleanup_exact_owner_required is True
    assert manifest.cleanup_exact_backing_required is True
    assert manifest.v146_volume_inspection_allowed is False
    assert manifest.v146_volume_mutation_allowed is False
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v150-official-matrix-v1"
    assert manifest.requires_independent_v145_audit is False
    assert manifest.requires_independent_v147_audit is False
    assert manifest.requires_independent_v149_audit is True
    assert all(getattr(manifest, name) is False for name in runner.v94._closed_training_flags())


def test_v148_static_bindings_accept_only_immutable_evidence() -> None:
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


def test_v148_configuration_routes_and_restores_v142() -> None:
    original = {name: getattr(runner.v142, name) for name in runner._V142_NAMES}

    with runner._v148_configuration():
        assert runner.v142.IDENTITY == runner.IDENTITY
        assert runner.v142.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v142._v142_materialize_task is runner._v148_materialize_task
        assert runner.v142._runtime_prepare_preflight is runner._runtime_prepare_preflight
        with runner._v142_baseline():
            assert runner.v142.IDENTITY != runner.IDENTITY
        assert runner.v142.IDENTITY == runner.IDENTITY

    assert all(getattr(runner.v142, name) is value for name, value in original.items())


@pytest.mark.parametrize("pr_number", [465, 1135, 1780, 2017, 2711])
def test_v148_scanner_uses_fresh_bounded_identity(
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
    assert policy.policy_id == "deepseek-harness-v148-bounded-command-scan-v1"
    assert policy.container_name == f"verigym-hwe-v148-command-scan-pr-{pr_number}"
    assert policy.owner_label == runner.IDENTITY
    assert policy.overall_timeout_seconds == 720
    assert result["scan_passed"] is True
    assert lock.security_scan_passed is True


def test_v148_runtime_preflight_applies_300_second_probe_bound_and_writes_pass(
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


def test_v148_runtime_preflight_failure_keeps_only_allowlisted_probe_details(
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
def test_v148_runtime_preflight_rejects_changed_policy(field: str, value: object) -> None:
    with pytest.raises(ConfigurationError, match="policy changed"):
        runner._runtime_prepare_preflight(
            _probe_manifest(**{field: value}),
            locks={},
            dind_name="unused",
        )


def test_v148_task_materialization_uses_fresh_tag(
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
    receipt = runner._v148_materialize_task(
        task,
        archive_root=tmp_path,
        root=tmp_path,
        command_tag_version="v97",
    )

    assert observed["tag"] == "v148"
    assert observed["import_task"] == task
    assert runner.v69._load_completed_archive is original_loader
    assert receipt["scanner_policy_id"] == "deepseek-harness-v148-bounded-command-scan-v1"


def test_v148_progress_maps_success_to_v149(tmp_path: Path) -> None:
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
    assert written["status"] == "completed_pending_independent_v149_audit"
    assert written["v142_volume_inspected"] is False
    assert written["v146_volume_inspected"] is False
    assert written["command_image_probe_control_timeout_seconds"] == 300
    assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]


def _cleanup_manifest(socket_backing: Path, **changes: Any) -> SimpleNamespace:
    values = {
        "socket_cleanup_control_timeout_seconds": 300,
        "socket_cleanup_stage_metadata_required": True,
        "socket_cleanup_raw_output_allowed": False,
        "cleanup_identity_binding_source": "exact-current-manifest-v1",
        "cleanup_predecessor_literal_allowed": False,
        "cleanup_exact_volume_required": True,
        "cleanup_exact_owner_required": True,
        "cleanup_exact_backing_required": True,
        "v146_volume_inspection_allowed": False,
        "v146_volume_mutation_allowed": False,
        "dind_socket_volume": "verigym-deepseek-harness-v148-dind-socket",
        "dind_socket_backing": str(socket_backing),
        "dind_owner": runner.IDENTITY,
        "dind_image_id": "sha256:" + "1" * 64,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_v148_cleanup_binds_and_removes_exact_current_manifest_volume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_backing = tmp_path / "socket"
    socket_backing.mkdir(mode=0o700)
    root = tmp_path / "evidence"
    root.mkdir(mode=0o700)
    observed: dict[str, Any] = {}
    commands: list[list[str]] = []

    def bind(volume: str, *, owner: str, role: str, backing: Path) -> None:
        observed.update(volume=volume, owner=owner, role=role, backing=backing)

    def run(command: list[str], *, timeout_s: int) -> Any:
        commands.append(command)
        assert timeout_s == 300
        return runner.subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_backing)
    monkeypatch.setattr(runner.dind, "_bind_backed_volume", bind)
    monkeypatch.setattr(runner.dind, "_run", run)

    receipt = runner._clean_socket_volume(_cleanup_manifest(socket_backing), root=root)

    assert observed == {
        "volume": "verigym-deepseek-harness-v148-dind-socket",
        "owner": runner.IDENTITY,
        "role": "socket",
        "backing": socket_backing,
    }
    assert commands[0][commands[0].index("--network") + 1] == "none"
    assert "verigym-deepseek-harness-v148-dind-socket:/verigym-socket:rw" in commands[0]
    assert commands[1] == [
        "docker",
        "volume",
        "rm",
        "verigym-deepseek-harness-v148-dind-socket",
    ]
    assert receipt["socket_volume_removed"] is True
    assert receipt["cleanup_exact_owner"] == runner.IDENTITY
    assert receipt["v146_volume_inspected"] is False
    assert receipt["v146_volume_mutated"] is False


def test_v148_cleanup_rejects_any_noncurrent_volume_before_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_backing = tmp_path / "socket"
    socket_backing.mkdir(mode=0o700)
    called = False

    def bind(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_backing)
    monkeypatch.setattr(runner.dind, "_bind_backed_volume", bind)

    with pytest.raises(ConfigurationError, match="cleanup identity policy changed"):
        runner._clean_socket_volume(
            _cleanup_manifest(socket_backing, dind_socket_volume="unexpected"),
            root=tmp_path,
        )

    assert called is False


def test_v148_static_source_uses_only_current_manifest_cleanup_identity() -> None:
    source = inspect.getsource(runner)

    assert "verigym-deepseek-harness-v142-dind-data" not in source
    assert "verigym-deepseek-harness-v142-dind-socket" not in source
    assert "verigym-deepseek-harness-v146-dind-data" not in source
    assert "verigym-deepseek-harness-v146-dind-socket" not in source
    assert "/data2/jiadongzhu/docker/deepseek-harness-hwe-v142/data" not in source
    assert '_V142_BASELINE["_clean_socket_volume"]' not in source
    assert "LocalRuntime" not in source


class _GuardedEnvironment(Mapping[str, str]):
    def __init__(self, blocked: set[str]) -> None:
        self._blocked = blocked
        self._names = [*sorted(blocked), "PATH"]

    def __getitem__(self, name: str) -> str:
        if name in self._blocked:
            raise AssertionError("blocked provider value was read")
        if name == "PATH":
            return "/usr/bin"
        raise KeyError(name)

    def __iter__(self) -> Iterator[str]:
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._names)


def test_v148_launcher_derives_exact_boundary_without_reading_blocked_values() -> None:
    blocked = set(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES) | {"DOCKER_CONTEXT", "DOCKER_HOST"}
    child = launcher._sanitized_child_environment(_GuardedEnvironment(blocked))

    assert set(launcher._blocked_child_environment_names()) == blocked
    assert not blocked.intersection(child)
    assert child["PATH"] == "/usr/bin"
    assert child[runner.OPT_IN_ENV] == "1"
    assert child[runner.CHILD_BOUNDARY_ENV] == "1"


def test_v148_runner_requires_verified_clean_child_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clean = {runner.CHILD_BOUNDARY_ENV: "1"}
    monkeypatch.setattr(runner.os, "environ", clean)
    runner._require_v148_environment_boundary()

    clean[ZERO_PROVIDER_CONFIGURATION_ENV_NAMES[0]] = "unread"
    with pytest.raises(ConfigurationError, match="contaminated"):
        runner._require_v148_environment_boundary()


def test_v148_runner_rejects_missing_child_boundary_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.os, "environ", {})
    with pytest.raises(ConfigurationError, match="verified provider-free child"):
        runner._require_v148_environment_boundary()
