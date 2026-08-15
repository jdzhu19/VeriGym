from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


def _module():  # type: ignore[no-untyped-def]
    path = Path(__file__).parents[2] / "scripts/run_repository_rollout_dind_controller.py"
    spec = importlib.util.spec_from_file_location("run_repository_rollout_dind_controller", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed(argv: list[str], stdout: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")


def test_dind_controller_keeps_privilege_out_of_project_and_benchmark_containers() -> None:
    module = _module()
    root = Path("/safe")
    command = module._controller_command(  # noqa: SLF001
        image_id="sha256:" + "a" * 64,
        socket_volume="verigym-dind-socket-test",
        source_volume="verigym-source-test",
        scratch_volume="verigym-scratch-test",
        empty_home=root / "empty-home",
        task_manifest=root / "manifest" / "tasks.json",
        broker_root=root / "broker",
        verifier_output=root / "output",
        report=root / "report" / "report.json",
    )

    assert "--privileged" not in command
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "ALL" in command
    assert "no-new-privileges" in command
    assert "DOCKER_HOST=unix:///var/run/docker.sock" in command
    assert "verigym-dind-socket-test:/var/run:rw" in command
    assert all(not value.startswith("/var/run/docker.sock:") for value in command)


def test_dind_daemon_is_networkless_and_uses_only_nested_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    observed: list[list[str]] = []

    def fake_run(argv: list[str], *, timeout_s: int = 60):  # type: ignore[no-untyped-def]
        observed.append(argv)
        if argv[:5] == ["docker", "exec", "daemon", "docker", "version"]:
            return _completed(argv, b"23.0.6\n")
        if argv[:5] == ["docker", "exec", "daemon", "docker", "info"] and "--format" in argv:
            metadata = {"Driver": "vfs", "DefaultRuntime": "runc"}
            return _completed(argv, json.dumps(metadata).encode())
        if argv[:4] == ["docker", "exec", "daemon", "stat"]:
            return _completed(argv, f"{os.getgid()}\n".encode())
        return _completed(argv)

    monkeypatch.setattr(module, "_run", fake_run)
    metadata = module._start_dind(  # noqa: SLF001
        name="daemon",
        image_id="sha256:" + "b" * 64,
        socket_volume="socket-volume",
        data_volume="data-volume",
        source_volume="source-volume",
        scratch_volume="scratch-volume",
        empty_home=Path("/safe/empty-home"),
        same_path_mounts=["--volume", "/safe/output:/safe/output:rw"],
        startup_timeout_s=1,
    )

    launch = observed[0]
    assert metadata["Driver"] == "vfs"
    assert "--privileged" in launch
    assert launch[launch.index("--network") + 1] == "none"
    assert "socket-volume:/var/run:rw" in launch
    assert "data-volume:/var/lib/docker:rw" in launch
    assert "source-volume:/verigym-source:ro" in launch
    assert "scratch-volume:/verigym-scratch:rw" in launch
    assert "type=bind,src=/safe/empty-home,dst=/verigym-host-sentinel,readonly" in launch
    assert "--storage-driver=vfs" in launch
    assert "--iptables=false" in launch
    assert "--bridge=none" in launch
    assert "/var/run/docker.sock" not in launch


def test_dind_image_requires_official_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    image_id = "sha256:" + "c" * 64
    monkeypatch.setattr(
        module,
        "_inspect",
        lambda kind, value: {
            "Id": value,
            "Config": {"Entrypoint": ["dockerd-entrypoint.sh"]},
        },
    )
    module._dind_image(image_id)  # noqa: SLF001

    monkeypatch.setattr(
        module,
        "_inspect",
        lambda kind, value: {"Id": value, "Config": {"Entrypoint": ["python3"]}},
    )
    with pytest.raises(RuntimeError, match="official entrypoint"):
        module._dind_image(image_id)  # noqa: SLF001


def test_controller_image_requires_frozen_git_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    image_id = "sha256:" + "e" * 64
    labels = {
        "io.verigym.role": "rollout-controller",
        "io.verigym.docker.client": "19.03.14",
    }
    monkeypatch.setattr(
        module,
        "_image",
        lambda value, role: {"Config": {"Labels": labels}},
    )
    with pytest.raises(RuntimeError, match="role labels"):
        module._controller_image(image_id)  # noqa: SLF001

    labels["io.verigym.git.client"] = "2.30.2"
    module._controller_image(image_id)  # noqa: SLF001


def test_dind_data_volume_requires_private_role_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_inspect",
        lambda kind, value: {
            "Driver": "local",
            "Labels": {
                "verigym.owner": "rollout-controller-dind",
                "verigym.role": "data",
            },
        },
    )
    module._volume(  # noqa: SLF001
        "dind-data", owner="rollout-controller-dind", role="data"
    )
    with pytest.raises(RuntimeError, match="socket policy"):
        module._volume(  # noqa: SLF001
            "dind-data", owner="rollout-controller-dind", role="socket"
        )


def test_dind_launcher_has_no_provider_or_host_socket_mount() -> None:
    source = (
        Path(__file__).parents[2] / "scripts/run_repository_rollout_dind_controller.py"
    ).read_text(encoding="utf-8")

    assert "provider" not in source.lower()
    assert 'f"{socket_volume}:/var/run:rw"' in source
    assert 'f"{socket}:{socket}:rw"' not in source
    assert "seccomp=unconfined" not in source


def test_cva6_acceptance_controller_is_unprivileged_and_model_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(__file__).parents[2] / "scripts/run_cva6_dind_acceptance.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("run_cva6_dind_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    root = Path("/safe")
    command = module._controller_command(  # noqa: SLF001
        image_id="sha256:" + "d" * 64,
        socket_volume="verigym-dind-socket-test",
        source=root / "source",
        candidate=root / "candidate",
        output=root / "output",
        empty_home=root / "empty-home",
    )

    assert "--privileged" not in command
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "ALL" in command
    assert "no-new-privileges" in command
    assert "DOCKER_HOST=unix:///var/run/docker.sock" in command
    assert "/var/run/docker.sock:/var/run/docker.sock" not in command
    assert "provider" not in module._ACCEPTANCE_PROGRAM.lower()  # noqa: SLF001
    assert "model_process_count" in module._ACCEPTANCE_PROGRAM  # noqa: SLF001
