from __future__ import annotations

import base64
import copy
import importlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

_preflight = importlib.import_module("scripts.preflight_openhands_hwe_v21_daemonless_prewarm")
_fetch = importlib.import_module("scripts.fetch_pinned_crane_release_v21")
_REPOSITORY = Path(__file__).resolve().parents[2]
_APPROVAL = _REPOSITORY / ("configs/training/qwen35_hwe_openhands_v21_daemonless_preflight_v1.json")


def test_v21_authorization_is_hash_bound_and_excludes_candidates() -> None:
    approved = _preflight._validated_authorization(_preflight._load_json(_APPROVAL))

    assert approved["authorization_hash"] == _preflight.OPENHANDS_V21_APPROVAL_HASH
    assert approved["authorized_actions"]["verify_crane_slsa_provenance"] is True
    assert approved["authorized_actions"]["refresh_sigstore_tuf_trust_metadata"] is True
    assert approved["required_controls"]["cryptographic_slsa_verification"] is True
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


def _bundle(*, builder_id: str | None = None) -> dict[str, Any]:
    source_uri = "git+https://github.com/google/go-containerregistry@refs/tags/v0.22.0"
    payload = {
        "_type": "https://in-toto.io/Statement/v0.1",
        "subject": [
            {
                "name": "go-containerregistry_Linux_x86_64.tar.gz",
                "digest": {"sha256": "a" * 64},
            }
        ],
        "predicateType": "https://slsa.dev/provenance/v0.2",
        "predicate": {
            "builder": {
                "id": builder_id
                or "https://github.com/slsa-framework/slsa-github-generator/"
                ".github/workflows/generator_generic_slsa3.yml@refs/tags/v2.1.0"
            },
            "buildType": "https://github.com/slsa-framework/slsa-github-generator/generic@v1",
            "invocation": {
                "configSource": {
                    "uri": source_uri,
                    "digest": {"sha1": "b" * 40},
                    "entryPoint": ".github/workflows/release.yml",
                }
            },
            "materials": [{"uri": source_uri, "digest": {"sha1": "b" * 40}}],
        },
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {
            "certificate": {"rawBytes": "certificate"},
            "tlogEntries": [{"logIndex": "1"}],
        },
        "dsseEnvelope": {
            "payload": encoded,
            "payloadType": "application/vnd.in-toto+json",
            "signatures": [{"sig": "signature"}],
        },
    }


def _validate_bundle(path: Path) -> None:
    _fetch._validate_sigstore_bundle(
        path,
        asset_name="go-containerregistry_Linux_x86_64.tar.gz",
        asset_sha256="a" * 64,
        source_uri="github.com/google/go-containerregistry",
        source_tag="v0.22.0",
        source_commit="b" * 40,
        builder_id="https://github.com/slsa-framework/slsa-github-generator/"
        ".github/workflows/generator_generic_slsa3.yml@refs/tags/v2.1.0",
        build_type="https://github.com/slsa-framework/slsa-github-generator/generic@v1",
        workflow_entrypoint=".github/workflows/release.yml",
    )


def test_v21_accepts_sigstore_bundle_wrapper_and_rejects_old_bare_dsse(tmp_path: Path) -> None:
    provenance = tmp_path / "multiple.intoto.jsonl"
    bundle = _bundle()
    provenance.write_text(json.dumps(bundle) + "\n", encoding="utf-8")
    _validate_bundle(provenance)

    provenance.write_text(json.dumps(bundle["dsseEnvelope"]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Sigstore media type"):
        _validate_bundle(provenance)


def test_v21_provenance_rejects_builder_drift(tmp_path: Path) -> None:
    provenance = tmp_path / "multiple.intoto.jsonl"
    provenance.write_text(json.dumps(_bundle(builder_id="unexpected-builder")) + "\n")
    with pytest.raises(ValueError, match="build identity changed"):
        _validate_bundle(provenance)


def test_v21_slsa_verifier_uses_exit_code_not_stderr_presence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = tmp_path / "slsa-verifier"
    asset = tmp_path / "asset"
    provenance = tmp_path / "provenance"
    for path in (verifier, asset, provenance):
        path.write_bytes(b"x")

    monkeypatch.setattr(
        _fetch.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"passed\n", stderr=b"public warning\n"
        ),
    )
    receipt = _fetch._run_slsa_verifier(
        verifier,
        asset=asset,
        provenance=provenance,
        source_uri="github.com/google/go-containerregistry",
        source_tag="v0.22.0",
    )
    assert receipt == {
        "exit_code": 0,
        "stdout_bytes": 7,
        "stderr_bytes": 15,
        "stderr_present": True,
    }

    monkeypatch.setattr(
        _fetch.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"rejected"
        ),
    )
    with pytest.raises(ValueError, match="rejected"):
        _fetch._run_slsa_verifier(
            verifier,
            asset=asset,
            provenance=provenance,
            source_uri="github.com/google/go-containerregistry",
            source_tag="v0.22.0",
        )


def test_v21_controlled_container_keeps_content_free_stderr_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(arguments: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if arguments[:2] == ["docker", "create"]:
            return subprocess.CompletedProcess(arguments, 0, b"container-id\n", b"")
        if arguments[:3] == ["docker", "start", "--attach"]:
            return subprocess.CompletedProcess(arguments, 0, b"v0.22.0\n", b"public warning\n")
        raise AssertionError(arguments)

    monkeypatch.setattr(_preflight.subprocess, "run", run)
    monkeypatch.setattr(_preflight, "_docker_json", lambda _arguments: [{}])
    monkeypatch.setattr(
        _preflight,
        "_validate_container_inspection",
        lambda *_args, **_kwargs: {"control_hash": "c" * 64},
    )
    monkeypatch.setattr(_preflight, "_remove_container", lambda _name: None)

    output, _control, receipt = _preflight._run_controlled_container(
        image_id="sha256:" + "1" * 64,
        source=tmp_path,
        mount_read_only=True,
        network="none",
        path="/download/crane",
        arguments=["version"],
        expected_environment=_preflight._EXECUTION_IMAGE_ENVIRONMENT,
        label_role="crane-version",
    )
    assert output == b"v0.22.0\n"
    assert receipt["exit_code"] == 0
    assert receipt["stderr_present"] is True
    assert receipt["stderr_bytes"] == 15
    assert "public warning" not in json.dumps(receipt)
    assert receipt["temporary_container_removed"] is True


def test_v21_failed_bootstrap_progress_names_exact_stage(tmp_path: Path) -> None:
    value = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v21_crane_bootstrap_progress_v1",
        "status": "failed",
        "current_stage": "validate_sigstore_bundle",
        "completed_stages": _preflight._BOOTSTRAP_STAGES[:5],
        "slsa_verifier_output": None,
        "sigstore_trust_root_mode": "slsa_verifier_builtin_tuf",
        "failure_stage": "validate_sigstore_bundle",
        "failure_type": "ValueError",
    }
    stored = {**value, "progress_hash": content_hash(value)}
    (tmp_path / "bootstrap-progress.json").write_text(json.dumps(stored), encoding="utf-8")

    observed = _preflight._read_bootstrap_progress(tmp_path, require_passed=False)
    assert observed is not None
    assert observed["failure_stage"] == "validate_sigstore_bundle"
    assert "message" not in observed


def test_v21_preflight_receipt_authorizes_no_candidate_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    bootstrap_progress = {"progress_hash": "e" * 64}
    monkeypatch.setenv(_preflight.OPENHANDS_V21_PREFLIGHT_OPT_IN_ENV, "1")
    monkeypatch.setattr(_preflight, "_validate_network", lambda: None)
    monkeypatch.setattr(_preflight, "_validate_local_image", lambda binding: binding)
    monkeypatch.setattr(_preflight, "_count_host_candidate_images", lambda: 0)
    monkeypatch.setattr(
        _preflight,
        "_bootstrap_crane",
        lambda *_args, **_kwargs: (
            cache,
            {"control_hash": "a" * 64},
            {"exit_code": 0},
            bootstrap_progress,
        ),
    )
    monkeypatch.setattr(
        _preflight,
        "_validated_crane_cache",
        lambda *_args, **_kwargs: {"crane_sha256": "b" * 64},
    )

    def run_container(**values: Any) -> tuple[bytes, dict[str, str], dict[str, Any]]:
        if values["arguments"] == ["version"]:
            return b"v0.22.0\n", {"control_hash": "c" * 64}, {"exit_code": 0}
        return (
            b"sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317\n",
            {"control_hash": "d" * 64},
            {"exit_code": 0},
        )

    monkeypatch.setattr(_preflight, "_run_controlled_container", run_container)
    report = _preflight.run_v21_daemonless_preflight(
        approval_path=_APPROVAL,
        output=tmp_path / "preflight",
    )

    assert report["status"] == "preflight_passed"
    assert report["slsa_verification_passed"] is True
    assert report["candidate_downloads_authorized"] is False
    assert report["candidate_downloads_started"] is False
    assert report["candidate_images_imported"] == 0
    assert report["qualification_started"] is False
    assert report["provider_calls"] == 0
    stored = json.loads((tmp_path / "preflight/preflight-report.json").read_text(encoding="utf-8"))
    observed_hash = stored.pop("report_hash")
    assert observed_hash == content_hash(stored)
