from __future__ import annotations

from pathlib import Path

from verigym.plugin_api import SuiteSourceConfig

from verigym_rtllm import RTLLMSuite
from verigym_rtllm.adapter import PINNED_COMMIT


def test_external_source_is_required() -> None:
    # Unit tests use the caller-provided source path; no benchmark is packaged by the adapter.
    assert RTLLMSuite().validate_source().valid is False


def test_descriptor_exposes_platform_modes() -> None:
    suite = RTLLMSuite()
    assert "external_source" in suite.descriptor.capabilities
    assert "chat" in suite.descriptor.capabilities
    assert "agent" in suite.descriptor.capabilities
    assert len(PINNED_COMMIT) == 40


def test_variant_is_strict(tmp_path: Path) -> None:
    config = SuiteSourceConfig(source_root=tmp_path, variant="counter_12")
    configured = RTLLMSuite().with_source(config)
    assert configured.validate_source().valid is False
