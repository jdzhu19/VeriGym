from __future__ import annotations

from pathlib import Path


def test_trainer_image_excludes_runtime_data_and_freezes_versions() -> None:
    root = Path(__file__).parents[2]
    dockerfile = (root / "docker/multiturn-trainer/Dockerfile").read_text(encoding="utf-8")
    build = (root / "scripts/build_multiturn_trainer_image.sh").read_text(encoding="utf-8")

    assert "verl==0.8.0" in dockerfile
    assert 'version("vllm") == "0.22.1"' in dockerfile
    assert "1d1109a655e291b3001d8526d7c9ecc5b9328226" in dockerfile
    assert "COPY rllm /opt/rllm" in dockerfile
    assert "COPY wheels /opt/verigym/wheels" in dockerfile
    assert "models" not in dockerfile.lower()
    assert "docker.sock" not in dockerfile
    assert "VLLM_BASE_REPODIGEST" in build
    assert "--network verigym-hwe-net" in build
    assert "--entrypoint python3" in build
    assert "RUN python3 -m pip install" in dockerfile


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
    assert "$HOME" not in runner
    assert "python3 /opt/verigym/bin/train_qwen35_multiturn_sft.py" in runner
