#!/usr/bin/env python3
"""Fetch and verify pinned crane tooling inside a download-only container."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

_ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
_BUFFER_BYTES = 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 32
_MAX_BINARY_BYTES = 128 * 1024 * 1024
_MAX_VERIFIER_OUTPUT_BYTES = 16 * 1024
_SIGSTORE_BUNDLE_MEDIA_TYPE = "application/vnd.dev.sigstore.bundle.v0.3+json"
_DSSE_PAYLOAD_TYPE = "application/vnd.in-toto+json"
_SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v0.2"
_T = TypeVar("_T")


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
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--builder-id", required=True)
    parser.add_argument("--build-type", required=True)
    parser.add_argument("--workflow-entrypoint", required=True)
    parser.add_argument("--slsa-verifier-tag", required=True)
    parser.add_argument("--slsa-verifier-url", required=True)
    parser.add_argument("--slsa-verifier-sha256", required=True)
    parser.add_argument("--slsa-verifier-size", type=int, required=True)
    parser.add_argument("--sigstore-tuf-repository", required=True)
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
        raise ValueError("release download URL escaped the allowlist")


def _download(
    *,
    url: str,
    destination: Path,
    expected_sha256: str,
    expected_size: int,
) -> None:
    _validate_download_url(url)
    if destination.exists() or destination.is_symlink():
        raise ValueError("release output already exists")
    if expected_size < 1 or expected_size > _MAX_BINARY_BYTES:
        raise ValueError("release asset size is outside the fixed bound")
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(url, headers={"User-Agent": "VeriGym-v24-bootstrap/1"})
    opener = urllib.request.build_opener(_RestrictedRedirectHandler())
    with opener.open(request, timeout=60) as response, destination.open("xb") as stream:
        _validate_download_url(response.geturl())
        while True:
            chunk = response.read(_BUFFER_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > expected_size:
                raise ValueError("release asset exceeded its registered size")
            digest.update(chunk)
            stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    if total != expected_size or digest.hexdigest() != expected_sha256:
        raise ValueError("release asset identity changed")


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
            raise ValueError("duplicate key in signed provenance")
        value[key] = item
    return value


def _required_object(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"signed provenance {field} is malformed")
    return value


def _validate_sigstore_bundle(
    path: Path,
    *,
    asset_name: str,
    asset_sha256: str,
    source_uri: str,
    source_tag: str,
    source_commit: str,
    builder_id: str,
    build_type: str,
    workflow_entrypoint: str,
) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise ValueError("crane provenance must contain one Sigstore bundle")
    bundle = json.loads(lines[0], object_pairs_hook=_unique_object)
    if not isinstance(bundle, dict) or bundle.get("mediaType") != _SIGSTORE_BUNDLE_MEDIA_TYPE:
        raise ValueError("crane provenance Sigstore media type changed")
    verification = _required_object(
        bundle.get("verificationMaterial"), field="verification material"
    )
    if not isinstance(verification.get("tlogEntries"), list) or not verification["tlogEntries"]:
        raise ValueError("crane provenance lacks transparency-log material")
    certificate = _required_object(verification.get("certificate"), field="certificate")
    if not isinstance(certificate.get("rawBytes"), str) or not certificate["rawBytes"]:
        raise ValueError("crane provenance lacks a signing certificate")
    envelope = _required_object(bundle.get("dsseEnvelope"), field="DSSE envelope")
    signatures = envelope.get("signatures")
    if (
        envelope.get("payloadType") != _DSSE_PAYLOAD_TYPE
        or not isinstance(envelope.get("payload"), str)
        or not isinstance(signatures, list)
        or len(signatures) != 1
    ):
        raise ValueError("crane provenance DSSE envelope changed")
    payload_bytes = base64.b64decode(envelope["payload"], validate=True)
    payload = json.loads(payload_bytes, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or payload.get("predicateType") != _SLSA_PREDICATE_TYPE:
        raise ValueError("crane provenance predicate type changed")
    subjects = payload.get("subject")
    matching_subjects = []
    if isinstance(subjects, list):
        matching_subjects = [
            subject
            for subject in subjects
            if isinstance(subject, dict)
            and subject.get("name") == asset_name
            and isinstance(subject.get("digest"), dict)
            and subject["digest"].get("sha256") == asset_sha256
        ]
    if len(matching_subjects) != 1:
        raise ValueError("crane provenance did not uniquely bind the registered asset")
    predicate = _required_object(payload.get("predicate"), field="predicate")
    builder = _required_object(predicate.get("builder"), field="builder")
    invocation = _required_object(predicate.get("invocation"), field="invocation")
    config_source = _required_object(invocation.get("configSource"), field="config source")
    expected_git_uri = "git+" + f"https://{source_uri}" + f"@refs/tags/{source_tag}"
    materials = predicate.get("materials")
    matching_materials = []
    if isinstance(materials, list):
        matching_materials = [
            material
            for material in materials
            if isinstance(material, dict)
            and material.get("uri") == expected_git_uri
            and isinstance(material.get("digest"), dict)
            and material["digest"].get("sha1") == source_commit
        ]
    if (
        builder.get("id") != builder_id
        or predicate.get("buildType") != build_type
        or config_source.get("uri") != expected_git_uri
        or config_source.get("entryPoint") != workflow_entrypoint
        or not isinstance(config_source.get("digest"), dict)
        or config_source["digest"].get("sha1") != source_commit
        or len(matching_materials) != 1
    ):
        raise ValueError("crane provenance build identity changed")


def _resolve_slsa_verifier_executable(
    verifier: Path,
    *,
    download_root: Path = Path("/download"),
) -> Path:
    root = download_root.resolve(strict=True)
    expected = root / "slsa-verifier-linux-amd64"
    if verifier not in {Path("slsa-verifier-linux-amd64"), expected}:
        raise ValueError("SLSA verifier path escaped the registered download root")
    metadata = expected.lstat()
    resolved = expected.resolve(strict=True)
    if (
        expected.is_symlink()
        or resolved != expected
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not os.access(expected, os.X_OK)
    ):
        raise ValueError("SLSA verifier executable is not one ordinary registered file")
    return resolved


def _run_slsa_verifier(
    verifier: Path,
    *,
    asset: Path,
    provenance: Path,
    source_uri: str,
    source_tag: str,
    download_root: Path = Path("/download"),
) -> dict[str, Any]:
    executable = _resolve_slsa_verifier_executable(verifier, download_root=download_root)
    with tempfile.TemporaryDirectory(prefix="slsa-verifier-home.", dir="/tmp") as home:
        result = subprocess.run(
            [
                str(executable),
                "verify-artifact",
                str(asset),
                "--provenance-path",
                str(provenance),
                "--source-uri",
                source_uri,
                "--source-tag",
                source_tag,
            ],
            check=False,
            capture_output=True,
            cwd=download_root,
            env={"HOME": home, "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            timeout=120,
        )
    if (
        len(result.stdout) > _MAX_VERIFIER_OUTPUT_BYTES
        or len(result.stderr) > _MAX_VERIFIER_OUTPUT_BYTES
    ):
        raise ValueError("SLSA verifier output exceeded its fixed bound")
    receipt = {
        "exit_code": result.returncode,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
        "stderr_present": bool(result.stderr),
    }
    if result.returncode != 0:
        raise ValueError("SLSA verification rejected the crane release")
    return receipt


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
        if len(candidates) != 1 or not 1 <= candidates[0].size <= _MAX_BINARY_BYTES:
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


def _hash_record(value: dict[str, Any], *, hash_name: str) -> dict[str, Any]:
    base = dict(value)
    base.pop(hash_name, None)
    digest = hashlib.sha256(
        json.dumps(base, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**base, hash_name: digest}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.next")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_progress(progress: dict[str, Any]) -> None:
    _atomic_json(Path("bootstrap-progress.json"), _hash_record(progress, hash_name="progress_hash"))


def _stage(
    progress: dict[str, Any],
    name: str,
    action: Callable[[], _T],
) -> _T:
    progress["current_stage"] = name
    _write_progress(progress)
    result = action()
    progress["completed_stages"].append(name)
    progress["current_stage"] = None
    _write_progress(progress)
    return result


def _run(arguments: argparse.Namespace) -> int:
    if Path.cwd().resolve(strict=True) != Path("/download"):
        raise ValueError("crane bootstrap must run in its isolated download mount")
    expected_existing = {Path(__file__).name}
    if {path.name for path in Path.cwd().iterdir()} != expected_existing:
        raise ValueError("crane bootstrap download mount was not empty")
    if arguments.release_tag != "v0.22.0" or arguments.slsa_verifier_tag != "v2.7.1":
        raise ValueError("registered bootstrap release tag changed")
    if arguments.sigstore_tuf_repository != "https://tuf-repo-cdn.sigstore.dev":
        raise ValueError("registered Sigstore TUF repository changed")

    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v24_crane_bootstrap_progress_v1",
        "status": "running",
        "current_stage": None,
        "completed_stages": [],
        "slsa_verifier_output": None,
        "sigstore_trust_root_mode": "slsa_verifier_builtin_tuf",
        "slsa_verifier_executable_path": "/download/slsa-verifier-linux-amd64",
    }
    _write_progress(progress)
    asset_name = "go-containerregistry_Linux_x86_64.tar.gz"
    asset = Path(asset_name)
    checksums = Path("checksums.txt")
    provenance = Path("multiple.intoto.jsonl")
    verifier = Path("slsa-verifier-linux-amd64")
    try:
        _stage(
            progress,
            "download_crane_archive",
            lambda: _download(
                url=arguments.asset_url,
                destination=asset,
                expected_sha256=arguments.asset_sha256,
                expected_size=arguments.asset_size,
            ),
        )
        _stage(
            progress,
            "download_checksums",
            lambda: _download(
                url=arguments.checksums_url,
                destination=checksums,
                expected_sha256=arguments.checksums_sha256,
                expected_size=arguments.checksums_size,
            ),
        )
        _stage(
            progress,
            "download_provenance",
            lambda: _download(
                url=arguments.provenance_url,
                destination=provenance,
                expected_sha256=arguments.provenance_sha256,
                expected_size=arguments.provenance_size,
            ),
        )
        _stage(
            progress,
            "download_slsa_verifier",
            lambda: _download(
                url=arguments.slsa_verifier_url,
                destination=verifier,
                expected_sha256=arguments.slsa_verifier_sha256,
                expected_size=arguments.slsa_verifier_size,
            ),
        )
        verifier.chmod(0o500)
        _stage(
            progress,
            "validate_checksums",
            lambda: _validate_checksums(
                checksums,
                asset_name=asset_name,
                asset_sha256=arguments.asset_sha256,
            ),
        )
        _stage(
            progress,
            "validate_sigstore_bundle",
            lambda: _validate_sigstore_bundle(
                provenance,
                asset_name=asset_name,
                asset_sha256=arguments.asset_sha256,
                source_uri=arguments.source_uri,
                source_tag=arguments.release_tag,
                source_commit=arguments.source_commit,
                builder_id=arguments.builder_id,
                build_type=arguments.build_type,
                workflow_entrypoint=arguments.workflow_entrypoint,
            ),
        )
        verifier_receipt = _stage(
            progress,
            "verify_slsa_signature",
            lambda: _run_slsa_verifier(
                verifier,
                asset=asset,
                provenance=provenance,
                source_uri=arguments.source_uri,
                source_tag=arguments.release_tag,
            ),
        )
        progress["slsa_verifier_output"] = verifier_receipt
        _write_progress(progress)
        crane_sha256 = _stage(
            progress,
            "extract_crane",
            lambda: _extract_crane(asset, Path("crane")),
        )
        receipt = {
            "schema_version": "1.0",
            "format_id": "verigym_openhands_hwe_v24_crane_bootstrap_receipt_v1",
            "release_tag": arguments.release_tag,
            "asset_sha256": arguments.asset_sha256,
            "checksums_sha256": arguments.checksums_sha256,
            "provenance_sha256": arguments.provenance_sha256,
            "source_uri": arguments.source_uri,
            "source_commit": arguments.source_commit,
            "builder_id": arguments.builder_id,
            "build_type": arguments.build_type,
            "workflow_entrypoint": arguments.workflow_entrypoint,
            "slsa_verifier_tag": arguments.slsa_verifier_tag,
            "slsa_verifier_sha256": arguments.slsa_verifier_sha256,
            "slsa_verifier_executable_path": "/download/slsa-verifier-linux-amd64",
            "sigstore_tuf_repository": arguments.sigstore_tuf_repository,
            "sigstore_trust_root_mode": "slsa_verifier_builtin_tuf",
            "slsa_verification_passed": True,
            "crane_sha256": crane_sha256,
        }
        _stage(
            progress,
            "write_bootstrap_receipt",
            lambda: _atomic_json(
                Path("bootstrap-receipt.json"),
                _hash_record(receipt, hash_name="receipt_hash"),
            ),
        )
        progress["status"] = "passed"
        progress["current_stage"] = None
        _write_progress(progress)
    except (Exception, KeyboardInterrupt) as exc:
        progress["status"] = "failed"
        progress["failure_stage"] = progress.get("current_stage") or "bootstrap_initialization"
        progress["failure_type"] = type(exc).__name__
        try:
            _write_progress(progress)
        except Exception:
            pass
        return 2
    return 0


def main() -> int:
    return _run(_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
