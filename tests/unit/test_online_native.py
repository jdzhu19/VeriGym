from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


def _script(name: str = "run_qwen35_online_native.py") -> ModuleType:
    path = (Path("scripts") / name).resolve(strict=True)
    spec = importlib.util.spec_from_file_location(f"verigym_{name}_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_runner_extracts_only_trainer_arguments(tmp_path: Path) -> None:
    module = _script()
    config = tmp_path / "campaign.json"
    config.write_text(
        json.dumps(
            {
                "format_id": "verigym_external_training_campaign_v1",
                "stages": [
                    {
                        "stage_id": "train",
                        "argv": [
                            "python",
                            "container.py",
                            "--model-root",
                            "not-visible-to-native-runner",
                            "--",
                            "actor_rollout_ref.model.path=${VERIGYM_MODEL_ROOT}",
                            "trainer.default_local_dir=${VERIGYM_CAMPAIGN_WORKSPACE}/checkpoints",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    arguments = module._trainer_arguments_from_config(
        config,
        "train",
        {
            "VERIGYM_MODEL_ROOT": "/model",
            "VERIGYM_CAMPAIGN_WORKSPACE": "/workspace",
        },
    )

    assert arguments == [
        "actor_rollout_ref.model.path=/model",
        "trainer.default_local_dir=/workspace/checkpoints",
    ]
    assert all("not-visible" not in value for value in arguments)


def test_native_runner_rejects_unknown_trainer_environment(tmp_path: Path) -> None:
    module = _script()
    config = tmp_path / "campaign.json"
    config.write_text(
        json.dumps(
            {
                "format_id": "verigym_external_training_campaign_v1",
                "stages": [
                    {
                        "stage_id": "train",
                        "argv": ["python", "launcher.py", "--", "x=${VERIGYM_HIDDEN_ROOT}"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="unsupported environment"):
        module._trainer_arguments_from_config(config, "train", {})


def test_native_runner_source_has_no_hidden_or_source_argument() -> None:
    source = Path("scripts/run_qwen35_online_native.py").read_text(encoding="utf-8")

    assert "--source-root" not in source
    assert "--hidden" not in source
    assert "docker.sock" not in source
    assert '"HF_HUB_OFFLINE": "1"' in source
    assert '"HOME": str(native_home)' in source
    assert '"TRANSFORMERS_OFFLINE": "1"' in source
    assert "ray_tmp = _private_directory(ray_tmp, max_bytes=48)" in source


def test_native_runner_binds_proot_identity_without_persisting_paths(tmp_path: Path) -> None:
    module = _script()
    executable = tmp_path / "proot"
    executable.write_bytes(b"qualified-proot")
    identity = tmp_path / "rootfs-image-id"
    identity.write_text(f"sha256:{'a' * 64}\n", encoding="utf-8")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("PROOT_NO_SECCOMP", "1")
        monkeypatch.setattr(module.platform, "libc_ver", lambda: ("glibc", "2.41"))
        layer = module._compatibility_layer(executable, identity)

    assert layer is not None
    assert layer["rootfs_image_id"] == f"sha256:{'a' * 64}"
    assert str(tmp_path) not in json.dumps(layer)


def test_native_runner_binds_glibc_loader_identities_without_paths(tmp_path: Path) -> None:
    module = _script()
    python = tmp_path / "python"
    python.write_bytes(b"qualified-python")
    loader = tmp_path / "loader"
    loader.write_bytes(b"qualified-loader")
    patcher = tmp_path / "patchelf"
    patcher.write_bytes(b"qualified-patcher")
    identity = tmp_path / "rootfs-image-id"
    identity.write_text(f"sha256:{'b' * 64}\n", encoding="utf-8")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(module.sys, "executable", str(python))
        monkeypatch.setattr(module.platform, "libc_ver", lambda: ("glibc", "2.41"))
        layer = module._glibc_compatibility_layer(python, loader, patcher, identity)

    assert layer is not None
    assert layer["kind"] == "glibc_loader"
    assert layer["rootfs_image_id"] == f"sha256:{'b' * 64}"
    assert str(tmp_path) not in json.dumps(layer)


def test_native_runner_binds_gpu_toolchain_without_paths(tmp_path: Path) -> None:
    module = _script()
    nccl = tmp_path / "libnccl.so.2"
    nccl.write_bytes(b"qualified-nccl")
    source = tmp_path / "nccl-source"
    source.mkdir()
    compiler = tmp_path / "gcc"
    compiler.write_bytes(b"qualified-gcc")
    compiler.chmod(0o755)
    nccl_sha256 = module._sha256_file(nccl)
    compiler_sha256 = module._sha256_file(compiler)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(module, "_git_head", lambda _path: "c" * 40)
        monkeypatch.setattr(module, "_program_version", lambda _path: "gcc (GCC) 12.2.0")
        identity = module._gpu_toolchain_identity(
            nccl,
            source,
            nccl_sha256,
            "c" * 40,
            "12.4.131",
            compiler,
            compiler_sha256,
            "gcc (GCC) 12.2.0",
        )

    assert identity is not None
    assert identity["nccl_cuda_version"] == "12.4.131"
    assert str(tmp_path) not in json.dumps(identity)


def test_native_runner_rejects_partial_gpu_toolchain_identity(tmp_path: Path) -> None:
    module = _script()

    with pytest.raises(RuntimeError, match="supplied together"):
        module._gpu_toolchain_identity(
            tmp_path / "libnccl.so.2",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )


def test_broker_container_requires_role_labeled_private_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _script("run_qwen35_online_broker_container.py")

    monkeypatch.setattr(
        module,
        "_inspect",
        lambda kind, value: {
            "Labels": {
                "verigym.owner": "online-repository-broker",
                "verigym.role": "source",
            },
            "Mountpoint": f"/var/lib/docker/volumes/{value}/_data",
        },
    )
    assert module._volume("source-v1", "source").endswith("/source-v1/_data")
    with pytest.raises(RuntimeError, match="scratch policy"):
        module._volume("source-v1", "scratch")


def test_broker_container_keeps_source_in_a_named_volume() -> None:
    source = Path("scripts/run_qwen35_online_broker_container.py").read_text(encoding="utf-8")

    assert 'f"{arguments.source_volume}:/verigym-source:ro"' in source
    assert '"--source-root",\n            "/verigym-source"' in source
    assert 'f"{socket}:{socket}:rw"' in source
    assert '"--network",\n        "none"' in source
