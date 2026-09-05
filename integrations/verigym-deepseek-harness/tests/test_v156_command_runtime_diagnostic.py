from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    load_v156_command_runtime_diagnostic_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock
from verigym.runtimes.docker.errors import DockerImageError

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import (  # noqa: E402
    launch_hwe_deepseek_harness_v156_command_runtime_diagnostic as launcher,
)
from scripts import (  # noqa: E402
    run_hwe_deepseek_harness_v156_command_runtime_diagnostic as runner,
)


def _arguments() -> argparse.Namespace:
    return argparse.Namespace(
        manifest=runner.MANIFEST,
        output=runner.OUTPUT_ROOT,
        post_merge_main_run_id=33957607230,
    )


def test_v156_manifest_and_paths_are_fresh_and_provider_free() -> None:
    manifest = load_v156_command_runtime_diagnostic_manifest(runner.MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.v155_audit_merge == "1cba9d58de2fe8bd4952e4494d96e0bd75edd3ae"
    assert manifest.v155_post_merge_main_run_id == 33957607230
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v156-dind-data"
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v156-dind-socket"
    assert manifest.dind_data_backing.startswith("/data2/jiadongzhu/docker/")
    assert "v148" not in manifest.dind_data_backing
    assert manifest.expected_inherited_environment_subreason == "image_missing"
    assert manifest.explicit_nested_engine_expected_pass is True
    assert manifest.archive_import_timeout_seconds == 1800
    assert manifest.archive_import_maximum_output_bytes == 1048576
    assert manifest.explicit_archive_import_required is True
    assert manifest.structured_subreason_required is True
    assert manifest.v148_volume_inspection_allowed is False
    assert manifest.v148_volume_mutation_allowed is False
    assert manifest.provider_credentials_available is False
    assert manifest.provider_calls == 0
    assert manifest.requires_independent_v157_audit is True


def test_v156_static_preflight_binds_v154_failure_without_opening_v148_volume() -> None:
    manifest = load_v156_command_runtime_diagnostic_manifest(runner.MANIFEST)
    source = inspect.getsource(runner._validate_static_predecessors)

    assert "v148-dind-data" not in source
    assert "deepseek-harness-hwe-v148/data" not in source
    receipt, task, source_lock = runner._validate_static_predecessors(manifest)

    assert receipt["v154_report_hash"] == manifest.v154_report_hash
    assert receipt["v154_attempt_hash"] == manifest.v154_attempt_hash
    assert receipt["v154_provider_consumed"] is False
    assert receipt["v148_reopen_budget_consumed"] is True
    assert receipt["v148_volume_inspected"] is False
    assert receipt["v148_volume_mutated"] is False
    assert task.task_id == manifest.task_id
    assert source_lock.task_id == manifest.task_id


def test_v156_launcher_removes_all_provider_and_docker_endpoints() -> None:
    source = {
        "PATH": "/usr/bin",
        "UNRELATED": "kept",
        "DOCKER_HOST": "must-not-read",
        "DOCKER_CONTEXT": "must-not-read",
        **{name: "must-not-read" for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES},
    }

    child = launcher._sanitized_child_environment(source)

    assert child["UNRELATED"] == "kept"
    assert child[runner.OPT_IN_ENV] == "1"
    assert child[runner.CHILD_BOUNDARY_ENV] == "1"
    assert not set(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES).intersection(child)
    assert "DOCKER_HOST" not in child
    assert "DOCKER_CONTEXT" not in child


def test_v156_boundary_rejects_provider_names_before_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(runner.CHILD_BOUNDARY_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")

    with pytest.raises(ConfigurationError, match="contaminated"):
        runner._require_execution_boundary(_arguments())


def test_v156_boundary_requires_exact_child_marker_and_postmerge_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, "DOCKER_HOST", "DOCKER_CONTEXT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.delenv(runner.CHILD_BOUNDARY_ENV, raising=False)
    with pytest.raises(ConfigurationError, match="child boundary"):
        runner._require_execution_boundary(_arguments())

    monkeypatch.setenv(runner.CHILD_BOUNDARY_ENV, "1")
    changed = _arguments()
    changed.post_merge_main_run_id = 0
    with pytest.raises(ConfigurationError, match="post-merge"):
        runner._require_execution_boundary(changed)


def test_v156_dual_probe_recovers_the_v154_transport_subreason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v156_command_runtime_diagnostic_manifest(runner.MANIFEST)
    lock = HweCommandImageLock.model_validate_json(runner.V148_COMMAND_LOCK.read_bytes())
    observed: list[tuple[str, object | None]] = []

    class FakeEngine:
        def __init__(self, *, docker_host: str) -> None:
            assert docker_host == manifest.nested_docker_host

    class FakeRuntime:
        def __init__(self, config: object, engine: object | None = None) -> None:
            del config
            self.engine = engine

        def prepare(self, run_id: str) -> None:
            observed.append((run_id, self.engine))
            if self.engine is None:
                raise DockerImageError("not persisted", subreason="image_missing")

        def close(self) -> None:
            pass

    monkeypatch.setattr(runner.v136, "DockerCliEngine", FakeEngine)
    monkeypatch.setattr(runner.v136, "DockerRuntime", FakeRuntime)
    monkeypatch.setattr(runner.v136, "_host_command_image_absent", lambda _image_id: True)
    monkeypatch.setattr(
        runner.v136.v130,
        "_inner_inventory",
        lambda: {"status": "passed", "all_container_count": 0, "all_volume_count": 0},
    )

    with runner._v156_bindings():
        diagnostic = runner.v136._diagnose_runtime_binding(manifest, lock)

    assert diagnostic["status"] == "confirmed"
    assert diagnostic["diagnosis"] == "docker_cli_missing_explicit_nested_endpoint_binding"
    assert diagnostic["inherited_environment_subreason"] == "image_missing"
    assert diagnostic["explicit_nested_engine_probe_passed"] is True
    assert diagnostic["v154_missing_subreason_recovered"] is True
    assert diagnostic["ambient_docker_host_inheritance_used"] is False
    assert diagnostic["explicit_nested_docker_engine_used"] is True
    assert diagnostic["provider_calls"] == 0
    assert len(observed) == 2


def test_v156_module_bindings_are_scoped() -> None:
    names = (
        "IDENTITY",
        "OUTPUT_ROOT",
        "DIND_DATA_BACKING",
        "DIND_SOCKET_BACKING",
        "RUNTIME_SCRATCH",
        "_DAEMON_NAME",
    )
    before = {name: getattr(runner.v136, name) for name in names}
    before_import = runner.v136.v130.v69._load_completed_archive
    before_cleanup = runner.v136.v130._cleanup

    with runner._v156_bindings():
        assert runner.v136.IDENTITY == runner.IDENTITY
        assert runner.v136.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert runner.v136.V132_COMMAND_LOCK == runner.V148_COMMAND_LOCK
        assert runner.v136.v130.v69._load_completed_archive is runner._load_completed_archive
        assert runner.v136.v130._cleanup is runner._cleanup

    assert {name: getattr(runner.v136, name) for name in names} == before
    assert runner.v136.v130.v69._load_completed_archive is before_import
    assert runner.v136.v130._cleanup is before_cleanup


def test_v156_report_keeps_collection_closed_and_subreason_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v156_command_runtime_diagnostic_manifest(runner.MANIFEST)
    report = runner._base_report(
        manifest,
        source_commit="a" * 40,
        post_merge_main_run_id=33957607230,
    )
    source = inspect.getsource(runner._diagnose_runtime_binding)

    assert report["task_execution_started"] is False
    assert report["base_reference_verification_started"] is False
    assert report["harness_controller_started"] is False
    assert report["provider_request_started"] is False
    assert report["provider_calls"] == 0
    assert report["formal_collection_allowed"] is False
    assert report["training_started"] is False
    assert report["requires_independent_v157_audit"] is True
    assert "str(exc)" not in source
    assert "exc.details" not in source

    monkeypatch.setattr(
        runner,
        "_BASE_V136_DIAGNOSE_BINDING",
        lambda *_args: {
            "schema_version": "1.0",
            "format_id": "old",
            "identity": "old",
            "status": "not_confirmed",
            "diagnosis": "expected_transport_binding_diagnosis_not_confirmed",
            "provider_calls": 0,
            "diagnostic_hash": "0" * 64,
        },
    )
    diagnostic = runner._diagnose_runtime_binding(
        manifest,
        HweCommandImageLock.model_validate_json(runner.V148_COMMAND_LOCK.read_bytes()),
    )
    assert diagnostic["v154_missing_subreason_recovered"] is False
    assert "raw message" not in json.dumps(diagnostic, sort_keys=True)


def test_v156_diagnose_promotes_only_the_v157_pending_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = {
        "schema_version": "1.0",
        "format_id": "old",
        "identity": runner.IDENTITY,
        "status": "diagnosed_pending_independent_v137_audit",
        "diagnosis": "docker_cli_missing_explicit_nested_endpoint_binding",
        "diagnosis_confirmed": True,
        "cleanup_confirmed": True,
        "provider_calls": 0,
        "requires_independent_v137_audit": True,
    }
    monkeypatch.setattr(runner.v136, "diagnose", lambda _arguments: dict(report))
    monkeypatch.setattr(runner, "OUTPUT_ROOT", tmp_path)

    promoted = runner.diagnose(_arguments())

    assert promoted["status"] == "diagnosed_pending_independent_v157_audit"
    assert promoted["requires_independent_v157_audit"] is True
    assert "requires_independent_v137_audit" not in promoted
    assert (tmp_path / "command-runtime-report.json").is_file()


def test_v156_source_uses_explicit_local_archive_import_and_no_provider() -> None:
    import_source = inspect.getsource(runner._load_completed_archive)
    binding_source = inspect.getsource(runner._diagnose_runtime_binding)

    assert "_explicit_archive_import" in import_source
    assert "DIND_SOCKET_BACKING" in import_source
    assert "v148-dind-data" not in import_source
    assert "provider" not in binding_source.lower()
    assert os.path.isabs(str(runner.DIND_DATA_BACKING))
