from __future__ import annotations

from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError, SuiteSourceConfig

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


def test_counter_family_variants_are_explicit(tmp_path: Path) -> None:
    for variant in ("counter_12", "up_down_counter"):
        configured = RTLLMSuite().with_source(
            SuiteSourceConfig(source_root=tmp_path, variant=variant)
        )
        assert configured.validate_source().valid is False


def test_variant_is_strict(tmp_path: Path) -> None:
    config = SuiteSourceConfig(source_root=tmp_path, variant="unsupported")
    with pytest.raises(ConfigurationError, match="supports variants"):
        RTLLMSuite().with_source(config)
