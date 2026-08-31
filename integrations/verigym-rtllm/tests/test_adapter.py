from __future__ import annotations

from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError, SuiteSourceConfig

from verigym_rtllm import RTLLMSuite
from verigym_rtllm.adapter import PINNED_COMMIT, _is_icarus12_version


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
    for variant in (
        "counter_12",
        "up_down_counter",
        "up_down_counter_iverilog_training",
        "counter_12_agent_eval_v1",
        "up_down_counter_agent_eval_v1",
        "counter_12_agent_eval_functional_v2",
        "up_down_counter_agent_eval_functional_v2",
    ):
        configured = RTLLMSuite().with_source(
            SuiteSourceConfig(source_root=tmp_path, variant=variant)
        )
        assert configured.validate_source().valid is False


def test_icarus_training_variant_maps_to_upstream_task(tmp_path: Path) -> None:
    configured = RTLLMSuite().with_source(
        SuiteSourceConfig(source_root=tmp_path, variant="up_down_counter_iverilog_training")
    )

    assert configured._base_variant() == "up_down_counter"


def test_agent_eval_variants_map_to_distinct_upstream_tasks(tmp_path: Path) -> None:
    counter = RTLLMSuite().with_source(
        SuiteSourceConfig(source_root=tmp_path, variant="counter_12_agent_eval_v1")
    )
    up_down = RTLLMSuite().with_source(
        SuiteSourceConfig(source_root=tmp_path, variant="up_down_counter_agent_eval_v1")
    )

    assert counter._base_variant() == "counter_12"
    assert up_down._base_variant() == "up_down_counter"

    counter_v2 = RTLLMSuite().with_source(
        SuiteSourceConfig(source_root=tmp_path, variant="counter_12_agent_eval_functional_v2")
    )
    up_down_v2 = RTLLMSuite().with_source(
        SuiteSourceConfig(source_root=tmp_path, variant="up_down_counter_agent_eval_functional_v2")
    )
    assert counter_v2._base_variant() == "counter_12"
    assert up_down_v2._base_variant() == "up_down_counter"


def test_variant_is_strict(tmp_path: Path) -> None:
    config = SuiteSourceConfig(source_root=tmp_path, variant="unsupported")
    with pytest.raises(ConfigurationError, match="supports variants"):
        RTLLMSuite().with_source(config)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("Icarus Verilog version 12.0", True),
        ("Icarus Verilog runtime version 12.1", True),
        ("12.0", True),
        ("Icarus Verilog version 13.0", False),
        (None, False),
    ],
)
def test_agent_eval_icarus12_version_gate(version: str | None, expected: bool) -> None:
    assert _is_icarus12_version(version) is expected
