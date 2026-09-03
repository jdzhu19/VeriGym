from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V71_MATRIX_TASK_IDS,
    load_v92_official_matrix_manifest,
    load_v115_explicit_nested_docker_socket_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v115_explicit_nested_docker_socket_scaffold as runner,
)


def _purpose_manifest() -> Any:
    return load_v115_explicit_nested_docker_socket_scaffold_manifest(runner.MANIFEST)


def _bound_manifest(socket_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        nested_docker_host=f"unix://{socket_path}",
        docker_host_binding_policy="explicit-canonical-local-unix-socket-v1",
        schedule=[
            SimpleNamespace(task_id="inner-only-image-a", pr_number=1),
            SimpleNamespace(task_id="inner-only-image-b", pr_number=2),
        ],
        runtime_prepare_task_count=2,
        workspace_runtime_image_id="sha256:" + "9" * 64,
        task_network="none",
        controller_image_id="sha256:" + "8" * 64,
        scaffold_outer_network="none",
        preflight_inner_network="verigym-hwe-net",
        preflight_inner_network_internal=True,
    )


def test_v115_manifest_freezes_the_explicit_socket_and_closed_policy() -> None:
    manifest = _purpose_manifest()

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.nested_docker_host == (
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket/docker.sock"
    )
    assert manifest.docker_host_binding_policy == "explicit-canonical-local-unix-socket-v1"
    assert manifest.docker_cli_explicit_binding_required is True
    assert manifest.harness_helper_explicit_binding_required is True
    assert manifest.inherited_docker_environment_allowed is False
    assert manifest.remote_docker_endpoint_allowed is False
    assert manifest.v112_data_volume_reused is False
    assert manifest.v114_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v117-official-matrix-v1"
    assert manifest.provider_credentials_available is False
    assert all(
        getattr(manifest, name) is False
        for name in runner.v94._closed_training_flags()  # noqa: SLF001
    )


def test_v115_configuration_restores_the_frozen_v112_runner() -> None:
    original = {
        "IDENTITY": runner.v112.IDENTITY,
        "DIND_DATA_BACKING": runner.v112.DIND_DATA_BACKING,
        "_runtime_prepare_preflight": runner.v112._runtime_prepare_preflight,  # noqa: SLF001
        "_harness_initialize_preflight": runner.v112._harness_initialize_preflight,  # noqa: SLF001
    }

    with runner._v115_configuration():  # noqa: SLF001
        assert runner.v112.IDENTITY == runner.IDENTITY
        assert runner.v112.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v112._runtime_prepare_preflight is runner._runtime_prepare_preflight  # noqa: SLF001
        assert (  # noqa: SLF001
            runner.v112._harness_initialize_preflight is runner._harness_initialize_preflight
        )

    assert runner.v112.IDENTITY == original["IDENTITY"]
    assert runner.v112.DIND_DATA_BACKING == original["DIND_DATA_BACKING"]
    assert runner.v112._runtime_prepare_preflight is original["_runtime_prepare_preflight"]  # noqa: SLF001
    assert (  # noqa: SLF001
        runner.v112._harness_initialize_preflight is original["_harness_initialize_preflight"]
    )


def test_v115_explicit_endpoint_requires_and_restores_the_nested_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_root = tmp_path / "socket"
    socket_root.mkdir()
    socket_path = socket_root / "docker.sock"
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.bind(str(socket_path))
    manifest = _bound_manifest(socket_path)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_root)
    monkeypatch.setenv("DOCKER_HOST", "prior-host")
    monkeypatch.setenv("DOCKER_CONTEXT", "prior-context")
    try:
        with runner.v94._nested_runtime(socket_path):  # noqa: SLF001
            assert runner._validated_nested_docker_host(manifest) == f"unix://{socket_path}"  # noqa: SLF001
        assert os.environ["DOCKER_HOST"] == "prior-host"
        assert os.environ["DOCKER_CONTEXT"] == "prior-context"
    finally:
        endpoint.close()

    with pytest.raises(ConfigurationError, match="scope or manifest endpoint"):
        runner._validated_nested_docker_host(manifest)  # noqa: SLF001


def test_v115_runtime_prepare_binds_inner_only_images_to_the_explicit_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_root = tmp_path / "socket"
    socket_root.mkdir()
    socket_path = socket_root / "docker.sock"
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.bind(str(socket_path))
    manifest = _bound_manifest(socket_path)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_root)
    monkeypatch.setenv("DOCKER_HOST", f"unix://{socket_path}")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    prepared: list[tuple[str, str, str]] = []
    empty_checks: list[str] = []

    class Runtime:
        def __init__(self, config: str, *, engine: Any) -> None:
            self.config = config
            self.engine = engine

        def prepare(self, run_id: str) -> None:
            prepared.append((self.config, str(self.engine.docker_host), run_id))

        def close(self) -> None:
            self.engine.close()

    monkeypatch.setattr(runner, "DockerRuntime", Runtime)
    monkeypatch.setattr(runner.v92, "_runtime_config", lambda lock: lock)  # noqa: SLF001
    monkeypatch.setattr(
        runner.dind,
        "_require_empty_inner_inventory",  # noqa: SLF001
        lambda name: empty_checks.append(name),
    )
    try:
        receipt = runner._runtime_prepare_preflight(  # noqa: SLF001
            manifest,
            locks={"inner-only-image-a": "image-a", "inner-only-image-b": "image-b"},
            dind_name="inner-daemon",
        )
    finally:
        endpoint.close()

    assert prepared == [
        ("image-a", f"unix://{socket_path}", "v115-preflight-pr-1"),
        ("image-b", f"unix://{socket_path}", "v115-preflight-pr-2"),
    ]
    assert empty_checks == ["inner-daemon", "inner-daemon"]
    assert receipt["inner_only_command_images_prepared"] is True
    assert receipt["docker_cli_explicit_binding"] is True
    assert receipt["remote_docker_endpoint_used"] is False


def test_v115_harness_initialize_uses_the_same_explicit_inner_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_root = tmp_path / "socket"
    socket_root.mkdir()
    socket_path = socket_root / "docker.sock"
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.bind(str(socket_path))
    manifest = _bound_manifest(socket_path)
    root = tmp_path / "evidence"
    (root / "preflight").mkdir(parents=True)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_root)
    monkeypatch.setenv("DOCKER_HOST", f"unix://{socket_path}")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv(runner.API_KEY_ENV, raising=False)
    monkeypatch.delenv(runner.BASE_URL_ENV, raising=False)
    observed: dict[str, Any] = {}

    settings = SimpleNamespace(
        configuration_fingerprint="configuration-fingerprint",
        controller_image_id=manifest.controller_image_id,
        controller_image_provenance="offline-load",
    )

    def helper(*args: Any, **kwargs: Any) -> SimpleNamespace:
        del args
        observed.update(kwargs)
        assert os.environ[runner.API_KEY_ENV].startswith("v115-offline-")
        assert os.environ[runner.BASE_URL_ENV] == "http://127.0.0.1:9/v1"
        return SimpleNamespace(
            events=(),
            provider_request_started=False,
            finish_reason=None,
            final_response="",
            format_repairs=(),
            run_interval_count=0,
        )

    monkeypatch.setattr(runner, "resolve_settings", lambda *args, **kwargs: settings)
    monkeypatch.setattr(runner, "run_harness_helper", helper)
    try:
        receipt = runner._harness_initialize_preflight(  # noqa: SLF001
            manifest,
            controller_receipt_hash="controller-receipt",
            root=root,
        )
    finally:
        endpoint.close()

    assert observed["docker_host"] == f"unix://{socket_path}"
    assert receipt["same_endpoint_as_runtime_prepare"] is True
    assert receipt["controller_initialized_on_inner_daemon"] is True
    assert receipt["provider_request_started"] is False
    assert runner.API_KEY_ENV not in os.environ
    assert runner.BASE_URL_ENV not in os.environ


def test_v115_progress_writer_calls_the_frozen_base_writer(tmp_path: Path) -> None:
    progress = {
        "schema_version": "1.0",
        "format_id": "predecessor",
        "identity": runner.IDENTITY,
        "status": "completed_pending_independent_v113_audit",
        "provider_calls": 0,
    }
    runner._write_progress(tmp_path, progress)  # noqa: SLF001
    written = runner.v94._load_json(tmp_path / "execution-scaffold-progress.json")  # noqa: SLF001

    assert written["format_id"] == "verigym_deepseek_harness_hwe_v115_scaffold_progress_v1"
    assert written["status"] == "completed_pending_independent_v116_audit"
    assert written["nested_docker_host"] == (
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket/docker.sock"
    )
    assert written["v112_data_volume_reused"] is False
    assert written["provider_calls"] == 0
    assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]  # noqa: SLF001


def test_v115_static_bindings_accept_only_the_audited_v112_stop() -> None:
    manifest = runner._load_composed_manifest(runner.MANIFEST)  # noqa: SLF001
    v92_manifest = load_v92_official_matrix_manifest(
        runner.v112.v109.v106.v103.v100.v97.V92_MANIFEST
    )
    report = runner.v94._load_json(runner.v112.v109.v106.v103.v100.v97.V92_REPORT)  # noqa: SLF001
    with (  # noqa: SLF001
        runner._v115_configuration(),
        runner.v112._v112_configuration(),
        runner.v112.v109._v109_configuration(),
        runner.v112.v109.v106._v106_configuration(),
        runner.v112.v109.v106.v103._v103_configuration(),
        runner.v112.v109.v106.v103.v100._v100_base_configuration(),
    ):
        runner._validate_static_bindings(  # noqa: SLF001
            manifest,
            v92_manifest,
            report,
            v92_manifest_path=runner.v112.v109.v106.v103.v100.v97.V92_MANIFEST,
            v92_report_path=runner.v112.v109.v106.v103.v100.v97.V92_REPORT,
        )


def test_v115_refuses_provider_environment_before_creating_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    arguments = argparse.Namespace(post_merge_main_run_id=33810326256)

    with runner._v115_configuration(), pytest.raises(ConfigurationError, match="provider"):
        runner.v112.materialize(arguments)


def test_v115_does_not_modify_the_frozen_v112_runner() -> None:
    assert runner.v69._hash_file(runner.V112_RUNNER) == (  # noqa: SLF001
        "c4653f2e141c0efcc21171e9e285643dd3cb28f5d52db6d4b5075cae6f16661f"
    )
