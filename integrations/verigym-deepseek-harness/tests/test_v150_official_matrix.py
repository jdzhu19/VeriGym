from __future__ import annotations

import hashlib
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
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV150OfficialMatrixManifest,
    load_v150_official_matrix_manifest,
    new_matrix_state,
    record_matrix_attempt,
)
from verigym.hwe.image_lock import HweCommandImageLock

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import collect_hwe_deepseek_harness_v150_official_matrix as runner  # noqa: E402
from scripts import launch_hwe_deepseek_harness_v150_official_matrix as launcher  # noqa: E402

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v150_official_matrix_v1.json"
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


def test_checked_in_v150_manifest_is_one_use_and_keeps_collection_closed() -> None:
    manifest = load_v150_official_matrix_manifest(_MANIFEST)
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.v148_data_volume_reopen_budget == 1
    assert manifest.v148_data_volume_reopen_count_before == 0
    assert manifest.protocol_baseline_identity == "deepseek-harness-hwe-v92-official-matrix-v1"
    assert manifest.predecessor_data_volume_owner.endswith("v148-cleanup-identity-scaffold-v1")
    assert manifest.runtime_resource_owner == runner.IDENTITY
    assert manifest.workspace_runtime_image_id == runner.HWE_WORKSPACE_RUNTIME_IMAGE_ID
    assert manifest.source_preparation_docker_control_timeout_seconds == 300
    assert all(
        item.source_preparation_docker_control_timeout_seconds == 300 for item in manifest.schedule
    )
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.provider_outer_network == "verigym-hwe-net"
    assert manifest.provider_inner_network == "verigym-hwe-net"
    assert manifest.task_network == "none"
    assert manifest.verifier_network == "none"
    assert manifest.max_provider_calls_per_task == 64
    assert manifest.max_provider_tokens_per_task == 1_000_000
    assert manifest.max_context_tokens == 65_536
    assert manifest.max_output_tokens == 2_048
    assert manifest.temperature == 0
    assert manifest.provider_request_retries == 0
    assert manifest.whole_episode_retries == 0
    assert manifest.ordinary_tool_choice == "auto"
    assert manifest.provider_hidden_thinking == "disabled"
    assert manifest.provider_environment_boundary == "exact-two-name-child-v1"
    assert manifest.provider_environment_name_count == 2
    assert manifest.ambient_provider_aliases_removed is True
    assert manifest.requires_independent_v151_audit is True
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v150_authorization_binds_manifest_launcher_runner_and_main_gate() -> None:
    authorization = (
        runner._REPOSITORY
        / "docs/audits/2026-09-05_deepseek-harness-v150-official-matrix-authorization.md"
    ).read_text(encoding="utf-8")
    assert hashlib.sha256(_MANIFEST.read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest() in authorization
    assert "33940855243" in authorization


def test_v150_manifest_hash_rejects_any_policy_mutation() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["max_provider_calls_per_task"] = 63
    with pytest.raises(ValueError):
        DeepSeekHarnessV150OfficialMatrixManifest.model_validate(value)


@pytest.mark.skipif(not runner.V148_ROOT.is_dir(), reason="sealed v148 evidence is not local")
def test_v150_checked_in_predecessor_chain_and_task_bindings_are_exact() -> None:
    manifest = load_v150_official_matrix_manifest(_MANIFEST)
    runner._validate_predecessor(manifest, v148_root=runner.V148_ROOT)  # noqa: SLF001
    locks = runner._validate_task_bindings(manifest, v148_root=runner.V148_ROOT)  # noqa: SLF001
    assert list(locks) == [item.task_id for item in manifest.schedule]
    assert [lock.lock_hash for lock in locks.values()] == [
        item.command_image_lock_hash for item in manifest.schedule
    ]


def test_v150_host_gate_keeps_predecessor_and_runtime_owners_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v150_official_matrix_manifest(_MANIFEST)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(runner, "DIND_DATA_BACKING", data)
    monkeypatch.setattr(
        runner, "HWE_WORKSPACE_RUNTIME_IMAGE_ID", manifest.workspace_runtime_image_id
    )
    observed: dict[str, str] = {}

    def inspect(role: str, name: str) -> dict[str, object]:
        if role == "image" and name == manifest.dind_image_id:
            return {"RepoDigests": [f"docker:23.0.6-dind@{manifest.dind_repository_digest}"]}
        if role == "network":
            return {"Name": name, "Driver": "bridge", "Internal": False, "Scope": "local"}
        if role == "image" and name == manifest.controller_image_tag:
            return {
                "Id": manifest.controller_image_id,
                "RepoDigests": [runner.CONTROLLER_IMAGE_REPO_DIGEST],
            }
        raise AssertionError((role, name))

    def bind_backed_volume(_name: str, *, owner: str, role: str, backing: Path) -> Path:
        observed["data_owner"] = owner
        assert role == "data"
        assert backing == data
        return data.resolve()

    def run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if arguments[:3] == ["docker", "volume", "inspect"]:
            return subprocess.CompletedProcess([], 1, b"", b"")
        observed["sidecar_filter"] = arguments[-1]
        return subprocess.CompletedProcess([], 0, b"", b"")

    monkeypatch.setattr(runner.dind, "_dind_image", lambda _image: None)
    monkeypatch.setattr(runner.dind, "_inspect", inspect)
    monkeypatch.setattr(runner.dind, "_bind_backed_volume", bind_backed_volume)
    monkeypatch.setattr(runner.dind, "_run", run)
    runner._validate_host_runtime(manifest)  # noqa: SLF001
    assert observed["data_owner"] == manifest.predecessor_data_volume_owner
    assert observed["sidecar_filter"] == f"label=verigym.owner={runner.IDENTITY}"


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


def test_v150_runtime_config_selects_repository_specific_labels() -> None:
    ibex = runner._runtime_config(_lock(repository="ibex"))  # noqa: SLF001
    cva6 = runner._runtime_config(_lock(repository="cva6"))  # noqa: SLF001
    assert ibex.network_mode == "none"
    assert ibex.command_image is not None
    assert ibex.command_image.network_mode == "none"
    assert ibex.command_image.execution_backend == "episode_container_exec_v1"
    assert ibex.command_image.identity_probe_timeout_s == 300
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
    socket_path = Path(f"/data2/jiadongzhu/v150-test-{os.getpid()}.sock")
    socket_path.unlink(missing_ok=True)
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
        socket_path.unlink(missing_ok=True)


def test_v150_marker_and_pre_provider_failure_do_not_consume_task(tmp_path: Path) -> None:
    manifest = load_v150_official_matrix_manifest(_MANIFEST)
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


def test_v150_provider_sidecar_enables_only_the_named_outer_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v150_official_matrix_manifest(_MANIFEST)
    v148_root = tmp_path / "v148"
    (v148_root / "dind-empty-home").mkdir(parents=True)
    source_root = tmp_path / "harness"
    source_root.mkdir()
    control_root = tmp_path / "control"
    control_root.mkdir()
    runtime_tmp = tmp_path / "runtime"
    runtime_tmp.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(runner, "V148_ROOT", v148_root)
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
    runner._start_provider_dind(name="v150-sidecar", manifest=manifest, root=output)  # noqa: SLF001
    command = calls[0]
    network_index = command.index("--network")
    assert command[network_index + 1] == "verigym-hwe-net"
    assert "--bridge=none" not in command
    assert "--iptables=false" not in command
    assert "/var/run/docker.sock" not in " ".join(command)
    assert harness_config.API_KEY_ENV not in " ".join(command)
    assert harness_config.BASE_URL_ENV not in " ".join(command)


def test_v150_provider_sidecar_retries_a_timed_out_readiness_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v150_official_matrix_manifest(_MANIFEST)
    v148_root = tmp_path / "v148"
    (v148_root / "dind-empty-home").mkdir(parents=True)
    source_root = tmp_path / "harness"
    source_root.mkdir()
    control_root = tmp_path / "control"
    control_root.mkdir()
    runtime_tmp = tmp_path / "runtime"
    runtime_tmp.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(runner, "V148_ROOT", v148_root)
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
    runner._start_provider_dind(name="v150-sidecar", manifest=manifest, root=output)  # noqa: SLF001
    assert readiness_calls == 2


def test_v150_provider_value_scan_never_persists_or_hashes_values(
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


@pytest.mark.parametrize(("stdout", "stderr"), [(b"unexpected\n", b""), (b"", b"unexpected\n")])
def test_v150_socket_cleanup_rejects_nonempty_output_before_volume_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: bytes,
    stderr: bytes,
) -> None:
    manifest = load_v150_official_matrix_manifest(_MANIFEST)
    socket_backing = tmp_path / "socket"
    socket_backing.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_backing)
    monkeypatch.setattr(runner.dind, "_bind_backed_volume", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runner.dind,
        "_run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, stdout, stderr),
    )
    monkeypatch.setattr(
        runner.dind,
        "_remove_volume",
        lambda _name: pytest.fail("nonempty cleanup output must fail before volume removal"),
    )

    with pytest.raises(ConfigurationError, match="socket cleanup failed"):
        runner._clean_socket_volume(manifest, root=tmp_path)  # noqa: SLF001


def test_v150_manifest_does_not_persist_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert harness_config.API_KEY_ENV not in encoded
    assert harness_config.BASE_URL_ENV not in encoded


class _GuardedEnvironment(dict[str, str]):
    def __getitem__(self, key: str) -> str:
        blocked_aliases = set(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES) - {
            harness_config.API_KEY_ENV,
            harness_config.BASE_URL_ENV,
        }
        if key in blocked_aliases:
            raise AssertionError(f"blocked provider alias value read: {key}")
        return super().__getitem__(key)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self[key] if key in self else default


def test_v150_launcher_passes_only_exact_provider_names_without_reading_aliases() -> None:
    source = _GuardedEnvironment(
        {
            "PATH": "/safe/bin",
            harness_config.API_KEY_ENV: "provider-key",
            harness_config.BASE_URL_ENV: "https://provider.example.invalid",
            "OPENAI_API_KEY": "must-not-read",
            "DOCKER_HOST": "must-not-read",
        }
    )
    child = launcher._sanitized_child_environment(source)  # noqa: SLF001
    present = {name for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES if name in child}
    assert present == {harness_config.API_KEY_ENV, harness_config.BASE_URL_ENV}
    assert child[harness_config.API_KEY_ENV] == "provider-key"
    assert child[harness_config.BASE_URL_ENV] == "https://provider.example.invalid"
    assert "DOCKER_HOST" not in child
    assert child[runner.CHILD_BOUNDARY_ENV] == "1"


def test_v150_runner_rejects_an_unverified_or_contaminated_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.os, "getuid", lambda: 1000)
    monkeypatch.setattr(runner.os, "getgid", lambda: 1000)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(harness_config.API_KEY_ENV, "provider-key")
    monkeypatch.setenv(harness_config.BASE_URL_ENV, "https://provider.example.invalid")
    monkeypatch.delenv(runner.CHILD_BOUNDARY_ENV, raising=False)
    with pytest.raises(ConfigurationError, match="verified provider child"):
        runner._require_opt_in()  # noqa: SLF001

    monkeypatch.setenv(runner.CHILD_BOUNDARY_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "contaminating-alias")
    with pytest.raises(ConfigurationError, match="contaminated"):
        runner._require_opt_in()  # noqa: SLF001


def test_v150_terminal_report_requires_v151_and_keeps_sft_import_closed() -> None:
    manifest = load_v150_official_matrix_manifest(_MANIFEST)
    state = new_matrix_state([item.task_id for item in manifest.schedule])
    details: list[dict[str, object]] = []
    for binding in manifest.schedule:
        detail: dict[str, object] = {
            "task_id": binding.task_id,
            "repository": binding.repository,
            "agent_toolchain_id": binding.agent_toolchain_id,
            "official_verifier_image": binding.official_verifier_image,
            "provider_marker": "started_valid",
            "provider_call_count": 1,
            "provider_total_tokens": 100,
            "first_effective_modification_action": 1,
            "outcome": "passed",
            "planes": {
                "benchmark_verifier_pass": True,
                "agent_protocol_valid": True,
                "trajectory_eligible": True,
                "infrastructure_valid": True,
                "security_valid": True,
                "sft_admitted": True,
            },
            "exact_64k_eligible": True,
            "maximum_decision_tokens": 100,
            "truncation_applied": False,
            "decision_only_loss_mask": True,
        }
        state = record_matrix_attempt(state, runner._state_attempt(detail))  # noqa: SLF001
        details.append(detail)
    report = runner._final_report(  # noqa: SLF001
        manifest,
        {
            "matrix_state": state.model_dump(mode="json"),
            "status": "completed",
            "dind_cleanup_confirmed": True,
        },
        details,
    )
    assert report["status"] == "completed_pending_independent_v151_audit"
    assert report["requires_independent_v151_audit"] is True
    assert report["trajectory_collection_migratable"] is True
    assert report["sft_path_migratable"] is True
    assert report["candidate_sft_import_authorized"] is False
    assert report["formal_collection_allowed"] is False
    assert report["training_started"] is False
