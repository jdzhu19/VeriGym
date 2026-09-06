from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym.experiments.private_staging import PrivateQualificationStaging
from verigym.plugin_api import SuiteSourceConfig
from verigym.registry.collections import build_registries
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.tool import CommandSpec

from verigym_rtllm import RTLLMSuite
from verigym_rtllm.adapter import L2_DIAGNOSTIC3_VARIANT
from verigym_rtllm.manifest import L2_DIAGNOSTIC3_TASK_NAMES

pytestmark = [pytest.mark.external_benchmark, pytest.mark.docker_integration]

_QUALIFICATION_IMAGE_ID = "sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1"
_BATCH_RUNNER = r"""from __future__ import annotations

import json
import subprocess
from pathlib import Path


root = Path("/workspace")
records = json.loads((root / "qualification.json").read_text(encoding="utf-8"))
issues = []
counts = {"public": 0, "hidden": 0}
for record in records:
    case_root = root / record["relative_root"]
    for kind in ("public", "hidden"):
        counts[kind] += 1
        source = "public-smoke.sv" if kind == "public" else "hidden-testbench.v"
        top = "public_smoke" if kind == "public" else record["hidden_top"]
        executable = root / ".verigym_internal" / f"{record['case']}-{kind}.vvp"
        try:
            compiled = subprocess.run(
                [
                    "iverilog", "-g2012", "-s", top, "-o", str(executable),
                    record["candidate"], source,
                ],
                cwd=case_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            issues.append({"case": record["case"], "kind": kind, "status": "compile-timeout"})
            continue
        if compiled.returncode != 0:
            issues.append({"case": record["case"], "kind": kind, "status": "compile-failed"})
            continue
        try:
            executed = subprocess.run(
                ["vvp", str(executable)],
                cwd=case_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            issues.append({"case": record["case"], "kind": kind, "status": "run-timeout"})
            continue
        output = executed.stdout + executed.stderr
        pass_marker = "VERIGYM_PUBLIC_PASS" if kind == "public" else record["hidden_pass"]
        fail_marker = "VERIGYM_PUBLIC_FAIL" if kind == "public" else record["hidden_fail"]
        passed = (
            executed.returncode == 0
            and pass_marker in output
            and (not fail_marker or fail_marker not in output)
        )
        if passed != record["expected"]:
            issues.append(
                {
                    "case": record["case"],
                    "kind": kind,
                    "status": "unexpected-pass" if passed else "unexpected-rejection",
                }
            )
if issues:
    print(json.dumps({"counts": counts, "issues": issues}, sort_keys=True))
    raise SystemExit(1)
print(
    "RTLLM_DOCKER_DIAGNOSTIC3_PASS "
    f"public={counts['public']} hidden={counts['hidden']} cases={len(records)}"
)
"""


@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE")
    or not os.environ.get("VERIGYM_RTLLM_ICARUS12_IMAGE"),
    reason="set VERIGYM_RTLLM_SOURCE and VERIGYM_RTLLM_ICARUS12_IMAGE for qualification",
)
def test_diagnostic3_reference_and_controls_pass_public_and_hidden_qualification(
    tmp_path: Path,
) -> None:
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(
            source_root=Path(os.environ["VERIGYM_RTLLM_SOURCE"]),
            variant=L2_DIAGNOSTIC3_VARIANT,
        )
    )
    assert suite.validate_source().valid
    cases = list(suite.conformance_cases())
    assert len(cases) == 15

    staging = PrivateQualificationStaging(tmp_path / "qualification-private")
    runtime = None
    session = None
    with staging:
        records: list[dict[str, object]] = []
        for ref in suite.discover():
            name = ref.native_id
            task = suite.load_task(ref)
            manifest = suite._manifest_for_task(task)
            assets = suite.resolve_assets(task)
            hidden = {asset.mount_path: asset.content for asset in assets.hidden_assets}
            task_cases = [case for case in cases if case.name.startswith(f"{name}-")]
            assert len(task_cases) == 5
            for case in task_cases:
                suffix = case.name.removeprefix(f"{name}-")
                relative_root = Path(name) / suffix
                candidate_name = f"{name}.v"
                staging.write_text(
                    relative_root / candidate_name,
                    case.candidate.files[f"repository/rtl/{name}.v"],
                )
                staging.write_text(relative_root / "public-smoke.sv", suite._public_smoke(name))
                staging.write_text(
                    relative_root / "hidden-testbench.v",
                    hidden["verifier/testbench.v"] or "",
                )
                for auxiliary in manifest.auxiliary_files:
                    staging.write_text(relative_root / auxiliary, hidden[auxiliary] or "")
                records.append(
                    {
                        "case": case.name,
                        "relative_root": relative_root.as_posix(),
                        "candidate": candidate_name,
                        "hidden_top": manifest.testbench_top,
                        "hidden_pass": manifest.pass_marker,
                        "hidden_fail": manifest.fail_marker,
                        "expected": case.expected_resolved,
                    }
                )
        assert tuple(ref.native_id for ref in suite.discover()) == L2_DIAGNOSTIC3_TASK_NAMES
        staging.write_json("qualification.json", records)
        staging.write_text("qualification.py", _BATCH_RUNNER)

        registries = build_registries(discover_external=False)
        runtime = registries.runtimes.get("docker").configure(
            DockerRuntimeConfig(
                image=os.environ["VERIGYM_RTLLM_ICARUS12_IMAGE"],
                pull_policy="never",
            )
        )
        try:
            runtime.prepare("rtllm-l2-diagnostic3-qualification")
            image = runtime.descriptor.image
            assert image is not None
            assert image.resolved_image_id == _QUALIFICATION_IMAGE_ID
            session = runtime.create_session(
                SessionSpec(
                    source_dir=str(staging.root),
                    label="verifier",
                    max_output_bytes=1_000_000,
                )
            )
            completed = session.execute(
                CommandSpec(argv=["python3", "qualification.py"], timeout_s=900)
            )
            assert completed.exit_code == 0, (completed.stdout, completed.stderr)
            assert "RTLLM_DOCKER_DIAGNOSTIC3_PASS public=15 hidden=15 cases=15" in (
                completed.stdout
            )
        finally:
            if session is not None:
                session.close()
            if runtime is not None:
                runtime.close()
        descriptor = runtime.descriptor
        assert descriptor.cleanup is not None
        assert descriptor.cleanup.complete is True
        receipt = staging.cleanup()

    assert receipt["cleanup_complete"] is True
    assert receipt["residual_paths"] == 0
