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
    load_v118_explicit_inner_inventory_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold as runner,
)


def _purpose_manifest() -> Any:
    return load_v118_explicit_inner_inventory_scaffold_manifest(runner.MANIFEST)


def _bound_manifest(socket_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        nested_docker_host=f"unix://{socket_path}",
        docker_host_binding_policy="explicit-canonical-local-unix-socket-v1",
        inner_inventory_transport_policy="explicit-bound-engine-all-resources-v1",
        schedule=[
            SimpleNamespace(task_id="inner-only-image-a", pr_number=1),
            SimpleNamespace(task_id="inner-only-image-b", pr_number=2),
        ],
        runtime_prepare_task_count=2,
        workspace_runtime_image_id="sha256:" + "9" * 64,
        task_network="none",
        preflight_inner_network="verigym-hwe-net",
        preflight_inner_network_internal=True,
        scaffold_outer_network="none",
        inner_network_transport_policy="explicit-bound-engine-v1",
        controller_image_id="sha256:" + "8" * 64,
    )


def _socket(path: Path) -> socket.socket:
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.bind(str(path))
    return endpoint


def test_v118_manifest_freezes_inner_inventory_and_closed_policy() -> None:
    manifest = _purpose_manifest()

    assert manifest.schedule_task_ids == list(V71_MATRIX_TASK_IDS)
    assert manifest.nested_docker_host == (
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v118/socket/docker.sock"
    )
    assert manifest.inner_inventory_transport_policy == "explicit-bound-engine-all-resources-v1"
    assert manifest.inner_inventory_all_containers_required is True
    assert manifest.inner_inventory_all_volumes_required is True
    assert manifest.host_sidecar_inventory_for_inner_allowed is False
    assert manifest.inner_network_transport_policy == "explicit-bound-engine-v1"
    assert manifest.host_sidecar_network_control_for_inner_allowed is False
    assert manifest.streaming_attach_explicit_binding_required is True
    assert manifest.v115_data_volume_reused is False
    assert manifest.v117_identity_retired is True
    assert manifest.provider_successor_identity == "deepseek-harness-hwe-v120-official-matrix-v1"
    assert all(getattr(manifest, name) is False for name in runner.v94._closed_training_flags())


def test_v118_configuration_restores_the_frozen_v115_runner() -> None:
    original = {name: getattr(runner.v115, name) for name in runner._V115_CONFIGURATION_NAMES}
    original_network = {
        name: getattr(runner.v94, name)
        for name in (
            "_create_internal_preflight_network",
            "_remove_internal_preflight_network",
            "_require_preflight_network_absent",
        )
    }

    with runner._v118_configuration():
        assert runner.v115.IDENTITY == runner.IDENTITY
        assert runner.v115.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v115._runtime_prepare_preflight is runner._runtime_prepare_preflight
        assert (
            runner.v94._create_internal_preflight_network
            is runner._create_internal_preflight_network
        )
        with runner._v115_predecessor_configuration():
            assert runner.v115.IDENTITY != runner.IDENTITY
        assert runner.v115.IDENTITY == runner.IDENTITY

    assert all(getattr(runner.v115, name) is value for name, value in original.items())
    assert all(getattr(runner.v94, name) is value for name, value in original_network.items())


def test_v118_runtime_prepare_queries_all_resources_through_each_bound_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_root = tmp_path / "socket"
    socket_root.mkdir()
    socket_path = socket_root / "docker.sock"
    endpoint = _socket(socket_path)
    manifest = _bound_manifest(socket_path)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_root)
    monkeypatch.setenv("DOCKER_HOST", f"unix://{socket_path}")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    calls: list[tuple[str, str]] = []

    class Engine:
        def __init__(self, *, docker_host: str) -> None:
            self.docker_host = docker_host

        def list_all_containers(self) -> list[str]:
            calls.append(("all-containers", self.docker_host))
            return []

        def list_all_volumes(self) -> list[str]:
            calls.append(("all-volumes", self.docker_host))
            return []

        def close(self) -> None:
            calls.append(("close", self.docker_host))

    class Runtime:
        def __init__(self, config: str, *, engine: Engine) -> None:
            self.config = config
            self.engine = engine

        def prepare(self, run_id: str) -> None:
            calls.append((f"prepare:{self.config}:{run_id}", self.engine.docker_host))

        def close(self) -> None:
            self.engine.close()

    monkeypatch.setattr(runner, "DockerCliEngine", Engine)
    monkeypatch.setattr(runner, "DockerRuntime", Runtime)
    monkeypatch.setattr(runner.v92, "_runtime_config", lambda lock: lock)
    try:
        receipt = runner._runtime_prepare_preflight(
            manifest,
            locks={"inner-only-image-a": "image-a", "inner-only-image-b": "image-b"},
            dind_name="outer-sidecar-must-not-be-used",
        )
    finally:
        endpoint.close()

    expected_host = f"unix://{socket_path}"
    assert calls == [
        ("prepare:image-a:v118-preflight-pr-1", expected_host),
        ("all-containers", expected_host),
        ("all-volumes", expected_host),
        ("close", expected_host),
        ("prepare:image-b:v118-preflight-pr-2", expected_host),
        ("all-containers", expected_host),
        ("all-volumes", expected_host),
        ("close", expected_host),
    ]
    assert receipt["inventory_check_count"] == 2
    assert receipt["host_sidecar_inventory_for_inner_used"] is False
    assert receipt["inner_container_inventory_empty"] is True
    assert receipt["inner_volume_inventory_empty"] is True


def test_v118_inner_network_lifecycle_never_targets_the_outer_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_root = tmp_path / "socket"
    socket_root.mkdir()
    socket_path = socket_root / "docker.sock"
    endpoint = _socket(socket_path)
    manifest = _bound_manifest(socket_path)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_root)
    calls: list[tuple[str, str]] = []
    present = False

    class Engine:
        def __init__(self, *, docker_host: str) -> None:
            self.docker_host = docker_host

        def inspect_network(self, name: str) -> dict[str, Any] | None:
            calls.append((f"inspect:{name}", self.docker_host))
            if not present:
                return None
            return {"Name": name, "Driver": "bridge", "Internal": True, "Scope": "local"}

        def create_internal_network(self, name: str) -> str:
            nonlocal present
            calls.append((f"create:{name}", self.docker_host))
            present = True
            return "network-id"

        def remove_network(self, name: str) -> None:
            nonlocal present
            calls.append((f"remove:{name}", self.docker_host))
            present = False

        def close(self) -> None:
            calls.append(("close", self.docker_host))

    monkeypatch.setattr(runner, "DockerCliEngine", Engine)
    try:
        runner._create_internal_preflight_network("outer-sidecar-must-not-be-used", manifest)
        runner._remove_internal_preflight_network("outer-sidecar-must-not-be-used", manifest)
        runner._require_preflight_network_absent("outer-sidecar-must-not-be-used", manifest)
    finally:
        endpoint.close()

    expected_host = f"unix://{socket_path}"
    assert calls == [
        ("inspect:verigym-hwe-net", expected_host),
        ("create:verigym-hwe-net", expected_host),
        ("inspect:verigym-hwe-net", expected_host),
        ("close", expected_host),
        ("remove:verigym-hwe-net", expected_host),
        ("inspect:verigym-hwe-net", expected_host),
        ("close", expected_host),
        ("inspect:verigym-hwe-net", expected_host),
        ("close", expected_host),
    ]


def test_v118_harness_initialize_retains_the_explicit_inner_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_root = tmp_path / "socket"
    socket_root.mkdir()
    socket_path = socket_root / "docker.sock"
    endpoint = _socket(socket_path)
    manifest = _bound_manifest(socket_path)
    root = tmp_path / "evidence"
    (root / "preflight").mkdir(parents=True)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_root)
    monkeypatch.setenv("DOCKER_HOST", f"unix://{socket_path}")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv(runner.v115.API_KEY_ENV, raising=False)
    monkeypatch.delenv(runner.v115.BASE_URL_ENV, raising=False)
    observed: dict[str, Any] = {}
    settings = SimpleNamespace(
        configuration_fingerprint="configuration-fingerprint",
        controller_image_id=manifest.controller_image_id,
        controller_image_provenance="offline-load",
    )

    def helper(*args: Any, **kwargs: Any) -> SimpleNamespace:
        del args
        observed.update(kwargs)
        return SimpleNamespace(
            events=(),
            provider_request_started=False,
            finish_reason=None,
            final_response="",
            format_repairs=(),
            run_interval_count=0,
        )

    monkeypatch.setattr(runner.v115, "resolve_settings", lambda *args, **kwargs: settings)
    monkeypatch.setattr(runner.v115, "run_harness_helper", helper)
    try:
        with runner._v118_configuration():
            receipt = runner._harness_initialize_preflight(
                manifest,
                controller_receipt_hash="controller-receipt",
                root=root,
            )
    finally:
        endpoint.close()

    assert observed["docker_host"] == f"unix://{socket_path}"
    assert receipt["inner_network_transport_policy"] == "explicit-bound-engine-v1"
    assert receipt["host_sidecar_network_control_for_inner_used"] is False
    assert receipt["controller_initialized_on_inner_daemon"] is True
    assert receipt["provider_request_started"] is False
    assert runner.v115.API_KEY_ENV not in os.environ
    assert runner.v115.BASE_URL_ENV not in os.environ


@pytest.mark.parametrize(
    ("containers", "volumes"),
    [(["unlabeled-container"], []), ([], ["unlabeled-volume"])],
)
def test_v118_runtime_prepare_rejects_any_inner_resource(
    containers: list[str],
    volumes: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_root = tmp_path / "socket"
    socket_root.mkdir()
    socket_path = socket_root / "docker.sock"
    endpoint = _socket(socket_path)
    manifest = _bound_manifest(socket_path)
    manifest.schedule = manifest.schedule[:1]
    manifest.runtime_prepare_task_count = 1
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_root)
    monkeypatch.setenv("DOCKER_HOST", f"unix://{socket_path}")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    closed: list[bool] = []

    class Engine:
        def __init__(self, *, docker_host: str) -> None:
            self.docker_host = docker_host

        def list_all_containers(self) -> list[str]:
            return containers

        def list_all_volumes(self) -> list[str]:
            return volumes

        def close(self) -> None:
            closed.append(True)

    class Runtime:
        def __init__(self, config: str, *, engine: Engine) -> None:
            del config
            self.engine = engine

        def prepare(self, run_id: str) -> None:
            del run_id

        def close(self) -> None:
            self.engine.close()

    monkeypatch.setattr(runner, "DockerCliEngine", Engine)
    monkeypatch.setattr(runner, "DockerRuntime", Runtime)
    monkeypatch.setattr(runner.v92, "_runtime_config", lambda lock: lock)
    try:
        with pytest.raises(ConfigurationError, match="inventory is not empty"):
            runner._runtime_prepare_preflight(
                manifest,
                locks={"inner-only-image-a": "image-a"},
                dind_name="outer-sidecar-must-not-be-used",
            )
    finally:
        endpoint.close()

    assert closed == [True]


def test_v118_progress_writer_seals_the_successor_identity(tmp_path: Path) -> None:
    progress = {
        "schema_version": "1.0",
        "format_id": "predecessor",
        "identity": runner.IDENTITY,
        "status": "completed_pending_independent_v116_audit",
        "provider_calls": 0,
    }
    runner._write_progress(tmp_path, progress)
    written = runner.v94._load_json(tmp_path / "execution-scaffold-progress.json")

    assert written["format_id"] == "verigym_deepseek_harness_hwe_v118_scaffold_progress_v1"
    assert written["status"] == "completed_pending_independent_v119_audit"
    assert written["inner_inventory_transport_policy"] == ("explicit-bound-engine-all-resources-v1")
    assert written["v115_data_volume_reused"] is False
    assert written["provider_calls"] == 0
    assert runner.v94._canonical_hash(written, "report_hash") == written["report_hash"]


def test_v118_static_bindings_accept_only_the_audited_v115_stop() -> None:
    manifest = runner._load_composed_manifest(runner.MANIFEST)
    v92_manifest = load_v92_official_matrix_manifest(
        runner.v115.v112.v109.v106.v103.v100.v97.V92_MANIFEST
    )
    report = runner.v94._load_json(runner.v115.v112.v109.v106.v103.v100.v97.V92_REPORT)
    with (
        runner._v118_configuration(),
        runner.v115._v115_configuration(),
        runner.v112._v112_configuration(),
        runner.v112.v109._v109_configuration(),
        runner.v112.v109.v106._v106_configuration(),
        runner.v112.v109.v106.v103._v103_configuration(),
        runner.v112.v109.v106.v103.v100._v100_base_configuration(),
    ):
        runner._validate_static_bindings(
            manifest,
            v92_manifest,
            report,
            v92_manifest_path=runner.v115.v112.v109.v106.v103.v100.v97.V92_MANIFEST,
            v92_report_path=runner.v115.v112.v109.v106.v103.v100.v97.V92_REPORT,
        )


def test_v118_refuses_provider_environment_before_creating_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    arguments = argparse.Namespace(post_merge_main_run_id=33815411217)

    with runner._v118_configuration(), pytest.raises(ConfigurationError, match="provider"):
        runner.v115.materialize(arguments)


def test_v118_does_not_modify_the_frozen_v115_runner() -> None:
    assert runner._hash_git_file(
        "48bc47f0dbb020e41f330bf5350bad621d01df1c", runner.V115_RUNNER
    ) == ("9243002e66e70d2f3b08300afc7bf095a4a99775ced9b38c8294b73df4bd662f")
