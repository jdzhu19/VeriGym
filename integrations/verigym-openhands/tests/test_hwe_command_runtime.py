from __future__ import annotations

from verigym.hwe.image_lock import build_hwe_command_image_lock

from verigym_openhands.hwe_command_runtime import build_hwe_command_runtime_config


def _lock():
    return build_hwe_command_image_lock(
        task_id="openhwgroup/cva6:pr-2330",
        task_hash="1" * 64,
        source_hash="2" * 64,
        verifier_base_image_id="sha256:" + "3" * 64,
        derived_command_image_id="sha256:" + "4" * 64,
        rg_sha256="5" * 64,
        rg_release_archive_sha256="6" * 64,
        toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
        allowlisted_artifacts=[
            {"path": "/usr/bin/make", "sha256": "7" * 64, "role": "build_tool"},
            {
                "path": "/tools/verilator/bin/verilator",
                "sha256": "8" * 64,
                "role": "simulator",
            },
        ],
        security_scan_id="9" * 64,
    )


def test_openhands_successor_runtime_uses_command_role_without_external_codex_agent() -> None:
    lock = _lock()
    config = build_hwe_command_runtime_config(
        lock,
        runtime_user="10001:10001",
        execution_backend="episode_container_exec_v1",
    )

    assert config.external_agent is None
    assert config.command_image is not None
    assert config.command_image.image == lock.derived_command_image_id
    assert config.command_image.execution_backend == "episode_container_exec_v1"
    assert config.command_image.expected_rg_sha256 == lock.rg_sha256
    assert not hasattr(config.command_image, "process_argv")
    assert config.command_image.required_image_labels["org.verigym.codex.present"] == "absent"
