from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from verigym.core.hashing import content_hash
from verigym.hwe.image_lock import (
    HweCommandImageLock,
    HweCommandSourceLock,
    build_hwe_command_image_lock,
    build_hwe_command_source_lock,
)


def _values() -> dict[str, object]:
    return {
        "task_id": "openhwgroup/cva6:pr-2330",
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "verifier_base_image_id": "sha256:" + "3" * 64,
        "derived_command_image_id": "sha256:" + "4" * 64,
        "rg_sha256": "5" * 64,
        "rg_release_archive_sha256": "6" * 64,
        "toolchain_profile_id": "cva6-verilator-5.008-container-native-v2",
        "allowlisted_artifacts": [
            {"path": "/usr/bin/make", "sha256": "7" * 64, "role": "build_tool"},
            {
                "path": "/tools/verilator/bin/verilator",
                "sha256": "8" * 64,
                "role": "simulator",
            },
        ],
        "security_scan_id": "9" * 64,
    }


def test_command_image_lock_has_no_codex_executable_identity() -> None:
    lock = build_hwe_command_image_lock(**_values())

    assert lock.format_id == "verigym_hwe_command_image_lock_v1"
    assert lock.codex_present is False
    assert lock.supported_execution_backends == (
        "ephemeral_container_v1",
        "episode_container_exec_v1",
    )
    assert lock.lock_hash == content_hash(lock.model_dump(mode="json", exclude={"lock_hash"}))
    payload = lock.model_dump(mode="json")
    assert "agent_codex_sha256" not in payload
    assert "host_codex_sha256" not in payload
    assert all("/codex/" not in item.path for item in lock.allowlisted_artifacts)


def test_command_image_lock_tampering_fails_closed() -> None:
    lock = build_hwe_command_image_lock(**_values())
    changed = lock.model_dump(mode="json")
    changed["rg_sha256"] = "a" * 64
    with pytest.raises(ValidationError, match="identity changed"):
        HweCommandImageLock.model_validate(changed)


def test_command_image_lock_accepts_ibex_whiteout_without_weakening_path_policy() -> None:
    values = _values()
    values["task_id"] = "lowRISC/ibex:pr-54"
    values["source_whiteout_path"] = "/home/ibex"
    values["toolchain_profile_id"] = "ibex-iverilog-container-native-v1"
    values["allowlisted_artifacts"] = [
        {"path": "/usr/bin/make", "sha256": "7" * 64, "role": "build_tool"},
        {"path": "/usr/bin/iverilog", "sha256": "8" * 64, "role": "simulator"},
    ]

    lock = build_hwe_command_image_lock(**values)

    assert lock.source_whiteout_path == "/home/ibex"
    rejected = dict(values)
    rejected["allowlisted_artifacts"] = [
        {"path": "/usr/bin/make", "sha256": "7" * 64, "role": "build_tool"},
        {"path": "/home/ibex/secret", "sha256": "8" * 64, "role": "simulator"},
    ]
    with pytest.raises(ValidationError, match="source, workspace, or root-home"):
        build_hwe_command_image_lock(**rejected)


def test_command_source_lock_seals_qualified_source_and_verifier() -> None:
    lock = build_hwe_command_source_lock(
        task_id="hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728",
        task_hash="1" * 64,
        source_hash="2" * 64,
        prepared_source_image_lock_sha256="3" * 64,
        verifier_base_image_id=f"sha256:{'4' * 64}",
        toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
        allowlisted_artifacts=[
            {"path": "/usr/bin/make", "sha256": "5" * 64, "role": "build_tool"},
            {
                "path": "/tools/verilator/bin/verilator_bin",
                "sha256": "6" * 64,
                "role": "simulator",
            },
        ],
    )

    assert HweCommandSourceLock.model_validate(lock.model_dump(mode="json")) == lock
    changed = lock.model_dump(mode="json")
    changed["source_hash"] = "7" * 64
    with pytest.raises(ValidationError, match="identity changed"):
        HweCommandSourceLock.model_validate(changed)


def test_command_image_builder_rejects_codex_bundled_rg_and_sanitizes_environment() -> None:
    script = Path("scripts/build_cva6_hwe_command_image.sh").read_text(encoding="utf-8")
    dockerfile = Path("docker/cva6-hwe-command/Dockerfile").read_text(encoding="utf-8")

    assert "'/@openai/codex/'" in script
    assert "'/codex-path/'" in script
    assert "tar -xOzf" in script
    assert "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c" in script
    assert "sanitize_docker_image_environment.py" in script
    assert "--network none" in script
    assert "CODEX_HOME" not in script
    assert 'org.verigym.codex.present="absent"' in dockerfile
    assert 'CMD ["/usr/bin/tail", "-f", "/dev/null"]' in dockerfile


def test_ibex_command_image_builder_whites_out_source_and_keeps_only_public_tools() -> None:
    script = Path("scripts/build_ibex_hwe_command_image.sh").read_text(encoding="utf-8")
    dockerfile = Path("docker/ibex-hwe-command/Dockerfile").read_text(encoding="utf-8")

    assert "--network none" in script
    assert "sanitize_docker_image_environment.py" in script
    assert "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849" in script
    assert "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c" in script
    assert "'/@openai/codex/'" in script
    assert "'/codex-path/'" in script
    assert 'source_whiteout_path": "/home/ibex"' in script
    assert "rm -rf /home/ibex /home/ibex_base_commit.txt" in dockerfile
    assert 'org.verigym.runtime.role="hwe-ibex-command"' in dockerfile
    assert 'org.verigym.ibex.toolchain.profile="${IBEX_TOOLCHAIN_PROFILE}"' in dockerfile
    assert "ibex-verilator-system-container-native-v1" in script
    assert "iverilog|verilator" in script
    assert 'org.verigym.codex.present="absent"' in dockerfile
    assert 'CMD ["/usr/bin/tail", "-f", "/dev/null"]' in dockerfile
