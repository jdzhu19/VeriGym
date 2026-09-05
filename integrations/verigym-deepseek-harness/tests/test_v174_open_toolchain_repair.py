from __future__ import annotations

import copy
import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain import OpenToolchainImageLock, load_open_toolchain_manifest
from verigym.hwe.open_toolchain_successor import load_v174_successor_manifest

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v172_open_toolchain as v172,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v174_open_toolchain_repair as runner,
)

_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v174_open_toolchain_repair_v1.json"
)
_UPSTREAM = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
)


def _lock(manifest: object) -> OpenToolchainImageLock:
    values = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_image_lock_v1",
        "identity": runner.IDENTITY,
        "agent_toolchain_id": manifest.agent_toolchain_id,
        "image_id": "sha256:" + "1" * 64,
        "accepted_open_tools_image_id": manifest.accepted_open_tools_image_id,
        "builder_image_id": "sha256:" + "2" * 64,
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
        "security_scan_id": "v174-open-toolchain-scan-v1",
        "security_check_count": 38,
        "security_scan_passed": True,
    }
    values["lock_hash"] = runner.content_hash(values)
    return OpenToolchainImageLock.model_validate(values)


def test_v174_reuses_frozen_inputs_with_fresh_runtime_identities() -> None:
    successor = load_v174_successor_manifest(_MANIFEST)
    upstream = load_open_toolchain_manifest(_UPSTREAM)
    runtime = runner._runtime_manifest(successor, upstream)  # noqa: SLF001
    assert runtime.manifest_hash == upstream.manifest_hash
    assert runtime.task == upstream.task
    assert runtime.accepted_open_tools_image_id == upstream.accepted_open_tools_image_id
    assert runtime.official_verifier_image == upstream.official_verifier_image
    assert runtime.builder_tag == successor.builder_tag
    assert runtime.final_dockerfile == successor.final_dockerfile
    assert runtime.dind_data_volume == successor.dind_data_volume
    assert runtime.output_root == successor.output_root


def test_v174_dockerfile_uses_only_fresh_builder_and_open_parent() -> None:
    source = (_ROOT / "docker/open-rtl-tools-hwe/Dockerfile.v174").read_text(encoding="utf-8")
    assert "FROM verigym/open-rtl-tools:iverilog12-yosys067" in source
    assert "FROM verigym/open-rtl-tools:v174-builder" in source
    assert "v172-builder" not in source
    assert "ghcr.io/pku-liang" not in source
    assert "RUN curl" not in source
    assert "RUN wget" not in source


def test_v174_patch_does_not_mutate_frozen_v172_globals() -> None:
    original = (v172.IDENTITY, v172.OUTPUT_ROOT, v172.OWNER)
    with runner._patched_v172_runtime():  # noqa: SLF001
        assert v172.IDENTITY == runner.IDENTITY
        assert v172.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert v172.OWNER == runner.OWNER
    assert (v172.IDENTITY, v172.OUTPUT_ROOT, v172.OWNER) == original


def test_v174_runner_has_zero_provider_no_retry_and_no_local_runtime() -> None:
    source = (
        _ROOT / "scripts/materialize_hwe_deepseek_harness_v174_open_toolchain_repair.py"
    ).read_text(encoding="utf-8")
    assert 'provider_calls": 0' in source
    assert "run_zero_model_smoke" in source
    assert "exact_repository_digest" in source
    assert "LocalRuntime" not in source
    assert "tenacity" not in source
    assert "retry(" not in source
    assert "qualification-contract.json" in source
    assert "_ALLOWED_UNTRACKED_PATHS" in source
    assert source.index("_load_official_image") < source.index("_scan_and_lock_open_image")
    assert source.index('atomic_dump_json(root / "qualification-contract.json"') > source.index(
        "_success_cleanup"
    )


def test_v174_execution_boundary_requires_new_main_and_rejects_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v174_successor_manifest(_MANIFEST)
    for name in runner.ZERO_PROVIDER_CONFIGURATION_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(runner.SANITIZED_CHILD_ENV, "1")
    monkeypatch.setattr(runner.os, "getuid", lambda: 1004)
    monkeypatch.setattr(runner.os, "getgid", lambda: 100)
    with pytest.raises(ConfigurationError, match="new post-merge"):
        runner._require_execution_boundary(  # noqa: SLF001
            Namespace(post_merge_main_run_id=manifest.predecessor_post_merge_main_run_id), manifest
        )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "present-but-never-read")
    with pytest.raises(ConfigurationError, match="provider configuration"):
        runner._require_execution_boundary(  # noqa: SLF001
            Namespace(post_merge_main_run_id=manifest.predecessor_post_merge_main_run_id + 1),
            manifest,
        )


def test_v174_contract_requires_both_routes_and_keeps_v176_closed() -> None:
    successor = load_v174_successor_manifest(_MANIFEST)
    upstream = load_open_toolchain_manifest(_UPSTREAM)
    runtime = runner._runtime_manifest(successor, upstream)  # noqa: SLF001
    open_comparison = {"base_failed": True, "reference_passed": True}
    official = {"base_failed": True, "reference_passed": True}
    contract = runner._qualification_contract(  # noqa: SLF001
        successor,
        manifest=runtime,
        source_commit="a" * 40,
        post_merge_main_run_id=successor.predecessor_post_merge_main_run_id + 1,
        archive_receipt={"receipt_hash": "b" * 64},
        patch_receipt={"receipt_hash": "c" * 64},
        source_binding={"task_hash": "d" * 64, "source_hash": "e" * 64},
        image_lock=_lock(runtime),
        open_comparison=open_comparison,
        official=official,
        binding={"binding_hash": "f" * 64},
        cleanup={"cleanup_complete": True},
    )
    assert contract["identity"] == runner.IDENTITY
    assert contract["repository_digest_parser"] == "exact-single-repository-at-sha256-v1"
    assert contract["provider_calls"] == 0
    assert contract["requires_independent_v175_audit"] is True
    assert contract["v176_canary_authorized"] is False
    assert contract["formal_collection_allowed"] is False

    failed = copy.deepcopy(open_comparison)
    failed["reference_passed"] = False
    with pytest.raises(ConfigurationError, match="partial qualification"):
        runner._qualification_contract(  # noqa: SLF001
            successor,
            manifest=runtime,
            source_commit="a" * 40,
            post_merge_main_run_id=successor.predecessor_post_merge_main_run_id + 1,
            archive_receipt={"receipt_hash": "b" * 64},
            patch_receipt={"receipt_hash": "c" * 64},
            source_binding={"task_hash": "d" * 64, "source_hash": "e" * 64},
            image_lock=_lock(runtime),
            open_comparison=failed,
            official=official,
            binding={"binding_hash": "f" * 64},
            cleanup={"cleanup_complete": True},
        )


def test_v174_launcher_strips_provider_and_ambient_docker_names() -> None:
    source = (
        _ROOT / "scripts/launch_hwe_deepseek_harness_v174_open_toolchain_repair.py"
    ).read_text(encoding="utf-8")
    assert "ZERO_PROVIDER_CONFIGURATION_ENV_NAMES" in source
    assert '"DOCKER_CONTEXT"' in source
    assert '"DOCKER_HOST"' in source
    assert "os.execvp" in source
    assert "os.environ.get(OPT_IN_ENV)" in source
    assert os.path.basename(runner.__file__) in source
