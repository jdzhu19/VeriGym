"""Restricted raw HWE artifacts that never enter public manifests or SFT datasets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_ID,
    resolve_hwe_collection_profile,
)

_SECRET = re.compile(
    r"(?:\b(?:authorization|api[_ -]?key|access[_ -]?token|password)\s*[:=]\s*['\"]?"
    r"[A-Za-z0-9._~+/=-]{8,}|\bbearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\b(?:sk|ds)-[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.I,
)


class HweRawArtifactWriter:
    """Write one bounded NDJSON audit stream as 0600 and freeze it to 0400."""

    def __init__(
        self,
        run_root: Path,
        *,
        filename: str = "raw-events.ndjson",
        profile_id: str = HWE_COLLECTION_PROFILE_ID,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", filename):
            raise ValueError("HWE raw artifact filename is not portable")
        audit_root = run_root / "private-audit"
        if audit_root.exists() and (audit_root.is_symlink() or not audit_root.is_dir()):
            raise ValueError("HWE private-audit root is unsafe")
        audit_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(audit_root, 0o700)
        self.path = audit_root / filename
        if self.path.exists():
            raise ValueError("HWE raw artifact must be new")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self._bytes = 0
        self._records = 0
        self._digest = hashlib.sha256()
        self._closed = False
        self.profile = resolve_hwe_collection_profile(profile_id)

    def append(
        self,
        record: dict[str, Any],
        *,
        command_raw_bytes: int | None = None,
        secret_scan_text: str | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("HWE raw artifact is already frozen")
        if command_raw_bytes is not None and command_raw_bytes > self.profile.raw_command_bytes:
            raise ValueError("HWE command raw output exceeded 32 MiB")
        serialized = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if _SECRET.search(serialized) or (
            secret_scan_text is not None and _SECRET.search(secret_scan_text)
        ):
            raise ValueError("HWE raw artifact failed the secret scan")
        encoded = serialized.encode("utf-8") + b"\n"
        if self._bytes + len(encoded) > self.profile.raw_episode_bytes:
            raise ValueError("HWE raw episode artifact exceeded 256 MiB")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("HWE raw artifact is not a private regular file")
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(self.path, 0o600)
        self._bytes += len(encoded)
        self._records += 1
        self._digest.update(encoded)

    def finalize(self) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("HWE raw artifact was already finalized")
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError("HWE raw artifact disappeared before finalization")
        observed = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if observed != self._digest.hexdigest() or self.path.stat().st_size != self._bytes:
            raise ValueError("HWE raw artifact identity changed before finalization")
        os.chmod(self.path, 0o400)
        self._closed = True
        return {
            "schema_version": "1.0",
            "format_id": "verigym_hwe_private_raw_artifact_manifest_v1",
            "relative_path": f"private-audit/{self.path.name}",
            "records": self._records,
            "bytes": self._bytes,
            "sha256": observed,
            "mode": "0400",
            "secret_scan": "passed",
            "observation_policy_id": self.profile.observation_policy_id,
            "public_manifest_included": False,
            "sft_dataset_included": False,
        }


__all__ = ["HweRawArtifactWriter"]
