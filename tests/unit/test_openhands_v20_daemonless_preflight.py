from __future__ import annotations

import copy
import importlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

_preflight = importlib.import_module("scripts.preflight_openhands_hwe_v20_daemonless_prewarm")
_fetch = importlib.import_module("scripts.fetch_pinned_crane_release")
_REPOSITORY = Path(__file__).resolve().parents[2]
_APPROVAL = _REPOSITORY / "configs/training/qwen35_hwe_openhands_v20_daemonless_preflight_v1.json"


def test_v20_daemonless_authorization_is_hash_bound_and_preflight_only() -> None:
    approved = _preflight._validated_authorization(_preflight._load_json(_APPROVAL))

    assert approved["authorization_hash"] == _preflight.OPENHANDS_V20_APPROVAL_HASH
    assert approved["authorized_actions"]["download_pinned_crane_release"] is True
    assert approved["authorized_actions"]["probe_registered_non_candidate_digest"] is True
    assert approved["authorized_actions"]["download_candidate_images"] is False
    assert approved["authorized_actions"]["start_qualification"] is False
    assert approved["authorized_actions"]["invoke_provider"] is False
    assert approved["authorized_actions"]["load_heldout_tasks"] is False

    changed = copy.deepcopy(approved)
    changed["authorized_actions"]["download_candidate_images"] = True
    unsigned = {key: value for key, value in changed.items() if key != "authorization_hash"}
    changed["authorization_hash"] = content_hash(unsigned)
    with pytest.raises(ConfigurationError, match="authorization identity changed"):
        _preflight._validated_authorization(changed)


def _inspection(source: Path) -> dict[str, Any]:
    return {
        "Image": "sha256:" + "1" * 64,
        "Path": "/download/crane",
        "Args": ["version"],
        "HostConfig": {
            "NetworkMode": "none",
            "IpcMode": "none",
            "PidMode": "",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "Devices": [],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": _preflight._MEMORY_BYTES,
            "MemorySwap": _preflight._MEMORY_BYTES,
            "NanoCpus": 1_000_000_000,
            "PidsLimit": _preflight._PIDS_LIMIT,
            "PublishAllPorts": False,
            "PortBindings": {},
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": False,
            "Tmpfs": {"/tmp": _preflight._TMPFS},
        },
        "Config": {
            "User": f"{_preflight.os.getuid()}:{_preflight.os.getgid()}",
            "WorkingDir": "/download",
            "ExposedPorts": None,
            "Volumes": None,
            "Env": list(_preflight._EXECUTION_IMAGE_ENVIRONMENT),
            "Labels": {
                "org.verigym.owner": "openhands-hwe-v20-daemonless-preflight-v1",
                "org.verigym.role": "crane-version",
            },
        },
        "Mounts": [
            {
                "Source": str(source),
                "Destination": "/download",
                "RW": False,
            }
        ],
        "NetworkSettings": {"Ports": {}},
    }


def test_v20_daemonless_effective_controls_reject_privilege_ports_and_extra_mounts(
    tmp_path: Path,
) -> None:
    source = tmp_path.resolve()
    inspection = _inspection(source)
    control = _preflight._validate_container_inspection(
        inspection,
        image_id="sha256:" + "1" * 64,
        source=source,
        mount_read_only=True,
        network="none",
        path="/download/crane",
        arguments=["version"],
        expected_environment=_preflight._EXECUTION_IMAGE_ENVIRONMENT,
        label_role="crane-version",
    )
    assert control["privileged"] is False
    assert control["docker_socket_mounted"] is False
    assert control["published_ports"] is False

    for mutate in (
        lambda value: value["HostConfig"].update({"Privileged": True}),
        lambda value: value["HostConfig"].update(
            {"PortBindings": {"2375/tcp": [{"HostPort": "2375"}]}}
        ),
        lambda value: value["Mounts"].append(
            {"Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": True}
        ),
    ):
        changed = copy.deepcopy(inspection)
        mutate(changed)
        with pytest.raises(ConfigurationError, match="effective container controls changed"):
            _preflight._validate_container_inspection(
                changed,
                image_id="sha256:" + "1" * 64,
                source=source,
                mount_read_only=True,
                network="none",
                path="/download/crane",
                arguments=["version"],
                expected_environment=_preflight._EXECUTION_IMAGE_ENVIRONMENT,
                label_role="crane-version",
            )


def test_v20_crane_fetch_restricts_urls_and_extracts_only_regular_binary(
    tmp_path: Path,
) -> None:
    _fetch._validate_download_url(
        "https://github.com/google/go-containerregistry/releases/download/v0.22.0/asset"
    )
    _fetch._validate_download_url("https://release-assets.githubusercontent.com/object")
    userinfo = "user:password"
    userinfo_url = "https:" + f"//{userinfo}@github.com/google/go-containerregistry"
    for value in (
        "http://github.com/google/go-containerregistry",
        userinfo_url,
        "https://example.com/google/go-containerregistry",
    ):
        with pytest.raises(ValueError, match="allowlist"):
            _fetch._validate_download_url(value)

    archive = tmp_path / "release.tar.gz"
    payload = b"static-crane-binary"
    with tarfile.open(archive, mode="w:gz") as stream:
        member = tarfile.TarInfo("crane")
        member.size = len(payload)
        stream.addfile(member, io.BytesIO(payload))
    output = tmp_path / "crane"
    digest = _fetch._extract_crane(archive, output)
    assert output.read_bytes() == payload
    assert digest == _fetch.hashlib.sha256(payload).hexdigest()

    unsafe = tmp_path / "unsafe.tar.gz"
    with tarfile.open(unsafe, mode="w:gz") as stream:
        member = tarfile.TarInfo("../crane")
        member.size = len(payload)
        stream.addfile(member, io.BytesIO(payload))
    with pytest.raises(ValueError, match="unsafe member"):
        _fetch._extract_crane(unsafe, tmp_path / "unsafe-crane")


def test_v20_daemonless_preflight_receipt_authorizes_no_candidate_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv(_preflight.OPENHANDS_V20_PREFLIGHT_OPT_IN_ENV, "1")
    monkeypatch.setattr(_preflight, "_validate_network", lambda: None)
    monkeypatch.setattr(_preflight, "_validate_local_image", lambda binding: binding)
    monkeypatch.setattr(_preflight, "_count_host_candidate_images", lambda: 0)
    monkeypatch.setattr(
        _preflight,
        "_bootstrap_crane",
        lambda *_args, **_kwargs: (cache, {"control_hash": "a" * 64}),
    )
    monkeypatch.setattr(
        _preflight,
        "_validated_crane_cache",
        lambda *_args, **_kwargs: {"crane_sha256": "b" * 64},
    )

    def run_container(**values: Any) -> tuple[bytes, dict[str, str]]:
        if values["arguments"] == ["version"]:
            return b"v0.22.0\n", {"control_hash": "c" * 64}
        return (
            b"sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317\n",
            {"control_hash": "d" * 64},
        )

    monkeypatch.setattr(_preflight, "_run_controlled_container", run_container)
    output = tmp_path / "preflight"
    report = _preflight.run_v20_daemonless_preflight(
        approval_path=_APPROVAL,
        output=output,
    )

    assert report["status"] == "preflight_passed"
    assert report["candidate_downloads_authorized"] is False
    assert report["candidate_downloads_started"] is False
    assert report["candidate_images_imported"] == 0
    assert report["qualification_started"] is False
    assert report["provider_calls"] == 0
    stored = json.loads((output / "preflight-report.json").read_text(encoding="utf-8"))
    observed = stored.pop("report_hash")
    assert observed == content_hash(stored)
