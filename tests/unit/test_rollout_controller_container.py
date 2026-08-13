from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _module():  # type: ignore[no-untyped-def]
    path = Path(__file__).parents[2] / "scripts/run_repository_rollout_controller.py"
    spec = importlib.util.spec_from_file_location("run_repository_rollout_controller", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_controller_image_is_narrow_and_uses_sibling_docker_client() -> None:
    root = Path(__file__).parents[2]
    dockerfile = (root / "docker/rollout-controller/Dockerfile").read_text(encoding="utf-8")
    build = (root / "scripts/build_rollout_controller_image.sh").read_text(encoding="utf-8")

    assert "FROM ${DOCKER_CLI_BASE} AS docker_cli" in dockerfile
    assert dockerfile.index("ARG PYTHON_BASE") < dockerfile.index("FROM ${DOCKER_CLI_BASE}")
    assert "Docker version 19.03.14" in dockerfile
    assert 'io.verigym.controller.glibc="2.31"' in dockerfile
    assert 'platform.libc_ver() == ("glibc", "2.31")' in dockerfile
    assert "threading.Thread" in dockerfile
    assert "run_qwen35_online_repository_broker.py" in dockerfile
    assert "rllm" not in dockerfile.lower()
    assert "vllm" not in dockerfile.lower()
    assert "openhands" not in dockerfile.lower()
    assert "--privileged" not in dockerfile
    assert "PYTHON_BASE_REPODIGEST" in build
    assert "DOCKER_CLI_BASE_REPODIGEST" in build
    assert "--network verigym-hwe-net" in build
    assert "DOCKER_BUILDKIT=0 docker build" in build
    assert "seccomp=unconfined" not in build


def test_controller_broker_keeps_diagnostics_private_and_sanitized() -> None:
    source = (
        Path(__file__).parents[2] / "scripts/run_qwen35_online_repository_broker.py"
    ).read_text(encoding="utf-8")

    assert "sanitize_diagnostic(" in source
    assert "sensitive_paths=(str(source_root), str(broker_root), str(output))" in source
    assert "file=sys.stderr" in source
    assert '"diagnostic"' not in source


def test_controller_runner_is_networkless_and_socket_is_controller_only() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_repository_rollout_controller.py").read_text(
        encoding="utf-8"
    )

    assert '"--network",\n        "none"' in source
    assert '"--read-only"' in source
    assert '"--cap-drop",\n        "ALL"' in source
    assert 'f"{socket}:{socket}:rw"' in source
    assert 'f"{empty_home}:{container_home}:rw"' in source
    assert '"--empty-home"' in source
    assert '"HOME=/tmp"' in source
    assert 'f"TMPDIR={scratch_mountpoint}"' in source
    assert 'f"{arguments.source_volume}:/verigym-source:ro"' in source
    assert '"--privileged"' not in source
    assert "provider" not in source.lower()


def test_controller_requires_role_labeled_volumes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_inspect",
        lambda kind, value: {
            "Labels": {
                "verigym.owner": "rollout-controller",
                "verigym.role": "source",
            },
            "Mountpoint": f"/var/lib/docker/volumes/{value}/_data",
        },
    )

    assert module._volume("source-v1", "source").endswith("/source-v1/_data")
    with pytest.raises(RuntimeError, match="scratch policy"):
        module._volume("source-v1", "scratch")


def test_controller_rejects_nonempty_home_mount(tmp_path: Path) -> None:
    module = _module()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert module._empty_directory(empty) == empty

    (empty / "unexpected").write_text("not safe to expose", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty-home mount is not empty"):
        module._empty_directory(empty)
