from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path

import pytest
from verigym_deepseek_harness.agent import DeepSeekHarnessHweAgentAdapter

from scripts import launch_hwe_deepseek_harness_v158_explicit_endpoint_scaffold as launcher
from scripts import materialize_hwe_deepseek_harness_v158_explicit_endpoint_scaffold as runner
from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    DeepSeekHarnessV158ExplicitEndpointScaffoldManifest,
    load_v92_official_matrix_manifest,
    load_v158_explicit_endpoint_scaffold_manifest,
)
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.runtime import DockerRuntimeConfig

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v158_explicit_endpoint_scaffold_v1.json"
)


def test_v158_manifest_freezes_fresh_data2_resources_and_keeps_collection_closed() -> None:
    manifest = load_v158_explicit_endpoint_scaffold_manifest(_MANIFEST)
    assert manifest.identity == runner.IDENTITY
    assert [int(task.rsplit("-", 1)[1]) for task in manifest.schedule_task_ids] == [
        465,
        1135,
        1780,
        2017,
        2711,
    ]
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.dind_socket_backing.startswith("/data2/")
    assert manifest.nested_docker_host.endswith("/deepseek-harness-hwe-v158/socket/docker.sock")
    assert manifest.fresh_data_volume_required is True
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.actual_service_runtime_path_qualified is True
    assert manifest.harness_agent_endpoint_forwarding_required is True
    assert manifest.provider_credentials_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


def test_v158_manifest_hash_rejects_transport_mutation() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["actual_service_runtime_path_qualified"] = False
    with pytest.raises(ValueError):
        DeepSeekHarnessV158ExplicitEndpointScaffoldManifest.model_validate(value)


def test_v158_authorization_binds_manifest_runner_launcher_and_prior_main_gate() -> None:
    authorization = (
        _REPOSITORY_ROOT
        / "docs/audits/2026-09-05_deepseek-harness-v158-explicit-endpoint-scaffold-authorization.md"
    ).read_text(encoding="utf-8")
    assert hashlib.sha256(_MANIFEST.read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest() in authorization
    assert "33959974205" in authorization


def test_v158_launcher_removes_provider_and_ambient_docker_names() -> None:
    source = {
        "PATH": os.environ["PATH"],
        "VERIGYM_DEEPSEEK_API_KEY": "do-not-read-or-copy",
        "VERIGYM_DEEPSEEK_API_BASE_URL": "do-not-read-or-copy",
        "DOCKER_HOST": "tcp://untrusted.example:2375",
        "DOCKER_CONTEXT": "untrusted",
    }
    child = launcher._sanitized_child_environment(source)  # noqa: SLF001
    assert child["PATH"] == source["PATH"]
    assert child[runner.OPT_IN_ENV] == "1"
    assert child[runner.CHILD_BOUNDARY_ENV] == "1"
    assert not set(launcher._blocked_child_environment_names()) & set(child)  # noqa: SLF001


def test_v158_runner_refuses_an_unverified_child_before_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(runner.CHILD_BOUNDARY_ENV, raising=False)
    with pytest.raises(ConfigurationError, match="verified provider-free child"):
        runner._require_v158_environment_boundary()  # noqa: SLF001


def test_v158_service_registry_uses_a_reusable_explicit_runtime_template() -> None:
    docker_host = "unix:///data2/jiadongzhu/docker/v158-test/docker.sock"
    service, template = runner._bound_runtime_registry(docker_host)  # noqa: SLF001
    assert service.registries.runtimes.get("docker") is template
    first = template.configure(DockerRuntimeConfig(image="example:first", pull_policy="never"))
    second = template.configure(DockerRuntimeConfig(image="example:second", pull_policy="never"))
    assert isinstance(first, DockerRuntime)
    assert isinstance(second, DockerRuntime)
    assert first is not second
    assert first._docker_host == docker_host  # noqa: SLF001
    assert second._docker_host == docker_host  # noqa: SLF001
    assert first._engine is None  # noqa: SLF001
    assert second._engine is None  # noqa: SLF001


def test_v158_agent_forwards_the_frozen_settings_endpoint() -> None:
    source = inspect.getsource(DeepSeekHarnessHweAgentAdapter.act)
    assert "docker_host=settings.docker_host" in source


@pytest.mark.skipif(not runner.V156_REPORT.is_file(), reason="sealed v156 evidence is not local")
def test_v158_predecessor_chain_and_schedule_are_exact() -> None:
    composed = runner._load_composed_manifest(_MANIFEST)  # noqa: SLF001
    v92_manifest = load_v92_official_matrix_manifest(runner.v148.v94.V92_MANIFEST)
    v92_report = runner._load_json(runner.v148.v94.V92_REPORT)  # noqa: SLF001
    runner._validate_static_bindings(  # noqa: SLF001
        composed,
        v92_manifest,
        v92_report,
        v92_manifest_path=runner.v148.v94.V92_MANIFEST,
        v92_report_path=runner.v148.v94.V92_REPORT,
    )
    assert [item.task_id for item in composed.schedule] == list(
        load_v158_explicit_endpoint_scaffold_manifest(_MANIFEST).schedule_task_ids
    )
