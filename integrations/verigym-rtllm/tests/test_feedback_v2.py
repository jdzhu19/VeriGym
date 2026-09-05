from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError, SuiteSourceConfig, content_hash

from verigym_rtllm.adapter import (
    FEEDBACK_V2_PUBLIC_SMOKE_SHA256,
    FEEDBACK_V2_TASK_IDENTITIES_SHA256,
    FEEDBACK_V2_VARIANT,
    FIFO_BEHAVIOR_CHECKER_ENVIRONMENT,
    FIFO_BEHAVIOR_CHECKER_PROJECTION,
    FIFO_BEHAVIOR_CHECKER_SHA256,
    FULL_FUNCTIONAL_TASK_IDENTITIES_SHA256,
    PPA47_TASK_IDENTITIES_SHA256,
    PPA47_VARIANT,
    RTLLMSuite,
)
from verigym_rtllm.manifest import ALL_TASK_NAMES, TASK_MANIFESTS
from verigym_rtllm.ppa import (
    PPA47_BINDINGS_SHA256,
    PPA47_EXCLUSION_REASONS,
    PPA47_TASK_NAMES,
    PPA_TASK_BINDINGS,
)
from verigym_rtllm.qualification import (
    FEEDBACK_V2_CATALOG_SHA256,
    FEEDBACK_V2_MUTANT_SOURCES_SHA256,
    MUTATION_CONTROLS,
    MUTATION_COUNT_PER_TASK,
    SPECIFICATION_OBLIGATIONS,
    feedback_v2_mutant_source,
    feedback_v2_mutant_sources_payload,
)


def test_feedback_v2_catalog_covers_fifty_tasks_and_twelve_unique_mutants() -> None:
    assert set(SPECIFICATION_OBLIGATIONS) == set(ALL_TASK_NAMES)
    assert set(MUTATION_CONTROLS) == set(ALL_TASK_NAMES)
    assert len(FEEDBACK_V2_CATALOG_SHA256) == 64
    assert len(FEEDBACK_V2_MUTANT_SOURCES_SHA256) == 64
    source_payload = feedback_v2_mutant_sources_payload()
    assert content_hash(source_payload) == FEEDBACK_V2_MUTANT_SOURCES_SHA256
    assert sum(len(sources) for sources in source_payload["tasks"].values()) == 600
    for name in ALL_TASK_NAMES:
        obligations = SPECIFICATION_OBLIGATIONS[name]
        controls = MUTATION_CONTROLS[name]
        assert obligations
        assert len(controls) == MUTATION_COUNT_PER_TASK
        assert sum(control.task_specific for control in controls) == 8
        sources = {
            control.mutation_id: feedback_v2_mutant_source(name, control.mutation_id)
            for control in controls
        }
        assert len(set(sources.values())) == MUTATION_COUNT_PER_TASK
        assert all("module" in source and "endmodule" in source for source in sources.values())
        for control in controls:
            if control.task_specific:
                source = sources[control.mutation_id]
                assert "verigym_control" in source or "64'h" in source
                assert "#1000000" not in source


def test_ppa47_binding_catalog_is_complete_and_has_stable_exclusions() -> None:
    assert set(PPA_TASK_BINDINGS) == set(ALL_TASK_NAMES)
    assert len(PPA47_TASK_NAMES) == 47
    assert PPA47_EXCLUSION_REASONS == {
        "float_multi": "reference_non_synthesizable_event_control",
        "synchronizer": "reference_multiple_edge_drivers",
        "clkgenerator": "reference_zero_cell_delay_model",
    }
    assert len(PPA47_BINDINGS_SHA256) == 64
    modes = [PPA_TASK_BINDINGS[name].clock_mode for name in PPA47_TASK_NAMES]
    assert modes.count("single_clock") == 32
    assert modes.count("asynchronous_dual_clock") == 1
    assert modes.count("combinational_virtual_clock") == 14
    fifo = PPA_TASK_BINDINGS["asyn_fifo"]
    assert fifo.clocks == (("wclk", 10.0), ("rclk", 14.0))
    assert fifo.sdc is not None and "set_clock_groups -asynchronous" in fifo.sdc
    sequence = PPA_TASK_BINDINGS["sequence_detector"]
    assert sequence.reference_normalization == ("dc_ver134_combinational_blocking_assignment_v1")
    assert sequence.reference_normalized_sha256 == (
        "da9720d113e7b248230569f6e707273e99d16645645b55e83d2276f2a8554ffd"
    )
    rom = PPA_TASK_BINDINGS["ROM"]
    assert rom.reference_normalization == "dc_ver281_fixed_rom_case_v1"
    assert rom.reference_normalized_sha256 == (
        "484b9dcd649a2aac9c8a5801fc3c6f52af066b07c3aab3e5767f3b914a817d02"
    )
    for name in PPA47_TASK_NAMES:
        binding = PPA_TASK_BINDINGS[name]
        assert binding.top == TASK_MANIFESTS[name].synthesis_top
        assert binding.source_path == f"rtl/{name}.v"
        assert binding.sdc
        assert binding.power_base_clock
        assert (binding.reference_normalization is None) == (
            binding.reference_normalized_sha256 is None
        )


def test_new_variants_are_explicit_without_changing_v1_constants(tmp_path: Path) -> None:
    for variant in (FEEDBACK_V2_VARIANT, PPA47_VARIANT):
        configured = RTLLMSuite().with_source(
            SuiteSourceConfig(source_root=tmp_path, variant=variant)
        )
        assert configured.validate_source().valid is False
    assert len(FULL_FUNCTIONAL_TASK_IDENTITIES_SHA256) == 64
    assert set(FEEDBACK_V2_PUBLIC_SMOKE_SHA256) == set(ALL_TASK_NAMES)
    assert all(len(value) == 64 for value in FEEDBACK_V2_PUBLIC_SMOKE_SHA256.values())


@pytest.mark.external_benchmark
@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE"),
    reason="set VERIGYM_RTLLM_SOURCE to check feedback-v2 identities",
)
def test_feedback_v2_and_ppa47_task_identities_and_contracts_are_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(os.environ["VERIGYM_RTLLM_SOURCE"])
    checker = os.environ.get(FIFO_BEHAVIOR_CHECKER_ENVIRONMENT)
    if checker is not None:
        monkeypatch.setenv(FIFO_BEHAVIOR_CHECKER_ENVIRONMENT, checker)
    expected = {
        FEEDBACK_V2_VARIANT: (50, FEEDBACK_V2_TASK_IDENTITIES_SHA256, False),
        PPA47_VARIANT: (47, PPA47_TASK_IDENTITIES_SHA256, True),
    }
    for variant, (count, aggregate, ppa_enabled) in expected.items():
        suite = RTLLMSuite().with_source(SuiteSourceConfig(source_root=source, variant=variant))
        refs = list(suite.discover())
        assert len(refs) == count
        identities = {ref.native_id: content_hash(suite.load_task(ref)) for ref in refs}
        assert content_hash(identities) == aggregate
        for ref in refs:
            task = suite.load_task(ref)
            assert task.scoring.ppa_enabled is ppa_enabled
            assert task.metadata["diagnostic_only"] is True
            assert task.metadata["benchmark_score_claimed"] is False
            assert task.metadata["mutation_control_count"] == 12
            assert (
                task.metadata["public_vector_partition"] != task.metadata["hidden_vector_partition"]
            )
            if variant == PPA47_VARIANT and ref.native_id == "sequence_detector":
                reference = suite.reference_solution(task)
                assert reference is not None
                source = reference.files["repository/rtl/sequence_detector.v"]
                assert "next_state <= IDLE" not in source
                assert "next_state = IDLE" in source
            if variant == PPA47_VARIANT and ref.native_id == "ROM":
                reference = suite.reference_solution(task)
                assert reference is not None
                source = reference.files["repository/rtl/ROM.v"]
                assert "initial begin" not in source
                assert "case (addr)" in source


@pytest.mark.external_benchmark
@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE"),
    reason="set VERIGYM_RTLLM_SOURCE to check FIFO hidden isolation",
)
def test_feedback_v2_fifo_uses_one_external_behavior_checker_without_trace_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(os.environ["VERIGYM_RTLLM_SOURCE"])
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(source_root=source, variant=FEEDBACK_V2_VARIANT)
    )
    ref = next(ref for ref in suite.discover() if ref.native_id == "asyn_fifo")
    task = suite.load_task(ref)
    assert [asset.mount_path for asset in task.workspace.hidden_assets] == ["verifier/testbench.v"]
    request = task.verifier.nodes[0].request
    assert request["auxiliary_files"] == []
    assert suite._effective_manifest(TASK_MANIFESTS["asyn_fifo"]).testbench_projection == (
        FIFO_BEHAVIOR_CHECKER_PROJECTION
    )

    monkeypatch.delenv(FIFO_BEHAVIOR_CHECKER_ENVIRONMENT, raising=False)
    with pytest.raises(ConfigurationError, match=FIFO_BEHAVIOR_CHECKER_ENVIRONMENT):
        suite.resolve_assets(task)

    configured = os.environ.get("VERIGYM_RTLLM_TEST_FIFO_CHECKER")
    if configured is None:
        return
    monkeypatch.setenv(FIFO_BEHAVIOR_CHECKER_ENVIRONMENT, configured)
    assets = suite.resolve_assets(task)
    assert len(assets.hidden_assets) == 1
    assert assets.hidden_assets[0].content_hash == FIFO_BEHAVIOR_CHECKER_SHA256
    visible = Path(assets.visible_root)
    assert not any("verifier" in path.relative_to(visible).parts for path in visible.rglob("*"))
