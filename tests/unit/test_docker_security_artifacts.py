from __future__ import annotations

import os
from pathlib import Path

import pytest

from verigym.core.errors import PathPolicyError
from verigym.runtimes.docker.artifacts import collect_declared_artifacts
from verigym.runtimes.docker.errors import (
    DockerArtifactError,
    DockerCapabilityError,
    sanitize_diagnostic,
)
from verigym.runtimes.docker.mounts import MountSpec, validate_mount_plan
from verigym.runtimes.docker.security import (
    BASELINE_ENVIRONMENT,
    build_environment,
    security_arguments,
    verify_effective_container,
)
from verigym.schemas.runtime import DockerRuntimeConfig


def test_environment_is_fixed_allowlisted_and_never_inherits_host_secrets(monkeypatch) -> None:
    monkeypatch.setenv("HOST_API_TOKEN", "must-not-enter")
    config = DockerRuntimeConfig(
        image="example:test",
        environment_allowlist=["EXPERIMENT_LABEL"],
    )
    environment = build_environment(
        config,
        {"EXPERIMENT_LABEL": "safe"},
        {},
    )
    assert environment == {**BASELINE_ENVIRONMENT, "EXPERIMENT_LABEL": "safe"}
    assert "HOST_API_TOKEN" not in environment
    with pytest.raises(DockerCapabilityError, match="not allowlisted"):
        build_environment(config, {}, {"UNDECLARED": "value"})


def test_security_arguments_have_no_unsafe_escape_hatches() -> None:
    config = DockerRuntimeConfig(image="example:test")
    arguments = security_arguments(
        config,
        user="10001:10001",
        cwd="/workspace",
        environment=BASELINE_ENVIRONMENT,
        labels={"org.verigym.managed": "true"},
    )
    joined = " ".join(arguments)
    assert "--network none" in joined
    assert "--pid" not in arguments
    assert "--ipc none" in joined
    assert "--read-only" in arguments
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges:true" in joined
    assert f"--stop-timeout {config.stop_timeout_s}" in joined
    assert "--init" in arguments
    assert "--privileged" not in arguments
    assert "/var/run/docker.sock" not in joined


def _effective_payload(root: Path, config: DockerRuntimeConfig) -> dict[str, object]:
    return {
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Init": True,
            "PidMode": "",
            "IpcMode": "none",
            "Memory": config.memory_bytes,
            "MemorySwap": config.memory_bytes,
            "NanoCpus": round(config.cpus * 1_000_000_000),
            "PidsLimit": config.pids_limit,
            "Tmpfs": {"/tmp": (f"rw,noexec,nosuid,nodev,size={config.tmpfs_bytes},mode=1777")},
            "Mounts": [{"Type": "bind", "Source": str(root), "Target": "/workspace"}],
        },
        "Config": {
            "User": "10001:10001",
            "StopTimeout": config.stop_timeout_s,
            "Env": [f"{name}={value}" for name, value in BASELINE_ENVIRONMENT.items()],
            "Labels": {
                "org.verigym.managed": "true",
                "org.verigym.run_id": "run",
            },
        },
    }


def test_effective_security_configuration_is_verified_not_assumed(tmp_path: Path) -> None:
    config = DockerRuntimeConfig(image="example:test")
    mount = MountSpec(source=tmp_path, destination="/workspace", read_only=False)
    labels = {"org.verigym.managed": "true", "org.verigym.run_id": "run"}
    payload = _effective_payload(tmp_path, config)
    verify_effective_container(
        payload,
        config=config,
        expected_user="10001:10001",
        expected_mounts=[mount],
        expected_environment=BASELINE_ENVIRONMENT,
        expected_labels=labels,
    )
    payload["HostConfig"]["NetworkMode"] = "bridge"  # type: ignore[index]
    with pytest.raises(DockerCapabilityError, match="network=none"):
        verify_effective_container(
            payload,
            config=config,
            expected_user="10001:10001",
            expected_mounts=[mount],
            expected_environment=BASELINE_ENVIRONMENT,
            expected_labels=labels,
        )


def test_mount_plan_accepts_only_private_canonical_staging(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    plan = validate_mount_plan(
        [MountSpec(staging, "/workspace", False)],
        approved_roots=(staging,),
        host_home=tmp_path / "home",
        repository_root=tmp_path / "repo",
    )
    assert plan == [MountSpec(staging.resolve(), "/workspace", False)]


def test_mount_plan_rejects_home_repo_socket_overlap_and_symlink(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repository = tmp_path / "repo"
    home.mkdir()
    repository.mkdir()
    with pytest.raises(PathPolicyError, match="home"):
        validate_mount_plan(
            [MountSpec(home, "/workspace", False)],
            approved_roots=(home,),
            host_home=home,
        )
    with pytest.raises(PathPolicyError, match="repository"):
        validate_mount_plan(
            [MountSpec(repository, "/workspace", False)],
            approved_roots=(repository,),
            host_home=home,
            repository_root=repository,
        )
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(PathPolicyError, match="socket"):
        validate_mount_plan(
            [MountSpec(staging, "/var/run/docker.sock", False)],
            approved_roots=(staging,),
            host_home=home,
        )
    nested = staging / "nested"
    nested.mkdir()
    with pytest.raises(PathPolicyError, match="overlap"):
        validate_mount_plan(
            [
                MountSpec(staging, "/workspace", False),
                MountSpec(nested, "/workspace/nested", False),
            ],
            approved_roots=(staging,),
            host_home=home,
        )
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathPolicyError, match="symlink"):
        validate_mount_plan(
            [MountSpec(link, "/workspace", False)],
            approved_roots=(outside,),
            host_home=home,
        )


def test_mount_plan_rejects_sources_outside_approved_root_and_traversal(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    with pytest.raises(PathPolicyError, match="outside"):
        validate_mount_plan(
            [MountSpec(outside, "/workspace", False)],
            approved_roots=(approved,),
            host_home=tmp_path / "home",
        )
    with pytest.raises(PathPolicyError, match="canonical"):
        validate_mount_plan(
            [MountSpec(approved, "/workspace/../escape", False)],
            approved_roots=(approved,),
            host_home=tmp_path / "home",
        )


def test_declared_artifacts_are_hashed_and_bounded(tmp_path: Path) -> None:
    output = tmp_path / "artifacts"
    output.mkdir()
    (output / "result.txt").write_text("ok", encoding="utf-8")
    metadata = collect_declared_artifacts(
        tmp_path,
        ["artifacts/result.txt"],
        max_file_bytes=10,
        max_total_bytes=10,
    )
    assert len(metadata) == 1
    assert metadata[0].path == "artifacts/result.txt"
    assert metadata[0].size_bytes == 2
    assert len(metadata[0].content_hash) == 64
    int(metadata[0].content_hash, 16)


def test_artifact_policy_rejects_traversal_symlink_hardlink_special_and_size(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifacts"
    output.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (output / "escape").symlink_to(outside)
    with pytest.raises(DockerArtifactError, match="symlink"):
        collect_declared_artifacts(
            tmp_path,
            ["artifacts/escape"],
            max_file_bytes=100,
            max_total_bytes=100,
        )
    outside_directory = tmp_path / "outside-directory"
    outside_directory.mkdir()
    (outside_directory / "nested.txt").write_text("outside", encoding="utf-8")
    (output / "linked-directory").symlink_to(outside_directory, target_is_directory=True)
    with pytest.raises(DockerArtifactError, match="symlink"):
        collect_declared_artifacts(
            tmp_path,
            ["artifacts/linked-directory/nested.txt"],
            max_file_bytes=100,
            max_total_bytes=100,
        )
    original = output / "original"
    original.write_text("hardlink", encoding="utf-8")
    os.link(original, output / "linked")
    with pytest.raises(DockerArtifactError, match="hard link"):
        collect_declared_artifacts(
            tmp_path,
            ["artifacts/linked"],
            max_file_bytes=100,
            max_total_bytes=100,
        )
    fifo = output / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(DockerArtifactError, match="regular file"):
        collect_declared_artifacts(
            tmp_path,
            ["artifacts/fifo"],
            max_file_bytes=100,
            max_total_bytes=100,
        )
    large = output / "large"
    large.write_bytes(b"x" * 11)
    with pytest.raises(DockerArtifactError, match="per-file"):
        collect_declared_artifacts(
            tmp_path,
            ["artifacts/large"],
            max_file_bytes=10,
            max_total_bytes=100,
        )
    with pytest.raises(DockerArtifactError, match="escapes"):
        collect_declared_artifacts(
            tmp_path,
            ["../outside.txt"],
            max_file_bytes=100,
            max_total_bytes=100,
        )
    with pytest.raises(DockerArtifactError, match="approved output root"):
        collect_declared_artifacts(
            tmp_path,
            ["outside.txt"],
            max_file_bytes=100,
            max_total_bytes=100,
        )


def test_docker_diagnostics_redact_secret_values_socket_and_private_paths() -> None:
    message = "TOKEN=abc API_KEY:xyz /var/run/docker.sock /private/staging"
    sanitized = sanitize_diagnostic(message, sensitive_paths=["/private/staging"])
    assert "abc" not in sanitized
    assert "xyz" not in sanitized
    assert "/var/run/docker.sock" not in sanitized
    assert "/private/staging" not in sanitized
    assert "<redacted>" in sanitized
