#!/usr/bin/env python3
"""Run an isolated-broker Qwen rLLM/veRL trainer in a native Conda environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from verigym_training_reference.native_runtime import (
    GpuHealthSample,
    package_inventory_hash,
    parse_visible_devices,
    replace_topology_overrides,
    seal_runtime_manifest,
    select_gpu_devices,
)

from verigym.experiments.state import atomic_dump_json

_SECRET_NAME = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|COOKIE)", re.IGNORECASE
)
_PROXY_NAME = re.compile(r"(?:HTTP|HTTPS|ALL|NO)_PROXY", re.IGNORECASE)
_ENV_REFERENCE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_REQUIRED_PACKAGES = ("ray", "rllm", "torch", "transformers", "verl", "vllm")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--rllm-root", type=Path, required=True)
    parser.add_argument("--verl-root", type=Path, required=True)
    parser.add_argument("--transformers-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter-root", type=Path, required=True)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--verifier-output", type=Path, required=True)
    parser.add_argument("--campaign-workspace", type=Path, required=True)
    parser.add_argument("--broker-report", type=Path, required=True)
    parser.add_argument("--gpu-count", choices=("auto", "4", "6", "8"), default="auto")
    parser.add_argument("--health-samples", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--health-interval-s", type=float, default=1.0)
    parser.add_argument("--broker-report-timeout-s", type=int, default=300)
    parser.add_argument("--trainer-config", type=Path)
    parser.add_argument("--trainer-stage", default="online-repository-grpo")
    parser.add_argument("--proot-executable", type=Path)
    parser.add_argument("--proot-rootfs-identity", type=Path)
    parser.add_argument("--glibc-python-executable", type=Path)
    parser.add_argument("--glibc-loader-executable", type=Path)
    parser.add_argument("--glibc-patchelf-executable", type=Path)
    parser.add_argument("--glibc-rootfs-identity", type=Path)
    parser.add_argument("trainer_args", nargs=argparse.REMAINDER)
    return parser


def _directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or resolved.is_symlink():
        raise RuntimeError(f"required directory is unavailable or unsafe: {path.name}")
    return resolved


def _file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise RuntimeError(f"required file is unavailable or unsafe: {path.name}")
    return resolved


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
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError("training source does not identify a full Git commit")
    return value


def _nvidia_rows(query: str) -> list[list[str]]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            f"--query-{query}",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        shell=False,
        text=True,
        timeout=30,
    )
    return [
        [column.strip() for column in line.split(",")]
        for line in completed.stdout.splitlines()
        if line.strip()
    ]


def _query_gpu_snapshot() -> tuple[dict[int, GpuHealthSample], dict[int, dict[str, Any]]]:
    process_counts: dict[str, int] = {}
    try:
        for row in _nvidia_rows("compute-apps=gpu_uuid,pid"):
            if len(row) == 2:
                process_counts[row[0]] = process_counts.get(row[0], 0) + 1
    except subprocess.CalledProcessError:
        # Some older drivers return a nonzero status when the process table is empty.
        process_counts = {}
    health: dict[int, GpuHealthSample] = {}
    metadata: dict[int, dict[str, Any]] = {}
    query = "gpu=index,uuid,name,driver_version,memory.total,memory.used,utilization.gpu"
    for row in _nvidia_rows(query):
        if len(row) != 7:
            raise RuntimeError("nvidia-smi returned an unexpected GPU inventory")
        index = int(row[0])
        health[index] = GpuHealthSample(
            memory_used_mib=int(row[5]),
            utilization_percent=int(row[6]),
            compute_process_count=process_counts.get(row[1], 0),
        )
        metadata[index] = {
            "name": row[2],
            "driver_version": row[3],
            "memory_total_mib": int(row[4]),
        }
    return health, metadata


def _sample_gpus(
    count: int, interval_s: float
) -> tuple[dict[int, list[GpuHealthSample]], dict[int, dict[str, Any]]]:
    samples: dict[int, list[GpuHealthSample]] = {}
    metadata: dict[int, dict[str, Any]] = {}
    for index in range(count):
        snapshot, current_metadata = _query_gpu_snapshot()
        if index == 0:
            metadata = current_metadata
        elif current_metadata != metadata:
            raise RuntimeError("GPU inventory changed during the contention preflight")
        for device, sample in snapshot.items():
            samples.setdefault(device, []).append(sample)
        if index + 1 < count:
            time.sleep(interval_s)
    return samples, metadata


def _package_inventory() -> tuple[dict[str, str], dict[str, str]]:
    complete: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if isinstance(name, str):
            complete[name.lower().replace("_", "-")] = distribution.version
    required = {name: complete[name] for name in _REQUIRED_PACKAGES if name in complete}
    missing = sorted(set(_REQUIRED_PACKAGES) - set(required))
    if missing:
        raise RuntimeError(f"native training environment lacks required packages: {missing}")
    return complete, required


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _file(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _compatibility_layer(
    proot_executable: Path | None, rootfs_identity: Path | None
) -> dict[str, object] | None:
    if (proot_executable is None) != (rootfs_identity is None):
        raise RuntimeError("proot executable and rootfs identity must be supplied together")
    if proot_executable is None or rootfs_identity is None:
        return None
    if os.environ.get("PROOT_NO_SECCOMP") != "1":
        raise RuntimeError("the qualified PRoot path requires disabled seccomp acceleration")
    identity = _file(rootfs_identity).read_text(encoding="utf-8").strip()
    digest = identity.removeprefix("sha256:")
    if (
        not identity.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError("rootfs identity is not a Docker SHA-256 image ID")
    libc_name, libc_version = platform.libc_ver()
    if libc_name != "glibc" or not libc_version:
        raise RuntimeError("PRoot compatibility layer did not expose a qualified glibc")
    return {
        "kind": "proot_rootfs",
        "executable_sha256": _sha256_file(proot_executable),
        "rootfs_image_id": identity,
        "seccomp_acceleration": False,
        "host_kernel_release": platform.release(),
        "guest_libc_version": libc_version,
    }


def _glibc_compatibility_layer(
    python_executable: Path | None,
    loader_executable: Path | None,
    patcher_executable: Path | None,
    rootfs_identity: Path | None,
) -> dict[str, object] | None:
    values = (python_executable, loader_executable, patcher_executable, rootfs_identity)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise RuntimeError("glibc compatibility identities must be supplied together")
    assert python_executable is not None
    assert loader_executable is not None
    assert patcher_executable is not None
    assert rootfs_identity is not None
    python = _file(python_executable)
    if not Path(sys.executable).resolve(strict=True).samefile(python):
        raise RuntimeError("native training is not running through the qualified Python")
    identity = _file(rootfs_identity).read_text(encoding="utf-8").strip()
    digest = identity.removeprefix("sha256:")
    if (
        not identity.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError("rootfs identity is not a Docker SHA-256 image ID")
    libc_name, libc_version = platform.libc_ver()
    if libc_name != "glibc" or not libc_version:
        raise RuntimeError("patched Python did not expose a qualified glibc")
    return {
        "kind": "glibc_loader",
        "executable_sha256": _sha256_file(python),
        "rootfs_image_id": identity,
        "loader_sha256": _sha256_file(loader_executable),
        "patcher_sha256": _sha256_file(patcher_executable),
        "host_kernel_release": platform.release(),
        "guest_libc_version": libc_version,
    }


def _clean_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not _SECRET_NAME.search(name) and not _PROXY_NAME.fullmatch(name)
    }
    for name in list(environment):
        if name.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}:
            environment.pop(name)
    return environment


def _wait_for_broker_report(path: Path, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise RuntimeError("repository broker did not publish its final report")
        time.sleep(0.2)


def _trainer_arguments_from_config(
    path: Path,
    stage_id: str,
    replacements: dict[str, str],
) -> list[str]:
    value = json.loads(_file(path).read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("format_id") != "verigym_external_training_campaign_v1"
    ):
        raise RuntimeError("trainer config is not an external training campaign")
    stages = value.get("stages")
    if not isinstance(stages, list):
        raise RuntimeError("trainer config omits its stages")
    matches = [
        stage for stage in stages if isinstance(stage, dict) and stage.get("stage_id") == stage_id
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("argv"), list):
        raise RuntimeError("trainer config does not contain exactly one selected stage")
    raw = matches[0]["argv"]
    if "--" not in raw or not all(isinstance(item, str) for item in raw):
        raise RuntimeError("selected trainer stage has no bounded argument separator")
    arguments = raw[raw.index("--") + 1 :]

    def expand(item: str) -> str:
        def replacement(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in replacements:
                raise RuntimeError(
                    f"trainer argument references unsupported environment name: {name}"
                )
            return replacements[name]

        return _ENV_REFERENCE.sub(replacement, item)

    return [expand(item) for item in arguments]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repository = _directory(arguments.repository)
    rllm_root = _directory(arguments.rllm_root)
    verl_root = _directory(arguments.verl_root)
    transformers_root = _directory(arguments.transformers_root)
    model_root = _directory(arguments.model_root)
    adapter_root = _directory(arguments.adapter_root)
    task_manifest = _file(arguments.task_manifest)
    broker_root = _directory(arguments.broker_root)
    verifier_output = _directory(arguments.verifier_output)
    workspace = _directory(arguments.campaign_workspace)
    broker_report = arguments.broker_report.resolve()
    if not broker_report.is_relative_to(workspace):
        raise RuntimeError("broker report must remain inside the campaign workspace")
    if (broker_root / "STOP").exists():
        raise RuntimeError("repository broker is already stopped")
    for name in ("requests", "responses"):
        _directory(broker_root / name)

    allocated = parse_visible_devices(os.environ.get("CUDA_VISIBLE_DEVICES", ""))
    health, gpu_metadata = _sample_gpus(arguments.health_samples, arguments.health_interval_s)
    requested: Literal["auto", "4", "6", "8"] = arguments.gpu_count
    selected = select_gpu_devices(allocated, health, requested)
    selected_metadata = [gpu_metadata[device] for device in selected]
    if any(value["memory_total_mib"] < 24_000 for value in selected_metadata):
        raise RuntimeError("selected GPUs do not provide the frozen 24 GiB memory envelope")

    environment = _clean_environment()
    environment["CUDA_VISIBLE_DEVICES"] = ",".join(str(device) for device in selected)
    cache = workspace / "native-cache"
    process_tmp = workspace / "process-tmp"
    ray_tmp = workspace / "ray"
    rllm_home = workspace / "rllm-home"
    hf_home = workspace / "hf-home"
    native_home = workspace / "native-home"
    for path in (cache, process_tmp, ray_tmp, rllm_home, hf_home, native_home):
        path.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "CUDA_CACHE_PATH": str(cache / "cuda"),
            "CUPY_CACHE_DIR": str(cache / "cupy"),
            "HF_HOME": str(hf_home),
            "HF_HUB_OFFLINE": "1",
            "HOME": str(native_home),
            "HYDRA_FULL_ERROR": "1",
            "MAX_JOBS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": (
                f"{repository / 'src'}:"
                f"{repository / 'integrations/verigym-training-reference/src'}:"
                f"{rllm_root}:"
                f"{rllm_root / 'rllm-model-gateway/src'}:"
                f"{verl_root}:{transformers_root / 'src'}"
            ),
            "RAY_TMPDIR": str(ray_tmp),
            "RAYON_NUM_THREADS": "1",
            "RLLM_HOME": str(rllm_home),
            "TMPDIR": str(process_tmp),
            "TOKENIZERS_PARALLELISM": "false",
            "TORCH_HOME": str(cache / "torch"),
            "TORCHINDUCTOR_CACHE_DIR": str(cache / "inductor"),
            "TRANSFORMERS_OFFLINE": "1",
            "TRITON_CACHE_DIR": str(cache / "triton"),
            "VERIGYM_ONLINE_COMPLETION_REPORT": str(workspace / "online-completion-report.json"),
            "VERIGYM_ONLINE_REPOSITORY_BROKER_ROOT": str(broker_root),
            "VERIGYM_ONLINE_TASK_MANIFEST": str(task_manifest),
            "VERIGYM_ONLINE_VERIFIER_OUTPUT": str(verifier_output),
            "VERIGYM_ONLINE_WORKFLOW": "repository",
            "VERIGYM_RLLM_COMMIT": _git_head(rllm_root),
            "VERIGYM_SOURCE_COMMIT": _git_head(repository),
            "VERIGYM_VERL_COMMIT": _git_head(verl_root),
            "VERIGYM_TRANSFORMERS_COMMIT": _git_head(transformers_root),
            "VLLM_ALLOW_LONG_MAX_MODEL_LEN": "1",
            "VLLM_ATTENTION_BACKEND": "FLASH_ATTN",
            "VLLM_ENGINE_ITERATION_TIMEOUT_S": "3600",
            "VLLM_GDN_PREFILL_BACKEND": "triton",
            "VLLM_USE_V1": "1",
            "XDG_CACHE_HOME": str(cache),
            "XDG_CONFIG_HOME": str(workspace / "native-config"),
            "XDG_DATA_HOME": str(workspace / "native-data"),
            "PYTORCH_ALLOC_CONF": "expandable_segments:False",
        }
    )

    # Import only after selecting the allocation so the runtime observes exactly that topology.
    os.environ["CUDA_VISIBLE_DEVICES"] = environment["CUDA_VISIBLE_DEVICES"]
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != len(selected):
        raise RuntimeError("PyTorch does not observe the selected frozen GPU topology")
    packages, required_packages = _package_inventory()
    driver_versions = {str(value["driver_version"]) for value in selected_metadata}
    if len(driver_versions) != 1:
        raise RuntimeError("selected GPUs report inconsistent driver versions")
    proot_compatibility = _compatibility_layer(
        arguments.proot_executable, arguments.proot_rootfs_identity
    )
    glibc_compatibility = _glibc_compatibility_layer(
        arguments.glibc_python_executable,
        arguments.glibc_loader_executable,
        arguments.glibc_patchelf_executable,
        arguments.glibc_rootfs_identity,
    )
    if proot_compatibility is not None and glibc_compatibility is not None:
        raise RuntimeError("native training accepts only one ABI compatibility strategy")
    runtime = seal_runtime_manifest(
        {
            "python_version": ".".join(str(value) for value in sys.version_info[:3]),
            "environment_name": os.environ.get("CONDA_DEFAULT_ENV", "agent"),
            "package_inventory_hash": package_inventory_hash(packages),
            "packages": required_packages,
            "verigym_commit": environment["VERIGYM_SOURCE_COMMIT"],
            "rllm_commit": environment["VERIGYM_RLLM_COMMIT"],
            "verl_commit": environment["VERIGYM_VERL_COMMIT"],
            "transformers_commit": environment["VERIGYM_TRANSFORMERS_COMMIT"],
            "torch_cuda_version": str(torch.version.cuda),
            "driver_version": driver_versions.pop(),
            "gpu_count": len(selected),
            "gpu_names": [torch.cuda.get_device_name(index) for index in range(len(selected))],
            "fsdp_size": len(selected),
            "rollout_group_size": len(selected),
            "visible_device_count": torch.cuda.device_count(),
            "compatibility_layer": proot_compatibility or glibc_compatibility,
        }
    )
    runtime_path = workspace / "native-training-runtime.json"
    atomic_dump_json(runtime_path, runtime.model_dump(mode="json"))
    environment["VERIGYM_TRAINING_RUNTIME_MANIFEST"] = str(runtime_path)

    trainer_args = list(arguments.trainer_args)
    if arguments.trainer_config is not None:
        if trainer_args:
            raise RuntimeError("use either --trainer-config or explicit trainer arguments")
        trainer_args = _trainer_arguments_from_config(
            arguments.trainer_config,
            arguments.trainer_stage,
            {
                "VERIGYM_MODEL_ROOT": str(model_root),
                "VERIGYM_INPUT_POLICY_ADAPTER": str(adapter_root),
                "VERIGYM_CAMPAIGN_WORKSPACE": str(workspace),
            },
        )
    elif trainer_args and trainer_args[0] == "--":
        trainer_args = trainer_args[1:]
    trainer_args = replace_topology_overrides(trainer_args, len(selected))
    command = [
        sys.executable,
        str(repository / "scripts/train_qwen35_rllm_verl_online.py"),
        *trainer_args,
    ]
    code = 1
    try:
        code = subprocess.run(command, cwd=repository, env=environment, shell=False).returncode
    finally:
        (broker_root / "STOP").write_text("stop\n", encoding="utf-8")
    if code != 0:
        return code
    _wait_for_broker_report(broker_report, arguments.broker_report_timeout_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
