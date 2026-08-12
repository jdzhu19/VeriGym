#!/usr/bin/env python3
"""Launch the native Qwen trainer through a hash-bound PRoot userspace."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path

_SECRET_NAME = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|COOKIE)", re.IGNORECASE
)
_PROXY_NAME = re.compile(r"(?:HTTP|HTTPS|ALL|NO)_PROXY", re.IGNORECASE)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proot", type=Path, required=True)
    parser.add_argument("--expected-proot-sha256", required=True)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--expected-rootfs-image-id", required=True)
    parser.add_argument("--python", type=Path, required=True)
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
    parser.add_argument("--trainer-config", type=Path, required=True)
    return parser


def _directory(path: Path) -> Path:
    if path.is_symlink():
        raise RuntimeError(f"required directory cannot be a symlink: {path.name}")
    value = path.resolve(strict=True)
    if not value.is_dir():
        raise RuntimeError(f"required directory is unavailable: {path.name}")
    return value


def _file(path: Path, *, executable: bool = False) -> Path:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"required file is unavailable or unsafe: {path.name}")
    value = path.resolve(strict=True)
    if executable and not os.access(value, os.X_OK):
        raise RuntimeError(f"required file is not executable: {path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _image_id(value: str) -> str:
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError("rootfs identity must be a Docker SHA-256 image ID")
    return value


def _bind_destination(rootfs: Path, source: Path) -> None:
    relative = source.relative_to("/")
    (rootfs / relative).mkdir(parents=True, exist_ok=True)


def _driver_binding(rootfs: Path, source: Path, destination_name: str) -> tuple[Path, Path]:
    source = source.resolve(strict=True)
    destination = rootfs / "opt/verigym-host-driver" / destination_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.touch(exist_ok=True)
    return source, Path("/opt/verigym-host-driver") / destination_name


def _clean_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if not _SECRET_NAME.search(name) and not _PROXY_NAME.fullmatch(name)
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    proot = _file(arguments.proot, executable=True)
    if _sha256(proot) != arguments.expected_proot_sha256:
        raise RuntimeError("PRoot executable identity differs from its pin")
    rootfs = _directory(arguments.rootfs)
    rootfs_identity = _file(rootfs / ".export-complete").read_text(encoding="utf-8").strip()
    if rootfs_identity != _image_id(arguments.expected_rootfs_image_id):
        raise RuntimeError("exported rootfs image identity differs from its pin")

    python = _file(arguments.python, executable=True)
    environment_root = _directory(python.parents[1])
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
    trainer_config = _file(arguments.trainer_config)

    mount_roots = {
        environment_root,
        repository,
        rllm_root,
        verl_root,
        transformers_root,
        model_root,
        adapter_root,
        task_manifest.parent,
        broker_root.parent,
        verifier_output.parent,
        workspace,
        proot.parent,
    }
    for source in mount_roots:
        _bind_destination(rootfs, source)

    driver_sources = {
        "nvidia-smi": Path("/usr/bin/nvidia-smi"),
        "libcuda.so.1": Path("/usr/lib64/libcuda.so.1"),
        "libnvidia-ml.so.1": Path("/usr/lib64/libnvidia-ml.so.1"),
        "libnvidia-ptxjitcompiler.so.1": Path("/usr/lib64/libnvidia-ptxjitcompiler.so.1"),
        "libnvidia-nvvm.so.4": Path("/usr/lib64/libnvidia-nvvm.so.4"),
    }
    driver_bindings = [
        _driver_binding(rootfs, source, name) for name, source in driver_sources.items()
    ]

    command = [
        str(proot),
        "-R",
        str(rootfs),
        "-b",
        "/dev:/dev",
        "-b",
        "/proc:/proc",
        "-b",
        "/sys:/sys",
    ]
    for source in sorted(mount_roots):
        command.extend(["-b", f"{source}:{source}"])
    for source, destination in driver_bindings:
        command.extend(["-b", f"{source}:{destination}"])
    command.extend(
        [
            "-w",
            str(repository),
            "/usr/bin/env",
            f"PATH={environment_root / 'bin'}:/opt/verigym-host-driver:/usr/bin:/bin",
            f"LD_LIBRARY_PATH=/opt/verigym-host-driver:{environment_root / 'lib'}",
            "LC_ALL=C.UTF-8",
            f"CONDA_DEFAULT_ENV={environment_root.name}",
            "PROOT_NO_SECCOMP=1",
            str(python),
            str(repository / "scripts/run_qwen35_online_native.py"),
            "--repository",
            str(repository),
            "--rllm-root",
            str(rllm_root),
            "--verl-root",
            str(verl_root),
            "--transformers-root",
            str(transformers_root),
            "--model-root",
            str(model_root),
            "--adapter-root",
            str(adapter_root),
            "--task-manifest",
            str(task_manifest),
            "--broker-root",
            str(broker_root),
            "--verifier-output",
            str(verifier_output),
            "--campaign-workspace",
            str(workspace),
            "--broker-report",
            str(broker_report),
            "--gpu-count",
            arguments.gpu_count,
            "--trainer-config",
            str(trainer_config),
            "--proot-executable",
            str(proot),
            "--proot-rootfs-identity",
            "/.export-complete",
        ]
    )
    environment = _clean_environment()
    environment["PROOT_NO_SECCOMP"] = "1"
    return subprocess.run(command, cwd=repository, env=environment, shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
