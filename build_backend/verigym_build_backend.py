"""Small PEP 517 wrapper that embeds provenance and normalizes archives."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from setuptools import build_meta as _backend

_ROOT = Path(__file__).resolve().parents[1]
_PROVENANCE_FILE = _ROOT / "src" / "verigym" / "_build_provenance.json"
_PATH_POLICY = (
    "tracked-and-nonignored files under .github, build_backend, docker, docs, examples, "
    "scripts, src, and tests, plus named root project files; generated embedded provenance "
    "and the self-referential docs/audits/reproducible_build.json report are excluded"
)
_SOURCE_PATHS = (
    ".github",
    "build_backend",
    "docker",
    "docs",
    "examples",
    "scripts",
    "src",
    "tests",
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "MANIFEST.in",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
)
_PROVENANCE_RELATIVE = "src/verigym/_build_provenance.json"
_REPRODUCIBILITY_REPORT_RELATIVE = "docs/audits/reproducible_build.json"
_ZIP_MIN_EPOCH = 315_532_800


def _git(arguments: list[str]) -> bytes:
    process = subprocess.run(
        ["git", *arguments],
        cwd=_ROOT,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        shell=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"git command failed with exit code {process.returncode}")
    return process.stdout


def _source_date_epoch() -> int | None:
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("SOURCE_DATE_EPOCH must be a non-negative integer") from exc
    if value < 0:
        raise RuntimeError("SOURCE_DATE_EPOCH must be a non-negative integer")
    return value


def _package_version() -> str:
    # Keep the backend dependency-free; the project version is a simple static
    # PEP 621 string in this repository.
    for line in (_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("cannot locate the static project version")


def _source_paths() -> list[str]:
    raw = _git(
        [
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *_SOURCE_PATHS,
        ]
    )
    return sorted(
        {
            item.decode("utf-8")
            for item in raw.split(b"\0")
            if item
            and item.decode("utf-8") not in {_PROVENANCE_RELATIVE, _REPRODUCIBILITY_REPORT_RELATIVE}
        }
    )


def _source_tree_hash(paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        encoded_path = relative.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        path = _ROOT / relative
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            digest.update(b"missing\0")
            continue
        if stat.S_ISLNK(metadata.st_mode):
            kind = b"symlink\0"
            payload = os.readlink(path).encode("utf-8")
        elif stat.S_ISREG(metadata.st_mode):
            kind = b"file\0"
            payload = path.read_bytes()
            if len(payload) != metadata.st_size:
                raise RuntimeError(f"source file changed while hashing: {relative}")
        else:
            raise RuntimeError(f"unsupported source-tree entry type: {relative}")
        digest.update(kind)
        digest.update((metadata.st_mode & 0o111).to_bytes(2, "big"))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _build_provenance() -> dict[str, Any]:
    epoch = _source_date_epoch()
    common: dict[str, Any] = {
        "schema_version": "1.0",
        "package_name": "verigym",
        "package_version": _package_version(),
        "build_backend": "setuptools.build_meta via verigym_build_backend",
        "python_build_version": platform.python_version(),
        "build_source_date_epoch": epoch,
        "source_archive_hash": None,
        "installed_distribution_metadata_hash": None,
        "source_tree_path_policy": _PATH_POLICY,
    }
    try:
        commit = _git(["rev-parse", "--verify", "HEAD^{commit}"]).decode("ascii").strip()
        paths = _source_paths()
        status = _git(
            [
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--",
                *_SOURCE_PATHS,
                f":(exclude){_PROVENANCE_RELATIVE}",
                f":(exclude){_REPRODUCIBILITY_REPORT_RELATIVE}",
            ]
        )
        return {
            **common,
            "source_commit": commit,
            "source_tree_hash": _source_tree_hash(paths),
            "dirty": bool(status),
            "provenance_method": "embedded_build",
            "source_tree_file_count": len(paths),
            "unknown_reason": None,
        }
    except (OSError, RuntimeError, subprocess.SubprocessError, UnicodeError):
        try:
            embedded = json.loads(_PROVENANCE_FILE.read_text(encoding="utf-8"))
            if not embedded.get("source_commit") or not embedded.get("source_tree_hash"):
                raise ValueError("embedded source provenance is unknown")
            return {
                **embedded,
                **common,
                "provenance_method": "embedded_source_archive",
                "unknown_reason": (
                    "source archive byte hash is unavailable to the isolated PEP 517 backend"
                ),
            }
        except (OSError, ValueError, json.JSONDecodeError):
            return {
                **common,
                "source_commit": None,
                "source_tree_hash": None,
                "dirty": None,
                "provenance_method": "unknown",
                "source_tree_file_count": None,
                "unknown_reason": "neither Git nor trustworthy embedded provenance is available",
            }


@contextlib.contextmanager
def _generated_provenance() -> Iterator[None]:
    previous = _PROVENANCE_FILE.read_bytes() if _PROVENANCE_FILE.exists() else None
    payload = json.dumps(_build_provenance(), indent=2, sort_keys=True) + "\n"
    _PROVENANCE_FILE.write_text(payload, encoding="utf-8")
    try:
        yield
    finally:
        if previous is None:
            _PROVENANCE_FILE.unlink(missing_ok=True)
        else:
            _PROVENANCE_FILE.write_bytes(previous)


@contextlib.contextmanager
def _clean_setuptools_build_tree() -> Iterator[None]:
    """Prevent ignored stale build/lib members from entering a wheel."""

    build_tree = _ROOT / "build"
    backup_root = Path(tempfile.mkdtemp(prefix=".verigym-build-backup-", dir=_ROOT))
    backup_tree = backup_root / "build"
    if build_tree.exists():
        os.replace(build_tree, backup_tree)
    try:
        yield
    finally:
        if build_tree.exists():
            shutil.rmtree(build_tree)
        if backup_tree.exists():
            os.replace(backup_tree, build_tree)
        backup_root.rmdir()


def _archive_epoch() -> int:
    return _source_date_epoch() or _ZIP_MIN_EPOCH


def _normalize_wheel(path: Path) -> None:
    epoch = max(_archive_epoch(), _ZIP_MIN_EPOCH)
    timestamp = time.gmtime(epoch)[:6]
    with zipfile.ZipFile(path, "r") as source:
        members = source.infolist()
        if len({member.filename for member in members}) != len(members):
            raise RuntimeError("wheel contains duplicate member paths")
        payloads = {member.filename: source.read(member) for member in members}
        metadata = {member.filename: member for member in members}
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as target:
            for name in sorted(payloads):
                original = metadata[name]
                member = zipfile.ZipInfo(name, date_time=timestamp)
                member.compress_type = zipfile.ZIP_DEFLATED
                member.create_system = 3
                member.external_attr = original.external_attr
                member.flag_bits = original.flag_bits
                target.writestr(member, payloads[name])
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _normalize_sdist(path: Path) -> None:
    epoch = _archive_epoch()
    with tarfile.open(path, "r:gz") as source:
        members = source.getmembers()
        if len({member.name for member in members}) != len(members):
            raise RuntimeError("sdist contains duplicate member paths")
        payloads: dict[str, bytes | None] = {}
        for member in members:
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise RuntimeError(f"sdist contains unsupported member type: {member.name}")
            stream = source.extractfile(member) if member.isfile() else None
            payloads[member.name] = stream.read() if stream is not None else None
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
                ) as target:
                    for member in sorted(members, key=lambda item: item.name):
                        member.uid = 0
                        member.gid = 0
                        member.uname = ""
                        member.gname = ""
                        member.mtime = epoch
                        member.pax_headers = {}
                        payload = payloads[member.name]
                        target.addfile(
                            member,
                            io.BytesIO(payload) if payload is not None else None,
                        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    with _clean_setuptools_build_tree(), _generated_provenance():
        name = _backend.build_wheel(wheel_directory, config_settings, metadata_directory)
    _normalize_wheel(Path(wheel_directory) / name)
    return name


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    with _clean_setuptools_build_tree(), _generated_provenance():
        name = _backend.build_sdist(sdist_directory, config_settings)
    _normalize_sdist(Path(sdist_directory) / name)
    return name


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    with _clean_setuptools_build_tree(), _generated_provenance():
        return _backend.build_editable(wheel_directory, config_settings, metadata_directory)


get_requires_for_build_wheel = _backend.get_requires_for_build_wheel
get_requires_for_build_sdist = _backend.get_requires_for_build_sdist
get_requires_for_build_editable = _backend.get_requires_for_build_editable
prepare_metadata_for_build_wheel = _backend.prepare_metadata_for_build_wheel
prepare_metadata_for_build_editable = _backend.prepare_metadata_for_build_editable
