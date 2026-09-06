from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym.core.orchestrator import VeriGym
from verigym.core.workspace import copy_tree_safely
from verigym.registry.collections import build_registries
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus

from verigym_rtllm import RTLLMSuite
from verigym_rtllm.adapter import _is_icarus12_version

pytestmark = [pytest.mark.external_benchmark, pytest.mark.docker_integration]


@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE")
    or not os.environ.get("VERIGYM_RTLLM_ICARUS12_IMAGE"),
    reason="set VERIGYM_RTLLM_SOURCE and VERIGYM_RTLLM_ICARUS12_IMAGE for qualification",
)
@pytest.mark.parametrize(
    "variant",
    ["counter_12_agent_eval_v1", "up_down_counter_agent_eval_v1"],
)
def test_pinned_reference_and_known_bad_are_qualified_without_fallback(
    tmp_path: Path,
    variant: str,
) -> None:
    source = Path(os.environ["VERIGYM_RTLLM_SOURCE"])
    image = os.environ["VERIGYM_RTLLM_ICARUS12_IMAGE"]
    source_config = SuiteSourceConfig(source_root=source, variant=variant)
    suite = RTLLMSuite().with_source(source_config)
    task = suite.load_task(next(iter(suite.discover())))
    assets = suite.resolve_assets(task)
    visible = Path(assets.visible_root)
    visible_texts = [
        path.read_text(encoding="utf-8") for path in visible.rglob("*") if path.is_file()
    ]
    assert assets.hidden_assets[0].content not in visible_texts
    assert not any("verifier" in path.relative_to(visible).parts for path in visible.rglob("*"))
    cases = list(suite.conformance_cases())
    assert [case.expected_resolved for case in cases] == [True, False]

    registries = build_registries(discover_external=False)
    runtime = registries.runtimes.get("docker").configure(
        DockerRuntimeConfig(image=image, pull_policy="never")
    )
    runtime.prepare(f"rtllm-agent-eval-qualification-{variant}")
    try:
        assert runtime.descriptor.image is not None
        assert _is_icarus12_version(runtime.descriptor.image.iverilog_version)
        assert _is_icarus12_version(runtime.descriptor.image.vvp_version)
        for case in cases:
            candidate = tmp_path / case.name
            copy_tree_safely(Path(assets.visible_root), candidate)
            for relative, content in case.candidate.files.items():
                destination = candidate / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            results = VeriGym(registries)._verify_candidate(
                suite=suite,
                task=task,
                assets=assets,
                runtime=runtime,
                candidate_dir=candidate,
                artifact_root=tmp_path / "artifacts" / case.name,
            )
            resolved = all(result.status == VerifierStatus.PASSED for result in results)
            assert resolved is case.expected_resolved
    finally:
        runtime.close()
