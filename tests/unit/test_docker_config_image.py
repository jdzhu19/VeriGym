from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import ValidationError

from verigym.registry.collections import build_registries
from verigym.runtimes.docker import runtime as docker_runtime_module
from verigym.runtimes.docker.engine import EngineResult
from verigym.runtimes.docker.errors import DockerCapabilityError, DockerImageError
from verigym.runtimes.docker.image import inspect_backend, resolve_image
from verigym.runtimes.docker.resources import (
    effective_timeout,
    resource_arguments,
    resource_summary,
)
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import RuntimeDescriptor
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig, DockerRuntimeConfig
from verigym.schemas.tool import CompletedCommand

IMAGE_ID = "sha256:" + "a" * 64


class ImageEngine:
    backend_type = "fake_docker"

    def __init__(
        self,
        *,
        present: bool = True,
        image_id: str = IMAGE_ID,
        repository_digests: list[str] | None = None,
        user: str = "10001:10001",
        capabilities: bool = True,
    ) -> None:
        self.present = present
        self.image_id = image_id
        self.repository_digests = repository_digests
        self.user = user
        self.capabilities = capabilities
        self.inspect_calls: list[str] = []
        self.pull_calls: list[str] = []

    def version(self) -> dict[str, Any]:
        return {
            "Client": {"Version": "25.0.0"},
            "Server": {
                "Version": "25.0.1",
                "ApiVersion": "1.44",
                "Os": "linux",
                "Arch": "amd64",
            },
        }

    def info(self) -> dict[str, Any]:
        return {
            "MemoryLimit": self.capabilities,
            "SwapLimit": self.capabilities,
            "CpuCfsPeriod": self.capabilities,
            "CpuCfsQuota": self.capabilities,
            "PidsLimit": self.capabilities,
            "SecurityOptions": ["name=seccomp,profile=builtin", "name=rootless"],
        }

    def inspect_image(self, reference: str) -> dict[str, Any] | None:
        self.inspect_calls.append(reference)
        if not self.present:
            return None
        return {
            "Id": self.image_id,
            "RepoDigests": self.repository_digests,
            "Created": "2026-01-02T03:04:05Z",
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {"User": self.user, "Env": ["PATH=/usr/bin"]},
        }

    def pull_image(self, reference: str) -> None:
        self.pull_calls.append(reference)
        self.present = True

    def create_container(self, arguments: list[str]) -> str:  # pragma: no cover - protocol stub
        raise AssertionError(arguments)

    def inspect_container(self, container_id: str) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError(container_id)

    def start_attach(
        self, container_id: str, *, timeout_s: int, max_output_bytes: int
    ) -> EngineResult:  # pragma: no cover
        raise AssertionError((container_id, timeout_s, max_output_bytes))

    def kill_container(self, container_id: str) -> EngineResult:  # pragma: no cover
        raise AssertionError(container_id)

    def remove_container(
        self, container_id: str, *, force: bool = True
    ) -> EngineResult:  # pragma: no cover
        raise AssertionError((container_id, force))

    def list_managed_containers(self) -> list[str]:
        return []

    def list_managed_volumes(self) -> list[str]:
        return []

    def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("memory_bytes", 1),
        ("cpus", 0),
        ("pids_limit", 1),
        ("tmpfs_bytes", 1),
        ("stop_timeout_s", 0),
        ("max_command_time_s", 0),
        ("network_mode", "bridge"),
        ("read_only_rootfs", False),
        ("pull_policy", "always"),
    ],
)
def test_docker_config_rejects_disabled_or_unbounded_controls(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        DockerRuntimeConfig.model_validate({"image": "example:test", field: value})


@pytest.mark.parametrize("name", ["API_TOKEN", "PRIVATE_KEY", "SECRET", "PASSWORD", "AUTH"])
def test_docker_config_rejects_secret_like_environment_names(name: str) -> None:
    with pytest.raises(ValidationError, match="secret-like"):
        DockerRuntimeConfig(image="example:test", environment_allowlist=[name])


@pytest.mark.parametrize("user", ["0", "0:0", "root", "root:10001"])
def test_docker_config_rejects_explicit_root_users(user: str) -> None:
    with pytest.raises(ValidationError, match="root"):
        DockerRuntimeConfig(image="example:test", run_as_user=user)


def test_docker_runtime_is_discoverable_without_a_python_docker_dependency() -> None:
    registries = build_registries(discover_external=False)
    assert "docker" in registries.runtimes.names()
    assert registries.runtimes.get("local").descriptor.isolation_level == "local_trusted"
    assert registries.runtimes.get("docker").descriptor.isolation_level == "docker_standard"


def test_exact_immutable_image_observations_are_cached_only_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier_id = "sha256:" + "c" * 64
    agent_id = "sha256:" + "d" * 64

    class RoleImageEngine(ImageEngine):
        def inspect_image(self, reference: str) -> dict[str, Any] | None:
            payload = super().inspect_image(reference)
            assert payload is not None
            payload["Id"] = agent_id if reference == "agent:test" else verifier_id
            return payload

    docker_runtime_module._IMAGE_OBSERVATION_CACHE.clear()
    counts = {"verifier": 0, "agent": 0}

    def probe_verifier(runtime: DockerRuntime) -> None:
        counts["verifier"] += 1
        assert runtime._descriptor.image is not None
        runtime._descriptor.image = runtime._descriptor.image.model_copy(
            update={
                "observed_uid": 1004,
                "observed_gid": 100,
                "iverilog_version": "Icarus Verilog version 12.0",
                "vvp_version": "Icarus Verilog runtime version 12.0",
                "compatibility_status": "canonical_or_reference_compatible",
            }
        )
        assert runtime._descriptor.security is not None
        runtime._descriptor.security = runtime._descriptor.security.model_copy(
            update={"observed_uid": 1004, "observed_gid": 100}
        )

    def probe_agent(runtime: DockerRuntime) -> None:
        counts["agent"] += 1
        assert runtime._agent_image is not None
        runtime._agent_image = runtime._agent_image.model_copy(
            update={
                "observed_uid": 1004,
                "observed_gid": 100,
                "compatibility_status": "codex-cli 0.144.6",
            }
        )

    monkeypatch.setattr(DockerRuntime, "_probe_image", probe_verifier)
    monkeypatch.setattr(DockerRuntime, "_probe_agent_image", probe_agent)
    config = DockerRuntimeConfig(
        image="verifier:test",
        expected_image_id=verifier_id,
        run_as_user=f"{os.getuid()}:{os.getgid()}",
        external_agent=DockerExternalAgentRuntimeConfig(
            image="agent:test",
            expected_image_id=agent_id,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.144.6",
            expected_executable_sha256="e" * 64,
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels={"org.example.credentials": "absent"},
            run_as_user=f"{os.getuid()}:{os.getgid()}",
        ),
    )
    first = DockerRuntime(config, engine=RoleImageEngine())
    first.prepare("cache-first")
    assert first.environment_summary()["image_observation_source"] == "fresh_probe"
    first.close()
    second = DockerRuntime(config, engine=RoleImageEngine())
    second.prepare("cache-second")
    assert second.environment_summary()["image_observation_source"] == (
        "in_process_immutable_cache"
    )
    second.close()
    assert counts == {"verifier": 1, "agent": 1}
    docker_runtime_module._IMAGE_OBSERVATION_CACHE.clear()


def test_pre_milestone7_local_runtime_and_command_artifacts_remain_loadable() -> None:
    legacy_runtime = RuntimeDescriptor.model_validate(
        {
            "schema_version": "1.0",
            "name": "local",
            "version": "0.1.0",
            "api_version": "1.0",
            "provider": "verigym",
            "capabilities": ["trusted_local", "timeouts", "bounded_output"],
            "isolation_level": "local_trusted",
            "deterministic": True,
        }
    )
    assert legacy_runtime.backend is None
    assert legacy_runtime.image is None
    assert legacy_runtime.sessions == []
    assert legacy_runtime.cleanup is None
    legacy_command = CompletedCommand.model_validate(
        {"argv": ["iverilog"], "cwd": ".", "exit_code": 0}
    )
    assert not legacy_command.oom_killed
    assert legacy_command.failure_origin is None


def test_tag_resolves_once_to_real_engine_identity_without_fabricating_digest() -> None:
    engine = ImageEngine(repository_digests=None)
    identity = resolve_image(engine, DockerRuntimeConfig(image="example:test"))
    assert identity.requested_reference == "example:test"
    assert identity.resolved_image_id == IMAGE_ID
    assert identity.repository_digests is None
    assert identity.os == "linux"
    assert identity.architecture == "amd64"
    assert identity.effective_user == "10001:10001"
    assert engine.inspect_calls == ["example:test"]
    assert engine.pull_calls == []


def test_repository_digest_is_preserved_only_when_engine_reports_it() -> None:
    digest = "example@sha256:" + "b" * 64
    engine = ImageEngine(repository_digests=[digest])
    assert resolve_image(engine, DockerRuntimeConfig(image="example:test")).repository_digests == [
        digest
    ]


def test_image_pull_is_never_default_and_is_explicit_when_selected() -> None:
    missing = ImageEngine(present=False)
    with pytest.raises(DockerImageError, match="unavailable locally"):
        resolve_image(missing, DockerRuntimeConfig(image="example:test"))
    assert missing.pull_calls == []

    explicit = ImageEngine(present=False)
    identity = resolve_image(
        explicit,
        DockerRuntimeConfig(image="example:test", pull_policy="if_missing"),
    )
    assert identity.resolved_image_id == IMAGE_ID
    assert explicit.pull_calls == ["example:test"]
    assert explicit.inspect_calls == ["example:test", "example:test"]


def test_exact_replay_image_id_is_enforced() -> None:
    engine = ImageEngine()
    with pytest.raises(DockerImageError, match="exact replay image ID"):
        resolve_image(
            engine,
            DockerRuntimeConfig(image="example:test"),
            expected_image_id="sha256:" + "c" * 64,
        )


def test_invalid_image_identity_root_user_and_image_environment_fail_closed() -> None:
    with pytest.raises(DockerImageError, match="sha256"):
        resolve_image(
            ImageEngine(image_id="not-a-content-id"),
            DockerRuntimeConfig(image="example:test"),
        )
    with pytest.raises(DockerImageError, match="non-root"):
        resolve_image(
            ImageEngine(user="0"),
            DockerRuntimeConfig(image="example:test"),
        )
    engine = ImageEngine()
    original = engine.inspect_image

    def image_with_secret(reference: str) -> dict[str, Any] | None:
        payload = original(reference)
        assert payload is not None
        payload["Config"]["Env"] = ["PATH=/usr/bin", "CLOUD_TOKEN=secret"]
        return payload

    engine.inspect_image = image_with_secret  # type: ignore[method-assign]
    with pytest.raises(DockerImageError, match="outside the runtime allowlist"):
        resolve_image(engine, DockerRuntimeConfig(image="example:test"))


def test_backend_capabilities_and_rootless_status_are_parsed() -> None:
    backend, _ = inspect_backend(ImageEngine())
    assert backend.client_version == "25.0.0"
    assert backend.server_version == "25.0.1"
    assert backend.api_version == "1.44"
    assert backend.rootless is True
    assert backend.memory_limit_supported is True
    with pytest.raises(DockerCapabilityError, match="mandatory controls"):
        inspect_backend(ImageEngine(capabilities=False))


def test_resource_planning_applies_site_ceiling_and_never_disables_limits() -> None:
    config = DockerRuntimeConfig(image="example:test")
    arguments = resource_arguments(config)
    assert arguments == [
        "--memory",
        str(config.memory_bytes),
        "--memory-swap",
        str(config.memory_bytes),
        "--cpus",
        "1",
        "--pids-limit",
        "128",
    ]
    assert effective_timeout(10, 60) == 10
    assert effective_timeout(120, 60) == 60
    summary = resource_summary(config, max_output_bytes=4096)
    assert summary.memory_bytes == config.memory_bytes
    assert summary.memory_swap_bytes == config.memory_bytes
    assert summary.swap_enforced
    assert summary.stop_timeout_s == config.stop_timeout_s
    assert summary.max_output_bytes == 4096
    assert summary.max_artifact_file_bytes == config.max_artifact_file_bytes
    assert summary.max_artifact_bytes == config.max_artifact_bytes
