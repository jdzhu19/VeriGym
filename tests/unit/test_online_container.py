from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


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


def test_online_container_keeps_cupy_cache_in_campaign_workspace() -> None:
    source = Path("scripts/run_qwen35_online_container.py").read_text(encoding="utf-8")

    assert '"CUPY_CACHE_DIR": str(container_cache / "cupy")' in source
    assert "VeriGym trainer:{workspace}" in source
    assert '"HOME":' not in source
