"""Content-addressed identity for the commercial worker control plane.

Only VeriGym/server code, worker code, startup code, and sanitized identity
manifests belong in this bundle. Licensed PDK/DB/SDC contents are represented
by hashes and are never copied by this module.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import field_validator, model_validator
from verigym.plugin_api import StrictModel, content_hash, hash_bytes, hash_directory

COMMERCIAL_WORKER_RELEASE_PROTOCOL: Literal["commercial_worker_release.v1"] = (
    "commercial_worker_release.v1"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LABEL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/-]{0,255}$")


class CommercialWorkerRelease(StrictModel):
    """Hash-only release identity exchanged by resolve and execute."""

    protocol: str = COMMERCIAL_WORKER_RELEASE_PROTOCOL
    server_code_hash: str
    worker_code_hash: str
    startup_script_hash: str
    profile_bundle_hash: str
    remote_tools_hash: str
    asset_manifest_hash: str
    worker_contract_hash: str
    worker_isolation_contract_hash: str
    bundle_hash: str
    release_hash: str

    @field_validator(
        "server_code_hash",
        "worker_code_hash",
        "startup_script_hash",
        "profile_bundle_hash",
        "remote_tools_hash",
        "asset_manifest_hash",
        "worker_contract_hash",
        "worker_isolation_contract_hash",
        "bundle_hash",
        "release_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("commercial worker release identities must be lowercase SHA-256")
        return value

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value != COMMERCIAL_WORKER_RELEASE_PROTOCOL:
            raise ValueError("unsupported commercial worker release protocol")
        return value

    @model_validator(mode="after")
    def validate_release_hash(self) -> CommercialWorkerRelease:
        payload = self.model_dump(mode="json", exclude={"release_hash"})
        if content_hash(payload) != self.release_hash:
            raise ValueError("commercial worker release hash is not canonical")
        return self

    def safe_dict(self) -> dict[str, str]:
        """Return the complete release record; it contains hashes only."""

        return self.model_dump(mode="json")


def _hash_value(value: Any, *, label: str) -> str:
    if isinstance(value, bytes):
        return hash_bytes(value)
    if isinstance(value, Path):
        expanded = value.expanduser()
        metadata = os.lstat(expanded)
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"{label} cannot contain a symlink")
        resolved = expanded.resolve(strict=True)
        if stat.S_ISREG(metadata.st_mode):
            return hash_bytes(resolved.read_bytes())
        if stat.S_ISDIR(metadata.st_mode):
            return hash_directory(resolved, excluded_names={"__pycache__", ".pytest_cache"})
        raise ValueError(f"{label} is not a regular file or directory")
    if isinstance(value, str):
        return hash_bytes(value.encode("utf-8"))
    return content_hash(value)


def _hash_bundle(value: Any, *, label: str) -> str:
    """Hash a labeled bundle while retaining only labels and content hashes."""

    items: Iterable[tuple[Any, Any]]
    if isinstance(value, Mapping):
        items = value.items()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = ((str(index), item) for index, item in enumerate(value))
    else:
        return _hash_value(value, label=label)
    records: list[dict[str, str]] = []
    for raw_label, item in items:
        item_label = str(raw_label)
        if _LABEL.fullmatch(item_label) is None:
            raise ValueError(f"{label} contains an invalid logical label")
        records.append({"label": item_label, "sha256": _hash_value(item, label=label)})
    return content_hash(sorted(records, key=lambda record: record["label"]))


def _code_file_records(value: Any, *, prefix: str) -> list[dict[str, str]]:
    items: Iterable[tuple[Any, Any]]
    if isinstance(value, Mapping):
        items = value.items()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = ((str(index), item) for index, item in enumerate(value))
    else:
        items = (("payload", value),)
    records = []
    for raw_label, item in items:
        item_label = str(raw_label)
        if _LABEL.fullmatch(item_label) is None or ".." in item_label.split("/"):
            raise ValueError("commercial release code contains an invalid logical label")
        records.append(
            {
                "label": f"{prefix}/{item_label}",
                "sha256": _hash_value(item, label="commercial release code"),
            }
        )
    return records


def _code_bundle_hash(server_code: Any, worker_code: Any, startup_script: Any) -> str:
    records = [
        *_code_file_records(server_code, prefix="server"),
        *_code_file_records(worker_code, prefix="worker"),
        {"label": "startup.sh", "sha256": _hash_value(startup_script, label="startup script")},
    ]
    return content_hash(sorted(records, key=lambda record: record["label"]))


def _materialized_bundle_hash(files: Mapping[str, bytes]) -> str:
    records = [{"label": name, "sha256": hash_bytes(payload)} for name, payload in files.items()]
    return content_hash(sorted(records, key=lambda record: record["label"]))


def _validate_materialized_target(
    target: Path,
    release: CommercialWorkerRelease,
    expected_manifest: str,
) -> None:
    if stat.S_IMODE(target.stat().st_mode) & 0o222:
        raise ValueError("content-addressed release target is writable")
    manifest = target / "release.json"
    if (
        not manifest.is_file()
        or manifest.is_symlink()
        or manifest.read_text(encoding="utf-8") != expected_manifest
    ):
        raise ValueError("content-addressed release manifest differs")
    files: dict[str, bytes] = {}
    for item in sorted(target.rglob("*")):
        if item.is_symlink():
            raise ValueError("content-addressed release contains a symlink")
        if item.is_dir():
            if stat.S_IMODE(item.stat().st_mode) & 0o222:
                raise ValueError("content-addressed release directory is writable")
            continue
        if not item.is_file() or stat.S_IMODE(item.stat().st_mode) & 0o222:
            raise ValueError("content-addressed release contains an invalid file")
        if item != manifest:
            files[item.relative_to(target).as_posix()] = item.read_bytes()
    if _materialized_bundle_hash(files) != release.bundle_hash:
        raise ValueError("content-addressed release files differ")


def _hash_asset_manifest(value: Any) -> str:
    """Hash a manifest containing hashes only; reject apparent copied content."""

    if not isinstance(value, Mapping):
        raise ValueError("commercial asset manifest must be a mapping")
    sanitized: dict[str, str] = {}
    for raw_name, raw_hash in value.items():
        name = str(raw_name)
        if _LABEL.fullmatch(name) is None or not isinstance(raw_hash, str):
            raise ValueError("commercial asset manifest must contain logical names and hashes")
        if _SHA256.fullmatch(raw_hash) is None:
            raise ValueError("commercial asset manifest contains a non-hash value")
        sanitized[name] = raw_hash
    return content_hash(sanitized)


def build_commercial_worker_release(
    *,
    server_code: Any,
    worker_code: Any,
    startup_script: Any,
    profile_bundle: Any,
    remote_tools: Any,
    asset_manifest: Mapping[str, str],
    worker_contract: Any,
    worker_isolation_contract: Any,
) -> CommercialWorkerRelease:
    """Build a stable release identity from code and hash-only site metadata."""

    components = {
        "server_code_hash": _hash_bundle(server_code, label="server code"),
        "worker_code_hash": _hash_bundle(worker_code, label="worker code"),
        "startup_script_hash": _hash_value(startup_script, label="startup script"),
        "profile_bundle_hash": _hash_bundle(profile_bundle, label="profile bundle"),
        "remote_tools_hash": _hash_bundle(remote_tools, label="remote tools"),
        "asset_manifest_hash": _hash_asset_manifest(asset_manifest),
        "worker_contract_hash": _hash_value(worker_contract, label="worker contract"),
        "worker_isolation_contract_hash": _hash_value(
            worker_isolation_contract,
            label="worker isolation contract",
        ),
    }
    bundle_hash = _code_bundle_hash(server_code, worker_code, startup_script)
    payload = {
        "protocol": COMMERCIAL_WORKER_RELEASE_PROTOCOL,
        **components,
        "bundle_hash": bundle_hash,
    }
    return CommercialWorkerRelease(
        **payload,
        release_hash=content_hash(payload),
    )


def verify_commercial_worker_release(
    release: CommercialWorkerRelease,
    expected_release_hash: str,
) -> None:
    """Fail closed when the release carried by a request is not exact."""

    if _SHA256.fullmatch(expected_release_hash) is None:
        raise ValueError("expected commercial worker release hash is invalid")
    if release.release_hash != expected_release_hash:
        raise ValueError("commercial worker release differs from the expected identity")


def materialize_commercial_worker_release(
    output_root: Path,
    release: CommercialWorkerRelease,
    files: Mapping[str, bytes],
) -> Path:
    """Materialize a read-only code bundle addressed by ``release_hash``.

    ``files`` is restricted to logical bundle paths. Callers must provide
    commercial assets through ``release.asset_manifest_hash`` only.
    """

    expanded_root = output_root.expanduser()
    if expanded_root.is_symlink():
        raise ValueError("commercial release root cannot be a symlink")
    root = expanded_root.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / release.release_hash
    expected_manifest = release.model_dump_json(indent=2) + "\n"
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise ValueError("content-addressed release target is not a directory")
        _validate_materialized_target(target, release, expected_manifest)
        return target
    for name in files:
        if _LABEL.fullmatch(name) is None or name.startswith("/") or ".." in name.split("/"):
            raise ValueError("commercial release file path is invalid")
        if name == "release.json":
            raise ValueError("release.json is reserved")
    if _materialized_bundle_hash(files) != release.bundle_hash:
        raise ValueError("commercial release files differ from the release identity")
    temporary = Path(tempfile.mkdtemp(prefix="commercial-release-", dir=root))
    try:
        for name, payload in files.items():
            destination = temporary / name
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(payload)
            destination.chmod(0o444)
        manifest = temporary / "release.json"
        manifest.write_text(expected_manifest, encoding="utf-8")
        manifest.chmod(0o444)
        for directory in sorted(
            (item for item in temporary.rglob("*") if item.is_dir()), reverse=True
        ):
            directory.chmod(0o555)
        temporary.chmod(0o555)
        os.replace(temporary, target)
    except FileExistsError:
        # A concurrent producer won the content-addressed slot. Validate it
        # below instead of replacing a potentially trusted release.
        pass
    finally:
        if temporary.exists():
            for item in sorted(temporary.rglob("*"), reverse=True):
                if item.is_file():
                    item.chmod(0o600)
                    item.unlink()
                elif item.is_dir():
                    item.chmod(0o700)
                    item.rmdir()
            temporary.rmdir()
    _validate_materialized_target(target, release, expected_manifest)
    return target


__all__ = [
    "COMMERCIAL_WORKER_RELEASE_PROTOCOL",
    "CommercialWorkerRelease",
    "build_commercial_worker_release",
    "materialize_commercial_worker_release",
    "verify_commercial_worker_release",
]
