from __future__ import annotations

import importlib.util
import json
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
    assert "data.dataloader_num_workers=0" in online_stage["argv"]
    assert "ray_init.num_cpus=16" in online_stage["argv"]
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
    assert "broker.wait(timeout=15)" in source
    assert '"--pids-limit",\n        "8192"' in source
    assert '"nproc=8192:8192"' in source


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
