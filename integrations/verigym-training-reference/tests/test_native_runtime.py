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
    replaced = replace_topology_overrides(
        [
            "data.train_batch_size=1",
            "actor_rollout_ref.rollout.n=4",
            "trainer.n_gpus_per_node=4",
            "++actor_rollout_ref.actor.fsdp_config.fsdp_size=4",
            "rllm.workflow.n_parallel_tasks=4",
        ],
        gpu_count,
    )
    assert len([value for value in replaced if "rollout.n=" in value]) == 1
    assert values == replaced[-4:]


def test_native_runtime_manifest_is_hash_bound_and_path_free() -> None:
    manifest = seal_runtime_manifest(_manifest())
    encoded = manifest.model_dump(mode="json")

    assert validate_runtime_manifest(encoded) == manifest
    assert encoded["raw_host_paths_included"] is False
    encoded["driver_version"] = "changed"
    with pytest.raises(ValueError, match="identity changed"):
        validate_runtime_manifest(encoded)


def test_native_runtime_rejects_inconsistent_topology() -> None:
    value = _manifest(6)
    value["rollout_group_size"] = 4
    with pytest.raises(ValueError, match="internally inconsistent"):
        seal_runtime_manifest(value)
