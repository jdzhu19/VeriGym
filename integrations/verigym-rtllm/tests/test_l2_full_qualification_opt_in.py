from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from verigym.plugin_api import SuiteSourceConfig
from verigym.registry.collections import build_registries
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.tool import CommandSpec

from verigym_rtllm import RTLLMSuite
from verigym_rtllm.adapter import FULL_FUNCTIONAL_VARIANT
from verigym_rtllm.manifest import ALL_TASK_NAMES

pytestmark = [pytest.mark.external_benchmark, pytest.mark.docker_integration]

_QUALIFICATION_IMAGE_ID = "sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1"
_CATEGORIES = (
    "reference",
    "stuck-zero",
    "reset-error",
    "protocol-latency-error",
    "functional-error",
)
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
    candidate = record["candidate"]
    for kind in ("public", "hidden"):
        counts[kind] += 1
        source = "public-smoke.sv" if kind == "public" else "hidden-testbench.v"
        top = "public_smoke" if kind == "public" else record["hidden_top"]
        executable = root / ".verigym_internal" / f"{record['case']}-{kind}.vvp"
        compile_result = subprocess.run(
            ["iverilog", "-g2012", "-s", top, "-o", str(executable), candidate, source],
            cwd=case_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if compile_result.returncode != 0:
            issues.append(
                {
                    "case": record["case"],
                    "kind": kind,
                    "status": "compile-failed",
                    "stderr": compile_result.stderr[-1000:],
                }
            )
            continue
        try:
            run_result = subprocess.run(
                ["vvp", str(executable)],
                cwd=case_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            issues.append({"case": record["case"], "kind": kind, "status": "timeout"})
            continue
        output = run_result.stdout + run_result.stderr
        pass_marker = record["public_pass"] if kind == "public" else record["hidden_pass"]
        fail_marker = "VERIGYM_PUBLIC_FAIL" if kind == "public" else record["hidden_fail"]
        passed = (
            run_result.returncode == 0
            and pass_marker in output
            and (not fail_marker or fail_marker not in output)
        )
        if passed != record["expected"]:
            issues.append(
                {
                    "case": record["case"],
                    "kind": kind,
                    "status": "unexpected-pass" if passed else "unexpected-rejection",
                    "output": output[-1000:],
                }
            )
if issues:
    print(json.dumps({"counts": counts, "issues": issues}, sort_keys=True))
    raise SystemExit(1)
print(
    "RTLLM_DOCKER_FULL_L2_PASS "
    f"public={counts['public']} hidden={counts['hidden']} cases={len(records)}"
)
"""


@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE")
    or not os.environ.get("VERIGYM_RTLLM_ICARUS12_IMAGE"),
    reason="set VERIGYM_RTLLM_SOURCE and VERIGYM_RTLLM_ICARUS12_IMAGE for qualification",
)
def test_full_l2_reference_and_four_negative_controls_pass_public_and_hidden_qualification(
    tmp_path: Path,
) -> None:
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(
            source_root=Path(os.environ["VERIGYM_RTLLM_SOURCE"]),
            variant=FULL_FUNCTIONAL_VARIANT,
        )
    )
    assert suite.validate_source().valid
    refs = list(suite.discover())
    assert [ref.native_id for ref in refs] == list(ALL_TASK_NAMES)
    cases = list(suite.conformance_cases())
    assert len(cases) == 250

    qualification_root = tmp_path / "qualification"
    qualification_root.mkdir()
    records: list[dict[str, object]] = []
    for ref in refs:
        name = ref.native_id
        task = suite.load_task(ref)
        manifest = suite._manifest_for_task(task)
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
        hidden_by_mount = {asset.mount_path: asset.content for asset in assets.hidden_assets}
        assert hidden_by_mount["verifier/testbench.v"] is not None
        task_cases = [case for case in cases if case.name.startswith(f"{name}-")]
        assert [case.name.removeprefix(f"{name}-") for case in task_cases] == list(_CATEGORIES)
        assert [case.expected_resolved for case in task_cases] == [
            True,
            False,
            False,
            False,
            False,
        ]
        for case in task_cases:
            relative_root = Path(name) / case.name.removeprefix(f"{name}-")
            case_root = qualification_root / relative_root
            case_root.mkdir(parents=True)
            candidate_path = f"{name}.v"
            candidate_source = case.candidate.files[f"repository/rtl/{name}.v"]
            (case_root / candidate_path).write_text(candidate_source, encoding="utf-8")
            (case_root / "public-smoke.sv").write_text(suite._public_smoke(name), encoding="utf-8")
            (case_root / "hidden-testbench.v").write_text(
                hidden_by_mount["verifier/testbench.v"] or "", encoding="utf-8"
            )
            for auxiliary in manifest.auxiliary_files:
                content = hidden_by_mount[auxiliary]
                assert content is not None
                destination = case_root / auxiliary
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            records.append(
                {
                    "case": case.name,
                    "relative_root": relative_root.as_posix(),
                    "candidate": candidate_path,
                    "hidden_top": manifest.testbench_top,
                    "hidden_pass": manifest.pass_marker,
                    "hidden_fail": manifest.fail_marker,
                    "public_pass": (
                        "PUBLIC_SMOKE_PASS"
                        if name in {"counter_12", "up_down_counter"}
                        else "VERIGYM_PUBLIC_PASS"
                    ),
                    "expected": case.expected_resolved,
                }
            )

    assert len(records) == 250
    (qualification_root / "qualification.json").write_text(
        json.dumps(records, sort_keys=True), encoding="utf-8"
    )
    (qualification_root / "qualification.py").write_text(_BATCH_RUNNER, encoding="utf-8")

    registries = build_registries(discover_external=False)
    runtime = registries.runtimes.get("docker").configure(
        DockerRuntimeConfig(
            image=os.environ["VERIGYM_RTLLM_ICARUS12_IMAGE"],
            pull_policy="never",
        )
    )
    runtime.prepare("rtllm-full-l2-batched-qualification")
    try:
        image = runtime.descriptor.image
        assert image is not None
        assert image.resolved_image_id == _QUALIFICATION_IMAGE_ID
        session = runtime.create_session(
            SessionSpec(
                source_dir=str(qualification_root),
                label="verifier",
                max_output_bytes=4_000_000,
            )
        )
        try:
            completed = session.execute(
                CommandSpec(argv=["python3", "qualification.py"], timeout_s=900)
            )
        finally:
            session.close()
        assert completed.exit_code == 0, (completed.stdout, completed.stderr)
        assert "RTLLM_DOCKER_FULL_L2_PASS public=250 hidden=250 cases=250" in completed.stdout
    finally:
        runtime.close()
