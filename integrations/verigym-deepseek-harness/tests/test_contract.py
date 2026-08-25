from __future__ import annotations

from pathlib import Path

import pytest
import verigym_deepseek_harness
from verigym_deepseek_harness.agent import (
    DeepSeekHarnessHweAgentAdapter,
    DeepSeekHarnessHweAgentV3Adapter,
)
from verigym_deepseek_harness.config import (
    CONTROLLER_IMAGE_ID,
    CONTROLLER_NETWORK,
    DEEPSEEK_HARNESS_VERSION,
)

from verigym.hwe.deepseek_harness import DEEPSEEK_HARNESS_TOOL_NAMES


def test_frozen_package_and_controller_contract() -> None:
    assert verigym_deepseek_harness.__version__ == "0.2.0"
    assert DEEPSEEK_HARNESS_VERSION == "0.1.1-rc.2"
    assert CONTROLLER_IMAGE_ID == (
        "sha256:daa74c183f7d8c1ba55ed79c76e912f50be8782ca9d2da640645f906dce474b8"
    )
    assert CONTROLLER_NETWORK == "verigym-hwe-net"
    assert DeepSeekHarnessHweAgentAdapter.requires_model is False
    assert DeepSeekHarnessHweAgentAdapter.descriptor.version == "0.1.0"
    assert DeepSeekHarnessHweAgentV3Adapter.descriptor.version == "0.2.0"
    assert DeepSeekHarnessHweAgentV3Adapter.format_repair_budget == 1
    assert DEEPSEEK_HARNESS_TOOL_NAMES == (
        "apply_patch",
        "finish",
        "inspect_diff",
        "list_files",
        "read_file",
        "shell",
    )


def test_runtime_assets_disable_compaction_and_keep_controller_interactive() -> None:
    package = Path(verigym_deepseek_harness.__file__).resolve().parent
    cordis = (package / "runtime/cordis.yml").read_text(encoding="utf-8")
    helper = (package / "helper.py").read_text(encoding="utf-8")
    tools = (package / "runtime/hwe-tools.mjs").read_text(encoding="utf-8")
    assert "compression: none" in cordis
    assert "maxRetries: 0" in cordis
    assert "maxParallelToolCalls: 1" in cordis
    assert '"--interactive"' in helper
    assert '"--network",\n        _NETWORK' in helper
    assert tools.count("ctx.tools.register") == 1
    assert "temperature: 0" in tools
    assert "reasoningEffort: 'off'" in tools


def test_helper_rejects_symlink_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = Path(
        "/data/jzhu484/Agent/datasets/deepseek-harness/"
        "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/python/sdk/src"
    )
    if not source_root.is_dir():
        pytest.skip("pinned DeepSeek Harness SDK source is not installed")
    monkeypatch.syspath_prepend(str(source_root))
    from verigym_deepseek_harness.helper import _directory

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe"):
        _directory(str(link), "test")
