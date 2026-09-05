from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym.core.orchestrator import VeriGym
from verigym.core.workspace import copy_tree_safely
from verigym.plugin_api import SuiteSourceConfig, ToolContext
from verigym.registry.collections import build_registries
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.verifier import VerifierStatus

from verigym_rtllm import RTLLMSuite
from verigym_rtllm.adapter import L2_BATCH2_VARIANT
from verigym_rtllm.manifest import L2_BATCH2_TASK_NAMES

pytestmark = [pytest.mark.external_benchmark, pytest.mark.docker_integration]


@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE")
    or not os.environ.get("VERIGYM_RTLLM_ICARUS12_IMAGE"),
    reason="set VERIGYM_RTLLM_SOURCE and VERIGYM_RTLLM_ICARUS12_IMAGE for qualification",
)
@pytest.mark.parametrize("name", L2_BATCH2_TASK_NAMES)
def test_l2_batch2_reference_and_four_negative_controls_pass_public_and_hidden_qualification(
    tmp_path: Path,
    name: str,
) -> None:
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(
            source_root=Path(os.environ["VERIGYM_RTLLM_SOURCE"]),
            variant=L2_BATCH2_VARIANT,
        )
    )
    assert suite.validate_source().valid
    registries = build_registries(discover_external=False)
    runtime = registries.runtimes.get("docker").configure(
        DockerRuntimeConfig(
            image=os.environ["VERIGYM_RTLLM_ICARUS12_IMAGE"],
            pull_policy="never",
        )
    )
    runtime.prepare(f"rtllm-l2-batch2-{name}-qualification")
    try:
        all_cases = list(suite.conformance_cases())
        ref = next(ref for ref in suite.discover() if ref.native_id == name)
        task = suite.load_task(ref)
        assets = suite.resolve_assets(task)
        visible = Path(assets.visible_root)
        visible_files = {
            path.relative_to(visible).as_posix(): path.read_text(encoding="utf-8")
            for path in visible.rglob("*")
            if path.is_file()
        }
        hidden_contents = {asset.content for asset in assets.hidden_assets}
        assert not hidden_contents.intersection(visible_files.values())
        assert not any("verifier" in Path(path).parts for path in visible_files)
        task_cases = [case for case in all_cases if case.name.startswith(f"{name}-")]
        assert [case.expected_resolved for case in task_cases] == [
            True,
            False,
            False,
            False,
            False,
        ]
        public_smoke = suite._public_smoke(name)
        for case in task_cases:
            candidate = tmp_path / "candidate" / case.name
            copy_tree_safely(visible, candidate)
            for relative, content in case.candidate.files.items():
                destination = candidate / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")

            public_root = candidate / "repository"
            (public_root / "assets").mkdir(parents=True, exist_ok=True)
            (public_root / "assets" / "public-smoke.sv").write_text(public_smoke, encoding="utf-8")
            session = runtime.create_session(
                SessionSpec(
                    source_dir=str(public_root),
                    label="diagnostic",
                    max_output_bytes=1_000_000,
                )
            )
            try:
                public = registries.tools.get("iverilog.simulate_visible").execute(
                    {
                        "sources": [f"rtl/{name}.v", "assets/public-smoke.sv"],
                        "top": "public_smoke",
                        "pass_marker": "VERIGYM_PUBLIC_PASS",
                        "fail_marker": "VERIGYM_PUBLIC_FAIL",
                        "timeout_s": 60,
                    },
                    ToolContext(session=session),
                )
            finally:
                session.close()
            assert public.success is case.expected_resolved, (
                case.name,
                public.message,
                public.stdout,
                public.stderr,
            )

            hidden = VeriGym(registries)._verify_candidate(
                suite=suite,
                task=task,
                assets=assets,
                runtime=runtime,
                candidate_dir=candidate,
                artifact_root=tmp_path / "artifacts" / case.name,
            )
            resolved = all(result.status == VerifierStatus.PASSED for result in hidden)
            assert resolved is case.expected_resolved
    finally:
        runtime.close()
