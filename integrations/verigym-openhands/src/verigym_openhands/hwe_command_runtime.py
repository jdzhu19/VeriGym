"""Codex-free Docker command-image configuration for successor HWE campaigns."""

from __future__ import annotations

from typing import Literal

from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID
from verigym.hwe.image_lock import HweCommandImageLock
from verigym.schemas.runtime import DockerCommandImageRuntimeConfig, DockerRuntimeConfig

CommandExecutionBackend = Literal[
    "ephemeral_container_v1",
    "episode_container_exec_v1",
]


def build_hwe_command_runtime_config(
    lock: HweCommandImageLock,
    *,
    runtime_user: str,
    execution_backend: CommandExecutionBackend,
) -> DockerRuntimeConfig:
    """Bind a successor OpenHands runtime to a scanned, task-specific command image."""

    if lock.source_whiteout_path == "/home/cva6":
        runtime_role = "hwe-cva6-command"
        verifier_label = "org.verigym.cva6.verifier_base_image_id"
    elif lock.source_whiteout_path == "/home/ibex":
        runtime_role = "hwe-ibex-command"
        verifier_label = "org.verigym.ibex.verifier_base_image_id"
    else:  # pragma: no cover - the lock schema rejects other values
        raise ValueError("unsupported HWE command-image source whiteout profile")
    labels = {
        "org.verigym.runtime.role": runtime_role,
        "org.verigym.collection.profile": lock.collection_profile_id,
        "org.verigym.tool.contract": lock.tool_contract_id,
        "org.verigym.command.protocol": lock.command_protocol,
        "org.verigym.command.rg.version": lock.rg_version,
        "org.verigym.command.rg.sha256": lock.rg_sha256,
        "org.verigym.command.rg.release_archive.sha256": lock.rg_release_archive_sha256,
        "org.verigym.hwe.task_id": lock.task_id,
        verifier_label: lock.verifier_base_image_id,
        "org.verigym.codex.present": "absent",
        "org.verigym.provider_credentials": "absent",
        "org.verigym.hidden_assets": "absent",
        "org.verigym.reference_patch": "absent",
        "org.verigym.verifier_payload": "absent",
    }
    return DockerRuntimeConfig(
        image=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        expected_image_id=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        pull_policy="never",
        network_mode="none",
        run_as_user=runtime_user,
        memory_bytes=16 * 1024**3,
        cpus=4,
        pids_limit=4096,
        max_command_time_s=900,
        command_image=DockerCommandImageRuntimeConfig(
            image=lock.derived_command_image_id,
            expected_image_id=lock.derived_command_image_id,
            expected_rg_version=lock.rg_version,
            expected_rg_sha256=lock.rg_sha256,
            protocol=lock.command_protocol,
            execution_backend=execution_backend,
            required_image_labels=labels,
            run_as_user=runtime_user,
            memory_bytes=16 * 1024**3,
            cpus=4,
            pids_limit=4096,
            max_command_time_s=3600,
            max_output_bytes=32 * 1024 * 1024,
        ),
    )


__all__ = ["CommandExecutionBackend", "build_hwe_command_runtime_config"]
