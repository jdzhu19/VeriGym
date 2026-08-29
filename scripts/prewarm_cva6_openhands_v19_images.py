#!/usr/bin/env python3
"""Prewarm frozen v19 verifier images through the dedicated HWE bridge."""

from __future__ import annotations

import argparse
import copy
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_v19_campaign import OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

OPENHANDS_V19_PREWARM_OPT_IN_ENV = "VERIGYM_PREWARM_OPENHANDS_HWE_V19_IMAGES"
OPENHANDS_V19_PREWARM_FORMAT = "verigym_openhands_hwe_v19_image_prewarm_v1"
OPENHANDS_V19_PREWARM_NETWORK = "verigym-hwe-net"
OPENHANDS_V19_DOWNLOADER_IMAGE = (
    "sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497"
)
OPENHANDS_V19_PREWARM_REFERENCES = tuple(
    f"ghcr.io/pku-liang/openhwgroup_m_cva6:pr-{number}"
    for number in OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS
)
_SCRATCH_PARENT = Path("/data/jzhu484/Agent/.verigym-tmp")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--downloader-image", default=OPENHANDS_V19_DOWNLOADER_IMAGE)
    parser.add_argument(
        "--seal-security-failure",
        choices=["downloader_tcp_api_exposed"],
    )
    return parser


def prewarm_v19_images(*, output: Path, downloader_image: str) -> dict[str, Any]:
    """Pull in nested Docker and stream images into the network-isolated host daemon."""

    if os.environ.get(OPENHANDS_V19_PREWARM_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V19_PREWARM_OPT_IN_ENV}=1 is required")
    if downloader_image != OPENHANDS_V19_DOWNLOADER_IMAGE:
        raise ConfigurationError("OpenHands v19 downloader image identity changed")
    _validate_downloader_image(downloader_image)
    _validate_network()
    root = _new_directory(output)
    references = list(OPENHANDS_V19_PREWARM_REFERENCES)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V19_PREWARM_FORMAT,
        "status": "running",
        "downloader_image": downloader_image,
        "download_network": OPENHANDS_V19_PREWARM_NETWORK,
        "default_bridge_used": False,
        "proxy_values_recorded": False,
        "references": references,
        "images": {},
    }
    _write_progress(root, progress)
    missing = [reference for reference in references if _inspect_host_image(reference) is None]
    if not missing:
        for reference in references:
            progress["images"][reference] = _inspect_host_image(reference)
        progress["status"] = "completed"
        _write_progress(root, progress)
        return _sealed_progress(progress)

    _SCRATCH_PARENT.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="openhands-v19-prewarm.", dir=_SCRATCH_PARENT))
    container_name = f"verigym-hwe-v19-prewarm-{os.getpid()}-{secrets.token_hex(4)}"
    failure: BaseException | None = None
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--pull",
                "never",
                "--privileged",
                "--network",
                OPENHANDS_V19_PREWARM_NETWORK,
                "--mount",
                f"type=bind,src={scratch},dst=/var/lib/docker",
                "--name",
                container_name,
                "--entrypoint",
                "dockerd",
                downloader_image,
                "--host=unix:///var/run/docker.sock",
                "--storage-driver=vfs",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        _wait_for_nested_daemon(container_name)
        _validate_nested_daemon(container_name)
        for reference in missing:
            subprocess.run(
                ["docker", "exec", container_name, "docker", "pull", reference],
                check=True,
                capture_output=True,
                text=True,
                timeout=1_800,
            )
            archive = scratch / "transfer.tar"
            with archive.open("wb") as stream:
                subprocess.run(
                    ["docker", "exec", container_name, "docker", "save", reference],
                    check=True,
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    timeout=1_800,
                )
            with archive.open("rb") as stream:
                subprocess.run(
                    ["docker", "load"],
                    check=True,
                    stdin=stream,
                    capture_output=True,
                    timeout=1_800,
                )
            archive.unlink()
            inspection = _inspect_host_image(reference)
            if inspection is None:
                raise ConfigurationError("OpenHands v19 prewarm did not import a verifier image")
            progress["images"][reference] = inspection
            _write_progress(root, progress)
        for reference in references:
            inspection = _inspect_host_image(reference)
            if inspection is None:
                raise ConfigurationError("OpenHands v19 prewarm lacks a frozen verifier image")
            progress["images"][reference] = inspection
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
    finally:
        try:
            _remove_downloader_container(container_name)
            progress["temporary_downloader_removed"] = True
        except BaseException as exc:
            if failure is None:
                failure = exc
        try:
            _remove_scratch(scratch, downloader_image=downloader_image)
        except BaseException as exc:
            if failure is None:
                failure = exc
        if failure is not None:
            progress["status"] = "stopped_infrastructure_invalid"
            progress["failure_type"] = type(failure).__name__
            _write_progress(root, progress)
    if failure is not None:
        raise ConfigurationError("OpenHands v19 controlled image prewarm failed") from failure
    progress["status"] = "completed"
    progress["temporary_downloader_removed"] = True
    _write_progress(root, progress)
    return _sealed_progress(progress)


def seal_v19_prewarm_security_failure(*, output: Path, reason: str) -> dict[str, Any]:
    """Seal an interrupted prewarm after an observed security-control violation."""

    if reason != "downloader_tcp_api_exposed":
        raise ConfigurationError("OpenHands v19 prewarm failure reason is not recognized")
    expanded = output.expanduser()
    if expanded.is_symlink() or not expanded.is_dir():
        raise ConfigurationError("OpenHands v19 prewarm output is unsafe")
    root = expanded.resolve(strict=True)
    path = root / "prewarm-progress.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError("OpenHands v19 prewarm progress is malformed")
    expected_hash = value.pop("progress_hash", None)
    if (
        not isinstance(expected_hash, str)
        or content_hash(value) != expected_hash
        or value.get("format_id") != OPENHANDS_V19_PREWARM_FORMAT
        or value.get("status") != "running"
        or value.get("downloader_image") != OPENHANDS_V19_DOWNLOADER_IMAGE
        or value.get("download_network") != OPENHANDS_V19_PREWARM_NETWORK
        or value.get("default_bridge_used") is not False
        or value.get("proxy_values_recorded") is not False
        or value.get("images") != {}
        or value.get("references") != list(OPENHANDS_V19_PREWARM_REFERENCES)
    ):
        raise ConfigurationError("OpenHands v19 interrupted prewarm evidence changed")
    running = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            "name=verigym-hwe-v19-prewarm-",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if running.stdout.strip():
        raise ConfigurationError("OpenHands v19 downloader remains active")
    if any(_inspect_host_image(reference) is not None for reference in value["references"]):
        raise ConfigurationError("OpenHands v19 interrupted prewarm imported a verifier image")
    value.update(
        {
            "status": "stopped_security_invalid",
            "failure_type": "effective_control_violation",
            "failure_reason": reason,
            "temporary_downloader_removed": True,
            "host_images_imported": 0,
            "qualification_started": False,
            "provider_calls": 0,
        }
    )
    sealed = _sealed_progress(value)
    atomic_dump_json(path, sealed)
    return sealed


def _validate_downloader_image(image: str) -> None:
    values = _docker_json(["docker", "image", "inspect", image])
    if len(values) != 1 or values[0].get("Id") != image:
        raise ConfigurationError("OpenHands v19 downloader image is not local and immutable")


def _validate_network() -> None:
    values = _docker_json(["docker", "network", "inspect", OPENHANDS_V19_PREWARM_NETWORK])
    if len(values) != 1:
        raise ConfigurationError("OpenHands v19 download network inspection is malformed")
    network = values[0]
    if (
        network.get("Name") != OPENHANDS_V19_PREWARM_NETWORK
        or network.get("Driver") != "bridge"
        or network.get("Internal") is not False
    ):
        raise ConfigurationError("OpenHands v19 dedicated download network is unavailable")


def _inspect_host_image(reference: str) -> dict[str, str] | None:
    result = subprocess.run(
        ["docker", "image", "inspect", reference],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("OpenHands v19 image inspection is malformed") from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ConfigurationError("OpenHands v19 image inspection is malformed")
    image_id = values[0].get("Id")
    digests = values[0].get("RepoDigests")
    if not isinstance(image_id, str) or not isinstance(digests, list):
        raise ConfigurationError("OpenHands v19 verifier image lacks immutable identities")
    manifest_digests = sorted(
        {
            value.rsplit("@", 1)[1]
            for value in digests
            if isinstance(value, str) and "@sha256:" in value
        }
    )
    if len(manifest_digests) != 1:
        raise ConfigurationError("OpenHands v19 verifier image has ambiguous manifest identity")
    return {"image_id": image_id, "manifest_digest": manifest_digests[0]}


def _wait_for_nested_daemon(container_name: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready = subprocess.run(
            ["docker", "exec", container_name, "docker", "info"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if ready.returncode == 0:
            return
        time.sleep(1)
    raise ConfigurationError("OpenHands v19 nested download daemon did not become ready")


def _validate_nested_daemon(container_name: str) -> None:
    values = _docker_json(["docker", "container", "inspect", container_name])
    if len(values) != 1:
        raise ConfigurationError("OpenHands v19 downloader inspection is malformed")
    container = values[0]
    arguments = container.get("Args")
    host = container.get("HostConfig")
    if (
        container.get("Path") != "dockerd"
        or arguments != ["--host=unix:///var/run/docker.sock", "--storage-driver=vfs"]
        or not isinstance(host, dict)
        or host.get("NetworkMode") != OPENHANDS_V19_PREWARM_NETWORK
        or any("tcp://" in str(value) for value in arguments)
    ):
        raise ConfigurationError("OpenHands v19 downloader effective controls changed")


def _remove_downloader_container(container_name: str) -> None:
    """Remove the deterministic downloader name even if ``docker run`` timed out."""

    subprocess.run(
        ["docker", "container", "rm", "--force", container_name],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    remaining = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            f"name={container_name}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if remaining.stdout.strip():
        raise ConfigurationError("OpenHands v19 downloader cleanup failed")


def _remove_scratch(scratch: Path, *, downloader_image: str) -> None:
    if not (
        scratch.is_relative_to(_SCRATCH_PARENT)
        and scratch.name.startswith("openhands-v19-prewarm.")
    ):
        raise ConfigurationError("OpenHands v19 downloader scratch path changed")
    try:
        shutil.rmtree(scratch, ignore_errors=False)
        return
    except PermissionError:
        pass
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--mount",
            f"type=bind,src={scratch},dst=/cleanup",
            "--entrypoint",
            "/bin/sh",
            downloader_image,
            "-c",
            "find /cleanup -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +",
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    scratch.rmdir()


def _docker_json(arguments: list[str]) -> list[dict[str, Any]]:
    try:
        value = json.loads(
            subprocess.run(
                arguments,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ConfigurationError("OpenHands v19 Docker inspection failed") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConfigurationError("OpenHands v19 Docker inspection returned malformed data")
    return value


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("OpenHands v19 prewarm output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _sealed_progress(progress: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(progress)
    base.pop("progress_hash", None)
    return {**base, "progress_hash": content_hash(base)}


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "prewarm-progress.json", _sealed_progress(progress))


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.seal_security_failure is not None:
        progress = seal_v19_prewarm_security_failure(
            output=arguments.output,
            reason=arguments.seal_security_failure,
        )
        print(
            json.dumps(
                {
                    "status": progress["status"],
                    "failure_reason": progress["failure_reason"],
                    "progress_hash": progress["progress_hash"],
                },
                sort_keys=True,
            )
        )
        return 2
    progress = prewarm_v19_images(
        output=arguments.output,
        downloader_image=arguments.downloader_image,
    )
    print(
        json.dumps(
            {
                "status": progress["status"],
                "image_count": len(progress["images"]),
                "progress_hash": progress["progress_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
