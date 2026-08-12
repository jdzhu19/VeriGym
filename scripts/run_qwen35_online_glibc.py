#!/usr/bin/env python3
"""Launch the native Qwen trainer through a hash-bound glibc loader."""

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
_DYNAMIC_LINKER_ENV = frozenset({"LD_LIBRARY_PATH", "LD_PRELOAD", "LIBRARY_PATH"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--expected-python-sha256", required=True)
    parser.add_argument("--patchelf", type=Path, required=True)
    parser.add_argument("--expected-patchelf-sha256", required=True)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--expected-rootfs-image-id", required=True)
    parser.add_argument("--nccl-library", type=Path, required=True)
    parser.add_argument("--active-nccl-library", type=Path, required=True)
    parser.add_argument("--expected-nccl-library-sha256", required=True)
    parser.add_argument("--nccl-source-root", type=Path, required=True)
    parser.add_argument("--expected-nccl-source-commit", required=True)
    parser.add_argument("--nccl-cuda-version", required=True)
    parser.add_argument("--c-compiler", type=Path, required=True)
    parser.add_argument("--expected-c-compiler-sha256", required=True)
    parser.add_argument("--expected-c-compiler-version", required=True)
    parser.add_argument("--process-tmp-root", type=Path, required=True)
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


def _linked_file(path: Path, *, confined_to: Path | None = None) -> Path:
    metadata = os.lstat(path)
    if not (stat.S_ISLNK(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
        raise RuntimeError(f"required linked file is unavailable or unsafe: {path.name}")
    value = path.resolve(strict=True)
    if not value.is_file():
        raise RuntimeError(f"required linked file target is unavailable: {path.name}")
    if confined_to is not None and not value.is_relative_to(confined_to.resolve(strict=True)):
        raise RuntimeError(f"required linked file escapes its qualified root: {path.name}")
    return value


def _private_directory(path: Path) -> Path:
    value = _directory(path)
    metadata = value.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise RuntimeError("process temporary directory must be private to the current user")
    if len(os.fsencode(value)) > 64:
        raise RuntimeError("process temporary directory path is too long for local IPC sockets")
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


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        cwd=root,
        env=_clean_environment(),
        shell=False,
        text=True,
        timeout=30,
    )
    value = completed.stdout.strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError("source does not identify a full Git commit")
    return value


def _clean_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if not _SECRET_NAME.search(name)
        and not _PROXY_NAME.fullmatch(name)
        and name not in _DYNAMIC_LINKER_ENV
    }


def _runtime_environment(
    python: Path, compiler: Path, process_tmp: Path, repository: Path
) -> dict[str, str]:
    environment = _clean_environment()
    environment.update(
        {
            "CC": str(compiler),
            "PATH": f"{compiler.parent}:{python.parent}:/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": (
                f"{repository / 'src'}:{repository / 'integrations/verigym-training-reference/src'}"
            ),
            "LD_LIBRARY_PATH": _runtime_library_path(python),
            "TMPDIR": str(process_tmp),
        }
    )
    return environment


def _runtime_library_path(python: Path) -> str:
    return f"{python.parent.parent / 'lib'}:/usr/lib64"


def _patchelf_value(patchelf: Path, option: str, executable: Path) -> str:
    environment = _clean_environment()
    environment["LD_LIBRARY_PATH"] = _runtime_library_path(executable)
    completed = subprocess.run(
        [str(patchelf), option, str(executable)],
        check=True,
        capture_output=True,
        env=environment,
        shell=False,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    python = _file(arguments.python, executable=True)
    if _sha256(python) != arguments.expected_python_sha256:
        raise RuntimeError("patched Python identity differs from its pin")
    patchelf = _file(arguments.patchelf, executable=True)
    if _sha256(patchelf) != arguments.expected_patchelf_sha256:
        raise RuntimeError("patchelf identity differs from its pin")
    rootfs = _directory(arguments.rootfs)
    rootfs_identity = _file(rootfs / ".export-complete").read_text(encoding="utf-8").strip()
    if rootfs_identity != _image_id(arguments.expected_rootfs_image_id):
        raise RuntimeError("exported rootfs image identity differs from its pin")
    loader_path = rootfs / "lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"
    loader = _linked_file(loader_path, confined_to=rootfs)
    if not os.access(loader, os.X_OK):
        raise RuntimeError("qualified dynamic loader is not executable")
    expected_rpath = ":".join(
        (
            str(python.parent.parent / "lib"),
            str(rootfs / "lib/x86_64-linux-gnu"),
            str(rootfs / "usr/lib/x86_64-linux-gnu"),
        )
    )
    if _patchelf_value(patchelf, "--print-interpreter", python) != str(loader_path):
        raise RuntimeError("patched Python interpreter differs from the qualified loader")
    if _patchelf_value(patchelf, "--print-rpath", python) != expected_rpath:
        raise RuntimeError("patched Python RPATH differs from the qualified userspace")

    nccl_library = _file(arguments.nccl_library)
    if _sha256(nccl_library) != arguments.expected_nccl_library_sha256:
        raise RuntimeError("NCCL library identity differs from its pin")
    if not _linked_file(arguments.active_nccl_library).samefile(nccl_library):
        raise RuntimeError("active Python NCCL library differs from the qualified build")
    nccl_source_root = _directory(arguments.nccl_source_root)
    if _git_head(nccl_source_root) != arguments.expected_nccl_source_commit:
        raise RuntimeError("NCCL source identity differs from its pin")
    compiler = _file(arguments.c_compiler, executable=True)
    if _sha256(compiler) != arguments.expected_c_compiler_sha256:
        raise RuntimeError("C compiler identity differs from its pin")
    completed = subprocess.run(
        [str(compiler), "--version"],
        check=True,
        capture_output=True,
        env=_clean_environment(),
        shell=False,
        text=True,
        timeout=30,
    )
    compiler_lines = completed.stdout.splitlines()
    if not compiler_lines or compiler_lines[0].strip() != arguments.expected_c_compiler_version:
        raise RuntimeError("C compiler version differs from its pin")
    process_tmp = _private_directory(arguments.process_tmp_root)

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

    environment = _runtime_environment(python, compiler, process_tmp, repository)
    command = [
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
        "--glibc-python-executable",
        str(python),
        "--glibc-loader-executable",
        str(loader),
        "--glibc-patchelf-executable",
        str(patchelf),
        "--glibc-rootfs-identity",
        str(rootfs / ".export-complete"),
        "--nccl-library",
        str(nccl_library),
        "--nccl-source-root",
        str(nccl_source_root),
        "--expected-nccl-library-sha256",
        arguments.expected_nccl_library_sha256,
        "--expected-nccl-source-commit",
        arguments.expected_nccl_source_commit,
        "--nccl-cuda-version",
        arguments.nccl_cuda_version,
        "--c-compiler",
        str(compiler),
        "--expected-c-compiler-sha256",
        arguments.expected_c_compiler_sha256,
        "--expected-c-compiler-version",
        arguments.expected_c_compiler_version,
        "--process-tmp-root",
        str(process_tmp),
    ]
    return subprocess.run(command, cwd=repository, env=environment, shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
