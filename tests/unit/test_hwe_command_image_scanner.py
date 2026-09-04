from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from verigym.hwe.image_lock import build_hwe_agent_image_lock, build_hwe_command_source_lock

_scanner = importlib.import_module("scripts.scan_and_lock_cva6_hwe_command_image")


def test_scanner_accepts_v52_command_source_lock_without_reinterpreting_agent_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_lock = build_hwe_command_source_lock(
        task_id="hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728",
        task_hash="1" * 64,
        source_hash="2" * 64,
        prepared_source_image_lock_sha256="3" * 64,
        verifier_base_image_id=f"sha256:{'4' * 64}",
        toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
        allowlisted_artifacts=[
            {"path": "/usr/bin/make", "sha256": "5" * 64, "role": "build_tool"},
            {
                "path": "/tools/verilator/bin/verilator_bin",
                "sha256": "6" * 64,
                "role": "simulator",
            },
        ],
    )
    identity_path = tmp_path / "source-lock.json"
    identity_path.write_text(json.dumps(source_lock.model_dump(mode="json")), encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        _scanner.HweAgentImageLock,
        "model_validate",
        lambda _value: (_ for _ in ()).throw(AssertionError("historical path was used")),
    )

    with pytest.raises(ValueError, match="receipt differs"):
        _scanner.scan_and_lock(
            receipt_path=receipt_path,
            identity_lock_path=identity_path,
            security_output=tmp_path / "security.json",
            lock_output=tmp_path / "lock.json",
        )


def test_ibex_verilator_profile_is_task_explicit_and_keeps_ibex_isolation() -> None:
    profile = _scanner._REPOSITORY_PROFILES["ibex-verilator"]

    assert profile.runtime_role == "hwe-ibex-command"
    assert profile.source_whiteout_path == "/home/ibex"
    assert profile.toolchain_profile_id == "ibex-verilator-system-container-native-v1"
    assert any("verilator_bin" in command for command, _exit_code in profile.tool_assertions)


def _inspection(user: str) -> dict[str, Any]:
    return {
        "HostConfig": {
            "NetworkMode": "none",
            "IpcMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "PidMode": "",
            "Memory": 16 * 1024**3,
            "MemorySwap": 16 * 1024**3,
            "NanoCpus": 4_000_000_000,
            "PidsLimit": 4096,
        },
        "Config": {"Env": list(_scanner._EXPECTED_IMAGE_ENVIRONMENT), "User": user},
        "Mounts": [{"Destination": "/workspace/repository", "RW": True}],
    }


def _run_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    start_returncode: int,
    container_exit_code: int,
    stdout: bytes = b"",
    stderr: bytes = b"",
    create_workspace_proof: bool = False,
    runtime_scratch_parent: Path | None = None,
):
    scratch_parent = runtime_scratch_parent or tmp_path
    workspace = scratch_parent / "scan-workspace"
    workspace.mkdir()
    monkeypatch.setattr(_scanner, "_SCRATCH_PARENT", tmp_path)

    def fake_mkdtemp(**kwargs):
        assert kwargs["dir"] == scratch_parent.resolve()
        return str(workspace)

    monkeypatch.setattr(_scanner.tempfile, "mkdtemp", fake_mkdtemp)
    removed: list[str] = []

    def fake_subprocess_run(arguments, **_kwargs):
        if arguments[:2] == ["docker", "create"]:
            return subprocess.CompletedProcess(arguments, 0, stdout=b"container-id\n", stderr=b"")
        if arguments[:3] == ["docker", "start", "--attach"]:
            if create_workspace_proof:
                (workspace / "workspace-proof").write_text("ok", encoding="utf-8")
            return subprocess.CompletedProcess(
                arguments,
                start_returncode,
                stdout=stdout,
                stderr=stderr,
            )
        if arguments[:4] == ["docker", "container", "rm", "--force"]:
            removed.append(arguments[-1])
            return subprocess.CompletedProcess(arguments, 0, stdout=b"container-id\n", stderr=b"")
        raise AssertionError(arguments)

    inspections = iter(
        (
            [_inspection("1000:1000")],
            [{"State": {"ExitCode": container_exit_code}}],
        )
    )

    def fake_run(arguments: list[str], *, timeout: int = 120):
        assert arguments[:3] == ["docker", "container", "inspect"]
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(next(inspections)))

    monkeypatch.setattr(_scanner.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(_scanner, "_run", fake_run)
    result = _scanner._container_scan(
        "sha256:" + "1" * 64,
        user="1000:1000",
        rg_sha256="2" * 64,
        artifacts=[{"path": "/usr/bin/make", "sha256": "3" * 64}],
        runtime_scratch_parent=runtime_scratch_parent,
    )
    return result, removed


def test_container_scan_uses_explicit_same_path_scratch_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch_parent = tmp_path / "successor-output" / "scan-workspaces"
    scratch_parent.mkdir(parents=True)
    (checks, diagnostic), _removed = _run_scan(
        tmp_path,
        monkeypatch,
        start_returncode=0,
        container_exit_code=0,
        create_workspace_proof=True,
        runtime_scratch_parent=scratch_parent,
    )

    assert all(checks.values())
    assert diagnostic["temporary_workspace_removed"] is True
    assert list(scratch_parent.iterdir()) == []


def test_container_scan_rejects_symlinked_explicit_scratch_parent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValueError, match="scratch parent is unsafe"):
        _scanner._container_scan(
            "sha256:" + "1" * 64,
            user="1000:1000",
            rg_sha256="2" * 64,
            artifacts=[],
            runtime_scratch_parent=linked,
        )


def test_container_scan_rejects_relative_explicit_scratch_parent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="scratch parent is unsafe"):
        _scanner._container_scan(
            "sha256:" + "1" * 64,
            user="1000:1000",
            rg_sha256="2" * 64,
            artifacts=[],
            runtime_scratch_parent=Path(tmp_path.name),
        )


def _v130_runtime_policy() -> _scanner.CommandImageScanRuntimePolicy:
    return _scanner.CommandImageScanRuntimePolicy(
        policy_id="deepseek-harness-v130-bounded-command-scan-v1",
        create_timeout_seconds=300,
        inspect_timeout_seconds=60,
        start_timeout_seconds=180,
        remove_timeout_seconds=120,
        overall_timeout_seconds=720,
        container_name="verigym-hwe-v130-command-scan-pr-465",
        owner_label="deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1",
    )


def test_explicit_scan_runtime_policy_is_finite_and_self_describing() -> None:
    policy = _v130_runtime_policy()

    assert policy.as_dict()["create_timeout_seconds"] == 300
    assert policy.as_dict()["overall_timeout_seconds"] == 720
    with pytest.raises(ValueError, match="runtime policy"):
        _scanner.CommandImageScanRuntimePolicy(
            policy_id=policy.policy_id,
            create_timeout_seconds=300,
            inspect_timeout_seconds=60,
            start_timeout_seconds=180,
            remove_timeout_seconds=120,
            overall_timeout_seconds=719,
            container_name=policy.container_name,
            owner_label=policy.owner_label,
        )


def test_create_timeout_uses_deterministic_name_and_cleans_without_container_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "scan-workspace"
    workspace.mkdir()
    monkeypatch.setattr(_scanner.tempfile, "mkdtemp", lambda **_kwargs: str(workspace))
    policy = _v130_runtime_policy()
    calls: list[tuple[list[str], float]] = []
    sensitive = b"daemon output that must not persist"

    def fake_subprocess_run(arguments, **kwargs):
        calls.append((arguments, kwargs["timeout"]))
        if arguments[:2] == ["docker", "create"]:
            raise subprocess.TimeoutExpired(arguments, kwargs["timeout"], stderr=sensitive)
        if arguments[:4] == ["docker", "container", "rm", "--force"]:
            return subprocess.CompletedProcess(
                arguments,
                1,
                stdout=b"",
                stderr=b"Error: No such container: deterministic-name\n",
            )
        raise AssertionError(arguments)

    monkeypatch.setattr(_scanner.subprocess, "run", fake_subprocess_run)

    with pytest.raises(_scanner.CommandImageScanFailure) as raised:
        _scanner._container_scan(
            "sha256:" + "1" * 64,
            user="1000:1000",
            rg_sha256="2" * 64,
            artifacts=[],
            runtime_scratch_parent=tmp_path,
            runtime_policy=policy,
        )

    diagnostic = raised.value.diagnostic
    create, remove = calls
    assert create[1] <= 300
    assert ["--name", policy.container_name] == create[0][
        create[0].index("--name") : create[0].index("--name") + 2
    ]
    assert f"verigym.owner={policy.owner_label}" in create[0]
    assert remove[0][-1] == policy.container_name
    assert remove[1] <= 120
    assert diagnostic["error_category"] == "docker_create_timeout"
    assert diagnostic["create_timed_out"] is True
    assert diagnostic["temporary_container_created"] is False
    assert diagnostic["temporary_container_removed"] is True
    assert diagnostic["temporary_workspace_removed"] is True
    assert diagnostic["runtime_policy"] == policy.as_dict()
    assert sensitive.decode() not in json.dumps(diagnostic)
    assert hashlib.sha256(sensitive).hexdigest() not in json.dumps(diagnostic)


def test_container_assertion_failure_is_attributable_and_output_is_not_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sensitive = b"credential=do-not-persist"

    with pytest.raises(_scanner.CommandImageScanFailure) as raised:
        _run_scan(
            tmp_path,
            monkeypatch,
            start_returncode=77,
            container_exit_code=77,
            stderr=sensitive,
        )

    diagnostic = raised.value.diagnostic
    assert diagnostic["error_category"] == "container_assertion_failed"
    assert diagnostic["assertion_id"] == "ripgrep_hash_exact"
    assert diagnostic["exit_code"] == 77
    assert diagnostic["container_exit_code"] == 77
    assert diagnostic["temporary_container_removed"] is True
    assert diagnostic["temporary_workspace_removed"] is True
    assert diagnostic["raw_output_persisted"] is False
    assert diagnostic["stderr_sha256"] is None
    assert diagnostic["nonempty_output_hashed"] is False
    assert sensitive.decode() not in json.dumps(diagnostic)
    assert hashlib.sha256(sensitive).hexdigest() not in json.dumps(diagnostic)


def test_docker_start_failure_is_distinct_from_inner_assertion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(_scanner.CommandImageScanFailure) as raised:
        _run_scan(
            tmp_path,
            monkeypatch,
            start_returncode=125,
            container_exit_code=0,
            stderr=b"daemon detail that must remain private",
        )

    diagnostic = raised.value.diagnostic
    assert diagnostic["error_category"] == "docker_start_failed"
    assert diagnostic["assertion_id"] is None
    assert diagnostic["exit_code"] == 125
    assert diagnostic["container_exit_code"] == 0


def test_container_scan_success_records_content_free_exit_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (checks, diagnostic), removed = _run_scan(
        tmp_path,
        monkeypatch,
        start_returncode=0,
        container_exit_code=0,
        create_workspace_proof=True,
    )

    assert all(checks.values())
    assert diagnostic["status"] == "passed"
    assert diagnostic["exit_code"] == 0
    assert diagnostic["container_exit_code"] == 0
    assert diagnostic["temporary_container_removed"] is True
    assert diagnostic["temporary_workspace_removed"] is True
    assert removed == ["container-id"]


def test_container_scan_rejects_over_bound_diagnostic_and_still_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(_scanner.CommandImageScanFailure) as raised:
        _run_scan(
            tmp_path,
            monkeypatch,
            start_returncode=1,
            container_exit_code=1,
            stderr=b"x" * (_scanner._MAX_DIAGNOSTIC_BYTES + 1),
        )

    diagnostic = raised.value.diagnostic
    assert diagnostic["error_category"] == "diagnostic_output_over_bound"
    assert diagnostic["output_within_bound"] is False
    assert diagnostic["temporary_container_removed"] is True
    assert diagnostic["temporary_workspace_removed"] is True


def test_scan_and_lock_persists_failed_diagnostic_without_writing_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330"
    verifier_id = "sha256:" + "1" * 64
    command_id = "sha256:" + "2" * 64
    unsanitized_id = "sha256:" + "3" * 64
    rg_sha256 = "4" * 64
    archive_sha256 = "5" * 64
    identity = build_hwe_agent_image_lock(
        task_id=task_id,
        task_hash="6" * 64,
        source_hash="7" * 64,
        verifier_base_image_id=verifier_id,
        derived_agent_image_id="sha256:" + "8" * 64,
        host_codex_sha256="9" * 64,
        agent_codex_sha256="a" * 64,
        agent_rg_sha256="b" * 64,
        toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
        allowlisted_artifacts=[
            {"path": "/usr/bin/make", "sha256": "c" * 64, "role": "build_tool"},
            {
                "path": "/tools/verilator/bin/verilator_bin",
                "sha256": "d" * 64,
                "role": "simulator",
            },
        ],
        security_scan_id="e" * 64,
    )
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity.model_dump(mode="json")), encoding="utf-8")
    receipt = {
        "format_id": "verigym_hwe_command_image_build_receipt_v1",
        "task_id": task_id,
        "verifier_base_image_id": verifier_id,
        "derived_command_image_id": command_id,
        "unsanitized_command_image_id": unsanitized_id,
        "rg_version": _scanner._RG_VERSION,
        "rg_source": _scanner._RG_SOURCE,
        "rg_sha256": rg_sha256,
        "rg_release_archive_sha256": archive_sha256,
        "configuration_sanitizer_sha256": "f" * 64,
        "codex_present": False,
        "collection_profile_id": "hwe_standard_v2",
        "tool_contract_id": "hwe_native_shell_v2",
        "command_protocol": "hwe_command_image_v1",
        "source_whiteout_path": "/home/cva6",
        "exact_image_environment": list(_scanner._EXPECTED_IMAGE_ENVIRONMENT),
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    labels = {
        "org.verigym.runtime.role": "hwe-cva6-command",
        "org.verigym.collection.profile": "hwe_standard_v2",
        "org.verigym.tool.contract": "hwe_native_shell_v2",
        "org.verigym.command.protocol": "hwe_command_image_v1",
        "org.verigym.command.rg.version": _scanner._RG_VERSION,
        "org.verigym.command.rg.sha256": rg_sha256,
        "org.verigym.command.rg.release_archive.sha256": archive_sha256,
        "org.verigym.hwe.task_id": task_id,
        "org.verigym.cva6.verifier_base_image_id": verifier_id,
        "org.verigym.codex.present": "absent",
        "org.verigym.provider_credentials": "absent",
        "org.verigym.hidden_assets": "absent",
        "org.verigym.reference_patch": "absent",
        "org.verigym.verifier_payload": "absent",
    }
    image = {
        "Id": command_id,
        "RootFS": {"Layers": ["sha256:" + "0" * 64]},
        "Config": {
            "Env": list(_scanner._EXPECTED_IMAGE_ENVIRONMENT),
            "User": f"{os.getuid()}:{os.getgid()}",
            "Volumes": None,
            "Cmd": ["/usr/bin/tail", "-f", "/dev/null"],
            "Labels": labels,
        },
    }
    monkeypatch.setattr(
        _scanner,
        "_inspect",
        lambda reference: (
            image
            if reference == command_id
            else {"Id": unsanitized_id, "RootFS": image["RootFS"], "Config": {}}
        ),
    )
    diagnostic = _scanner._empty_diagnostic()
    diagnostic.update(
        {
            "status": "failed",
            "failure_stage": "container_diagnostic_start",
            "error_category": "docker_start_failed",
            "exit_code": 125,
            "temporary_container_created": True,
            "temporary_container_removed": True,
            "temporary_workspace_removed": True,
        }
    )
    monkeypatch.setattr(
        _scanner,
        "_container_scan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            _scanner.CommandImageScanFailure(_scanner._seal_diagnostic(diagnostic))
        ),
    )
    security_output = tmp_path / "security.json"
    lock_output = tmp_path / "lock.json"

    with pytest.raises(RuntimeError, match="runtime security scan failed"):
        _scanner.scan_and_lock(
            receipt_path=receipt_path,
            identity_lock_path=identity_path,
            security_output=security_output,
            lock_output=lock_output,
        )

    persisted = json.loads(security_output.read_text(encoding="utf-8"))
    assert persisted["format_id"] == "verigym_hwe_command_image_security_scan_v2"
    assert persisted["scan_passed"] is False
    assert persisted["diagnostic"]["exit_code"] == 125
    assert persisted["diagnostic"]["temporary_container_removed"] is True
    assert not lock_output.exists()
