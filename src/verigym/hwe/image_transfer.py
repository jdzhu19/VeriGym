"""Content-addressed, redacted image-transfer primitives for HWE materialization."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from verigym.core.errors import ConfigurationError

TransferErrorFamily = Literal[
    "dns",
    "tls",
    "timeout",
    "http_status",
    "disk_full",
    "permission",
    "checksum",
    "tar_write",
    "unknown",
]
TransferErrorFamilyV2 = Literal[
    "dns",
    "tls",
    "timeout",
    "transport",
    "http_status",
    "disk_full",
    "permission",
    "checksum",
    "tar_write",
    "unknown",
]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_STAGE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HTTP_STATUS = re.compile(r"(?:http(?: status)?|status code)\D*([45][0-9]{2})", re.IGNORECASE)
_HTTP_STATUS_V2 = re.compile(
    r"(?:http(?: status)?|status(?: code)?)\D*([45][0-9]{2})",
    re.IGNORECASE,
)
_RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class LayerCacheReceipt:
    """A bounded cache fact that never exposes a host path."""

    digest: str
    size: int
    cache_hit: bool

    def safe_dict(self) -> dict[str, str | int | bool]:
        return {"digest": self.digest, "size": self.size, "cache_hit": self.cache_hit}


@dataclass(frozen=True)
class RegistryBlobDescriptor:
    """A digest-qualified, size-bounded registry blob descriptor."""

    digest: str
    size: int


@dataclass(frozen=True)
class RegistryImageManifest:
    """The exact config and ordered layers from one platform image manifest."""

    manifest_digest: str
    manifest_size: int
    config: RegistryBlobDescriptor
    layers: tuple[RegistryBlobDescriptor, ...]


def validate_registry_image_manifest(
    raw: bytes,
    *,
    expected_digest: str,
    maximum_layers: int = 512,
) -> RegistryImageManifest:
    """Validate crane manifest output without accepting an index or unbounded layer set."""

    match = _DIGEST.fullmatch(expected_digest)
    if match is None or not 1 <= maximum_layers <= 512:
        raise ConfigurationError("HWE registry manifest policy is invalid")
    payload = raw[:-1] if raw.endswith(b"\n") else raw
    if not payload or hashlib.sha256(payload).hexdigest() != match.group(1):
        raise ConfigurationError("HWE registry manifest digest changed")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("HWE registry manifest is malformed") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("HWE registry manifest is not an object")
    allowed_media_types = {
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    }
    layers_raw = value.get("layers")
    if (
        value.get("schemaVersion") != 2
        or value.get("mediaType") not in allowed_media_types
        or not isinstance(layers_raw, list)
        or not 1 <= len(layers_raw) <= maximum_layers
    ):
        raise ConfigurationError("HWE registry platform manifest policy changed")
    config = _registry_blob_descriptor(value.get("config"), label="config")
    layers = tuple(_registry_blob_descriptor(item, label="layer") for item in layers_raw)
    if len({item.digest for item in layers}) != len(layers):
        raise ConfigurationError("HWE registry manifest repeats a layer digest")
    return RegistryImageManifest(
        manifest_digest=expected_digest,
        manifest_size=len(payload),
        config=config,
        layers=layers,
    )


def _registry_blob_descriptor(value: Any, *, label: str) -> RegistryBlobDescriptor:
    if not isinstance(value, dict):
        raise ConfigurationError(f"HWE registry {label} descriptor is malformed")
    digest = value.get("digest")
    size = value.get("size")
    if (
        not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
    ):
        raise ConfigurationError(f"HWE registry {label} descriptor is invalid")
    return RegistryBlobDescriptor(digest=digest, size=size)


class LayerCachePromotionError(ConfigurationError):
    """One or more crane staging entries were incomplete or checksum-invalid."""

    def __init__(self, inventory: list[LayerCacheReceipt]) -> None:
        super().__init__("HWE layer-cache staging contains an incomplete layer")
        self.inventory = tuple(inventory)


class LayerCacheValidationError(ConfigurationError):
    """A task-staged blob was complete enough to inspect but failed its descriptor."""

    def __init__(self, kind: Literal["size", "checksum"]) -> None:
        super().__init__(f"HWE layer-cache staged {kind} changed")
        self.kind = kind


@dataclass(frozen=True)
class LayerTransferRetryPolicy:
    """Bound retries for digest-verified environment provisioning, never model calls."""

    maximum_attempts: int = 3

    def __post_init__(self) -> None:
        if isinstance(self.maximum_attempts, bool) or not 1 <= self.maximum_attempts <= 3:
            raise ConfigurationError("HWE layer-transfer retry policy is invalid")


class ContentAddressedLayerCache:
    """Commit verified layer blobs from per-task staging into a persistent cache."""

    def __init__(self, root: Path) -> None:
        self.root = _real_directory(root, create=True)
        self._blob_root = _real_directory(self.root / "sha256", create=True)
        self._staging_root = _real_directory(self.root / ".staging", create=True)

    def task_staging(self, task_identity: str) -> Path:
        """Create one exclusive task staging directory under the cache filesystem."""

        if not _TASK_ID.fullmatch(task_identity):
            raise ConfigurationError("HWE layer-cache task identity is invalid")
        path = self._staging_root / task_identity
        try:
            path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise ConfigurationError("HWE layer-cache task staging already exists") from exc
        return _real_directory(path)

    def commit(self, staged: Path, *, digest: str, size: int) -> LayerCacheReceipt:
        """Validate a staged layer and atomically rename it to its digest path."""

        match = _DIGEST.fullmatch(digest)
        if match is None or isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ConfigurationError("HWE layer-cache digest or size is invalid")
        staged_path = _safe_regular_file(staged)
        if not staged_path.is_relative_to(self._staging_root):
            raise ConfigurationError("HWE layer-cache blob is outside task staging")
        if staged_path.stat().st_size != size:
            raise LayerCacheValidationError("size")
        observed = _sha256_file(staged_path)
        if observed != match.group(1):
            raise LayerCacheValidationError("checksum")
        target = self._blob_root / match.group(1)
        lock = self._blob_root / f".{match.group(1)}.lock"
        descriptor = os.open(
            lock,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ConfigurationError("HWE layer-cache digest lock changed")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            cache_hit = False
            if target.exists() or target.is_symlink():
                cached = _safe_regular_file(target, expected_size=size)
                if _sha256_file(cached) != match.group(1):
                    raise ConfigurationError("HWE layer-cache cached checksum changed")
                staged_path.unlink()
                cache_hit = True
            else:
                # Both paths are inside the fixed cache root, so rename is a
                # same-filesystem atomic publication after the complete validation.
                staged_path.rename(target)
                _fsync_directory(self._blob_root)
        finally:
            os.close(descriptor)
        return LayerCacheReceipt(digest=digest, size=size, cache_hit=cache_hit)

    def seed_task_staging(
        self,
        staging: Path,
        *,
        digests: list[str] | None = None,
        maximum_entries: int = 512,
    ) -> list[LayerCacheReceipt]:
        """Copy persistent blobs into crane's task cache without sharing writable inodes."""

        target_root = self._validated_task_staging(staging)
        if digests is None:
            blobs = sorted(
                path for path in self._blob_root.iterdir() if not path.name.startswith(".")
            )
        else:
            if len(digests) > maximum_entries or len(set(digests)) != len(digests):
                raise ConfigurationError("HWE layer-cache seed request is unbounded")
            blobs = []
            for digest in sorted(digests):
                match = _DIGEST.fullmatch(digest)
                if match is None:
                    raise ConfigurationError("HWE layer-cache seed digest is invalid")
                path = self._blob_root / match.group(1)
                if not path.exists() and not path.is_symlink():
                    raise ConfigurationError("HWE layer-cache seed blob is missing")
                blobs.append(path)
        if len(blobs) > maximum_entries:
            raise ConfigurationError("HWE layer-cache seed inventory is unbounded")
        receipts: list[LayerCacheReceipt] = []
        for blob in blobs:
            if re.fullmatch(r"[0-9a-f]{64}", blob.name) is None:
                raise ConfigurationError("HWE layer-cache persistent filename changed")
            source = _safe_regular_file(blob)
            if _sha256_file(source) != blob.name:
                raise ConfigurationError("HWE layer-cache persistent checksum changed")
            destination = target_root / f"sha256:{blob.name}"
            if destination.exists() or destination.is_symlink():
                raise ConfigurationError("HWE layer-cache task seed already exists")
            with source.open("rb") as input_stream, destination.open("xb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            receipts.append(
                LayerCacheReceipt(
                    digest=f"sha256:{blob.name}",
                    size=source.stat().st_size,
                    cache_hit=True,
                )
            )
        _fsync_directory(target_root)
        return receipts

    def promote_task_staging(
        self,
        staging: Path,
        *,
        maximum_entries: int = 512,
    ) -> list[LayerCacheReceipt]:
        """Validate crane v0.22 filesystem-cache files, then atomically promote valid blobs."""

        source_root = self._validated_task_staging(staging)
        entries = sorted(source_root.iterdir())
        if len(entries) > maximum_entries:
            raise ConfigurationError("HWE layer-cache promotion inventory is unbounded")
        valid: list[tuple[Path, str, int]] = []
        incomplete = False
        for path in entries:
            match = _DIGEST.fullmatch(path.name)
            if match is None:
                raise ConfigurationError("HWE layer-cache crane filename changed")
            source = _safe_regular_file(path)
            size = source.stat().st_size
            if size <= 0 or _sha256_file(source) != match.group(1):
                source.unlink()
                incomplete = True
                continue
            valid.append((source, path.name, size))
        receipts = [self.commit(path, digest=digest, size=size) for path, digest, size in valid]
        if incomplete:
            raise LayerCachePromotionError(receipts)
        return receipts

    def bounded_inventory(
        self, digests: list[str], *, maximum_entries: int = 512
    ) -> list[dict[str, Any]]:
        """Return only requested digest/size/hit facts, never cache filenames."""

        if not 0 <= len(digests) <= maximum_entries or len(set(digests)) != len(digests):
            raise ConfigurationError("HWE layer-cache inventory request is unbounded")
        inventory: list[dict[str, Any]] = []
        for digest in sorted(digests):
            match = _DIGEST.fullmatch(digest)
            if match is None:
                raise ConfigurationError("HWE layer-cache inventory digest is invalid")
            target = self._blob_root / match.group(1)
            if target.exists() or target.is_symlink():
                cached = _safe_regular_file(target)
                if _sha256_file(cached) != match.group(1):
                    raise ConfigurationError("HWE layer-cache inventory checksum changed")
                inventory.append(LayerCacheReceipt(digest, cached.stat().st_size, True).safe_dict())
            else:
                inventory.append(LayerCacheReceipt(digest, 0, False).safe_dict())
        return inventory

    def _validated_task_staging(self, path: Path) -> Path:
        resolved = _real_directory(path)
        if resolved.parent != self._staging_root:
            raise ConfigurationError("HWE layer-cache task staging boundary changed")
        return resolved


class SingleCleanupArchive:
    """Own one temporary archive and remove it at most once."""

    def __init__(self, path: Path) -> None:
        if path.exists() or path.is_symlink():
            raise ConfigurationError("HWE temporary archive path is not empty")
        self.path = path
        self._cleaned = False

    @property
    def cleanup_count(self) -> int:
        return int(self._cleaned)

    def cleanup(self) -> None:
        if self._cleaned:
            raise ConfigurationError("HWE temporary archive cleanup was repeated")
        self.path.unlink(missing_ok=True)
        self._cleaned = True

    def __enter__(self) -> SingleCleanupArchive:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.cleanup()


def redacted_transfer_failure(
    exc: BaseException,
    *,
    raw_stderr: bytes,
    stage: str,
) -> dict[str, str | int | bool]:
    """Classify temporary stderr without persisting its text or sensitive values."""

    if not _STAGE.fullmatch(stage):
        raise ConfigurationError("HWE transfer failure stage is invalid")
    family = _error_family(exc, raw_stderr)
    return {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_redacted_transfer_failure_v1",
        "stage": stage,
        "error_family": family,
        "stderr_bytes": len(raw_stderr),
        "stderr_sha256": hashlib.sha256(raw_stderr).hexdigest(),
        "raw_stderr_persisted": False,
    }


def redacted_transfer_failure_v2(
    exc: BaseException,
    *,
    raw_stderr: bytes,
    stage: str,
) -> dict[str, str | int | bool]:
    """Return a retry decision plus bounded diagnostics without stderr text."""

    if not _STAGE.fullmatch(stage):
        raise ConfigurationError("HWE transfer failure stage is invalid")
    family, reason, http_status, retryable = _error_details_v2(exc, raw_stderr)
    receipt: dict[str, str | int | bool] = {
        "schema_version": "2.0",
        "format_id": "verigym_hwe_redacted_transfer_failure_v2",
        "stage": stage,
        "error_family": family,
        "reason": reason,
        "retryable": retryable,
        "stderr_bytes": len(raw_stderr),
        "stderr_sha256": hashlib.sha256(raw_stderr).hexdigest(),
        "raw_stderr_persisted": False,
    }
    if http_status is not None:
        receipt["http_status"] = http_status
    return receipt


def _error_details_v2(
    exc: BaseException,
    stderr: bytes,
) -> tuple[TransferErrorFamilyV2, str, int | None, bool]:
    text = stderr.decode("utf-8", errors="replace").lower()
    if isinstance(exc, LayerCacheValidationError):
        return "checksum", f"staged_{exc.kind}_mismatch", None, True
    http_match = _HTTP_STATUS_V2.search(text)
    if http_match is not None:
        status = int(http_match.group(1))
        return "http_status", "http_status", status, status in _RETRYABLE_HTTP_STATUSES
    family = _error_family(exc, stderr)
    transport_reasons = (
        ("connection reset", "connection_reset"),
        ("unexpected eof", "unexpected_eof"),
        ("stream error", "stream_error"),
        ("connection closed", "connection_closed"),
        ("connection refused", "connection_refused"),
        ("broken pipe", "broken_pipe"),
    )
    for pattern, reason in transport_reasons:
        if pattern in text:
            return "transport", reason, None, True
    if re.search(r"(?:^|[^a-z])eof(?:[^a-z]|$)", text):
        return "transport", "unexpected_eof", None, True
    if family == "dns":
        return "dns", "dns", None, True
    if family == "timeout":
        return "timeout", "timeout", None, True
    if family == "tls":
        return "tls", "tls", None, False
    if family == "checksum":
        return "checksum", "checksum", None, False
    if family == "disk_full":
        return "disk_full", "disk_full", None, False
    if family == "permission":
        return "permission", "permission", None, False
    if family == "tar_write":
        return "tar_write", "tar_write", None, False
    return "unknown", "unknown", None, False


def _error_family(exc: BaseException, stderr: bytes) -> TransferErrorFamily:
    text = stderr.decode("utf-8", errors="replace").lower()
    if isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in text:
        return "timeout"
    if isinstance(exc, LayerCachePromotionError):
        return "checksum"
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "disk_full"
    if isinstance(exc, PermissionError) or (
        isinstance(exc, OSError) and exc.errno in {errno.EACCES, errno.EPERM}
    ):
        return "permission"
    if "no space left" in text or "disk full" in text:
        return "disk_full"
    if "permission denied" in text or "operation not permitted" in text:
        return "permission"
    if "certificate" in text or "tls" in text or "x509" in text:
        return "tls"
    if (
        "name resolution" in text
        or "no such host" in text
        or "temporary failure in name" in text
        or "dns" in text
    ):
        return "dns"
    if _HTTP_STATUS.search(text):
        return "http_status"
    if "checksum" in text or "digest mismatch" in text or "hash mismatch" in text:
        return "checksum"
    if "tar" in text and ("write" in text or "archive" in text):
        return "tar_write"
    return "unknown"


def _real_directory(path: Path, *, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ConfigurationError("HWE layer-cache directory cannot be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError("HWE layer-cache path is not a directory")
    return resolved


def _safe_regular_file(path: Path, *, expected_size: int | None = None) -> Path:
    if path.is_symlink():
        raise ConfigurationError("HWE layer-cache file cannot be a symlink")
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ConfigurationError("HWE layer-cache file metadata changed")
    if expected_size is not None and metadata.st_size != expected_size:
        raise ConfigurationError("HWE layer-cache file size changed")
    return path.resolve(strict=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ContentAddressedLayerCache",
    "LayerCacheReceipt",
    "LayerCachePromotionError",
    "LayerCacheValidationError",
    "LayerTransferRetryPolicy",
    "RegistryBlobDescriptor",
    "RegistryImageManifest",
    "SingleCleanupArchive",
    "TransferErrorFamily",
    "TransferErrorFamilyV2",
    "redacted_transfer_failure",
    "redacted_transfer_failure_v2",
    "validate_registry_image_manifest",
]
