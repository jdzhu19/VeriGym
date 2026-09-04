from __future__ import annotations

import argparse
import contextlib
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V71_MATRIX_TASK_IDS,
    load_v92_official_matrix_manifest,
    load_v127_readiness_gated_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v127_readiness_gated_scaffold as runner,
)


def _completed(
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _start_arguments(tmp_path: Path) -> dict[str, Any]:
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    return {
        "name": "v127-daemon",
        "image_id": "sha256:" + "a" * 64,
        "socket_volume": "v127-socket",
        "data_volume": "v127-data",
        "source_volume": None,
        "scratch_volume": None,
        "empty_home": empty_home,
        "same_path_mounts": [],
        "startup_timeout_s": 120,
    }


def test_v127_manifest_freezes_readiness_schedule_and_closed_policy() -> None:
    manifest = load_v127_readiness_gated_scaffold_manifest(runner.MANIFEST)

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.v125_readiness_poll_count == 16
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v127-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v127-dind-socket"
    assert manifest.readiness_timeout_seconds == 120
    assert manifest.readiness_command_timeout_seconds == 5
    assert manifest.readiness_probe_policy == ("explicit-three-field-exact-monotonic-deadline-v1")
    assert manifest.json_info_readiness_allowed is False
    assert manifest.fixed_poll_count_cap_allowed is False
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.requires_independent_v128_audit is True
    assert all(getattr(manifest, name) is False for name in runner.v94._closed_training_flags())


def test_v127_start_waits_beyond_legacy_poll_caps_for_exact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], int]] = []
    results = [
        _completed(b"container-id\n"),
        *[_completed(stderr=b"daemon secret transient") for _ in range(25)],
        _completed(b"23.0.6\tvfs\trunc\n"),
        _completed(b"/var/lib/docker\n"),
        _completed(f"{runner.os.getgid()}\n".encode()),
    ]

    def run(arguments: list[str], *, timeout_s: int) -> subprocess.CompletedProcess[bytes]:
        calls.append((arguments, timeout_s))
        return results.pop(0)

    monkeypatch.setattr(runner.dind, "_run", run)
    monkeypatch.setattr(runner.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    metadata = runner._start_dind(**_start_arguments(tmp_path))

    readiness = [
        item
        for item in calls
        if item[0][0:5] == ["docker", "exec", "v127-daemon", "docker", "info"]
        and item[0][-1] == "{{.ServerVersion}}\t{{.Driver}}\t{{.DefaultRuntime}}"
    ]
    assert len(readiness) == 26
    assert all(timeout == 5 for _, timeout in readiness)
    assert calls[0][1] == 60
    assert calls[0][0].count("run") == 1
    assert all("{{json .}}" not in arguments for arguments, _ in calls)
    assert metadata == {
        "ServerVersion": "23.0.6",
        "Driver": "vfs",
        "DefaultRuntime": "runc",
        "DockerRootDir": "/var/lib/docker",
        "v127_readiness_poll_count": 26,
        "v127_readiness_probe_policy": ("explicit-three-field-exact-monotonic-deadline-v1"),
    }


def test_v127_start_rejects_a_clean_complete_mismatch_without_leaking_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    secret = "not-the-frozen-secret-version"
    results = [_completed(b"container-id\n"), _completed(f"{secret}\tvfs\trunc\n".encode())]

    def run(arguments: list[str], *, timeout_s: int) -> subprocess.CompletedProcess[bytes]:
        del timeout_s
        calls.append(arguments)
        return results.pop(0)

    monkeypatch.setattr(runner.dind, "_run", run)
    monkeypatch.setattr(runner.time, "monotonic", lambda: 0.0)

    with pytest.raises(RuntimeError) as caught:
        runner._start_dind(**_start_arguments(tmp_path))

    assert "identity differs from policy" in str(caught.value)
    assert secret not in str(caught.value)
    assert len(calls) == 2


def test_v127_start_uses_the_monotonic_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    results = [_completed(b"container-id\n"), _completed(returncode=1)]
    moments = iter((0.0, 0.0, 120.0, 121.0))

    def run(arguments: list[str], *, timeout_s: int) -> subprocess.CompletedProcess[bytes]:
        del timeout_s
        calls.append(arguments)
        return results.pop(0)

    monkeypatch.setattr(runner.dind, "_run", run)
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(moments))

    with pytest.raises(RuntimeError, match="did not become ready"):
        runner._start_dind(**_start_arguments(tmp_path))

    assert len(calls) == 2


def test_v127_configuration_restores_runner_and_dind_bindings() -> None:
    original = {name: getattr(runner.v118, name) for name in runner._V118_CONFIGURATION_NAMES}
    original_start = runner.dind._start_dind
    original_owner = runner.dind._DIND_OWNER

    with runner._v127_configuration():
        assert runner.v118.IDENTITY == runner.IDENTITY
        assert runner.v118.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v118._runtime_prepare_preflight is runner._runtime_prepare_preflight
        assert runner.dind._start_dind is runner._start_dind
        assert runner.dind._DIND_OWNER == runner.IDENTITY
        with runner._v118_predecessor_configuration():
            assert runner.v118.IDENTITY != runner.IDENTITY
        assert runner.v118.IDENTITY == runner.IDENTITY

    assert all(getattr(runner.v118, name) is value for name, value in original.items())
    assert runner.dind._start_dind is original_start
    assert runner.dind._DIND_OWNER == original_owner


def test_v127_identity_reaches_the_frozen_base_scaffold() -> None:
    v115 = runner.v118.v115
    v112 = v115.v112
    v109 = v112.v109
    v106 = v109.v106
    v103 = v106.v103
    v100 = v103.v100
    v97 = v100.v97

    with contextlib.ExitStack() as stack:
        stack.enter_context(runner._v127_configuration())
        stack.enter_context(runner.v118._v118_configuration())
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
        assert runner.dind._start_dind is runner._start_dind
        assert runner.dind._DIND_OWNER == runner.IDENTITY


def test_v127_progress_writer_maps_every_historical_success_to_v128(tmp_path: Path) -> None:
    for index, status in enumerate(sorted(runner._SUCCESS_STATUS_NAMES)):
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
        assert written["status"] == "completed_pending_independent_v128_audit"
        assert written["readiness_timeout_seconds"] == 120
        assert written["readiness_command_timeout_seconds"] == 5
        assert written["predecessor_volumes_inspected"] is False
        assert written["predecessor_volumes_mutated"] is False
        assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]


def test_v127_command_image_tag_is_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}

    def materialize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return {"tag": kwargs["command_tag_version"]}

    monkeypatch.setattr(runner, "_V69_MATERIALIZE_TASK", materialize)
    result = runner._v127_materialize_task("task", command_tag_version="v97")

    assert result == {"tag": "v127"}
    assert observed["kwargs"]["command_tag_version"] == "v127"
    with pytest.raises(ConfigurationError, match="tag version"):
        runner._v127_materialize_task("task", command_tag_version="v118")


def test_v127_static_bindings_use_only_audited_files_not_predecessor_volumes() -> None:
    source = inspect.getsource(runner._validate_static_bindings)
    assert "v118-dind-data" not in source
    assert "deepseek-harness-hwe-v118/data" not in source
    manifest = runner._load_composed_manifest(runner.MANIFEST)
    v92_manifest = load_v92_official_matrix_manifest(
        runner.v118.v115.v112.v109.v106.v103.v100.v97.V92_MANIFEST
    )
    report = runner.v94._load_json(runner.v118.v115.v112.v109.v106.v103.v100.v97.V92_REPORT)

    runner._validate_static_bindings(
        manifest,
        v92_manifest,
        report,
        v92_manifest_path=runner.v118.v115.v112.v109.v106.v103.v100.v97.V92_MANIFEST,
        v92_report_path=runner.v118.v115.v112.v109.v106.v103.v100.v97.V92_REPORT,
    )


def test_v127_contract_binds_readiness_and_independent_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = SimpleNamespace(
        v118_manifest_hash="v118",
        v119_audit_commit="v119",
        v125_manifest_hash="v125-manifest",
        v125_report_hash="v125-report",
        v125_probe_hash="v125-probe",
        v125_readiness_poll_count=16,
        v126_audit_commit="v126",
        v126_post_merge_main_run_id=33830266674,
        readiness_probe_policy="explicit-three-field-exact-monotonic-deadline-v1",
        readiness_timeout_seconds=120,
        readiness_command_timeout_seconds=5,
    )
    monkeypatch.setattr(
        runner,
        "_V118_SCAFFOLD_CONTRACT",
        lambda _manifest, **_kwargs: {
            "contract_hash": "old",
            "v118_tasks_materialized_from_completed_local_archives": True,
            "requires_independent_v119_audit": True,
        },
    )

    contract = runner._scaffold_contract(manifest)

    assert contract["identity"] == runner.IDENTITY
    assert contract["v125_readiness_poll_count"] == 16
    assert contract["json_info_readiness_used"] is False
    assert contract["fixed_poll_count_cap_used"] is False
    assert contract["predecessor_volumes_inspected"] is False
    assert contract["predecessor_volumes_mutated"] is False
    assert contract["requires_independent_v128_audit"] is True
    assert runner.v94._canonical_hash(contract, "contract_hash") == contract["contract_hash"]


def test_v127_refuses_provider_environment_before_creating_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    arguments = argparse.Namespace(post_merge_main_run_id=33830266674)

    with runner._v127_configuration(), pytest.raises(ConfigurationError, match="provider"):
        runner.v118.materialize(arguments)
