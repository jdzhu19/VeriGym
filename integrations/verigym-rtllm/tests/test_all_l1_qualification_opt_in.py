from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym.core.orchestrator import VeriGym
from verigym.core.workspace import copy_tree_safely
from verigym.plugin_api import Candidate, SuiteSourceConfig, ToolContext
from verigym.registry.collections import build_registries
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.verifier import VerifierStatus

from verigym_rtllm import RTLLMSuite
from verigym_rtllm.adapter import ALL_AGENT_EVAL_VARIANT, _is_icarus12_version
from verigym_rtllm.manifest import FROZEN_TASK_COUNT

pytestmark = [pytest.mark.external_benchmark, pytest.mark.docker_integration]


def _sanitized_failure(path: Path) -> dict[str, int | bool]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lowered = text.lower()
    return {
        "bytes": len(text.encode("utf-8")),
        "lines": len(text.splitlines()),
        "syntax_error": "syntax error" in lowered,
        "unknown_module": "unknown module" in lowered,
        "unable_to_bind": "unable to bind" in lowered,
        "unsupported": "not supported" in lowered or "unsupported" in lowered,
    }


@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE")
    or not os.environ.get("VERIGYM_RTLLM_ICARUS12_IMAGE"),
    reason="set VERIGYM_RTLLM_SOURCE and VERIGYM_RTLLM_ICARUS12_IMAGE for qualification",
)
def test_all_l1_references_pass_public_compile_and_hidden_final_verification(
    tmp_path: Path,
) -> None:
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(
            source_root=Path(os.environ["VERIGYM_RTLLM_SOURCE"]),
            variant=ALL_AGENT_EVAL_VARIANT,
        )
    )
    registries = build_registries(discover_external=False)
    runtime = registries.runtimes.get("docker").configure(
        DockerRuntimeConfig(
            image=os.environ["VERIGYM_RTLLM_ICARUS12_IMAGE"],
            pull_policy="never",
        )
    )
    runtime.prepare("rtllm-all-l1-qualification")
    try:
        assert runtime.descriptor.image is not None
        assert _is_icarus12_version(runtime.descriptor.image.iverilog_version)
        assert _is_icarus12_version(runtime.descriptor.image.vvp_version)
        refs = list(suite.discover())
        assert len(refs) == FROZEN_TASK_COUNT
        selected = os.environ.get("VERIGYM_RTLLM_QUALIFICATION_TASK")
        if selected:
            refs = [ref for ref in refs if ref.native_id == selected]
            assert len(refs) == 1, f"unknown RTLLM qualification task: {selected}"
        start = os.environ.get("VERIGYM_RTLLM_QUALIFICATION_START")
        if start:
            positions = [index for index, ref in enumerate(refs) if ref.native_id == start]
            assert len(positions) == 1, f"unknown RTLLM qualification start task: {start}"
            refs = refs[positions[0] :]
        first_public_negative = refs[0].native_id
        for ref in refs:
            task = suite.load_task(ref)
            assets = suite.resolve_assets(task)
            reference = suite.reference_solution(task)
            assert reference is not None
            cases = [
                ("reference", reference, True),
                (
                    "missing-module",
                    Candidate(
                        files={
                            f"repository/rtl/{ref.native_id}.v": suite._candidate_stub(
                                suite._manifest_for_task(task)
                            )
                        },
                        label="known-bad-missing-module",
                    ),
                    False,
                ),
            ]
            if os.environ.get("VERIGYM_RTLLM_QUALIFICATION_REFERENCE_ONLY") == "1":
                cases = cases[:1]
            for label, candidate_files, expected in cases:
                candidate = tmp_path / ref.native_id / label
                copy_tree_safely(Path(assets.visible_root), candidate)
                for relative, content in candidate_files.files.items():
                    destination = candidate / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(content, encoding="utf-8")

                if expected or ref.native_id == first_public_negative:
                    session = runtime.create_session(
                        SessionSpec(
                            source_dir=str(candidate / "repository"),
                            label="diagnostic",
                            max_output_bytes=1_000_000,
                        )
                    )
                    try:
                        public = registries.tools.get("iverilog.compile").execute(
                            {
                                "sources": [f"rtl/{ref.native_id}.v"],
                                "top": task.metadata["candidate_top"],
                                "output": ".verigym_internal/public/compile-only",
                                "language": "2012",
                                "timeout_s": 30,
                            },
                            ToolContext(session=session),
                        )
                    finally:
                        session.close()
                    assert public.success is expected, (ref.native_id, label, public.message)

                hidden_root = tmp_path / "artifacts" / ref.native_id / label
                hidden = VeriGym(registries)._verify_candidate(
                    suite=suite,
                    task=task,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate,
                    artifact_root=hidden_root,
                )
                resolved = all(result.status == VerifierStatus.PASSED for result in hidden)
                diagnostic = _sanitized_failure(hidden_root / "functional_hidden" / "stderr.log")
                assert resolved is expected, (ref.native_id, label, hidden, diagnostic)
    finally:
        runtime.close()
