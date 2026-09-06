"""Fail-closed private staging for qualification-only verifier assets."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from types import TracebackType

from verigym.core.errors import PathPolicyError
from verigym.core.workspace import normalize_relative_path

_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600


class PrivateQualificationStaging:
    """Create one private, non-reusable staging tree and attest its removal."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise PathPolicyError("private qualification staging root must be absolute")
        self.root = root
        self._created = False
        self._closed = False
        self._files_created = 0
        self._directories_created = 0

    def __enter__(self) -> PrivateQualificationStaging:
        if self._created or self._closed:
            raise PathPolicyError("private qualification staging cannot be reused")
        if os.path.lexists(self.root):
            raise PathPolicyError(
                "private qualification staging already exists; stale state requires review"
            )
        try:
            self.root.mkdir(mode=_DIRECTORY_MODE)
            self._chmod_nofollow(self.root, _DIRECTORY_MODE, directory=True)
            self._assert_mode(self.root, _DIRECTORY_MODE, kind="directory")
        except BaseException:
            if os.path.lexists(self.root) and not self.root.is_symlink():
                shutil.rmtree(self.root)
            raise
        self._created = True
        self._directories_created = 1
        return self

    def mkdir(self, relative: str | Path) -> Path:
        self._assert_active()
        destination = self._destination(relative)
        current = self.root
        for part in destination.relative_to(self.root).parts:
            current = current / part
            if os.path.lexists(current):
                if current.is_symlink() or not current.is_dir():
                    raise PathPolicyError("private qualification staging path is not a directory")
                self._assert_mode(current, _DIRECTORY_MODE, kind="directory")
                continue
            current.mkdir(mode=_DIRECTORY_MODE)
            self._chmod_nofollow(current, _DIRECTORY_MODE, directory=True)
            self._assert_mode(current, _DIRECTORY_MODE, kind="directory")
            self._directories_created += 1
        return destination

    def write_text(self, relative: str | Path, content: str) -> Path:
        self._assert_active()
        destination = self._destination(relative)
        if destination.parent != self.root:
            self.mkdir(destination.parent.relative_to(self.root))
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(destination, flags, _FILE_MODE)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        self._chmod_nofollow(destination, _FILE_MODE, directory=False)
        self._assert_mode(destination, _FILE_MODE, kind="file")
        self._files_created += 1
        return destination

    def write_json(self, relative: str | Path, value: object) -> Path:
        return self.write_text(relative, json.dumps(value, sort_keys=True, separators=(",", ":")))

    def cleanup(self) -> dict[str, object]:
        if not self._created:
            raise PathPolicyError("private qualification staging was never created")
        if self._closed:
            raise PathPolicyError("private qualification staging cleanup cannot be repeated")
        if self.root.is_symlink() or not self.root.is_dir():
            raise PathPolicyError("private qualification staging root identity changed")
        self._assert_mode(self.root, _DIRECTORY_MODE, kind="directory")
        shutil.rmtree(self.root)
        self._closed = True
        residual = os.path.lexists(self.root)
        if residual:
            raise PathPolicyError("private qualification staging cleanup left residual state")
        return {
            "format_id": "verigym_private_qualification_staging_receipt_v1",
            "private_directory_mode": format(_DIRECTORY_MODE, "04o"),
            "private_file_mode": format(_FILE_MODE, "04o"),
            "directories_created": self._directories_created,
            "files_created": self._files_created,
            "stale_state_rejected": True,
            "cleanup_attempted": True,
            "cleanup_complete": True,
            "residual_paths": 0,
        }

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._created and not self._closed:
            self.cleanup()

    def _destination(self, relative: str | Path) -> Path:
        normalized = normalize_relative_path(str(relative))
        return self.root / normalized

    def _assert_active(self) -> None:
        if not self._created or self._closed:
            raise PathPolicyError("private qualification staging is not active")

    @staticmethod
    def _assert_mode(path: Path, expected: int, *, kind: str) -> None:
        observed = stat.S_IMODE(path.lstat().st_mode)
        if observed != expected:
            raise PathPolicyError(
                f"private qualification staging {kind} mode must be {expected:04o}"
            )

    @staticmethod
    def _chmod_nofollow(path: Path, mode: int, *, directory: bool) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if directory and hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(path, flags)
        try:
            os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)


__all__ = ["PrivateQualificationStaging"]
