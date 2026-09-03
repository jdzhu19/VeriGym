from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
from verigym_deepseek_harness import config as harness_config

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.trace import TraceWriter
from verigym.hwe.deepseek_harness_campaign import (
    load_v92_official_matrix_manifest,
    new_matrix_state,
    record_matrix_attempt,
)
from verigym.hwe.image_lock import HweCommandImageLock

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import collect_hwe_deepseek_harness_v92_official_matrix as runner  # noqa: E402

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v92_official_matrix_v1.json"
)


def _lock(*, repository: str = "ibex") -> HweCommandImageLock:
    source_home = "/home/ibex" if repository == "ibex" else "/home/cva6"
    profile = (
        "ibex-verilator-system-container-native-v1"
        if repository == "ibex"
        else "cva6-verilator-5.008-container-native-v2"
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_command_image_lock_v1",
        "task_id": (
            "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465"
            if repository == "ibex"
            else "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017"
        ),
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "verifier_base_image_id": "sha256:" + "3" * 64,
        "derived_command_image_id": "sha256:" + "4" * 64,
        "rg_version": "ripgrep 15.2.0 (rev e89fff89ac)",
        "rg_sha256": "5" * 64,
        "rg_release_archive_sha256": "6" * 64,
        "rg_source": "github.com/BurntSushi/ripgrep/releases/15.2.0",
        "collection_profile_id": "hwe_standard_v2",
        "tool_contract_id": "hwe_native_shell_v2",
        "command_protocol": "hwe_command_image_v1",
        "supported_execution_backends": [
            "ephemeral_container_v1",
            "episode_container_exec_v1",
        ],
        "toolchain_profile_id": profile,
        "allowlisted_artifacts": [
            {"path": "/usr/bin/make", "sha256": "7" * 64, "role": "build_tool"},
            {"path": "/usr/bin/verilator", "sha256": "8" * 64, "role": "simulator"},
        ],
        "source_whiteout_path": source_home,
        "visible_workspace_path": "/workspace/repository",
        "build_network": "none",
        "runtime_network": "none",
        "codex_present": False,
        "provider_credentials_present": False,
        "hidden_assets_present": False,
        "verifier_payload_present": False,
        "reference_patch_present": False,
        "security_scan_id": "9" * 64,
        "security_scan_passed": True,
    }
    return HweCommandImageLock.model_validate({**base, "lock_hash": content_hash(base)})


def test_checked_in_v92_manifest_is_one_use_and_keeps_collection_closed() -> None:
    manifest = load_v92_official_matrix_manifest(_MANIFEST)
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.v90_data_volume_reopen_budget == 1
    assert manifest.source_preparation_docker_control_timeout_seconds == 300
    assert all(
        item.source_preparation_docker_control_timeout_seconds == 300 for item in manifest.schedule
    )
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.provider_outer_network == "verigym-hwe-net"
    assert manifest.task_network == "none"
    assert manifest.verifier_network == "none"
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_offline_controller_requires_explicit_mode_tag_and_source_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = {
        "Id": harness_config.CONTROLLER_IMAGE_ID,
        "RepoTags": [harness_config.CONTROLLER_IMAGE_TAG],
        "RepoDigests": [],
    }
    monkeypatch.setattr(
        harness_config.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, json.dumps(value), ""),
    )
    with pytest.raises(ValueError, match="digest changed"):
        harness_config._verify_controller_image(  # noqa: SLF001
            harness_config.CONTROLLER_IMAGE_ID
        )
    harness_config._verify_controller_image(  # noqa: SLF001
        harness_config.CONTROLLER_IMAGE_ID,
        allow_offline_load=True,
    )

    value["RepoTags"] = []
    with pytest.raises(ValueError, match="digest changed"):
        harness_config._verify_controller_image(  # noqa: SLF001
            harness_config.CONTROLLER_IMAGE_ID,
            allow_offline_load=True,
        )


def test_offline_controller_settings_bind_the_audited_source_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"
    (source / "python/sdk/src").mkdir(parents=True)
    runtime = source / "packages/examples/jsonrpc-demo/src/bin.ts"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("export {};\n", encoding="utf-8")
    (source / "package.json").write_text('{"version":"0.1.1-rc.2"}\n', encoding="utf-8")
    monkeypatch.setattr(harness_config, "_verify_source_checkout", lambda _root: None)
    monkeypatch.setattr(harness_config, "_tracked_tree_hash", lambda _root: "1" * 64)
    verified: list[bool] = []
    monkeypatch.setattr(
        harness_config,
        "_verify_controller_image",
        lambda _image, *, allow_offline_load=False: verified.append(allow_offline_load),
    )
    common = {
        "collection_profile_id": "hwe_standard_v2",
        "harness_source_root": source,
        "controller_image_offline_load": True,
    }
    with pytest.raises(ValueError, match="source receipt"):
        harness_config.resolve_settings(common, task_wall_time_s=300)

    settings = harness_config.resolve_settings(
        {**common, "controller_image_source_receipt_hash": "2" * 64},
        task_wall_time_s=300,
    )
    assert verified == [True]
    assert settings.controller_image_provenance == "audited_offline_canonical_tag_load_v1"
    assert settings.harness_identity()["controller_image_source_receipt_hash"] == "2" * 64


def test_v92_runtime_config_selects_repository_specific_labels() -> None:
    ibex = runner._runtime_config(_lock(repository="ibex"))  # noqa: SLF001
    cva6 = runner._runtime_config(_lock(repository="cva6"))  # noqa: SLF001
    assert ibex.network_mode == "none"
    assert ibex.command_image is not None
    assert ibex.command_image.network_mode == "none"
    assert ibex.command_image.execution_backend == "episode_container_exec_v1"
    assert ibex.command_image.required_image_labels["org.verigym.runtime.role"] == (
        "hwe-ibex-command"
    )
    assert "org.verigym.ibex.verifier_base_image_id" in (ibex.command_image.required_image_labels)
    assert cva6.command_image is not None
    assert cva6.command_image.required_image_labels["org.verigym.runtime.role"] == (
        "hwe-cva6-command"
    )
    assert "org.verigym.cva6.verifier_base_image_id" in (cva6.command_image.required_image_labels)


def test_nested_runtime_restores_docker_and_temp_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_tmp = tmp_path / "runtime"
    runtime_tmp.mkdir()
    socket_path = tmp_path / "docker.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(socket_path))
    previous_tempdir = tempfile.tempdir
    monkeypatch.setattr(runner, "RUNTIME_TMP", runtime_tmp)
    monkeypatch.setenv("DOCKER_HOST", "prior-host")
    monkeypatch.setenv("DOCKER_CONTEXT", "prior-context")
    monkeypatch.setenv("TMPDIR", "prior-tmp")
    try:
        with runner._nested_runtime(socket_path):  # noqa: SLF001
            assert os.environ["DOCKER_HOST"] == f"unix://{socket_path}"
            assert "DOCKER_CONTEXT" not in os.environ
            assert tempfile.tempdir == str(runtime_tmp)
        assert os.environ["DOCKER_HOST"] == "prior-host"
        assert os.environ["DOCKER_CONTEXT"] == "prior-context"
        assert os.environ["TMPDIR"] == "prior-tmp"
        assert tempfile.tempdir == previous_tempdir
    finally:
        listener.close()


def test_v92_marker_and_pre_provider_failure_do_not_consume_task(tmp_path: Path) -> None:
    manifest = load_v92_official_matrix_manifest(_MANIFEST)
    binding = manifest.schedule[0]
    task_root = tmp_path / "tasks" / f"pr-{binding.pr_number}"
    trace = TraceWriter(task_root / "runs/episode/trace.jsonl", "episode")
    trace.emit(
        "deepseek_harness_provider_request_started",
        {
            "provider_request_started": True,
            "provider_request_count_lower_bound": 1,
            "credential_values_persisted": False,
            "content_truncated": False,
        },
    )
    assert runner._provider_marker_state(task_root) == ("started_valid", True)  # noqa: SLF001

    detail = runner._exception_attempt(  # noqa: SLF001
        binding,
        marker="not_started",
        exception=ConfigurationError("not persisted"),
    )
    state = record_matrix_attempt(
        new_matrix_state([binding.task_id]), runner._state_attempt(detail)
    )
    assert state.stop_reason == "pre_provider_infrastructure_failure"
    assert state.attempts[0]["provider_consumed"] is False
    assert "not persisted" not in json.dumps(detail)


def test_v92_provider_sidecar_enables_only_the_named_outer_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v92_official_matrix_manifest(_MANIFEST)
    v90_root = tmp_path / "v90"
    (v90_root / "dind-empty-home").mkdir(parents=True)
    source_root = tmp_path / "harness"
    source_root.mkdir()
    control_root = tmp_path / "control"
    control_root.mkdir()
    runtime_tmp = tmp_path / "runtime"
    runtime_tmp.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(runner, "V90_ROOT", v90_root)
    monkeypatch.setattr(runner, "DEEPSEEK_HARNESS_SOURCE_ROOT", source_root)
    monkeypatch.setattr(runner, "CONTROL_ROOT", control_root)
    monkeypatch.setattr(runner, "RUNTIME_TMP", runtime_tmp)
    calls: list[list[str]] = []

    def run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        if arguments[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess([], 0, b"container-id\n", b"")
        if "version" in arguments:
            return subprocess.CompletedProcess([], 0, b"23.0.6\n", b"")
        if "--format" in arguments and "info" in arguments:
            value = {"Driver": "vfs", "DefaultRuntime": "runc"}
            return subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b"")
        if "stat" in arguments:
            return subprocess.CompletedProcess([], 0, f"{os.getgid()}\n".encode(), b"")
        return subprocess.CompletedProcess([], 0, b"ready\n", b"")

    monkeypatch.setattr(runner.dind, "_run", run)
    monkeypatch.setattr(runner, "_validate_outer_provider_sidecar", lambda *_a, **_k: None)
    runner._start_provider_dind(name="v92-sidecar", manifest=manifest, root=output)  # noqa: SLF001
    command = calls[0]
    network_index = command.index("--network")
    assert command[network_index + 1] == "verigym-hwe-net"
    assert "--bridge=none" not in command
    assert "--iptables=false" not in command
    assert "/var/run/docker.sock" not in " ".join(command)
    assert harness_config.API_KEY_ENV not in " ".join(command)
    assert harness_config.BASE_URL_ENV not in " ".join(command)


def test_v92_provider_sidecar_retries_a_timed_out_readiness_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v92_official_matrix_manifest(_MANIFEST)
    v90_root = tmp_path / "v90"
    (v90_root / "dind-empty-home").mkdir(parents=True)
    source_root = tmp_path / "harness"
    source_root.mkdir()
    control_root = tmp_path / "control"
    control_root.mkdir()
    runtime_tmp = tmp_path / "runtime"
    runtime_tmp.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(runner, "V90_ROOT", v90_root)
    monkeypatch.setattr(runner, "DEEPSEEK_HARNESS_SOURCE_ROOT", source_root)
    monkeypatch.setattr(runner, "CONTROL_ROOT", control_root)
    monkeypatch.setattr(runner, "RUNTIME_TMP", runtime_tmp)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    readiness_calls = 0

    def run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal readiness_calls
        if arguments[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess([], 0, b"container-id\n", b"")
        if arguments[-2:] == ["docker", "info"]:
            readiness_calls += 1
            if readiness_calls == 1:
                raise subprocess.TimeoutExpired(arguments, 15)
            return subprocess.CompletedProcess([], 0, b"ready\n", b"")
        if "version" in arguments:
            return subprocess.CompletedProcess([], 0, b"23.0.6\n", b"")
        if "--format" in arguments and "info" in arguments:
            value = {"Driver": "vfs", "DefaultRuntime": "runc"}
            return subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b"")
        if "stat" in arguments:
            return subprocess.CompletedProcess([], 0, f"{os.getgid()}\n".encode(), b"")
        raise AssertionError(arguments)

    monkeypatch.setattr(runner.dind, "_run", run)
    monkeypatch.setattr(runner, "_validate_outer_provider_sidecar", lambda *_a, **_k: None)
    runner._start_provider_dind(name="v92-sidecar", manifest=manifest, root=output)  # noqa: SLF001
    assert readiness_calls == 2


def test_v92_provider_value_scan_never_persists_or_hashes_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(harness_config.API_KEY_ENV, "provider-secret-test-value")
    monkeypatch.setenv(harness_config.BASE_URL_ENV, "https://provider.example.invalid")
    (tmp_path / "safe.json").write_text('{"provider_values_persisted":false}\n')
    receipt = runner._scan_provider_values(tmp_path)  # noqa: SLF001
    assert receipt["passed"] is True
    assert receipt["provider_values_persisted_or_hashed"] is False

    (tmp_path / "unsafe.txt").write_text("provider-secret-test-value")
    with pytest.raises(ConfigurationError, match="provider value"):
        runner._scan_provider_values(tmp_path)  # noqa: SLF001


def test_v92_manifest_does_not_persist_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert harness_config.API_KEY_ENV not in encoded
    assert harness_config.BASE_URL_ENV not in encoded
