#!/usr/bin/env python3
"""Fetch and validate one pinned official crane release inside a download-only container."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

_ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
_BUFFER_BYTES = 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 32
_MAX_CRANE_BYTES = 128 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--asset-url", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--asset-size", type=int, required=True)
    parser.add_argument("--checksums-url", required=True)
    parser.add_argument("--checksums-sha256", required=True)
    parser.add_argument("--checksums-size", type=int, required=True)
    parser.add_argument("--provenance-url", required=True)
    parser.add_argument("--provenance-sha256", required=True)
    parser.add_argument("--provenance-size", type=int, required=True)
    return parser


class _RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        _validate_download_url(new_url)
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _validate_download_url(value: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("crane release download URL escaped the allowlist")


def _download(
    *,
    url: str,
    destination: Path,
    expected_sha256: str,
    expected_size: int,
) -> None:
    _validate_download_url(url)
    if destination.exists() or destination.is_symlink():
        raise ValueError("crane release output already exists")
    if expected_size < 1 or expected_size > 128 * 1024 * 1024:
        raise ValueError("crane release asset size is outside the fixed bound")
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(url, headers={"User-Agent": "VeriGym-crane-bootstrap/1"})
    opener = urllib.request.build_opener(_RestrictedRedirectHandler())
    with opener.open(request, timeout=60) as response, destination.open("xb") as stream:
        _validate_download_url(response.geturl())
        while True:
            chunk = response.read(_BUFFER_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > expected_size:
                raise ValueError("crane release asset exceeded its registered size")
            digest.update(chunk)
            stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    if total != expected_size or digest.hexdigest() != expected_sha256:
        raise ValueError("crane release asset identity changed")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_BUFFER_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_checksums(path: Path, *, asset_name: str, asset_sha256: str) -> None:
    matches = []
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if separator and name == asset_name:
            matches.append(digest)
    if matches != [asset_sha256]:
        raise ValueError("official checksum list did not bind the crane release asset")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key in crane provenance")
        value[key] = item
    return value


def _validate_provenance(
    path: Path,
    *,
    asset_name: str,
    asset_sha256: str,
    release_tag: str,
) -> None:
    matched = False
    for line in path.read_text(encoding="utf-8").splitlines():
        envelope = json.loads(line, object_pairs_hook=_unique_object)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), str):
            raise ValueError("crane provenance envelope is malformed")
        payload_bytes = base64.b64decode(envelope["payload"], validate=True)
        payload = json.loads(payload_bytes, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict):
            raise ValueError("crane provenance payload is malformed")
        subjects = payload.get("subject")
        if not isinstance(subjects, list):
            continue
        for subject in subjects:
            if not isinstance(subject, dict) or subject.get("name") != asset_name:
                continue
            digest = subject.get("digest")
            if isinstance(digest, dict) and digest.get("sha256") == asset_sha256:
                serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                if "google/go-containerregistry" not in serialized or release_tag not in serialized:
                    raise ValueError("crane provenance source identity changed")
                matched = True
    if not matched:
        raise ValueError("crane provenance did not bind the registered asset")


def _extract_crane(archive_path: Path, output_path: Path) -> str:
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("crane binary output already exists")
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        if not members or len(members) > _MAX_ARCHIVE_MEMBERS:
            raise ValueError("crane release archive member count changed")
        for member in members:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or any(part in {"", ".", ".."} for part in relative.parts)
                or not member.isreg()
            ):
                raise ValueError("crane release archive contains an unsafe member")
        candidates = [member for member in members if member.name == "crane"]
        if len(candidates) != 1 or not 1 <= candidates[0].size <= _MAX_CRANE_BYTES:
            raise ValueError("crane release archive lacks one bounded crane binary")
        source = archive.extractfile(candidates[0])
        if source is None:
            raise ValueError("crane release archive binary could not be read")
        descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
        total = 0
        try:
            with os.fdopen(descriptor, "wb") as destination:
                while True:
                    chunk = source.read(_BUFFER_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > candidates[0].size:
                        raise ValueError("crane release binary exceeded its archive size")
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
        finally:
            source.close()
        if total != candidates[0].size:
            raise ValueError("crane release binary was truncated")
    metadata = output_path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError("crane release binary is not an ordinary private file")
    return _sha256_file(output_path)


def main() -> int:
    arguments = _parser().parse_args()
    if Path.cwd().resolve(strict=True) != Path("/download"):
        raise ValueError("crane bootstrap must run in its isolated download mount")
    expected_existing = {Path(__file__).name}
    if {path.name for path in Path.cwd().iterdir()} != expected_existing:
        raise ValueError("crane bootstrap download mount was not empty")
    if arguments.release_tag != "v0.22.0":
        raise ValueError("crane release tag changed")

    asset_name = "go-containerregistry_Linux_x86_64.tar.gz"
    asset = Path(asset_name)
    checksums = Path("checksums.txt")
    provenance = Path("multiple.intoto.jsonl")
    _download(
        url=arguments.asset_url,
        destination=asset,
        expected_sha256=arguments.asset_sha256,
        expected_size=arguments.asset_size,
    )
    _download(
        url=arguments.checksums_url,
        destination=checksums,
        expected_sha256=arguments.checksums_sha256,
        expected_size=arguments.checksums_size,
    )
    _download(
        url=arguments.provenance_url,
        destination=provenance,
        expected_sha256=arguments.provenance_sha256,
        expected_size=arguments.provenance_size,
    )
    _validate_checksums(asset_name=asset_name, asset_sha256=arguments.asset_sha256, path=checksums)
    _validate_provenance(
        provenance,
        asset_name=asset_name,
        asset_sha256=arguments.asset_sha256,
        release_tag=arguments.release_tag,
    )
    crane_sha256 = _extract_crane(asset, Path("crane"))
    receipt = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v20_crane_bootstrap_receipt_v1",
        "release_tag": arguments.release_tag,
        "asset_sha256": arguments.asset_sha256,
        "checksums_sha256": arguments.checksums_sha256,
        "provenance_sha256": arguments.provenance_sha256,
        "crane_sha256": crane_sha256,
    }
    receipt["receipt_hash"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    descriptor = os.open("bootstrap-receipt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
