from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain import OpenToolchainImageLock
from verigym.hwe.open_toolchain_dind_mount_repair import (
    load_v180_dind_mount_repair_manifest,
)

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v172_open_toolchain as v172,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v178_local_builder as v178,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v180_dind_mount_repair as runner,
)

_MANIFEST = _ROOT / ("configs/training/qwen35_hwe_deepseek_harness_v180_dind_mount_repair_v1.json")


def _successor() -> object:
    return load_v180_dind_mount_repair_manifest(_MANIFEST)


def _runtime() -> tuple[object, object]:
    successor = _successor()
    predecessor = runner._load_predecessor(successor)  # noqa: SLF001
    upstream = v178._load_and_bind_upstream(predecessor)  # noqa: SLF001
    builder = runner._project_predecessor(successor, predecessor)  # noqa: SLF001
    return builder, v178._runtime_manifest(builder, upstream)  # noqa: SLF001


def _lock(manifest: object, builder: object) -> OpenToolchainImageLock:
    values = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_image_lock_v1",
        "identity": runner.IDENTITY,
        "agent_toolchain_id": manifest.agent_toolchain_id,
        "image_id": "sha256:" + "1" * 64,
        "accepted_open_tools_image_id": manifest.accepted_open_tools_image_id,
        "builder_image_id": builder.local_builder_image_id,
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
        "security_scan_id": "v180-open-toolchain-scan-v1",
        "security_check_count": 38,
        "security_scan_passed": True,
    }
    values["lock_hash"] = runner.content_hash(values)
    return OpenToolchainImageLock.model_validate(values)


def test_v180_reuses_frozen_task_and_builder_with_only_fresh_runtime_resources() -> None:
    successor = _successor()
    predecessor = runner._load_predecessor(successor)  # noqa: SLF001
    builder, runtime = _runtime()

    assert builder.local_builder_image_id == predecessor.local_builder_image_id
    assert builder.local_builder_archive_sha256 == predecessor.local_builder_archive_sha256
    upstream = v178._load_and_bind_upstream(predecessor)  # noqa: SLF001
    assert runtime.task == upstream.task
    assert runtime.official_verifier_image == upstream.official_verifier_image
    assert runtime.builder_tag == successor.builder_tag
    assert runtime.final_dockerfile == successor.final_dockerfile
    assert runtime.dind_data_volume == successor.dind_data_volume
    assert runtime.output_root == successor.output_root


def test_v180_final_dockerfile_changes_only_the_fresh_builder_tag() -> None:
    v178_text = (_ROOT / "docker/open-rtl-tools-hwe/Dockerfile.v178").read_text()
    v180_text = (_ROOT / "docker/open-rtl-tools-hwe/Dockerfile.v180").read_text()

    assert v180_text == v178_text.replace("v178-builder", "v180-builder")
    assert "ghcr.io/pku-liang" not in v180_text
    assert "RUN curl" not in v180_text
    assert "RUN wget" not in v180_text


def test_v180_dind_command_repairs_only_two_writable_bind_mounts(tmp_path: Path) -> None:
    _, manifest = _runtime()
    root = tmp_path / "output"
    scratch = tmp_path / "scratch"
    empty_home = scratch / "empty-home"
    command = runner._dind_command(  # noqa: SLF001
        "test-dind",
        manifest,
        root=root,
        scratch=scratch,
        empty_home=empty_home,
    )
    mount_values = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    volume_values = [
        command[index + 1] for index, value in enumerate(command) if value == "--volume"
    ]

    assert mount_values == [
        f"type=bind,src={root},dst={root}",
        f"type=bind,src={scratch},dst={scratch}",
        f"type=bind,src={empty_home},dst=/verigym-host-sentinel,readonly",
    ]
    assert all(not value.endswith(",rw") for value in mount_values[:2])
    assert mount_values[2].endswith(",readonly")
    assert volume_values == [
        f"{manifest.dind_socket_volume}:/var/run:rw",
        f"{manifest.dind_data_volume}:/var/lib/docker:rw",
    ]
    assert command[command.index("--network") + 1] == "none"
    assert "--privileged" in command


def test_v180_start_inspects_exact_mount_types_sources_and_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, manifest = _runtime()
    root = tmp_path / "output"
    scratch = tmp_path / "scratch"
    root.mkdir()
    scratch.mkdir()
    empty_home = scratch / "empty-home"
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int) -> bytes:
        calls.append(command)
        if "info" in command and "--format" in command:
            return json.dumps(
                {
                    "Driver": manifest.dind_storage_driver,
                    "DefaultRuntime": manifest.dind_default_runtime,
                }
            ).encode()
        if "version" in command:
            return f"{manifest.dind_server_version}\n".encode()
        return b"container-id\n"

    inspection = {
        "HostConfig": {"Privileged": True, "NetworkMode": "none"},
        "Config": {
            "Labels": {
                "verigym.owner": runner.OWNER,
                "verigym.role": "offline-daemon",
            },
            "Env": ["PATH=/usr/local/bin:/usr/bin", "DOCKER_TLS_CERTDIR="],
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": manifest.dind_socket_volume,
                "Destination": "/var/run",
                "RW": True,
            },
            {
                "Type": "volume",
                "Name": manifest.dind_data_volume,
                "Destination": "/var/lib/docker",
                "RW": True,
            },
            {"Type": "bind", "Source": str(root), "Destination": str(root), "RW": True},
            {
                "Type": "bind",
                "Source": str(scratch),
                "Destination": str(scratch),
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": str(empty_home),
                "Destination": "/verigym-host-sentinel",
                "RW": False,
            },
        ],
    }
    monkeypatch.setattr(runner.v172, "_run", fake_run)
    monkeypatch.setattr(
        runner.v172,
        "_run_result",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=[], returncode=0),
    )
    monkeypatch.setattr(runner.v172, "_inspect_container", lambda *_: inspection)

    receipt = runner._start_dind(  # noqa: SLF001
        "test-dind", manifest, root=root, scratch=scratch
    )

    assert receipt["mount_inspection_passed"] is True
    assert receipt["writable_bind_mount_count"] == 2
    assert receipt["readonly_bind_mount_syntax_unchanged"] is True
    assert calls[0][0:2] == ["docker", "run"]

    changed = copy.deepcopy(inspection)
    changed["Mounts"][-1]["RW"] = True
    monkeypatch.setattr(runner.v172, "_inspect_container", lambda *_: changed)
    scratch2 = tmp_path / "scratch2"
    scratch2.mkdir()
    with pytest.raises(ConfigurationError, match="isolation"):
        runner._start_dind(  # noqa: SLF001
            "test-dind-2", manifest, root=root, scratch=scratch2
        )


def test_v180_predecessor_evidence_is_exact_and_has_no_contract() -> None:
    runner._validate_predecessor_evidence(_successor())  # noqa: SLF001


def test_v180_execution_boundary_requires_new_main_and_rejects_provider(
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


def test_v180_contract_requires_both_routes_and_keeps_v182_closed() -> None:
    successor = _successor()
    builder, runtime = _runtime()
    open_comparison = {"base_failed": True, "reference_passed": True}
    official = {"base_failed": True, "reference_passed": True}
    builder_receipt = {"binding_passed": True, "binding_hash": "9" * 64}
    builder_archive = {"archive_structure_passed": True, "receipt_hash": "8" * 64}
    contract = runner._qualification_contract(  # noqa: SLF001
        successor,
        builder=builder,
        manifest=runtime,
        source_commit="a" * 40,
        post_merge_main_run_id=successor.predecessor_audit_post_merge_main_run_id + 1,
        archive_receipt={"receipt_hash": "b" * 64},
        patch_receipt={"receipt_hash": "c" * 64},
        source_binding={"task_hash": "d" * 64, "source_hash": "e" * 64},
        builder_receipt=builder_receipt,
        builder_archive_receipt=builder_archive,
        image_lock=_lock(runtime, builder),
        open_comparison=open_comparison,
        official=official,
        binding={"binding_hash": "f" * 64},
        cleanup={"cleanup_complete": True},
    )
    assert contract["requires_independent_v181_audit"] is True
    assert contract["v182_canary_authorized"] is False
    assert contract["provider_calls"] == 0
    assert contract["download_performed"] is False
    assert contract["formal_collection_allowed"] is False

    failed = copy.deepcopy(builder_receipt)
    failed["binding_passed"] = False
    with pytest.raises(ConfigurationError, match="partial qualification"):
        runner._qualification_contract(  # noqa: SLF001
            successor,
            builder=builder,
            manifest=runtime,
            source_commit="a" * 40,
            post_merge_main_run_id=successor.predecessor_audit_post_merge_main_run_id + 1,
            archive_receipt={"receipt_hash": "b" * 64},
            patch_receipt={"receipt_hash": "c" * 64},
            source_binding={"task_hash": "d" * 64, "source_hash": "e" * 64},
            builder_receipt=failed,
            builder_archive_receipt=builder_archive,
            image_lock=_lock(runtime, builder),
            open_comparison=open_comparison,
            official=official,
            binding={"binding_hash": "f" * 64},
            cleanup={"cleanup_complete": True},
        )


def test_v180_patch_context_restores_v178_and_v172_globals() -> None:
    original_v178 = (v178.IDENTITY, v178.OUTPUT_ROOT, v178.OWNER)
    original_v172 = (v172.IDENTITY, v172.OUTPUT_ROOT, v172.OWNER)
    with runner._patched_inherited_runtime():  # noqa: SLF001
        assert v178.IDENTITY == runner.IDENTITY
        assert v172.IDENTITY == runner.IDENTITY
        assert v172.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert v172.OWNER == runner.OWNER
    assert (v178.IDENTITY, v178.OUTPUT_ROOT, v178.OWNER) == original_v178
    assert (v172.IDENTITY, v172.OUTPUT_ROOT, v172.OWNER) == original_v172


def test_v180_runner_and_launcher_have_no_provider_surface() -> None:
    source = (
        _ROOT / "scripts/materialize_hwe_deepseek_harness_v180_dind_mount_repair.py"
    ).read_text(encoding="utf-8")
    launcher = (_ROOT / "scripts/launch_hwe_deepseek_harness_v180_dind_mount_repair.py").read_text(
        encoding="utf-8"
    )

    assert 'provider_calls": 0' in source
    assert "run_zero_model_smoke" in source
    assert "LocalRuntime" not in source
    assert "tenacity" not in source
    assert "retry(" not in source
    assert "ZERO_PROVIDER_CONFIGURATION_ENV_NAMES" in launcher
    assert '"DOCKER_CONTEXT"' in launcher
    assert '"DOCKER_HOST"' in launcher
    assert "os.execvp" in launcher
    assert os.path.basename(runner.__file__) in launcher
