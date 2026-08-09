from __future__ import annotations

import importlib.util
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
