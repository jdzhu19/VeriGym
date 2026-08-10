from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from verigym.plugin_api import ToolVisibility, VerifierNode, VerifierStatus, hash_directory

from verigym_hwe_bench import docker_verifier
from verigym_hwe_bench.docker_verifier import DockerHweVerifier
from verigym_hwe_bench.models import HweInstance, ImageLockEntry


def test_verifier_parses_pass_without_persisting_hidden_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    candidate = tmp_path / "candidate"
    base.mkdir()
    candidate.mkdir()
    (base / "demo.sv").write_text("module demo; endmodule\n", encoding="utf-8")
    (candidate / "demo.sv").write_text("module demo; endmodule\n", encoding="utf-8")
    instance = HweInstance(
        org="lowRISC",
        repo="ibex",
        number=1,
        title="fixture",
        problem_statement="fixture",
        base_commit="1" * 40,
        fix_patch="diff --git a/demo.sv b/demo.sv\n",
        tb_script="SECRET_TESTBENCH_CONTENT",
        modified_files=["demo.sv"],
        expected_test_ids=["demo"],
    )
    image_id = f"sha256:{'2' * 64}"
    digest = f"sha256:{'3' * 64}"
    entry = ImageLockEntry(
        instance_id=instance.instance_id,
        slug=instance.slug,
        image_reference="ghcr.io/pku-liang/lowrisc_m_ibex:pr-1",
        manifest_digest=digest,
        image_id=image_id,
        repository_home="/home/ibex",
        base_commit=instance.base_commit,
        repository_hash=hash_directory(base),
        reference_repository_hash="4" * 64,
        reference_candidate_hash="5" * 64,
        reference_patch_hash="6" * 64,
        verifier_payload_hash="7" * 64,
        task_bundle_hash="8" * 64,
        license_file_hash="9" * 64,
    )

    def fake_run(argv: list[str], *, timeout_s: int = 60) -> subprocess.CompletedProcess[bytes]:
        del timeout_s
        if argv[:3] == ["docker", "image", "inspect"]:
            payload = {"Id": image_id, "RepoDigests": [f"name@{digest}"]}
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b"")
        if argv[:2] == ["docker", "create"]:
            return subprocess.CompletedProcess(argv, 0, b"container-id\n", b"")
        if argv[:3] == ["docker", "start", "--attach"]:
            output = (
                b"build output\nHWE_BENCH_RESULTS_START\n"
                b"TEST: demo ... PASS\nHWE_BENCH_RESULTS_END\nSECRET_RUNTIME_OUTPUT\n"
            )
            return subprocess.CompletedProcess(argv, 0, output, b"")
        if argv[:3] == ["docker", "rm", "--force"]:
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        raise AssertionError(argv)

    monkeypatch.setattr(docker_verifier, "_run", fake_run)
    node = VerifierNode(
        id="run_hidden_regression",
        plugin="hwe_bench.simulate",
        visibility=ToolVisibility.VERIFIER_ONLY,
        request={"identity": "frozen"},
        timeout_s=10,
    )
    result = DockerHweVerifier().evaluate(
        instance=instance,
        entry=entry,
        node=node,
        base_repository=base,
        candidate_repository=candidate,
        artifact_root=tmp_path / "artifacts",
    )
    persisted = (tmp_path / "artifacts" / node.id / "result.json").read_text()
    assert result.status == VerifierStatus.PASSED
    assert result.tests_passed == result.tests_total == 1
    assert "SECRET_TESTBENCH_CONTENT" not in persisted
    assert "SECRET_RUNTIME_OUTPUT" not in persisted
