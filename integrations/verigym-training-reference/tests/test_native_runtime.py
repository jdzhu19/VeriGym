from __future__ import annotations

import pytest

from verigym_training_reference.native_runtime import (
    GpuHealthSample,
    package_inventory_hash,
    parse_visible_devices,
    replace_topology_overrides,
    seal_runtime_manifest,
    select_gpu_devices,
    topology_overrides,
    validate_runtime_manifest,
)


def _samples(*, busy: set[int] | None = None) -> dict[int, list[GpuHealthSample]]:
    busy = busy or set()
    return {
        device: [
            GpuHealthSample(
                memory_used_mib=1024 if device in busy else 0,
                utilization_percent=50 if device in busy else 0,
                compute_process_count=1 if device in busy else 0,
            )
            for _ in range(3)
        ]
        for device in range(8)
    }


def _manifest(gpu_count: int = 4) -> dict[str, object]:
    return {
        "python_version": "3.11.13",
        "environment_name": "agent",
        "package_inventory_hash": package_inventory_hash({"torch": "2.10.0"}),
        "packages": {"torch": "2.10.0", "vllm": "0.17.0"},
        "verigym_commit": "a" * 40,
        "rllm_commit": "b" * 40,
        "verl_commit": "c" * 40,
        "transformers_commit": "d" * 40,
        "torch_cuda_version": "12.8",
        "driver_version": "525.105.17",
        "gpu_count": gpu_count,
        "gpu_names": ["NVIDIA A30"] * gpu_count,
        "fsdp_size": gpu_count,
        "rollout_group_size": gpu_count,
        "visible_device_count": gpu_count,
    }


def test_visible_device_parser_rejects_ambiguous_allocations() -> None:
    assert parse_visible_devices("1,0,2,3,5,4") == [1, 0, 2, 3, 5, 4]
    with pytest.raises(ValueError, match="numeric"):
        parse_visible_devices("GPU-a,GPU-b")
    with pytest.raises(ValueError, match="duplicate"):
        parse_visible_devices("0,0,1,2")


def test_topology_uses_only_clean_allocated_devices() -> None:
    allocated = [1, 0, 2, 3, 5, 4]
    samples = _samples(busy={0, 5})

    assert select_gpu_devices(allocated, samples, "4") == [1, 2, 3, 4]
    assert select_gpu_devices(list(range(8)), _samples(), "auto") == list(range(8))
    assert select_gpu_devices(list(range(6)), _samples(), "auto") == list(range(6))
    with pytest.raises(ValueError, match="fewer than 6"):
        select_gpu_devices(allocated, samples, "6")


@pytest.mark.parametrize("gpu_count", [4, 6, 8])
def test_topology_overrides_scale_grpo_group_with_world_size(gpu_count: int) -> None:
    values = topology_overrides(gpu_count)
    assert f"actor_rollout_ref.rollout.n={gpu_count}" in values
    assert f"trainer.n_gpus_per_node={gpu_count}" in values
    assert f"+ray_init.num_cpus={gpu_count * 4}" in values
    replaced = replace_topology_overrides(
        [
            "data.train_batch_size=1",
            "actor_rollout_ref.rollout.n=4",
            "trainer.n_gpus_per_node=4",
            "++actor_rollout_ref.actor.fsdp_config.fsdp_size=4",
            "rllm.workflow.n_parallel_tasks=4",
            "+ray_init.num_cpus=16",
        ],
        gpu_count,
    )
    assert len([value for value in replaced if "rollout.n=" in value]) == 1
    assert len([value for value in replaced if "ray_init.num_cpus=" in value]) == 1
    assert values == replaced[-5:]


def test_native_runtime_manifest_is_hash_bound_and_path_free() -> None:
    manifest = seal_runtime_manifest(_manifest())
    encoded = manifest.model_dump(mode="json")

    assert validate_runtime_manifest(encoded) == manifest
    assert encoded["raw_host_paths_included"] is False
    encoded["driver_version"] = "changed"
    with pytest.raises(ValueError, match="identity changed"):
        validate_runtime_manifest(encoded)


def test_native_runtime_binds_path_free_proot_identity() -> None:
    value = _manifest()
    value["compatibility_layer"] = {
        "kind": "proot_rootfs",
        "executable_sha256": "e" * 64,
        "rootfs_image_id": f"sha256:{'e' * 64}",
        "seccomp_acceleration": False,
        "host_kernel_release": "3.10.0-1160.el7.x86_64",
        "guest_libc_version": "2.41",
    }

    manifest = seal_runtime_manifest(value)

    assert manifest.compatibility_layer is not None
    assert manifest.compatibility_layer.kind == "proot_rootfs"
    assert "/" not in manifest.compatibility_layer.executable_sha256


def test_native_runtime_binds_path_free_glibc_loader_identities() -> None:
    value = _manifest()
    value["compatibility_layer"] = {
        "kind": "glibc_loader",
        "executable_sha256": "e" * 64,
        "rootfs_image_id": f"sha256:{'e' * 64}",
        "loader_sha256": "f" * 64,
        "patcher_sha256": "a" * 64,
        "host_kernel_release": "3.10.0-1160.el7.x86_64",
        "guest_libc_version": "2.41",
    }

    manifest = seal_runtime_manifest(value)

    assert manifest.compatibility_layer is not None
    assert manifest.compatibility_layer.kind == "glibc_loader"
    assert manifest.compatibility_layer.seccomp_acceleration is None


def test_native_runtime_binds_path_free_gpu_toolchain() -> None:
    value = _manifest()
    value["gpu_toolchain"] = {
        "nccl_library_sha256": "1" * 64,
        "nccl_source_commit": "2" * 40,
        "nccl_cuda_version": "12.4.131",
        "c_compiler_sha256": "3" * 64,
        "c_compiler_version": "gcc (GCC) 12.2.0",
    }

    manifest = seal_runtime_manifest(value)

    assert manifest.gpu_toolchain is not None
    assert manifest.gpu_toolchain.nccl_cuda_version == "12.4.131"
    assert "/" not in manifest.gpu_toolchain.c_compiler_version


def test_native_runtime_rejects_invalid_gpu_toolchain_identity() -> None:
    value = _manifest()
    value["gpu_toolchain"] = {
        "nccl_library_sha256": "not-a-hash",
        "nccl_source_commit": "2" * 40,
        "nccl_cuda_version": "12.4.131",
        "c_compiler_sha256": "3" * 64,
        "c_compiler_version": "gcc (GCC) 12.2.0",
    }

    with pytest.raises(ValueError, match="SHA-256"):
        seal_runtime_manifest(value)


def test_native_runtime_rejects_incomplete_glibc_loader_identity() -> None:
    value = _manifest()
    value["compatibility_layer"] = {
        "kind": "glibc_loader",
        "executable_sha256": "e" * 64,
        "rootfs_image_id": f"sha256:{'e' * 64}",
        "loader_sha256": "f" * 64,
        "host_kernel_release": "3.10.0-1160.el7.x86_64",
        "guest_libc_version": "2.41",
    }

    with pytest.raises(ValueError, match="incomplete"):
        seal_runtime_manifest(value)


def test_native_runtime_rejects_inconsistent_topology() -> None:
    value = _manifest(6)
    value["rollout_group_size"] = 4
    with pytest.raises(ValueError, match="internally inconsistent"):
        seal_runtime_manifest(value)
