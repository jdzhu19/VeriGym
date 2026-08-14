from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from verigym.plugin_api import (
    ErrorCategory,
    ToolVisibility,
    VerifierNode,
    VerifierStatus,
    hash_bytes,
    hash_directory,
)

from verigym_hwe_bench import docker_verifier
from verigym_hwe_bench.docker_verifier import DockerHweVerifier, _render_runner
from verigym_hwe_bench.models import (
    HweInstance,
    ImageLockEntry,
    ImageLockEntryV2,
    LicenseFileLock,
    VerifierDependencyFile,
    repository_profile,
)


@pytest.mark.parametrize("airgapped", [False, True])
def test_verifier_parses_pass_without_persisting_hidden_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    airgapped: bool,
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
            payload = {"Id": image_id, "RepoDigests": [] if airgapped else [f"name@{digest}"]}
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
    assert result.metadata["manifest_digest_observed"] is not airgapped
    assert result.metadata["seccomp_unconfined"] is False
    assert result.metadata["seccomp_profile_sha256"] == docker_verifier._SECCOMP_PROFILE_SHA256
    assert "SECRET_TESTBENCH_CONTENT" not in persisted
    assert "SECRET_RUNTIME_OUTPUT" not in persisted


def test_packaged_seccomp_profile_is_hash_bound_and_never_allows_by_default() -> None:
    profile = docker_verifier._validated_seccomp_profile()
    payload = json.loads(profile.read_text(encoding="utf-8"))

    assert hash_bytes(profile.read_bytes()) == docker_verifier._SECCOMP_PROFILE_SHA256
    assert payload["defaultAction"] == "SCMP_ACT_ERRNO"
    assert "clone3" not in {
        name for syscall in payload["syscalls"] for name in syscall.get("names", [])
    }


def test_packaged_seccomp_profile_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    changed = tmp_path / "changed-seccomp.json"
    changed.write_text('{"defaultAction":"SCMP_ACT_ALLOW"}\n', encoding="utf-8")
    monkeypatch.setattr(docker_verifier, "_SECCOMP_PROFILE", changed)

    with pytest.raises(ValueError, match="profile changed"):
        docker_verifier._validated_seccomp_profile()


def test_runner_uses_repository_specific_base_commit_marker(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    entry = ImageLockEntry(
        instance_id="openhwgroup/cva6:pr-2170",
        slug="openhwgroup__cva6__pr-2170",
        image_reference="ghcr.io/pku-liang/openhwgroup_m_cva6:pr-2170",
        manifest_digest=f"sha256:{'3' * 64}",
        image_id=f"sha256:{'2' * 64}",
        repository_home="/home/cva6",
        base_commit="1" * 40,
        repository_hash=hash_directory(repository),
        reference_repository_hash="4" * 64,
        reference_candidate_hash="5" * 64,
        reference_patch_hash="6" * 64,
        verifier_payload_hash="7" * 64,
        task_bundle_hash="8" * 64,
        license_file_hash="9" * 64,
    )

    runner = _render_runner(entry)

    assert "cd /home/cva6" in runner
    assert runner.count("git -c safe.directory=/home/cva6") == 5
    assert "VERIGYM_HWE_SETUP_FAILURE" in runner
    assert "VERIGYM_HWE_TESTBENCH_STARTED" in runner
    assert "/home/cva6_base_commit.txt" in runner
    assert "/home/ibex_base_commit.txt" not in runner
    syntax = subprocess.run(["bash", "-n"], input=runner.encode(), capture_output=True, check=False)
    assert syntax.returncode == 0


def test_v2_runner_uses_explicit_non_derived_rocket_marker() -> None:
    profile = repository_profile("chipsalliance/rocket-chip")
    entry = ImageLockEntryV2(
        instance_id="chipsalliance/rocket-chip:pr-3065",
        slug="chipsalliance__rocket-chip__pr-3065",
        image_reference="ghcr.io/pku-liang/chipsalliance_m_rocket-chip:pr-3065",
        manifest_digest=f"sha256:{'3' * 64}",
        image_id=f"sha256:{'2' * 64}",
        repository_home=profile.repository_home,
        base_commit_marker=profile.base_commit_marker,
        base_commit="1" * 40,
        repository_hash="4" * 64,
        reference_repository_hash="5" * 64,
        reference_candidate_hash="6" * 64,
        reference_patch_hash="7" * 64,
        verifier_payload_hash="8" * 64,
        task_bundle_hash="9" * 64,
        repository_profile_hash=profile.profile_hash,
        license_inventory=[LicenseFileLock(path="LICENSE.Berkeley", sha256="a" * 64)],
    )

    runner = _render_runner(entry)

    assert "cd /home/rocket-chip" in runner
    assert "/home/base_commit.txt" in runner
    assert "/home/rocket-chip_base_commit.txt" not in runner


@pytest.mark.parametrize(
    ("output", "returncode", "expected_status", "expected_category"),
    [
        (
            b"VERIGYM_HWE_SETUP_FAILURE:repository_reset\n",
            128,
            VerifierStatus.ERROR,
            ErrorCategory.SANDBOX_ERROR,
        ),
        (
            (
                b"VERIGYM_HWE_TESTBENCH_STARTED\n"
                b"VERIGYM_HWE_SETUP_FAILURE:repository_reset\ncompiler terminated\n"
            ),
            128,
            VerifierStatus.FAILED,
            ErrorCategory.TEST_FAILED,
        ),
    ],
)
def test_verifier_distinguishes_setup_failure_from_candidate_test_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    output: bytes,
    returncode: int,
    expected_status: VerifierStatus,
    expected_category: ErrorCategory,
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
            identity = {"Id": image_id, "RepoDigests": [f"name@{digest}"]}
            return subprocess.CompletedProcess(argv, 0, json.dumps(identity).encode(), b"")
        if argv[:2] == ["docker", "create"]:
            return subprocess.CompletedProcess(argv, 0, b"container-id\n", b"")
        if argv[:3] == ["docker", "start", "--attach"]:
            return subprocess.CompletedProcess(argv, returncode, output, b"")
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

    assert result.status == expected_status
    assert result.error_category == expected_category
    if expected_status == VerifierStatus.ERROR:
        assert result.metadata["failure_stage"] == "repository_reset"
        assert result.tests_passed is None
    else:
        assert "failure_stage" not in result.metadata
        assert result.tests_passed == 0


def test_cache_volume_cleanup_retries_a_transient_release_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[list[str]] = []
    delays: list[float] = []

    def fake_run(argv: list[str], *, timeout_s: int = 60) -> subprocess.CompletedProcess[bytes]:
        assert timeout_s == 30
        attempts.append(argv)
        return subprocess.CompletedProcess(argv, 1 if len(attempts) == 1 else 0, b"", b"")

    monkeypatch.setattr(docker_verifier, "_run", fake_run)
    monkeypatch.setattr(docker_verifier.time, "sleep", delays.append)

    assert docker_verifier._remove_volume("verigym-hwe-cache-fixture") is True
    assert attempts == [
        ["docker", "volume", "rm", "verigym-hwe-cache-fixture"],
        ["docker", "volume", "rm", "verigym-hwe-cache-fixture"],
    ]
    assert delays == [0.25]


@pytest.mark.parametrize(
    ("seed_ready", "expected_status"),
    [(True, VerifierStatus.PASSED), (False, VerifierStatus.ERROR)],
)
def test_verifier_uses_and_removes_an_isolated_offline_cache_volume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    seed_ready: bool,
    expected_status: VerifierStatus,
) -> None:
    base = tmp_path / "base"
    candidate = tmp_path / "candidate"
    base.mkdir()
    candidate.mkdir()
    (base / "demo.scala").write_text("val enabled = true\n", encoding="utf-8")
    (candidate / "demo.scala").write_text("val enabled = true\n", encoding="utf-8")
    payload = b"public dependency fixture\n"
    dependency = VerifierDependencyFile(
        cache_path="https/repo1.maven.org/maven2/org/example/demo/1.0/demo-1.0.jar",
        sha256=hash_bytes(payload),
        size_bytes=len(payload),
    )
    dependency_root = tmp_path / "dependencies"
    dependency_path = dependency_root / dependency.cache_path
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_bytes(payload)
    instance = HweInstance(
        org="chipsalliance",
        repo="rocket-chip",
        number=3065,
        title="fixture",
        problem_statement="fixture",
        base_commit="1" * 40,
        fix_patch="diff --git a/demo.scala b/demo.scala\n",
        tb_script="SECRET_TESTBENCH_CONTENT",
        modified_files=["demo.scala"],
        expected_test_ids=["demo"],
        language="Chisel/Scala",
        license_id="BSD-3-Clause AND Apache-2.0",
    )
    profile = repository_profile(instance.repository_id)
    image_id = f"sha256:{'2' * 64}"
    digest = f"sha256:{'3' * 64}"
    entry = ImageLockEntryV2(
        instance_id=instance.instance_id,
        slug=instance.slug,
        image_reference="ghcr.io/pku-liang/chipsalliance_m_rocket-chip:pr-3065",
        manifest_digest=digest,
        image_id=image_id,
        repository_home=profile.repository_home,
        base_commit_marker=profile.base_commit_marker,
        base_commit=instance.base_commit,
        repository_hash=hash_directory(base),
        reference_repository_hash="4" * 64,
        reference_candidate_hash="5" * 64,
        reference_patch_hash="6" * 64,
        verifier_payload_hash="7" * 64,
        task_bundle_hash="8" * 64,
        repository_profile_hash=profile.profile_hash,
        license_inventory=[LicenseFileLock(path="LICENSE.Berkeley", sha256="9" * 64)],
        verifier_dependencies=[dependency],
    )
    created_volume: list[str] = []
    removed_volume: list[str] = []
    create_argv: list[str] = []
    rendered_seed: list[str] = []

    def fake_run(argv: list[str], *, timeout_s: int = 60) -> subprocess.CompletedProcess[bytes]:
        del timeout_s
        if argv[:3] == ["docker", "image", "inspect"]:
            payload = {"Id": image_id, "RepoDigests": [f"name@{digest}"]}
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b"")
        if argv[:3] == ["docker", "volume", "create"]:
            created_volume.append(argv[-1])
            return subprocess.CompletedProcess(argv, 0, f"{argv[-1]}\n".encode(), b"")
        if argv[:2] == ["docker", "create"]:
            create_argv.extend(argv)
            seed_mount = next(value for value in argv if "verigym-cache-seed.sh" in value)
            seed_source = seed_mount.removeprefix("type=bind,src=").split(",dst=", 1)[0]
            rendered_seed.append(Path(seed_source).read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(argv, 0, b"container-id\n", b"")
        if argv[:3] == ["docker", "start", "--attach"]:
            output = (
                b"VERIGYM_HWE_CACHE_SEED_OK\n" if seed_ready else b""
            ) + b"HWE_BENCH_RESULTS_START\nTEST: demo ... PASS\nHWE_BENCH_RESULTS_END\n"
            return subprocess.CompletedProcess(argv, 0, output, b"")
        if argv[:3] == ["docker", "rm", "--force"]:
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        if argv[:3] == ["docker", "volume", "rm"]:
            removed_volume.append(argv[-1])
            return subprocess.CompletedProcess(argv, 0, f"{argv[-1]}\n".encode(), b"")
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
        verifier_dependency_root=dependency_root,
    )

    assert result.status == expected_status
    assert created_volume == removed_volume
    assert len(created_volume) == 1
    assert "--network" in create_argv
    assert create_argv[create_argv.index("--network") + 1] == "none"
    security_options = [
        create_argv[index + 1]
        for index, value in enumerate(create_argv)
        if value == "--security-opt"
    ]
    assert "no-new-privileges" in security_options
    seccomp_options = [value for value in security_options if value.startswith("seccomp=")]
    assert len(seccomp_options) == 1
    assert seccomp_options[0] != "seccomp=unconfined"
    assert Path(seccomp_options[0].removeprefix("seccomp=")).is_file()
    assert any("type=volume" in value and "/tools/coursier" in value for value in create_argv)
    assert dependency.sha256 in rendered_seed[0]
    assert ".checked" in rendered_seed[0]
    if seed_ready:
        assert result.metadata["cache_volume_removed"] is True
    else:
        assert result.error_category == ErrorCategory.SANDBOX_ERROR
