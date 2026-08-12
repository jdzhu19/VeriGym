from __future__ import annotations

import importlib.util
import json
import socket
from pathlib import Path
from types import ModuleType

import pytest


def _script() -> ModuleType:
    path = Path("scripts/run_qwen35_online_container.py").resolve(strict=True)
    spec = importlib.util.spec_from_file_location("verigym_online_container_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multi_gpu_request_preserves_device_list_for_docker_csv_parser() -> None:
    module = _script()

    assert module._docker_gpu_request("0,1,2,3") == '"device=0,1,2,3"'


def test_online_campaign_redirects_hydra_outputs_to_campaign_workspace() -> None:
    path = Path("configs/training/qwen35_rllm_verl_online_smoke_v1.json")
    campaign = json.loads(path.read_text(encoding="utf-8"))
    online_stage = next(stage for stage in campaign["stages"] if stage["stage_id"] == "online-grpo")

    assert "hydra.run.dir=${VERIGYM_CAMPAIGN_WORKSPACE}/hydra" in online_stage["argv"]
    assert "hydra.output_subdir=null" in online_stage["argv"]
    assert "hydra.job.chdir=False" in online_stage["argv"]
    assert "actor_rollout_ref.actor.ppo_mini_batch_size=2" in online_stage["argv"]
    assert (
        "++actor_rollout_ref.model.override_config.attn_implementation=sdpa" in online_stage["argv"]
    )
    assert "rllm.sdk.proxy.admin_token=EMPTY" in online_stage["argv"]
    assert "actor_rollout_ref.rollout.max_num_seqs=32" in online_stage["argv"]
    assert "actor_rollout_ref.rollout.load_format=safetensors" in online_stage["argv"]
    assert "actor_rollout_ref.rollout.layered_summon=True" in online_stage["argv"]
    assert "actor_rollout_ref.rollout.free_cache_engine=True" in online_stage["argv"]
    assert "++actor_rollout_ref.actor.fsdp_config.offload_policy=False" in online_stage["argv"]
    assert (
        "actor_rollout_ref.rollout.checkpoint_engine.update_weights_bucket_megabytes=4096"
        in online_stage["argv"]
    )
    assert (
        "++actor_rollout_ref.rollout.engine_kwargs.vllm.worker_extension_cls="
        "verigym_training_reference.qwen35_vllm_worker.VeriGymQwen35WorkerExtension"
        in online_stage["argv"]
    )
    assert "data.dataloader_num_workers=0" in online_stage["argv"]
    assert "+ray_init.num_cpus=16" in online_stage["argv"]
    assert not any(argument.startswith("ray_kwargs.ray_init.") for argument in online_stage["argv"])
    assert "reward.num_workers=1" in online_stage["argv"]
    assert (
        "actor_rollout_ref.model.external_lib=verigym_training_reference.qwen35_verl_compat"
        in online_stage["argv"]
    )
    assert not any("gdn_prefill_backend" in value for value in online_stage["argv"])


def test_online_container_keeps_cupy_cache_in_campaign_workspace() -> None:
    source = Path("scripts/run_qwen35_online_container.py").read_text(encoding="utf-8")

    assert '"CUPY_CACHE_DIR": str(_container_workspace_path(container_cache / "cupy"' in source
    assert "VeriGym trainer:{_CONTAINER_WORKSPACE}" in source
    assert '"HOME":' not in source
    assert '"OMP_NUM_THREADS": "1"' in source
    assert '"TMPDIR": str(process_tmp)' in source
    assert '"XDG_CACHE_HOME": str(container_cache / "host-xdg")' in source
    assert '"HF_HOME": str(workspace / "host-hf-home")' in source
    assert "broker.wait(timeout=15)" in source
    assert "broker.wait(timeout=3)" in source
    assert '"--pids-limit",\n        "8192"' in source
    assert '"nproc=8192:8192"' in source

    trainer_source = Path("scripts/train_qwen35_rllm_verl_online.py").read_text(encoding="utf-8")
    assert "RLLM_VERL_GRPO_GROUP_COMPATIBILITY_ACTIVE" in trainer_source
    assert '"effective_policy_update_verified": True' in trainer_source
    assert 'update_stats["changed_tensor_count"] <= 0' in trainer_source


def test_repository_mode_preserves_legacy_rtl_report_name() -> None:
    source = Path("scripts/run_qwen35_online_container.py").read_text(encoding="utf-8")

    assert '"online-verifier-broker-report.json"' in source
    assert '"online-repository-broker-report.json"' in source


def test_repository_campaign_uses_multiturn_workflow_and_bounded_gpu_envelope() -> None:
    path = Path("configs/training/qwen35_repository_rllm_verl_online_smoke_v1.json")
    campaign = json.loads(path.read_text(encoding="utf-8"))
    stage = next(
        item for item in campaign["stages"] if item["stage_id"] == "online-repository-grpo"
    )

    assert ["--workflow", "repository"] == stage["argv"][
        stage["argv"].index("--workflow") : stage["argv"].index("--workflow") + 2
    ]
    assert "data.max_response_length=16384" in stage["argv"]
    assert "++actor_rollout_ref.rollout.max_model_len=32768" in stage["argv"]
    assert "actor_rollout_ref.rollout.free_cache_engine=False" in stage["argv"]
    assert "++actor_rollout_ref.rollout.enable_sleep_mode=False" in stage["argv"]
    assert "actor_rollout_ref.rollout.gpu_memory_utilization=0.5" in stage["argv"]
    assert (
        "actor_rollout_ref.rollout.checkpoint_engine.update_weights_bucket_megabytes=256"
        in stage["argv"]
    )
    assert "rllm.workflow.retry_limit=1" in stage["argv"]
    assert "online-repository-broker-report.json" in stage["expected_outputs"]
    assert stage["gpu_ids"] == [0, 1, 2, 3]


def test_online_trainer_accepts_hash_bound_native_runtime_without_weakening_container() -> None:
    source = Path("scripts/train_qwen35_rllm_verl_online.py").read_text(encoding="utf-8")

    assert "VERIGYM_TRAINING_RUNTIME_MANIFEST" in source
    assert "validate_runtime_manifest" in source
    assert "cannot be both native and containerized" in source
    assert '"training_runtime_hash"' in source
    assert '"source_root_loaded_by_training_process": False' in source


def test_online_container_uses_short_workspace_alias_for_ray_sockets(tmp_path: Path) -> None:
    module = _script()
    artifact = tmp_path / "ray" / "session"

    assert module._container_workspace_path(artifact, tmp_path) == Path(
        "/verigym-campaign/ray/session"
    )
    assert module._containerize_argument(f"trainer.dir={tmp_path}/checkpoints", tmp_path) == (
        "trainer.dir=/verigym-campaign/checkpoints"
    )
    with pytest.raises(RuntimeError, match="outside the campaign workspace"):
        module._container_workspace_path(tmp_path.parent / "outside", tmp_path)


def test_online_container_removes_only_ephemeral_special_entries(tmp_path: Path) -> None:
    module = _script()
    process_tmp = tmp_path / "process-tmp"
    ray_tmp = tmp_path / "ray"
    process_tmp.mkdir()
    ray_tmp.mkdir()
    diagnostic = ray_tmp / "raylet.out"
    diagnostic.write_text("keep", encoding="utf-8")
    (ray_tmp / "session_latest").symlink_to("session_fixture")
    endpoint = process_tmp / "worker.sock"
    worker_socket = socket.socket(socket.AF_UNIX)
    worker_socket.bind(str(endpoint))
    worker_socket.close()

    removed = module._remove_ephemeral_special_entries([process_tmp, ray_tmp])

    assert removed == 2
    assert diagnostic.read_text(encoding="utf-8") == "keep"
    assert not endpoint.exists()
    assert not (ray_tmp / "session_latest").exists()
