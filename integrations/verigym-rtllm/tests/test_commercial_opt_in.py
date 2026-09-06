from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym.core.orchestrator import VeriGym
from verigym.models.static import StaticModelClient
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

from verigym_rtllm import RTLLMSuite


@pytest.mark.commercial
@pytest.mark.skipif(
    os.environ.get("VERIGYM_RUN_SYNOPSYS_TESTS") != "1",
    reason="set VERIGYM_RUN_SYNOPSYS_TESTS=1 for licensed site execution",
)
@pytest.mark.parametrize("variant", ["counter_12", "up_down_counter"])
def test_pinned_reference_through_vcs_and_optional_dc(tmp_path: Path, variant: str) -> None:
    source_value = os.environ.get("VERIGYM_RTLLM_SOURCE")
    if source_value is None:
        pytest.fail("VERIGYM_RTLLM_SOURCE is required")
    source = Path(source_value)
    source_config = SuiteSourceConfig(source_root=source, variant=variant)
    suite = RTLLMSuite().with_source(source_config)
    assert suite.validate_source().valid
    task = suite.load_task(next(iter(suite.discover())))
    reference = suite.reference_solution(task)
    assert reference is not None

    registries = build_registries()
    registries.models.register(
        StaticModelClient(
            name="rtllm-commercial-reference",
            responses=[reference.files[f"rtl/{variant}.v"]],
        )
    )
    suffix = variant.upper()
    vcs_profile_path = os.environ.get(f"VERIGYM_VCS_MCP_PROFILE_{suffix}")
    if vcs_profile_path is None:
        pytest.fail(f"VERIGYM_VCS_MCP_PROFILE_{suffix} is required")
    verifier_profile = load_verifier_profile(vcs_profile_path)
    profile_path = os.environ.get(f"VERIGYM_DC_MCP_PROFILE_{suffix}")
    profile_id: str | None = None
    if profile_path is not None:
        profile_id = registries.profiles.load_file(profile_path).id
    result = VeriGym(registries).run(
        RunConfig(
            task_id=f"rtllm/{variant}",
            suite_source=source_config,
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model="rtllm-commercial-reference",
            runtime="local",
            toolchain_profile=profile_id,
            verifier_profile_id=verifier_profile.id,
            verifier_profile=verifier_profile,
            output=tmp_path,
        )
    )
    assert result.scorecard.resolved
    vcs = next(
        item for item in result.scorecard.verifier_results if item.node_id == "vcs_regression"
    )
    assert vcs.status.value == "passed"
    assert vcs.plugin == "synopsys.vcs.mcp"
    assert result.manifest.resolved_verifier_profile_hash is not None
    if profile_id is not None:
        assert result.scorecard.quality.ppa is not None
        assert result.scorecard.quality.ppa.eligible
