"""Trustworthy live-checkout and embedded distribution provenance."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from verigym.schemas.provenance import BuildProvenance
from verigym.version import __version__

SOURCE_TREE_PATH_POLICY = (
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
_EMBEDDED_RELATIVE_PATH = "src/verigym/_build_provenance.json"
_REPRODUCIBILITY_REPORT_RELATIVE_PATH = "docs/audits/reproducible_build.json"
_MAX_SOURCE_FILES = 100_000
_MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024


def _git(root: Path, arguments: list[str]) -> bytes:
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
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


def _repository_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    if not (candidate / ".git").exists() or not (candidate / "pyproject.toml").is_file():
        return None
    try:
        reported = Path(
            _git(candidate, ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
        ).resolve()
    except (OSError, RuntimeError, UnicodeError):
        return None
    return candidate if reported == candidate else None


def _source_paths(root: Path) -> list[str]:
    raw = _git(
        root,
        [
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *_SOURCE_PATHS,
        ],
    )
    paths = sorted(
        {
            item.decode("utf-8")
            for item in raw.split(b"\0")
            if item
            and item.decode("utf-8")
            not in {_EMBEDDED_RELATIVE_PATH, _REPRODUCIBILITY_REPORT_RELATIVE_PATH}
        }
    )
    if len(paths) > _MAX_SOURCE_FILES:
        raise RuntimeError("source identity exceeds its file-count bound")
    return paths


def _hash_source_state(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    total_bytes = 0
    for relative in paths:
        encoded_path = relative.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        path = root / relative
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
        total_bytes += len(payload)
        if total_bytes > _MAX_SOURCE_BYTES:
            raise RuntimeError("source identity exceeds its byte bound")
        digest.update(kind)
        digest.update((metadata.st_mode & 0o111).to_bytes(2, "big"))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _distribution_metadata_hash() -> str | None:
    try:
        metadata = importlib.metadata.distribution("verigym").read_text("METADATA")
    except importlib.metadata.PackageNotFoundError:
        return None
    if metadata is None:
        return None
    return hashlib.sha256(metadata.encode("utf-8")).hexdigest()


def _live_provenance(root: Path) -> BuildProvenance:
    commit = _git(root, ["rev-parse", "--verify", "HEAD^{commit}"]).decode("ascii").strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise RuntimeError("Git returned an invalid commit identity")
    paths = _source_paths(root)
    status = _git(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *_SOURCE_PATHS,
            f":(exclude){_EMBEDDED_RELATIVE_PATH}",
            f":(exclude){_REPRODUCIBILITY_REPORT_RELATIVE_PATH}",
        ],
    )
    return BuildProvenance(
        package_version=__version__,
        source_commit=commit,
        source_tree_hash=_hash_source_state(root, paths),
        dirty=bool(status),
        provenance_method="git_live_editable",
        build_backend="setuptools.build_meta via verigym_build_backend",
        python_build_version=None,
        installed_distribution_metadata_hash=_distribution_metadata_hash(),
        source_tree_path_policy=SOURCE_TREE_PATH_POLICY,
        source_tree_file_count=len(paths),
    )


def _embedded_provenance() -> BuildProvenance:
    path = Path(__file__).with_name("_build_provenance.json")
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        provenance = BuildProvenance.model_validate(raw)
    except (OSError, ValueError) as exc:
        return BuildProvenance(
            package_version=__version__,
            provenance_method="unknown",
            source_tree_path_policy=SOURCE_TREE_PATH_POLICY,
            unknown_reason=f"embedded provenance unavailable: {type(exc).__name__}",
        )
    metadata_hash = _distribution_metadata_hash()
    return provenance.model_copy(
        update={
            "installed_distribution_metadata_hash": metadata_hash,
            "unknown_reason": (
                provenance.unknown_reason
                if metadata_hash is not None
                else "installed distribution METADATA is unavailable"
            ),
        }
    )


def get_build_provenance() -> BuildProvenance:
    """Return live Git provenance for editable source, else embedded build data."""

    root = _repository_root()
    if root is not None:
        try:
            return _live_provenance(root)
        except (OSError, RuntimeError, subprocess.SubprocessError, UnicodeError) as exc:
            return BuildProvenance(
                package_version=__version__,
                provenance_method="unknown",
                source_tree_path_policy=SOURCE_TREE_PATH_POLICY,
                unknown_reason=f"live provenance unavailable: {type(exc).__name__}",
            )
    return _embedded_provenance()


__all__ = ["SOURCE_TREE_PATH_POLICY", "get_build_provenance"]
