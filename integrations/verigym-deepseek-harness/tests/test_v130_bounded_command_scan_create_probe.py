from __future__ import annotations

import argparse
import inspect
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    load_v130_bounded_command_scan_probe_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    run_hwe_deepseek_harness_v130_bounded_command_scan_create_probe as runner,
)


def _completed(
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_v130_manifest_and_runner_freeze_the_bounded_create_probe() -> None:
    manifest = load_v130_bounded_command_scan_probe_manifest(runner.MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.task_id == "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465"
    assert manifest.archive_root == str(runner.ARCHIVE_ROOT)
    assert manifest.runtime_scratch_root == str(runner.RUNTIME_SCRATCH)
    assert manifest.scanner_container_name == "verigym-hwe-v130-command-scan-pr-465"
    assert (
        manifest.create_timeout_seconds
        + 2 * manifest.inspect_timeout_seconds
        + manifest.start_timeout_seconds
        + manifest.remove_timeout_seconds
        == manifest.overall_timeout_seconds
    )
    assert manifest.task_execution_allowed is False
    assert manifest.base_reference_verification_allowed is False
    assert manifest.harness_controller_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.provider_calls == 0


def test_v130_static_predecessor_uses_files_not_frozen_volumes() -> None:
    manifest = load_v130_bounded_command_scan_probe_manifest(runner.MANIFEST)
    source = inspect.getsource(runner._validate_static_predecessor)

    assert "v127-dind-data" not in source
    assert "deepseek-harness-hwe-v127/data" not in source
    receipt, source_lock = runner._validate_static_predecessor(manifest)
    task = runner._task_lock(manifest)

    assert receipt["status"] == "passed"
    assert receipt["predecessor_volumes_inspected"] is False
    assert receipt["predecessor_volumes_mutated"] is False
    assert source_lock.task_id == manifest.task_id
    assert task.official_verifier_image == manifest.official_verifier_image


def test_v130_start_uses_fresh_data2_mount_and_exact_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v130_bounded_command_scan_probe_manifest(runner.MANIFEST)
    calls: list[tuple[list[str], float]] = []
    results = [
        _completed(("a" * 64 + "\n").encode()),
        _completed(b"23.0.6\tvfs\trunc\n"),
    ]

    def run(
        arguments: list[str],
        *,
        timeout: float,
        env: Any = None,
    ) -> subprocess.CompletedProcess[bytes]:
        del env
        calls.append((arguments, timeout))
        return results.pop(0)

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(runner, "RUNTIME_SCRATCH", tmp_path)
    monkeypatch.setattr(runner, "_outer_controls_valid", lambda _manifest: True)

    receipt = runner._start_dind(manifest)

    start = calls[0][0]
    assert ["--network", "none"] == start[start.index("--network") : start.index("--network") + 2]
    assert f"type=volume,src={manifest.dind_data_volume},dst=/var/lib/docker" in start
    assert f"type=volume,src={manifest.dind_socket_volume},dst=/var/run" in start
    assert f"type=bind,src={tmp_path},dst={tmp_path}" in start
    assert calls[0][1] == 60
    assert calls[1][1] == 5
    assert receipt["storage_driver"] == "vfs"
    assert receipt["predecessor_volumes_inspected"] is False


def test_v130_outer_control_inspection_rejects_any_extra_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v130_bounded_command_scan_probe_manifest(runner.MANIFEST)
    monkeypatch.setattr(runner, "RUNTIME_SCRATCH", tmp_path)
    value = {
        "Image": manifest.dind_image_id,
        "HostConfig": {"Privileged": True, "NetworkMode": "none", "PidsLimit": 32768},
        "Config": {
            "Labels": {
                "verigym.owner": runner.IDENTITY,
                "verigym.role": "command-scan-probe-daemon",
            },
            "Env": ["DOCKER_TLS_CERTDIR="],
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": manifest.dind_data_volume,
                "Destination": "/var/lib/docker",
                "RW": True,
            },
            {
                "Type": "volume",
                "Name": manifest.dind_socket_volume,
                "Destination": "/var/run",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": str(tmp_path),
                "Destination": str(tmp_path),
                "RW": True,
            },
        ],
    }
    monkeypatch.setattr(runner, "_docker_json", lambda *_args, **_kwargs: [value])

    assert runner._outer_controls_valid(manifest) is True
    value["Mounts"].append(
        {"Type": "bind", "Source": "/unexpected", "Destination": "/unexpected", "RW": True}
    )
    assert runner._outer_controls_valid(manifest) is False


def test_v130_build_passes_the_exact_runtime_policy_without_task_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v130_bounded_command_scan_probe_manifest(runner.MANIFEST)
    task = runner._task_lock(manifest)
    _, source_lock = runner._validate_static_predecessor(manifest)
    for directory in ("image-receipts", "security-scans", "image-locks"):
        (tmp_path / directory).mkdir()
    receipt = tmp_path / "image-receipts/pr-465.json"
    observed: dict[str, Any] = {}
    monkeypatch.setattr(runner.v69, "_load_completed_archive", lambda *_args, **_kwargs: None)

    def build(command: list[str], *, timeout: int) -> dict[str, Any]:
        observed["build"] = (command, timeout)
        receipt.write_text("{}", encoding="utf-8")
        return {
            "status": "passed",
            "category": "command_image_build_complete",
            "diagnostic_hash": "b" * 64,
        }

    def scan(**kwargs: Any) -> tuple[dict[str, Any], SimpleNamespace]:
        observed["scan"] = kwargs
        lock = SimpleNamespace(
            security_scan_passed=True,
            task_id=manifest.task_id,
            verifier_base_image_id=manifest.official_verifier_image,
            model_dump=lambda **_kwargs: {"lock_hash": "c" * 64},
        )
        return {"scan_passed": True, "security_scan_id": "d" * 64}, lock

    monkeypatch.setattr(runner, "_bounded_build", build)
    monkeypatch.setattr(runner, "scan_and_lock", scan)
    monkeypatch.setattr(
        runner,
        "_inner_inventory",
        lambda: {"status": "passed", "inventory_hash": "e" * 64},
    )

    scan_value, lock_value, inventory = runner._build_and_scan(
        manifest,
        task,
        source_lock,
        root=tmp_path,
    )

    policy = observed["scan"]["runtime_policy"]
    assert policy.create_timeout_seconds == 300
    assert policy.inspect_timeout_seconds == 60
    assert policy.start_timeout_seconds == 180
    assert policy.remove_timeout_seconds == 120
    assert policy.overall_timeout_seconds == 720
    assert policy.container_name == manifest.scanner_container_name
    assert observed["scan"]["runtime_scratch_parent"] == runner.RUNTIME_SCRATCH
    assert observed["build"][1] == 1800
    assert scan_value["scan_passed"] is True
    assert lock_value["lock_hash"] == "c" * 64
    assert inventory["status"] == "passed"
    assert "run_zero_model_smoke" not in inspect.getsource(runner._build_and_scan)


def test_v130_failed_scan_still_requires_an_empty_inner_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v130_bounded_command_scan_probe_manifest(runner.MANIFEST)
    task = runner._task_lock(manifest)
    _, source_lock = runner._validate_static_predecessor(manifest)
    for directory in ("image-receipts", "security-scans", "image-locks"):
        (tmp_path / directory).mkdir()
    receipt = tmp_path / "image-receipts/pr-465.json"
    monkeypatch.setattr(runner.v69, "_load_completed_archive", lambda *_args, **_kwargs: None)

    def build(_command: list[str], *, timeout: int) -> dict[str, Any]:
        assert timeout == 1800
        receipt.write_text("{}", encoding="utf-8")
        return {
            "status": "passed",
            "category": "command_image_build_complete",
            "diagnostic_hash": "b" * 64,
        }

    def failed_scan(**kwargs: Any) -> None:
        Path(kwargs["security_output"]).write_text(
            json.dumps({"diagnostic": {"error_category": "docker_create_timeout"}}),
            encoding="utf-8",
        )
        raise RuntimeError("bounded scanner failure")

    monkeypatch.setattr(runner, "_bounded_build", build)
    monkeypatch.setattr(runner, "scan_and_lock", failed_scan)
    monkeypatch.setattr(
        runner,
        "_inner_inventory",
        lambda: {"status": "passed", "inventory_hash": "e" * 64},
    )

    with pytest.raises(runner._ProbeFailure, match="docker_create_timeout"):
        runner._build_and_scan(manifest, task, source_lock, root=tmp_path)

    persisted = json.loads((tmp_path / "inner-inventory.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "passed"


def test_v130_refuses_provider_environment_before_any_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    arguments = argparse.Namespace(
        manifest=runner.MANIFEST,
        output=runner.OUTPUT_ROOT,
        post_merge_main_run_id=1,
    )

    with pytest.raises(ConfigurationError, match="provider"):
        runner._require_execution_boundary(arguments)


def test_v130_closed_report_never_claims_collection() -> None:
    manifest = load_v130_bounded_command_scan_probe_manifest(runner.MANIFEST)
    report = runner._base_report(
        manifest,
        source_commit="a" * 40,
        post_merge_main_run_id=1,
    )

    assert report["task_execution_started"] is False
    assert report["base_reference_verification_started"] is False
    assert report["harness_controller_started"] is False
    assert report["provider_request_started"] is False
    assert report["provider_calls"] == 0
    assert report["formal_collection_allowed"] is False
    assert report["training_started"] is False
    assert json.dumps(report).count("not-a-real-key") == 0
