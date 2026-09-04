from __future__ import annotations

import argparse
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    load_v136_command_runtime_diagnostic_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock
from verigym.runtimes.docker.errors import DockerImageError

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import (  # noqa: E402
    run_hwe_deepseek_harness_v136_command_runtime_diagnostic as runner,
)


def _completed(
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_v136_manifest_freezes_a_fresh_provider_free_dual_probe() -> None:
    manifest = load_v136_command_runtime_diagnostic_manifest(runner.MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.v135_audit_merge == "da971e808b8da441d01ce7f76445fe6284939cd7"
    assert manifest.v135_post_merge_main_run_id == 33856107497
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v136-dind-data"
    assert manifest.dind_data_backing.startswith("/data2/jiadongzhu/docker/")
    assert manifest.inherited_environment_probe_count == 1
    assert manifest.explicit_nested_engine_probe_count == 1
    assert manifest.expected_inherited_environment_subreason == "image_missing"
    assert manifest.docker_cli_explicit_binding_required is True
    assert manifest.historical_command_image_id_required is False
    assert manifest.historical_command_image_semantics_required is True
    assert manifest.v132_volume_inspection_allowed is False
    assert manifest.v132_volume_mutation_allowed is False
    assert manifest.provider_calls == 0
    assert all(
        getattr(manifest, name) is False
        for name in (
            "task_execution_allowed",
            "base_reference_verification_allowed",
            "harness_controller_allowed",
            "registry_access_allowed",
            "partial_archive_allowed",
            "provider_credentials_available",
            "formal_collection_allowed",
            "training_started",
            "production_training_ready",
        )
    )


def test_v136_static_preflight_uses_files_and_never_the_v132_volume() -> None:
    manifest = load_v136_command_runtime_diagnostic_manifest(runner.MANIFEST)
    source = inspect.getsource(runner._validate_static_predecessors)

    assert "v132-dind-data" not in source
    assert "deepseek-harness-hwe-v132/data" not in source
    receipt, task, source_lock = runner._validate_static_predecessors(manifest)

    assert receipt["status"] == "passed"
    assert receipt["all_five_tasks_provider_unconsumed"] is True
    assert receipt["v132_reopen_budget_consumed"] is True
    assert receipt["v132_volume_inspected"] is False
    assert task.task_id == manifest.task_id
    assert source_lock.task_id == manifest.task_id


def test_v136_dual_probe_confirms_missing_explicit_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v136_command_runtime_diagnostic_manifest(runner.MANIFEST)
    lock = HweCommandImageLock.model_validate_json(runner.V132_COMMAND_LOCK.read_bytes())
    observed: list[tuple[str, object | None]] = []

    class FakeEngine:
        def __init__(self, *, docker_host: str) -> None:
            assert docker_host == manifest.nested_docker_host

    class FakeRuntime:
        def __init__(self, config: object, engine: object | None = None) -> None:
            observed.append(("construct", engine))
            self.engine = engine

        def prepare(self, run_id: str) -> None:
            observed.append((run_id, self.engine))
            if self.engine is None:
                raise DockerImageError("not persisted", subreason="image_missing")

        def close(self) -> None:
            observed.append(("close", self.engine))

    monkeypatch.setattr(runner, "DockerCliEngine", FakeEngine)
    monkeypatch.setattr(runner, "DockerRuntime", FakeRuntime)
    monkeypatch.setattr(runner, "_host_command_image_absent", lambda _image_id: True)
    monkeypatch.setattr(
        runner.v130,
        "_inner_inventory",
        lambda: {
            "status": "passed",
            "all_container_count": 0,
            "all_volume_count": 0,
        },
    )

    diagnostic = runner._diagnose_runtime_binding(manifest, lock)

    assert diagnostic["status"] == "confirmed"
    assert diagnostic["diagnosis"] == "docker_cli_missing_explicit_nested_endpoint_binding"
    assert diagnostic["inherited_environment_subreason"] == "image_missing"
    assert diagnostic["explicit_nested_engine_probe_passed"] is True
    assert diagnostic["provider_calls"] == 0
    assert any(name == "v136-inherited-environment-probe" for name, _ in observed)
    assert any(name == "v136-explicit-nested-engine-probe" for name, _ in observed)


def test_v136_command_lock_comparison_ignores_only_fresh_identity_fields() -> None:
    original = HweCommandImageLock.model_validate_json(runner.V132_COMMAND_LOCK.read_bytes())
    rebuilt = original.model_copy(
        update={
            "derived_command_image_id": "sha256:" + "a" * 64,
            "security_scan_id": "b" * 64,
            "lock_hash": "c" * 64,
        }
    )

    assert runner._command_lock_semantics(original) == runner._command_lock_semantics(rebuilt)
    changed = rebuilt.model_copy(update={"rg_sha256": "d" * 64})
    assert runner._command_lock_semantics(original) != runner._command_lock_semantics(changed)


def test_v136_host_absence_check_drops_inherited_nested_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run(arguments: list[str], *, timeout: float, env: object = None) -> object:
        observed.update(arguments=arguments, timeout=timeout, env=env)
        return _completed(returncode=1)

    monkeypatch.setenv("DOCKER_HOST", "unix:///fresh-nested/docker.sock")
    monkeypatch.setenv("DOCKER_CONTEXT", "forbidden-context")
    monkeypatch.setattr(runner.v130, "_run", run)

    assert runner._host_command_image_absent("sha256:" + "a" * 64) is True
    assert "DOCKER_HOST" not in observed["env"]
    assert "DOCKER_CONTEXT" not in observed["env"]


def test_v136_unallowlisted_image_error_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v136_command_runtime_diagnostic_manifest(runner.MANIFEST)
    lock = HweCommandImageLock.model_validate_json(runner.V132_COMMAND_LOCK.read_bytes())

    class FakeEngine:
        def __init__(self, *, docker_host: str) -> None:
            del docker_host

    class FakeRuntime:
        def __init__(self, config: object, engine: object | None = None) -> None:
            del config
            self.engine = engine

        def prepare(self, run_id: str) -> None:
            del run_id
            if self.engine is None:
                raise DockerImageError("secret-bearing raw message", subreason="new_subreason")

        def close(self) -> None:
            pass

    monkeypatch.setattr(runner, "DockerCliEngine", FakeEngine)
    monkeypatch.setattr(runner, "DockerRuntime", FakeRuntime)
    monkeypatch.setattr(runner, "_host_command_image_absent", lambda _image_id: True)
    monkeypatch.setattr(
        runner.v130,
        "_inner_inventory",
        lambda: {
            "status": "passed",
            "all_container_count": 0,
            "all_volume_count": 0,
        },
    )

    diagnostic = runner._diagnose_runtime_binding(manifest, lock)
    serialized = json.dumps(diagnostic, sort_keys=True)

    assert diagnostic["status"] == "not_confirmed"
    assert diagnostic["inherited_environment_subreason"] == ("unallowlisted_docker_image_error")
    assert "secret-bearing" not in serialized
    assert "new_subreason" not in serialized


def test_v136_refuses_provider_environment_before_any_output(
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


def test_v136_runtime_environment_binds_socket_and_restores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v136_command_runtime_diagnostic_manifest(runner.MANIFEST)
    socket_root = tmp_path / "socket"
    runtime_root = tmp_path / "runtime"
    socket_root.mkdir()
    runtime_root.mkdir()
    socket_path = socket_root / "docker.sock"
    socket_path.touch()
    monkeypatch.setattr(Path, "is_socket", lambda self: self == socket_path)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_root)
    monkeypatch.setattr(runner, "RUNTIME_SCRATCH", runtime_root)
    changed = manifest.model_copy(update={"nested_docker_host": f"unix://{socket_path}"})
    monkeypatch.setenv("TMPDIR", "/original-tmp")
    os.environ.pop("DOCKER_HOST", None)

    with runner._nested_runtime_environment(changed):
        assert os.environ["DOCKER_HOST"] == f"unix://{socket_path}"
        assert os.environ["TMPDIR"] == str(runtime_root)
        assert "DOCKER_CONTEXT" not in os.environ

    assert "DOCKER_HOST" not in os.environ
    assert os.environ["TMPDIR"] == "/original-tmp"


def test_v136_transfer_is_content_free_and_identity_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v136_command_runtime_diagnostic_manifest(runner.MANIFEST)
    host = [{"Id": manifest.workspace_runtime_image_id}]
    monkeypatch.setattr(runner.v130, "_docker_json", lambda *_args, **_kwargs: host)
    monkeypatch.setattr(runner.dind, "_pipe_image", lambda **_kwargs: (b"ok", b""))
    monkeypatch.setattr(
        runner.dind,
        "_inner",
        lambda arguments, **_kwargs: (
            _completed(returncode=1)
            if "--format" not in arguments
            else _completed((manifest.workspace_runtime_image_id + "\n").encode())
        ),
    )

    receipt = runner._transfer_workspace_runtime(manifest)

    assert receipt["status"] == "passed"
    assert receipt["inner_image_id_verified"] is True
    assert receipt["transfer_archive_persisted"] is False
    assert receipt["raw_transfer_output_persisted"] is False
    assert receipt["provider_calls"] == 0


def test_v136_closed_report_never_claims_collection() -> None:
    manifest = load_v136_command_runtime_diagnostic_manifest(runner.MANIFEST)
    report = runner._base_report(
        manifest,
        source_commit="a" * 40,
        post_merge_main_run_id=1,
    )
    source = inspect.getsource(runner._diagnose_runtime_binding)

    assert report["task_execution_started"] is False
    assert report["base_reference_verification_started"] is False
    assert report["harness_controller_started"] is False
    assert report["provider_request_started"] is False
    assert report["provider_calls"] == 0
    assert report["formal_collection_allowed"] is False
    assert report["training_started"] is False
    assert "str(exc)" not in source
    assert "exc.details" not in source


def test_v136_v130_configuration_is_scoped() -> None:
    before = {name: getattr(runner.v130, name) for name in runner._V130_PATCH_NAMES}

    with runner._v136_v130_configuration():
        assert runner.v130.IDENTITY == runner.IDENTITY
        assert runner.v130.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
        assert runner.v130._DAEMON_NAME == runner._DAEMON_NAME

    assert {name: getattr(runner.v130, name) for name in runner._V130_PATCH_NAMES} == before
