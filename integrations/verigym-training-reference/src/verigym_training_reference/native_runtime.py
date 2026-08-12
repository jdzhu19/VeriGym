"""Frozen native-runtime and accelerator topology helpers for online training."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

SUPPORTED_GPU_COUNTS = (4, 6, 8)


@dataclass(frozen=True)
class GpuHealthSample:
    """One bounded health sample for an allocated physical GPU."""

    memory_used_mib: int
    utilization_percent: int
    compute_process_count: int

    @property
    def uncontended(self) -> bool:
        return (
            self.memory_used_mib <= 512
            and self.utilization_percent <= 5
            and self.compute_process_count == 0
        )


class NativeCompatibilityLayer(StrictModel):
    """Path-free identity of an optional userspace ABI compatibility layer."""

    kind: Literal["proot_rootfs", "glibc_loader"]
    executable_sha256: str
    rootfs_image_id: str
    seccomp_acceleration: Literal[False] | None = None
    loader_sha256: str | None = None
    patcher_sha256: str | None = None
    host_kernel_release: str = Field(min_length=1, max_length=128)
    guest_libc_version: str = Field(min_length=1, max_length=64)

    @field_validator("executable_sha256", "loader_sha256", "patcher_sha256")
    @classmethod
    def validate_executable_hash(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("compatibility executable identity must be a SHA-256 digest")
        return value

    @field_validator("rootfs_image_id")
    @classmethod
    def validate_rootfs_image_id(cls, value: str) -> str:
        digest = value.removeprefix("sha256:")
        if (
            not value.startswith("sha256:")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("compatibility rootfs identity must be a Docker SHA-256 image ID")
        return value

    @model_validator(mode="after")
    def validate_strategy_fields(self) -> NativeCompatibilityLayer:
        if self.kind == "proot_rootfs":
            if (
                self.seccomp_acceleration is not False
                or self.loader_sha256 is not None
                or self.patcher_sha256 is not None
            ):
                raise ValueError("PRoot compatibility fields are internally inconsistent")
        elif (
            self.seccomp_acceleration is not None
            or self.loader_sha256 is None
            or self.patcher_sha256 is None
        ):
            raise ValueError("glibc-loader compatibility fields are incomplete")
        return self


class NativeGpuToolchain(StrictModel):
    """Path-free identity of the qualified native GPU/JIT toolchain."""

    nccl_library_sha256: str
    nccl_source_commit: str
    nccl_cuda_version: str = Field(min_length=1, max_length=32)
    c_compiler_sha256: str
    c_compiler_version: str = Field(min_length=1, max_length=128)

    @field_validator("nccl_library_sha256", "c_compiler_sha256")
    @classmethod
    def validate_binary_hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("native GPU toolchain binary identity must be a SHA-256 digest")
        return value

    @field_validator("nccl_source_commit")
    @classmethod
    def validate_source_commit(cls, value: str) -> str:
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("NCCL source identity must be a full Git commit")
        return value


class NativeTrainingRuntimeManifest(StrictModel):
    """Portable identity of a Conda-hosted rLLM/veRL training process."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_native_training_runtime_v1"] = "verigym_native_training_runtime_v1"
    runtime_kind: Literal["conda"] = "conda"
    python_version: str
    environment_name: str
    package_inventory_hash: str
    packages: dict[str, str]
    verigym_commit: str
    rllm_commit: str
    verl_commit: str
    transformers_commit: str
    torch_cuda_version: str
    driver_version: str
    gpu_count: int
    gpu_names: list[str]
    tensor_parallel_size: int = 2
    fsdp_size: int
    rollout_group_size: int
    visible_device_count: int
    compatibility_layer: NativeCompatibilityLayer | None = None
    gpu_toolchain: NativeGpuToolchain | None = None
    source_root_loaded_by_training_process: Literal[False] = False
    docker_socket_loaded_by_training_process: Literal[False] = False
    hidden_assets_loaded_by_training_process: Literal[False] = False
    reference_solution_loaded_by_training_process: Literal[False] = False
    credential_values_included: Literal[False] = False
    raw_host_paths_included: Literal[False] = False
    manifest_hash: str = Field(default="", min_length=0, max_length=64)

    @field_validator(
        "package_inventory_hash",
        "verigym_commit",
        "rllm_commit",
        "verl_commit",
        "transformers_commit",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        if len(value) != 40 and len(value) != 64:
            raise ValueError("runtime identities must be full Git commits or SHA-256 digests")
        if any(character not in "0123456789abcdef" for character in value):
            raise ValueError("runtime identities must be lowercase hexadecimal")
        return value

    @model_validator(mode="after")
    def validate_topology(self) -> NativeTrainingRuntimeManifest:
        if self.gpu_count not in SUPPORTED_GPU_COUNTS:
            raise ValueError("native Qwen training supports exactly 4, 6, or 8 GPUs")
        if (
            self.visible_device_count != self.gpu_count
            or len(self.gpu_names) != self.gpu_count
            or self.fsdp_size != self.gpu_count
            or self.rollout_group_size != self.gpu_count
            or self.gpu_count % self.tensor_parallel_size != 0
        ):
            raise ValueError("native runtime topology is internally inconsistent")
        return self


def parse_visible_devices(value: str) -> list[int]:
    """Parse the numeric LSF CUDA allocation without accepting ambiguous aliases."""

    parts = value.split(",") if value else []
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError("CUDA_VISIBLE_DEVICES must be a comma-separated numeric LSF allocation")
    devices = [int(part) for part in parts]
    if len(devices) != len(set(devices)):
        raise ValueError("CUDA_VISIBLE_DEVICES contains duplicate devices")
    return devices


def select_gpu_devices(
    allocated: list[int],
    samples: dict[int, list[GpuHealthSample]],
    requested: Literal["auto", "4", "6", "8"],
) -> list[int]:
    """Select only repeatedly uncontended GPUs from the scheduler allocation."""

    if not allocated:
        raise ValueError("the scheduler allocation contains no GPUs")
    clean = [
        device
        for device in allocated
        if samples.get(device) and all(sample.uncontended for sample in samples[device])
    ]
    if requested == "auto":
        choices = [count for count in SUPPORTED_GPU_COUNTS if count <= len(clean)]
        if not choices:
            raise ValueError("fewer than four uncontended allocated GPUs are available")
        count = max(choices)
    else:
        count = int(requested)
        if count not in SUPPORTED_GPU_COUNTS:
            raise ValueError("requested GPU count must be auto, 4, 6, or 8")
        if len(clean) < count:
            raise ValueError(f"fewer than {count} uncontended allocated GPUs are available")
    return clean[:count]


def topology_overrides(gpu_count: int) -> list[str]:
    """Return the coupled veRL/rLLM overrides for one frozen topology."""

    if gpu_count not in SUPPORTED_GPU_COUNTS:
        raise ValueError("topology overrides require 4, 6, or 8 GPUs")
    return [
        f"++actor_rollout_ref.actor.fsdp_config.fsdp_size={gpu_count}",
        f"actor_rollout_ref.rollout.n={gpu_count}",
        f"rllm.workflow.n_parallel_tasks={gpu_count}",
        f"trainer.n_gpus_per_node={gpu_count}",
    ]


def replace_topology_overrides(arguments: list[str], gpu_count: int) -> list[str]:
    """Replace topology keys rather than relying on duplicate Hydra overrides."""

    prefixes = tuple(value.split("=", maxsplit=1)[0] + "=" for value in topology_overrides(4))
    return [value for value in arguments if not value.startswith(prefixes)] + topology_overrides(
        gpu_count
    )


def package_inventory_hash(packages: dict[str, str]) -> str:
    encoded = json.dumps(packages, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def seal_runtime_manifest(value: dict[str, Any]) -> NativeTrainingRuntimeManifest:
    """Validate and hash a runtime manifest with no self-referential hash field."""

    candidate = dict(value)
    candidate.pop("manifest_hash", None)
    draft = NativeTrainingRuntimeManifest.model_validate({**candidate, "manifest_hash": ""})
    base = draft.model_dump(mode="json", exclude={"manifest_hash"})
    return NativeTrainingRuntimeManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )


def validate_runtime_manifest(value: dict[str, Any]) -> NativeTrainingRuntimeManifest:
    identity = dict(value)
    expected = identity.pop("manifest_hash", None)
    if not isinstance(expected, str) or expected != content_hash(identity):
        raise ValueError("native training runtime manifest identity changed")
    return NativeTrainingRuntimeManifest.model_validate(value)


__all__ = [
    "GpuHealthSample",
    "NativeCompatibilityLayer",
    "NativeGpuToolchain",
    "NativeTrainingRuntimeManifest",
    "SUPPORTED_GPU_COUNTS",
    "package_inventory_hash",
    "parse_visible_devices",
    "replace_topology_overrides",
    "seal_runtime_manifest",
    "select_gpu_devices",
    "topology_overrides",
    "validate_runtime_manifest",
]
