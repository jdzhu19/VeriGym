from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError, SuiteSourceConfig, content_hash
from verigym.schemas.suite import SuiteSourceSnapshot

from verigym_rtllm import RTLLMSuite
from verigym_rtllm.adapter import HARDER_VARIANT, PINNED_COMMIT, _is_icarus12_version
from verigym_rtllm.known_bad import known_bad_source
from verigym_rtllm.manifest import (
    FROZEN_DATASET_FILES_HASH,
    FROZEN_FILE_COUNT,
    FROZEN_TASK_COUNT,
    FROZEN_TASK_TREES,
    FROZEN_TASK_TREES_HASH,
    HARDER_TASK_NAMES,
    TASK_MANIFESTS,
)


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


def test_harder_variant_is_explicit(tmp_path: Path) -> None:
    configured = RTLLMSuite().with_source(
        SuiteSourceConfig(source_root=tmp_path, variant=HARDER_VARIANT)
    )
    assert configured.validate_source().valid is False


@pytest.mark.external_benchmark
@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE"),
    reason="set VERIGYM_RTLLM_SOURCE to check historical task identities",
)
@pytest.mark.parametrize(
    ("variant", "expected_task_hash"),
    [
        (
            "counter_12_agent_eval_functional_v2",
            "23efb4a898070f8489c459d292374df0aebf9cbf5a3a05b60a704e7c26fe3715",
        ),
        (
            "up_down_counter_agent_eval_functional_v2",
            "f7ed592251502b77b55c3055dba1e1cc8bba987faec75a095233e156853e01c4",
        ),
    ],
)
def test_historical_functional_v2_task_identity_is_unchanged(
    variant: str, expected_task_hash: str
) -> None:
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(
            source_root=Path(os.environ["VERIGYM_RTLLM_SOURCE"]),
            variant=variant,
        )
    )
    task = suite.load_task(next(iter(suite.discover())))

    assert content_hash(task) == expected_task_hash


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


def test_frozen_manifest_covers_exactly_50_task_trees_and_four_harder_tasks() -> None:
    assert len(FROZEN_TASK_TREES) == FROZEN_TASK_COUNT == 50
    assert sum(tree.file_count for tree in FROZEN_TASK_TREES.values()) == FROZEN_FILE_COUNT == 207
    assert len(FROZEN_TASK_TREES_HASH) == 64
    assert len(FROZEN_DATASET_FILES_HASH) == 64
    assert HARDER_TASK_NAMES == ("radix2_div", "multi_pipe_8bit", "LIFObuffer", "asyn_fifo")
    for name in HARDER_TASK_NAMES:
        manifest = TASK_MANIFESTS[name]
        assert manifest.root in FROZEN_TASK_TREES
        assert manifest.candidate_top == manifest.synthesis_top


def test_harder_hidden_assets_and_candidate_paths_are_metadata_driven(tmp_path: Path) -> None:
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(source_root=tmp_path, variant=HARDER_VARIANT)
    )
    for name in HARDER_TASK_NAMES:
        manifest = TASK_MANIFESTS[name]
        assert suite._candidate_path(manifest) == f"repository/rtl/{name}.v"
        assets = suite._hidden_asset_declarations(manifest)
        assert [asset.mount_path for asset in assets] == [
            "verifier/testbench.v",
            *manifest.auxiliary_files,
        ]
        assert all(asset.content is None for asset in assets)
    assert TASK_MANIFESTS["asyn_fifo"].auxiliary_files == (
        "wfull.txt",
        "rempty.txt",
        "tdata.txt",
    )


def test_harder_tasks_require_typed_finish_before_hidden_verification() -> None:
    suite = RTLLMSuite()
    manifest = TASK_MANIFESTS["radix2_div"]
    metadata = suite._task_metadata(
        manifest,
        variant=HARDER_VARIANT,
        snapshot=SuiteSourceSnapshot(
            source_root="/datasets/RTLLM",
            dataset_root="/datasets/RTLLM",
            variant=HARDER_VARIANT,
            native_layout="rtllm-v2",
            strict_compatibility=True,
            configuration_fingerprint="a" * 64,
            dataset_content_hash="b" * 64,
        ),
        candidate_path="repository/rtl/radix2_div.v",
        public_contract={"id": "public-smoke"},
        upstream_prompt="upstream",
        derived_note="projection",
        agent_eval=True,
        functional_agent_eval=True,
        functional_v2=False,
        harder=True,
        icarus_training=False,
    )

    assert metadata["verification_requires_final_submission"] is True


@pytest.mark.parametrize("name", HARDER_TASK_NAMES)
@pytest.mark.parametrize(
    "category",
    ("stuck-zero", "reset-error", "protocol-latency-error", "functional-error"),
)
def test_harder_known_bad_controls_are_distinct_and_compile_shaped(
    name: str, category: str
) -> None:
    source = known_bad_source(name, category)
    assert f"module {name}" in source
    assert len(source) < 4_000
    assert len(content_hash(source)) == 64


def test_asyn_fifo_workspace_exposes_both_candidate_modules() -> None:
    suite = RTLLMSuite()
    source = (suite._harder_workspace_root / "rtl" / "asyn_fifo.v").read_text(encoding="utf-8")
    assert "module dual_port_RAM" in source
    assert "module asyn_fifo" in source
