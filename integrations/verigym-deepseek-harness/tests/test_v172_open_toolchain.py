from __future__ import annotations

import copy
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain import OpenToolchainImageLock, load_open_toolchain_manifest

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from scripts import materialize_hwe_deepseek_harness_v172_open_toolchain as runner  # noqa: E402

_MANIFEST = _ROOT / (
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
        "binary_sha256": {name: "3" * 64 for name in runner._BINARY_PATHS},  # noqa: SLF001
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
        "security_scan_id": "v172-open-toolchain-scan-v1",
        "security_check_count": 38,
        "security_scan_passed": True,
    }
    values["lock_hash"] = runner.content_hash(values)
    return OpenToolchainImageLock.model_validate(values)


def test_dockerfile_uses_only_verigym_open_inputs() -> None:
    source = (_ROOT / "docker/open-rtl-tools-hwe/Dockerfile").read_text(encoding="utf-8")
    assert "FROM verigym/open-rtl-tools:iverilog12-yosys067" in source
    assert "FROM verigym/open-rtl-tools:v172-builder" in source
    assert "ghcr.io/pku-liang" not in source
    assert "COPY --from=accepted-open-tools /opt/yosys" in source
    assert "COPY --from=accepted-open-tools /opt/iverilog" in source
    assert "RUN curl" not in source
    assert "RUN wget" not in source


def test_runner_has_zero_provider_and_no_registry_pull_surface() -> None:
    source = (_ROOT / "scripts/materialize_hwe_deepseek_harness_v172_open_toolchain.py").read_text(
        encoding="utf-8"
    )
    assert '"pull",' not in source
    assert 'provider_calls": 0' in source
    assert "run_zero_model_smoke" in source
    assert "require_toolchain_verifier_binding" in source
    assert "LocalRuntime" not in source
    assert '--network",\n        "none' in source


def test_execution_boundary_rejects_provider_names(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = load_open_toolchain_manifest(_MANIFEST)
    for name in runner.ZERO_PROVIDER_CONFIGURATION_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(runner.SANITIZED_CHILD_ENV, "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "present-but-never-read")
    monkeypatch.setattr(runner.os, "getuid", lambda: 1004)
    monkeypatch.setattr(runner.os, "getgid", lambda: 100)
    arguments = Namespace(post_merge_main_run_id=manifest.predecessor_post_merge_main_run_id + 1)
    with pytest.raises(ConfigurationError, match="provider configuration"):
        runner._require_execution_boundary(arguments, manifest)  # noqa: SLF001


def test_qualification_contract_requires_both_routes_and_keeps_canary_closed() -> None:
    manifest = load_open_toolchain_manifest(_MANIFEST)
    open_comparison = {"base_failed": True, "reference_passed": True}
    official = {"base_failed": True, "reference_passed": True}
    contract = runner._qualification_contract(  # noqa: SLF001
        manifest,
        source_commit="a" * 40,
        post_merge_main_run_id=manifest.predecessor_post_merge_main_run_id + 1,
        archive_receipt={"receipt_hash": "b" * 64},
        patch_receipt={"receipt_hash": "c" * 64},
        source_binding={"task_hash": "d" * 64, "source_hash": "e" * 64},
        image_lock=_lock(manifest),
        open_comparison=open_comparison,
        official=official,
        binding={"binding_hash": "f" * 64},
        cleanup={"cleanup_complete": True},
    )
    assert contract["agent_result_role"] == "agent_only_non_authoritative"
    assert contract["official_result_role"] == "benchmark_authoritative"
    assert contract["provider_calls"] == 0
    assert contract["v174_canary_authorized"] is False
    assert contract["formal_collection_allowed"] is False

    failed = copy.deepcopy(open_comparison)
    failed["reference_passed"] = False
    with pytest.raises(ConfigurationError, match="partial qualification"):
        runner._qualification_contract(  # noqa: SLF001
            manifest,
            source_commit="a" * 40,
            post_merge_main_run_id=manifest.predecessor_post_merge_main_run_id + 1,
            archive_receipt={"receipt_hash": "b" * 64},
            patch_receipt={"receipt_hash": "c" * 64},
            source_binding={"task_hash": "d" * 64, "source_hash": "e" * 64},
            image_lock=_lock(manifest),
            open_comparison=failed,
            official=official,
            binding={"binding_hash": "f" * 64},
            cleanup={"cleanup_complete": True},
        )


def test_binding_receipt_rejects_same_agent_and_official_hash() -> None:
    manifest = load_open_toolchain_manifest(_MANIFEST)
    open_comparison = {"receipt_hash": runner.content_hash({"official": True})}
    official = {"official": True}
    with pytest.raises(ConfigurationError, match="identities are confused"):
        runner._binding_receipt(  # noqa: SLF001
            manifest,
            open_comparison=open_comparison,
            official=official,
        )
