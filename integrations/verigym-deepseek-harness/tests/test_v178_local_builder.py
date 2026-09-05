from __future__ import annotations

import copy
import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain import OpenToolchainImageLock, load_open_toolchain_manifest
from verigym.hwe.open_toolchain_local_builder import load_v178_local_builder_manifest

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v172_open_toolchain as v172,
)
from scripts import materialize_hwe_deepseek_harness_v178_local_builder as runner  # noqa: E402

_MANIFEST = _ROOT / "configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json"
_UPSTREAM = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
)


def _successor() -> object:
    return load_v178_local_builder_manifest(_MANIFEST)


def _runtime() -> object:
    successor = _successor()
    upstream = load_open_toolchain_manifest(_UPSTREAM)
    return runner._runtime_manifest(successor, upstream)  # noqa: SLF001


def _lock(manifest: object) -> OpenToolchainImageLock:
    values = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_image_lock_v1",
        "identity": runner.IDENTITY,
        "agent_toolchain_id": manifest.agent_toolchain_id,
        "image_id": "sha256:" + "1" * 64,
        "accepted_open_tools_image_id": manifest.accepted_open_tools_image_id,
        "builder_image_id": _successor().local_builder_image_id,
        "official_verifier_image": manifest.official_verifier_image,
        "binary_sha256": {name: "3" * 64 for name in v172._BINARY_PATHS},  # noqa: SLF001
        "binary_versions": {"verilator": "5.008"},
        "build_network": "none",
        "runtime_network": "none",
        "effective_user": "1004:100",
        "read_only_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "single_workspace_mount": True,
        "provider_credentials_present": False,
        "codex_present": False,
        "hwe_task_image_ancestor": False,
        "official_verifier_included": False,
        "security_scan_id": "v178-open-toolchain-scan-v1",
        "security_check_count": 38,
        "security_scan_passed": True,
    }
    values["lock_hash"] = runner.content_hash(values)
    return OpenToolchainImageLock.model_validate(values)


def _builder_image() -> dict[str, object]:
    successor = _successor()
    return {
        "Id": successor.local_builder_image_id,
        "Created": successor.local_builder_created,
        "Os": "linux",
        "Architecture": "amd64",
        "RootFS": {"Layers": list(successor.local_builder_rootfs_layers)},
        "Config": {
            "Image": successor.local_builder_parent_image_id,
            "User": "",
            "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
            "Cmd": ["bash"],
            "Entrypoint": [],
            "WorkingDir": "",
            "Labels": None,
            "Volumes": None,
        },
    }


def test_v178_reuses_frozen_task_inputs_with_fresh_runtime_identities() -> None:
    successor = _successor()
    upstream = load_open_toolchain_manifest(_UPSTREAM)
    runtime = runner._runtime_manifest(successor, upstream)  # noqa: SLF001

    assert runtime.manifest_hash == upstream.manifest_hash
    assert runtime.task == upstream.task
    assert runtime.accepted_open_tools_image_id == upstream.accepted_open_tools_image_id
    assert runtime.official_verifier_image == upstream.official_verifier_image
    assert runtime.builder_source_dockerfile == upstream.builder_source_dockerfile
    assert runtime.builder_tag == successor.builder_tag
    assert runtime.final_dockerfile == successor.final_dockerfile
    assert runtime.dind_data_volume == successor.dind_data_volume
    assert runtime.output_root == successor.output_root


def test_v178_final_dockerfile_changes_only_the_fresh_builder_tag() -> None:
    v176 = (_ROOT / "docker/open-rtl-tools-hwe/Dockerfile.v176").read_text()
    v178 = (_ROOT / "docker/open-rtl-tools-hwe/Dockerfile.v178").read_text()

    assert v178 == v176.replace("v176-builder", "v178-builder")
    assert "ghcr.io/pku-liang" not in v178
    assert "RUN curl" not in v178
    assert "RUN wget" not in v178


def test_v178_runner_has_no_generic_builder_build_or_provider_surface() -> None:
    source = (_ROOT / "scripts/materialize_hwe_deepseek_harness_v178_local_builder.py").read_text(
        encoding="utf-8"
    )

    assert "_bind_and_probe_local_builder" in source
    assert "local_builder_image_id" in source
    assert "_builder_archive_receipt" in source
    assert "local_builder_archive_path" in source
    assert '"docker", "build"' not in source
    assert 'provider_calls": 0' in source
    assert "run_zero_model_smoke" in source
    assert "LocalRuntime" not in source
    assert "tenacity" not in source
    assert "retry(" not in source
    assert source.index("_load_official_image") < source.index("_scan_and_lock_open_image")
    assert source.index('atomic_dump_json(root / "qualification-contract.json"') > source.index(
        "_success_cleanup"
    )


def test_v178_local_builder_metadata_and_history_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor()
    runtime = _runtime()
    monkeypatch.setattr(runner, "_local_builder_history", lambda *args, **kwargs: b"history")
    monkeypatch.setattr(runner, "_validate_builder_history", lambda *_: None)
    monkeypatch.setattr(
        v172,
        "_inspect_image",
        lambda image, **kwargs: (
            _builder_image() if image == successor.local_builder_image_id else None
        ),
    )
    monkeypatch.setattr(v172, "_is_ancestor_layers", lambda *_: False)
    runner._validate_local_builder(successor, runtime, docker_host="unix:///test.sock")  # noqa: SLF001

    changed = _builder_image()
    changed["RootFS"] = {"Layers": ["sha256:" + "0" * 64]}
    monkeypatch.setattr(
        v172,
        "_inspect_image",
        lambda image, **kwargs: changed if image == successor.local_builder_image_id else None,
    )
    with pytest.raises(ConfigurationError, match="metadata"):
        runner._validate_local_builder(  # noqa: SLF001
            successor, runtime, docker_host="unix:///test.sock"
        )


def test_v178_history_reader_requires_exact_bounded_secret_free_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor()
    expected = b"x" * successor.local_builder_history_bytes
    monkeypatch.setattr(
        runner.v176,
        "_run_bounded_process",
        lambda *args, **kwargs: runner.v176._BoundedResult(0, expected, b"", False, True),
    )
    assert (  # noqa: SLF001
        runner._local_builder_history(successor, docker_host="unix:///test.sock") == expected
    )

    monkeypatch.setattr(
        runner.v176,
        "_run_bounded_process",
        lambda *args, **kwargs: runner.v176._BoundedResult(0, expected, b"stderr", False, True),
    )
    with pytest.raises(ConfigurationError, match="history binding"):
        runner._local_builder_history(successor, docker_host="unix:///test.sock")  # noqa: SLF001


def test_v178_execution_boundary_requires_new_main_and_rejects_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _successor()
    for name in runner.ZERO_PROVIDER_CONFIGURATION_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(runner.SANITIZED_CHILD_ENV, "1")
    monkeypatch.setattr(runner.os, "getuid", lambda: 1004)
    monkeypatch.setattr(runner.os, "getgid", lambda: 100)
    with pytest.raises(ConfigurationError, match="new post-merge"):
        runner._require_execution_boundary(  # noqa: SLF001
            Namespace(post_merge_main_run_id=manifest.predecessor_audit_post_merge_main_run_id),
            manifest,
        )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "present-but-never-read")
    with pytest.raises(ConfigurationError, match="provider configuration"):
        runner._require_execution_boundary(  # noqa: SLF001
            Namespace(post_merge_main_run_id=manifest.predecessor_audit_post_merge_main_run_id + 1),
            manifest,
        )


def test_v178_contract_requires_both_routes_and_keeps_v180_closed() -> None:
    successor = _successor()
    runtime = _runtime()
    open_comparison = {"base_failed": True, "reference_passed": True}
    official = {"base_failed": True, "reference_passed": True}
    builder = {"binding_passed": True, "binding_hash": "9" * 64}
    builder_archive = {
        "archive_structure_passed": True,
        "receipt_hash": "8" * 64,
    }
    contract = runner._qualification_contract(  # noqa: SLF001
        successor,
        manifest=runtime,
        source_commit="a" * 40,
        post_merge_main_run_id=successor.predecessor_audit_post_merge_main_run_id + 1,
        archive_receipt={"receipt_hash": "b" * 64},
        patch_receipt={"receipt_hash": "c" * 64},
        source_binding={"task_hash": "d" * 64, "source_hash": "e" * 64},
        builder_receipt=builder,
        builder_archive_receipt=builder_archive,
        image_lock=_lock(runtime),
        open_comparison=open_comparison,
        official=official,
        binding={"binding_hash": "f" * 64},
        cleanup={"cleanup_complete": True},
    )
    assert contract["provider_calls"] == 0
    assert contract["requires_independent_v179_audit"] is True
    assert contract["v180_canary_authorized"] is False
    assert contract["download_performed"] is False
    assert contract["formal_collection_allowed"] is False

    failed = copy.deepcopy(builder)
    failed["binding_passed"] = False
    with pytest.raises(ConfigurationError, match="partial qualification"):
        runner._qualification_contract(  # noqa: SLF001
            successor,
            manifest=runtime,
            source_commit="a" * 40,
            post_merge_main_run_id=successor.predecessor_audit_post_merge_main_run_id + 1,
            archive_receipt={"receipt_hash": "b" * 64},
            patch_receipt={"receipt_hash": "c" * 64},
            source_binding={"task_hash": "d" * 64, "source_hash": "e" * 64},
            builder_receipt=failed,
            builder_archive_receipt=builder_archive,
            image_lock=_lock(runtime),
            open_comparison=open_comparison,
            official=official,
            binding={"binding_hash": "f" * 64},
            cleanup={"cleanup_complete": True},
        )


def test_v178_patch_does_not_mutate_frozen_v172_globals() -> None:
    original = (v172.IDENTITY, v172.OUTPUT_ROOT, v172.OWNER)
    with runner._patched_v172_runtime():  # noqa: SLF001
        assert v172.IDENTITY == runner.IDENTITY
        assert v172.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert v172.OWNER == runner.OWNER
    assert (v172.IDENTITY, v172.OUTPUT_ROOT, v172.OWNER) == original


def test_v178_launcher_strips_provider_and_ambient_docker_names() -> None:
    source = (_ROOT / "scripts/launch_hwe_deepseek_harness_v178_local_builder.py").read_text(
        encoding="utf-8"
    )
    assert "ZERO_PROVIDER_CONFIGURATION_ENV_NAMES" in source
    assert '"DOCKER_CONTEXT"' in source
    assert '"DOCKER_HOST"' in source
    assert "os.execvp" in source
    assert "os.environ.get(OPT_IN_ENV)" in source
    assert os.path.basename(runner.__file__) in source
