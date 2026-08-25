#!/usr/bin/env python3
"""Create a config-only Docker image variant with an exact non-secret environment.

The filesystem layers are streamed through ``docker save``/``docker load`` and are not
rewritten.  Only the image configuration JSON and manifest tag are replaced.  This is
useful for strict runtimes that reject inherited build-time environment variables.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any, BinaryIO, cast

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONFIG_NAME = re.compile(r"^[0-9a-f]{64}\.json$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_METADATA_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output-tag", required=True)
    parser.add_argument("--user", required=True, help="Exact non-root UID:GID image user")
    parser.add_argument(
        "--environment",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Exact image environment entry; repeat in the desired order",
    )
    return parser


def _inspect(reference: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "image", "inspect", reference],
        check=True,
        capture_output=True,
        text=True,
    )
    values = json.loads(result.stdout)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise RuntimeError("Docker returned malformed image inspection data")
    return values[0]


def _read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    if member.size > _MAX_METADATA_BYTES:
        raise RuntimeError(f"oversized Docker image metadata: {member.name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise RuntimeError(f"missing Docker image metadata payload: {member.name}")
    payload = stream.read(_MAX_METADATA_BYTES + 1)
    if len(payload) != member.size:
        raise RuntimeError(f"truncated Docker image metadata: {member.name}")
    return payload


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes, mode: int = 0o644) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = mode
    archive.addfile(member, io.BytesIO(payload))


def _stream_variant(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    output_tag: str,
    environment: list[str],
    user: str,
) -> None:
    metadata: dict[str, tuple[tarfile.TarInfo, bytes]] = {}
    with tarfile.open(fileobj=source, mode="r|*") as input_archive:
        with tarfile.open(fileobj=destination, mode="w|") as output_archive:
            for member in input_archive:
                if member.name == "manifest.json" or _CONFIG_NAME.fullmatch(member.name):
                    metadata[member.name] = (member, _read_member(input_archive, member))
                    continue
                stream = input_archive.extractfile(member) if member.isfile() else None
                output_archive.addfile(member, stream)

            manifest_entry = metadata.get("manifest.json")
            if manifest_entry is None:
                raise RuntimeError("Docker save archive has no manifest.json")
            manifest = json.loads(manifest_entry[1])
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise RuntimeError("Docker save archive must contain exactly one image")
            record = manifest[0]
            if not isinstance(record, dict) or not isinstance(record.get("Config"), str):
                raise RuntimeError("Docker save manifest has no image configuration")
            old_config_name = record["Config"]
            config_entry = metadata.get(old_config_name)
            if config_entry is None:
                raise RuntimeError("Docker save archive omits its image configuration")
            config = json.loads(config_entry[1])
            if not isinstance(config, dict) or not isinstance(config.get("config"), dict):
                raise RuntimeError("Docker image configuration is malformed")
            config["config"]["Env"] = environment
            config["config"]["User"] = user
            if isinstance(config.get("container_config"), dict):
                config["container_config"]["Env"] = environment
                config["container_config"]["User"] = user
            config_payload = _json_bytes(config)
            new_config_name = f"{hashlib.sha256(config_payload).hexdigest()}.json"
            record["Config"] = new_config_name
            record["RepoTags"] = [output_tag]
            _add_bytes(output_archive, new_config_name, config_payload)
            _add_bytes(output_archive, "manifest.json", _json_bytes(manifest))


def sanitize(*, image_id: str, output_tag: str, environment: list[str], user: str) -> str:
    if not _IMAGE_ID.fullmatch(image_id):
        raise ValueError("--image-id must be an immutable sha256 image ID")
    if not _TAG.fullmatch(output_tag) or ".." in Path(output_tag).parts:
        raise ValueError("--output-tag is not a portable local Docker tag")
    if len(environment) != len({item.partition("=")[0] for item in environment}):
        raise ValueError("environment names must be unique")
    if any("=" not in item or "\x00" in item for item in environment):
        raise ValueError("environment entries must use NAME=VALUE without NUL bytes")
    if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", user):
        raise ValueError("--user must be an explicit non-root numeric UID:GID")
    source_inspection = _inspect(image_id)
    try:
        _inspect(output_tag)
    except subprocess.CalledProcessError:
        pass
    else:
        raise RuntimeError("refusing to overwrite an existing Docker image tag")

    save = subprocess.Popen(["docker", "save", image_id], stdout=subprocess.PIPE)
    load = subprocess.Popen(
        ["docker", "load"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert save.stdout is not None and load.stdin is not None
    try:
        _stream_variant(
            cast(BinaryIO, save.stdout),
            cast(BinaryIO, load.stdin),
            output_tag=output_tag,
            environment=environment,
            user=user,
        )
        save.stdout.close()
        load.stdin.close()
        load.stdin = None
        load_stdout, load_stderr = load.communicate()
        save_status = save.wait()
    except BaseException:
        save.kill()
        load.kill()
        save.wait()
        load.wait()
        raise
    if save_status != 0:
        raise RuntimeError(f"docker save failed with status {save_status}")
    if load.returncode != 0:
        message = load_stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"docker load failed: {message}")
    if output_tag.encode("utf-8") not in load_stdout:
        raise RuntimeError("docker load did not report the requested output tag")

    result = _inspect(output_tag)
    result_id = result.get("Id")
    if not isinstance(result_id, str) or not _IMAGE_ID.fullmatch(result_id):
        raise RuntimeError("sanitized Docker image has no immutable identity")
    if result_id == image_id:
        raise RuntimeError("sanitized Docker image identity did not change")
    if result.get("RootFS") != source_inspection.get("RootFS"):
        raise RuntimeError("sanitization changed Docker filesystem layer identity")
    result_config = result.get("Config")
    if not isinstance(result_config, dict) or result_config.get("Env") != environment:
        raise RuntimeError("sanitized Docker image environment differs from the exact request")
    if result_config.get("User") != user:
        raise RuntimeError("sanitized Docker image user differs from the exact request")
    return result_id


def main() -> int:
    arguments = _parser().parse_args()
    result_id = sanitize(
        image_id=arguments.image_id,
        output_tag=arguments.output_tag,
        environment=arguments.environment,
        user=arguments.user,
    )
    print(json.dumps({"image_id": result_id, "tag": arguments.output_tag}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
