from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from verigym.hwe.image_lock import build_hwe_command_image_lock
from verigym.plugin_api import ExternalAgentBridge

from verigym_openhands.hwe_agent import _validated_hwe_runtime_bridge
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


def test_openhands_ibex_runtime_uses_repository_specific_role_and_verifier_label() -> None:
    values = _lock().model_dump(mode="json", exclude={"lock_hash"})
    values["supported_execution_backends"] = tuple(values["supported_execution_backends"])
    values.update(
        {
            "task_id": "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-54",
            "source_whiteout_path": "/home/ibex",
            "toolchain_profile_id": "ibex-iverilog-container-native-v1",
            "allowlisted_artifacts": [
                {"path": "/usr/bin/make", "sha256": "7" * 64, "role": "build_tool"},
                {"path": "/usr/bin/iverilog", "sha256": "8" * 64, "role": "simulator"},
            ],
        }
    )
    lock = build_hwe_command_image_lock(**values)

    config = build_hwe_command_runtime_config(
        lock,
        runtime_user="10001:10001",
        execution_backend="episode_container_exec_v1",
    )

    assert config.command_image is not None
    labels = config.command_image.required_image_labels
    assert labels["org.verigym.runtime.role"] == "hwe-ibex-command"
    assert labels["org.verigym.ibex.verifier_base_image_id"] == lock.verifier_base_image_id
    assert "org.verigym.cva6.verifier_base_image_id" not in labels


def _bridge(
    *, process: str, command: str, isolation: str = "docker_standard"
) -> ExternalAgentBridge:
    return cast(
        ExternalAgentBridge,
        SimpleNamespace(
            execution_backend=process,
            command_execution_backend=command,
            isolation_level=isolation,
        ),
    )


def test_openhands_start_gate_accepts_only_explicit_isolated_backends() -> None:
    command = _bridge(
        process="runtime_external_process_unavailable",
        command="episode_container_exec_v1",
    )
    outer = _bridge(
        process="docker_outer_runtime_delegated",
        command="ephemeral_container_v1",
    )

    assert _validated_hwe_runtime_bridge(command) is command
    assert _validated_hwe_runtime_bridge(outer) is outer
    for rejected in (
        _bridge(
            process="runtime_external_process_unavailable",
            command="runtime_external_command_unavailable",
        ),
        _bridge(
            process="runtime_external_process_unavailable",
            command="ephemeral_container_v1",
        ),
        _bridge(
            process="runtime_external_process_unavailable",
            command="episode_container_exec_v1",
            isolation="trusted_local",
        ),
    ):
        with pytest.raises(ValueError, match="Docker|isolated"):
            _validated_hwe_runtime_bridge(rejected)
