from __future__ import annotations

from pathlib import Path


def test_trainer_image_excludes_runtime_data_and_freezes_versions() -> None:
    root = Path(__file__).parents[2]
    dockerfile = (root / "docker/multiturn-trainer/Dockerfile").read_text(encoding="utf-8")
    build = (root / "scripts/build_multiturn_trainer_image.sh").read_text(encoding="utf-8")

    assert "verl==0.8.0" in dockerfile
    assert "VERIGYM_VLLM_SERVICE_VERSION=0.22.1" in dockerfile
    assert "vllm lmcache opencv-python-headless cupy-cuda12x cupy-cuda13x pygobject" in dockerfile
    assert "1d1109a655e291b3001d8526d7c9ecc5b9328226" in dockerfile
    assert "COPY rllm /opt/rllm" in dockerfile
    assert ".verigym-rllm-commit" in dockerfile
    assert '"$context/rllm/.verigym-rllm-commit"' in build
    assert 'subprocess.check_output(["git"' not in dockerfile
    assert "COPY wheels /opt/verigym/wheels" in dockerfile
    assert "smoke_reload_qwen35_multiturn_adapter.py" in dockerfile
    assert "smoke_qwen35_rllm_multiturn.py" in dockerfile
    assert "models" not in dockerfile.lower()
    assert "docker.sock" not in dockerfile
    assert "VLLM_SERVICE_IMAGE_ID" in build
    assert "--network verigym-hwe-net" in build
    assert "DOCKER_BUILDKIT=0 docker build" in build
    assert "--entrypoint python3" in build
    assert "python3 -m pip install" in dockerfile
    assert '"vllm" not in' in build


def test_vllm_service_uses_frozen_cuda_129_wheel_and_restricted_runtime() -> None:
    root = Path(__file__).parents[2]
    dockerfile = (root / "docker/vllm-service-cu129/Dockerfile").read_text(encoding="utf-8")
    build = (root / "scripts/build_vllm_service_image.sh").read_text(encoding="utf-8")
    runner = (root / "scripts/run_vllm_service_container.sh").read_text(encoding="utf-8")

    assert "v0.22.1" in dockerfile
    assert "torch==2.11.0+cu129" in dockerfile
    assert "365ee929afd73bb5d146235b65053fa948788ec2ee00a2c3e957d3f43bf2b0cd" in dockerfile
    assert 'torch.version.cuda == "12.9"' in dockerfile
    assert "PYTHON_BASE_REPODIGEST" in build
    assert "VERIGYM_COMMIT" in dockerfile
    assert "VERIGYM_COMMIT=$verigym_commit" in build
    assert "vllm-service-pip-freeze.txt" in dockerfile
    assert "--network verigym-hwe-net" in build
    assert "DOCKER_BUILDKIT=0 docker build" in build
    assert '--gpus "\\"device=$gpu_devices\\""' in runner
    assert '--publish "127.0.0.1:$port:8000"' in runner
    assert '--network "$network_name"' in runner
    assert "ADAPTER_ROOT_OR_DASH" in runner
    assert "--enable-lora" in runner
    assert '--lora-modules "$served_model_id=/adapter"' in runner
    assert "$adapter_root:/adapter:ro" in runner
    assert "--read-only" in runner
    assert "--cap-drop ALL" in runner
    assert "no-new-privileges" in runner
    assert "--ipc host" not in runner
    assert "docker.sock" not in runner
    assert "--privileged" not in runner


def test_trainer_runner_is_offline_and_limits_gpu_and_mount_visibility() -> None:
    runner = (Path(__file__).parents[2] / "scripts/run_multiturn_sft_container.sh").read_text(
        encoding="utf-8"
    )

    assert "--network none" in runner
    assert '--gpus "\\"device=$gpu_devices\\""' in runner
    assert "$model_root:/model:ro" in runner
    assert "$dataset_root:/dataset:ro" in runner
    assert "$output_root:/output" in runner
    assert "$cache_root:/cache" in runner
    assert "docker.sock" not in runner
    assert "--privileged" not in runner
    assert "--ipc host" not in runner
    assert "--shm-size 16g" in runner
    assert "--read-only" in runner
    assert "--cap-drop ALL" in runner
    assert "$HOME" not in runner
    assert "python3 /opt/verigym/bin/train_qwen35_multiturn_sft.py" in runner


def test_reload_and_native_smoke_runners_preserve_boundaries() -> None:
    root = Path(__file__).parents[2]
    reload_runner = (root / "scripts/run_multiturn_reload_container.sh").read_text(encoding="utf-8")
    native_runner = (root / "scripts/run_rllm_multiturn_smoke_container.sh").read_text(
        encoding="utf-8"
    )

    assert "--network none" in reload_runner
    assert '--gpus "\\"device=$gpu_devices\\""' in reload_runner
    assert "--nproc-per-node=4" in reload_runner
    assert "--read-only" in reload_runner
    assert "docker.sock" not in reload_runner
    assert "--privileged" not in reload_runner
    assert '--network "$network_name"' in native_runner
    assert "verigym-qwen35-vllm:8000/v1" in native_runner
    assert "--gpus" not in native_runner
    assert "$task:/input/task.json:ro" in native_runner
    assert "$model_root:/model:ro" in native_runner
    assert "--read-only" in native_runner
    assert "docker.sock" not in native_runner
    assert "--privileged" not in native_runner
