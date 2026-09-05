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
from verigym_rtllm.adapter import FEEDBACK_V2_VARIANT
from verigym_rtllm.manifest import ALL_TASK_NAMES

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
output_path = root / ".verigym_internal" / "command-output.log"


def run_bounded(argv, *, cwd, timeout):
    bounded_argv = [
        "/bin/sh",
        "-c",
        'ulimit -f 2048; exec "$@"',
        "verigym-bounded-command",
        *argv,
    ]
    try:
        with output_path.open("wb") as stream:
            completed = subprocess.run(
                bounded_argv,
                cwd=cwd,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    output = output_path.read_bytes()[-1_000_000:].decode("utf-8", errors="replace")
    output_path.unlink(missing_ok=True)
    return completed, output


for record in records:
    case_root = root / record["relative_root"]
    for kind in ("public", "hidden"):
        counts[kind] += 1
        source = "public-smoke.sv" if kind == "public" else "hidden-testbench.v"
        top = "public_smoke" if kind == "public" else record["hidden_top"]
        executable = root / ".verigym_internal" / f"{record['case']}-{kind}.vvp"
        compiled, output = run_bounded(
            ["iverilog", "-g2012", "-s", top, "-o", str(executable), record["candidate"], source],
            cwd=case_root,
            timeout=60,
        )
        passed = False
        if compiled is not None and compiled.returncode == 0:
            executed, output = run_bounded(
                ["vvp", "-n", str(executable)],
                cwd=case_root,
                timeout=60,
            )
            if executed is not None:
                pass_marker = record["public_pass"] if kind == "public" else record["hidden_pass"]
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
                    "output": output[-1000:],
                }
            )
if issues:
    print(json.dumps({"counts": counts, "issues": issues}, sort_keys=True))
    raise SystemExit(1)
print(
    "RTLLM_FEEDBACK_V2_PASS "
    f"public={counts['public']} hidden={counts['hidden']} cases={len(records)}"
)
"""


@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RTLLM_SOURCE")
    or not os.environ.get("VERIGYM_RTLLM_ICARUS12_IMAGE")
    or not os.environ.get("VERIGYM_RTLLM_FIFO_BEHAVIOR_CHECKER_V2"),
    reason="set RTLLM source, Icarus 12 image, and verifier-only FIFO checker",
)
def test_feedback_v2_reference_and_mutants_pass_public_and_hidden_qualification(
    tmp_path: Path,
) -> None:
    suite = RTLLMSuite().with_source(
        SuiteSourceConfig(
            source_root=Path(os.environ["VERIGYM_RTLLM_SOURCE"]),
            variant=FEEDBACK_V2_VARIANT,
        )
    )
    assert suite.validate_source().valid
    refs = list(suite.discover())
    assert [ref.native_id for ref in refs] == list(ALL_TASK_NAMES)
    cases = list(suite.conformance_cases())
    assert len(cases) == 650

    qualification_root = tmp_path / "qualification"
    qualification_root.mkdir()
    records: list[dict[str, object]] = []
    for ref in refs:
        name = ref.native_id
        task = suite.load_task(ref)
        manifest = suite._manifest_for_task(task)
        assets = suite.resolve_assets(task)
        hidden = {asset.mount_path: asset.content for asset in assets.hidden_assets}
        task_cases = [case for case in cases if case.name.startswith(f"{name}-")]
        assert len(task_cases) == 13
        for case in task_cases:
            case_suffix = case.name.removeprefix(f"{name}-")
            relative_root = Path(name) / case_suffix
            case_root = qualification_root / relative_root
            case_root.mkdir(parents=True)
            candidate_path = f"{name}.v"
            (case_root / candidate_path).write_text(
                case.candidate.files[f"repository/rtl/{name}.v"], encoding="utf-8"
            )
            (case_root / "public-smoke.sv").write_text(suite._public_smoke(name), encoding="utf-8")
            (case_root / "hidden-testbench.v").write_text(
                hidden["verifier/testbench.v"] or "", encoding="utf-8"
            )
            for auxiliary in suite._effective_manifest(manifest).auxiliary_files:
                (case_root / auxiliary).write_text(hidden[auxiliary] or "", encoding="utf-8")
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

    assert len(records) == 650
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
    runtime.prepare("rtllm-feedback-v2-batched-qualification")
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
                CommandSpec(argv=["python3", "qualification.py"], timeout_s=1800)
            )
        finally:
            session.close()
        assert completed.exit_code == 0, (completed.stdout, completed.stderr)
        assert "RTLLM_FEEDBACK_V2_PASS public=650 hidden=650 cases=650" in completed.stdout
    finally:
        runtime.close()
