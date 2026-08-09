#!/usr/bin/env python3
"""Run the minimal rLLM + verl stack in an isolated multi-GPU training container."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

_GPU_IDS = re.compile(r"^[0-9]+(?:,[0-9]+)*$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--container-venv", type=Path, required=True)
    parser.add_argument("--verifier-python", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--rllm-root", type=Path, required=True)
    parser.add_argument("--verl-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter-root", type=Path, required=True)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--campaign-workspace", type=Path, required=True)
    parser.add_argument("--gpu-ids", default="0,1,2,3")
    parser.add_argument("trainer_args", nargs=argparse.REMAINDER)
    return parser


def _resolved(path: Path, *, directory: bool = True) -> Path:
    value = path.resolve(strict=True)
    if directory and not value.is_dir():
        raise RuntimeError(f"required directory is unavailable: {path.name}")
    if not directory and not value.is_file():
        raise RuntimeError(f"required file is unavailable: {path.name}")
    return value


def _image_id(image: str) -> str:
    completed = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        shell=False,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        shell=False,
        text=True,
        timeout=30,
    )
    value = completed.stdout.strip()
    if len(value) != 40:
        raise RuntimeError("training source does not identify a full Git commit")
    return value


def _mount(path: Path, mode: str) -> str:
    return f"{path}:{path}:{mode}"


def _docker_gpu_request(gpu_ids: str) -> str:
    # Docker parses --gpus with its CSV reader. Literal quotes keep a multi-ID
    # device value together when argv is passed directly rather than by a shell.
    return f'"device={gpu_ids}"'


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not _GPU_IDS.fullmatch(arguments.gpu_ids):
        raise RuntimeError("GPU IDs must be a comma-separated list of integers")
    if _image_id(arguments.image) != arguments.expected_image_id:
        raise RuntimeError("training container image identity differs from the campaign pin")

    repository = _resolved(arguments.repository)
    rllm_root = _resolved(arguments.rllm_root)
    verl_root = _resolved(arguments.verl_root)
    model_root = _resolved(arguments.model_root)
    adapter_root = _resolved(arguments.adapter_root)
    container_venv = _resolved(arguments.container_venv)
    verifier_python = _resolved(arguments.verifier_python, directory=False)
    task_manifest = _resolved(arguments.task_manifest, directory=False)
    source_root = _resolved(arguments.source_root)
    workspace = arguments.campaign_workspace.resolve(strict=True)
    if not workspace.is_dir():
        raise RuntimeError("campaign workspace is unavailable")

    broker_root = workspace / "verifier-broker"
    verifier_output = workspace / "verifier-runs"
    process_tmp = workspace / "process-tmp"
    container_cache = workspace / "container-cache"
    container_config = workspace / "container-config"
    container_data = workspace / "container-data"
    container_identity = workspace / "container-identity"
    ray_tmp = workspace / "ray"
    rllm_home = workspace / "rllm-home"
    hf_home = workspace / "hf-home"
    for path in [
        broker_root,
        verifier_output,
        process_tmp,
        container_cache,
        container_config,
        container_data,
        container_identity,
        ray_tmp,
        rllm_home,
        hf_home,
    ]:
        path.mkdir(parents=True, exist_ok=True)
    passwd_path = container_identity / "passwd"
    group_path = container_identity / "group"
    passwd_path.write_text(
        "root:x:0:0:root:/root:/bin/bash\n"
        f"verigym:x:{os.getuid()}:{os.getgid()}:VeriGym trainer:/nonexistent:/usr/sbin/nologin\n",
        encoding="utf-8",
    )
    group_path.write_text(f"root:x:0:\nverigym:x:{os.getgid()}:verigym\n", encoding="utf-8")
    broker_report = workspace / "online-verifier-broker-report.json"
    completion_report = workspace / "online-completion-report.json"

    broker_environment = {
        name: os.environ[name]
        for name in ["HOME", "LANG", "LC_ALL", "PATH", "PYTHONPATH"]
        if name in os.environ
    }
    broker = subprocess.Popen(
        [
            str(verifier_python),
            str(repository / "scripts/run_qwen35_online_verifier_broker.py"),
            "--task-manifest",
            str(task_manifest),
            "--source-root",
            str(source_root),
            "--broker-root",
            str(broker_root),
            "--verifier-output",
            str(verifier_output),
            "--report",
            str(broker_report),
        ],
        cwd=repository,
        env=broker_environment,
        shell=False,
    )
    deadline = time.monotonic() + 30
    while not (broker_root / "requests").is_dir() or not (broker_root / "responses").is_dir():
        if broker.poll() is not None:
            raise RuntimeError("online verifier broker failed during startup")
        if time.monotonic() >= deadline:
            broker.terminate()
            raise RuntimeError("online verifier broker startup timed out")
        time.sleep(0.1)

    trainer_args = arguments.trainer_args
    if trainer_args and trainer_args[0] == "--":
        trainer_args = trainer_args[1:]
    container_environment = {
        "CUDA_CACHE_PATH": str(container_cache / "cuda"),
        "HF_HOME": str(hf_home),
        "HF_HUB_OFFLINE": "1",
        "HYDRA_FULL_ERROR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": (
            f"{repository / 'src'}:"
            f"{repository / 'integrations/verigym-training-reference/src'}:"
            f"{rllm_root}:{verl_root}"
        ),
        "RAY_TMPDIR": str(ray_tmp),
        "RLLM_HOME": str(rllm_home),
        "TMPDIR": str(process_tmp),
        "TORCH_HOME": str(container_cache / "torch"),
        "TORCHINDUCTOR_CACHE_DIR": str(container_cache / "inductor"),
        "TRANSFORMERS_OFFLINE": "1",
        "TRITON_CACHE_DIR": str(container_cache / "triton"),
        "VERIGYM_ONLINE_BROKER_ROOT": str(broker_root),
        "VERIGYM_ONLINE_COMPLETION_REPORT": str(completion_report),
        "VERIGYM_ONLINE_TASK_MANIFEST": str(task_manifest),
        "VERIGYM_ONLINE_VERIFIER_OUTPUT": str(verifier_output),
        "VERIGYM_RLLM_COMMIT": _git_head(rllm_root),
        "VERIGYM_SOURCE_COMMIT": _git_head(repository),
        "VERIGYM_TRAINING_IMAGE_ID": arguments.expected_image_id,
        "VERIGYM_VERL_COMMIT": _git_head(verl_root),
        "VLLM_ALLOW_LONG_MAX_MODEL_LEN": "1",
        "VLLM_ATTENTION_BACKEND": "FLASH_ATTN",
        "VLLM_ENGINE_ITERATION_TIMEOUT_S": "3600",
        "VLLM_GDN_PREFILL_BACKEND": "triton",
        "VLLM_USE_V1": "1",
        "XDG_CACHE_HOME": str(container_cache),
        "XDG_CONFIG_HOME": str(container_config),
        "XDG_DATA_HOME": str(container_data),
        "PYTORCH_ALLOC_CONF": "expandable_segments:False",
    }
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--ipc",
        "host",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--gpus",
        _docker_gpu_request(arguments.gpu_ids),
        "--workdir",
        str(repository),
    ]
    for name, value in container_environment.items():
        command.extend(["--env", f"{name}={value}"])
    for path in [repository, rllm_root, verl_root, model_root, adapter_root, container_venv]:
        command.extend(["--volume", _mount(path, "ro")])
    command.extend(["--volume", _mount(workspace, "rw")])
    command.extend(["--volume", f"{passwd_path}:/etc/passwd:ro"])
    command.extend(["--volume", f"{group_path}:/etc/group:ro"])
    command.extend(
        [
            arguments.image,
            str(container_venv / "bin/python"),
            str(repository / "scripts/train_qwen35_rllm_verl_online.py"),
            *trainer_args,
        ]
    )
    trainer_code = 1
    try:
        trainer_code = subprocess.run(command, cwd=repository, shell=False).returncode
    finally:
        (broker_root / "STOP").write_text("stop\n", encoding="utf-8")
        try:
            broker_code = broker.wait(timeout=300)
        except subprocess.TimeoutExpired:
            broker.terminate()
            broker_code = broker.wait(timeout=30)
    if trainer_code != 0:
        return trainer_code
    if broker_code != 0 or not broker_report.is_file() or not completion_report.is_file():
        raise RuntimeError("online verifier broker or training completion report failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
